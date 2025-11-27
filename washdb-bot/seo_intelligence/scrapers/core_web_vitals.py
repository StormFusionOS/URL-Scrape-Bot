"""
Core Web Vitals Collector

Measures Core Web Vitals using Playwright's Performance APIs.

Metrics collected:
- LCP (Largest Contentful Paint): Loading performance
- CLS (Cumulative Layout Shift): Visual stability
- FID (First Input Delay): Simulated via click interaction
- FCP (First Contentful Paint): First paint with content
- TTI (Time to Interactive): Estimated from Long Tasks
- TTFB (Time to First Byte): Server response time

Technical approach:
- Inject JavaScript PerformanceObserver before navigation
- Collect metrics via browser Performance APIs
- Simulate user interaction for FID measurement
- Calculate TTI from Long Tasks API

Usage:
    from seo_intelligence.scrapers.core_web_vitals import CoreWebVitalsCollector

    collector = CoreWebVitalsCollector()
    metrics = collector.measure_url("https://example.com")

    # Returns:
    # {
    #     "lcp_ms": 2345.67,
    #     "cls_value": 0.05,
    #     "fid_ms": 45.0,
    #     "fcp_ms": 1234.56,
    #     "tti_ms": 3456.78,
    #     "ttfb_ms": 234.56,
    #     "lcp_element": "img.hero-image",
    #     "lcp_rating": "GOOD",
    #     "cls_rating": "GOOD",
    #     "fid_rating": "GOOD",
    #     "cwv_score": 85.5,
    #     "cwv_assessment": "PASSED"
    # }
"""

import os
import time
import json
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse
from dataclasses import dataclass

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from playwright_stealth import Stealth

from seo_intelligence.services.cwv_metrics import get_cwv_metrics_service, CWVRating
from runner.logging_setup import get_logger

logger = get_logger("core_web_vitals")


# JavaScript to inject for CWV measurement
CWV_INJECTION_SCRIPT = """
() => {
    // Initialize CWV storage
    window.__cwv_metrics = {
        lcp: null,
        cls: 0,
        fid: null,
        fcp: null,
        ttfb: null,
        tti: null,
        lcp_element: null,
        long_tasks: [],
        layout_shifts: [],
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
    lcp_ms: Optional[float] = None
    cls_value: Optional[float] = None
    fid_ms: Optional[float] = None
    fcp_ms: Optional[float] = None
    tti_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None
    lcp_element: Optional[str] = None
    lcp_rating: Optional[str] = None
    cls_rating: Optional[str] = None
    fid_rating: Optional[str] = None
    cwv_score: Optional[float] = None
    cwv_assessment: Optional[str] = None
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
    """

    def __init__(
        self,
        headless: bool = True,
        page_timeout: int = 30000,
        cwv_wait_time: float = 5.0,
    ):
        """
        Initialize CWV collector.

        Args:
            headless: Run browser in headless mode
            page_timeout: Page load timeout in milliseconds
            cwv_wait_time: Time to wait for CWV metrics to stabilize (seconds)
        """
        self.headless = headless
        self.page_timeout = page_timeout
        self.cwv_wait_time = cwv_wait_time
        self.cwv_service = get_cwv_metrics_service()

        logger.info(
            f"CoreWebVitalsCollector initialized "
            f"(headless={headless}, wait={cwv_wait_time}s)"
        )

    def _create_browser_context(
        self,
        browser: Browser,
    ) -> BrowserContext:
        """Create browser context with realistic settings."""
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        context.set_default_timeout(self.page_timeout)
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
                    result.fid_ms = raw_metrics.get("fid")
                    result.fcp_ms = raw_metrics.get("fcp")
                    result.tti_ms = raw_metrics.get("tti")
                    result.ttfb_ms = raw_metrics.get("ttfb")
                    result.lcp_element = raw_metrics.get("lcp_element")

                    # Calculate ratings
                    if result.lcp_ms is not None:
                        result.lcp_rating = self.cwv_service.rate_lcp(result.lcp_ms).value

                    if result.cls_value is not None:
                        result.cls_rating = self.cwv_service.rate_cls(result.cls_value).value

                    if result.fid_ms is not None:
                        result.fid_rating = self.cwv_service.rate_fid(result.fid_ms).value

                    # Calculate composite score
                    result.cwv_score = self.cwv_service.calculate_cwv_score(
                        lcp_ms=result.lcp_ms,
                        cls_value=result.cls_value,
                        fid_ms=result.fid_ms,
                        fcp_ms=result.fcp_ms,
                        tti_ms=result.tti_ms,
                        ttfb_ms=result.ttfb_ms,
                    )

                    # Get assessment
                    assessment, _ = self.cwv_service.get_cwv_assessment(
                        lcp_ms=result.lcp_ms,
                        cls_value=result.cls_value,
                        fid_ms=result.fid_ms,
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
