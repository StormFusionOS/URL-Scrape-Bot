"""
Google Business Scraper - Playwright Client

Extremely cautious Playwright-based scraper for Google Maps/Business.
NO API calls - pure browser automation with anti-detection measures.

Features:
- Conservative rate limiting (30-60s delays)
- Human behavior simulation
- Browser fingerprint randomization
- Quality scoring
- Comprehensive error handling

Author: washdb-bot
Date: 2025-11-10
"""

import asyncio
import random
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Error as PlaywrightError

from .google_logger import GoogleScraperLogger
from .google_config import GoogleConfig
from .google_stealth import (
    StealthConfig,
    apply_stealth,
    human_like_delay,
    random_mouse_movement,
    human_like_scroll,
    human_like_type,
    check_for_captcha,
    wait_with_jitter,
    random_page_interactions
)


class GoogleBusinessClient:
    """
    Playwright-based Google Maps/Business scraper with extreme caution.

    This client uses browser automation to scrape Google Maps search results
    and business details without using any APIs or proxies.
    """

    def __init__(self, config: GoogleConfig = None, logger: GoogleScraperLogger = None):
        """
        Initialize the Google Business scraper client.

        Args:
            config: GoogleConfig instance (uses default if None)
            logger: GoogleScraperLogger instance (creates new if None)
        """
        self.config = config or GoogleConfig.from_env()
        self.logger = logger or GoogleScraperLogger(log_dir=self.config.log_dir)

        # Initialize stealth configuration
        self.stealth_config = StealthConfig() if self.config.stealth.enabled else None

        # Playwright objects
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # Session tracking
        self.requests_this_session = 0
        self.start_time = time.time()

        # Statistics
        self.stats = {
            "searches_performed": 0,
            "businesses_scraped": 0,
            "errors": 0,
            "captchas_detected": 0
        }

        # Initialize screenshot directory
        if self.config.scraping.screenshot_on_error:
            Path(self.config.scraping.screenshot_dir).mkdir(parents=True, exist_ok=True)

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def start(self):
        """Initialize Playwright browser and context."""
        try:
            self.logger.operation_started("browser_initialization")

            # Start Playwright
            self.playwright = await async_playwright().start()

            # Get browser type
            if self.config.playwright.browser_type == "firefox":
                browser_type = self.playwright.firefox
            elif self.config.playwright.browser_type == "webkit":
                browser_type = self.playwright.webkit
            else:
                browser_type = self.playwright.chromium

            # Determine context settings
            if self.stealth_config and self.config.stealth.randomize_viewport:
                viewport = self.stealth_config.viewport
            else:
                viewport = self.config.playwright.get_randomized_viewport()

            if self.stealth_config and self.config.stealth.randomize_user_agent:
                user_agent = self.stealth_config.user_agent
            else:
                user_agent = self.config.playwright.get_random_user_agent()

            # Use stealth timezone if randomization is enabled
            if self.stealth_config and self.config.stealth.randomize_timezone:
                timezone_id = self.stealth_config.timezone
            else:
                timezone_id = self.config.playwright.timezone

            # Create persistent or ephemeral context
            if self.config.playwright.use_persistent_profile:
                self.logger.info(f"Using persistent browser profile: {self.config.playwright.profile_dir}")

                # Create profile directory if it doesn't exist
                from pathlib import Path
                profile_path = Path(self.config.playwright.profile_dir)
                profile_path.mkdir(parents=True, exist_ok=True)

                # Launch persistent context (browser + context combined)
                self.context = await browser_type.launch_persistent_context(
                    str(profile_path),
                    headless=self.config.playwright.headless,
                    args=self.config.playwright.browser_args,
                    viewport=viewport,
                    user_agent=user_agent,
                    locale=self.config.playwright.locale,
                    timezone_id=timezone_id,
                    geolocation={
                        "latitude": self.config.playwright.latitude,
                        "longitude": self.config.playwright.longitude
                    } if self.config.playwright.latitude else None,
                    permissions=["geolocation"] if self.config.playwright.latitude else []
                )
                self.browser = None  # Not used with persistent context

            else:
                # Launch browser with anti-detection arguments (ephemeral)
                self.browser = await browser_type.launch(
                    headless=self.config.playwright.headless,
                    args=self.config.playwright.browser_args
                )

                # Create context with randomized settings
                self.context = await self.browser.new_context(
                    viewport=viewport,
                    user_agent=user_agent,
                    locale=self.config.playwright.locale,
                    timezone_id=timezone_id,
                    geolocation={
                        "latitude": self.config.playwright.latitude,
                        "longitude": self.config.playwright.longitude
                    } if self.config.playwright.latitude else None,
                    permissions=["geolocation"] if self.config.playwright.latitude else []
                )

            # Set default timeouts
            self.context.set_default_navigation_timeout(self.config.playwright.navigation_timeout)
            self.context.set_default_timeout(self.config.playwright.default_timeout)

            # Apply stealth measures to context if enabled
            if self.stealth_config and self.config.stealth.enabled:
                await apply_stealth(self.context, self.stealth_config)
                self.logger.info("Stealth measures applied to browser context")

            # Create page
            self.page = await self.context.new_page()

            # Inject anti-detection scripts (fallback if stealth not enabled)
            if not self.stealth_config:
                await self._inject_anti_detection()

            self.logger.operation_completed("browser_initialization", "success")
            self.logger.info("Playwright browser initialized", {
                "browser": self.config.playwright.browser_type,
                "headless": self.config.playwright.headless,
                "viewport": viewport
            })

        except Exception as e:
            self.logger.error("Failed to initialize browser", error=e)
            raise

    async def _inject_anti_detection(self):
        """Inject JavaScript to mask automation detection."""
        await self.page.add_init_script("""
            // Overwrite the `navigator.webdriver` property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Overwrite the `plugins` property
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Overwrite the `languages` property
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Remove Playwright-specific properties
            delete window.playwright;
            delete window.__playwright;
        """)

    async def close(self):
        """Clean up and close browser."""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

            duration_minutes = (time.time() - self.start_time) / 60
            self.logger.info("Browser closed", {
                "session_duration_minutes": round(duration_minutes, 2),
                "stats": self.stats
            })

        except Exception as e:
            self.logger.error("Error closing browser", error=e)

    async def _wait_rate_limit(self):
        """Wait for rate limit with logging and jitter if stealth enabled."""
        wait_seconds = self.config.rate_limit.get_request_delay()
        self.logger.rate_limit_wait(wait_seconds, "between_requests")

        # Use wait with jitter if stealth is enabled
        if self.stealth_config and self.config.stealth.enable_random_jitter:
            await wait_with_jitter(wait_seconds, self.config.stealth.jitter_factor)
        else:
            await asyncio.sleep(wait_seconds)

        self.requests_this_session += 1

    async def _check_session_break(self):
        """Check if we need a session break."""
        if self.requests_this_session >= self.config.rate_limit.max_requests_per_session:
            break_seconds = self.config.rate_limit.get_session_break()
            self.logger.rate_limit_wait(break_seconds, "session_break")
            self.logger.warning(f"Session break: {break_seconds}s after {self.requests_this_session} requests")
            await asyncio.sleep(break_seconds)
            self.requests_this_session = 0

    async def _simulate_human_behavior(self):
        """Simulate human-like behavior on the page using stealth utilities."""
        if not self.config.scraping.simulate_mouse_movement:
            return

        try:
            # Use stealth module's human-like behaviors if enabled
            if self.stealth_config and self.config.stealth.simulate_mouse_movements:
                await random_mouse_movement(self.page)
            else:
                # Fallback to basic mouse movements
                for _ in range(random.randint(1, 3)):
                    x = random.randint(100, 800)
                    y = random.randint(100, 600)
                    await self.page.mouse.move(x, y)
                    await asyncio.sleep(random.uniform(0.1, 0.3))

            # Random page interactions (stealth module)
            if self.stealth_config and self.config.stealth.simulate_random_scrolling:
                await random_page_interactions(self.page)

            # Simulate reading time with jitter if stealth enabled
            if self.config.scraping.simulate_reading_time:
                if self.stealth_config and self.config.stealth.simulate_reading_delays:
                    reading_delay_ms = random.uniform(
                        self.config.stealth.reading_delay_min,
                        self.config.stealth.reading_delay_max
                    )
                    await asyncio.sleep(reading_delay_ms / 1000)
                else:
                    reading_time = self.config.scraping.get_reading_time()
                    await asyncio.sleep(reading_time)

        except Exception as e:
            self.logger.debug("Error simulating human behavior", {"error": str(e)})

    async def _scroll_page(self, scrolls: int = None):
        """
        Scroll the page gradually to trigger lazy loading using stealth utilities.

        Args:
            scrolls: Number of scrolls (uses config default if None)
        """
        if not self.config.scraping.enable_scrolling:
            return

        scrolls = scrolls or self.config.scraping.max_scrolls

        try:
            # Use stealth module's human-like scroll if enabled
            if self.stealth_config and self.config.stealth.simulate_random_scrolling:
                for i in range(scrolls):
                    await human_like_scroll(self.page, distance=random.randint(300, 800))

                    # Check if we've reached the bottom
                    is_at_bottom = await self.page.evaluate(
                        "window.innerHeight + window.scrollY >= document.body.offsetHeight"
                    )
                    if is_at_bottom:
                        break
            else:
                # Fallback to basic scrolling
                for i in range(scrolls):
                    scroll_amount = random.randint(200, 500)
                    await self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")

                    delay = self.config.rate_limit.get_scroll_delay()
                    await asyncio.sleep(delay)

                    is_at_bottom = await self.page.evaluate(
                        "window.innerHeight + window.scrollY >= document.body.offsetHeight"
                    )
                    if is_at_bottom:
                        break

        except Exception as e:
            self.logger.debug("Error scrolling page", {"error": str(e)})

    async def _check_for_captcha(self) -> bool:
        """
        Check if a CAPTCHA is present on the page using stealth utilities.

        Returns:
            True if CAPTCHA detected, False otherwise
        """
        try:
            # Use stealth module's comprehensive CAPTCHA detection if enabled
            if self.stealth_config and self.config.stealth.detect_captcha:
                captcha_detected = await check_for_captcha(self.page)
            else:
                # Fallback to basic CAPTCHA detection
                captcha_detected = False
                captcha_selectors = [
                    'iframe[src*="recaptcha"]',
                    'iframe[src*="captcha"]',
                    '#captcha',
                    '.g-recaptcha',
                    '[data-sitekey]'
                ]

                for selector in captcha_selectors:
                    element = await self.page.query_selector(selector)
                    if element:
                        captcha_detected = True
                        break

            if captcha_detected:
                self.logger.captcha_detected(self.page.url)
                self.stats["captchas_detected"] += 1

            return captcha_detected

        except Exception as e:
            self.logger.debug("Error checking for CAPTCHA", {"error": str(e)})
            return False

    async def _take_screenshot(self, name: str):
        """Take a screenshot for debugging."""
        if not self.config.scraping.screenshot_on_error:
            return

        try:
            timestamp = int(time.time())
            screenshot_path = Path(self.config.scraping.screenshot_dir) / f"{name}_{timestamp}.png"
            await self.page.screenshot(path=str(screenshot_path), full_page=True)
            self.logger.debug(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            self.logger.debug("Error taking screenshot", {"error": str(e)})

    async def search_google_maps(
        self,
        query: str,
        location: str = None,
        max_results: int = None
    ) -> List[Dict]:
        """
        Search Google Maps for businesses.

        Args:
            query: Search query (e.g., "car wash")
            location: Optional location (e.g., "Seattle, WA")
            max_results: Max results to return (uses config default if None)

        Returns:
            List of business dictionaries with basic info
        """
        max_results = max_results or self.config.scraping.max_results_per_search
        results = []

        try:
            # Check session break
            await self._check_session_break()

            # Build search URL
            search_term = f"{query} {location}" if location else query
            encoded_query = quote_plus(search_term)
            search_url = f"{self.config.google_maps_url}/search/{encoded_query}"

            self.logger.scrape_started(search_term, location)
            self.logger.set_context(search_term=search_term)

            # Navigate to Google homepage first (realistic user flow)
            start_time = time.time()
            self.logger.info("Navigating to Google homepage first (realistic flow)")
            await self.page.goto("https://www.google.com", wait_until=self.config.playwright.wait_until)

            # Brief pause on homepage
            if self.stealth_config:
                await human_like_delay(2000, 4000)
                await random_mouse_movement(self.page)
            else:
                await asyncio.sleep(3)

            # Now navigate to Google Maps main page
            self.logger.info("Navigating to Google Maps")
            await self.page.goto(self.config.google_maps_url, wait_until=self.config.playwright.wait_until)

            # Pause on Maps homepage
            if self.stealth_config:
                await human_like_delay(2000, 5000)
                await random_page_interactions(self.page)
            else:
                await asyncio.sleep(3)

            # Now perform the search by typing in search box instead of direct URL
            self.logger.info(f"Typing search query: {search_term}")
            try:
                # Wait for search box
                search_box = await self.page.wait_for_selector('input[id="searchboxinput"]', timeout=10000)

                # Type search term with human-like delays
                if self.stealth_config and self.config.stealth.simulate_typing_delays:
                    await human_like_type(self.page, 'input[id="searchboxinput"]', search_term)
                else:
                    await search_box.type(search_term, delay=random.randint(50, 150))

                # Wait a moment before pressing Enter
                await asyncio.sleep(random.uniform(0.5, 1.5))

                # Press Enter to search
                await self.page.keyboard.press('Enter')

                # Wait for results to load
                await self.page.wait_for_load_state('networkidle', timeout=30000)

            except Exception as e:
                # Fallback to direct URL navigation if search box interaction fails
                self.logger.warning(f"Search box interaction failed, using direct URL: {str(e)}")
                await self.page.goto(search_url, wait_until=self.config.playwright.wait_until)

            load_time_ms = int((time.time() - start_time) * 1000)
            self.logger.page_loaded(search_url, load_time_ms)

            # Check for CAPTCHA
            if await self._check_for_captcha():
                self.logger.error("CAPTCHA detected on search page", context={"url": search_url})
                await self._take_screenshot("captcha_search")
                return results

            # Wait for results to load
            page_delay = self.config.rate_limit.get_page_load_delay()
            await asyncio.sleep(page_delay)

            # Simulate human behavior
            await self._simulate_human_behavior()

            # Scroll to load more results
            await self._scroll_page()

            # Extract business listings from search results
            # NOTE: This is a simplified selector - may need adjustment based on Google's HTML structure
            results = await self._extract_search_results(max_results)

            self.stats["searches_performed"] += 1
            duration = time.time() - start_time
            self.logger.scrape_completed(len(results), duration)

            # Wait rate limit before next request
            await self._wait_rate_limit()

        except PlaywrightError as e:
            self.logger.page_load_failed(search_url if 'search_url' in locals() else "unknown", e)
            self.stats["errors"] += 1
            await self._take_screenshot("error_search")

        except Exception as e:
            self.logger.error("Unexpected error during search", error=e, context={"query": query})
            self.stats["errors"] += 1
            await self._take_screenshot("error_search_unexpected")

        finally:
            self.logger.clear_context()

        return results

    async def _extract_search_results(self, max_results: int) -> List[Dict]:
        """
        Extract business data from Google Maps search results page.

        Args:
            max_results: Maximum number of results to extract

        Returns:
            List of business dictionaries
        """
        results = []

        try:
            # Wait for search results to appear
            # NOTE: These selectors are examples and may need updating based on Google's current HTML
            await self.page.wait_for_selector('div[role="article"]', timeout=10000)

            # Get all business listing elements
            listing_elements = await self.page.query_selector_all('div[role="article"]')

            for idx, element in enumerate(listing_elements[:max_results]):
                try:
                    # Extract basic info from listing
                    # NOTE: These selectors are simplified - real implementation needs more robust parsing
                    business_data = await element.evaluate("""
                        (el) => {
                            const nameEl = el.querySelector('[class*="fontHeadlineSmall"]');
                            const addressEl = el.querySelector('[class*="fontBodyMedium"]');
                            const linkEl = el.querySelector('a[href*="/maps/place/"]');

                            return {
                                name: nameEl ? nameEl.textContent : null,
                                address: addressEl ? addressEl.textContent : null,
                                url: linkEl ? linkEl.href : null
                            };
                        }
                    """)

                    if business_data and business_data.get("name"):
                        # Extract place_id from URL if available
                        if business_data.get("url"):
                            business_data["place_id"] = self._extract_place_id_from_url(business_data["url"])

                        results.append(business_data)
                        self.logger.debug(f"Extracted business {idx + 1}: {business_data.get('name')}")

                except Exception as e:
                    self.logger.debug(f"Error extracting business {idx + 1}", {"error": str(e)})
                    continue

        except Exception as e:
            self.logger.error("Error extracting search results", error=e)

        return results

    def _extract_place_id_from_url(self, url: str) -> Optional[str]:
        """
        Extract Google Place ID from URL.

        Args:
            url: Google Maps URL

        Returns:
            Place ID or None
        """
        try:
            # Place ID is typically in format: /maps/place/...data=...!1s<PLACE_ID>!...
            # Or in newer format: /maps/place/.../<PLACE_ID>
            if "!1s" in url:
                parts = url.split("!1s")
                if len(parts) > 1:
                    place_id = parts[1].split("!")[0]
                    return place_id
            elif "/place/" in url:
                # Try to extract from path
                path_parts = url.split("/place/")
                if len(path_parts) > 1:
                    # Place ID might be the last part before query params
                    potential_id = path_parts[-1].split("/")[-1].split("?")[0]
                    if len(potential_id) > 20 and potential_id.startswith("ChIJ"):
                        return potential_id

        except Exception as e:
            self.logger.debug("Error extracting place_id from URL", {"url": url, "error": str(e)})

        return None

    async def scrape_business_details(self, business_url: str) -> Dict:
        """
        Scrape detailed information for a specific business.

        Args:
            business_url: Google Maps URL for the business

        Returns:
            Dictionary with detailed business information
        """
        business_data = {}

        try:
            # Check session break
            await self._check_session_break()

            self.logger.set_context(business_url=business_url)

            # Navigate to business page
            start_time = time.time()
            await self.page.goto(business_url, wait_until=self.config.playwright.wait_until)
            load_time_ms = int((time.time() - start_time) * 1000)
            self.logger.page_loaded(business_url, load_time_ms)

            # Check for CAPTCHA
            if await self._check_for_captcha():
                self.logger.error("CAPTCHA detected on business page", context={"url": business_url})
                await self._take_screenshot("captcha_business")
                return business_data

            # Wait for page to load
            page_delay = self.config.rate_limit.get_page_load_delay()
            await asyncio.sleep(page_delay)

            # Simulate human behavior
            await self._simulate_human_behavior()

            # Scroll to load all content
            await self._scroll_page(scrolls=3)

            # Extract business details
            # NOTE: This uses simplified selectors - production code needs robust parsing
            business_data = await self._extract_business_details()

            # Add metadata
            business_data["google_business_url"] = business_url
            business_data["place_id"] = self._extract_place_id_from_url(business_url)
            business_data["scrape_timestamp"] = int(time.time())

            # Calculate quality metrics
            completeness = self.config.quality.calculate_completeness(business_data)
            business_data["data_completeness"] = completeness

            # Log successful scrape
            fields_extracted = [k for k, v in business_data.items() if v]
            self.logger.business_scraped(
                business_data.get("name", "Unknown"),
                business_data.get("place_id", "Unknown"),
                fields_extracted
            )

            self.stats["businesses_scraped"] += 1

            # Wait rate limit before next request
            await self._wait_rate_limit()

        except PlaywrightError as e:
            self.logger.page_load_failed(business_url, e)
            self.stats["errors"] += 1
            await self._take_screenshot("error_business")

        except Exception as e:
            self.logger.error("Unexpected error scraping business", error=e, context={"url": business_url})
            self.stats["errors"] += 1
            await self._take_screenshot("error_business_unexpected")

        finally:
            self.logger.clear_context()

        return business_data

    async def _extract_business_details(self) -> Dict:
        """
        Extract detailed business information from current page.

        Returns:
            Dictionary with business details
        """
        details = {}

        try:
            # NOTE: These are simplified selectors - production needs robust parsing with google_parse.py
            # Extract name
            try:
                name_el = await self.page.query_selector('h1[class*="fontHeadline"]')
                if name_el:
                    details["name"] = await name_el.text_content()
            except Exception as e:
                self.logger.parsing_error("name", e)

            # Extract address
            try:
                address_el = await self.page.query_selector('button[data-item-id*="address"]')
                if address_el:
                    details["address"] = await address_el.text_content()
            except Exception as e:
                self.logger.parsing_error("address", e)

            # Extract phone
            try:
                phone_el = await self.page.query_selector('button[data-item-id*="phone"]')
                if phone_el:
                    details["phone"] = await phone_el.text_content()
            except Exception as e:
                self.logger.parsing_error("phone", e)

            # Extract website
            try:
                website_el = await self.page.query_selector('a[data-item-id*="authority"]')
                if website_el:
                    details["website"] = await website_el.get_attribute("href")
            except Exception as e:
                self.logger.parsing_error("website", e)

            # Extract rating
            try:
                rating_el = await self.page.query_selector('div[class*="fontDisplayLarge"]')
                if rating_el:
                    rating_text = await rating_el.text_content()
                    details["rating"] = float(rating_text.strip()) if rating_text else None
            except Exception as e:
                self.logger.parsing_error("rating", e)

            # Extract category
            try:
                category_el = await self.page.query_selector('button[class*="DkEaL"]')
                if category_el:
                    details["category"] = await category_el.text_content()
            except Exception as e:
                self.logger.parsing_error("category", e)

            # More fields can be added using google_parse.py

        except Exception as e:
            self.logger.error("Error extracting business details", error=e)

        return details

    def get_stats(self) -> Dict:
        """
        Get scraping session statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            **self.stats,
            "session_duration_minutes": round((time.time() - self.start_time) / 60, 2),
            "requests_this_session": self.requests_this_session
        }
