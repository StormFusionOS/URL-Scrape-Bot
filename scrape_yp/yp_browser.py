#!/usr/bin/env python3
"""
Yellow Pages browser automation using Playwright with advanced stealth mode.

This module provides browser-based scraping for Yellow Pages with enhanced
anti-detection techniques to bypass 403 Forbidden errors and bot protection.

Features:
- Persistent browser instance (reuses browser across requests)
- playwright-stealth integration for maximum anti-detection
- Exponential backoff on 403 errors
- Human-like behavior simulation
- Randomized browser fingerprints
"""
from __future__ import annotations
import time
import os
import random
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
from playwright_stealth import stealth_sync

from runner.logging_setup import get_logger

logger = get_logger("yp_browser")


class YellowPagesBrowser:
    """
    Browser automation for Yellow Pages scraping with advanced anti-detection.

    Uses Playwright with stealth mode to make requests indistinguishable from
    real browser traffic.
    """

    def __init__(self, headless: bool = True, timeout: int = 60000):
        """
        Initialize browser automation with anti-detection.

        Args:
            headless: Run browser in headless mode (default: True)
            timeout: Page load timeout in milliseconds (default: 60s)
        """
        self.headless = headless
        self.timeout = timeout
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context = None
        self.pages_loaded = 0
        self.consecutive_403s = 0  # Track consecutive 403 errors for backoff

        # Session persistence directory
        self.session_dir = Path(__file__).parent.parent / "data" / "browser_sessions" / "yp"
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        """Context manager entry - start browser."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close browser."""
        self.close()

    def start(self):
        """Start Playwright with stealth mode and persistent session."""
        if self.playwright is None:
            logger.info("[YP Browser] Starting Playwright with stealth mode")
            self.playwright = sync_playwright().start()

            # Enhanced browser args for Yellow Pages anti-detection
            browser_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-setuid-sandbox',
                '--no-first-run',
                '--no-default-browser-check',
                '--password-store=basic',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-client-side-phishing-detection',
                '--disable-hang-monitor',
                '--disable-popup-blocking',
                '--disable-prompt-on-repost',
                '--disable-sync',
                '--metrics-recording-only',
                '--no-pings',
            ]

            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=browser_args
            )

            # Randomize viewport (simulate different screen sizes)
            viewports = [
                {'width': 1920, 'height': 1080},
                {'width': 1366, 'height': 768},
                {'width': 1536, 'height': 864},
                {'width': 1440, 'height': 900},
                {'width': 1680, 'height': 1050},
            ]

            # Randomize user agent
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            ]

            # Randomize timezone
            timezones = [
                'America/New_York',
                'America/Chicago',
                'America/Denver',
                'America/Los_Angeles',
                'America/Phoenix',
                'America/Detroit',
            ]

            # Randomize geolocation (US cities)
            geolocations = [
                {'latitude': 40.7128, 'longitude': -74.0060},  # New York
                {'latitude': 34.0522, 'longitude': -118.2437},  # Los Angeles
                {'latitude': 41.8781, 'longitude': -87.6298},  # Chicago
                {'latitude': 29.7604, 'longitude': -95.3698},  # Houston
                {'latitude': 33.4484, 'longitude': -112.0740},  # Phoenix
            ]

            # Create persistent context with randomized settings
            self.context = self.browser.new_context(
                viewport=random.choice(viewports),
                user_agent=random.choice(user_agents),
                locale='en-US',
                timezone_id=random.choice(timezones),
                permissions=['geolocation'],
                geolocation=random.choice(geolocations),
                color_scheme='light',
                device_scale_factor=random.choice([1, 1.25, 1.5, 2]),
                has_touch=False,
                is_mobile=False,
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                }
            )

            logger.info("[YP Browser] Browser launched with anti-detection")

    def close(self):
        """Close browser context and Playwright."""
        if self.context:
            self.context.close()
            self.context = None
        if self.browser:
            logger.info(f"[YP Browser] Closing browser (loaded {self.pages_loaded} pages, {self.consecutive_403s} consecutive 403s)")
            self.browser.close()
            self.browser = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None

    def fetch_page(
        self,
        url: str,
        wait_for_selector: str = None,
        min_delay: int = 3,
        max_delay: int = 7
    ) -> Optional[str]:
        """
        Fetch a page using Playwright with stealth mode and exponential backoff on 403.

        Args:
            url: URL to fetch
            wait_for_selector: CSS selector to wait for before extracting HTML
            min_delay: Minimum delay in seconds after page load (default: 3s)
            max_delay: Maximum delay in seconds after page load (default: 7s)

        Returns:
            Page HTML content or None if failed
        """
        if not self.context:
            self.start()

        page: Page = None
        max_retries = 5

        for attempt in range(max_retries):
            try:
                # Calculate exponential backoff for 403 errors
                if self.consecutive_403s > 0:
                    # Aggressive backoff: 10, 20, 40, 80, 160 seconds
                    backoff_delay = 10 * (2 ** self.consecutive_403s)
                    logger.warning(f"[YP Browser] {self.consecutive_403s} consecutive 403s detected. Backing off for {backoff_delay}s before retry {attempt + 1}/{max_retries}")
                    time.sleep(backoff_delay)

                # Create new page from context
                page = self.context.new_page()

                # Apply stealth mode to hide automation
                stealth_sync(page)

                # Add additional anti-detection scripts
                page.add_init_script("""
                    // Remove webdriver property
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });

                    // Override permissions API
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );

                    // Add realistic plugins
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [
                            {
                                name: 'Chrome PDF Plugin',
                                description: 'Portable Document Format',
                                filename: 'internal-pdf-viewer'
                            },
                            {
                                name: 'Chrome PDF Viewer',
                                description: '',
                                filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'
                            },
                            {
                                name: 'Native Client',
                                description: '',
                                filename: 'internal-nacl-plugin'
                            }
                        ]
                    });

                    // Randomize canvas fingerprint
                    const getParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {
                        if (parameter === 37445) {
                            return 'Intel Inc.';
                        }
                        if (parameter === 37446) {
                            return 'Intel Iris OpenGL Engine';
                        }
                        return getParameter.call(this, parameter);
                    };
                """)

                logger.info(f"[YP Browser] Loading {url}")

                # Random delay before navigation (human-like behavior)
                time.sleep(random.uniform(1, 2.5))

                # Navigate to URL with timeout
                response = page.goto(url, wait_until='domcontentloaded', timeout=self.timeout)

                # Check for 403 Forbidden
                if response and response.status == 403:
                    self.consecutive_403s += 1
                    logger.error(f"[YP Browser] 403 Forbidden (attempt {attempt + 1}/{max_retries}, consecutive 403s: {self.consecutive_403s})")
                    page.close()

                    if attempt < max_retries - 1:
                        # Calculate immediate retry backoff
                        retry_backoff = 5 * (2 ** attempt)  # 5, 10, 20, 40 seconds
                        logger.info(f"[YP Browser] Retrying in {retry_backoff}s...")
                        time.sleep(retry_backoff)
                        continue
                    else:
                        logger.error("[YP Browser] Max retries reached for 403 error")
                        return None

                # Reset consecutive 403 counter on success
                if self.consecutive_403s > 0:
                    logger.info(f"[YP Browser] Success after {self.consecutive_403s} consecutive 403s - resetting counter")
                    self.consecutive_403s = 0

                # Wait a moment for JavaScript to execute
                logger.debug("[YP Browser] Waiting for page to settle...")
                time.sleep(random.uniform(2, 4))

                # Wait for specific selector if provided
                if wait_for_selector:
                    try:
                        logger.debug(f"[YP Browser] Waiting for selector: {wait_for_selector}")
                        page.wait_for_selector(wait_for_selector, timeout=15000)
                        logger.debug(f"[YP Browser] Selector found: {wait_for_selector}")
                    except PlaywrightTimeout:
                        logger.warning(f"[YP Browser] Timeout waiting for selector: {wait_for_selector}")
                        # Continue anyway - page might have loaded

                # Simulate human behavior
                self._simulate_human_behavior(page)

                # Additional delay to ensure JavaScript has executed
                delay = random.uniform(min_delay, max_delay)
                logger.debug(f"[YP Browser] Additional delay: {delay:.1f}s")
                time.sleep(delay)

                # Extract HTML
                html = page.content()
                self.pages_loaded += 1

                logger.info(f"[YP Browser] Page loaded successfully ({len(html)} chars)")
                return html

            except PlaywrightTimeout as e:
                logger.error(f"[YP Browser] Timeout loading {url}: {e}")
                if page:
                    # Try to get HTML even if timeout
                    try:
                        html = page.content()
                        if len(html) > 1000:
                            logger.info(f"[YP Browser] Partial page loaded ({len(html)} chars)")
                            return html
                    except:
                        pass

                if attempt < max_retries - 1:
                    backoff = 5 * (2 ** attempt)
                    logger.info(f"[YP Browser] Retrying in {backoff}s...")
                    time.sleep(backoff)
                    continue
                return None

            except Exception as e:
                logger.error(f"[YP Browser] Error loading {url}: {e}", exc_info=True)
                if attempt < max_retries - 1:
                    backoff = 5 * (2 ** attempt)
                    logger.info(f"[YP Browser] Retrying in {backoff}s...")
                    time.sleep(backoff)
                    continue
                return None

            finally:
                if page:
                    page.close()

        return None

    def _simulate_human_behavior(self, page: Page):
        """
        Simulate human-like behavior on the page.

        Args:
            page: Playwright page object
        """
        try:
            # Random scrolling pattern
            scroll_positions = [
                random.randint(100, 400),
                random.randint(500, 900),
                random.randint(1000, 1500),
                random.randint(800, 1200),
                random.randint(200, 600),
                0  # Scroll back to top
            ]

            for position in scroll_positions:
                page.evaluate(f"window.scrollTo({{top: {position}, behavior: 'smooth'}})")
                time.sleep(random.uniform(0.3, 0.8))

            # Random mouse movements
            for _ in range(random.randint(3, 6)):
                x = random.randint(100, 1200)
                y = random.randint(100, 800)
                page.mouse.move(x, y)
                time.sleep(random.uniform(0.1, 0.3))

            # Occasionally hover over elements (without clicking)
            try:
                # Try to find some business listings
                listings = page.query_selector_all('div.result, div.srp-listing, div.organic')
                if listings and len(listings) > 0:
                    # Hover over a random listing
                    random_listing = random.choice(listings[:min(5, len(listings))])
                    random_listing.hover()
                    time.sleep(random.uniform(0.5, 1.5))
            except:
                pass  # Ignore hover errors

        except Exception as e:
            logger.debug(f"[YP Browser] Error simulating human behavior: {e}")
            # Ignore errors in behavior simulation


# Global browser instance for reuse across requests
_browser_instance: Optional[YellowPagesBrowser] = None


def get_yp_browser() -> YellowPagesBrowser:
    """Get or create global YP browser instance."""
    global _browser_instance
    if _browser_instance is None:
        _browser_instance = YellowPagesBrowser(headless=True)
        _browser_instance.start()
    return _browser_instance


def close_global_yp_browser():
    """Close the global YP browser instance."""
    global _browser_instance
    if _browser_instance:
        _browser_instance.close()
        _browser_instance = None
