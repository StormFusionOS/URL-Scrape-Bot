"""
Camoufox Driver Wrappers

Provides Camoufox browser integration for anti-detection scraping.
Camoufox is a Firefox-based browser with advanced fingerprint spoofing.

Use this as a fallback when SeleniumBase UC gets detected.

Supports:
- Residential proxy integration
- Timezone matching to proxy location
- GPS geolocation spoofing
"""

import os
import time
import random
import threading

# Fix for Camoufox sync API in asyncio contexts
# Camoufox uses Playwright internally which cannot run sync API in asyncio loop
# nest_asyncio allows nested asyncio loops, fixing the conflict
import nest_asyncio
nest_asyncio.apply()
from typing import Optional, List, Dict, Any, Callable, Tuple, TYPE_CHECKING
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass
from contextlib import contextmanager

from runner.logging_setup import get_logger

if TYPE_CHECKING:
    from seo_intelligence.services.residential_proxy_manager import ResidentialProxy

logger = get_logger("camoufox_drivers")


@dataclass
class CamoufoxPageArtifact:
    """Captures page state from Camoufox."""
    url: str
    html: str
    title: str
    status_code: int = 200
    detected_captcha: bool = False
    detected_block: bool = False
    screenshot_path: Optional[str] = None
    cookies: Optional[List[Dict]] = None
    timing: Optional[Dict] = None


class CamoufoxDriver:
    """
    Wrapper for Camoufox browser providing a consistent interface.

    Features:
    - Human-like browsing simulation
    - Advanced fingerprint spoofing
    - Cookie/session management
    - CAPTCHA detection
    - Residential proxy integration
    - Timezone and geolocation spoofing
    """

    # Default profile directory for Google sessions
    GOOGLE_PROFILE_DIR = "/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/browser_profiles/google_camoufox"

    def __init__(
        self,
        headless: bool = False,
        humanize: bool = True,
        new_fingerprint: bool = False,
        page_timeout: int = 30000,
        proxy: Optional[Dict[str, str]] = None,
        timezone: Optional[str] = None,
        geolocation: Optional[Dict[str, float]] = None,
        profile_path: Optional[str] = None,
    ):
        """
        Initialize Camoufox driver.

        Args:
            headless: Run in headless mode (less stealthy)
            humanize: Enable human-like behavior simulation
            new_fingerprint: Force new fingerprint generation
            page_timeout: Page load timeout in ms
            proxy: Proxy config dict with keys: server, username, password
            timezone: IANA timezone ID (e.g., 'America/New_York')
            geolocation: GPS coordinates dict with keys: latitude, longitude, accuracy
            profile_path: Path to persist cookies/storage (default: Google profile)
        """
        self.headless = headless
        self.humanize = humanize
        self.new_fingerprint = new_fingerprint
        self.page_timeout = page_timeout
        self.proxy = proxy
        self.timezone = timezone
        self.geolocation = geolocation
        self.profile_path = profile_path or self.GOOGLE_PROFILE_DIR

        self._camoufox = None  # Camoufox launcher
        self._browser = None   # Playwright browser
        self._context = None
        self._page = None
        self._creator_thread_id = None  # Track which thread created the browser
        self._is_closed = False  # Track if browser has been closed

        # Ensure profile directory exists
        os.makedirs(self.profile_path, exist_ok=True)

        proxy_info = f", proxy={proxy.get('server')}" if proxy else ""
        tz_info = f", tz={timezone}" if timezone else ""
        logger.info(f"CamoufoxDriver initialized (headless={headless}, humanize={humanize}{proxy_info}{tz_info})")

    def _get_storage_state_path(self) -> str:
        """Get path to storage state file."""
        return os.path.join(self.profile_path, "storage_state.json")

    def _ensure_browser(self):
        """Ensure browser is started with proxy, timezone, geolocation, and persisted storage."""
        if self._browser is None or self._is_closed:
            import asyncio

            # nest_asyncio is applied at module load (line 24) to allow nested event loops.
            # This lets Playwright's sync API work even when there's already an event loop.
            # We do NOT patch asyncio.get_running_loop - Playwright needs it to work normally.

            # Create a fresh event loop for this thread if needed
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    asyncio.set_event_loop(asyncio.new_event_loop())
                    logger.debug("Created new event loop (previous was closed)")
            except RuntimeError:
                # No event loop in this thread
                asyncio.set_event_loop(asyncio.new_event_loop())
                logger.debug("Created new event loop for thread")

            # Import Camoufox (uses Playwright with nest_asyncio support)
            from camoufox.sync_api import Camoufox

            # Build Camoufox launch options
            camoufox_kwargs = {
                "headless": self.headless,
                "humanize": self.humanize,
                "i_know_what_im_doing": True,
            }

            # Add geolocation if configured and lat/lon are non-zero
            if self.geolocation and self.geolocation.get("latitude", 0) != 0:
                try:
                    # Only enable geoip if the package is available
                    import geoip2  # noqa: F401
                    camoufox_kwargs["geoip"] = True
                except ImportError:
                    logger.warning("geoip2 not installed, skipping automatic geoip lookup")

            # Create Camoufox launcher and start the browser
            self._camoufox = Camoufox(**camoufox_kwargs)
            self._browser = self._camoufox.start()  # Returns Playwright browser

            # Create context with proxy, timezone, geolocation, and storage state
            context_kwargs = {}
            if self.proxy:
                context_kwargs["proxy"] = self.proxy
            if self.timezone:
                # Playwright uses timezone_id for timezone override
                context_kwargs["timezone_id"] = self.timezone
                context_kwargs["locale"] = "en-US"
            if self.geolocation and (self.geolocation.get("latitude", 0) != 0 or
                                     self.geolocation.get("longitude", 0) != 0):
                context_kwargs["geolocation"] = {
                    "latitude": self.geolocation.get("latitude", 0),
                    "longitude": self.geolocation.get("longitude", 0),
                    "accuracy": self.geolocation.get("accuracy", 100),
                }
                context_kwargs["permissions"] = ["geolocation"]

            # Load persisted storage state (cookies, localStorage) if it exists
            storage_state_path = self._get_storage_state_path()
            if os.path.exists(storage_state_path):
                try:
                    context_kwargs["storage_state"] = storage_state_path
                    logger.info(f"Loading persisted Google session from {storage_state_path}")
                except Exception as e:
                    logger.warning(f"Failed to load storage state: {e}")

            if context_kwargs:
                self._context = self._browser.new_context(**context_kwargs)
                self._page = self._context.new_page()
            else:
                self._page = self._browser.new_page()

            self._page.set_default_timeout(self.page_timeout)
            self._creator_thread_id = threading.get_ident()  # Track creator thread
            self._is_closed = False
            logger.info("Camoufox browser started")

    def _simulate_human_delay(self, min_sec: float = 0.5, max_sec: float = 2.0):
        """Add human-like delay between actions."""
        if self.humanize:
            delay = random.uniform(min_sec, max_sec)
            time.sleep(delay)

    def _check_for_captcha(self, page) -> bool:
        """Check if page contains CAPTCHA."""
        try:
            content = page.content().lower()
            captcha_indicators = [
                'captcha', 'recaptcha', 'g-recaptcha', 'hcaptcha',
                'cf-challenge', 'please verify you are human',
                'security check', 'unusual traffic', 'robot',
            ]
            for indicator in captcha_indicators:
                if indicator in content:
                    logger.warning(f"CAPTCHA detected: {indicator}")
                    return True
            return False
        except Exception:
            return False

    def _check_for_block(self, page) -> bool:
        """Check if page shows block/access denied."""
        try:
            content = page.content().lower()
            block_indicators = [
                'access denied', 'blocked', 'forbidden',
                'your access to this site has been limited',
                '403 forbidden', '429 too many requests',
            ]
            for indicator in block_indicators:
                if indicator in content:
                    logger.warning(f"Block detected: {indicator}")
                    return True
            return False
        except Exception:
            return False

    # =========================================================================
    # Selenium-compatible interface methods
    # These allow CamoufoxDriver to be used interchangeably with Selenium drivers
    # =========================================================================

    def get(self, url: str) -> None:
        """
        Navigate to URL (Selenium-compatible interface).

        This wraps fetch_page() to provide a Selenium-like API for
        compatibility with code that expects driver.get(url).
        """
        self._ensure_browser()
        try:
            self._simulate_human_delay(0.3, 1.0)
            self._page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            logger.warning(f"Navigation error: {e}")
            raise

    @property
    def page_source(self) -> str:
        """Get page source (Selenium-compatible property)."""
        self._ensure_browser()
        try:
            return self._page.content()
        except Exception:
            return ""

    @property
    def current_url(self) -> str:
        """Get current URL (Selenium-compatible property)."""
        self._ensure_browser()
        try:
            return self._page.url
        except Exception:
            return ""

    def execute_script(self, script: str, *args) -> Any:
        """
        Execute JavaScript (Selenium-compatible interface).

        Args:
            script: JavaScript code to execute (can start with 'return')
            *args: Arguments to pass to the script

        Returns:
            Result of the script execution
        """
        self._ensure_browser()
        try:
            # Playwright uses evaluate() which expects an expression or arrow function
            # Selenium's execute_script() often uses 'return X' statements
            # We need to wrap in an arrow function for Playwright compatibility
            clean_script = script.strip()

            # Always wrap in arrow function for consistent behavior
            if args:
                # Pass args to the function
                wrapped = f"(args) => {{ {clean_script} }}"
                return self._page.evaluate(wrapped, list(args))
            else:
                # Wrap script in arrow function
                # If script doesn't have return, add one for expressions
                if 'return ' not in clean_script.lower():
                    wrapped = f"() => {{ return {clean_script}; }}"
                else:
                    wrapped = f"() => {{ {clean_script} }}"
                return self._page.evaluate(wrapped)
        except Exception as e:
            logger.debug(f"Script execution error: {e}")
            return None

    def quit(self) -> None:
        """Close browser (Selenium-compatible interface)."""
        self.close()

    def fetch_page(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_timeout: int = None,
        extra_wait: float = 0,
    ) -> Optional[CamoufoxPageArtifact]:
        """
        Fetch a page with Camoufox.

        Args:
            url: URL to fetch
            wait_for_selector: CSS selector to wait for
            wait_timeout: Timeout for selector (uses page_timeout if None)
            extra_wait: Additional wait after load

        Returns:
            CamoufoxPageArtifact or None on failure
        """
        self._ensure_browser()

        try:
            # Navigate
            self._simulate_human_delay(0.3, 1.0)
            response = self._page.goto(url, wait_until="domcontentloaded")

            status_code = response.status if response else 0

            # Wait for specific selector if provided
            if wait_for_selector:
                try:
                    timeout = wait_timeout or self.page_timeout
                    self._page.wait_for_selector(wait_for_selector, timeout=timeout)
                except Exception as e:
                    logger.debug(f"Selector wait failed: {e}")

            # Extra wait for dynamic content
            if extra_wait > 0:
                time.sleep(extra_wait)

            # Check for issues
            detected_captcha = self._check_for_captcha(self._page)
            detected_block = self._check_for_block(self._page)

            # Get page content
            html = self._page.content()
            title = self._page.title()

            artifact = CamoufoxPageArtifact(
                url=self._page.url,
                html=html,
                title=title,
                status_code=status_code,
                detected_captcha=detected_captcha,
                detected_block=detected_block,
            )

            if detected_captcha or detected_block:
                logger.warning(f"Page issue detected: captcha={detected_captcha}, block={detected_block}")

            return artifact

        except Exception as e:
            logger.error(f"Camoufox fetch error for {url}: {e}")
            return None

    def get_cookies(self) -> List[Dict]:
        """Get current cookies."""
        self._ensure_browser()
        return self._page.context.cookies()

    def set_cookies(self, cookies: List[Dict]):
        """Set cookies."""
        self._ensure_browser()
        self._page.context.add_cookies(cookies)

    def scroll_page(self, direction: str = "down", amount: int = 500, natural: bool = False):
        """
        Scroll the page with human-like behavior.

        Args:
            direction: "down" or "up"
            amount: Pixels to scroll (ignored if natural=True)
            natural: If True, use natural scrolling with scroll back behavior
        """
        self._ensure_browser()

        if natural:
            # Use natural scrolling from human_behavior module
            from .human_behavior import scroll_naturally_playwright
            scroll_naturally_playwright(self._page, direction, scroll_back_chance=0.3)
        else:
            self._simulate_human_delay(0.2, 0.5)
            if direction == "down":
                self._page.mouse.wheel(0, amount)
            elif direction == "up":
                self._page.mouse.wheel(0, -amount)

    def click_element(self, selector: str, timeout: int = 5000, natural: bool = False) -> bool:
        """
        Click an element with human-like behavior.

        Args:
            selector: CSS selector for element
            timeout: Max wait time in ms
            natural: If True, use bezier curve mouse movement
        """
        self._ensure_browser()
        try:
            self._simulate_human_delay(0.2, 0.5)
            element = self._page.wait_for_selector(selector, timeout=timeout)
            if element:
                if natural:
                    # Get element position and use natural mouse movement
                    box = element.bounding_box()
                    if box:
                        from .human_behavior import move_mouse_naturally_playwright
                        target_x = int(box['x'] + box['width'] / 2)
                        target_y = int(box['y'] + box['height'] / 2)
                        move_mouse_naturally_playwright(self._page, target_x, target_y)
                        self._simulate_human_delay(0.1, 0.3)
                        self._page.mouse.click(target_x, target_y)
                    else:
                        element.click()
                else:
                    element.click()
                return True
        except Exception as e:
            logger.debug(f"Click failed for {selector}: {e}")
        return False

    def type_text(self, selector: str, text: str, timeout: int = 5000, natural: bool = False) -> bool:
        """
        Type text into an element with human-like delays.

        Args:
            selector: CSS selector for element
            text: Text to type
            timeout: Max wait time in ms
            natural: If True, use natural typing with occasional typos and corrections
        """
        self._ensure_browser()
        try:
            if natural:
                # Use natural typing from human_behavior module
                from .human_behavior import type_naturally_playwright
                return type_naturally_playwright(self._page, selector, text)
            else:
                element = self._page.wait_for_selector(selector, timeout=timeout)
                if element:
                    self._simulate_human_delay(0.1, 0.3)
                    # Type with human-like delays between characters
                    for char in text:
                        element.type(char)
                        if self.humanize:
                            time.sleep(random.uniform(0.05, 0.15))
                    return True
        except Exception as e:
            logger.debug(f"Type failed for {selector}: {e}")
        return False

    def click_safe_element(self) -> bool:
        """
        Click a random safe element with natural mouse movement.

        Uses the human_behavior module to find and click safe elements.
        """
        self._ensure_browser()
        try:
            from .human_behavior import click_safe_element_playwright
            return click_safe_element_playwright(self._page)
        except Exception as e:
            logger.debug(f"Safe click failed: {e}")
            return False

    def simulate_reading(self, min_time: float = 3, max_time: float = 8) -> None:
        """
        Simulate human reading behavior with scrolling and occasional clicks.

        Uses the human_behavior module for natural scrolling and click patterns.
        """
        self._ensure_browser()
        try:
            from .human_behavior import simulate_reading_playwright
            simulate_reading_playwright(self._page, min_time, max_time)
        except Exception as e:
            logger.debug(f"Reading simulation failed: {e}")
            time.sleep(random.uniform(min_time, max_time))

    def move_mouse_naturally(self, target_x: int, target_y: int) -> bool:
        """
        Move mouse to target position using bezier curve path.

        Uses the human_behavior module for natural mouse movement.
        """
        self._ensure_browser()
        try:
            from .human_behavior import move_mouse_naturally_playwright
            return move_mouse_naturally_playwright(self._page, target_x, target_y)
        except Exception as e:
            logger.debug(f"Natural mouse move failed: {e}")
            return False

    def screenshot(self, path: str = None) -> Optional[str]:
        """Take a screenshot."""
        self._ensure_browser()
        if path is None:
            path = f"/tmp/camoufox_screenshot_{int(time.time())}.png"
        try:
            self._page.screenshot(path=path)
            return path
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None

    def _is_same_thread(self) -> bool:
        """Check if current thread is the same as the one that created the browser."""
        return self._creator_thread_id is not None and threading.get_ident() == self._creator_thread_id

    def save_storage_state(self) -> bool:
        """
        Save cookies and localStorage to persist across restarts.

        Returns:
            True if saved successfully, False otherwise.

        Note:
            This must be called from the same thread that created the browser.
            Playwright operations cannot be called from different threads.
        """
        if self._is_closed:
            logger.debug("Cannot save storage state: browser already closed")
            return False

        if not self._context:
            logger.debug("Cannot save storage state: no context available")
            return False

        if not self._is_same_thread():
            logger.debug("Skipping storage state save: different thread")
            return False

        try:
            storage_state_path = self._get_storage_state_path()
            self._context.storage_state(path=storage_state_path)
            logger.info(f"Saved Google session to {storage_state_path}")
            return True
        except Exception as e:
            # Only log warning for non-thread errors
            if "cannot switch to a different thread" not in str(e):
                logger.warning(f"Failed to save storage state: {e}")
            else:
                logger.debug(f"Thread mismatch in save_storage_state: {e}")
            return False

    def close(self):
        """
        Close the browser and context, persisting storage state.

        This method is thread-safe and handles cases where the browser
        was created on a different thread.
        """
        if self._is_closed:
            return

        self._is_closed = True

        # Only attempt storage save and Playwright operations if on same thread
        same_thread = self._is_same_thread()

        if same_thread:
            # Save storage state before closing (only if same thread)
            self.save_storage_state()

            # Close context and browser
            if self._context:
                try:
                    self._context.close()
                except Exception as e:
                    logger.debug(f"Error closing context: {e}")
                self._context = None

            if self._browser:
                try:
                    self._browser.close()
                except Exception as e:
                    logger.debug(f"Error closing browser: {e}")
                self._browser = None
                self._page = None
        else:
            # Different thread - just clear references, don't call Playwright methods
            logger.debug("Closing from different thread - skipping Playwright operations")
            self._context = None
            self._browser = None
            self._page = None

        # Stop the Camoufox launcher (this should be thread-safe)
        if self._camoufox:
            try:
                # Camoufox launcher has a stop() method that stops the asyncio loop
                if hasattr(self._camoufox, 'stop'):
                    self._camoufox.stop()
                    logger.debug("Camoufox launcher stopped")
            except Exception as e:
                logger.debug(f"Error stopping Camoufox launcher: {e}")
            self._camoufox = None
            logger.info("Camoufox browser closed")

    def __enter__(self):
        self._ensure_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


@contextmanager
def get_camoufox_driver(
    headless: bool = False,
    humanize: bool = True,
    new_fingerprint: bool = False,
    proxy: Optional[Dict[str, str]] = None,
    timezone: Optional[str] = None,
    geolocation: Optional[Dict[str, float]] = None,
) -> CamoufoxDriver:
    """
    Context manager for Camoufox driver.

    Args:
        headless: Run in headless mode
        humanize: Enable human-like behavior
        new_fingerprint: Force new fingerprint
        proxy: Proxy config dict with keys: server, username, password
        timezone: IANA timezone ID
        geolocation: GPS coordinates dict with keys: latitude, longitude, accuracy

    Usage:
        with get_camoufox_driver() as driver:
            artifact = driver.fetch_page("https://example.com")
    """
    driver = CamoufoxDriver(
        headless=headless,
        humanize=humanize,
        new_fingerprint=new_fingerprint,
        proxy=proxy,
        timezone=timezone,
        geolocation=geolocation,
    )
    try:
        yield driver
    finally:
        driver.close()


@contextmanager
def get_camoufox_driver_with_residential_proxy(
    directory: str = None,
    target_state: str = None,
    headless: bool = False,
    humanize: bool = True,
) -> Tuple[CamoufoxDriver, Optional['ResidentialProxy']]:
    """
    Context manager for Camoufox driver with residential proxy.

    Uses the ResidentialProxyManager to get a proxy and configures
    the browser with matching timezone and geolocation.

    Args:
        directory: Directory name for pool selection (e.g., 'yellowpages', 'yelp')
        target_state: Target state code for location matching (e.g., 'TX', 'CA')
        headless: Run in headless mode
        humanize: Enable human-like behavior

    Yields:
        Tuple of (CamoufoxDriver, ResidentialProxy) - proxy may be None if unavailable

    Usage:
        with get_camoufox_driver_with_residential_proxy(directory='yelp') as (driver, proxy):
            artifact = driver.fetch_page("https://yelp.com/biz/...")
            if artifact and not artifact.detected_block:
                manager.report_success(proxy, 'yelp')
    """
    from seo_intelligence.services.residential_proxy_manager import get_residential_proxy_manager

    manager = get_residential_proxy_manager()
    proxy = None
    driver = None

    try:
        # Get proxy based on directory or state
        if directory:
            proxy = manager.get_proxy_for_directory(directory)
        elif target_state:
            proxy = manager.get_proxy_for_state(target_state)
        else:
            proxy = manager.get_proxy_for_directory("pool_other")

        if proxy:
            browser_config = manager.get_browser_config(proxy)
            proxy_config = browser_config.get("proxy", {})
            timezone = browser_config.get("timezone_id")
            geolocation = browser_config.get("geolocation")

            driver = CamoufoxDriver(
                headless=headless,
                humanize=humanize,
                proxy=proxy_config,
                timezone=timezone,
                geolocation=geolocation,
            )
            logger.info(f"Created Camoufox driver with residential proxy {proxy.host} "
                       f"({proxy.city_name}, {proxy.state} - TZ: {proxy.timezone})")
        else:
            logger.warning("No healthy residential proxy available, using direct connection")
            driver = CamoufoxDriver(headless=headless, humanize=humanize)

        yield driver, proxy

    finally:
        if driver:
            driver.close()


class CamoufoxGoogleDriver(CamoufoxDriver):
    """
    Specialized Camoufox driver for Google searches.

    Includes Google-specific anti-detection and search handling.
    """

    GOOGLE_SEARCH_URL = "https://www.google.com/search"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_search_time = 0
        self.min_search_interval = 10  # Minimum seconds between searches

    def _rate_limit_search(self):
        """Enforce rate limiting for Google searches."""
        elapsed = time.time() - self.last_search_time
        if elapsed < self.min_search_interval:
            sleep_time = self.min_search_interval - elapsed + random.uniform(0, 2)
            logger.debug(f"Rate limiting: sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
        self.last_search_time = time.time()

    def search_google(
        self,
        query: str,
        location: Optional[str] = None,
        num_results: int = 10,
    ) -> Optional[CamoufoxPageArtifact]:
        """
        Perform a Google search.

        Args:
            query: Search query
            location: Optional location for localized results
            num_results: Number of results to request

        Returns:
            CamoufoxPageArtifact with search results page
        """
        self._ensure_browser()
        self._rate_limit_search()

        try:
            # Build search URL
            params = f"?q={query}&num={num_results}"
            if location:
                params += f"&near={location}"

            url = f"{self.GOOGLE_SEARCH_URL}{params}"

            # Navigate to Google first to set cookies
            if "google.com" not in (self._page.url or ""):
                self._page.goto("https://www.google.com")
                self._simulate_human_delay(1, 2)

            # Perform search
            artifact = self.fetch_page(url, wait_for_selector="div#search", extra_wait=1)

            if artifact and artifact.detected_captcha:
                logger.error("Google CAPTCHA detected - need to escalate")

            return artifact

        except Exception as e:
            logger.error(f"Google search error: {e}")
            return None

    def get_autocomplete_suggestions(self, query: str) -> List[str]:
        """Get Google autocomplete suggestions."""
        self._ensure_browser()
        self._rate_limit_search()

        try:
            # Navigate to Google
            if "google.com" not in (self._page.url or ""):
                self._page.goto("https://www.google.com")
                self._simulate_human_delay(1, 2)

            # Find and interact with search box
            search_box = self._page.wait_for_selector('textarea[name="q"], input[name="q"]', timeout=5000)
            if not search_box:
                return []

            # Type query slowly to trigger autocomplete
            search_box.click()
            self._simulate_human_delay(0.2, 0.5)

            for char in query:
                search_box.type(char)
                time.sleep(random.uniform(0.08, 0.2))

            # Wait for suggestions to appear
            self._simulate_human_delay(0.5, 1.0)

            # Extract suggestions
            suggestions = []
            try:
                suggestion_elements = self._page.query_selector_all('ul[role="listbox"] li span')
                for elem in suggestion_elements[:10]:
                    text = elem.inner_text().strip()
                    if text and text != query:
                        suggestions.append(text)
            except Exception as e:
                logger.debug(f"Could not extract suggestions: {e}")

            return suggestions

        except Exception as e:
            logger.error(f"Autocomplete error: {e}")
            return []
