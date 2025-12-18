"""
Core Web Vitals Collector

Measures Core Web Vitals using Playwright's Performance APIs.

Metrics collected:
- LCP (Largest Contentful Paint): Loading performance
- CLS (Cumulative Layout Shift): Visual stability
- INP (Interaction to Next Paint): Responsiveness (replaces FID)
- FID (First Input Delay): Legacy metric, still collected
- FCP (First Contentful Paint): First paint with content
- TTI (Time to Interactive): Estimated from Long Tasks
- TTFB (Time to First Byte): Server response time

Features:
- Multi-sample measurement (3-5 samples) for accuracy
- Median and p95 value reporting
- Mobile emulation with network throttling
- Desktop and mobile profiles
- Full stealth features (matches SERP scraper tactics)

Technical approach:
- Inject JavaScript PerformanceObserver before navigation
- Collect metrics via browser Performance APIs
- Simulate user interaction for INP/FID measurement
- Calculate TTI from Long Tasks API
- Run multiple samples for statistical reliability

Stealth Features (matching SERP scraper):
- Randomized fingerprints (viewport, timezone, locale)
- Canvas/WebGL/Audio fingerprint randomization
- playwright-stealth integration
- Human-like delays and behavior
- User agent rotation

Usage:
    from seo_intelligence.scrapers.core_web_vitals import CoreWebVitalsCollector

    collector = CoreWebVitalsCollector()

    # Single measurement (fast)
    metrics = collector.measure_url("https://example.com")

    # Multi-sample measurement (more accurate)
    metrics = collector.measure_url_multi_sample(
        "https://example.com",
        samples=5,
        mobile=True
    )

    # Returns:
    # {
    #     "lcp_ms": 2345.67,
    #     "lcp_median": 2300.0,
    #     "lcp_p95": 2800.0,
    #     "cls_value": 0.05,
    #     "inp_ms": 120.0,  # New INP metric
    #     "fid_ms": 45.0,
    #     "fcp_ms": 1234.56,
    #     "tti_ms": 3456.78,
    #     "ttfb_ms": 234.56,
    #     "lcp_element": "img.hero-image",
    #     "lcp_rating": "GOOD",
    #     "cls_rating": "GOOD",
    #     "inp_rating": "GOOD",
    #     "cwv_score": 85.5,
    #     "cwv_assessment": "PASSED",
    #     "samples_collected": 5,
    #     "device_type": "mobile"
    # }
"""

import os
import sys
import time
import json
import random
import statistics
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from playwright_stealth import Stealth

from seo_intelligence.services.cwv_metrics import get_cwv_metrics_service, CWVRating
from seo_intelligence.services import get_user_agent_rotator
from runner.logging_setup import get_logger

# Import YP stealth features for consistent anti-detection
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
try:
    from scrape_yp.yp_stealth import (
        human_delay,
        get_human_reading_delay,
    )
    HAS_YP_STEALTH = True
except ImportError:
    HAS_YP_STEALTH = False
    def human_delay(min_seconds=1.0, max_seconds=3.0, jitter=0.5):
        """Fallback human delay."""
        base = random.uniform(min_seconds, max_seconds)
        actual_jitter = base * random.uniform(-jitter, jitter)
        time.sleep(max(0.1, base + actual_jitter))
    def get_human_reading_delay(content_length):
        """Fallback reading delay."""
        return random.uniform(0.5, 2.0)

logger = get_logger("core_web_vitals")


# JavaScript to inject for CWV measurement (includes INP)
CWV_INJECTION_SCRIPT = """
() => {
    // Initialize CWV storage with INP support
    window.__cwv_metrics = {
        lcp: null,
        cls: 0,
        fid: null,
        inp: null,  // Interaction to Next Paint (replaces FID in CWV)
        fcp: null,
        ttfb: null,
        tti: null,
        lcp_element: null,
        long_tasks: [],
        layout_shifts: [],
        interactions: [],  // For INP calculation
        collected_at: null
    };

    // PerformanceObserver for Largest Contentful Paint
    try {
        const lcpObserver = new PerformanceObserver((entryList) => {
            const entries = entryList.getEntries();
            const lastEntry = entries[entries.length - 1];
            if (lastEntry) {
                window.__cwv_metrics.lcp = lastEntry.startTime;
                // Try to get the element that triggered LCP
                if (lastEntry.element) {
                    const el = lastEntry.element;
                    let selector = el.tagName.toLowerCase();
                    if (el.id) selector += '#' + el.id;
                    if (el.className && typeof el.className === 'string') {
                        selector += '.' + el.className.split(' ').filter(c => c).join('.');
                    }
                    window.__cwv_metrics.lcp_element = selector;
                }
            }
        });
        lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (e) {
        console.warn('LCP observer not supported:', e);
    }

    // PerformanceObserver for Cumulative Layout Shift
    try {
        const clsObserver = new PerformanceObserver((entryList) => {
            for (const entry of entryList.getEntries()) {
                if (!entry.hadRecentInput) {
                    window.__cwv_metrics.cls += entry.value;
                    window.__cwv_metrics.layout_shifts.push({
                        value: entry.value,
                        time: entry.startTime
                    });
                }
            }
        });
        clsObserver.observe({ type: 'layout-shift', buffered: true });
    } catch (e) {
        console.warn('CLS observer not supported:', e);
    }

    // PerformanceObserver for First Input Delay
    try {
        const fidObserver = new PerformanceObserver((entryList) => {
            const firstInput = entryList.getEntries()[0];
            if (firstInput && window.__cwv_metrics.fid === null) {
                window.__cwv_metrics.fid = firstInput.processingStart - firstInput.startTime;
            }
        });
        fidObserver.observe({ type: 'first-input', buffered: true });
    } catch (e) {
        console.warn('FID observer not supported:', e);
    }

    // PerformanceObserver for Long Tasks (for TTI estimation)
    try {
        const longTaskObserver = new PerformanceObserver((entryList) => {
            for (const entry of entryList.getEntries()) {
                window.__cwv_metrics.long_tasks.push({
                    duration: entry.duration,
                    startTime: entry.startTime
                });
            }
        });
        longTaskObserver.observe({ type: 'longtask', buffered: true });
    } catch (e) {
        console.warn('Long Task observer not supported:', e);
    }

    // PerformanceObserver for Interaction to Next Paint (INP)
    // INP replaces FID as a Core Web Vital metric
    try {
        const inpObserver = new PerformanceObserver((entryList) => {
            for (const entry of entryList.getEntries()) {
                // INP considers all interactions, not just the first one
                const interactionDuration = entry.duration;
                window.__cwv_metrics.interactions.push({
                    duration: interactionDuration,
                    startTime: entry.startTime,
                    processingStart: entry.processingStart,
                    processingEnd: entry.processingEnd,
                    interactionId: entry.interactionId,
                    name: entry.name
                });

                // INP is the worst interaction (98th percentile in practice)
                // For simplicity, we track the worst one seen so far
                if (window.__cwv_metrics.inp === null || interactionDuration > window.__cwv_metrics.inp) {
                    window.__cwv_metrics.inp = interactionDuration;
                }
            }
        });
        inpObserver.observe({ type: 'event', buffered: true, durationThreshold: 16 });
    } catch (e) {
        console.warn('INP/Event observer not supported:', e);
    }

    // Get paint timing (FCP)
    try {
        const paintEntries = performance.getEntriesByType('paint');
        for (const entry of paintEntries) {
            if (entry.name === 'first-contentful-paint') {
                window.__cwv_metrics.fcp = entry.startTime;
            }
        }
    } catch (e) {
        console.warn('Paint timing not available:', e);
    }

    // Get navigation timing (TTFB)
    try {
        const navEntries = performance.getEntriesByType('navigation');
        if (navEntries.length > 0) {
            const navEntry = navEntries[0];
            window.__cwv_metrics.ttfb = navEntry.responseStart - navEntry.requestStart;
        }
    } catch (e) {
        console.warn('Navigation timing not available:', e);
    }

    console.log('CWV measurement initialized');
}
"""

# JavaScript to collect final metrics
CWV_COLLECT_SCRIPT = """
() => {
    const metrics = window.__cwv_metrics || {};

    // Final collection timestamp
    metrics.collected_at = Date.now();

    // Get final paint timing if not already collected
    if (!metrics.fcp) {
        try {
            const paintEntries = performance.getEntriesByType('paint');
            for (const entry of paintEntries) {
                if (entry.name === 'first-contentful-paint') {
                    metrics.fcp = entry.startTime;
                }
            }
        } catch (e) {}
    }

    // Get final navigation timing if not already collected
    if (!metrics.ttfb) {
        try {
            const navEntries = performance.getEntriesByType('navigation');
            if (navEntries.length > 0) {
                const navEntry = navEntries[0];
                metrics.ttfb = navEntry.responseStart - navEntry.requestStart;
            }
        } catch (e) {}
    }

    // Estimate TTI from long tasks
    // TTI = FCP + time until no long tasks for 5 seconds
    if (metrics.fcp && metrics.long_tasks.length > 0) {
        const lastLongTask = metrics.long_tasks[metrics.long_tasks.length - 1];
        metrics.tti = lastLongTask.startTime + lastLongTask.duration;
    } else if (metrics.fcp) {
        // No long tasks, TTI is close to FCP
        metrics.tti = metrics.fcp + 100;  // Small buffer
    }

    // Calculate final INP if we have interactions
    // INP should be the 98th percentile of interaction durations
    if (metrics.interactions && metrics.interactions.length > 0) {
        const durations = metrics.interactions.map(i => i.duration).sort((a, b) => a - b);
        const p98Index = Math.floor(durations.length * 0.98);
        metrics.inp = durations[Math.min(p98Index, durations.length - 1)];
    }

    return metrics;
}
"""

# JavaScript to simulate a click for FID measurement
FID_TRIGGER_SCRIPT = """
() => {
    // Find a clickable element to trigger FID measurement
    const clickable = document.querySelector('a, button, input, [onclick]');
    if (clickable) {
        // Create and dispatch a synthetic click event
        const event = new MouseEvent('click', {
            view: window,
            bubbles: true,
            cancelable: true
        });
        clickable.dispatchEvent(event);
        return true;
    }
    return false;
}
"""


@dataclass
class CWVResult:
    """Container for CWV measurement results."""
    url: str
    # Core metrics
    lcp_ms: Optional[float] = None
    cls_value: Optional[float] = None
    inp_ms: Optional[float] = None  # Interaction to Next Paint (replaces FID)
    fid_ms: Optional[float] = None  # Legacy metric, still collected
    fcp_ms: Optional[float] = None
    tti_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None

    # Element info
    lcp_element: Optional[str] = None

    # Ratings
    lcp_rating: Optional[str] = None
    cls_rating: Optional[str] = None
    inp_rating: Optional[str] = None  # INP rating
    fid_rating: Optional[str] = None

    # Scores
    cwv_score: Optional[float] = None
    cwv_assessment: Optional[str] = None

    # Multi-sample statistics (when using measure_url_multi_sample)
    lcp_median: Optional[float] = None
    lcp_p95: Optional[float] = None
    cls_median: Optional[float] = None
    cls_p95: Optional[float] = None
    inp_median: Optional[float] = None
    inp_p95: Optional[float] = None
    fcp_median: Optional[float] = None
    ttfb_median: Optional[float] = None
    samples_collected: Optional[int] = None

    # Device info
    device_type: str = "desktop"  # desktop or mobile

    # Timing
    measurement_time_ms: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


class CoreWebVitalsCollector:
    """
    Collects Core Web Vitals metrics using Playwright.

    Uses browser Performance APIs to measure:
    - LCP via PerformanceObserver
    - CLS via PerformanceObserver
    - FID via PerformanceObserver (with simulated interaction)
    - FCP from paint timing
    - TTI estimated from Long Tasks
    - TTFB from navigation timing

    Stealth Features:
    - User agent rotation (13+ agents)
    - Randomized viewport sizes
    - Randomized timezone/locale
    - playwright-stealth integration
    - Human-like delays between samples
    """

    # Randomized viewports for fingerprint variation (matching SERP stealth)
    VIEWPORT_VARIATIONS = [
        {"width": 1920, "height": 1080},
        {"width": 1536, "height": 864},
        {"width": 1440, "height": 900},
        {"width": 1366, "height": 768},
        {"width": 1280, "height": 720},
    ]

    # Timezone variations
    TIMEZONES = [
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Phoenix",
    ]

    # Locales
    LOCALES = ["en-US", "en-GB", "en-CA"]

    def __init__(
        self,
        headless: bool = True,
        page_timeout: int = 30000,
        cwv_wait_time: float = 5.0,
        use_stealth: bool = True,
    ):
        """
        Initialize CWV collector with stealth features.

        Args:
            headless: Run browser in headless mode
            page_timeout: Page load timeout in milliseconds
            cwv_wait_time: Time to wait for CWV metrics to stabilize (seconds)
            use_stealth: Enable stealth features (user agent rotation, fingerprint randomization)
        """
        self.headless = headless
        self.page_timeout = page_timeout
        self.cwv_wait_time = cwv_wait_time
        self.cwv_service = get_cwv_metrics_service()
        self.use_stealth = use_stealth

        # User agent rotator (same as SERP scraper)
        try:
            self.ua_rotator = get_user_agent_rotator()
        except Exception:
            self.ua_rotator = None

        logger.info(
            f"CoreWebVitalsCollector initialized "
            f"(headless={headless}, wait={cwv_wait_time}s, stealth={use_stealth})"
        )

    def _get_random_user_agent(self, mobile: bool = False) -> str:
        """Get a random user agent string."""
        if self.ua_rotator:
            return self.ua_rotator.get_random_ua(
                device_type="mobile" if mobile else "desktop"
            )
        # Fallback user agents
        if mobile:
            return (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            )
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    def _get_random_viewport(self) -> Dict[str, int]:
        """Get a random viewport size."""
        if self.use_stealth:
            return random.choice(self.VIEWPORT_VARIATIONS)
        return {"width": 1920, "height": 1080}

    def _get_random_timezone(self) -> str:
        """Get a random timezone."""
        if self.use_stealth:
            return random.choice(self.TIMEZONES)
        return "America/New_York"

    def _get_random_locale(self) -> str:
        """Get a random locale."""
        if self.use_stealth:
            return random.choice(self.LOCALES)
        return "en-US"

    def _create_browser_context(
        self,
        browser: Browser,
    ) -> BrowserContext:
        """Create browser context with stealth settings (randomized fingerprints)."""
        # Use randomized stealth settings like SERP scraper
        viewport = self._get_random_viewport()
        locale = self._get_random_locale()
        timezone = self._get_random_timezone()
        user_agent = self._get_random_user_agent(mobile=False)

        context = browser.new_context(
            viewport=viewport,
            locale=locale,
            timezone_id=timezone,
            user_agent=user_agent,
            # Additional stealth settings
            color_scheme=random.choice(["light", "dark"]) if self.use_stealth else "light",
            reduced_motion="reduce" if random.random() < 0.3 and self.use_stealth else "no-preference",
        )
        context.set_default_timeout(self.page_timeout)

        if self.use_stealth:
            logger.debug(
                f"Stealth context: viewport={viewport['width']}x{viewport['height']}, "
                f"locale={locale}, tz={timezone}"
            )

        return context

    def _inject_cwv_observers(self, page: Page) -> None:
        """Inject CWV measurement scripts into the page."""
        page.add_init_script(CWV_INJECTION_SCRIPT)

    def _collect_metrics(self, page: Page) -> Dict[str, Any]:
        """Collect CWV metrics from the page."""
        return page.evaluate(CWV_COLLECT_SCRIPT)

    def _trigger_fid(self, page: Page) -> bool:
        """Trigger a click to measure FID."""
        try:
            return page.evaluate(FID_TRIGGER_SCRIPT)
        except Exception as e:
            logger.debug(f"FID trigger failed: {e}")
            return False

    def measure_url(self, url: str) -> CWVResult:
        """
        Measure Core Web Vitals for a URL.

        Args:
            url: URL to measure

        Returns:
            CWVResult with all metrics and ratings
        """
        start_time = time.time()
        result = CWVResult(url=url)

        try:
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )

                try:
                    # Create context
                    context = self._create_browser_context(browser)

                    # Create page with CWV observers
                    page = context.new_page()

                    # Apply stealth
                    stealth = Stealth()
                    stealth.apply_stealth_sync(page)

                    # Inject CWV measurement observers
                    self._inject_cwv_observers(page)

                    # Navigate to URL
                    logger.debug(f"Navigating to {url}")
                    response = page.goto(url, wait_until="load")

                    if response is None or response.status >= 400:
                        result.error = f"HTTP {response.status if response else 'no response'}"
                        return result

                    # Wait for page to stabilize and CWV to be measured
                    logger.debug(f"Waiting {self.cwv_wait_time}s for CWV metrics")
                    time.sleep(self.cwv_wait_time)

                    # Trigger interaction for FID measurement
                    self._trigger_fid(page)
                    time.sleep(0.5)  # Brief wait for FID to register

                    # Collect all metrics
                    raw_metrics = self._collect_metrics(page)
                    logger.debug(f"Raw metrics: {raw_metrics}")

                    # Extract metrics
                    result.lcp_ms = raw_metrics.get("lcp")
                    result.cls_value = raw_metrics.get("cls", 0)
                    result.inp_ms = raw_metrics.get("inp")  # INP (replaces FID)
                    result.fid_ms = raw_metrics.get("fid")  # Legacy FID
                    result.fcp_ms = raw_metrics.get("fcp")
                    result.tti_ms = raw_metrics.get("tti")
                    result.ttfb_ms = raw_metrics.get("ttfb")
                    result.lcp_element = raw_metrics.get("lcp_element")

                    # Calculate ratings
                    if result.lcp_ms is not None:
                        result.lcp_rating = self.cwv_service.rate_lcp(result.lcp_ms).value

                    if result.cls_value is not None:
                        result.cls_rating = self.cwv_service.rate_cls(result.cls_value).value

                    # INP rating (similar thresholds to FID but typically higher)
                    # Good: <= 200ms, Needs Improvement: <= 500ms, Poor: > 500ms
                    if result.inp_ms is not None:
                        if result.inp_ms <= 200:
                            result.inp_rating = "GOOD"
                        elif result.inp_ms <= 500:
                            result.inp_rating = "NEEDS_IMPROVEMENT"
                        else:
                            result.inp_rating = "POOR"

                    if result.fid_ms is not None:
                        result.fid_rating = self.cwv_service.rate_fid(result.fid_ms).value

                    # Calculate composite score (use INP if available, fallback to FID)
                    responsiveness_metric = result.inp_ms if result.inp_ms is not None else result.fid_ms
                    result.cwv_score = self.cwv_service.calculate_cwv_score(
                        lcp_ms=result.lcp_ms,
                        cls_value=result.cls_value,
                        fid_ms=responsiveness_metric,  # Use INP or FID
                        fcp_ms=result.fcp_ms,
                        tti_ms=result.tti_ms,
                        ttfb_ms=result.ttfb_ms,
                    )

                    # Get assessment (use INP if available, fallback to FID)
                    assessment, _ = self.cwv_service.get_cwv_assessment(
                        lcp_ms=result.lcp_ms,
                        cls_value=result.cls_value,
                        fid_ms=responsiveness_metric,
                    )
                    result.cwv_assessment = assessment

                    # Close page and context
                    page.close()
                    context.close()

                finally:
                    browser.close()

        except Exception as e:
            logger.error(f"Error measuring CWV for {url}: {e}")
            result.error = str(e)

        # Record measurement time
        result.measurement_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"CWV measurement for {url}: "
            f"LCP={result.lcp_ms}ms ({result.lcp_rating}), "
            f"CLS={result.cls_value} ({result.cls_rating}), "
            f"INP={result.inp_ms}ms ({result.inp_rating}), "
            f"FID={result.fid_ms}ms ({result.fid_rating}), "
            f"Score={result.cwv_score}, Assessment={result.cwv_assessment}"
        )

        return result

    def measure_urls(self, urls: List[str]) -> List[CWVResult]:
        """
        Measure Core Web Vitals for multiple URLs.

        Args:
            urls: List of URLs to measure

        Returns:
            List of CWVResult objects
        """
        results = []
        for url in urls:
            result = self.measure_url(url)
            results.append(result)

            # Small delay between measurements
            time.sleep(1.0)

        return results

    def _create_mobile_browser_context(
        self,
        browser: Browser,
    ) -> BrowserContext:
        """Create mobile browser context with stealth settings."""
        # Mobile viewport variations (different device sizes)
        mobile_viewports = [
            {"width": 375, "height": 667, "scale": 2},    # iPhone SE
            {"width": 390, "height": 844, "scale": 3},    # iPhone 12/13
            {"width": 414, "height": 896, "scale": 2},    # iPhone 11
            {"width": 360, "height": 800, "scale": 3},    # Samsung Galaxy
            {"width": 412, "height": 915, "scale": 2.625}, # Pixel 6
        ]

        selected = random.choice(mobile_viewports) if self.use_stealth else mobile_viewports[0]
        user_agent = self._get_random_user_agent(mobile=True)
        timezone = self._get_random_timezone()
        locale = self._get_random_locale()

        context = browser.new_context(
            viewport={"width": selected["width"], "height": selected["height"]},
            device_scale_factor=selected["scale"],
            is_mobile=True,
            has_touch=True,
            locale=locale,
            timezone_id=timezone,
            user_agent=user_agent,
        )
        context.set_default_timeout(self.page_timeout)

        if self.use_stealth:
            logger.debug(
                f"Mobile stealth context: {selected['width']}x{selected['height']}, "
                f"locale={locale}, tz={timezone}"
            )

        return context

    def _measure_single_sample(
        self,
        url: str,
        mobile: bool = False,
    ) -> CWVResult:
        """
        Measure a single sample with optional mobile emulation.

        Args:
            url: URL to measure
            mobile: Whether to use mobile emulation

        Returns:
            CWVResult with metrics
        """
        start_time = time.time()
        result = CWVResult(url=url, device_type="mobile" if mobile else "desktop")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )

                try:
                    # Create appropriate context
                    if mobile:
                        context = self._create_mobile_browser_context(browser)
                    else:
                        context = self._create_browser_context(browser)

                    page = context.new_page()

                    # Apply stealth
                    stealth = Stealth()
                    stealth.apply_stealth_sync(page)

                    # Inject CWV observers
                    self._inject_cwv_observers(page)

                    # Navigate
                    response = page.goto(url, wait_until="load")

                    if response is None or response.status >= 400:
                        result.error = f"HTTP {response.status if response else 'no response'}"
                        return result

                    # Wait for metrics
                    time.sleep(self.cwv_wait_time)

                    # Trigger interaction
                    self._trigger_fid(page)
                    time.sleep(0.5)

                    # Collect metrics
                    raw_metrics = self._collect_metrics(page)

                    result.lcp_ms = raw_metrics.get("lcp")
                    result.cls_value = raw_metrics.get("cls", 0)
                    result.inp_ms = raw_metrics.get("inp")
                    result.fid_ms = raw_metrics.get("fid")
                    result.fcp_ms = raw_metrics.get("fcp")
                    result.tti_ms = raw_metrics.get("tti")
                    result.ttfb_ms = raw_metrics.get("ttfb")
                    result.lcp_element = raw_metrics.get("lcp_element")

                    page.close()
                    context.close()

                finally:
                    browser.close()

        except Exception as e:
            logger.debug(f"Sample measurement error for {url}: {e}")
            result.error = str(e)

        result.measurement_time_ms = (time.time() - start_time) * 1000
        return result

    def measure_url_multi_sample(
        self,
        url: str,
        samples: int = 5,
        mobile: bool = False,
    ) -> CWVResult:
        """
        Measure Core Web Vitals with multiple samples for accuracy.

        Takes multiple measurements and reports median and p95 values.
        This provides more reliable metrics by accounting for variance.

        Args:
            url: URL to measure
            samples: Number of samples to collect (3-5 recommended)
            mobile: Whether to use mobile emulation

        Returns:
            CWVResult with median/p95 statistics
        """
        samples = max(1, min(10, samples))  # Clamp to 1-10

        logger.info(f"Multi-sample CWV measurement for {url} ({samples} samples, mobile={mobile})")
        start_time = time.time()

        # Collect samples
        sample_results: List[CWVResult] = []
        for i in range(samples):
            result = self._measure_single_sample(url, mobile=mobile)
            if not result.error:
                sample_results.append(result)
            else:
                logger.debug(f"Sample {i+1} failed: {result.error}")

            # Human-like delay between samples (matching SERP tactics)
            if i < samples - 1:
                if self.use_stealth and HAS_YP_STEALTH:
                    human_delay(min_seconds=1.5, max_seconds=3.5, jitter=0.3)
                else:
                    time.sleep(random.uniform(1.0, 2.5))

        if not sample_results:
            return CWVResult(
                url=url,
                device_type="mobile" if mobile else "desktop",
                error="All samples failed",
                measurement_time_ms=(time.time() - start_time) * 1000,
            )

        # Calculate statistics
        def calc_median(values: List[float]) -> Optional[float]:
            if not values:
                return None
            return statistics.median(values)

        def calc_p95(values: List[float]) -> Optional[float]:
            if not values:
                return None
            if len(values) < 2:
                return values[0]
            sorted_vals = sorted(values)
            idx = int(len(sorted_vals) * 0.95)
            return sorted_vals[min(idx, len(sorted_vals) - 1)]

        # Extract values (filtering None)
        lcp_values = [r.lcp_ms for r in sample_results if r.lcp_ms is not None]
        cls_values = [r.cls_value for r in sample_results if r.cls_value is not None]
        inp_values = [r.inp_ms for r in sample_results if r.inp_ms is not None]
        fcp_values = [r.fcp_ms for r in sample_results if r.fcp_ms is not None]
        ttfb_values = [r.ttfb_ms for r in sample_results if r.ttfb_ms is not None]

        # Create result with statistics
        result = CWVResult(
            url=url,
            device_type="mobile" if mobile else "desktop",
            samples_collected=len(sample_results),
            measurement_time_ms=(time.time() - start_time) * 1000,
        )

        # LCP
        if lcp_values:
            result.lcp_ms = calc_median(lcp_values)
            result.lcp_median = result.lcp_ms
            result.lcp_p95 = calc_p95(lcp_values)
            if result.lcp_ms is not None:
                result.lcp_rating = self.cwv_service.rate_lcp(result.lcp_ms).value

        # CLS
        if cls_values:
            result.cls_value = calc_median(cls_values)
            result.cls_median = result.cls_value
            result.cls_p95 = calc_p95(cls_values)
            if result.cls_value is not None:
                result.cls_rating = self.cwv_service.rate_cls(result.cls_value).value

        # INP
        if inp_values:
            result.inp_ms = calc_median(inp_values)
            result.inp_median = result.inp_ms
            result.inp_p95 = calc_p95(inp_values)
            if result.inp_ms is not None:
                if result.inp_ms <= 200:
                    result.inp_rating = "GOOD"
                elif result.inp_ms <= 500:
                    result.inp_rating = "NEEDS_IMPROVEMENT"
                else:
                    result.inp_rating = "POOR"

        # FCP
        if fcp_values:
            result.fcp_ms = calc_median(fcp_values)
            result.fcp_median = result.fcp_ms

        # TTFB
        if ttfb_values:
            result.ttfb_ms = calc_median(ttfb_values)
            result.ttfb_median = result.ttfb_ms

        # LCP element (use most common one)
        elements = [r.lcp_element for r in sample_results if r.lcp_element]
        if elements:
            result.lcp_element = max(set(elements), key=elements.count)

        # Calculate composite score using median values
        responsiveness = result.inp_ms if result.inp_ms else result.fid_ms
        result.cwv_score = self.cwv_service.calculate_cwv_score(
            lcp_ms=result.lcp_ms,
            cls_value=result.cls_value,
            fid_ms=responsiveness,
            fcp_ms=result.fcp_ms,
            tti_ms=None,  # Not reliable across samples
            ttfb_ms=result.ttfb_ms,
        )

        # Get assessment
        assessment, _ = self.cwv_service.get_cwv_assessment(
            lcp_ms=result.lcp_ms,
            cls_value=result.cls_value,
            fid_ms=responsiveness,
        )
        result.cwv_assessment = assessment

        logger.info(
            f"Multi-sample CWV for {url} ({len(sample_results)}/{samples} samples): "
            f"LCP={result.lcp_ms}ms (p95={result.lcp_p95}ms), "
            f"CLS={result.cls_value} (p95={result.cls_p95}), "
            f"INP={result.inp_ms}ms (p95={result.inp_p95}ms), "
            f"Score={result.cwv_score}, Device={result.device_type}"
        )

        return result


# Module-level singleton
_cwv_collector_instance = None


def get_cwv_collector(**kwargs) -> CoreWebVitalsCollector:
    """Get or create the singleton CoreWebVitalsCollector instance."""
    global _cwv_collector_instance

    if _cwv_collector_instance is None:
        _cwv_collector_instance = CoreWebVitalsCollector(**kwargs)

    return _cwv_collector_instance


def main():
    """Demo/CLI interface for CWV collector."""
    import argparse

    parser = argparse.ArgumentParser(description="Core Web Vitals Collector")
    parser.add_argument("--url", "-u", help="URL to measure")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")
    parser.add_argument("--headed", action="store_true", help="Run in headed mode")
    parser.add_argument("--wait", type=float, default=5.0, help="CWV wait time (seconds)")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("Core Web Vitals Collector Demo Mode")
        logger.info("=" * 60)
        logger.info("")
        logger.info("This measures Core Web Vitals using Playwright Performance APIs:")
        logger.info("  - LCP (Largest Contentful Paint)")
        logger.info("  - CLS (Cumulative Layout Shift)")
        logger.info("  - FID (First Input Delay)")
        logger.info("  - FCP (First Contentful Paint)")
        logger.info("  - TTI (Time to Interactive)")
        logger.info("  - TTFB (Time to First Byte)")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python core_web_vitals.py --url 'https://example.com'")
        logger.info("")
        logger.info("=" * 60)
        return

    if not args.url:
        parser.print_help()
        return

    collector = CoreWebVitalsCollector(
        headless=not args.headed,
        cwv_wait_time=args.wait,
    )

    result = collector.measure_url(args.url)

    print("\n" + "=" * 60)
    print(f"Core Web Vitals for: {args.url}")
    print("=" * 60)
    print(f"  LCP: {result.lcp_ms:.2f}ms ({result.lcp_rating})" if result.lcp_ms else "  LCP: Not measured")
    print(f"  CLS: {result.cls_value:.4f} ({result.cls_rating})" if result.cls_value is not None else "  CLS: Not measured")
    print(f"  FID: {result.fid_ms:.2f}ms ({result.fid_rating})" if result.fid_ms else "  FID: Not measured")
    print(f"  FCP: {result.fcp_ms:.2f}ms" if result.fcp_ms else "  FCP: Not measured")
    print(f"  TTI: {result.tti_ms:.2f}ms" if result.tti_ms else "  TTI: Not measured")
    print(f"  TTFB: {result.ttfb_ms:.2f}ms" if result.ttfb_ms else "  TTFB: Not measured")
    print("-" * 60)
    print(f"  CWV Score: {result.cwv_score:.1f}/100")
    print(f"  Assessment: {result.cwv_assessment}")
    if result.lcp_element:
        print(f"  LCP Element: {result.lcp_element}")
    if result.error:
        print(f"  Error: {result.error}")
    print("=" * 60)


if __name__ == "__main__":
    main()
