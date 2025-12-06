"""
Base Scraper Class

Provides shared functionality for all SEO intelligence scrapers.

Features:
- Playwright browser management
- Integration with Phase 2 services (rate limiter, robots checker, etc.)
- Common page interaction methods
- Error handling and retries
- Task logging integration

All scrapers (SERP, competitor, backlinks, citations) inherit from this class.
"""

import os
import time
import random
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from contextlib import contextmanager
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

from seo_intelligence.services import (
    get_rate_limiter,
    get_robots_checker,
    get_user_agent_rotator,
    get_proxy_manager,
    get_task_logger,
    get_content_hasher,
    get_domain_quarantine,
    get_browser_profile_manager,
)
from runner.logging_setup import get_logger


class BaseScraper(ABC):
    """
    Abstract base class for all SEO intelligence scrapers.

    Provides:
    - Browser lifecycle management
    - Rate limiting integration
    - Robots.txt compliance
    - User agent rotation
    - Proxy support
    - Error handling with retries
    """

    def __init__(
        self,
        name: str,
        tier: str = "C",
        headless: bool = True,  # Hybrid mode: start headless, upgrade to headed on detection
        respect_robots: bool = True,
        use_proxy: bool = False,  # Disabled: datacenter proxies get detected
        max_retries: int = 3,
        page_timeout: int = 30000,
    ):
        """
        Initialize base scraper.

        Args:
            name: Scraper name for logging
            tier: Rate limit tier (A-G, default: C)
            headless: Default browser mode (hybrid mode overrides per-domain)
            respect_robots: Check robots.txt before crawling
            use_proxy: Use proxy pool
            max_retries: Maximum retry attempts on failure
            page_timeout: Page load timeout in milliseconds
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
        self.ua_rotator = get_user_agent_rotator()
        self.proxy_manager = get_proxy_manager()
        self.task_logger = get_task_logger()
        self.content_hasher = get_content_hasher()
        self.domain_quarantine = get_domain_quarantine()
        self.browser_profile_manager = get_browser_profile_manager()

        # Track current session's browser mode per domain
        self._current_domain = None
        self._current_headed_mode = False

        # Browser state
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

        # Statistics
        self.stats = {
            "pages_crawled": 0,
            "pages_skipped": 0,
            "pages_failed": 0,
            "robots_blocked": 0,
            "rate_limited": 0,
        }

        self.logger.info(f"{name} initialized (tier={tier}, headless={headless})")

    def _get_random_delay(self) -> float:
        """
        Get randomized delay based on tier configuration with ±20% jitter.

        Per SCRAPING_NOTES.md §3: "Per-request base delay: 3-6s with ±20% jitter"
        """
        from seo_intelligence.services.rate_limiter import TIER_CONFIGS

        config = TIER_CONFIGS.get(self.tier, TIER_CONFIGS["C"])
        delay = random.uniform(config.min_delay_seconds, config.max_delay_seconds)

        # Add ±20% jitter per spec
        jitter = delay * random.uniform(-0.20, 0.20)
        final_delay = max(0.1, delay + jitter)  # Ensure minimum 0.1s delay

        self.logger.debug(f"Delay: {delay:.2f}s + jitter {jitter:.2f}s = {final_delay:.2f}s")
        return final_delay

    def _apply_base_delay(self):
        """
        Apply base delay (5-12s with ±30% jitter) before each request.

        Conservative delays to appear more human-like and avoid detection.
        This is in addition to tier-specific rate limiting.
        """
        base_delay = random.uniform(5.0, 12.0)
        jitter = base_delay * random.uniform(-0.30, 0.30)
        final_delay = max(2.0, base_delay + jitter)  # Ensure minimum 2s

        self.logger.debug(f"Base delay: {base_delay:.2f}s + jitter {jitter:.2f}s = {final_delay:.2f}s")
        time.sleep(final_delay)

    def _check_robots(self, url: str) -> bool:
        """
        Check if URL is allowed by robots.txt.

        Args:
            url: URL to check

        Returns:
            bool: True if allowed (or robots check disabled), False otherwise
        """
        if not self.respect_robots:
            return True

        allowed = self.robots_checker.is_allowed(url)

        if not allowed:
            self.logger.warning(f"URL blocked by robots.txt: {url}")
            self.stats["robots_blocked"] += 1

        return allowed

    @contextmanager
    def _rate_limit_and_concurrency(self, domain: str):
        """
        Context manager for rate limiting and concurrency control.

        Enforces per SCRAPING_NOTES.md §3:
        - Global max concurrency: 5
        - Per-domain max concurrency: 1
        - Per-request base delay: 3-6s with ±20% jitter
        - Tier-specific rate limits

        Usage:
            with self._rate_limit_and_concurrency(domain):
                # Make request to domain
                pass

        Args:
            domain: Domain to rate limit
        """
        # Set tier for domain if not already set
        self.rate_limiter.set_domain_tier(domain, self.tier)

        # Acquire concurrency permits (global + per-domain)
        if not self.rate_limiter.acquire_concurrency(domain, timeout=60.0):
            self.logger.warning(f"Concurrency timeout for {domain}")
            self.stats["rate_limited"] += 1
            raise RuntimeError(f"Failed to acquire concurrency permits for {domain}")

        try:
            # Acquire rate limit token
            if not self.rate_limiter.acquire(domain, wait=True, max_wait=60.0):
                self.logger.warning(f"Rate limit timeout for {domain}")
                self.stats["rate_limited"] += 1
                raise RuntimeError(f"Failed to acquire rate limit token for {domain}")

            # Apply base delay with jitter (3-6s ±20%)
            self._apply_base_delay()

            # Yield control to caller
            yield

        finally:
            # Always release concurrency permits
            self.rate_limiter.release_concurrency(domain)

    def _get_stealth_context_options(self) -> dict:
        """
        Generate randomized browser context options for stealth.

        Returns realistic fingerprints to avoid bot detection.
        """
        # Random screen resolutions (common desktop sizes)
        screen_sizes = [
            {"width": 1920, "height": 1080},
            {"width": 1366, "height": 768},
            {"width": 1536, "height": 864},
            {"width": 1440, "height": 900},
            {"width": 1280, "height": 720},
            {"width": 2560, "height": 1440},
        ]
        viewport = random.choice(screen_sizes)

        # Random timezones (US-based)
        timezones = [
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
            "America/Phoenix",
        ]
        timezone = random.choice(timezones)

        # Random locales
        locales = ["en-US", "en-GB", "en-CA"]
        locale = random.choice(locales)

        # Random color schemes
        color_schemes = ["light", "dark", "no-preference"]

        return {
            "viewport": viewport,
            "screen": {"width": viewport["width"] + random.randint(0, 100),
                       "height": viewport["height"] + random.randint(0, 100)},
            "locale": locale,
            "timezone_id": timezone,
            "color_scheme": random.choice(color_schemes),
            "has_touch": False,
            "is_mobile": False,
            "device_scale_factor": random.choice([1, 1.25, 1.5, 2]),
            "java_script_enabled": True,
            # Permissions that real browsers have
            "permissions": ["geolocation"],
            # Extra HTTP headers to appear more human
            "extra_http_headers": {
                "Accept-Language": f"{locale},en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        }

    def _simulate_human_behavior(self, page: Page, intensity: str = "normal"):
        """
        Simulate human-like behavior on the page.

        Includes random mouse movements, scrolling, reading pauses, and delays.

        Args:
            intensity: "light", "normal", or "thorough" - how much human simulation
        """
        try:
            # Random initial delay (humans don't act instantly)
            if intensity == "light":
                time.sleep(random.uniform(0.5, 1.5))
            elif intensity == "normal":
                time.sleep(random.uniform(1.0, 3.0))
            else:  # thorough
                time.sleep(random.uniform(2.0, 5.0))

            # Random mouse movement (like looking around the page)
            move_count = {"light": 2, "normal": 4, "thorough": 8}.get(intensity, 4)
            for _ in range(random.randint(2, move_count)):
                x = random.randint(100, 1200)
                y = random.randint(100, 800)
                # Move in a more natural curve by using small steps
                page.mouse.move(x, y, steps=random.randint(5, 15))
                time.sleep(random.uniform(0.1, 0.4))

            # Simulate reading the page (longer pause)
            if intensity != "light":
                reading_time = random.uniform(1.0, 4.0)
                self.logger.debug(f"Simulating reading for {reading_time:.1f}s")
                time.sleep(reading_time)

            # Random scroll (humans often scroll to read content)
            scroll_amount = random.randint(200, 600)
            page.mouse.wheel(0, scroll_amount)
            time.sleep(random.uniform(0.5, 1.5))

            # Sometimes scroll more
            if random.random() > 0.4:
                page.mouse.wheel(0, random.randint(100, 300))
                time.sleep(random.uniform(0.3, 0.8))

            # Sometimes scroll back up (like re-reading something)
            if random.random() > 0.5:
                page.mouse.wheel(0, -scroll_amount // 2)
                time.sleep(random.uniform(0.3, 0.8))

            # Occasionally hover over elements (like reading links)
            if intensity == "thorough" and random.random() > 0.6:
                try:
                    links = page.query_selector_all("a")[:5]
                    if links:
                        link = random.choice(links)
                        link.hover()
                        time.sleep(random.uniform(0.2, 0.6))
                except Exception:
                    pass

            # Final reading pause
            if intensity != "light":
                time.sleep(random.uniform(0.5, 2.0))

        except Exception as e:
            # Don't fail if human simulation fails
            self.logger.debug(f"Human simulation skipped: {e}")

    def _simulate_typing(self, page: Page, selector: str, text: str):
        """
        Simulate human-like typing with variable speed and occasional pauses.

        Args:
            page: Playwright Page object
            selector: CSS selector for the input field
            text: Text to type
        """
        try:
            element = page.query_selector(selector)
            if not element:
                self.logger.warning(f"Element not found: {selector}")
                return

            element.click()
            time.sleep(random.uniform(0.2, 0.5))

            # Type character by character with variable delays
            for i, char in enumerate(text):
                element.type(char)

                # Variable delay between keystrokes (humans don't type uniformly)
                if random.random() > 0.9:
                    # Occasional longer pause (thinking)
                    time.sleep(random.uniform(0.3, 0.8))
                else:
                    # Normal typing speed varies between 50-200ms per char
                    time.sleep(random.uniform(0.05, 0.2))

                # Occasionally make a small pause after words
                if char == ' ' and random.random() > 0.7:
                    time.sleep(random.uniform(0.1, 0.3))

            # Pause after finishing typing
            time.sleep(random.uniform(0.3, 1.0))

        except Exception as e:
            self.logger.debug(f"Typing simulation failed: {e}")
            # Fallback to regular fill
            try:
                page.fill(selector, text)
            except Exception:
                pass

    def _take_session_break(self):
        """
        Take a longer break between sessions to appear more human.
        Used after multiple requests or when switching tasks.
        """
        break_duration = random.uniform(30, 90)  # 30-90 second break
        self.logger.info(f"Taking session break for {break_duration:.1f}s to appear human")
        time.sleep(break_duration)

    def _is_honeypot_link(self, page: Page, element) -> bool:
        """
        Check if a link element is a honeypot trap.

        Honeypots are invisible or hidden elements designed to catch bots.
        Real users never click them, but bots following all links will.

        Args:
            page: Playwright Page object
            element: Link element to check

        Returns:
            bool: True if element appears to be a honeypot
        """
        try:
            # Get computed styles
            box = element.bounding_box()

            # Check 1: Element has no visible dimensions
            if box is None:
                self.logger.debug("Honeypot detected: no bounding box")
                return True

            # Check 2: Element is too small (1x1 pixel traps)
            if box['width'] < 5 or box['height'] < 5:
                self.logger.debug(f"Honeypot detected: tiny size ({box['width']}x{box['height']})")
                return True

            # Check 3: Element is positioned off-screen
            viewport = page.viewport_size
            if viewport:
                if box['x'] < -100 or box['y'] < -100:
                    self.logger.debug("Honeypot detected: off-screen position")
                    return True
                if box['x'] > viewport['width'] + 100 or box['y'] > viewport['height'] + 100:
                    self.logger.debug("Honeypot detected: beyond viewport")
                    return True

            # Check 4: Check for honeypot classes/IDs
            honeypot_keywords = [
                'honeypot', 'honey-pot', 'honey_pot',
                'trap', 'bot-trap', 'bot_trap', 'bottrap',
                'hidden', 'invisible', 'offscreen', 'off-screen',
                'hp-', 'ohnohoney', 'catch-bot', 'anti-bot',
                'display-none', 'visibility-hidden',
            ]

            element_class = element.get_attribute('class') or ''
            element_id = element.get_attribute('id') or ''
            element_name = element.get_attribute('name') or ''

            for keyword in honeypot_keywords:
                if keyword in element_class.lower():
                    self.logger.debug(f"Honeypot detected: class contains '{keyword}'")
                    return True
                if keyword in element_id.lower():
                    self.logger.debug(f"Honeypot detected: id contains '{keyword}'")
                    return True
                if keyword in element_name.lower():
                    self.logger.debug(f"Honeypot detected: name contains '{keyword}'")
                    return True

            # Check 5: Check computed visibility via JavaScript
            is_visible = page.evaluate("""
                (element) => {
                    const style = window.getComputedStyle(element);
                    return style.display !== 'none' &&
                           style.visibility !== 'hidden' &&
                           parseFloat(style.opacity) > 0.1 &&
                           element.offsetParent !== null;
                }
            """, element)

            if not is_visible:
                self.logger.debug("Honeypot detected: CSS hidden")
                return True

            # Check 6: Check if link text is suspicious
            link_text = element.text_content() or ''
            suspicious_texts = [
                'click here if you are not a robot',
                'do not click', 'dont click', "don't click",
                'bot test', 'verify human', 'are you human',
            ]

            for suspicious in suspicious_texts:
                if suspicious in link_text.lower():
                    self.logger.debug(f"Honeypot detected: suspicious text '{suspicious}'")
                    return True

            # Check 7: Check parent elements for hidden containers
            parent_hidden = page.evaluate("""
                (element) => {
                    let parent = element.parentElement;
                    while (parent && parent !== document.body) {
                        const style = window.getComputedStyle(parent);
                        if (style.display === 'none' ||
                            style.visibility === 'hidden' ||
                            parseFloat(style.opacity) < 0.1) {
                            return true;
                        }
                        parent = parent.parentElement;
                    }
                    return false;
                }
            """, element)

            if parent_hidden:
                self.logger.debug("Honeypot detected: parent container hidden")
                return True

            return False

        except Exception as e:
            self.logger.debug(f"Honeypot check error: {e}")
            # When in doubt, treat as suspicious
            return True

    def _is_honeypot_form_field(self, page: Page, field) -> bool:
        """
        Check if a form field is a honeypot.

        Many sites add hidden form fields that should remain empty.
        Bots that fill all fields get caught.

        Args:
            page: Playwright Page object
            field: Form field element

        Returns:
            bool: True if field appears to be a honeypot
        """
        try:
            # Check field type
            field_type = field.get_attribute('type') or ''

            # Hidden fields are often honeypots
            if field_type == 'hidden':
                field_name = field.get_attribute('name') or ''
                # Some hidden fields are legitimate (csrf, etc)
                legitimate_hidden = ['csrf', 'token', '_token', 'nonce', 'state']
                if not any(leg in field_name.lower() for leg in legitimate_hidden):
                    self.logger.debug(f"Potential honeypot: hidden field '{field_name}'")
                    return True

            # Check for honeypot naming patterns
            honeypot_names = [
                'honeypot', 'honey', 'pot', 'trap',
                'email2', 'phone2', 'address2', 'name2',
                'confirm_email', 'url', 'website', 'homepage',
                'fax', 'company2', 'subject2',
            ]

            field_name = field.get_attribute('name') or ''
            field_id = field.get_attribute('id') or ''

            for hp_name in honeypot_names:
                if hp_name in field_name.lower() or hp_name in field_id.lower():
                    # Check if it's visually hidden
                    box = field.bounding_box()
                    if box is None or box['width'] < 2 or box['height'] < 2:
                        self.logger.debug(f"Honeypot form field: '{field_name}'")
                        return True

            # Check autocomplete="off" + tabindex="-1" combo (common honeypot pattern)
            autocomplete = field.get_attribute('autocomplete') or ''
            tabindex = field.get_attribute('tabindex') or ''

            if autocomplete == 'off' and tabindex == '-1':
                box = field.bounding_box()
                if box and (box['width'] < 5 or box['height'] < 5):
                    self.logger.debug("Honeypot form field: autocomplete=off + tabindex=-1 + tiny")
                    return True

            return False

        except Exception as e:
            self.logger.debug(f"Form honeypot check error: {e}")
            return True  # When in doubt, don't fill

    def _filter_safe_links(self, page: Page, links: list) -> list:
        """
        Filter out honeypot links from a list of link elements.

        Args:
            page: Playwright Page object
            links: List of link elements

        Returns:
            list: Filtered list of safe links
        """
        safe_links = []
        for link in links:
            if not self._is_honeypot_link(page, link):
                safe_links.append(link)
            else:
                href = link.get_attribute('href') or 'unknown'
                self.logger.info(f"Skipping honeypot link: {href[:50]}")

        self.logger.debug(f"Filtered {len(links)} links -> {len(safe_links)} safe links")
        return safe_links

    def _avoid_honeypot_patterns(self, url: str) -> bool:
        """
        Check if a URL matches common honeypot patterns.

        Args:
            url: URL to check

        Returns:
            bool: True if URL should be avoided
        """
        url_lower = url.lower()

        # Suspicious URL patterns
        honeypot_url_patterns = [
            '/trap', '/honeypot', '/honey-pot', '/bot-trap',
            '/catch', '/gotcha', '/verify-human',
            'trap=', 'honeypot=', 'bot=true',
            '/wp-content/plugins/honeypot',
            '/invisible-link', '/hidden-link',
            '?hp=', '&hp=', '?trap=', '&trap=',
        ]

        for pattern in honeypot_url_patterns:
            if pattern in url_lower:
                self.logger.warning(f"Avoiding honeypot URL pattern: {pattern}")
                return True

        return False

    @contextmanager
    def browser_session(self, domain: Optional[str] = None):
        """
        Context manager for browser session with stealth capabilities.

        Supports hybrid headless/headed mode:
        - Starts in headless mode by default (faster, less resource intensive)
        - Automatically uses headed mode for domains that have triggered detection
        - Persists browser profiles (cookies, localStorage) for better stealth

        Usage:
            with scraper.browser_session(domain="google.com") as (browser, context, page):
                page.goto("https://google.com")
                # ... scrape content ...

        Args:
            domain: Target domain (optional). If provided, enables hybrid mode
                    and browser profile persistence for that domain.

        Includes:
        - Hybrid headless/headed mode based on domain detection history
        - Persistent browser profiles with cookies and localStorage
        - Playwright stealth mode (evades bot detection)
        - Randomized fingerprints (screen, timezone, locale)
        - Human-like browser headers
        - Optional proxy support
        """
        playwright = None
        browser = None
        context = None
        page = None
        profile_path = None

        # Determine if we need headed mode for this domain
        use_headed = False
        if domain:
            self._current_domain = domain
            use_headed = self.browser_profile_manager.requires_headed(domain)
            self._current_headed_mode = use_headed

            # Get/create persistent profile path for this domain
            profile_path = self.browser_profile_manager.get_profile_path(domain)

            mode_str = "headed (required)" if use_headed else "headless (default)"
            self.logger.info(f"Browser session for {domain}: {mode_str}")
        else:
            # No domain specified, use default headless setting
            use_headed = not self.headless
            self._current_headed_mode = use_headed

        try:
            # Start Playwright
            playwright = sync_playwright().start()

            # Get proxy if enabled
            proxy_config = None
            if self.use_proxy:
                proxy_config = self.proxy_manager.get_proxy_for_playwright()

            # Get random user agent
            user_agent = self.ua_rotator.get_random()

            # Launch browser with stealth args
            # Use headed mode if domain requires it, otherwise use headless
            browser = playwright.chromium.launch(
                headless=not use_headed,  # headless=False means headed
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-position=0,0",
                    "--ignore-certificate-errors",
                    "--ignore-certificate-errors-spki-list",
                    f"--user-agent={user_agent}",
                ],
            )

            # Get stealth context options
            context_options = self._get_stealth_context_options()
            context_options["user_agent"] = user_agent

            if proxy_config:
                context_options["proxy"] = proxy_config
                self.logger.debug(f"Using proxy: {proxy_config.get('server', 'N/A')}")

            # Add persistent storage path if domain profile exists
            if profile_path:
                context_options["storage_state"] = None  # Will load from profile if exists
                # Check if we have saved state
                storage_file = os.path.join(profile_path, "storage_state.json")
                if os.path.exists(storage_file):
                    context_options["storage_state"] = storage_file
                    self.logger.debug(f"Loading saved browser state from {storage_file}")

            context = browser.new_context(**context_options)
            context.set_default_timeout(self.page_timeout)

            # Create page
            page = context.new_page()

            # Apply playwright-stealth to evade bot detection
            stealth = Stealth()
            stealth.apply_stealth_sync(page)

            # Add enhanced stealth scripts (matching google_stealth.py)
            # Generate random hardware values for this session
            hardware_concurrency = random.choice([2, 4, 8, 16])
            device_memory = random.choice([4, 8, 16])

            # Generate randomized fingerprint values for this session
            canvas_noise = random.uniform(0.0001, 0.001)
            webgl_vendor = random.choice([
                'Google Inc. (NVIDIA)',
                'Google Inc. (Intel)',
                'Google Inc. (AMD)',
                'Google Inc. (ANGLE)'
            ])
            webgl_renderer = random.choice([
                'ANGLE (NVIDIA GeForce GTX 1060 Direct3D11 vs_5_0 ps_5_0)',
                'ANGLE (Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)',
                'ANGLE (AMD Radeon RX 580 Series Direct3D11 vs_5_0 ps_5_0)',
                'ANGLE (NVIDIA GeForce RTX 2060 Direct3D11 vs_5_0 ps_5_0)'
            ])
            audio_sample_rate = random.choice([44100, 48000])
            battery_level = random.uniform(0.2, 0.95)
            battery_charging = random.choice([True, False])

            page.add_init_script(f"""
                // Override navigator.webdriver
                Object.defineProperty(navigator, 'webdriver', {{
                    get: () => undefined
                }});

                // Override navigator.plugins with realistic values
                Object.defineProperty(navigator, 'plugins', {{
                    get: () => [
                        {{
                            name: 'Chrome PDF Plugin',
                            filename: 'internal-pdf-viewer',
                            description: 'Portable Document Format',
                            length: 1
                        }},
                        {{
                            name: 'Chrome PDF Viewer',
                            filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                            description: '',
                            length: 1
                        }},
                        {{
                            name: 'Native Client',
                            filename: 'internal-nacl-plugin',
                            description: '',
                            length: 2
                        }}
                    ]
                }});

                // Override navigator.languages
                Object.defineProperty(navigator, 'languages', {{
                    get: () => ['en-US', 'en']
                }});

                // Delete Chrome automation flags
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

                // Override chrome runtime with realistic properties
                window.chrome = {{
                    runtime: {{}},
                    loadTimes: function() {{}},
                    csi: function() {{}},
                    app: {{}}
                }};

                // Override permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({{ state: Notification.permission }}) :
                        originalQuery(parameters)
                );

                // Add realistic hardware concurrency
                Object.defineProperty(navigator, 'hardwareConcurrency', {{
                    get: () => {hardware_concurrency}
                }});

                // Add realistic device memory
                Object.defineProperty(navigator, 'deviceMemory', {{
                    get: () => {device_memory}
                }});

                // ========== CANVAS FINGERPRINT RANDOMIZATION ==========
                // Add subtle noise to canvas to prevent fingerprinting
                const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                const originalToBlob = HTMLCanvasElement.prototype.toBlob;
                const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;

                const canvasNoise = {canvas_noise};

                HTMLCanvasElement.prototype.toDataURL = function(...args) {{
                    const context = this.getContext('2d');
                    if (context) {{
                        const imageData = context.getImageData(0, 0, this.width, this.height);
                        for (let i = 0; i < imageData.data.length; i += 4) {{
                            imageData.data[i] = imageData.data[i] + Math.floor(Math.random() * canvasNoise * 255);
                            imageData.data[i + 1] = imageData.data[i + 1] + Math.floor(Math.random() * canvasNoise * 255);
                            imageData.data[i + 2] = imageData.data[i + 2] + Math.floor(Math.random() * canvasNoise * 255);
                        }}
                        context.putImageData(imageData, 0, 0);
                    }}
                    return originalToDataURL.apply(this, args);
                }};

                CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
                    const imageData = originalGetImageData.apply(this, args);
                    for (let i = 0; i < imageData.data.length; i += 4) {{
                        imageData.data[i] = imageData.data[i] + Math.floor(Math.random() * canvasNoise * 255);
                        imageData.data[i + 1] = imageData.data[i + 1] + Math.floor(Math.random() * canvasNoise * 255);
                        imageData.data[i + 2] = imageData.data[i + 2] + Math.floor(Math.random() * canvasNoise * 255);
                    }}
                    return imageData;
                }};

                // ========== WEBGL FINGERPRINT RANDOMIZATION ==========
                const getParameterProxyHandler = {{
                    apply: function(target, ctx, args) {{
                        const param = args[0];
                        const UNMASKED_VENDOR_WEBGL = 0x9245;
                        const UNMASKED_RENDERER_WEBGL = 0x9246;

                        if (param === UNMASKED_VENDOR_WEBGL) {{
                            return '{webgl_vendor}';
                        }}
                        if (param === UNMASKED_RENDERER_WEBGL) {{
                            return '{webgl_renderer}';
                        }}
                        return target.apply(ctx, args);
                    }}
                }};

                const addProxyToContext = (context) => {{
                    if (!context || !context.getParameter) return;
                    context.getParameter = new Proxy(context.getParameter, getParameterProxyHandler);
                }};

                const originalGetContext = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(...args) {{
                    const context = originalGetContext.apply(this, args);
                    if (args[0] === 'webgl' || args[0] === 'webgl2' || args[0] === 'experimental-webgl') {{
                        addProxyToContext(context);
                    }}
                    return context;
                }};

                // ========== AUDIO CONTEXT FINGERPRINT RANDOMIZATION ==========
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                if (AudioContext) {{
                    const OriginalAnalyser = AudioContext.prototype.createAnalyser;
                    AudioContext.prototype.createAnalyser = function() {{
                        const analyser = OriginalAnalyser.apply(this, arguments);
                        const originalGetFloatFrequencyData = analyser.getFloatFrequencyData;
                        analyser.getFloatFrequencyData = function(array) {{
                            originalGetFloatFrequencyData.apply(this, arguments);
                            for (let i = 0; i < array.length; i++) {{
                                array[i] = array[i] + Math.random() * 0.1 - 0.05;
                            }}
                        }};
                        return analyser;
                    }};

                    // Randomize sample rate
                    Object.defineProperty(AudioContext.prototype, 'sampleRate', {{
                        get: function() {{
                            return {audio_sample_rate};
                        }}
                    }});
                }}

                // ========== MEDIA DEVICES ENUMERATION ==========
                // Return realistic media device list
                const originalEnumerateDevices = navigator.mediaDevices.enumerateDevices;
                navigator.mediaDevices.enumerateDevices = async function() {{
                    return [
                        {{
                            deviceId: 'default',
                            kind: 'audioinput',
                            label: 'Default - Microphone',
                            groupId: 'default'
                        }},
                        {{
                            deviceId: 'communications',
                            kind: 'audioinput',
                            label: 'Communications - Microphone',
                            groupId: 'communications'
                        }},
                        {{
                            deviceId: 'default',
                            kind: 'audiooutput',
                            label: 'Default - Speakers',
                            groupId: 'default'
                        }},
                        {{
                            deviceId: 'communications',
                            kind: 'audiooutput',
                            label: 'Communications - Speakers',
                            groupId: 'communications'
                        }},
                        {{
                            deviceId: 'video' + Math.random().toString(36).substring(7),
                            kind: 'videoinput',
                            label: 'Integrated Camera',
                            groupId: 'videoinput'
                        }}
                    ];
                }};

                // ========== BATTERY API SPOOFING ==========
                // Spoof battery API to look like real device
                if (navigator.getBattery) {{
                    const originalGetBattery = navigator.getBattery.bind(navigator);
                    navigator.getBattery = async function() {{
                        const battery = await originalGetBattery();
                        Object.defineProperties(battery, {{
                            charging: {{ get: () => {str(battery_charging).lower()} }},
                            chargingTime: {{ get: () => {str(battery_charging).lower()} ? 3600 : Infinity }},
                            dischargingTime: {{ get: () => {str(battery_charging).lower()} ? Infinity : 7200 }},
                            level: {{ get: () => {battery_level} }}
                        }});
                        return battery;
                    }};
                }}

                // ========== SCREEN PROPERTIES ==========
                // Add realistic screen properties
                Object.defineProperty(screen, 'availWidth', {{
                    get: () => screen.width - Math.floor(Math.random() * 10)
                }});
                Object.defineProperty(screen, 'availHeight', {{
                    get: () => screen.height - Math.floor(Math.random() * 50) - 40
                }});

                // ========== TIMEZONE CONSISTENCY ==========
                // Ensure timezone matches geolocation (already set in context options)
                // This just verifies it's consistent
                const timezoneOffset = new Date().getTimezoneOffset();

                // ========== CONNECTION INFO ==========
                // Add realistic connection properties
                if (navigator.connection || navigator.mozConnection || navigator.webkitConnection) {{
                    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
                    Object.defineProperties(connection, {{
                        downlink: {{ get: () => Math.random() * 10 + 5 }}, // 5-15 Mbps
                        rtt: {{ get: () => Math.floor(Math.random() * 50) + 20 }}, // 20-70ms
                        effectiveType: {{ get: () => '4g' }},
                        saveData: {{ get: () => false }}
                    }});
                }}

                // Make toString return native code for all modified functions
                const oldToString = Function.prototype.toString;
                Function.prototype.toString = function() {{
                    if (this === window.navigator.permissions.query ||
                        this === HTMLCanvasElement.prototype.toDataURL ||
                        this === CanvasRenderingContext2D.prototype.getImageData ||
                        this === navigator.mediaDevices.enumerateDevices ||
                        this === navigator.getBattery) {{
                        return 'function() {{ [native code] }}';
                    }}
                    return oldToString.call(this);
                }};

                // Hide that we modified anything
                Object.defineProperty(Function.prototype.toString, 'toString', {{
                    value: () => 'function toString() {{ [native code] }}'
                }});
            """)

            mode_label = "headed" if use_headed else "headless"
            self.logger.debug(f"Stealth browser session started ({mode_label}, UA: {user_agent[:50]}...)")

            yield browser, context, page

        except Exception as e:
            self.logger.error(f"Browser session error: {e}", exc_info=True)
            raise

        finally:
            # Save browser state before closing (for profile persistence)
            if context and profile_path:
                try:
                    storage_file = os.path.join(profile_path, "storage_state.json")
                    context.storage_state(path=storage_file)
                    self.browser_profile_manager.mark_cookies_stored(domain)
                    self.logger.debug(f"Saved browser state to {storage_file}")
                except Exception as e:
                    self.logger.debug(f"Could not save browser state: {e}")

            # Cleanup
            if page:
                try:
                    page.close()
                except Exception:
                    pass

            if context:
                try:
                    context.close()
                except Exception:
                    pass

            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass

            # Reset current session tracking
            self._current_domain = None
            self._current_headed_mode = False

            self.logger.debug("Browser session closed")

    def _validate_html_response(
        self,
        html: str,
        url: str,
        content_type: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate HTML response for sanity checks.

        Detects:
        - Non-HTML MIME types
        - CAPTCHA pages
        - Bot detection pages
        - Missing essential HTML elements

        Args:
            html: HTML content
            url: URL being validated
            content_type: Content-Type header value

        Returns:
            Tuple of (is_valid, reason_code)
            - is_valid: True if HTML passes sanity checks
            - reason_code: None if valid, otherwise error code
        """
        if not html or len(html.strip()) < 100:
            return False, "EMPTY_RESPONSE"

        # Check Content-Type if provided
        if content_type:
            if not any(ct in content_type.lower() for ct in ['text/html', 'application/xhtml']):
                self.logger.warning(f"Non-HTML content type: {content_type} for {url}")
                return False, "NON_HTML_MIME"

        html_lower = html.lower()

        # Check for CAPTCHA indicators
        captcha_indicators = [
            'captcha',
            'recaptcha',
            'g-recaptcha',
            'hcaptcha',
            'cf-challenge',  # Cloudflare challenge
            'please verify you are human',
            'security check',
            'unusual traffic',
        ]

        for indicator in captcha_indicators:
            if indicator in html_lower:
                self.logger.warning(f"CAPTCHA detected on {url}: {indicator}")
                return False, "CAPTCHA_DETECTED"

        # Check for bot detection / anti-scraping
        bot_detection_indicators = [
            'access denied',
            'blocked',
            'forbidden',
            'your access to this site has been limited',
            'enable javascript',
            'javascript is disabled',
            'please enable cookies',
        ]

        for indicator in bot_detection_indicators:
            if indicator in html_lower:
                self.logger.warning(f"Bot detection page on {url}: {indicator}")
                return False, "BOT_DETECTED"

        # Check for essential HTML elements
        if '<title>' not in html_lower and '<title ' not in html_lower:
            self.logger.warning(f"Missing <title> tag on {url}")
            return False, "NO_TITLE_TAG"

        # Check for minimal HTML structure
        if '<html' not in html_lower and '<!doctype html' not in html_lower:
            self.logger.warning(f"Invalid HTML structure on {url}")
            return False, "INVALID_HTML"

        # Passed all checks
        return True, None

    def fetch_page(
        self,
        url: str,
        page: Page,
        wait_for: str = "domcontentloaded",
        extra_wait: float = 0,
    ) -> Optional[str]:
        """
        Fetch a page with all checks and rate limiting.

        Integrates Phase 2 enhancements:
        - Domain quarantine checks
        - Exponential backoff on errors
        - Automatic quarantine on 403, repeated 429, CAPTCHA
        - Retry-After header respect

        Args:
            url: URL to fetch
            page: Playwright Page object
            wait_for: Wait condition ('domcontentloaded', 'load', 'networkidle')
            extra_wait: Additional wait time in seconds after page load

        Returns:
            str: Page HTML content, or None if failed
        """
        domain = urlparse(url).netloc

        # Check if domain is quarantined (Task 11: Ethical Crawling)
        if self.domain_quarantine.is_quarantined(domain):
            quarantine_end = self.domain_quarantine.get_quarantine_end(domain)
            self.logger.warning(
                f"Domain {domain} is quarantined until {quarantine_end}, skipping"
            )
            self.stats["pages_skipped"] += 1
            return None

        # Check robots.txt
        if not self._check_robots(url):
            self.stats["pages_skipped"] += 1
            return None

        # Check for honeypot URL patterns
        if self._avoid_honeypot_patterns(url):
            self.logger.warning(f"Skipping honeypot URL: {url}")
            self.stats["pages_skipped"] += 1
            return None

        # Fetch page with retries and exponential backoff
        for attempt in range(self.max_retries):
            # Apply exponential backoff delay (Task 11)
            retry_attempt = self.domain_quarantine.get_retry_attempt(domain)
            backoff_delay = self.domain_quarantine.get_backoff_delay(retry_attempt)

            if backoff_delay > 0:
                self.logger.info(
                    f"Exponential backoff for {domain}: waiting {backoff_delay}s "
                    f"(retry attempt {retry_attempt})"
                )
                time.sleep(backoff_delay)

            try:
                self.logger.debug(f"Fetching {url} (attempt {attempt + 1}/{self.max_retries})")

                response = page.goto(url, wait_until=wait_for)

                if response is None:
                    self.logger.warning(f"No response from {url}")
                    continue

                # Handle HTTP errors
                if response.status >= 400:
                    self.logger.warning(f"HTTP {response.status} from {url}")

                    # 403 Forbidden - Quarantine domain and flag for headed mode
                    if response.status == 403:
                        self.logger.error(f"403 Forbidden from {domain} - quarantining")
                        self.domain_quarantine.quarantine_domain(
                            domain=domain,
                            reason="403_FORBIDDEN",
                            metadata={"url": url, "attempt": attempt}
                        )
                        # Record detection for hybrid mode (may upgrade to headed)
                        self.browser_profile_manager.record_detection(domain, "403_FORBIDDEN")
                        self.browser_profile_manager.record_failure(domain, self._current_headed_mode, "403_FORBIDDEN")
                        self.stats["pages_failed"] += 1
                        return None

                    # 429 Rate Limited - Record event (auto-quarantines after 3) (Task 11)
                    if response.status == 429:
                        self.domain_quarantine.record_error_event(domain, "429")

                        # Check for Retry-After header
                        retry_after = response.headers.get('retry-after')
                        retry_after_seconds = None

                        if retry_after:
                            try:
                                retry_after_seconds = int(retry_after)
                                self.logger.info(
                                    f"Rate limited, Retry-After: {retry_after_seconds}s"
                                )
                            except ValueError:
                                # Retry-After might be a date, ignore for now
                                pass

                        # Use exponential backoff if no Retry-After
                        wait_time = retry_after_seconds if retry_after_seconds else (
                            self._get_random_delay() * 2
                        )

                        self.logger.info(f"Rate limited, waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue

                    # 5xx Server Errors - Record event (auto-quarantines after 3) (Task 11)
                    if response.status >= 500:
                        self.domain_quarantine.record_error_event(
                            domain,
                            f"{response.status}"
                        )
                        self.logger.warning(
                            f"Server error {response.status}, retrying with backoff..."
                        )
                        continue

                    # Other client errors - don't retry
                    self.stats["pages_failed"] += 1
                    return None

                # Extra wait for JavaScript rendering
                if extra_wait > 0:
                    time.sleep(extra_wait)

                # Simulate human behavior after page load (looks more natural)
                self._simulate_human_behavior(page, intensity="normal")

                # Get page content
                content = page.content()

                # Validate HTML response
                content_type = response.headers.get('content-type')
                is_valid, reason_code = self._validate_html_response(content, url, content_type)

                if not is_valid:
                    self.logger.warning(f"HTML validation failed for {url}: {reason_code}")

                    # Quarantine domain on CAPTCHA or bot detection (Task 11)
                    if reason_code in ("CAPTCHA_DETECTED", "BOT_DETECTED"):
                        self.logger.error(
                            f"{reason_code} on {domain} - quarantining for 60 minutes"
                        )
                        self.domain_quarantine.quarantine_domain(
                            domain=domain,
                            reason=reason_code,
                            duration_minutes=60,
                            metadata={"url": url, "validation_failure": reason_code}
                        )
                        # Record detection for hybrid mode (upgrades to headed after threshold)
                        self.browser_profile_manager.record_detection(domain, reason_code)
                        self.browser_profile_manager.record_failure(domain, self._current_headed_mode, reason_code)

                    self.stats["pages_failed"] += 1
                    return None

                # SUCCESS - Reset retry attempts (Task 11)
                self.domain_quarantine.reset_retry_attempts(domain)

                # Record success for hybrid mode statistics
                self.browser_profile_manager.record_success(domain, self._current_headed_mode)

                self.stats["pages_crawled"] += 1
                self.logger.debug(f"Fetched {url} ({len(content)} chars) - validation passed")

                # Add random delay before next request
                delay = self._get_random_delay()
                time.sleep(delay)

                return content

            except PlaywrightTimeout as e:
                self.logger.warning(f"Timeout fetching {url}: {e}")
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
        self.browser_profile_manager.record_failure(domain, self._current_headed_mode, "MAX_RETRIES_EXCEEDED")
        self.logger.error(f"Failed to fetch {url} after {self.max_retries} attempts")
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
