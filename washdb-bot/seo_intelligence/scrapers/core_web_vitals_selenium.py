"""
Core Web Vitals Collector (Selenium Version)

Uses SeleniumBase Undetected Chrome for better anti-detection.
Measures Core Web Vitals using browser Performance APIs.

This is the SeleniumBase equivalent of core_web_vitals.py.
"""

import os
import time
import random
import statistics
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urlparse
from dataclasses import dataclass, field

from dotenv import load_dotenv

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper
from seo_intelligence.services.cwv_metrics import get_cwv_metrics_service, CWVRating
from runner.logging_setup import get_logger

load_dotenv()

logger = get_logger("core_web_vitals_selenium")


# Default mobile viewport (iPhone X)
MOBILE_VIEWPORT = {"width": 375, "height": 812}


# JavaScript to inject for CWV measurement
CWV_INJECTION_SCRIPT = """
// Initialize CWV storage with INP support
window.__cwv_metrics = {
    lcp: null,
    cls: 0,
    fid: null,
    inp: null,
    fcp: null,
    ttfb: null,
    tti: null,
    lcp_element: null,
    long_tasks: [],
    layout_shifts: [],
    interactions: [],
    collected_at: null
};

// LCP Observer
try {
    const lcpObserver = new PerformanceObserver((entryList) => {
        const entries = entryList.getEntries();
        const lastEntry = entries[entries.length - 1];
        if (lastEntry) {
            window.__cwv_metrics.lcp = lastEntry.startTime;
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
} catch (e) {}

// CLS Observer
try {
    const clsObserver = new PerformanceObserver((entryList) => {
        for (const entry of entryList.getEntries()) {
            if (!entry.hadRecentInput) {
                window.__cwv_metrics.cls += entry.value;
            }
        }
    });
    clsObserver.observe({ type: 'layout-shift', buffered: true });
} catch (e) {}

// FID Observer
try {
    const fidObserver = new PerformanceObserver((entryList) => {
        const firstInput = entryList.getEntries()[0];
        if (firstInput && window.__cwv_metrics.fid === null) {
            window.__cwv_metrics.fid = firstInput.processingStart - firstInput.startTime;
        }
    });
    fidObserver.observe({ type: 'first-input', buffered: true });
} catch (e) {}

// Long Tasks Observer (for TTI)
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
} catch (e) {}

// INP Observer
try {
    const inpObserver = new PerformanceObserver((entryList) => {
        for (const entry of entryList.getEntries()) {
            const interactionDuration = entry.duration;
            window.__cwv_metrics.interactions.push({
                duration: interactionDuration,
                startTime: entry.startTime
            });
            if (window.__cwv_metrics.inp === null || interactionDuration > window.__cwv_metrics.inp) {
                window.__cwv_metrics.inp = interactionDuration;
            }
        }
    });
    inpObserver.observe({ type: 'event', buffered: true, durationThreshold: 16 });
} catch (e) {}

// Paint timing (FCP)
try {
    const paintEntries = performance.getEntriesByType('paint');
    for (const entry of paintEntries) {
        if (entry.name === 'first-contentful-paint') {
            window.__cwv_metrics.fcp = entry.startTime;
        }
    }
} catch (e) {}

// Navigation timing (TTFB)
try {
    const navEntries = performance.getEntriesByType('navigation');
    if (navEntries.length > 0) {
        const navEntry = navEntries[0];
        window.__cwv_metrics.ttfb = navEntry.responseStart - navEntry.requestStart;
    }
} catch (e) {}
"""

# JavaScript to collect final metrics
CWV_COLLECT_SCRIPT = """
return (function() {
    const metrics = window.__cwv_metrics || {};
    metrics.collected_at = Date.now();

    // Get final FCP if not collected
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

    // Get final TTFB if not collected
    if (!metrics.ttfb) {
        try {
            const navEntries = performance.getEntriesByType('navigation');
            if (navEntries.length > 0) {
                const navEntry = navEntries[0];
                metrics.ttfb = navEntry.responseStart - navEntry.requestStart;
            }
        } catch (e) {}
    }

    // Estimate TTI
    if (metrics.fcp && metrics.long_tasks.length > 0) {
        const lastLongTask = metrics.long_tasks[metrics.long_tasks.length - 1];
        metrics.tti = lastLongTask.startTime + lastLongTask.duration;
    } else if (metrics.fcp) {
        metrics.tti = metrics.fcp + 100;
    }

    // Calculate final INP
    if (metrics.interactions && metrics.interactions.length > 0) {
        const durations = metrics.interactions.map(i => i.duration).sort((a, b) => a - b);
        const p98Index = Math.floor(durations.length * 0.98);
        metrics.inp = durations[Math.min(p98Index, durations.length - 1)];
    }

    return metrics;
})();
"""

# JavaScript to trigger FID
FID_TRIGGER_SCRIPT = """
return (function() {
    const clickable = document.querySelector('a, button, input, [onclick]');
    if (clickable) {
        const event = new MouseEvent('click', {
            view: window,
            bubbles: true,
            cancelable: true
        });
        clickable.dispatchEvent(event);
        return true;
    }
    return false;
})();
"""

# JavaScript to collect detailed resource timing breakdown
RESOURCE_TIMING_SCRIPT = """
return (function() {
    const result = {
        navigation_timing: {},
        resource_timing: {
            by_type: {},
            by_origin: {},
            render_blocking: [],
            total_resources: 0,
            total_size_bytes: 0,
            total_duration_ms: 0
        },
        third_party: {
            domains: [],
            total_count: 0,
            total_duration_ms: 0,
            blocking_scripts: []
        }
    };

    // Navigation timing (DNS, TCP, SSL, etc.)
    try {
        const navEntries = performance.getEntriesByType('navigation');
        if (navEntries.length > 0) {
            const nav = navEntries[0];
            result.navigation_timing = {
                dns_lookup_ms: nav.domainLookupEnd - nav.domainLookupStart,
                tcp_connect_ms: nav.connectEnd - nav.connectStart,
                ssl_handshake_ms: nav.secureConnectionStart > 0 ?
                    nav.connectEnd - nav.secureConnectionStart : 0,
                request_time_ms: nav.responseStart - nav.requestStart,
                response_time_ms: nav.responseEnd - nav.responseStart,
                dom_interactive_ms: nav.domInteractive - nav.fetchStart,
                dom_content_loaded_ms: nav.domContentLoadedEventEnd - nav.fetchStart,
                dom_complete_ms: nav.domComplete - nav.fetchStart,
                load_event_ms: nav.loadEventEnd - nav.fetchStart,
                redirect_time_ms: nav.redirectEnd - nav.redirectStart,
                redirect_count: nav.redirectCount || 0,
                transfer_size_bytes: nav.transferSize || 0,
                encoded_body_size: nav.encodedBodySize || 0,
                decoded_body_size: nav.decodedBodySize || 0
            };
        }
    } catch (e) {}

    // Resource timing
    try {
        const resources = performance.getEntriesByType('resource');
        const pageOrigin = window.location.origin;
        const byType = {};
        const byOrigin = {};
        const thirdPartyDomains = new Set();
        const blockingScripts = [];

        for (const res of resources) {
            // Track by initiator type (script, link, img, etc.)
            const type = res.initiatorType || 'other';
            if (!byType[type]) {
                byType[type] = {
                    count: 0,
                    total_duration_ms: 0,
                    total_size_bytes: 0,
                    resources: []
                };
            }
            byType[type].count++;
            byType[type].total_duration_ms += res.duration || 0;
            byType[type].total_size_bytes += res.transferSize || 0;

            // Track top 5 slowest resources per type
            if (byType[type].resources.length < 5) {
                byType[type].resources.push({
                    url: res.name.substring(0, 100),
                    duration_ms: Math.round(res.duration || 0),
                    size_bytes: res.transferSize || 0
                });
                byType[type].resources.sort((a, b) => b.duration_ms - a.duration_ms);
            } else if (res.duration > byType[type].resources[4].duration_ms) {
                byType[type].resources[4] = {
                    url: res.name.substring(0, 100),
                    duration_ms: Math.round(res.duration || 0),
                    size_bytes: res.transferSize || 0
                };
                byType[type].resources.sort((a, b) => b.duration_ms - a.duration_ms);
            }

            // Track by origin
            try {
                const url = new URL(res.name);
                const origin = url.origin;
                if (!byOrigin[origin]) {
                    byOrigin[origin] = {
                        count: 0,
                        total_duration_ms: 0,
                        total_size_bytes: 0,
                        is_third_party: origin !== pageOrigin
                    };
                }
                byOrigin[origin].count++;
                byOrigin[origin].total_duration_ms += res.duration || 0;
                byOrigin[origin].total_size_bytes += res.transferSize || 0;

                // Track third-party domains
                if (origin !== pageOrigin) {
                    thirdPartyDomains.add(url.hostname);

                    // Track blocking third-party scripts
                    if (type === 'script' && res.renderBlockingStatus === 'blocking') {
                        blockingScripts.push({
                            url: res.name.substring(0, 100),
                            domain: url.hostname,
                            duration_ms: Math.round(res.duration || 0)
                        });
                    }
                }
            } catch (e) {}

            // Detect render-blocking resources
            if (res.renderBlockingStatus === 'blocking') {
                result.resource_timing.render_blocking.push({
                    url: res.name.substring(0, 100),
                    type: type,
                    duration_ms: Math.round(res.duration || 0)
                });
            }

            // Totals
            result.resource_timing.total_resources++;
            result.resource_timing.total_size_bytes += res.transferSize || 0;
            result.resource_timing.total_duration_ms += res.duration || 0;
        }

        // Convert to arrays for JSON
        result.resource_timing.by_type = byType;

        // Top 10 origins by duration
        const originEntries = Object.entries(byOrigin)
            .sort((a, b) => b[1].total_duration_ms - a[1].total_duration_ms)
            .slice(0, 10);
        result.resource_timing.by_origin = Object.fromEntries(originEntries);

        // Third-party summary
        result.third_party.domains = Array.from(thirdPartyDomains).slice(0, 20);
        result.third_party.total_count = thirdPartyDomains.size;
        result.third_party.blocking_scripts = blockingScripts.slice(0, 10);

        // Calculate third-party total duration
        for (const [origin, data] of Object.entries(byOrigin)) {
            if (data.is_third_party) {
                result.third_party.total_duration_ms += data.total_duration_ms;
            }
        }

    } catch (e) {}

    // Round numbers for cleaner output
    result.resource_timing.total_duration_ms = Math.round(result.resource_timing.total_duration_ms);
    result.third_party.total_duration_ms = Math.round(result.third_party.total_duration_ms);

    return result;
})();
"""


@dataclass
class MobileDesktopComparison:
    """
    Comparison of CWV metrics between desktop and mobile measurements.

    This provides insights into how a page performs differently on mobile
    vs desktop, helping identify mobile-specific performance issues.
    """
    url: str
    desktop_result: Optional['CWVResult'] = None
    mobile_result: Optional['CWVResult'] = None

    # Delta values (mobile - desktop, positive = mobile is slower/worse)
    lcp_delta_ms: Optional[float] = None
    cls_delta: Optional[float] = None
    inp_delta_ms: Optional[float] = None
    fcp_delta_ms: Optional[float] = None
    ttfb_delta_ms: Optional[float] = None
    tbt_delta_ms: Optional[float] = None

    # Percentage differences
    lcp_pct_change: Optional[float] = None
    cls_pct_change: Optional[float] = None
    tbt_pct_change: Optional[float] = None

    # Score comparisons
    desktop_score: Optional[float] = None
    mobile_score: Optional[float] = None
    score_delta: Optional[float] = None

    # Rating comparisons
    desktop_grade: Optional[str] = None
    mobile_grade: Optional[str] = None

    # Resource differences
    desktop_resource_count: Optional[int] = None
    mobile_resource_count: Optional[int] = None
    desktop_page_size_bytes: Optional[int] = None
    mobile_page_size_bytes: Optional[int] = None

    # Analysis
    mobile_penalty_detected: bool = False  # True if mobile significantly worse
    mobile_issues: List[str] = None  # List of identified mobile-specific issues
    recommendations: List[str] = None  # Mobile optimization recommendations

    measurement_time_ms: Optional[float] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.mobile_issues is None:
            self.mobile_issues = []
        if self.recommendations is None:
            self.recommendations = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'url': self.url,
            'desktop_result': self.desktop_result.to_dict() if self.desktop_result else None,
            'mobile_result': self.mobile_result.to_dict() if self.mobile_result else None,
            'lcp_delta_ms': self.lcp_delta_ms,
            'cls_delta': self.cls_delta,
            'inp_delta_ms': self.inp_delta_ms,
            'fcp_delta_ms': self.fcp_delta_ms,
            'ttfb_delta_ms': self.ttfb_delta_ms,
            'tbt_delta_ms': self.tbt_delta_ms,
            'lcp_pct_change': self.lcp_pct_change,
            'cls_pct_change': self.cls_pct_change,
            'tbt_pct_change': self.tbt_pct_change,
            'desktop_score': self.desktop_score,
            'mobile_score': self.mobile_score,
            'score_delta': self.score_delta,
            'desktop_grade': self.desktop_grade,
            'mobile_grade': self.mobile_grade,
            'desktop_resource_count': self.desktop_resource_count,
            'mobile_resource_count': self.mobile_resource_count,
            'desktop_page_size_bytes': self.desktop_page_size_bytes,
            'mobile_page_size_bytes': self.mobile_page_size_bytes,
            'mobile_penalty_detected': self.mobile_penalty_detected,
            'mobile_issues': self.mobile_issues,
            'recommendations': self.recommendations,
            'measurement_time_ms': self.measurement_time_ms,
            'error': self.error,
        }


@dataclass
class CWVResult:
    """Container for CWV measurement results."""
    url: str
    lcp_ms: Optional[float] = None
    cls_value: Optional[float] = None
    inp_ms: Optional[float] = None
    fid_ms: Optional[float] = None
    fcp_ms: Optional[float] = None
    tti_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None
    tbt_ms: Optional[float] = None  # Total Blocking Time
    lcp_element: Optional[str] = None
    lcp_rating: Optional[str] = None
    cls_rating: Optional[str] = None
    inp_rating: Optional[str] = None
    fid_rating: Optional[str] = None
    tbt_rating: Optional[str] = None  # TBT rating
    cwv_score: Optional[float] = None
    cwv_assessment: Optional[str] = None
    lcp_median: Optional[float] = None
    lcp_p95: Optional[float] = None
    cls_median: Optional[float] = None
    cls_p95: Optional[float] = None
    inp_median: Optional[float] = None
    inp_p95: Optional[float] = None
    fcp_median: Optional[float] = None
    ttfb_median: Optional[float] = None
    tbt_median: Optional[float] = None  # TBT median for multi-sample
    long_task_count: Optional[int] = None  # Number of long tasks
    long_task_total_ms: Optional[float] = None  # Total long task duration
    samples_collected: Optional[int] = None
    device_type: str = "desktop"
    measurement_time_ms: Optional[float] = None
    error: Optional[str] = None
    grade: Optional[str] = None

    # Resource timing breakdown (Phase 2.2)
    dns_lookup_ms: Optional[float] = None
    tcp_connect_ms: Optional[float] = None
    ssl_handshake_ms: Optional[float] = None
    request_time_ms: Optional[float] = None
    response_time_ms: Optional[float] = None
    dom_interactive_ms: Optional[float] = None
    dom_content_loaded_ms: Optional[float] = None
    dom_complete_ms: Optional[float] = None
    load_event_ms: Optional[float] = None
    redirect_time_ms: Optional[float] = None
    redirect_count: Optional[int] = None

    # Page size metrics
    page_transfer_size_bytes: Optional[int] = None
    page_encoded_size_bytes: Optional[int] = None
    page_decoded_size_bytes: Optional[int] = None

    # Resource counts and timing by type
    total_resources: Optional[int] = None
    total_resources_size_bytes: Optional[int] = None
    total_resources_duration_ms: Optional[float] = None
    resources_by_type: Optional[Dict[str, Any]] = None  # {script: {count, size, duration}, img: {...}, ...}

    # Render-blocking resources
    render_blocking_count: Optional[int] = None
    render_blocking_resources: Optional[List[Dict]] = None  # [{url, type, duration_ms}, ...]

    # Third-party analysis
    third_party_domain_count: Optional[int] = None
    third_party_domains: Optional[List[str]] = None
    third_party_duration_ms: Optional[float] = None
    third_party_blocking_scripts: Optional[List[Dict]] = None  # [{url, domain, duration_ms}, ...]

    # Resource origin breakdown
    resources_by_origin: Optional[Dict[str, Any]] = None  # {origin: {count, duration, size, is_third_party}, ...}

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class CoreWebVitalsSelenium(BaseSeleniumScraper):
    """
    Core Web Vitals collector using SeleniumBase Undetected Chrome.

    Better anti-detection than Playwright version.
    """

    def __init__(
        self,
        headless: bool = False,  # Non-headless by default for better stealth
        use_proxy: bool = True,
        tier: str = "C",
        cwv_wait_time: float = 5.0,
        mobile_mode: bool = False,
        database_url: Optional[str] = None,
    ):
        super().__init__(
            name="core_web_vitals_selenium",
            tier=tier,
            headless=headless,
            respect_robots=False,
            use_proxy=use_proxy,
            max_retries=2,
            page_timeout=30,
            mobile_mode=mobile_mode,
        )

        self.cwv_wait_time = cwv_wait_time
        self.cwv_service = get_cwv_metrics_service()
        self._mobile_mode = mobile_mode

        # Database connection
        database_url = database_url or os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None

        mode_str = "mobile" if mobile_mode else "desktop"
        logger.info(f"CoreWebVitalsSelenium initialized (tier={tier}, {mode_str}, UC mode)")

    def _inject_cwv_observers(self, driver):
        """Inject CWV measurement scripts into the page."""
        try:
            driver.execute_script(CWV_INJECTION_SCRIPT)
        except Exception as e:
            logger.debug(f"Failed to inject CWV observers: {e}")

    def _collect_metrics(self, driver) -> Dict[str, Any]:
        """Collect CWV metrics from the page."""
        try:
            return driver.execute_script(CWV_COLLECT_SCRIPT) or {}
        except Exception as e:
            logger.debug(f"Failed to collect metrics: {e}")
            return {}

    def _trigger_fid(self, driver) -> bool:
        """Trigger a click to measure FID."""
        try:
            return driver.execute_script(FID_TRIGGER_SCRIPT) or False
        except Exception as e:
            logger.debug(f"FID trigger failed: {e}")
            return False

    def _collect_resource_timing(self, driver) -> Dict[str, Any]:
        """
        Collect detailed resource timing breakdown.

        Returns comprehensive timing data including:
        - Navigation timing (DNS, TCP, SSL, request/response)
        - Resource timing by type and origin
        - Third-party analysis
        - Render-blocking resource detection
        """
        try:
            return driver.execute_script(RESOURCE_TIMING_SCRIPT) or {}
        except Exception as e:
            logger.debug(f"Failed to collect resource timing: {e}")
            return {}

    def _calculate_grade(self, cwv_score: Optional[float]) -> str:
        """Calculate letter grade from CWV score."""
        if cwv_score is None:
            return "N/A"
        if cwv_score >= 90:
            return "A"
        elif cwv_score >= 80:
            return "B"
        elif cwv_score >= 70:
            return "C"
        elif cwv_score >= 60:
            return "D"
        else:
            return "F"

    def _calculate_tbt(self, long_tasks: List[Dict[str, float]]) -> Dict[str, Any]:
        """
        Calculate Total Blocking Time (TBT) from long tasks.

        TBT is the sum of the "blocking time" for each long task.
        Blocking time = max(0, task_duration - 50ms)

        A long task is any task that takes >50ms.

        Args:
            long_tasks: List of long tasks with 'duration' and 'startTime' keys

        Returns:
            Dict with tbt_ms, long_task_count, long_task_total_ms, tbt_rating
        """
        if not long_tasks:
            return {
                'tbt_ms': 0.0,
                'long_task_count': 0,
                'long_task_total_ms': 0.0,
                'tbt_rating': 'GOOD',
            }

        # Calculate TBT: sum of blocking time (duration - 50ms threshold)
        tbt_ms = 0.0
        total_long_task_ms = 0.0

        for task in long_tasks:
            duration = task.get('duration', 0)
            if duration > 50:  # Only count tasks > 50ms
                blocking_time = duration - 50  # Blocking portion
                tbt_ms += blocking_time
                total_long_task_ms += duration

        # Determine TBT rating based on Google's thresholds
        # GOOD: ≤200ms, NEEDS_IMPROVEMENT: ≤600ms, POOR: >600ms
        if tbt_ms <= 200:
            rating = 'GOOD'
        elif tbt_ms <= 600:
            rating = 'NEEDS_IMPROVEMENT'
        else:
            rating = 'POOR'

        return {
            'tbt_ms': round(tbt_ms, 2),
            'long_task_count': len(long_tasks),
            'long_task_total_ms': round(total_long_task_ms, 2),
            'tbt_rating': rating,
        }

    def measure_url(self, url: str, samples: int = 1) -> CWVResult:
        """
        Measure Core Web Vitals for a URL.

        Args:
            url: URL to measure
            samples: Number of samples (1 for single measurement)

        Returns:
            CWVResult with all metrics and ratings
        """
        if samples > 1:
            return self._measure_multi_sample(url, samples)

        start_time = time.time()
        result = CWVResult(url=url)

        try:
            with self.browser_session("generic") as driver:
                # Navigate to URL
                logger.debug(f"Navigating to {url}")
                driver.get(url)

                # Inject CWV observers
                self._inject_cwv_observers(driver)

                # Wait for page to stabilize
                time.sleep(self.cwv_wait_time)

                # Trigger interaction for FID
                self._trigger_fid(driver)
                time.sleep(0.5)

                # Human-like scrolling
                self._human_scroll(driver, "down", random.randint(200, 400))
                time.sleep(random.uniform(0.5, 1.0))

                # Collect metrics
                raw_metrics = self._collect_metrics(driver)
                logger.debug(f"Raw metrics: {raw_metrics}")

                # Extract metrics
                result.lcp_ms = raw_metrics.get("lcp")
                result.cls_value = raw_metrics.get("cls", 0)
                result.inp_ms = raw_metrics.get("inp")
                result.fid_ms = raw_metrics.get("fid")
                result.fcp_ms = raw_metrics.get("fcp")
                result.tti_ms = raw_metrics.get("tti")
                result.ttfb_ms = raw_metrics.get("ttfb")
                result.lcp_element = raw_metrics.get("lcp_element")

                # Calculate TBT from long tasks
                long_tasks = raw_metrics.get("long_tasks", [])
                tbt_data = self._calculate_tbt(long_tasks)
                result.tbt_ms = tbt_data['tbt_ms']
                result.tbt_rating = tbt_data['tbt_rating']
                result.long_task_count = tbt_data['long_task_count']
                result.long_task_total_ms = tbt_data['long_task_total_ms']

                # Collect resource timing breakdown (Phase 2.2)
                resource_timing = self._collect_resource_timing(driver)
                if resource_timing:
                    # Navigation timing
                    nav_timing = resource_timing.get('navigation_timing', {})
                    if nav_timing:
                        result.dns_lookup_ms = nav_timing.get('dns_lookup_ms')
                        result.tcp_connect_ms = nav_timing.get('tcp_connect_ms')
                        result.ssl_handshake_ms = nav_timing.get('ssl_handshake_ms')
                        result.request_time_ms = nav_timing.get('request_time_ms')
                        result.response_time_ms = nav_timing.get('response_time_ms')
                        result.dom_interactive_ms = nav_timing.get('dom_interactive_ms')
                        result.dom_content_loaded_ms = nav_timing.get('dom_content_loaded_ms')
                        result.dom_complete_ms = nav_timing.get('dom_complete_ms')
                        result.load_event_ms = nav_timing.get('load_event_ms')
                        result.redirect_time_ms = nav_timing.get('redirect_time_ms')
                        result.redirect_count = nav_timing.get('redirect_count')
                        result.page_transfer_size_bytes = nav_timing.get('transfer_size_bytes')
                        result.page_encoded_size_bytes = nav_timing.get('encoded_body_size')
                        result.page_decoded_size_bytes = nav_timing.get('decoded_body_size')

                    # Resource timing summary
                    res_timing = resource_timing.get('resource_timing', {})
                    if res_timing:
                        result.total_resources = res_timing.get('total_resources')
                        result.total_resources_size_bytes = res_timing.get('total_size_bytes')
                        result.total_resources_duration_ms = res_timing.get('total_duration_ms')
                        result.resources_by_type = res_timing.get('by_type')
                        result.resources_by_origin = res_timing.get('by_origin')

                        # Render-blocking resources
                        render_blocking = res_timing.get('render_blocking', [])
                        result.render_blocking_count = len(render_blocking)
                        result.render_blocking_resources = render_blocking[:10] if render_blocking else None

                    # Third-party analysis
                    third_party = resource_timing.get('third_party', {})
                    if third_party:
                        result.third_party_domain_count = third_party.get('total_count')
                        result.third_party_domains = third_party.get('domains')
                        result.third_party_duration_ms = third_party.get('total_duration_ms')
                        result.third_party_blocking_scripts = third_party.get('blocking_scripts')

                    logger.debug(
                        f"Resource timing: {result.total_resources} resources, "
                        f"{result.render_blocking_count} render-blocking, "
                        f"{result.third_party_domain_count} third-party domains"
                    )

                # Calculate ratings
                if result.lcp_ms is not None:
                    result.lcp_rating = self.cwv_service.rate_lcp(result.lcp_ms).value

                if result.cls_value is not None:
                    result.cls_rating = self.cwv_service.rate_cls(result.cls_value).value

                # INP rating
                if result.inp_ms is not None:
                    if result.inp_ms <= 200:
                        result.inp_rating = "GOOD"
                    elif result.inp_ms <= 500:
                        result.inp_rating = "NEEDS_IMPROVEMENT"
                    else:
                        result.inp_rating = "POOR"

                if result.fid_ms is not None:
                    result.fid_rating = self.cwv_service.rate_fid(result.fid_ms).value

                # Calculate composite score
                responsiveness = result.inp_ms if result.inp_ms is not None else result.fid_ms
                result.cwv_score = self.cwv_service.calculate_cwv_score(
                    lcp_ms=result.lcp_ms,
                    cls_value=result.cls_value,
                    fid_ms=responsiveness,
                    fcp_ms=result.fcp_ms,
                    tti_ms=result.tti_ms,
                    ttfb_ms=result.ttfb_ms,
                )

                # Get assessment
                assessment, _ = self.cwv_service.get_cwv_assessment(
                    lcp_ms=result.lcp_ms,
                    cls_value=result.cls_value,
                    fid_ms=responsiveness,
                )
                result.cwv_assessment = assessment
                result.grade = self._calculate_grade(result.cwv_score)

        except Exception as e:
            logger.error(f"Error measuring CWV for {url}: {e}")
            result.error = str(e)

        result.measurement_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"CWV measurement for {url}: "
            f"LCP={result.lcp_ms}ms ({result.lcp_rating}), "
            f"CLS={result.cls_value} ({result.cls_rating}), "
            f"TBT={result.tbt_ms}ms ({result.tbt_rating}), "
            f"Score={result.cwv_score}, Grade={result.grade}"
        )

        return result

    def _measure_multi_sample(self, url: str, samples: int = 3) -> CWVResult:
        """Measure with multiple samples for accuracy."""
        samples = max(1, min(10, samples))
        logger.info(f"Multi-sample CWV for {url} ({samples} samples)")
        start_time = time.time()

        sample_results = []
        for i in range(samples):
            single_result = self.measure_url(url, samples=1)
            if not single_result.error:
                sample_results.append(single_result)

            if i < samples - 1:
                time.sleep(random.uniform(1.5, 3.0))

        if not sample_results:
            return CWVResult(
                url=url,
                error="All samples failed",
                measurement_time_ms=(time.time() - start_time) * 1000,
            )

        # Calculate statistics
        def calc_median(values):
            return statistics.median(values) if values else None

        def calc_p95(values):
            if not values:
                return None
            if len(values) < 2:
                return values[0]
            sorted_vals = sorted(values)
            idx = int(len(sorted_vals) * 0.95)
            return sorted_vals[min(idx, len(sorted_vals) - 1)]

        lcp_values = [r.lcp_ms for r in sample_results if r.lcp_ms is not None]
        cls_values = [r.cls_value for r in sample_results if r.cls_value is not None]
        inp_values = [r.inp_ms for r in sample_results if r.inp_ms is not None]
        fcp_values = [r.fcp_ms for r in sample_results if r.fcp_ms is not None]
        ttfb_values = [r.ttfb_ms for r in sample_results if r.ttfb_ms is not None]
        tbt_values = [r.tbt_ms for r in sample_results if r.tbt_ms is not None]
        long_task_counts = [r.long_task_count for r in sample_results if r.long_task_count is not None]
        long_task_totals = [r.long_task_total_ms for r in sample_results if r.long_task_total_ms is not None]

        result = CWVResult(
            url=url,
            samples_collected=len(sample_results),
            measurement_time_ms=(time.time() - start_time) * 1000,
        )

        if lcp_values:
            result.lcp_ms = calc_median(lcp_values)
            result.lcp_median = result.lcp_ms
            result.lcp_p95 = calc_p95(lcp_values)
            if result.lcp_ms:
                result.lcp_rating = self.cwv_service.rate_lcp(result.lcp_ms).value

        if cls_values:
            result.cls_value = calc_median(cls_values)
            result.cls_median = result.cls_value
            result.cls_p95 = calc_p95(cls_values)
            if result.cls_value is not None:
                result.cls_rating = self.cwv_service.rate_cls(result.cls_value).value

        if inp_values:
            result.inp_ms = calc_median(inp_values)
            result.inp_median = result.inp_ms
            result.inp_p95 = calc_p95(inp_values)

        if fcp_values:
            result.fcp_ms = calc_median(fcp_values)
            result.fcp_median = result.fcp_ms

        if ttfb_values:
            result.ttfb_ms = calc_median(ttfb_values)
            result.ttfb_median = result.ttfb_ms

        # TBT statistics
        if tbt_values:
            result.tbt_ms = calc_median(tbt_values)
            result.tbt_median = result.tbt_ms
            # Determine TBT rating based on median
            if result.tbt_ms <= 200:
                result.tbt_rating = 'GOOD'
            elif result.tbt_ms <= 600:
                result.tbt_rating = 'NEEDS_IMPROVEMENT'
            else:
                result.tbt_rating = 'POOR'

        if long_task_counts:
            result.long_task_count = int(calc_median(long_task_counts))

        if long_task_totals:
            result.long_task_total_ms = calc_median(long_task_totals)

        # Calculate composite score
        responsiveness = result.inp_ms or result.fid_ms
        result.cwv_score = self.cwv_service.calculate_cwv_score(
            lcp_ms=result.lcp_ms,
            cls_value=result.cls_value,
            fid_ms=responsiveness,
            fcp_ms=result.fcp_ms,
            tti_ms=None,
            ttfb_ms=result.ttfb_ms,
        )

        assessment, _ = self.cwv_service.get_cwv_assessment(
            lcp_ms=result.lcp_ms,
            cls_value=result.cls_value,
            fid_ms=responsiveness,
        )
        result.cwv_assessment = assessment
        result.grade = self._calculate_grade(result.cwv_score)

        return result

    def measure_url_with_artifact(
        self,
        url: str,
        samples: int = 1,
        save_artifact: bool = True,
        quality_profile: Optional['ScrapeQualityProfile'] = None,
    ) -> Tuple['CWVResult', Optional['PageArtifact']]:
        """
        Measure Core Web Vitals and capture comprehensive artifacts.

        This method captures raw HTML, screenshots, and metadata alongside
        CWV measurements so data can be analyzed offline.

        Args:
            url: URL to measure
            samples: Number of samples (1 for single measurement)
            save_artifact: Whether to persist artifact to disk
            quality_profile: Quality settings (defaults to HIGH_QUALITY_PROFILE)

        Returns:
            Tuple of (CWVResult, PageArtifact) - PageArtifact may be None if fetch failed
        """
        from seo_intelligence.models.artifacts import (
            PageArtifact,
            ScrapeQualityProfile,
            ArtifactStorage,
            HIGH_QUALITY_PROFILE,
        )

        profile = quality_profile or HIGH_QUALITY_PROFILE
        logger.info(f"Measuring CWV with artifact for {url} (quality={profile.wait_strategy})")

        start_time = time.time()
        result = CWVResult(url=url)
        artifact = None

        try:
            with self.browser_session("generic") as driver:
                # First, capture artifact using the base class method
                artifact = self.fetch_page_with_artifact(
                    driver=driver,
                    url=url,
                    quality_profile=profile,
                    save_artifact=save_artifact,
                    wait_for_selector="body",
                )

                if artifact:
                    # Add artifact metadata to result
                    result.artifact_captured = True
                    result.artifact_completeness = artifact.completeness_score

                    if artifact.detected_captcha:
                        result.error = "CAPTCHA detected"
                        return result, artifact

                    # Now inject CWV observers and measure
                    logger.debug(f"Injecting CWV observers for {url}")
                    self._inject_cwv_observers(driver)

                    # Wait for metrics to stabilize
                    time.sleep(self.cwv_wait_time)

                    # Trigger FID interaction
                    self._trigger_fid(driver)
                    time.sleep(0.5)

                    # Human-like scrolling
                    self._human_scroll(driver, "down", random.randint(200, 400))
                    time.sleep(random.uniform(0.5, 1.0))

                    # Collect metrics
                    raw_metrics = self._collect_metrics(driver)
                    logger.debug(f"Raw metrics with artifact: {raw_metrics}")

                    # Extract metrics
                    result.lcp_ms = raw_metrics.get("lcp")
                    result.cls_value = raw_metrics.get("cls", 0)
                    result.inp_ms = raw_metrics.get("inp")
                    result.fid_ms = raw_metrics.get("fid")
                    result.fcp_ms = raw_metrics.get("fcp")
                    result.tti_ms = raw_metrics.get("tti")
                    result.ttfb_ms = raw_metrics.get("ttfb")
                    result.lcp_element = raw_metrics.get("lcp_element")

                    # Calculate TBT from long tasks
                    long_tasks = raw_metrics.get("long_tasks", [])
                    tbt_data = self._calculate_tbt(long_tasks)
                    result.tbt_ms = tbt_data['tbt_ms']
                    result.tbt_rating = tbt_data['tbt_rating']
                    result.long_task_count = tbt_data['long_task_count']
                    result.long_task_total_ms = tbt_data['long_task_total_ms']

                    # Collect resource timing breakdown
                    resource_timing = self._collect_resource_timing(driver)
                    if resource_timing:
                        nav_timing = resource_timing.get('navigation_timing', {})
                        if nav_timing:
                            result.dns_lookup_ms = nav_timing.get('dns_lookup_ms')
                            result.tcp_connect_ms = nav_timing.get('tcp_connect_ms')
                            result.ssl_handshake_ms = nav_timing.get('ssl_handshake_ms')
                            result.request_time_ms = nav_timing.get('request_time_ms')
                            result.response_time_ms = nav_timing.get('response_time_ms')
                            result.dom_interactive_ms = nav_timing.get('dom_interactive_ms')
                            result.dom_content_loaded_ms = nav_timing.get('dom_content_loaded_ms')
                            result.dom_complete_ms = nav_timing.get('dom_complete_ms')
                            result.load_event_ms = nav_timing.get('load_event_ms')

                        res_timing = resource_timing.get('resource_timing', {})
                        if res_timing:
                            result.total_resources = res_timing.get('total_resources')
                            result.total_resources_size_bytes = res_timing.get('total_size_bytes')
                            result.render_blocking_count = len(res_timing.get('render_blocking', []))

                        third_party = resource_timing.get('third_party', {})
                        if third_party:
                            result.third_party_domain_count = third_party.get('total_count')
                            result.third_party_domains = third_party.get('domains')

                    # Calculate ratings
                    if result.lcp_ms is not None:
                        result.lcp_rating = self.cwv_service.rate_lcp(result.lcp_ms).value

                    if result.cls_value is not None:
                        result.cls_rating = self.cwv_service.rate_cls(result.cls_value).value

                    if result.inp_ms is not None:
                        if result.inp_ms <= 200:
                            result.inp_rating = "GOOD"
                        elif result.inp_ms <= 500:
                            result.inp_rating = "NEEDS_IMPROVEMENT"
                        else:
                            result.inp_rating = "POOR"

                    if result.fid_ms is not None:
                        result.fid_rating = self.cwv_service.rate_fid(result.fid_ms).value

                    # Calculate composite score
                    responsiveness = result.inp_ms if result.inp_ms is not None else result.fid_ms
                    result.cwv_score = self.cwv_service.calculate_cwv_score(
                        lcp_ms=result.lcp_ms,
                        cls_value=result.cls_value,
                        fid_ms=responsiveness,
                        fcp_ms=result.fcp_ms,
                        tti_ms=result.tti_ms,
                        ttfb_ms=result.ttfb_ms,
                    )

                    assessment, _ = self.cwv_service.get_cwv_assessment(
                        lcp_ms=result.lcp_ms,
                        cls_value=result.cls_value,
                        fid_ms=responsiveness,
                    )
                    result.cwv_assessment = assessment
                    result.grade = self._calculate_grade(result.cwv_score)

                    # Store artifact console errors in result metadata
                    if artifact.console_errors:
                        result.console_errors_count = len(artifact.console_errors)

        except Exception as e:
            logger.error(f"Error measuring CWV with artifact for {url}: {e}")
            result.error = str(e)

        result.measurement_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"CWV with artifact for {url}: "
            f"LCP={result.lcp_ms}ms ({result.lcp_rating}), "
            f"CLS={result.cls_value} ({result.cls_rating}), "
            f"Score={result.cwv_score}, artifact={artifact is not None}"
        )

        return result, artifact

    def measure_desktop_and_mobile(
        self,
        url: str,
        samples: int = 1,
    ) -> MobileDesktopComparison:
        """
        Measure Core Web Vitals in both desktop and mobile modes and compare.

        This method creates separate measurements using:
        - Desktop: 1920x1080 viewport with desktop user agent
        - Mobile: 375x812 viewport (iPhone X) with mobile user agent

        Returns a MobileDesktopComparison object with both results and
        computed deltas, percentage changes, and mobile-specific recommendations.

        Args:
            url: URL to measure
            samples: Number of samples per device type (1 for single measurement)

        Returns:
            MobileDesktopComparison with desktop_result, mobile_result, and analysis
        """
        start_time = time.time()
        comparison = MobileDesktopComparison(url=url)

        try:
            # Store original mobile mode setting
            original_mobile_mode = self._mobile_mode

            # === Desktop Measurement ===
            logger.info(f"Starting desktop CWV measurement for {url}")
            self._mobile_mode = False

            # Create desktop scraper instance
            desktop_scraper = CoreWebVitalsSelenium(
                headless=self.headless,
                use_proxy=self.use_proxy,
                tier=self.tier,
                cwv_wait_time=self.cwv_wait_time,
                mobile_mode=False,
            )

            try:
                desktop_result = desktop_scraper.measure_url(url, samples=samples)
                desktop_result.device_type = "desktop"
                comparison.desktop_result = desktop_result
                logger.info(
                    f"Desktop CWV: LCP={desktop_result.lcp_ms}ms, "
                    f"CLS={desktop_result.cls_value}, "
                    f"Score={desktop_result.cwv_score}"
                )
            except Exception as e:
                logger.error(f"Desktop measurement failed: {e}")
                desktop_result = CWVResult(url=url, device_type="desktop", error=str(e))
                comparison.desktop_result = desktop_result
            finally:
                desktop_scraper.cleanup()

            # Brief pause between measurements
            time.sleep(random.uniform(1.0, 2.0))

            # === Mobile Measurement ===
            logger.info(f"Starting mobile CWV measurement for {url}")

            # Create mobile scraper instance
            mobile_scraper = CoreWebVitalsSelenium(
                headless=self.headless,
                use_proxy=self.use_proxy,
                tier=self.tier,
                cwv_wait_time=self.cwv_wait_time,
                mobile_mode=True,
            )

            try:
                mobile_result = mobile_scraper.measure_url(url, samples=samples)
                mobile_result.device_type = "mobile"
                comparison.mobile_result = mobile_result
                logger.info(
                    f"Mobile CWV: LCP={mobile_result.lcp_ms}ms, "
                    f"CLS={mobile_result.cls_value}, "
                    f"Score={mobile_result.cwv_score}"
                )
            except Exception as e:
                logger.error(f"Mobile measurement failed: {e}")
                mobile_result = CWVResult(url=url, device_type="mobile", error=str(e))
                comparison.mobile_result = mobile_result
            finally:
                mobile_scraper.cleanup()

            # Restore original mode
            self._mobile_mode = original_mobile_mode

            # === Calculate Deltas ===
            self._calculate_comparison_metrics(comparison)

            # === Analyze Mobile Issues ===
            self._analyze_mobile_issues(comparison)

        except Exception as e:
            logger.error(f"Error in desktop/mobile comparison for {url}: {e}")
            comparison.error = str(e)

        comparison.measurement_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Desktop vs Mobile comparison for {url}: "
            f"Desktop={comparison.desktop_score} ({comparison.desktop_grade}), "
            f"Mobile={comparison.mobile_score} ({comparison.mobile_grade}), "
            f"Score Delta={comparison.score_delta}, "
            f"Mobile Penalty={comparison.mobile_penalty_detected}"
        )

        return comparison

    def _calculate_comparison_metrics(self, comparison: MobileDesktopComparison) -> None:
        """Calculate delta values and percentage changes between desktop and mobile."""
        desktop = comparison.desktop_result
        mobile = comparison.mobile_result

        if not desktop or not mobile:
            return

        # Calculate deltas (positive = mobile is slower/worse)
        if desktop.lcp_ms is not None and mobile.lcp_ms is not None:
            comparison.lcp_delta_ms = round(mobile.lcp_ms - desktop.lcp_ms, 2)
            if desktop.lcp_ms > 0:
                comparison.lcp_pct_change = round(
                    ((mobile.lcp_ms - desktop.lcp_ms) / desktop.lcp_ms) * 100, 1
                )

        if desktop.cls_value is not None and mobile.cls_value is not None:
            comparison.cls_delta = round(mobile.cls_value - desktop.cls_value, 4)
            if desktop.cls_value > 0:
                comparison.cls_pct_change = round(
                    ((mobile.cls_value - desktop.cls_value) / desktop.cls_value) * 100, 1
                )

        if desktop.inp_ms is not None and mobile.inp_ms is not None:
            comparison.inp_delta_ms = round(mobile.inp_ms - desktop.inp_ms, 2)

        if desktop.fcp_ms is not None and mobile.fcp_ms is not None:
            comparison.fcp_delta_ms = round(mobile.fcp_ms - desktop.fcp_ms, 2)

        if desktop.ttfb_ms is not None and mobile.ttfb_ms is not None:
            comparison.ttfb_delta_ms = round(mobile.ttfb_ms - desktop.ttfb_ms, 2)

        if desktop.tbt_ms is not None and mobile.tbt_ms is not None:
            comparison.tbt_delta_ms = round(mobile.tbt_ms - desktop.tbt_ms, 2)
            if desktop.tbt_ms > 0:
                comparison.tbt_pct_change = round(
                    ((mobile.tbt_ms - desktop.tbt_ms) / desktop.tbt_ms) * 100, 1
                )

        # Score comparisons
        comparison.desktop_score = desktop.cwv_score
        comparison.mobile_score = mobile.cwv_score
        comparison.desktop_grade = desktop.grade
        comparison.mobile_grade = mobile.grade

        if desktop.cwv_score is not None and mobile.cwv_score is not None:
            comparison.score_delta = round(mobile.cwv_score - desktop.cwv_score, 1)

        # Resource comparisons
        comparison.desktop_resource_count = desktop.total_resources
        comparison.mobile_resource_count = mobile.total_resources
        comparison.desktop_page_size_bytes = desktop.page_transfer_size_bytes
        comparison.mobile_page_size_bytes = mobile.page_transfer_size_bytes

    def _analyze_mobile_issues(self, comparison: MobileDesktopComparison) -> None:
        """Analyze and identify mobile-specific performance issues."""
        issues = []
        recommendations = []

        desktop = comparison.desktop_result
        mobile = comparison.mobile_result

        if not desktop or not mobile or desktop.error or mobile.error:
            return

        # Check for mobile penalty (score drop > 10 points)
        if comparison.score_delta is not None and comparison.score_delta < -10:
            comparison.mobile_penalty_detected = True
            issues.append(f"Significant mobile performance penalty: {abs(comparison.score_delta):.0f} point score drop")

        # LCP issues (mobile > 500ms slower)
        if comparison.lcp_delta_ms is not None and comparison.lcp_delta_ms > 500:
            issues.append(f"LCP {comparison.lcp_delta_ms:.0f}ms slower on mobile")
            if comparison.lcp_pct_change and comparison.lcp_pct_change > 50:
                recommendations.append("Optimize LCP element for mobile: use responsive images with srcset")
                recommendations.append("Consider lazy loading below-fold images")

        # CLS issues (mobile > 0.05 worse)
        if comparison.cls_delta is not None and comparison.cls_delta > 0.05:
            issues.append(f"CLS {comparison.cls_delta:.3f} worse on mobile")
            recommendations.append("Add explicit dimensions to images and embeds")
            recommendations.append("Reserve space for dynamic content (ads, forms)")

        # TBT issues (mobile > 200ms worse)
        if comparison.tbt_delta_ms is not None and comparison.tbt_delta_ms > 200:
            issues.append(f"TBT {comparison.tbt_delta_ms:.0f}ms higher on mobile")
            recommendations.append("Reduce JavaScript execution time for mobile")
            recommendations.append("Consider code splitting for mobile-specific bundles")

        # Check for rating degradation
        desktop_ratings = {
            'lcp': desktop.lcp_rating,
            'cls': desktop.cls_rating,
            'inp': desktop.inp_rating,
        }
        mobile_ratings = {
            'lcp': mobile.lcp_rating,
            'cls': mobile.cls_rating,
            'inp': mobile.inp_rating,
        }

        rating_order = {'GOOD': 3, 'NEEDS_IMPROVEMENT': 2, 'POOR': 1, None: 0}

        for metric, desktop_rating in desktop_ratings.items():
            mobile_rating = mobile_ratings[metric]
            if desktop_rating and mobile_rating:
                if rating_order.get(mobile_rating, 0) < rating_order.get(desktop_rating, 0):
                    issues.append(f"{metric.upper()} rating dropped from {desktop_rating} to {mobile_rating} on mobile")

        # Resource count difference
        if comparison.desktop_resource_count and comparison.mobile_resource_count:
            if comparison.mobile_resource_count > comparison.desktop_resource_count * 1.2:
                issues.append(f"Mobile loads more resources ({comparison.mobile_resource_count} vs {comparison.desktop_resource_count})")
                recommendations.append("Audit mobile-specific resources and optimize loading")

        # Page size difference
        if comparison.desktop_page_size_bytes and comparison.mobile_page_size_bytes:
            size_ratio = comparison.mobile_page_size_bytes / comparison.desktop_page_size_bytes
            if size_ratio > 1.1:
                issues.append(f"Mobile page size {size_ratio:.1f}x larger than desktop")
                recommendations.append("Ensure responsive images serve appropriately sized assets")

        # General mobile recommendations
        if issues:
            if not any("responsive" in r.lower() for r in recommendations):
                recommendations.append("Verify responsive design with appropriate breakpoints")
            if not any("viewport" in r.lower() for r in recommendations):
                recommendations.append("Ensure proper viewport meta tag configuration")

        comparison.mobile_issues = issues
        comparison.recommendations = recommendations

    def run(self, urls: List[str]) -> Dict[str, Any]:
        """Run CWV measurement for multiple URLs."""
        results = {
            "total_urls": len(urls),
            "successful": 0,
            "failed": 0,
            "measurements": [],
        }

        for url in urls:
            measurement = self.measure_url(url)
            if not measurement.error:
                results["successful"] += 1
            else:
                results["failed"] += 1
            results["measurements"].append(measurement.to_dict())

        return results

    def save_to_db(
        self,
        result: CWVResult,
        company_id: Optional[int] = None,
    ) -> Optional[int]:
        """Save CWV result to database.

        Args:
            result: The CWVResult from measure_url()
            company_id: Optional company ID to associate with the measurement

        Returns:
            The record ID if saved successfully, None otherwise
        """
        if not self.engine:
            logger.warning("No database engine configured, skipping DB save")
            return None

        try:
            import json
            with Session(self.engine) as session:
                insert_result = session.execute(
                    text("""
                        INSERT INTO core_web_vitals (
                            company_id, url, device_type,
                            lcp_ms, cls_value, inp_ms, fid_ms, fcp_ms, ttfb_ms, tbt_ms, tti_ms,
                            lcp_rating, cls_rating, inp_rating, fid_rating, tbt_rating,
                            cwv_score, cwv_assessment, grade,
                            dns_lookup_ms, tcp_connect_ms, ssl_handshake_ms,
                            request_time_ms, response_time_ms,
                            dom_interactive_ms, dom_content_loaded_ms, dom_complete_ms, load_event_ms,
                            page_transfer_size_bytes, total_resources, total_resources_size_bytes,
                            third_party_domain_count, render_blocking_count,
                            long_task_count, long_task_total_ms,
                            metrics_json
                        ) VALUES (
                            :company_id, :url, :device_type,
                            :lcp_ms, :cls_value, :inp_ms, :fid_ms, :fcp_ms, :ttfb_ms, :tbt_ms, :tti_ms,
                            :lcp_rating, :cls_rating, :inp_rating, :fid_rating, :tbt_rating,
                            :cwv_score, :cwv_assessment, :grade,
                            :dns_lookup_ms, :tcp_connect_ms, :ssl_handshake_ms,
                            :request_time_ms, :response_time_ms,
                            :dom_interactive_ms, :dom_content_loaded_ms, :dom_complete_ms, :load_event_ms,
                            :page_transfer_size_bytes, :total_resources, :total_resources_size_bytes,
                            :third_party_domain_count, :render_blocking_count,
                            :long_task_count, :long_task_total_ms,
                            :metrics_json
                        )
                        RETURNING id
                    """),
                    {
                        "company_id": company_id,
                        "url": result.url,
                        "device_type": result.device_type,
                        "lcp_ms": result.lcp_ms,
                        "cls_value": result.cls_value,
                        "inp_ms": result.inp_ms,
                        "fid_ms": result.fid_ms,
                        "fcp_ms": result.fcp_ms,
                        "ttfb_ms": result.ttfb_ms,
                        "tbt_ms": result.tbt_ms,
                        "tti_ms": result.tti_ms,
                        "lcp_rating": result.lcp_rating,
                        "cls_rating": result.cls_rating,
                        "inp_rating": result.inp_rating,
                        "fid_rating": result.fid_rating,
                        "tbt_rating": result.tbt_rating,
                        "cwv_score": result.cwv_score,
                        "cwv_assessment": result.cwv_assessment,
                        "grade": result.grade,
                        "dns_lookup_ms": result.dns_lookup_ms,
                        "tcp_connect_ms": result.tcp_connect_ms,
                        "ssl_handshake_ms": result.ssl_handshake_ms,
                        "request_time_ms": result.request_time_ms,
                        "response_time_ms": result.response_time_ms,
                        "dom_interactive_ms": result.dom_interactive_ms,
                        "dom_content_loaded_ms": result.dom_content_loaded_ms,
                        "dom_complete_ms": result.dom_complete_ms,
                        "load_event_ms": result.load_event_ms,
                        "page_transfer_size_bytes": result.page_transfer_size_bytes,
                        "total_resources": result.total_resources,
                        "total_resources_size_bytes": result.total_resources_size_bytes,
                        "third_party_domain_count": result.third_party_domain_count,
                        "render_blocking_count": result.render_blocking_count,
                        "long_task_count": result.long_task_count,
                        "long_task_total_ms": result.long_task_total_ms,
                        "metrics_json": json.dumps(result.to_dict()),
                    }
                )
                record_id = insert_result.fetchone()[0]
                session.commit()
                logger.info(f"Saved CWV result {record_id} for {result.url} (grade={result.grade})")
                return record_id

        except Exception as e:
            logger.error(f"Failed to save CWV to DB: {e}")
            return None


# Module singleton
_cwv_selenium_instance = None


def get_cwv_selenium(**kwargs) -> CoreWebVitalsSelenium:
    """Get or create singleton CoreWebVitalsSelenium instance."""
    global _cwv_selenium_instance
    if _cwv_selenium_instance is None:
        _cwv_selenium_instance = CoreWebVitalsSelenium(**kwargs)
    return _cwv_selenium_instance
