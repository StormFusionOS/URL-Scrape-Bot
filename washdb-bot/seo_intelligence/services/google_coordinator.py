"""
Google Request Coordinator

Centralizes all Google requests to:
1. Prevent simultaneous requests from multiple scrapers
2. Optionally share a single browser session
3. Enforce proper delays between requests
4. Respect domain quarantine globally

This solves the problem of multiple SEO modules (SERP, Autocomplete, KeywordIntelligence)
hitting Google in quick succession with separate browser sessions, which triggers CAPTCHAs.
"""

import threading
import time
import random
from typing import Callable, Any, Optional
from dataclasses import dataclass, field
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from seo_intelligence.services.rate_limiter import get_rate_limiter
from seo_intelligence.services.domain_quarantine import get_domain_quarantine
from seo_intelligence.drivers import (
    get_driver_for_site,
    get_escalation_manager,
    should_use_camoufox,
    BrowserTier,
    CamoufoxGoogleDriver,
)
from runner.logging_setup import get_logger

logger = get_logger("google_coordinator")

GOOGLE_DOMAIN = "www.google.com"
GOOGLE_DOMAIN_SHORT = "google.com"  # For escalation tracking
MIN_DELAY_BETWEEN_REQUESTS = 15.0  # seconds
MAX_DELAY_BETWEEN_REQUESTS = 30.0  # seconds


@dataclass(order=True)
class GoogleRequest:
    """A queued Google request with priority."""
    priority: int
    request_type: str = field(compare=False)
    callback: Callable = field(compare=False)
    created_at: float = field(default_factory=time.time, compare=False)


class CamoufoxSeleniumWrapper:
    """
    Wrapper that provides a SeleniumBase-compatible interface for CamoufoxGoogleDriver.

    This allows existing scrapers that expect a Selenium WebDriver to work with Camoufox.
    """

    def __init__(self, camoufox_driver: 'CamoufoxGoogleDriver'):
        self._driver = camoufox_driver
        self._driver._ensure_browser()
        self._page = self._driver._page
        self._current_url = ""

    @property
    def page_source(self) -> str:
        """Get page HTML source."""
        try:
            return self._page.content()
        except Exception:
            return ""

    @property
    def current_url(self) -> str:
        """Get current URL."""
        try:
            return self._page.url
        except Exception:
            return self._current_url

    @property
    def title(self) -> str:
        """Get page title."""
        try:
            return self._page.title()
        except Exception:
            return ""

    def get(self, url: str):
        """Navigate to URL (Selenium-compatible)."""
        self._current_url = url
        self._page.goto(url, wait_until="domcontentloaded")
        time.sleep(random.uniform(1, 2))  # Human-like delay

    def _to_playwright_selector(self, by: str, value: str) -> str:
        """Convert Selenium By to Playwright selector."""
        if by == "css selector" or by == "CSS_SELECTOR":
            return value
        elif by == "xpath" or by == "XPATH":
            return f"xpath={value}"
        elif by == "id" or by == "ID":
            return f"#{value}"
        elif by == "name" or by == "NAME":
            return f"[name='{value}']"
        elif by == "tag name" or by == "TAG_NAME":
            return value
        else:
            return value

    def find_element(self, by: str, value: str):
        """Find element (basic Selenium compatibility)."""
        selector = self._to_playwright_selector(by, value)
        element = self._page.query_selector(selector)
        if element:
            return CamoufoxElementWrapper(element, self._page)
        return None

    def wait_for_element(self, selector: str, timeout: int = 10000, state: str = "visible"):
        """
        Wait for element (Playwright-native method).

        This method can be used directly by scrapers that detect Camoufox.

        Args:
            selector: CSS selector
            timeout: Timeout in milliseconds
            state: "visible", "attached", "detached", "hidden"

        Returns:
            CamoufoxElementWrapper if found, None otherwise
        """
        try:
            element = self._page.wait_for_selector(selector, timeout=timeout, state=state)
            if element:
                return CamoufoxElementWrapper(element, self._page)
        except Exception:
            pass
        return None

    def find_elements(self, by: str, value: str):
        """Find multiple elements (basic Selenium compatibility)."""
        selector = self._to_playwright_selector(by, value)
        elements = self._page.query_selector_all(selector)
        return [CamoufoxElementWrapper(e, self._page) for e in elements]

    def execute_script(self, script: str, *args):
        """Execute JavaScript."""
        return self._page.evaluate(script)

    def quit(self):
        """Close browser - handled by coordinator."""
        pass  # Don't close, coordinator manages lifecycle

    def close(self):
        """Close current tab - handled by coordinator."""
        pass


class CamoufoxElementWrapper:
    """Wrapper for Playwright element to provide Selenium-like interface."""

    def __init__(self, element, page):
        self._element = element
        self._page = page

    @property
    def text(self) -> str:
        """Get element text."""
        try:
            return self._element.inner_text()
        except Exception:
            return ""

    def get_attribute(self, name: str) -> Optional[str]:
        """Get element attribute."""
        try:
            return self._element.get_attribute(name)
        except Exception:
            return None

    def click(self):
        """Click element."""
        self._element.click()

    def send_keys(self, text: str):
        """Type text into element."""
        self._element.type(text)

    def clear(self):
        """Clear element."""
        self._element.fill("")

    def is_displayed(self) -> bool:
        """Check if element is visible."""
        try:
            return self._element.is_visible()
        except Exception:
            return False


class GoogleCoordinator:
    """
    Coordinates all Google requests across SEO modules.

    Ensures only one request hits Google at a time with proper delays.
    Optionally shares a single browser session across all modules.
    """

    def __init__(
        self,
        share_browser: bool = True,
        headless: bool = False,  # Default False - runs on Xvfb virtual display for better anti-detection
        use_proxy: bool = True,
        enable_escalation: bool = True,  # Enable Camoufox escalation on CAPTCHA
    ):
        """
        Initialize the Google Coordinator.

        Args:
            share_browser: If True, share a single browser session for all Google requests.
                          If False, create a new browser for each request.
            headless: Run browser in headless mode (False recommended - uses Xvfb)
            use_proxy: Use proxy pool for requests
            enable_escalation: Enable automatic escalation to Camoufox on CAPTCHA
        """
        self.share_browser = share_browser
        self.headless = headless
        self.use_proxy = use_proxy
        self.enable_escalation = enable_escalation
        self.rate_limiter = get_rate_limiter()
        self.quarantine = get_domain_quarantine()

        # Browser escalation manager
        self.escalation_manager = get_escalation_manager() if enable_escalation else None

        self._browser = None  # SeleniumBase UC browser
        self._camoufox = None  # Camoufox browser (fallback)
        self._browser_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._last_request_time = 0.0

        # Statistics
        self._stats = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "captchas_detected": 0,
            "camoufox_used": 0,
            "escalations": 0,
        }

        # Set Google to Tier A (strictest rate limiting)
        self.rate_limiter.set_domain_tier(GOOGLE_DOMAIN, "A")

        logger.info(f"GoogleCoordinator initialized (share_browser={share_browser}, headless={headless}, use_proxy={use_proxy}, escalation={enable_escalation})")

    def is_quarantined(self) -> bool:
        """Check if Google is currently quarantined due to CAPTCHA detection."""
        return self.quarantine.is_quarantined(GOOGLE_DOMAIN)

    def get_quarantine_info(self) -> Optional[dict]:
        """Get quarantine information for Google if quarantined."""
        if self.is_quarantined():
            return self.quarantine.get_quarantine_info(GOOGLE_DOMAIN)
        return None

    def _should_use_camoufox(self) -> bool:
        """Check if we should use Camoufox based on escalation state."""
        if not self.enable_escalation or not self.escalation_manager:
            return False
        return should_use_camoufox(GOOGLE_DOMAIN_SHORT)

    def _get_current_tier(self) -> Optional[BrowserTier]:
        """Get current browser tier for Google."""
        if not self.escalation_manager:
            return None
        return self.escalation_manager.get_current_tier(GOOGLE_DOMAIN_SHORT)

    def _record_success(self):
        """Record successful request and periodically save browser state."""
        self._stats["requests_success"] += 1
        if self.escalation_manager:
            self.escalation_manager.record_success(GOOGLE_DOMAIN_SHORT)

        # Save browser storage state every 5 successful requests
        if self._stats["requests_success"] % 5 == 0:
            self._save_browser_state()

    def _save_browser_state(self):
        """Save Camoufox storage state (cookies, localStorage) to persist across restarts."""
        if self._camoufox and hasattr(self._camoufox, 'save_storage_state'):
            try:
                self._camoufox.save_storage_state()
            except Exception as e:
                logger.debug(f"Could not save browser state: {e}")

    def _record_captcha(self):
        """Record CAPTCHA detection and escalate."""
        self._stats["captchas_detected"] += 1
        if self.escalation_manager:
            old_tier = self._get_current_tier()
            self.escalation_manager.record_failure(GOOGLE_DOMAIN_SHORT, is_captcha=True)
            new_tier = self._get_current_tier()
            if old_tier != new_tier:
                self._stats["escalations"] += 1
                logger.info(f"Escalated Google browser: {old_tier.name if old_tier else 'None'} -> {new_tier.name if new_tier else 'None'}")

    def _get_delay(self) -> float:
        """Get randomized delay for next request (15-30s)."""
        return random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)

    def _warm_up_browser(self):
        """
        Warm up the browser with a simple search before doing actual SERP queries.

        This helps avoid detection by establishing a "real user" session pattern.
        Based on the Scrape-Bot approach that warms up with a neutral query first.
        """
        if not self._camoufox:
            return

        max_retries = 2
        for attempt in range(max_retries):
            try:
                logger.debug(f"Warming up browser (attempt {attempt + 1}/{max_retries})...")
                self._camoufox._ensure_browser()
                page = self._camoufox._page

                # First try simple homepage (faster, less likely to fail)
                try:
                    page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=20000)
                    time.sleep(2)
                except Exception:
                    # Fallback: try with longer timeout
                    page.goto("https://www.google.com", wait_until="load", timeout=45000)
                    time.sleep(2)

                # Handle consent popup if present
                try:
                    consent_btn = page.query_selector('button[id="L2AGLb"]')
                    if consent_btn and consent_btn.is_visible():
                        consent_btn.click()
                        logger.debug("Clicked consent button during warm-up")
                        time.sleep(1)
                except Exception:
                    pass

                # Check for CAPTCHA
                url = page.url
                if "/sorry/" in url:
                    logger.warning("Got CAPTCHA during warm-up - session may be flagged")
                    self._record_captcha()
                else:
                    logger.debug("Browser warm-up successful")
                    time.sleep(1)
                    return  # Success

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Browser warm-up attempt {attempt + 1} failed, retrying: {str(e)[:50]}")
                    time.sleep(2)
                else:
                    # Only log as debug on final failure - warm-up is optional
                    logger.debug(f"Browser warm-up failed after {max_retries} attempts (non-critical)")

    def _run_in_isolated_thread(self, func, *args, timeout: int = 120, **kwargs):
        """
        Run a function in an isolated thread to avoid asyncio loop contamination.

        Playwright's sync API creates an event loop that persists even after the
        browser closes. This wrapper ensures Camoufox operations run in a clean
        thread. nest_asyncio (applied in camoufox_drivers.py) allows nested event
        loops, so Playwright works correctly.

        Args:
            func: Function to run in isolated thread
            *args: Positional arguments for func
            timeout: Timeout in seconds (default 120)
            **kwargs: Keyword arguments for func

        Returns:
            Result from func
        """
        import asyncio

        def wrapped_func(*args, **kwargs):
            # Ensure nest_asyncio is applied (camoufox_drivers import does this)
            import nest_asyncio
            nest_asyncio.apply()

            # Create a fresh event loop for this thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)

            try:
                return func(*args, **kwargs)
            finally:
                # Clean up the event loop
                try:
                    new_loop.close()
                except Exception:
                    pass

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="isolated_browser") as executor:
            future = executor.submit(wrapped_func, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeout:
                logger.error(f"Browser operation timed out after {timeout}s")
                raise
            except Exception as e:
                logger.error(f"Browser operation failed: {e}")
                raise

    def _ensure_delay(self):
        """Ensure minimum delay since last request."""
        if self._last_request_time == 0.0:
            # First request, no delay needed
            return

        elapsed = time.time() - self._last_request_time
        delay_needed = self._get_delay()

        if elapsed < delay_needed:
            wait_time = delay_needed - elapsed
            logger.debug(f"Waiting {wait_time:.1f}s before next Google request")
            time.sleep(wait_time)

    @contextmanager
    def _get_browser(self):
        """
        Get browser session (shared or new).

        Automatically uses Camoufox if escalation tier requires it.

        Yields:
            Browser driver instance (SeleniumBase or Camoufox wrapper)
        """
        use_camoufox = self._should_use_camoufox()

        if use_camoufox:
            # Use Camoufox for better anti-detection
            with self._get_camoufox_browser() as browser:
                yield browser
        elif self.share_browser:
            with self._browser_lock:
                if self._browser is None:
                    logger.info(f"Creating shared Google browser session (headless={self.headless})")
                    self._browser = get_driver_for_site(
                        site="google",
                        headless=self.headless,
                        use_proxy=self.use_proxy,
                    )
                yield self._browser
        else:
            # Create new browser for this request
            logger.debug(f"Creating new browser for Google request (headless={self.headless})")
            browser = get_driver_for_site(site="google", headless=self.headless, use_proxy=self.use_proxy)
            try:
                yield browser
            finally:
                if browser:
                    try:
                        browser.quit()
                    except Exception:
                        pass

    @contextmanager
    def _get_camoufox_browser(self):
        """
        Get Camoufox browser for Google requests.

        Camoufox is a Firefox-based undetected browser used when
        SeleniumBase UC gets CAPTCHA'd.

        Yields:
            CamoufoxGoogleDriver instance
        """
        self._stats["camoufox_used"] += 1
        tier = self._get_current_tier()
        new_fingerprint = tier == BrowserTier.CAMOUFOX_NEW_FP if tier else False

        logger.info(f"Using Camoufox for Google (tier={tier.name if tier else 'None'}, new_fp={new_fingerprint}, proxy={self.use_proxy})")

        with self._browser_lock:
            if self._camoufox is None:
                # Get residential proxy if enabled
                proxy_config = None
                timezone = None
                geolocation = None

                if self.use_proxy:
                    try:
                        from seo_intelligence.services.residential_proxy_manager import get_residential_proxy_manager
                        manager = get_residential_proxy_manager()
                        proxy = manager.get_proxy_for_directory("pool_google")
                        if proxy:
                            browser_config = manager.get_browser_config(proxy)
                            proxy_config = browser_config.get("proxy", {})
                            timezone = browser_config.get("timezone_id")
                            geolocation = browser_config.get("geolocation")
                            logger.info(f"Camoufox using residential proxy {proxy.host} ({proxy.city_name}, {proxy.state})")
                        else:
                            logger.warning("No residential proxy available for Google, using direct")
                    except Exception as e:
                        logger.warning(f"Failed to get residential proxy: {e}")

                self._camoufox = CamoufoxGoogleDriver(
                    headless=self.headless,
                    humanize=True,
                    new_fingerprint=new_fingerprint,
                    proxy=proxy_config,
                    timezone=timezone,
                    geolocation=geolocation,
                )

                # Warm up the browser with a simple search to avoid detection
                self._warm_up_browser()

            # Return a wrapper that provides SeleniumBase-compatible interface
            yield CamoufoxSeleniumWrapper(self._camoufox)

    def _execute_with_browser_impl(self, request_type: str, callback: Callable[[Any], Any], fresh_browser: bool = False) -> Any:
        """
        Internal implementation that gets browser and executes callback.

        This is separated so it can be run in an isolated thread when using Camoufox.

        Args:
            request_type: Type of request for logging
            callback: Function to execute with browser
            fresh_browser: If True, close existing Camoufox browser first to avoid
                          thread affinity issues when running in isolated threads
        """
        # When running in isolated thread, we need a fresh browser because
        # the previous browser was created in a different thread that has exited
        if fresh_browser and self._camoufox is not None:
            with self._browser_lock:
                if self._camoufox:
                    try:
                        self._camoufox.close()
                    except Exception:
                        pass
                    self._camoufox = None
                    logger.debug("Closed existing Camoufox for fresh browser in isolated thread")

        with self._get_browser() as browser:
            if browser is None:
                logger.error("Failed to get browser for Google request")
                self._stats["requests_failed"] += 1
                return None

            tier = self._get_current_tier()
            logger.debug(f"Executing {request_type} request via GoogleCoordinator (tier={tier.name if tier else 'UC'})")
            result = callback(browser)

            # Update last request time
            self._last_request_time = time.time()

            # Record success
            self._record_success()

            return result

    def execute(
        self,
        request_type: str,
        callback: Callable[[Any], Any],
        priority: int = 5
    ) -> Any:
        """
        Execute a Google request with coordination.

        Args:
            request_type: Type of request ("serp", "autocomplete", "keyword", etc.)
            callback: Function that takes a browser driver and returns result
            priority: Request priority (1=highest, 10=lowest) - for future queue implementation

        Returns:
            Result from callback function, or None if quarantined/failed
        """
        # Check escalation tier - if using Camoufox, bypass quarantine
        using_camoufox = self._should_use_camoufox()

        # Check quarantine, but allow Camoufox to bypass
        if self.is_quarantined() and not using_camoufox:
            info = self.get_quarantine_info()
            logger.warning(
                f"Google is quarantined, skipping {request_type} request. "
                f"Reason: {info.get('reason') if info else 'unknown'}"
            )
            return None
        elif self.is_quarantined() and using_camoufox:
            logger.info(
                f"Google is quarantined but using Camoufox for {request_type} - attempting bypass"
            )

        # Serialize all Google requests
        with self._request_lock:
            # Ensure delay between requests
            self._ensure_delay()

            # Acquire rate limit token
            if not self.rate_limiter.acquire(GOOGLE_DOMAIN, wait=True, max_wait=120.0):
                logger.warning("Failed to acquire rate limit token for Google")
                return None

            self._stats["requests_total"] += 1

            try:
                # If using Camoufox, run in isolated thread to avoid asyncio loop contamination
                if using_camoufox:
                    result = self._run_in_isolated_thread(
                        self._execute_with_browser_impl,
                        request_type,
                        callback,
                        True,  # fresh_browser=True - need new browser for new thread
                        timeout=120
                    )
                else:
                    result = self._execute_with_browser_impl(request_type, callback)

                return result

            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Google {request_type} request failed: {e}")
                self._stats["requests_failed"] += 1

                # Check if CAPTCHA and escalate + quarantine
                if "captcha" in error_str or "unusual traffic" in error_str or "blocked" in error_str:
                    self._record_captcha()
                    logger.warning("CAPTCHA/block detected, escalating and quarantining Google")
                    self.quarantine.quarantine_domain(
                        domain=GOOGLE_DOMAIN,
                        reason="CAPTCHA_DETECTED",
                        duration_minutes=60
                    )

                raise

    def _execute_with_own_browser_impl(self, request_type: str, scraper_method: Callable[[], Any]) -> Any:
        """
        Internal implementation for execute_with_own_browser.

        This is separated so it can be run in an isolated thread when using Camoufox.
        """
        tier = self._get_current_tier()
        logger.debug(f"Executing {request_type} request (own browser) via GoogleCoordinator (tier={tier.name if tier else 'UC'})")
        result = scraper_method()

        # Update last request time
        self._last_request_time = time.time()

        # Record success
        self._record_success()

        return result

    def execute_with_own_browser(
        self,
        request_type: str,
        scraper_method: Callable[[], Any],
        priority: int = 5
    ) -> Any:
        """
        Execute a request that uses its own browser, but with coordination.

        Use this when the scraper needs to manage its own browser lifecycle
        but still needs rate limiting and serialization.

        Args:
            request_type: Type of request ("serp", "autocomplete", etc.)
            scraper_method: Method to call (uses its own browser internally)
            priority: Request priority

        Returns:
            Result from scraper_method, or None if quarantined/failed
        """
        # Check escalation tier - if using Camoufox, bypass quarantine
        using_camoufox = self._should_use_camoufox()

        # Check quarantine, but allow Camoufox to bypass
        if self.is_quarantined() and not using_camoufox:
            info = self.get_quarantine_info()
            logger.warning(
                f"Google is quarantined, skipping {request_type} request. "
                f"Reason: {info.get('reason') if info else 'unknown'}"
            )
            return None
        elif self.is_quarantined() and using_camoufox:
            logger.info(
                f"Google is quarantined but using Camoufox for {request_type} - attempting bypass"
            )

        # Serialize all Google requests
        with self._request_lock:
            # Ensure delay between requests
            self._ensure_delay()

            # Acquire rate limit token
            if not self.rate_limiter.acquire(GOOGLE_DOMAIN, wait=True, max_wait=120.0):
                logger.warning("Failed to acquire rate limit token for Google")
                return None

            self._stats["requests_total"] += 1

            try:
                # If using Camoufox, run in isolated thread to avoid asyncio loop contamination
                if using_camoufox:
                    result = self._run_in_isolated_thread(
                        self._execute_with_own_browser_impl,
                        request_type,
                        scraper_method,
                        timeout=120
                    )
                else:
                    result = self._execute_with_own_browser_impl(request_type, scraper_method)

                return result

            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Google {request_type} request failed: {e}")
                self._stats["requests_failed"] += 1

                # Check if CAPTCHA and escalate + quarantine
                if "captcha" in error_str or "unusual traffic" in error_str or "blocked" in error_str:
                    self._record_captcha()
                    logger.warning("CAPTCHA/block detected, escalating and quarantining Google")
                    self.quarantine.quarantine_domain(
                        domain=GOOGLE_DOMAIN,
                        reason="CAPTCHA_DETECTED",
                        duration_minutes=60
                    )

                raise

    def refresh_browser(self):
        """Force refresh of the shared browser session (both UC and Camoufox)."""
        with self._browser_lock:
            if self._browser:
                try:
                    self._browser.quit()
                except Exception:
                    pass
                self._browser = None

            if self._camoufox:
                try:
                    self._camoufox.close()
                except Exception:
                    pass
                self._camoufox = None

        logger.info("Shared Google browser sessions refreshed (UC + Camoufox)")

    def reconfigure(self, headless: bool = None, use_proxy: bool = None):
        """
        Reconfigure browser settings and refresh the shared browser.

        Args:
            headless: New headless setting (None = keep current)
            use_proxy: New proxy setting (None = keep current)
        """
        if headless is not None:
            self.headless = headless
        if use_proxy is not None:
            self.use_proxy = use_proxy

        # Refresh browser to apply new settings
        self.refresh_browser()
        logger.info(f"GoogleCoordinator reconfigured (headless={self.headless}, use_proxy={self.use_proxy})")

    def close(self):
        """Close shared browser sessions and cleanup."""
        with self._browser_lock:
            if self._browser:
                try:
                    self._browser.quit()
                except Exception:
                    pass
                self._browser = None

            if self._camoufox:
                try:
                    self._camoufox.close()
                except Exception:
                    pass
                self._camoufox = None

        logger.info("GoogleCoordinator closed")

    def get_stats(self) -> dict:
        """Get coordinator statistics including escalation info."""
        tier = self._get_current_tier()
        return {
            "share_browser": self.share_browser,
            "browser_active": self._browser is not None,
            "camoufox_active": self._camoufox is not None,
            "current_tier": tier.name if tier else "SELENIUM_UC",
            "using_camoufox": self._should_use_camoufox(),
            "is_quarantined": self.is_quarantined(),
            "quarantine_info": self.get_quarantine_info(),
            "last_request_time": self._last_request_time,
            "seconds_since_last_request": time.time() - self._last_request_time if self._last_request_time > 0 else None,
            "min_delay": MIN_DELAY_BETWEEN_REQUESTS,
            "max_delay": MAX_DELAY_BETWEEN_REQUESTS,
            **self._stats,  # Include all stats
        }


# Singleton instance
_coordinator_instance = None
_coordinator_lock = threading.Lock()


def get_google_coordinator(
    share_browser: bool = True,
    headless: bool = False,  # Default False - uses Xvfb virtual display
    use_proxy: bool = True,
) -> GoogleCoordinator:
    """
    Get or create the singleton GoogleCoordinator.

    If the coordinator exists but settings differ, it will be reconfigured.

    Args:
        share_browser: If True, share browser session
        headless: Run browser in headless mode (False recommended - uses Xvfb)
        use_proxy: Use proxy pool for requests

    Returns:
        GoogleCoordinator singleton instance
    """
    global _coordinator_instance

    with _coordinator_lock:
        if _coordinator_instance is None:
            _coordinator_instance = GoogleCoordinator(
                share_browser=share_browser,
                headless=headless,
                use_proxy=use_proxy,
            )
        elif (
            _coordinator_instance.headless != headless or
            _coordinator_instance.use_proxy != use_proxy
        ):
            # Settings changed - reconfigure the coordinator
            logger.info(f"Reconfiguring GoogleCoordinator (headless={headless}, use_proxy={use_proxy})")
            _coordinator_instance.reconfigure(headless=headless, use_proxy=use_proxy)

    return _coordinator_instance


def reset_google_coordinator():
    """Reset the singleton coordinator (for testing)."""
    global _coordinator_instance

    with _coordinator_lock:
        if _coordinator_instance:
            _coordinator_instance.close()
        _coordinator_instance = None


if __name__ == "__main__":
    # Quick test
    coordinator = get_google_coordinator()
    print(f"Coordinator stats: {coordinator.get_stats()}")
    print(f"Is quarantined: {coordinator.is_quarantined()}")
    coordinator.close()
