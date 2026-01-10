"""
Base Selenium Scraper Class

Provides shared functionality for SEO scrapers using SeleniumBase (Undetected Chrome).

This is the SeleniumBase equivalent of BaseScraper, designed for sites that block
Playwright but work with SeleniumBase's UC mode.

Features:
- SeleniumBase UC browser management (better anti-detection than Playwright)
- Integration with Phase 2 services (rate limiter, robots checker, etc.)
- Human-like interactions (clicking, scrolling)
- CAPTCHA/block detection with auto-retry
- Same interface as BaseScraper for easy migration

Usage:
    class MyScraper(BaseSeleniumScraper):
        def run(self, ...):
            with self.browser_session("google.com") as driver:
                driver.get("https://google.com")
                # ... scrape content ...
"""

import os
import time
import random
import signal
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
from contextlib import contextmanager
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from seo_intelligence.services import (
    get_rate_limiter,
    get_robots_checker,
    get_proxy_manager,
    get_task_logger,
    get_content_hasher,
    get_domain_quarantine,
)
from seo_intelligence.drivers import (
    get_driver_for_site,
    get_uc_driver,
    click_element_human_like,
    # Browser escalation
    get_escalation_manager,
    should_use_camoufox,
    report_captcha,
    report_success,
    BrowserTier,
    CamoufoxDriver,
    # Browser pool
    get_browser_pool,
)
from seo_intelligence.models.artifacts import (
    PageArtifact,
    ScrapeQualityProfile,
    ArtifactStorage,
    DEFAULT_QUALITY_PROFILE,
)
from runner.logging_setup import get_logger


class BaseSeleniumScraper(ABC):
    """
    Abstract base class for SeleniumBase-powered SEO scrapers.

    Uses SeleniumBase's Undetected Chrome mode for better anti-detection
    than Playwright. Maintains the same interface as BaseScraper for
    easy migration.

    Provides:
    - Browser lifecycle management (SeleniumBase UC)
    - Rate limiting integration
    - Robots.txt compliance
    - Proxy support via existing ProxyManager
    - Error handling with retries
    """

    def __init__(
        self,
        name: str,
        tier: str = "C",
        headless: bool = None,  # None means use env var
        respect_robots: bool = True,
        use_proxy: bool = None,  # None means use env var
        max_retries: int = 3,
        page_timeout: int = 30,
        mobile_mode: bool = False,
        enable_escalation: bool = True,  # Enable browser escalation on CAPTCHA
    ):
        """
        Initialize base Selenium scraper.

        Args:
            name: Scraper name for logging
            tier: Rate limit tier (A-G, default: C)
            headless: Browser mode (None=use BROWSER_HEADLESS env var, default: false)
            respect_robots: Check robots.txt before crawling
            use_proxy: Use proxy pool (None=use PROXY_ROTATION_ENABLED env var, default: true)
            max_retries: Maximum retry attempts on failure
            page_timeout: Page load timeout in seconds
            mobile_mode: Emulate mobile device (iPhone X viewport and user agent)
            enable_escalation: Enable automatic browser escalation on CAPTCHA detection
        """
        self.name = name
        self.tier = tier

        # Read headless from env if not explicitly set
        if headless is None:
            self.headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
        else:
            self.headless = headless

        self.respect_robots = respect_robots

        # Read use_proxy from env if not explicitly set
        if use_proxy is None:
            self.use_proxy = os.getenv("PROXY_ROTATION_ENABLED", "true").lower() == "true"
        else:
            self.use_proxy = use_proxy

        self.max_retries = max_retries
        self.page_timeout = page_timeout
        self.mobile_mode = mobile_mode
        self.enable_escalation = enable_escalation

        # Initialize logger
        self.logger = get_logger(name)

        # Initialize services
        self.rate_limiter = get_rate_limiter()
        self.robots_checker = get_robots_checker()
        self.proxy_manager = get_proxy_manager()
        self.task_logger = get_task_logger()
        self.content_hasher = get_content_hasher()
        self.domain_quarantine = get_domain_quarantine()

        # Browser escalation manager (for CAPTCHA handling)
        self.escalation_manager = get_escalation_manager() if enable_escalation else None

        # Current driver instance
        self._driver = None
        self._camoufox_driver = None  # Camoufox fallback driver
        self._current_domain = None
        self._using_camoufox = False  # Track if we're using Camoufox

        # Statistics
        self.stats = {
            "pages_crawled": 0,
            "pages_skipped": 0,
            "pages_failed": 0,
            "robots_blocked": 0,
            "rate_limited": 0,
            "escalations": 0,          # Times we escalated browser
            "camoufox_used": 0,        # Times Camoufox was used
            "captchas_detected": 0,    # CAPTCHAs encountered
        }

        self.logger.info(f"{name} (Selenium) initialized (tier={tier}, headless={headless})")

    def _get_random_delay(self) -> float:
        """Get randomized delay based on tier with jitter."""
        from seo_intelligence.services.rate_limiter import TIER_CONFIGS

        config = TIER_CONFIGS.get(self.tier, TIER_CONFIGS["C"])
        delay = random.uniform(config.min_delay_seconds, config.max_delay_seconds)
        jitter = delay * random.uniform(-0.20, 0.20)
        final_delay = max(0.1, delay + jitter)

        self.logger.debug(f"Delay: {final_delay:.2f}s")
        return final_delay

    def _apply_base_delay(self):
        """Apply base delay before requests to appear human-like."""
        base_delay = random.uniform(5.0, 12.0)
        jitter = base_delay * random.uniform(-0.30, 0.30)
        final_delay = max(2.0, base_delay + jitter)

        self.logger.debug(f"Base delay: {final_delay:.2f}s")
        time.sleep(final_delay)

    def _check_robots(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt."""
        if not self.respect_robots:
            return True

        allowed = self.robots_checker.is_allowed(url)

        if not allowed:
            self.logger.warning(f"URL blocked by robots.txt: {url}")
            self.stats["robots_blocked"] += 1

        return allowed

    @contextmanager
    def _rate_limit_and_concurrency(self, domain: str):
        """Context manager for rate limiting and concurrency control."""
        self.rate_limiter.set_domain_tier(domain, self.tier)

        if not self.rate_limiter.acquire_concurrency(domain, timeout=60.0):
            self.logger.warning(f"Concurrency timeout for {domain}")
            self.stats["rate_limited"] += 1
            raise RuntimeError(f"Failed to acquire concurrency permits for {domain}")

        try:
            if not self.rate_limiter.acquire(domain, wait=True, max_wait=60.0):
                self.logger.warning(f"Rate limit timeout for {domain}")
                self.stats["rate_limited"] += 1
                raise RuntimeError(f"Failed to acquire rate limit token for {domain}")

            self._apply_base_delay()
            yield

        finally:
            self.rate_limiter.release_concurrency(domain)

    def _human_click(self, driver, element, scroll_first: bool = True):
        """Perform human-like click on element."""
        click_element_human_like(driver, element, scroll_first)

    def _human_scroll(self, driver, direction: str = "down", amount: int = None):
        """
        Simulate human-like scrolling.

        Args:
            driver: Selenium driver
            direction: "down" or "up"
            amount: Scroll amount in pixels (random if None)
        """
        try:
            if amount is None:
                amount = random.randint(200, 600)

            if direction == "up":
                amount = -amount

            driver.execute_script(f"window.scrollBy({{top: {amount}, behavior: 'smooth'}});")
            time.sleep(random.uniform(0.3, 1.0))

        except Exception as e:
            self.logger.debug(f"Scroll failed: {e}")

    def _human_type(self, driver, element, text: str, clear_first: bool = True):
        """
        Type text with human-like delays.

        Args:
            driver: Selenium driver
            element: Element to type into
            text: Text to type
            clear_first: Clear the field first
        """
        try:
            if clear_first:
                element.clear()
                time.sleep(random.uniform(0.1, 0.3))

            for char in text:
                element.send_keys(char)
                time.sleep(random.uniform(0.03, 0.12))

                # Occasional thinking pause
                if random.random() < 0.03:
                    time.sleep(random.uniform(0.2, 0.5))

            # Post-typing pause
            time.sleep(random.uniform(0.2, 0.5))

        except Exception as e:
            self.logger.debug(f"Human typing failed, using direct send: {e}")
            try:
                if clear_first:
                    element.clear()
                element.send_keys(text)
            except Exception:
                pass

    def _simulate_human_behavior(self, driver, intensity: str = "normal"):
        """
        Simulate human browsing behavior.

        Args:
            driver: Selenium driver
            intensity: "light", "normal", or "thorough"
        """
        try:
            # Initial pause
            initial_delays = {"light": (0.3, 1.0), "normal": (0.8, 2.0), "thorough": (1.5, 3.5)}
            delay_range = initial_delays.get(intensity, (0.8, 2.0))
            time.sleep(random.uniform(*delay_range))

            # Random mouse movements (via scroll)
            if intensity != "light":
                self._human_scroll(driver, "down", random.randint(100, 300))
                time.sleep(random.uniform(0.5, 1.5))

                if random.random() > 0.5:
                    self._human_scroll(driver, "up", random.randint(50, 150))
                    time.sleep(random.uniform(0.3, 0.8))

            if intensity == "thorough":
                # Additional browsing
                self._human_scroll(driver, "down", random.randint(200, 500))
                time.sleep(random.uniform(1.0, 2.5))

        except Exception as e:
            self.logger.debug(f"Human behavior simulation skipped: {e}")

    @contextmanager
    def browser_session(self, site: str = "generic"):
        """
        Context manager for SeleniumBase browser session.

        If browser pool is enabled, acquires a session from the pool.
        Otherwise falls back to creating a fresh driver.

        Gets appropriate driver for the target site with:
        - Undetected Chrome mode (uc=True)
        - Proxy rotation from existing ProxyManager
        - CAPTCHA/block detection with retry

        Usage:
            with scraper.browser_session("google") as driver:
                driver.get("https://google.com/search?q=test")
                # ... scrape ...

        Args:
            site: Target site name (google, yelp, bbb, yellowpages, gbp)
                  Used to get site-specific driver configuration.

        Yields:
            Configured SeleniumBase Driver
        """
        # Try to use browser pool if enabled
        pool = get_browser_pool()

        if pool and pool.is_enabled():
            # Use pool-based session
            yield from self._browser_session_from_pool(site, pool)
        else:
            # Fallback to direct driver creation
            yield from self._browser_session_direct(site)

    def _browser_session_from_pool(self, site: str, pool):
        """
        Get browser session from the pool.

        Args:
            site: Target site name
            pool: EnterpriseBrowserPool instance

        Yields:
            Driver from pool
        """
        lease = None
        driver = None
        session_dirty = False
        dirty_reason = None
        detected_captcha = False
        detected_block = False

        try:
            self.logger.info(f"Acquiring pool session for {site}")

            # Acquire session from pool
            lease = pool.acquire_session(
                target_domain=site,
                requester=self.name,
                timeout_seconds=60,
                lease_duration_seconds=300,
            )

            if lease is None:
                self.logger.warning(f"Pool session unavailable for {site}, falling back to direct driver")
                yield from self._browser_session_direct(site)
                return

            # Get driver from pool
            driver = pool.get_driver(lease)

            if driver is None:
                self.logger.warning(f"Pool driver unavailable for {site}, falling back to direct driver")
                pool.release_session(lease, dirty=True, dirty_reason="No driver")
                yield from self._browser_session_direct(site)
                return

            self._driver = driver
            self._current_domain = site
            self._lease = lease

            self.logger.info(f"Pool session acquired: {lease.lease_id[:8]}")

            yield driver

        except Exception as e:
            self.logger.error(f"Pool session error: {e}")
            error_str = str(e).lower()
            session_dirty = True
            dirty_reason = str(e)
            detected_captcha = "captcha" in error_str
            detected_block = "blocked" in error_str or "forbidden" in error_str
            raise

        finally:
            # Release session back to pool
            if lease:
                pool.release_session(
                    lease,
                    dirty=session_dirty,
                    dirty_reason=dirty_reason,
                    detected_captcha=detected_captcha,
                    detected_block=detected_block,
                )
                self.logger.debug(f"Pool session released: {lease.lease_id[:8]}")

            self._driver = None
            self._current_domain = None
            self._lease = None

    def _browser_session_direct(self, site: str):
        """
        Create direct browser session (fallback when pool unavailable).

        Includes PID tracking for emergency cleanup if driver.quit() fails,
        preventing Chrome process leaks.

        Args:
            site: Target site name

        Yields:
            Fresh driver
        """
        driver = None
        chrome_pid = None

        try:
            self.logger.info(f"Starting direct Selenium session for {site}")

            # Get appropriate driver for site
            driver = get_driver_for_site(
                site=site,
                headless=self.headless,
                use_proxy=self.use_proxy,
                mobile_mode=self.mobile_mode,
                retry_attempts=self.max_retries,
                wait_time=self.page_timeout,
            )

            if driver is None:
                self.logger.error(f"Failed to create driver for {site}")
                raise RuntimeError(f"Could not create driver for {site}")

            # Track Chrome PID for emergency cleanup
            # SeleniumBase stores the browser process in driver.browser_pid or service.process
            try:
                if hasattr(driver, 'browser_pid'):
                    chrome_pid = driver.browser_pid
                elif hasattr(driver, 'service') and hasattr(driver.service, 'process'):
                    chrome_pid = driver.service.process.pid
                if chrome_pid:
                    self.logger.debug(f"Tracking Chrome PID {chrome_pid} for emergency cleanup")
            except Exception:
                pass  # PID tracking is optional

            self._driver = driver
            self._current_domain = site

            yield driver

        except Exception as e:
            self.logger.error(f"Browser session error: {e}")
            raise

        finally:
            # Cleanup - try graceful quit first, then emergency kill
            quit_success = False

            if driver:
                try:
                    driver.quit()
                    quit_success = True
                    self.logger.debug("Driver closed successfully")
                except Exception as e:
                    self.logger.warning(f"Driver quit() failed: {e}")

            # Emergency cleanup: kill Chrome process if quit failed
            if not quit_success and chrome_pid:
                try:
                    os.kill(chrome_pid, signal.SIGKILL)
                    self.logger.info(f"Emergency killed Chrome PID {chrome_pid}")
                except (ProcessLookupError, PermissionError, OSError) as e:
                    self.logger.debug(f"Emergency kill failed (may already be dead): {e}")

            self._driver = None
            self._current_domain = None

    def _validate_page_response(
        self,
        driver,
        url: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate page response for CAPTCHA/block detection.

        Uses regex pattern matching for high-confidence CAPTCHA detection
        to avoid false positives from text mentions of "captcha".

        Args:
            driver: Selenium driver
            url: URL being validated

        Returns:
            Tuple of (is_valid, reason_code)
        """
        import re

        try:
            page_source = driver.page_source
            page_lower = page_source.lower()

            # High-confidence CAPTCHA patterns (element-based, not text mentions)
            captcha_patterns = [
                r'<iframe[^>]*(?:recaptcha|hcaptcha)',           # reCAPTCHA/hCaptcha iframe
                r'<div[^>]*class=["\'][^"\']*(?:g-recaptcha|h-captcha)',  # CAPTCHA div class
                r'cf-challenge-running',                          # Cloudflare challenge
                r'challenge-platform',                            # Generic challenge platform
                r'id=["\']captcha',                               # ID containing captcha
                r'data-sitekey=',                                 # reCAPTCHA/hCaptcha sitekey
            ]

            for pattern in captcha_patterns:
                if re.search(pattern, page_lower):
                    self.logger.warning(f"CAPTCHA detected via pattern: {pattern[:40]}")
                    return False, "CAPTCHA_DETECTED"

            # Blocking text indicators - only flag if page is very short (no real content)
            blocking_indicators = [
                'verify you are human',
                'security check required',
                'please complete the security check',
                'unusual traffic from your computer',
            ]

            if any(ind in page_lower for ind in blocking_indicators):
                # Only flag if page is also very short (no real content)
                if len(page_source) < 2000:
                    self.logger.warning("CAPTCHA page detected (blocking text + short page)")
                    return False, "CAPTCHA_DETECTED"

            # Bot detection indicators - more specific patterns
            bot_indicators = [
                'access denied',
                'your access to this site has been limited',
                '403 forbidden',
            ]

            for indicator in bot_indicators:
                if indicator in page_lower:
                    # Only flag if page lacks main content
                    if len(page_source) < 3000:
                        self.logger.warning(f"Bot detection: {indicator}")
                        return False, "BOT_DETECTED"

            # Check for minimal content
            if len(page_source) < 500:
                return False, "EMPTY_RESPONSE"

            return True, None

        except Exception as e:
            self.logger.error(f"Validation error: {e}")
            return False, "VALIDATION_ERROR"

    def fetch_page(
        self,
        driver,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_timeout: int = None,
        extra_wait: float = 0,
    ) -> Optional[str]:
        """
        Fetch a page with all checks and rate limiting.

        Args:
            driver: Selenium driver
            url: URL to fetch
            wait_for_selector: CSS selector to wait for (optional)
            wait_timeout: Wait timeout (uses page_timeout if None)
            extra_wait: Additional wait time after load

        Returns:
            Page source HTML or None if failed
        """
        domain = urlparse(url).netloc

        # Check quarantine
        if self.domain_quarantine.is_quarantined(domain):
            self.logger.warning(f"Domain {domain} is quarantined, skipping")
            self.stats["pages_skipped"] += 1
            return None

        # Check robots
        if not self._check_robots(url):
            self.stats["pages_skipped"] += 1
            return None

        timeout = wait_timeout or self.page_timeout
        wait = WebDriverWait(driver, timeout)

        for attempt in range(self.max_retries):
            try:
                self.logger.debug(f"Fetching {url} (attempt {attempt + 1})")

                # Navigate to URL
                driver.get(url)

                # Wait for selector if specified
                if wait_for_selector:
                    try:
                        wait.until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector))
                        )
                    except TimeoutException:
                        self.logger.warning(f"Timeout waiting for {wait_for_selector}")

                # Extra wait
                if extra_wait > 0:
                    time.sleep(extra_wait)

                # Human behavior
                self._simulate_human_behavior(driver, intensity="normal")

                # Validate response
                is_valid, reason = self._validate_page_response(driver, url)

                if not is_valid:
                    self.logger.warning(f"Page validation failed: {reason}")

                    if reason in ("CAPTCHA_DETECTED", "BOT_DETECTED"):
                        self.stats["captchas_detected"] += 1

                        # Try escalation before quarantine
                        if self.enable_escalation and self.escalation_manager:
                            self.escalation_manager.record_failure(domain, is_captcha=(reason == "CAPTCHA_DETECTED"))
                            self.stats["escalations"] += 1

                            # Check if we should try Camoufox
                            if should_use_camoufox(domain) and not self._using_camoufox:
                                self.logger.info(f"Escalating to Camoufox for {domain}")
                                camoufox_result = self._fetch_with_camoufox(
                                    url=url,
                                    wait_for_selector=wait_for_selector,
                                    extra_wait=extra_wait,
                                )
                                if camoufox_result:
                                    self.stats["camoufox_used"] += 1
                                    self.stats["pages_crawled"] += 1
                                    return camoufox_result

                        # Camoufox failed or not enabled, quarantine
                        self.domain_quarantine.quarantine_domain(
                            domain=domain,
                            reason=reason,
                            duration_minutes=60,
                        )

                    self.stats["pages_failed"] += 1
                    return None

                # Success - report to escalation manager
                if self.enable_escalation and self.escalation_manager:
                    self.escalation_manager.record_success(domain)

                self.domain_quarantine.reset_retry_attempts(domain)
                self.stats["pages_crawled"] += 1

                content = driver.page_source
                self.logger.debug(f"Fetched {url} ({len(content)} chars)")

                # Post-request delay
                time.sleep(self._get_random_delay())

                return content

            except TimeoutException as e:
                self.logger.warning(f"Timeout: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self._get_random_delay())
                continue

            except WebDriverException as e:
                self.logger.warning(f"WebDriver error: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self._get_random_delay())
                continue

            except Exception as e:
                self.logger.error(f"Error fetching {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self._get_random_delay())
                continue

        # All retries failed
        self.stats["pages_failed"] += 1
        self.logger.error(f"Failed to fetch {url} after {self.max_retries} attempts")
        return None

    def _fetch_with_camoufox(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        extra_wait: float = 0,
    ) -> Optional[str]:
        """
        Fetch a page using Camoufox (Firefox-based undetected browser).

        This is used as a fallback when SeleniumBase UC gets CAPTCHA'd.

        Args:
            url: URL to fetch
            wait_for_selector: CSS selector to wait for
            extra_wait: Additional wait time

        Returns:
            Page HTML or None if failed
        """
        domain = urlparse(url).netloc

        try:
            self.logger.info(f"Attempting Camoufox fetch for {url}")
            self._using_camoufox = True

            # Get escalation state for this domain
            state = self.escalation_manager.get_state(domain) if self.escalation_manager else None
            new_fingerprint = state and state.current_tier == BrowserTier.CAMOUFOX_NEW_FP

            # Create Camoufox driver
            driver = CamoufoxDriver(
                headless=self.headless,
                humanize=True,
                new_fingerprint=new_fingerprint,
                page_timeout=self.page_timeout * 1000,  # Convert to ms
            )

            try:
                # Fetch the page
                artifact = driver.fetch_page(
                    url=url,
                    wait_for_selector=wait_for_selector,
                    extra_wait=extra_wait,
                )

                if artifact is None:
                    self.logger.warning("Camoufox fetch returned None")
                    return None

                # Check for CAPTCHA/block
                if artifact.detected_captcha:
                    self.logger.warning("Camoufox also got CAPTCHA'd")
                    if self.escalation_manager:
                        self.escalation_manager.record_failure(domain, is_captcha=True)
                    return None

                if artifact.detected_block:
                    self.logger.warning("Camoufox got blocked")
                    if self.escalation_manager:
                        self.escalation_manager.record_failure(domain, is_captcha=False)
                    return None

                # Success!
                self.logger.info(f"Camoufox successfully fetched {url} ({len(artifact.html)} chars)")
                if self.escalation_manager:
                    self.escalation_manager.record_success(domain)

                return artifact.html

            finally:
                driver.close()

        except Exception as e:
            self.logger.error(f"Camoufox fetch error: {e}")
            return None

        finally:
            self._using_camoufox = False

    def fetch_page_with_artifact(
        self,
        driver,
        url: str,
        quality_profile: Optional[ScrapeQualityProfile] = None,
        save_artifact: bool = False,
        wait_for_selector: Optional[str] = None,
    ) -> Optional[PageArtifact]:
        """
        Fetch a page and capture comprehensive artifacts for later re-parsing.

        This method captures raw HTML, screenshots, console logs, and metadata
        so data can be re-parsed offline without re-scraping.

        Args:
            driver: Selenium driver
            url: URL to fetch
            quality_profile: Quality settings (defaults to DEFAULT_QUALITY_PROFILE)
            save_artifact: Whether to persist artifact to disk
            wait_for_selector: CSS selector to wait for before capturing

        Returns:
            PageArtifact with all captured data, or None if fetch failed
        """
        from datetime import datetime, timezone
        import base64

        profile = quality_profile or DEFAULT_QUALITY_PROFILE
        domain = urlparse(url).netloc
        start_time = time.time()

        # Check quarantine
        if self.domain_quarantine.is_quarantined(domain):
            self.logger.warning(f"Domain {domain} is quarantined, skipping")
            self.stats["pages_skipped"] += 1
            return None

        # Check robots
        if not self._check_robots(url):
            self.stats["pages_skipped"] += 1
            return None

        # Initialize artifact
        artifact = PageArtifact(
            url=url,
            final_url=url,
            engine="selenium",
            quality_profile=profile.to_dict(),
            user_agent=driver.execute_script("return navigator.userAgent;") if driver else None,
            viewport={
                "width": profile.viewport_width,
                "height": profile.viewport_height,
            },
        )

        timeout = profile.navigation_timeout // 1000  # Convert ms to seconds
        wait = WebDriverWait(driver, timeout)

        for attempt in range(profile.max_retries):
            try:
                self.logger.debug(f"Fetching with artifact: {url} (attempt {attempt + 1})")

                # Navigate to URL
                driver.get(url)

                # Update final URL after redirects
                artifact.final_url = driver.current_url

                # Wait for selector if specified
                if wait_for_selector:
                    try:
                        wait.until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector))
                        )
                    except TimeoutException:
                        self.logger.warning(f"Timeout waiting for {wait_for_selector}")

                # Wait based on strategy
                if profile.wait_strategy == "networkidle":
                    # Selenium doesn't have networkidle, so we wait longer
                    time.sleep(3.0)
                elif profile.wait_strategy == "load":
                    wait.until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )

                # Extra wait
                if profile.extra_wait_seconds > 0:
                    time.sleep(profile.extra_wait_seconds)

                # Scroll page if configured
                if profile.scroll_page:
                    self._scroll_page_for_artifact(driver, profile)

                # Capture console errors if available
                if profile.capture_console:
                    try:
                        logs = driver.get_log('browser')
                        for entry in logs:
                            level = entry.get('level', '')
                            message = entry.get('message', '')
                            if level == 'SEVERE':
                                artifact.console_errors.append(message)
                            elif level == 'WARNING':
                                artifact.console_warnings.append(message)
                    except Exception as e:
                        self.logger.debug(f"Could not capture console logs: {e}")

                # Human behavior
                self._simulate_human_behavior(driver, intensity="normal")

                # Validate response
                is_valid, reason = self._validate_page_response(driver, url)

                if not is_valid:
                    self.logger.warning(f"Page validation failed: {reason}")
                    artifact.detected_captcha = reason == "CAPTCHA_DETECTED"
                    artifact.detected_login_wall = reason == "BOT_DETECTED"

                    if reason in ("CAPTCHA_DETECTED", "BOT_DETECTED"):
                        self.domain_quarantine.quarantine_domain(
                            domain=domain,
                            reason=reason,
                            duration_minutes=60,
                        )

                    # Still capture what we can
                    artifact.html_raw = driver.page_source
                    artifact.status_code = 403 if reason == "BOT_DETECTED" else 429
                    artifact.fetch_duration_ms = int((time.time() - start_time) * 1000)

                    self.stats["pages_failed"] += 1

                    if save_artifact:
                        storage = ArtifactStorage()
                        storage.save(artifact)

                    return artifact

                # Success - capture all artifacts
                artifact.status_code = 200

                # Capture HTML
                if profile.capture_html:
                    artifact.html_raw = driver.page_source

                # Check for consent overlay
                artifact.detected_consent_overlay = self._detect_consent_overlay_selenium(driver)

                # Capture screenshot
                if profile.capture_screenshot:
                    try:
                        # Full page screenshot
                        screenshot_data = driver.get_screenshot_as_png()
                        if screenshot_data and save_artifact:
                            storage = ArtifactStorage()
                            artifact_dir = storage._get_artifact_dir(artifact)
                            screenshot_path = artifact_dir / "screenshot.png"
                            with open(screenshot_path, 'wb') as f:
                                f.write(screenshot_data)
                            artifact.screenshot_path = str(screenshot_path)
                    except Exception as e:
                        self.logger.debug(f"Screenshot capture failed: {e}")

                # Compute fetch duration
                artifact.fetch_duration_ms = int((time.time() - start_time) * 1000)

                # Update stats
                self.domain_quarantine.reset_retry_attempts(domain)
                self.stats["pages_crawled"] += 1

                self.logger.debug(
                    f"Fetched artifact for {url} ({artifact.html_size_bytes} bytes, "
                    f"{artifact.fetch_duration_ms}ms)"
                )

                # Save artifact if requested
                if save_artifact:
                    storage = ArtifactStorage()
                    artifact_path = storage.save(artifact)
                    self.logger.debug(f"Artifact saved to {artifact_path}")

                # Post-request delay
                time.sleep(self._get_random_delay())

                return artifact

            except TimeoutException as e:
                self.logger.warning(f"Timeout: {e}")
                if attempt < profile.max_retries - 1:
                    time.sleep(self._get_random_delay())
                continue

            except WebDriverException as e:
                self.logger.warning(f"WebDriver error: {e}")
                if attempt < profile.max_retries - 1:
                    time.sleep(self._get_random_delay())
                continue

            except Exception as e:
                self.logger.error(f"Error fetching artifact for {url}: {e}")
                if attempt < profile.max_retries - 1:
                    time.sleep(self._get_random_delay())
                continue

        # All retries failed
        artifact.fetch_duration_ms = int((time.time() - start_time) * 1000)
        self.stats["pages_failed"] += 1
        self.logger.error(f"Failed to fetch artifact for {url} after {profile.max_retries} attempts")

        if save_artifact:
            storage = ArtifactStorage()
            storage.save(artifact)

        return artifact

    def _scroll_page_for_artifact(self, driver, profile: ScrapeQualityProfile):
        """
        Scroll through page to trigger lazy loading.

        Args:
            driver: Selenium driver
            profile: Quality profile with scroll settings
        """
        try:
            viewport_height = driver.execute_script("return window.innerHeight")
            total_height = driver.execute_script("return document.body.scrollHeight")

            scroll_increment = viewport_height * 0.8
            current_position = 0

            for step in range(profile.scroll_steps):
                current_position += scroll_increment

                driver.execute_script(f"window.scrollTo({{top: {current_position}, behavior: 'smooth'}});")
                time.sleep(profile.scroll_delay)

                # Check if we've reached the bottom
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height > total_height:
                    total_height = new_height

                if current_position >= total_height:
                    break

            # Scroll back to top
            driver.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
            time.sleep(0.5)

        except Exception as e:
            self.logger.debug(f"Scroll for artifact failed: {e}")

    def _detect_consent_overlay_selenium(self, driver) -> bool:
        """
        Detect common consent/cookie overlays.

        Args:
            driver: Selenium driver

        Returns:
            True if consent overlay detected
        """
        try:
            page_source = driver.page_source.lower()
            consent_indicators = [
                'cookie-consent',
                'cookie-banner',
                'cookieconsent',
                'gdpr-consent',
                'privacy-consent',
                'consent-dialog',
                'cookie-notice',
                'accept cookies',
                'we use cookies',
            ]

            for indicator in consent_indicators:
                if indicator in page_source:
                    return True

            # Check for common consent overlay selectors
            consent_selectors = [
                '#cookie-consent',
                '.cookie-banner',
                '[class*="cookie-consent"]',
                '[class*="gdpr"]',
                '#onetrust-banner-sdk',
                '.cc-banner',
            ]

            for selector in consent_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements and any(e.is_displayed() for e in elements):
                        return True
                except Exception:
                    continue

            return False

        except Exception as e:
            self.logger.debug(f"Consent detection failed: {e}")
            return False

    def wait_for_element(
        self,
        driver,
        selector: str,
        by: By = By.CSS_SELECTOR,
        timeout: int = None,
        condition: str = "presence"
    ):
        """
        Wait for an element with various conditions.

        Args:
            driver: Selenium driver or CamoufoxSeleniumWrapper
            selector: Element selector
            by: Selector type (By.CSS_SELECTOR, By.XPATH, etc.)
            timeout: Wait timeout
            condition: "presence", "visible", "clickable"

        Returns:
            Element if found, None otherwise
        """
        timeout = timeout or self.page_timeout

        # Check if this is a Camoufox wrapper (Playwright-based)
        if hasattr(driver, 'wait_for_element') and 'CamoufoxSeleniumWrapper' in type(driver).__name__:
            # Use Playwright's native wait_for_selector
            state_map = {
                "presence": "attached",
                "visible": "visible",
                "clickable": "visible",  # Playwright doesn't have clickable, use visible
            }
            state = state_map.get(condition, "visible")
            # Convert timeout to milliseconds for Playwright
            timeout_ms = timeout * 1000 if timeout < 1000 else timeout
            return driver.wait_for_element(selector, timeout=timeout_ms, state=state)

        # Standard Selenium WebDriverWait
        wait = WebDriverWait(driver, timeout)

        conditions = {
            "presence": EC.presence_of_element_located,
            "visible": EC.visibility_of_element_located,
            "clickable": EC.element_to_be_clickable,
        }

        ec_condition = conditions.get(condition, EC.presence_of_element_located)

        try:
            return wait.until(ec_condition((by, selector)))
        except TimeoutException:
            return None

    def find_elements(
        self,
        driver,
        selector: str,
        by: By = By.CSS_SELECTOR
    ):
        """Find all matching elements."""
        try:
            # Camoufox wrapper uses (by, value) format for find_elements
            if 'CamoufoxSeleniumWrapper' in type(driver).__name__:
                return driver.find_elements(str(by), selector)
            return driver.find_elements(by, selector)
        except Exception:
            return []

    def get_text(self, element) -> str:
        """Get element text safely."""
        try:
            return element.text.strip() if element else ""
        except Exception:
            return ""

    def get_attribute(self, element, attr: str) -> Optional[str]:
        """Get element attribute safely."""
        try:
            return element.get_attribute(attr) if element else None
        except Exception:
            return None

    def get_stats(self) -> Dict[str, int]:
        """Get scraper statistics."""
        return self.stats.copy()

    def reset_stats(self):
        """Reset scraper statistics."""
        self.stats = {
            "pages_crawled": 0,
            "pages_skipped": 0,
            "pages_failed": 0,
            "robots_blocked": 0,
            "rate_limited": 0,
        }

    @abstractmethod
    def run(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Run the scraper.

        Subclasses must implement this method.

        Returns:
            dict: Results of the scraping operation
        """
        pass
