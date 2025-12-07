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
        headless: bool = True,
        respect_robots: bool = True,
        use_proxy: bool = True,  # Enabled by default (unlike Playwright version)
        max_retries: int = 3,
        page_timeout: int = 30,
    ):
        """
        Initialize base Selenium scraper.

        Args:
            name: Scraper name for logging
            tier: Rate limit tier (A-G, default: C)
            headless: Default browser mode
            respect_robots: Check robots.txt before crawling
            use_proxy: Use proxy pool (recommended for SEO scraping)
            max_retries: Maximum retry attempts on failure
            page_timeout: Page load timeout in seconds
        """
        self.name = name
        self.tier = tier
        self.headless = headless
        self.respect_robots = respect_robots
        self.use_proxy = use_proxy
        self.max_retries = max_retries
        self.page_timeout = page_timeout

        # Initialize logger
        self.logger = get_logger(name)

        # Initialize services
        self.rate_limiter = get_rate_limiter()
        self.robots_checker = get_robots_checker()
        self.proxy_manager = get_proxy_manager()
        self.task_logger = get_task_logger()
        self.content_hasher = get_content_hasher()
        self.domain_quarantine = get_domain_quarantine()

        # Current driver instance
        self._driver = None
        self._current_domain = None

        # Statistics
        self.stats = {
            "pages_crawled": 0,
            "pages_skipped": 0,
            "pages_failed": 0,
            "robots_blocked": 0,
            "rate_limited": 0,
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
        driver = None

        try:
            self.logger.info(f"Starting Selenium session for {site}")

            # Get appropriate driver for site
            driver = get_driver_for_site(
                site=site,
                headless=self.headless,
                use_proxy=self.use_proxy,
                retry_attempts=self.max_retries,
                wait_time=self.page_timeout,
            )

            if driver is None:
                self.logger.error(f"Failed to create driver for {site}")
                raise RuntimeError(f"Could not create driver for {site}")

            self._driver = driver
            self._current_domain = site

            yield driver

        except Exception as e:
            self.logger.error(f"Browser session error: {e}")
            raise

        finally:
            # Cleanup
            if driver:
                try:
                    driver.quit()
                    self.logger.debug("Driver closed")
                except Exception as e:
                    self.logger.debug(f"Driver cleanup error: {e}")

            self._driver = None
            self._current_domain = None

    def _validate_page_response(
        self,
        driver,
        url: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate page response for CAPTCHA/block detection.

        Args:
            driver: Selenium driver
            url: URL being validated

        Returns:
            Tuple of (is_valid, reason_code)
        """
        try:
            page_source = driver.page_source.lower()

            # CAPTCHA indicators
            captcha_indicators = [
                'captcha', 'recaptcha', 'g-recaptcha', 'hcaptcha',
                'cf-challenge', 'please verify you are human',
                'security check', 'unusual traffic',
            ]

            for indicator in captcha_indicators:
                if indicator in page_source:
                    self.logger.warning(f"CAPTCHA detected: {indicator}")
                    return False, "CAPTCHA_DETECTED"

            # Bot detection indicators
            bot_indicators = [
                'access denied', 'blocked', 'forbidden',
                'your access to this site has been limited',
                'enable javascript', 'please enable cookies',
            ]

            for indicator in bot_indicators:
                if indicator in page_source:
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
                        self.domain_quarantine.quarantine_domain(
                            domain=domain,
                            reason=reason,
                            duration_minutes=60,
                        )

                    self.stats["pages_failed"] += 1
                    return None

                # Success
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
            driver: Selenium driver
            selector: Element selector
            by: Selector type (By.CSS_SELECTOR, By.XPATH, etc.)
            timeout: Wait timeout
            condition: "presence", "visible", "clickable"

        Returns:
            Element if found, None otherwise
        """
        timeout = timeout or self.page_timeout
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
