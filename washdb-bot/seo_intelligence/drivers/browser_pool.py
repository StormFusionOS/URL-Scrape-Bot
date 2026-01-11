"""
Enterprise Browser Pool

A lease-based browser pool system with warm sessions, context recycling,
and adaptive concurrency for SEO scraping.

Features:
- Long-lived browser instances to reduce startup overhead
- Pre-warmed sessions for better detection evasion
- Lease-based access with heartbeat monitoring
- Automatic escalation through browser types on CAPTCHA
- Session recycling based on TTL, navigation caps, and health
- Thread-safe for concurrent access
"""

import os
import random
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, Generator, List, Optional, Tuple

from runner.logging_setup import get_logger

from .pool_models import (
    BrowserSession,
    BrowserType,
    ESCALATION_ORDER,
    PoolStats,
    RecycleAction,
    SessionLease,
    SessionState,
    TARGET_GROUP_CONFIGS,
    TargetGroupConfig,
    get_next_escalation_type,
    get_target_group_for_domain,
)
from .pool_metrics import get_pool_metrics, LeaseMetrics
from .human_behavior import (
    move_mouse_naturally_selenium,
    move_mouse_naturally_playwright,
    scroll_naturally_selenium,
    scroll_naturally_playwright,
    click_safe_element_selenium,
    click_safe_element_playwright,
    simulate_reading_selenium,
    simulate_reading_playwright,
)
from .warmup_reputation import get_warmup_reputation_tracker

logger = get_logger("browser_pool")


# Environment configuration
POOL_ENABLED = os.getenv("BROWSER_POOL_ENABLED", "true").lower() == "true"
POOL_MIN_SESSIONS = int(os.getenv("BROWSER_POOL_MIN_SESSIONS", "6"))
POOL_MAX_SESSIONS = int(os.getenv("BROWSER_POOL_MAX_SESSIONS", "10"))
SESSION_TTL_MINUTES = int(os.getenv("BROWSER_POOL_SESSION_TTL", "60"))
IDLE_TTL_MINUTES = int(os.getenv("BROWSER_POOL_IDLE_TTL", "15"))
NAVIGATION_CAP = int(os.getenv("BROWSER_POOL_NAVIGATION_CAP", "150"))
LEASE_TIMEOUT_SECONDS = int(os.getenv("BROWSER_POOL_LEASE_TIMEOUT", "300"))
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("BROWSER_POOL_HEARTBEAT_INTERVAL", "30"))
WARMUP_FREQUENCY_SECONDS = int(os.getenv("BROWSER_POOL_WARMUP_FREQUENCY", "1800"))

# Maximum time to wait for a session
MAX_ACQUIRE_WAIT_SECONDS = 300  # 5 minutes - allow pool warmup time

# Chrome process limits
# Each browser session spawns ~20 Chrome processes (main + renderer + GPU + utility)
# With POOL_MAX=10, expect up to 200 Chrome processes normally
MAX_CHROME_PROCESSES = 150  # Warn and clean orphans
CRITICAL_CHROME_PROCESSES = 250  # Force aggressive cleanup
EMERGENCY_CHROME_PROCESSES = 350  # Hard cap - emergency cleanup
CHROME_CLEANUP_INTERVAL = 60  # Check every minute

# Self-healing thresholds
QUARANTINE_RECOVERY_THRESHOLD = 0.30  # Auto-recovery if >30% sessions quarantined
MIN_HEALTHY_SESSIONS = 3  # Minimum warm sessions before triggering recovery
ACQUISITION_TIMEOUT_RATE_THRESHOLD = 0.10  # Trigger cleanup if >10% timeouts


class EnterpriseBrowserPool:
    """
    Enterprise Browser Pool Manager.

    Provides lease-based access to warm browser sessions with:
    - Target group routing (search_engines, directories, general)
    - Session state machine (COLD → WARMING → IDLE_WARM → LEASED → ...)
    - Context recycling based on TTL and navigation caps
    - Automatic browser type escalation on CAPTCHA
    - Thread-safe concurrent access
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """Initialize the browser pool."""
        if self._initialized:
            return

        self._initialized = True
        self._enabled = POOL_ENABLED

        # Main pool storage
        self._sessions: Dict[str, BrowserSession] = {}
        self._leases: Dict[str, SessionLease] = {}

        # Threading primitives
        self._pool_lock = threading.RLock()
        self._session_locks: Dict[str, threading.Lock] = {}
        self._session_available = threading.Condition(self._pool_lock)

        # Statistics
        self._stats = PoolStats()
        self._total_leases_issued = 0
        self._lease_durations: List[float] = []

        # Background threads
        self._warmer_thread: Optional[threading.Thread] = None
        self._recycler_thread: Optional[threading.Thread] = None
        self._heartbeat_monitor_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()

        # Chrome process cleanup tracking
        self._last_chrome_cleanup = datetime.now()

        # Drain mode - stop accepting new leases during cleanup
        self._drain_mode = False
        self._drain_started = None
        self._drain_timeout = 60  # Max seconds to wait for drain

        # Recovery mode - extended warmup after cleanup
        self._recovery_mode = False
        self._recovery_started = None
        self._recovery_success_count = 0
        self._recovery_success_threshold = 10  # Exit recovery after N successful sessions

        # Self-healing metrics (rolling window)
        self._acquisition_attempts = 0
        self._acquisition_timeouts = 0
        self._last_health_check = datetime.now()
        self._health_check_interval = 60  # Check health every 60 seconds
        self._consecutive_timeouts = 0  # Track consecutive timeouts for immediate action

        # Driver creation functions (lazy import to avoid circular deps)
        self._driver_factories = {}

        logger.info(f"EnterpriseBrowserPool initialized (enabled={self._enabled})")

        if self._enabled:
            self._start_background_threads()

    def _get_session_lock(self, session_id: str) -> threading.Lock:
        """Get or create a lock for a specific session."""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = threading.Lock()
        return self._session_locks[session_id]

    def _start_background_threads(self):
        """Start background worker threads."""
        # Warmer thread - keeps sessions warm
        self._warmer_thread = threading.Thread(
            target=self._warmer_loop,
            name="BrowserPool-Warmer",
            daemon=True,
        )
        self._warmer_thread.start()

        # Recycler thread - handles TTL and navigation caps
        self._recycler_thread = threading.Thread(
            target=self._recycler_loop,
            name="BrowserPool-Recycler",
            daemon=True,
        )
        self._recycler_thread.start()

        # Heartbeat monitor - reclaims stale leases
        self._heartbeat_monitor_thread = threading.Thread(
            target=self._heartbeat_monitor_loop,
            name="BrowserPool-HeartbeatMonitor",
            daemon=True,
        )
        self._heartbeat_monitor_thread.start()

        logger.info("Background threads started")

    def is_enabled(self) -> bool:
        """Check if pool is enabled."""
        return self._enabled

    def _safe_quit_driver(self, driver: Any, session_id: str = None) -> None:
        """
        Safely quit a driver and release its resources.

        Args:
            driver: Browser driver to quit
            session_id: Optional session ID for process cleanup
        """
        if driver is None:
            return

        # Get driver PID before quitting (for force-kill if needed)
        driver_pid = None
        try:
            if hasattr(driver, 'service') and hasattr(driver.service, 'process'):
                driver_pid = driver.service.process.pid
        except Exception:
            pass

        # Release debugging port if allocated
        debug_port = getattr(driver, '_debug_port', None)
        if debug_port:
            try:
                from .seleniumbase_drivers import _release_debugging_port
                _release_debugging_port(debug_port)
            except Exception as e:
                logger.debug(f"Could not release port {debug_port}: {e}")

        # Terminate session processes via ChromeProcessManager if we have session_id
        if session_id:
            try:
                from .chrome_process_manager import get_chrome_process_manager
                pm = get_chrome_process_manager()
                pm.terminate_session_processes(session_id, graceful=True)
            except Exception as e:
                logger.debug(f"Could not terminate session processes: {e}")

        # Quit the driver
        try:
            driver.quit()
        except Exception as e:
            logger.debug(f"Error quitting driver: {e}")
            # If quit failed and we have PID, force kill
            if driver_pid:
                try:
                    import os
                    import signal
                    os.kill(driver_pid, signal.SIGKILL)
                    logger.debug(f"Force killed driver PID {driver_pid}")
                except Exception:
                    pass

    def _create_driver_with_stealth(
        self,
        browser_type: BrowserType,
        target_group: str = "general",
    ) -> Tuple[Optional[Any], Optional[Any]]:
        """
        Create a browser driver with full stealth configuration.

        Uses residential proxies with geo-matching for timezone, geolocation,
        and other fingerprint consistency. Each session gets a sticky proxy
        that stays bound for the session lifetime.

        Args:
            browser_type: Type of browser to create
            target_group: Target group for proxy selection hints

        Returns:
            Tuple of (driver, proxy) or (None, None) on failure
        """
        try:
            # Lazy import to avoid circular dependencies
            from .seleniumbase_drivers import (
                get_uc_driver_with_residential_proxy,
                configure_browser_for_proxy,
                set_browser_timezone,
                set_browser_geolocation,
            )
            # CamoufoxDriver imported inline where needed
            from seo_intelligence.services.residential_proxy_manager import (
                get_residential_proxy_manager,
                ResidentialProxy,
            )

            # Get residential proxy manager for geo-aware proxies
            proxy_manager = get_residential_proxy_manager()

            if browser_type in (BrowserType.SELENIUM_UC, BrowserType.SELENIUM_UC_FRESH):
                # Map target group to directory hint for proxy selection
                directory_hint = {
                    "search_engines": "pool_other",  # General pool for search engines
                    "directories": "yellowpages",    # Directory pool
                    "general": "pool_other",
                }.get(target_group, "pool_other")

                # Get driver with residential proxy (includes timezone/geo matching)
                driver, proxy = get_uc_driver_with_residential_proxy(
                    directory=directory_hint,
                    headless=False,  # Headed mode for better detection evasion
                    use_virtual_display=True,
                )

                if driver and proxy:
                    # Apply additional stealth measures
                    self._apply_extra_stealth(driver, proxy)
                    return driver, proxy
                else:
                    logger.warning("Failed to get driver with residential proxy, falling back")
                    # Fallback to basic UC driver
                    from .seleniumbase_drivers import get_uc_driver
                    driver = get_uc_driver(
                        headless=False,
                        use_proxy=True,
                        use_proxy_extension=True,
                    )
                    return driver, None

            elif browser_type in (BrowserType.CAMOUFOX, BrowserType.CAMOUFOX_NEW_FP):
                # Camoufox has its own fingerprint protection
                # Import CamoufoxDriver directly (not context manager) for pool persistence
                from .camoufox_drivers import CamoufoxDriver

                # Get a proxy for it
                proxy = proxy_manager.get_proxy_for_directory("pool_other")

                if proxy:
                    browser_config = proxy_manager.get_browser_config(proxy)
                    proxy_config = browser_config.get("proxy", {})
                    timezone = browser_config.get("timezone_id")
                    geolocation = browser_config.get("geolocation")

                    driver = CamoufoxDriver(
                        headless=False,
                        humanize=True,
                        new_fingerprint=(browser_type == BrowserType.CAMOUFOX_NEW_FP),
                        proxy=proxy_config,
                        timezone=timezone,
                        geolocation=geolocation,
                    )
                    logger.info(f"Created Camoufox driver with residential proxy {proxy.host} "
                               f"({proxy.city_name}, {proxy.state} - TZ: {proxy.timezone})")
                    return driver, proxy
                else:
                    # Fallback without proxy
                    driver = CamoufoxDriver(headless=False, humanize=True)
                    logger.warning("No proxy available for Camoufox, using direct connection")
                    return driver, None

        except Exception as e:
            logger.error(f"Failed to create {browser_type.value} driver with stealth: {e}")
            import traceback
            traceback.print_exc()

        return None, None

    def _apply_extra_stealth(self, driver: Any, proxy: Any) -> None:
        """
        Apply additional stealth measures beyond basic timezone/geo matching.

        Args:
            driver: Browser driver
            proxy: Residential proxy with geo data
        """
        try:
            # WebRTC leak prevention - disable WebRTC or force it through proxy
            try:
                driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                    "userAgent": driver.execute_script("return navigator.userAgent"),
                    "platform": "Win32",  # Consistent platform
                })
            except Exception:
                pass

            # Disable WebRTC IP leak (Chrome specific)
            try:
                driver.execute_script("""
                    // Override WebRTC to prevent IP leaks
                    Object.defineProperty(navigator, 'mediaDevices', {
                        get: function() {
                            return {
                                getUserMedia: function() {
                                    return Promise.reject(new Error('Permission denied'));
                                },
                                enumerateDevices: function() {
                                    return Promise.resolve([]);
                                }
                            };
                        }
                    });
                """)
            except Exception:
                pass

            # Set navigator properties for consistency
            if proxy and hasattr(proxy, 'timezone'):
                try:
                    # Override Date to use proxy timezone
                    tz_offset = getattr(proxy, 'timezone_offset', -300)
                    driver.execute_script(f"""
                        // Store original Date
                        const OriginalDate = Date;
                        const tzOffset = {tz_offset};

                        // Override getTimezoneOffset
                        Date.prototype.getTimezoneOffset = function() {{
                            return tzOffset;
                        }};
                    """)
                except Exception:
                    pass

            # Navigator language consistency - match locale to proxy country
            if proxy and hasattr(proxy, 'country_code'):
                try:
                    # Map country codes to locale strings
                    country_locale_map = {
                        "US": "en-US",
                        "CA": "en-CA",
                        "GB": "en-GB",
                        "UK": "en-GB",
                        "AU": "en-AU",
                        "NZ": "en-NZ",
                        "IE": "en-IE",
                        "DE": "de-DE",
                        "FR": "fr-FR",
                        "ES": "es-ES",
                        "IT": "it-IT",
                        "NL": "nl-NL",
                        "BR": "pt-BR",
                        "MX": "es-MX",
                    }
                    lang = country_locale_map.get(proxy.country_code, "en-US")
                    # Build languages array with fallbacks
                    base_lang = lang.split("-")[0]
                    languages = [lang, base_lang] if base_lang != lang else [lang]
                    if base_lang != "en":
                        languages.append("en")
                    languages_str = ", ".join(f"'{l}'" for l in languages)

                    driver.execute_script(f"""
                        Object.defineProperty(navigator, 'language', {{
                            get: function() {{ return '{lang}'; }}
                        }});
                        Object.defineProperty(navigator, 'languages', {{
                            get: function() {{ return [{languages_str}]; }}
                        }});
                    """)
                except Exception:
                    pass

            # HTTP header randomization with Sec-Ch-Ua headers matching user agent
            try:
                user_agent = driver.execute_script("return navigator.userAgent")

                # Extract Chrome version from user agent
                import re
                chrome_match = re.search(r'Chrome/(\d+)', user_agent)
                chrome_version = chrome_match.group(1) if chrome_match else "120"

                # Build realistic Sec-Ch-Ua header
                sec_ch_ua = f'"Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}", "Not-A.Brand";v="99"'

                # Detect platform from user agent
                if "Windows" in user_agent:
                    platform = "Windows"
                elif "Mac" in user_agent:
                    platform = "macOS"
                elif "Linux" in user_agent:
                    platform = "Linux"
                else:
                    platform = "Windows"

                # Set extra HTTP headers via CDP
                headers = {
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': lang if 'lang' in dir() else 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Ch-Ua': sec_ch_ua,
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': f'"{platform}"',
                }

                driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {'headers': headers})
                logger.debug(f"Set Sec-Ch-Ua headers for Chrome/{chrome_version} on {platform}")

            except Exception as e:
                logger.debug(f"Could not set extra HTTP headers: {e}")

            logger.debug(f"Applied extra stealth measures for proxy {proxy.host if proxy else 'unknown'}")

        except Exception as e:
            logger.warning(f"Error applying extra stealth: {e}")

    def _create_session(
        self,
        target_group: str = "general",
        browser_type: BrowserType = BrowserType.SELENIUM_UC,
    ) -> Optional[BrowserSession]:
        """
        Create a new browser session with full stealth configuration.

        Each session gets:
        - A sticky residential proxy (bound for session lifetime)
        - Timezone matching the proxy location
        - Geolocation matching the proxy location
        - WebRTC leak prevention
        - Consistent navigator properties

        Args:
            target_group: Target group for the session
            browser_type: Type of browser to use

        Returns:
            BrowserSession or None on failure
        """
        session = BrowserSession(
            target_group=target_group,
            browser_type=browser_type,
            state=SessionState.COLD,
        )

        # Create driver with stealth configuration
        driver, proxy = self._create_driver_with_stealth(browser_type, target_group)
        if driver is None:
            logger.error(f"Failed to create driver for session {session.session_id}")
            session.state = SessionState.DEAD
            return None

        session.driver = driver
        session.proxy = proxy  # Sticky proxy binding
        session.proxy_assigned_at = datetime.now()
        session.state = SessionState.WARMING

        with self._pool_lock:
            self._sessions[session.session_id] = session
            self._session_locks[session.session_id] = threading.Lock()

        proxy_info = f"{proxy.host} ({proxy.city_name}, {proxy.state})" if proxy else "no proxy"
        logger.info(f"Created session {session.session_id[:8]} ({target_group}, {browser_type.value}) with {proxy_info}")
        return session

    def _is_page_blocked(self, driver: Any, url: str) -> bool:
        """
        Check if a page shows actual block/CAPTCHA indicators.

        This performs intelligent detection rather than naive string matching,
        since many sites (YouTube, etc.) have words like "blocked" or "captcha"
        in their JavaScript code but aren't actually blocking the browser.

        Args:
            driver: Browser driver
            url: URL being checked (for context)

        Returns:
            True if page appears to be blocked or showing CAPTCHA
        """
        try:
            # Get page info
            page_source = driver.page_source.lower() if hasattr(driver, 'page_source') else ""
            title = driver.title.lower() if hasattr(driver, 'title') else ""
            current_url = driver.current_url.lower() if hasattr(driver, 'current_url') else ""

            # Check 1: Redirected to security challenge pages
            block_url_indicators = [
                "challenge",  # Cloudflare challenge
                "/captcha",
                "/blocked",
                "sorry/index",  # Google sorry page
                "ipv4.google.com/sorry",
            ]
            if any(indicator in current_url for indicator in block_url_indicators):
                logger.debug(f"Block detected via URL redirect: {current_url}")
                return True

            # Check 2: Block page titles (explicit block indicators)
            # These need to be full-title matches or start-of-title to avoid false positives
            block_titles_exact = [
                "access denied",
                "403 forbidden",
                "just a moment",  # Cloudflare waiting page
                "attention required",  # Cloudflare
                "please verify",
                "security check",
            ]
            # Only flag if title STARTS with or IS the block message
            # (avoids false positives like "Blocked Questions - Stack Overflow")
            if any(title.startswith(bt) or title == bt for bt in block_titles_exact):
                logger.debug(f"Block detected via title: {title}")
                return True

            # Check 3: reCAPTCHA iframe (actual challenge, not just the word in JS)
            # Look for the iframe src, not just "captcha" anywhere
            recaptcha_indicators = [
                'src="https://www.google.com/recaptcha',
                "src='https://www.google.com/recaptcha",
                'data-sitekey=',  # reCAPTCHA sitekey attribute
                'class="g-recaptcha"',
                "class='g-recaptcha'",
                'id="recaptcha"',
            ]
            if any(indicator in page_source for indicator in recaptcha_indicators):
                # Double check it's not just a config reference
                if 'iframe' in page_source and 'recaptcha' in page_source:
                    logger.debug(f"Block detected via reCAPTCHA iframe")
                    return True

            # Check 4: Explicit block messages in visible content
            # These should appear in text, not hidden in JS config
            # Be very specific to avoid false positives in news/content sites
            block_messages = [
                "you have been blocked",
                "access to this page has been denied",
                "please verify you are a human",
                "please complete the security check",
                "unusual traffic from your computer network",  # More specific
                "our systems have detected unusual traffic from your",  # More specific
            ]
            # Only check first 20KB to focus on visible page content
            visible_content = page_source[:20000]
            if any(msg in visible_content for msg in block_messages):
                logger.debug(f"Block detected via explicit message")
                return True

            # Check 5: Cloudflare challenge page structure
            if "cf-browser-verification" in page_source or "cf_chl_opt" in page_source:
                logger.debug(f"Block detected via Cloudflare challenge")
                return True

            # Check 6: PerimeterX (px) challenge
            if "_pxcaptcha" in page_source or "perimeterx" in page_source:
                logger.debug(f"Block detected via PerimeterX")
                return True

            return False

        except Exception as e:
            logger.warning(f"Error checking block status: {e}")
            return False  # Assume not blocked on error

    def _check_for_honeypots(self, driver: Any) -> bool:
        """
        Check for suspicious honeypot traps on the current page.

        Honeypots are invisible elements designed to catch bots.
        Real users never interact with them.

        This check is conservative to avoid false positives - modern sites
        have many hidden elements (navigation, dropdowns, etc.) that are
        legitimate.

        Returns:
            True if suspicious honeypots detected (page should be treated carefully)
        """
        try:
            # Check for truly suspicious honeypots:
            # - Elements positioned off-screen (negative coords)
            # - Links with suspicious trap-like patterns
            # - Elements with deceptive styling (1px size but clickable)
            honeypot_check = driver.execute_script("""
                const links = document.querySelectorAll('a');
                let suspiciousCount = 0;

                for (let link of links) {
                    const style = window.getComputedStyle(link);
                    const rect = link.getBoundingClientRect();

                    // Only flag truly suspicious patterns:
                    // 1. Positioned way off-screen (bot trap)
                    const offScreen = rect.left < -1000 || rect.top < -1000;

                    // 2. Has suspicious class/id names
                    const suspiciousName = /honey|trap|bot|catch|hidden.*link/i.test(
                        (link.className || '') + (link.id || '')
                    );

                    // 3. Invisible but with high z-index (overlay trap)
                    const overlayTrap = (
                        style.opacity === '0' &&
                        parseInt(style.zIndex) > 1000
                    );

                    if (offScreen || suspiciousName || overlayTrap) {
                        suspiciousCount++;
                    }
                }

                return suspiciousCount;
            """)

            # Only flag if there are multiple obvious traps
            if honeypot_check and honeypot_check > 3:
                logger.debug(f"Detected {honeypot_check} suspicious honeypot patterns")
                return True

            return False

        except Exception as e:
            logger.debug(f"Honeypot check failed: {e}")
            return False

    def _verify_js_execution(self, driver: Any) -> bool:
        """
        Verify that JavaScript is executing properly.

        This ensures the browser can handle JS-heavy sites correctly.

        Returns:
            True if JS is working properly
        """
        try:
            # Test 1: Basic JS execution
            result = driver.execute_script("return 1 + 1")
            if result != 2:
                return False

            # Test 2: DOM manipulation
            driver.execute_script("""
                const testDiv = document.createElement('div');
                testDiv.id = 'js-test-element';
                testDiv.style.display = 'none';
                document.body.appendChild(testDiv);
            """)

            # Verify element was created
            element_exists = driver.execute_script(
                "return document.getElementById('js-test-element') !== null"
            )
            if not element_exists:
                return False

            # Clean up
            driver.execute_script("""
                const el = document.getElementById('js-test-element');
                if (el) el.remove();
            """)

            # Test 3: Async/Promise support
            async_result = driver.execute_script("""
                return new Promise(resolve => {
                    setTimeout(() => resolve('async-ok'), 100);
                });
            """)
            if async_result != 'async-ok':
                return False

            # Test 4: Fetch API availability
            fetch_available = driver.execute_script("return typeof fetch === 'function'")
            if not fetch_available:
                logger.warning("Fetch API not available")
                # Not a failure, just a warning

            return True

        except Exception as e:
            logger.warning(f"JS verification failed: {e}")
            return False

    def _simulate_human_reading(self, driver: Any, session: BrowserSession, min_time: float = 3, max_time: float = 8):
        """
        Simulate human reading behavior with realistic scroll patterns and mouse movement.

        Uses bezier curve mouse movement and natural scrolling from human_behavior module.
        """
        try:
            # Check if this is a Playwright/Camoufox driver or Selenium
            if session.browser_type in (BrowserType.CAMOUFOX, BrowserType.CAMOUFOX_NEW_FP):
                # Camoufox uses Playwright
                if hasattr(driver, '_page'):
                    simulate_reading_playwright(driver._page, min_time, max_time)
                else:
                    time.sleep(random.uniform(min_time, max_time))
            else:
                # Selenium UC - use new natural scrolling with bezier mouse movement
                simulate_reading_selenium(driver, min_time, max_time)

        except Exception as e:
            logger.debug(f"Human reading simulation error: {e}")
            time.sleep(random.uniform(min_time, max_time))

    def _click_safe_element(self, driver: Any, session: BrowserSession) -> bool:
        """
        Click on a safe, visible element to simulate user interaction.

        Uses bezier curve mouse movement for natural clicking behavior.
        Delegates to human_behavior module for Selenium or Playwright.
        """
        try:
            # Check if this is a Playwright/Camoufox driver or Selenium
            if session.browser_type in (BrowserType.CAMOUFOX, BrowserType.CAMOUFOX_NEW_FP):
                # Camoufox uses Playwright
                if hasattr(driver, '_page'):
                    return click_safe_element_playwright(driver._page)
                return False
            else:
                # Selenium UC - use new click with bezier mouse movement
                return click_safe_element_selenium(driver)

        except Exception as e:
            logger.debug(f"Safe click failed: {e}")
            return False

    def _click_safe_element_legacy(self, driver: Any) -> bool:
        """
        Legacy click method - kept for reference.

        Only clicks on elements that are:
        - Visible and not honeypots
        - Not form submissions
        - Not external links that might be traps
        """
        try:
            # Find safe clickable elements
            safe_elements = driver.execute_script("""
                const safeElements = [];
                const clickables = document.querySelectorAll('a, button, [role="button"]');

                for (let el of clickables) {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();

                    // Must be visible
                    if (style.display === 'none' ||
                        style.visibility === 'hidden' ||
                        rect.width === 0 ||
                        rect.height === 0) {
                        continue;
                    }

                    // Must be in viewport
                    if (rect.top < 0 || rect.top > window.innerHeight) {
                        continue;
                    }

                    // Skip external links
                    if (el.tagName === 'A' && el.href) {
                        const url = new URL(el.href, window.location.origin);
                        if (url.origin !== window.location.origin) {
                            continue;
                        }
                    }

                    // Skip form buttons
                    if (el.type === 'submit' || el.closest('form')) {
                        continue;
                    }

                    // Skip anything that looks like login/signup
                    const text = el.textContent.toLowerCase();
                    if (text.includes('login') ||
                        text.includes('sign') ||
                        text.includes('subscribe') ||
                        text.includes('newsletter')) {
                        continue;
                    }

                    safeElements.push({
                        tag: el.tagName,
                        text: el.textContent.substring(0, 50),
                        x: rect.x + rect.width/2,
                        y: rect.y + rect.height/2
                    });
                }

                return safeElements.slice(0, 10);  // Return up to 10 candidates
            """)

            if not safe_elements:
                return False

            # Pick a random safe element
            element = random.choice(safe_elements)
            logger.debug(f"Clicking safe element: {element['tag']} - {element['text'][:30]}")

            # Move to element and click (human-like)
            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(driver)

            # Small random offset for natural clicking
            offset_x = random.randint(-5, 5)
            offset_y = random.randint(-5, 5)

            # Use JavaScript click for reliability
            driver.execute_script(f"""
                const el = document.elementFromPoint({element['x']}, {element['y']});
                if (el) el.click();
            """)

            time.sleep(random.uniform(0.5, 1.5))
            return True

        except Exception as e:
            logger.debug(f"Safe click failed: {e}")
            return False

    def _warm_session(self, session: BrowserSession) -> bool:
        """
        Execute comprehensive warm plan for a session.

        This is an enterprise-grade tiered warmup that:
        - Uses safe-first URL selection (Tier S → A → B)
        - Visits 5-10 diverse sites with tier-appropriate behavior
        - Simulates realistic human browsing behavior
        - Verifies JS execution works correctly
        - Avoids bot-aware sites early in warmup
        - Builds authentic cookies and browsing history

        Args:
            session: Session to warm

        Returns:
            True if warming succeeded
        """
        from .pool_models import WARMUP_CONFIG
        from .tiered_warmup_adapter import TieredWarmupAdapter, get_tiered_warmup_urls_legacy

        if session.driver is None:
            return False

        config = TARGET_GROUP_CONFIGS.get(session.target_group)
        if config is None:
            config = TARGET_GROUP_CONFIGS["general"]

        try:
            session.state = SessionState.WARMING
            driver = session.driver
            successful_warmups = 0
            js_verified = False

            # Use tiered warmup system for safer-first URL selection
            reputation_tracker = get_warmup_reputation_tracker()

            if WARMUP_CONFIG.get("use_tiered_warmup", True):
                # Generate tiered warmup URLs (S → A → B pattern)
                num_sites = random.randint(
                    WARMUP_CONFIG["min_sites_to_visit"],
                    WARMUP_CONFIG["max_sites_to_visit"]
                )

                # Create tiered adapter with target-group-specific settings
                adapter = TieredWarmupAdapter(
                    tier_c_probability=WARMUP_CONFIG.get("tier_c_probability", 0.35),
                    enforce_no_domain_reuse=WARMUP_CONFIG.get("enforce_no_domain_reuse", True),
                )

                warmup_urls = adapter.get_warmup_urls(
                    count=num_sites,
                    is_rewarm=False,
                )
            else:
                # Fallback to legacy URL selection
                all_urls = list(config.warmup_urls)
                num_sites = random.randint(
                    WARMUP_CONFIG["min_sites_to_visit"],
                    min(WARMUP_CONFIG["max_sites_to_visit"], len(all_urls))
                )

                warmup_urls = reputation_tracker.get_prioritized_warmup_urls(
                    base_urls=all_urls,
                    count=num_sites,
                    include_new=True
                )

            logger.info(f"Session {session.session_id[:8]} starting comprehensive warmup ({len(warmup_urls)} sites)")

            # Visit warmup URLs with human-like behavior
            for i, url_tuple in enumerate(warmup_urls):
                # Handle both 3-tuple and 4-tuple formats
                if len(url_tuple) >= 4:
                    url, min_wait, max_wait, category = url_tuple[:4]
                else:
                    url, min_wait, max_wait = url_tuple[:3]
                    category = "general"

                url_success = False
                try:
                    logger.debug(f"Session {session.session_id[:8]} [{i+1}/{len(warmup_urls)}] visiting: {url}")

                    # Use timeout-protected URL visit to prevent hangs
                    if not self._visit_url_with_timeout(driver, url, timeout=30):
                        reputation_tracker.record_failure(url, timeout=True, reason="timeout")
                        continue

                    # Initial load wait
                    time.sleep(random.uniform(min_wait, max_wait))

                    # Check for blocks
                    if self._is_page_blocked(driver, url):
                        logger.warning(f"Session {session.session_id[:8]} blocked at {url}")
                        session.captcha_count += 1
                        # Track blocked URL
                        reputation_tracker.record_failure(url, blocked=True, reason="blocked")
                        continue

                    # Check for honeypots (on first few sites) - just log, don't skip
                    has_honeypots = i < 3 and self._check_for_honeypots(driver)
                    if has_honeypots:
                        logger.debug(f"Honeypot patterns at {url}, will avoid clicking")

                    # Verify JS execution (once per session)
                    if not js_verified and WARMUP_CONFIG["verify_js_execution"]:
                        if self._verify_js_execution(driver):
                            js_verified = True
                            logger.debug(f"Session {session.session_id[:8]} JS verification passed")
                        else:
                            logger.warning(f"Session {session.session_id[:8]} JS verification failed")

                    # Simulate human reading/scrolling with bezier mouse movement
                    if random.random() < WARMUP_CONFIG["scroll_probability"]:
                        self._simulate_human_reading(
                            driver,
                            session,
                            WARMUP_CONFIG["read_time_min"],
                            WARMUP_CONFIG["read_time_max"]
                        )

                    # Occasionally click safe elements with natural mouse movement
                    if not has_honeypots and random.random() < WARMUP_CONFIG["click_probability"]:
                        self._click_safe_element(driver, session)

                    # Mark as successful
                    url_success = True
                    successful_warmups += 1

                    # Track successful URL
                    reputation_tracker.record_success(url)

                    # Random delay between sites (human-like pacing)
                    if i < len(warmup_urls) - 1:
                        inter_site_delay = random.uniform(2, 5)
                        time.sleep(inter_site_delay)

                except Exception as e:
                    logger.warning(f"Warmup error at {url}: {e}")
                    # Track failed URL (timeout or other error)
                    reputation_tracker.record_failure(
                        url,
                        timeout="timeout" in str(e).lower(),
                        reason=str(e)[:100]
                    )
                    # Continue with other URLs

            # Require at least 40% success rate for warmup to pass (min 3 sites)
            min_required = max(3, int(len(warmup_urls) * 0.4))
            if successful_warmups >= min_required:
                session.last_warmed_at = datetime.now()
                session.state = SessionState.IDLE_WARM
                logger.info(
                    f"Session {session.session_id[:8]} warmed successfully "
                    f"({successful_warmups}/{len(warmup_urls)} sites, JS={'OK' if js_verified else 'FAIL'})"
                )
                get_pool_metrics().record_warmup(success=True)
                return True
            else:
                logger.warning(
                    f"Session {session.session_id[:8]} warmup failed "
                    f"({successful_warmups}/{len(warmup_urls)} sites, needed {min_required})"
                )
                session.state = SessionState.QUARANTINED
                get_pool_metrics().record_warmup(success=False)
                return False

        except Exception as e:
            logger.error(f"Failed to warm session {session.session_id[:8]}: {e}")
            session.state = SessionState.DEAD
            get_pool_metrics().record_warmup(success=False)
            return False

    def _visit_url_with_timeout(self, driver: Any, url: str, timeout: int = 30) -> bool:
        """
        Visit a URL with a timeout to prevent hangs.

        Uses shared executor to prevent thread exhaustion from creating
        new ThreadPoolExecutor for each URL visit.

        Args:
            driver: Browser driver
            url: URL to visit
            timeout: Max seconds to wait

        Returns:
            True if page loaded successfully
        """
        try:
            from seo_intelligence.utils.shared_executor import run_with_timeout
            run_with_timeout(driver.get, timeout, url)
            return True
        except FuturesTimeoutError:
            logger.warning(f"URL visit timed out after {timeout}s: {url}")
            return False
        except RuntimeError as e:
            # Thread exhaustion - log as error, not just warning
            logger.error(f"URL visit failed (thread exhaustion): {e}")
            return False
        except Exception as e:
            logger.warning(f"URL visit error: {e}")
            return False

    def resurrect_dead_sessions(self) -> int:
        """
        Attempt to resurrect DEAD sessions by recreating their drivers.

        This allows the pool to recover from failures without requiring
        a full restart. Called by the self-healing coordinator.

        Returns:
            Number of sessions successfully resurrected
        """
        import threading
        resurrected = 0

        with self._pool_lock:
            dead_sessions = [
                s for s in self._sessions.values()
                if s.state == SessionState.DEAD
            ]

        if not dead_sessions:
            return 0

        thread_count = threading.active_count()
        logger.info(f"Attempting to resurrect {len(dead_sessions)} dead sessions (threads: {thread_count})")

        # Check if thread exhaustion might prevent resurrection
        if thread_count > 2500:
            logger.warning(f"Thread count high ({thread_count}), resurrection may fail")

        for session in dead_sessions:
            try:
                logger.debug(f"Resurrecting session {session.session_id[:8]}")

                # Clean up old driver if any
                if session.driver:
                    self._safe_quit_driver(session.driver, session.session_id)
                    session.driver = None

                # Create new driver
                try:
                    driver, proxy = self._create_driver_with_stealth(
                        session.browser_type,
                        session.target_group
                    )
                except RuntimeError as e:
                    # Thread exhaustion
                    logger.error(f"Cannot create driver for {session.session_id[:8]}: {e}")
                    driver, proxy = None, None
                except Exception as e:
                    logger.error(f"Driver creation failed for {session.session_id[:8]}: {e}")
                    driver, proxy = None, None

                if driver:
                    session.driver = driver
                    session.proxy = proxy
                    session.state = SessionState.COLD
                    session.created_at = datetime.now()
                    session.navigation_count = 0
                    session.consecutive_failures = 0
                    session.captcha_count = 0

                    # Register driver PID with ChromeProcessManager
                    try:
                        if hasattr(driver, 'service') and hasattr(driver.service, 'process'):
                            from .chrome_process_manager import get_chrome_process_manager
                            pm = get_chrome_process_manager()
                            pm.register_process(
                                driver.service.process.pid,
                                session.session_id,
                                getattr(driver, '_debug_port', None)
                            )
                    except Exception:
                        pass

                    # Warm the resurrected session
                    if self._warm_session(session):
                        resurrected += 1
                        logger.info(f"Successfully resurrected session {session.session_id[:8]}")
                    else:
                        logger.warning(f"Resurrected session {session.session_id[:8]} but warmup failed")
                        session.state = SessionState.QUARANTINED
                else:
                    logger.warning(
                        f"Could not create driver for session {session.session_id[:8]} "
                        f"(threads: {threading.active_count()})"
                    )

            except Exception as e:
                logger.error(f"Failed to resurrect session {session.session_id[:8]}: {e}")

        logger.info(f"Resurrected {resurrected}/{len(dead_sessions)} dead sessions")

        return resurrected

    def _initialize_pool(self):
        """
        Initialize the pool with minimum sessions per target group.

        Uses round-robin initialization to ensure all groups have at least
        one session before filling to capacity. Sessions are warmed concurrently
        via ThreadPoolExecutor to prevent blocking startup.

        Respects POOL_MIN_SESSIONS env var to cap total sessions.
        """
        logger.info("Initializing browser pool...")

        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Calculate how many sessions per group based on global min
        num_groups = len(TARGET_GROUP_CONFIGS)
        sessions_per_group = max(1, POOL_MIN_SESSIONS // num_groups)

        logger.info(f"Target: {POOL_MIN_SESSIONS} total sessions, {sessions_per_group} per group")

        # Collect sessions to warm
        sessions_to_warm = []
        total_created = 0

        # Round-robin: create sessions until we hit the global limit
        for round_idx in range(sessions_per_group):
            for group_name, config in TARGET_GROUP_CONFIGS.items():
                if total_created >= POOL_MIN_SESSIONS:
                    break

                session = self._create_session(
                    target_group=group_name,
                    browser_type=BrowserType.SELENIUM_UC,
                )
                if session:
                    sessions_to_warm.append(session)
                    total_created += 1
                    if round_idx == 0:
                        logger.info(f"First session for {group_name} initialized")

            if total_created >= POOL_MIN_SESSIONS:
                break

        # Warm sessions concurrently to speed up initialization
        logger.info(f"Warming {len(sessions_to_warm)} sessions concurrently...")

        def warm_session_with_retry(session, max_retries: int = 3):
            """Warm a session with retry logic for resilience."""
            for attempt in range(max_retries):
                try:
                    # Reset session state if retrying
                    if attempt > 0 and session.state == SessionState.QUARANTINED:
                        session.state = SessionState.WARMING
                        logger.info(f"Retry {attempt + 1}/{max_retries} for session {session.session_id[:8]}")
                        # Brief pause between retries
                        time.sleep(2 + attempt * 2)

                    if self._warm_session(session):
                        return True

                    # Warmup failed but no exception - try again
                    if attempt < max_retries - 1:
                        logger.debug(f"Warmup attempt {attempt + 1} failed for {session.session_id[:8]}, retrying...")

                except Exception as e:
                    logger.warning(f"Warmup attempt {attempt + 1} error for {session.session_id[:8]}: {e}")
                    if attempt == max_retries - 1:
                        return False

            return False

        # Limit concurrency to prevent resource exhaustion (browsers crash with too many)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(warm_session_with_retry, s): s for s in sessions_to_warm}
            for future in as_completed(futures):
                session = futures[future]
                try:
                    success = future.result(timeout=300)  # 5 min timeout per warmup (includes retries)
                    if not success:
                        logger.warning(f"Failed to warm session {session.session_id[:8]} after all retries")
                        # Mark as dead so it gets cleaned up and replaced
                        session.state = SessionState.DEAD
                except Exception as e:
                    logger.warning(f"Warmup timeout/error for {session.session_id[:8]}: {e}")
                    session.state = SessionState.DEAD

        total = len(self._sessions)
        warm_count = len([s for s in self._sessions.values() if s.state == SessionState.IDLE_WARM])
        logger.info(f"Pool initialized with {total} sessions ({warm_count} warm)")

    def acquire_session(
        self,
        target_domain: str,
        requester: str,
        preferred_proxy: Optional[Any] = None,
        timeout_seconds: int = MAX_ACQUIRE_WAIT_SECONDS,
        lease_duration_seconds: int = LEASE_TIMEOUT_SECONDS,
    ) -> Optional[SessionLease]:
        """
        Acquire a browser session from the pool.

        Args:
            target_domain: Domain to be scraped (e.g., "google.com")
            requester: Name of requesting module
            preferred_proxy: Optional specific proxy to use
            timeout_seconds: How long to wait for available session
            lease_duration_seconds: Maximum lease duration

        Returns:
            SessionLease if successful, None if no session available
        """
        if not self._enabled:
            return None

        # Check if pool is in drain mode (cleanup in progress)
        if self._drain_mode:
            logger.warning(f"Pool in drain mode - rejecting lease request from {requester}")
            return None

        target_group = get_target_group_for_domain(target_domain)
        start_time = time.time()

        # Track acquisition attempt for self-healing metrics
        self._acquisition_attempts += 1

        # Exponential backoff intervals with jitter (avoid thundering herd)
        backoff_intervals = [0.1, 0.5, 1.0, 2.0, 5.0, 5.0, 5.0]  # Max out at 5s
        attempt = 0

        with self._session_available:
            while True:
                # Check drain mode again inside the loop
                if self._drain_mode:
                    logger.warning(f"Pool entered drain mode - rejecting lease request from {requester}")
                    return None

                # Find available session in target group
                session = self._find_available_session(target_group)

                if session:
                    # Verify session is actually alive before leasing
                    if not self.is_session_alive(session):
                        logger.warning(f"Session {session.session_id[:8]} is dead - invalidating")
                        self.invalidate_session(session.session_id, reason="dead_on_acquire")
                        continue  # Try to find another session
                    # Create lease
                    lease = SessionLease(
                        session_id=session.session_id,
                        leased_by=requester,
                        target_domain=target_domain,
                        timeout_at=datetime.now() + timedelta(seconds=lease_duration_seconds),
                        heartbeat_interval=HEARTBEAT_INTERVAL_SECONDS,
                    )

                    # Update session state
                    with self._get_session_lock(session.session_id):
                        session.state = SessionState.LEASED
                        session.lease_id = lease.lease_id
                        session.leased_at = datetime.now()
                        session.lease_timeout = lease.timeout_at
                        session.last_heartbeat = datetime.now()
                        session.leased_by = requester

                    # Track lease
                    self._leases[lease.lease_id] = lease
                    self._total_leases_issued += 1

                    # Record metrics (outside lock scope for better performance)
                    metrics = get_pool_metrics()
                    lease_metrics = metrics.record_lease_acquired(
                        lease_id=lease.lease_id,
                        session_id=session.session_id,
                        target_domain=target_domain,
                        target_group=target_group,
                        requester=requester,
                        browser_type=session.browser_type.value,
                        proxy_location=f"{session.proxy.city_name}, {session.proxy.state}" if session.proxy else None,
                    )
                    # Store metrics reference in lease for release
                    lease._metrics = lease_metrics

                    # Reset consecutive timeout counter on success
                    self._consecutive_timeouts = 0

                    logger.info(
                        f"Leased session {session.session_id[:8]} to {requester} "
                        f"for {target_domain} (group: {target_group})"
                    )
                    return lease

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed >= timeout_seconds:
                    # Track timeout for self-healing
                    self._acquisition_timeouts += 1
                    self._consecutive_timeouts += 1

                    logger.warning(
                        f"Timeout waiting for session (domain={target_domain}, "
                        f"group={target_group}, requester={requester}, "
                        f"consecutive_timeouts={self._consecutive_timeouts})"
                    )

                    # Trigger self-healing if needed
                    self._check_and_trigger_self_healing()

                    return None

                # Exponential backoff with jitter
                backoff_idx = min(attempt, len(backoff_intervals) - 1)
                base_wait = backoff_intervals[backoff_idx]
                jitter = base_wait * 0.2 * (2 * (hash(requester + str(time.time())) % 100) / 100 - 1)
                wait_time = max(0.05, base_wait + jitter)

                remaining = timeout_seconds - elapsed
                self._session_available.wait(timeout=min(remaining, wait_time))
                attempt += 1

    def _find_available_session(self, target_group: str) -> Optional[BrowserSession]:
        """Find an available session in the target group."""
        # First, try exact group match
        for session in self._sessions.values():
            if session.target_group == target_group and session.is_available:
                return session

        # If no exact match, try general pool
        if target_group != "general":
            for session in self._sessions.values():
                if session.target_group == "general" and session.is_available:
                    return session

        return None

    def release_session(
        self,
        lease: SessionLease,
        dirty: bool = False,
        dirty_reason: Optional[str] = None,
        detected_captcha: bool = False,
        detected_block: bool = False,
    ) -> bool:
        """
        Release a leased browser session back to the pool.

        Args:
            lease: The lease to release
            dirty: Whether session needs cleanup before reuse
            dirty_reason: Why session is dirty
            detected_captcha: CAPTCHA was encountered
            detected_block: Block/403 was encountered

        Returns:
            True if release successful
        """
        if lease.lease_id not in self._leases:
            logger.warning(f"Unknown lease {lease.lease_id}")
            return False

        session = self._sessions.get(lease.session_id)
        if session is None:
            logger.warning(f"Session {lease.session_id} not found")
            del self._leases[lease.lease_id]
            return False

        with self._get_session_lock(session.session_id):
            # Calculate lease duration
            if session.leased_at:
                duration = (datetime.now() - session.leased_at).total_seconds()
                self._lease_durations.append(duration)
                # Keep only last 100 durations
                if len(self._lease_durations) > 100:
                    self._lease_durations = self._lease_durations[-100:]

            # Update session state
            session.state = SessionState.RETURNING
            session.lease_id = None
            session.leased_by = None
            session.leased_at = None
            session.lease_timeout = None

            # Handle CAPTCHA/block detection
            if detected_captcha:
                session.mark_failure(dirty_reason, is_captcha=True)
                if session.captcha_count >= 2:
                    # Quarantine after 2 CAPTCHAs
                    session.state = SessionState.QUARANTINED
                    self._stats.total_quarantined += 1
                    logger.warning(f"Session {session.session_id[:8]} quarantined (CAPTCHA)")
                else:
                    # Try escalation
                    self._escalate_session(session)
            elif detected_block:
                session.mark_failure(dirty_reason)
                if session.consecutive_failures >= 3:
                    session.state = SessionState.QUARANTINED
                    self._stats.total_quarantined += 1
                    logger.warning(f"Session {session.session_id[:8]} quarantined (blocks)")
            elif dirty:
                session.mark_dirty(dirty_reason)
                session.state = SessionState.CLEANING
            else:
                session.mark_success()
                session.state = SessionState.IDLE_WARM
                # Track successful operations for recovery mode
                if self._recovery_mode:
                    self.record_recovery_success()

        # Record metrics
        if hasattr(lease, '_metrics') and lease._metrics:
            metrics = get_pool_metrics()
            metrics.record_lease_released(
                metrics=lease._metrics,
                success=not (detected_captcha or detected_block or dirty),
                blocked=detected_block,
                captcha=detected_captcha,
                error=dirty_reason,
                pages_visited=session.navigation_count,
            )

        # Remove lease
        del self._leases[lease.lease_id]

        # Notify waiting threads
        with self._session_available:
            self._session_available.notify_all()

        logger.info(f"Released session {session.session_id[:8]} (state: {session.state.value})")
        return True

    def _escalate_session(self, session: BrowserSession) -> bool:
        """
        Escalate session to a more stealthy browser type.

        Args:
            session: Session to escalate

        Returns:
            True if escalation successful
        """
        next_type = get_next_escalation_type(session.browser_type)
        if next_type is None:
            logger.warning(f"Session {session.session_id[:8]} at max escalation")
            return False

        logger.info(
            f"Escalating session {session.session_id[:8]}: "
            f"{session.browser_type.value} → {next_type.value}"
        )

        # Close current driver
        if session.driver:
            self._safe_quit_driver(session.driver)

        # Create new driver with escalated type
        session.browser_type = next_type
        driver, proxy = self._create_driver_with_stealth(next_type, session.target_group)
        session.driver = driver
        session.proxy = proxy

        if session.driver is None:
            session.state = SessionState.DEAD
            return False

        # Re-warm the session
        return self._warm_session(session)

    def heartbeat(self, lease: SessionLease) -> bool:
        """
        Send heartbeat for an active lease.

        Must be called periodically during long operations.
        Session is reclaimed if heartbeats stop.

        Args:
            lease: The lease to heartbeat

        Returns:
            True if session still valid
        """
        if lease.lease_id not in self._leases:
            return False

        session = self._sessions.get(lease.session_id)
        if session is None or session.state != SessionState.LEASED:
            return False

        with self._get_session_lock(session.session_id):
            session.last_heartbeat = datetime.now()
            lease.refresh_heartbeat()

        return True

    def get_driver(self, lease: SessionLease) -> Optional[Any]:
        """
        Get the browser driver for a valid lease.

        Args:
            lease: Valid lease

        Returns:
            Driver instance or None
        """
        if lease.lease_id not in self._leases:
            return None

        session = self._sessions.get(lease.session_id)
        if session is None or session.state != SessionState.LEASED:
            return None

        # Update usage tracking
        session.mark_used()

        return session.driver

    @contextmanager
    def browser_lease(
        self,
        target_domain: str,
        requester: str,
        timeout_seconds: int = MAX_ACQUIRE_WAIT_SECONDS,
        lease_duration_seconds: int = LEASE_TIMEOUT_SECONDS,
    ) -> Generator[Tuple[Optional[SessionLease], Optional[Any]], None, None]:
        """
        Context manager for automatic lease management.

        Usage:
            pool = get_browser_pool()
            with pool.browser_lease("google.com", "serp_scraper") as (lease, driver):
                if driver:
                    driver.get("https://google.com/search?q=test")
                    # ... scrape ...
            # Lease automatically released

        Args:
            target_domain: Domain to scrape
            requester: Module name
            timeout_seconds: Acquire timeout
            lease_duration_seconds: Lease duration

        Yields:
            Tuple of (SessionLease, driver) or (None, None) if unavailable
        """
        lease = None
        driver = None
        dirty = False
        dirty_reason = None
        detected_captcha = False
        detected_block = False

        try:
            lease = self.acquire_session(
                target_domain=target_domain,
                requester=requester,
                timeout_seconds=timeout_seconds,
                lease_duration_seconds=lease_duration_seconds,
            )

            if lease:
                driver = self.get_driver(lease)

            yield lease, driver

        except Exception as e:
            error_str = str(e).lower()
            dirty = True
            dirty_reason = str(e)
            detected_captcha = "captcha" in error_str
            detected_block = "blocked" in error_str or "forbidden" in error_str
            raise

        finally:
            if lease:
                self.release_session(
                    lease,
                    dirty=dirty,
                    dirty_reason=dirty_reason,
                    detected_captcha=detected_captcha,
                    detected_block=detected_block,
                )

    def get_stats(self) -> PoolStats:
        """Get pool statistics."""
        with self._pool_lock:
            stats = PoolStats()
            stats.total_sessions = len(self._sessions)
            stats.active_leases = len(self._leases)
            stats.total_leases_issued = self._total_leases_issued
            stats.total_recycled = self._stats.total_recycled
            stats.total_quarantined = self._stats.total_quarantined

            # Calculate averages
            if self._lease_durations:
                stats.avg_lease_duration_seconds = sum(self._lease_durations) / len(self._lease_durations)

            success_rates = [s.success_rate for s in self._sessions.values() if s.success_count + s.failure_count > 0]
            if success_rates:
                stats.avg_success_rate = sum(success_rates) / len(success_rates)

            # Count by state
            for session in self._sessions.values():
                state_name = session.state.value
                stats.sessions_by_state[state_name] = stats.sessions_by_state.get(state_name, 0) + 1

            # Count by group
            for session in self._sessions.values():
                group = session.target_group
                stats.sessions_by_group[group] = stats.sessions_by_group.get(group, 0) + 1

            # Count by type
            for session in self._sessions.values():
                type_name = session.browser_type.value
                stats.sessions_by_type[type_name] = stats.sessions_by_type.get(type_name, 0) + 1

            return stats

    def get_metrics_summary(self) -> dict:
        """
        Get comprehensive metrics from the pool metrics collector.

        Returns detailed statistics including:
        - Lease duration percentiles (p50, p95, p99)
        - Success/failure rates by target group
        - Domain-level metrics (block rates, CAPTCHA rates)
        - Warmup success rates
        - Recycle breakdown by reason
        - Browser type distribution
        """
        return get_pool_metrics().get_summary()

    def log_metrics(self):
        """Log a metrics summary for observability."""
        get_pool_metrics().log_summary()

    # --- Background worker loops ---

    def _warmer_loop(self):
        """Background loop to keep sessions warm."""
        logger.info("Warmer thread started")

        # Initial pool initialization
        time.sleep(2)  # Let main thread finish
        self._initialize_pool()

        while not self._shutdown.is_set():
            try:
                # Check each idle session
                with self._pool_lock:
                    idle_sessions = [
                        s for s in self._sessions.values()
                        if s.state == SessionState.IDLE_WARM
                    ]

                for session in idle_sessions:
                    if self._shutdown.is_set():
                        break

                    # Check if re-warm needed
                    config = TARGET_GROUP_CONFIGS.get(session.target_group, TARGET_GROUP_CONFIGS["general"])
                    if session.last_warmed_at:
                        elapsed = (datetime.now() - session.last_warmed_at).total_seconds()
                        if elapsed >= config.warmup_frequency_seconds:
                            logger.debug(f"Re-warming session {session.session_id[:8]}")
                            self._warm_session(session)

                # Sleep before next check
                self._shutdown.wait(timeout=60)

            except Exception as e:
                logger.error(f"Warmer loop error: {e}")
                self._shutdown.wait(timeout=10)

    def _recycler_loop(self):
        """Background loop to recycle sessions based on TTL and caps."""
        logger.info("Recycler thread started")

        while not self._shutdown.is_set():
            try:
                sessions_to_recycle = []

                with self._pool_lock:
                    for session in self._sessions.values():
                        action = self._determine_recycle_action(session)
                        if action != RecycleAction.NONE:
                            sessions_to_recycle.append((session, action))

                # Execute recycling outside lock
                for session, action in sessions_to_recycle:
                    if self._shutdown.is_set():
                        break
                    self._execute_recycle(session, action)

                # Sleep before next check
                self._shutdown.wait(timeout=30)

            except Exception as e:
                logger.error(f"Recycler loop error: {e}")
                self._shutdown.wait(timeout=10)

    def _get_browser_memory_mb(self, session: BrowserSession) -> float:
        """
        Get approximate memory usage of browser session in MB.

        Returns:
            Memory usage in MB, or 0 if cannot determine
        """
        try:
            if not session.driver:
                return 0

            # Try to get Chrome memory via DevTools
            try:
                # Get all Chrome processes via performance logs
                memory_info = session.driver.execute_cdp_cmd(
                    "Memory.getBrowserSamplingProfile", {}
                )
                # Estimate from JS heap if available
                js_heap = session.driver.execute_script(
                    "return performance.memory ? performance.memory.usedJSHeapSize / 1048576 : 0"
                )
                return float(js_heap) if js_heap else 0
            except Exception:
                pass

            # Fallback: estimate based on page count
            # Rough heuristic: 50MB base + 20MB per navigation
            return 50 + (session.navigation_count * 20)

        except Exception:
            return 0

    def _determine_recycle_action(self, session: BrowserSession) -> RecycleAction:
        """
        Determine what recycle action is needed for a session.

        Checks in order of priority:
        1. Session TTL exceeded → HARD_RECYCLE
        2. Navigation cap exceeded → HARD_RECYCLE
        3. Memory threshold exceeded → HARD_RECYCLE
        4. CAPTCHA/failure thresholds → QUARANTINE (with escalation attempt first)
        5. Idle TTL exceeded → REWARM
        6. Dirty flag set → SOFT_RECYCLE
        7. Quarantine cooldown complete → HARD_RECYCLE
        """
        if session.state == SessionState.LEASED:
            return RecycleAction.NONE

        if session.state == SessionState.DEAD:
            return RecycleAction.HARD_RECYCLE

        config = TARGET_GROUP_CONFIGS.get(session.target_group, TARGET_GROUP_CONFIGS["general"])

        # Check session TTL
        session_age_minutes = (datetime.now() - session.created_at).total_seconds() / 60
        if session_age_minutes >= config.session_ttl_minutes:
            logger.debug(f"Session {session.session_id[:8]} exceeded TTL ({session_age_minutes:.0f}m >= {config.session_ttl_minutes}m)")
            return RecycleAction.HARD_RECYCLE

        # Check navigation cap
        if session.navigation_count >= config.navigation_cap:
            logger.debug(f"Session {session.session_id[:8]} exceeded nav cap ({session.navigation_count} >= {config.navigation_cap})")
            return RecycleAction.HARD_RECYCLE

        # Check memory (if browser is bloated > 500MB estimated, recycle)
        memory_mb = self._get_browser_memory_mb(session)
        if memory_mb > 500:
            logger.warning(f"Session {session.session_id[:8]} memory high ({memory_mb:.0f}MB), recycling")
            return RecycleAction.HARD_RECYCLE

        # Check health - but first try escalation
        if session.captcha_count >= 2 or session.consecutive_failures >= 3:
            # Try browser escalation before quarantine
            if self._can_escalate_browser(session):
                logger.info(f"Session {session.session_id[:8]} unhealthy, attempting escalation")
                return RecycleAction.HARD_RECYCLE  # Will escalate in execute
            else:
                return RecycleAction.QUARANTINE

        # Check idle TTL (only for warm sessions)
        if session.state == SessionState.IDLE_WARM:
            last_activity = session.last_used_at or session.last_warmed_at or session.created_at
            idle_minutes = (datetime.now() - last_activity).total_seconds() / 60
            if idle_minutes >= config.idle_ttl_minutes:
                logger.debug(f"Session {session.session_id[:8]} idle ({idle_minutes:.0f}m >= {config.idle_ttl_minutes}m), re-warming")
                return RecycleAction.REWARM

        # Check cleaning needed
        if session.state == SessionState.CLEANING or session.dirty:
            return RecycleAction.SOFT_RECYCLE

        # Check quarantine cooldown (1 hour)
        if session.state == SessionState.QUARANTINED:
            last_activity = session.last_used_at or session.created_at
            quarantine_elapsed = (datetime.now() - last_activity).total_seconds()
            if quarantine_elapsed >= 3600:  # 1 hour
                logger.info(f"Session {session.session_id[:8]} quarantine expired, recycling")
                return RecycleAction.HARD_RECYCLE

        return RecycleAction.NONE

    def _can_escalate_browser(self, session: BrowserSession) -> bool:
        """Check if session can be escalated to a more stealthy browser type."""
        from .pool_models import get_next_escalation_type
        next_type = get_next_escalation_type(session.browser_type)
        return next_type is not None

    def _escalate_browser_type(self, session: BrowserSession) -> bool:
        """
        Escalate session to next browser type in stealth hierarchy.

        Escalation order: SELENIUM_UC → SELENIUM_UC_FRESH → CAMOUFOX → CAMOUFOX_NEW_FP

        Returns:
            True if escalation succeeded
        """
        from .pool_models import get_next_escalation_type

        next_type = get_next_escalation_type(session.browser_type)
        if next_type is None:
            logger.warning(f"Session {session.session_id[:8]} at max escalation ({session.browser_type.value})")
            return False

        old_type = session.browser_type.value
        logger.info(f"Escalating session {session.session_id[:8]} from {old_type} to {next_type.value}")
        session.browser_type = next_type

        # Record escalation in metrics
        get_pool_metrics().record_escalation(old_type, next_type.value)
        return True

    def _execute_recycle(self, session: BrowserSession, action: RecycleAction):
        """
        Execute a recycling action on a session.

        Actions:
        - REWARM: Re-execute warmup plan (keep browser, refresh cookies)
        - SOFT_RECYCLE: Clear cookies/cache but keep browser instance
        - HARD_RECYCLE: Close browser, create new one with stealth, warm it
        - QUARANTINE: Mark session as quarantined for cooldown
        """
        with self._get_session_lock(session.session_id):
            if action == RecycleAction.REWARM:
                logger.debug(f"Re-warming session {session.session_id[:8]}")
                self._warm_session(session)
                get_pool_metrics().record_recycle("rewarm")

            elif action == RecycleAction.SOFT_RECYCLE:
                logger.info(f"Soft recycling session {session.session_id[:8]}")
                # Clear cookies/cache but keep browser
                try:
                    if hasattr(session.driver, 'delete_all_cookies'):
                        session.driver.delete_all_cookies()
                    # Also clear local/session storage
                    session.driver.execute_script("window.localStorage.clear();")
                    session.driver.execute_script("window.sessionStorage.clear();")
                except Exception as e:
                    logger.debug(f"Soft recycle cleanup error: {e}")
                session.clear_dirty()
                session.state = SessionState.IDLE_WARM
                get_pool_metrics().record_recycle("soft_recycle")

            elif action == RecycleAction.HARD_RECYCLE:
                # Check if this is due to health issues - try escalation
                needs_escalation = (
                    session.captcha_count >= 2 or
                    session.consecutive_failures >= 3
                )
                if needs_escalation and self._can_escalate_browser(session):
                    self._escalate_browser_type(session)

                logger.info(
                    f"Hard recycling session {session.session_id[:8]} "
                    f"(type={session.browser_type.value}, "
                    f"navs={session.navigation_count}, "
                    f"captchas={session.captcha_count})"
                )
                self._stats.total_recycled += 1

                # Close existing driver
                if session.driver:
                    self._safe_quit_driver(session.driver)
                    session.driver = None

                # Reset session stats
                session.state = SessionState.COLD
                session.navigation_count = 0
                session.success_count = 0
                session.failure_count = 0
                session.captcha_count = 0
                session.consecutive_failures = 0
                session.created_at = datetime.now()
                session.last_error = None

                # Create new driver WITH STEALTH configuration
                # Preserve proxy if available, otherwise get new one
                driver, proxy = self._create_driver_with_stealth(
                    session.browser_type,
                    session.target_group
                )

                if driver:
                    session.driver = driver
                    if proxy:
                        session.proxy = proxy
                        session.proxy_assigned_at = datetime.now()

                    # Re-apply extra stealth measures
                    if proxy:
                        self._apply_extra_stealth(driver, proxy)

                    # Warm the new session
                    self._warm_session(session)
                else:
                    logger.error(f"Failed to create new driver for session {session.session_id[:8]}")
                    session.state = SessionState.DEAD

                get_pool_metrics().record_recycle("hard_recycle")

            elif action == RecycleAction.QUARANTINE:
                logger.warning(
                    f"Quarantining session {session.session_id[:8]} "
                    f"(captchas={session.captcha_count}, failures={session.consecutive_failures})"
                )
                session.state = SessionState.QUARANTINED
                session.last_used_at = datetime.now()  # Track quarantine start
                self._stats.total_quarantined += 1
                get_pool_metrics().record_recycle("quarantine")

    def _heartbeat_monitor_loop(self):
        """Background loop to monitor lease heartbeats and reclaim stale sessions."""
        logger.info("Heartbeat monitor thread started")

        while not self._shutdown.is_set():
            try:
                stale_leases = []

                with self._pool_lock:
                    for lease in self._leases.values():
                        # Check for expired lease
                        if lease.is_expired:
                            stale_leases.append(lease)
                            continue

                        # Check for stale heartbeat
                        if lease.heartbeat_stale:
                            stale_leases.append(lease)

                # Reclaim stale leases
                for lease in stale_leases:
                    logger.warning(f"Reclaiming stale lease {lease.lease_id} from {lease.leased_by}")
                    self.release_session(lease, dirty=True, dirty_reason="Stale heartbeat")

                # Periodic Chrome process cleanup
                if (datetime.now() - self._last_chrome_cleanup).total_seconds() >= CHROME_CLEANUP_INTERVAL:
                    self.check_and_cleanup_chrome()

                # Sleep before next check
                self._shutdown.wait(timeout=HEARTBEAT_INTERVAL_SECONDS)

            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}")
                self._shutdown.wait(timeout=10)

    def _get_chrome_process_count(self) -> int:
        """Count Chrome-related processes on the system."""
        try:
            result = subprocess.run(
                ['pgrep', '-c', '-f', 'chrom'],
                capture_output=True,
                text=True
            )
            return int(result.stdout.strip()) if result.returncode == 0 else 0
        except Exception:
            return 0

    def _cleanup_orphan_chrome_processes(self) -> int:
        """Kill orphaned Chrome processes (parent PID = 1)."""
        killed = 0
        try:
            # Get Chrome PIDs
            result = subprocess.run(
                ['pgrep', '-f', 'chrom'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return 0

            for pid_str in result.stdout.strip().split('\n'):
                if not pid_str:
                    continue
                try:
                    pid = int(pid_str)
                    # Check if orphaned (parent = 1)
                    with open(f'/proc/{pid}/stat', 'r') as f:
                        stat = f.read().split()
                        ppid = int(stat[3]) if len(stat) > 3 else 0
                        if ppid == 1:  # Orphaned process
                            os.kill(pid, signal.SIGKILL)
                            killed += 1
                except (FileNotFoundError, PermissionError, ValueError, ProcessLookupError):
                    pass
        except Exception as e:
            logger.debug(f"Chrome cleanup error: {e}")
        return killed

    def _aggressive_chrome_cleanup(self) -> int:
        """
        Aggressively kill Chrome processes not belonging to active sessions.

        This is more aggressive than _cleanup_orphan_chrome_processes - it kills
        ALL Chrome processes older than 5 minutes that aren't tracked by sessions.
        """
        killed = 0
        try:
            # Get PIDs of Chrome processes owned by current user
            result = subprocess.run(
                ['pgrep', '-u', str(os.getuid()), '-f', 'chrom'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return 0

            chrome_pids = set()
            for pid_str in result.stdout.strip().split('\n'):
                if pid_str:
                    try:
                        chrome_pids.add(int(pid_str))
                    except ValueError:
                        pass

            if not chrome_pids:
                return 0

            # Get PIDs that belong to active sessions (check service_url ports)
            active_pids = set()
            with self._pool_lock:
                for session in self._sessions.values():
                    if session.driver:
                        try:
                            # Try to get the browser PID from driver
                            service_url = getattr(session.driver, 'service', None)
                            if service_url and hasattr(service_url, 'process'):
                                proc = service_url.process
                                if proc and proc.pid:
                                    active_pids.add(proc.pid)
                                    # Also protect children
                                    try:
                                        children = subprocess.run(
                                            ['pgrep', '-P', str(proc.pid)],
                                            capture_output=True,
                                            text=True
                                        )
                                        for child_pid in children.stdout.strip().split('\n'):
                                            if child_pid:
                                                active_pids.add(int(child_pid))
                                    except Exception:
                                        pass
                        except Exception:
                            pass

            # Kill Chrome processes that are stale (not active, older than 5 min)
            stale_threshold = time.time() - 300  # 5 minutes

            for pid in chrome_pids:
                if pid in active_pids:
                    continue  # Skip active session PIDs

                try:
                    # Check process age
                    stat_file = f'/proc/{pid}/stat'
                    if os.path.exists(stat_file):
                        # Get process start time
                        with open(stat_file, 'r') as f:
                            stat = f.read().split()
                            # starttime is field 22 (0-indexed: 21)
                            if len(stat) > 21:
                                starttime = int(stat[21])
                                # Convert to seconds since boot
                                with open('/proc/uptime', 'r') as u:
                                    uptime = float(u.read().split()[0])
                                clk_tck = os.sysconf('SC_CLK_TCK')
                                process_age = uptime - (starttime / clk_tck)

                                # Kill if older than threshold
                                if process_age > 300:  # 5 minutes old
                                    os.kill(pid, signal.SIGKILL)
                                    killed += 1
                                    continue

                        # Also kill if zombie or stopped
                        with open(f'/proc/{pid}/status', 'r') as f:
                            status = f.read()
                            if 'State:\tZ' in status or 'State:\tT' in status:
                                os.kill(pid, signal.SIGKILL)
                                killed += 1

                except (FileNotFoundError, PermissionError, ValueError, ProcessLookupError, OSError):
                    pass

            logger.info(f"Aggressive cleanup: killed {killed} stale Chrome processes")

        except Exception as e:
            logger.error(f"Error in aggressive Chrome cleanup: {e}")

        return killed

    def _targeted_chrome_cleanup(self) -> int:
        """
        Targeted cleanup: Use ChromeProcessManager to clean orphaned processes.

        Does NOT kill all Chrome - only orphans and stale processes.
        This replaces the old nuclear option which killed everything.
        """
        try:
            from .chrome_process_manager import get_chrome_process_manager

            logger.info("Executing targeted Chrome cleanup via ChromeProcessManager")

            pm = get_chrome_process_manager()

            # Refresh tracking to remove dead processes
            pm.refresh_tracked_processes()

            # Clean up orphaned processes (not belonging to active sessions)
            killed = pm.cleanup_orphaned_processes()

            remaining = self._get_chrome_process_count()
            logger.info(f"Targeted cleanup complete: killed {killed}, {remaining} remaining")

            return killed

        except Exception as e:
            logger.error(f"Error in targeted Chrome cleanup: {e}")
            return 0

    def check_and_cleanup_chrome(self) -> Tuple[int, int]:
        """
        Check Chrome process count and clean up if needed.

        Escalation levels:
        1. MAX_CHROME_PROCESSES (40): Kill orphans only
        2. CRITICAL_CHROME_PROCESSES (60): Aggressive + targeted cleanup
        3. EMERGENCY_CHROME_PROCESSES (80): Hard cap - kill ALL orphans aggressively

        Returns:
            Tuple of (process_count, killed_count)
        """
        chrome_count = self._get_chrome_process_count()
        killed = 0

        if chrome_count >= EMERGENCY_CHROME_PROCESSES:
            # EMERGENCY: Hard cap exceeded - aggressive measures
            logger.error(f"EMERGENCY: {chrome_count} Chrome processes - forcing hard cleanup!")

            # Kill ALL orphan processes immediately
            killed = self._cleanup_orphan_chrome_processes()
            killed += self._aggressive_chrome_cleanup()
            killed += self._targeted_chrome_cleanup()

            remaining = self._get_chrome_process_count()
            if remaining >= EMERGENCY_CHROME_PROCESSES:
                # Last resort: kill oldest Chrome processes
                logger.error(f"Still {remaining} - killing oldest Chrome processes")
                killed += self._emergency_chrome_cleanup()

            remaining = self._get_chrome_process_count()
            logger.warning(f"Emergency cleanup complete: {remaining} processes remain (killed {killed})")

        elif chrome_count >= CRITICAL_CHROME_PROCESSES:
            logger.warning(f"CRITICAL: {chrome_count} Chrome processes - starting cleanup")

            # Level 1: Try orphan cleanup first
            killed = self._cleanup_orphan_chrome_processes()
            remaining = self._get_chrome_process_count()

            if remaining >= CRITICAL_CHROME_PROCESSES:
                # Level 2: Aggressive cleanup - kill stale processes
                logger.warning(f"Still {remaining} after orphan cleanup - escalating to aggressive")
                killed += self._aggressive_chrome_cleanup()
                remaining = self._get_chrome_process_count()

                if remaining >= CRITICAL_CHROME_PROCESSES:
                    # Level 3: Targeted cleanup via ChromeProcessManager
                    logger.warning(f"Still {remaining} after aggressive - using targeted cleanup")
                    killed += self._targeted_chrome_cleanup()

            remaining = self._get_chrome_process_count()
            if remaining >= MAX_CHROME_PROCESSES:
                logger.warning(f"Chrome count still elevated: {remaining} processes remain")
            else:
                logger.info(f"Chrome cleanup successful: {remaining} processes remain")

        elif chrome_count >= MAX_CHROME_PROCESSES:
            logger.info(f"Elevated Chrome count: {chrome_count} - cleaning orphans")
            killed = self._cleanup_orphan_chrome_processes()

            # If orphan cleanup wasn't enough, try targeted
            remaining = self._get_chrome_process_count()
            if remaining >= MAX_CHROME_PROCESSES:
                logger.info(f"Still {remaining} after orphan cleanup - using targeted cleanup")
                killed += self._targeted_chrome_cleanup()

        if killed > 0:
            logger.info(f"Chrome cleanup: killed {killed} processes total")

        self._last_chrome_cleanup = datetime.now()
        return chrome_count, killed

    def _emergency_chrome_cleanup(self) -> int:
        """
        Emergency cleanup: Kill oldest Chrome processes to get under limit.

        This is the last resort when other cleanup methods fail.
        """
        try:
            import subprocess

            # Get Chrome processes sorted by start time (oldest first)
            result = subprocess.run(
                ["ps", "-eo", "pid,etimes,comm", "--sort=-etimes"],
                capture_output=True,
                text=True,
                timeout=10
            )

            killed = 0
            target_count = EMERGENCY_CHROME_PROCESSES - 20  # Kill down to 60
            current_count = self._get_chrome_process_count()

            for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                if current_count <= target_count:
                    break

                parts = line.split()
                if len(parts) >= 3:
                    pid = parts[0]
                    comm = parts[2]

                    if 'chrome' in comm.lower() or 'chromium' in comm.lower():
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                            killed += 1
                            current_count -= 1
                            logger.debug(f"Emergency killed Chrome PID {pid}")
                        except (ProcessLookupError, PermissionError):
                            pass

            logger.warning(f"Emergency cleanup: killed {killed} oldest Chrome processes")
            return killed

        except Exception as e:
            logger.error(f"Emergency Chrome cleanup error: {e}")
            return 0

    # ========== Drain Mode Methods ==========

    def enter_drain_mode(self, timeout: int = 60) -> bool:
        """
        Enter drain mode - stop accepting new leases and wait for existing to complete.

        Args:
            timeout: Max seconds to wait for active leases to complete

        Returns:
            True if drain completed successfully, False if timed out
        """
        with self._pool_lock:
            if self._drain_mode:
                logger.warning("Already in drain mode")
                return True

            self._drain_mode = True
            self._drain_started = datetime.now()
            self._drain_timeout = timeout
            active_leases = len(self._leases)
            logger.info(f"Entering drain mode - {active_leases} active leases")

        # Wait for active leases to complete
        start = time.time()
        while time.time() - start < timeout:
            with self._pool_lock:
                if len(self._leases) == 0:
                    logger.info("Drain complete - all leases released")
                    return True
                remaining = len(self._leases)

            logger.debug(f"Drain waiting - {remaining} leases remaining")
            time.sleep(2)

        # Timed out
        with self._pool_lock:
            remaining = len(self._leases)
        logger.warning(f"Drain timed out with {remaining} leases still active")
        return False

    def exit_drain_mode(self):
        """Exit drain mode and resume accepting leases."""
        with self._pool_lock:
            self._drain_mode = False
            self._drain_started = None
            logger.info("Exited drain mode - accepting new leases")

    def is_draining(self) -> bool:
        """Check if pool is in drain mode."""
        return self._drain_mode

    # ========== Recovery Mode Methods ==========

    def _check_and_trigger_self_healing(self):
        """
        Check pool health and trigger self-healing if needed.

        Called after acquisition timeouts to automatically recover from:
        - High timeout rates (>10%)
        - Too many quarantined sessions (>30%)
        - Too few healthy sessions (<3)
        - Consecutive timeouts (>3 in a row)
        """
        try:
            # Check if enough time has passed since last health check
            now = datetime.now()
            if (now - self._last_health_check).total_seconds() < self._health_check_interval:
                # But still act on consecutive timeouts
                if self._consecutive_timeouts >= 3:
                    logger.warning(f"3+ consecutive timeouts - triggering immediate recovery")
                    self._trigger_recovery_action("consecutive_timeouts")
                return

            self._last_health_check = now

            with self._pool_lock:
                total_sessions = len(self._sessions)
                if total_sessions == 0:
                    logger.warning("No sessions in pool - reinitializing")
                    self._trigger_recovery_action("empty_pool")
                    return

                # Count session states
                healthy_count = sum(1 for s in self._sessions.values()
                                   if s.state == SessionState.IDLE_WARM)
                quarantined_count = sum(1 for s in self._sessions.values()
                                       if s.state == SessionState.QUARANTINED)
                dead_count = sum(1 for s in self._sessions.values()
                                if s.state == SessionState.DEAD)

                # Check quarantine rate
                quarantine_rate = quarantined_count / total_sessions
                if quarantine_rate >= QUARANTINE_RECOVERY_THRESHOLD:
                    logger.warning(
                        f"High quarantine rate: {quarantine_rate:.1%} ({quarantined_count}/{total_sessions}) "
                        f"- triggering recovery"
                    )
                    self._trigger_recovery_action("high_quarantine_rate")
                    return

                # Check minimum healthy sessions
                if healthy_count < MIN_HEALTHY_SESSIONS:
                    logger.warning(
                        f"Too few healthy sessions: {healthy_count} (min: {MIN_HEALTHY_SESSIONS}) "
                        f"- triggering recovery"
                    )
                    self._trigger_recovery_action("low_healthy_count")
                    return

                # Check timeout rate
                if self._acquisition_attempts >= 10:
                    timeout_rate = self._acquisition_timeouts / self._acquisition_attempts
                    if timeout_rate >= ACQUISITION_TIMEOUT_RATE_THRESHOLD:
                        logger.warning(
                            f"High timeout rate: {timeout_rate:.1%} "
                            f"({self._acquisition_timeouts}/{self._acquisition_attempts}) "
                            f"- triggering recovery"
                        )
                        self._trigger_recovery_action("high_timeout_rate")

                        # Reset counters after triggering
                        self._acquisition_attempts = 0
                        self._acquisition_timeouts = 0
                        return

                # Clean up dead sessions proactively
                if dead_count > 0:
                    logger.info(f"Found {dead_count} dead sessions - cleaning up")
                    for session in list(self._sessions.values()):
                        if session.state == SessionState.DEAD:
                            self.invalidate_session(session.session_id, reason="dead_session_cleanup")

        except Exception as e:
            logger.error(f"Error in self-healing check: {e}")

    def _trigger_recovery_action(self, reason: str):
        """
        Execute recovery actions based on the trigger reason.

        Args:
            reason: What triggered the recovery
        """
        logger.info(f"Triggering recovery action: {reason}")

        try:
            # Enter recovery mode if not already
            if not self._recovery_mode:
                self.enter_recovery_mode()

            # Perform coordinated cleanup for serious issues
            if reason in ("consecutive_timeouts", "high_quarantine_rate", "empty_pool"):
                # Run cleanup in background thread to avoid blocking
                cleanup_thread = threading.Thread(
                    target=self._background_recovery_cleanup,
                    args=(reason,),
                    name="BrowserPool-RecoveryCleanup",
                    daemon=True,
                )
                cleanup_thread.start()

            # For less serious issues, just ensure warmup is prioritized
            elif reason in ("low_healthy_count", "high_timeout_rate"):
                # Wake up warmer thread
                with self._session_available:
                    self._session_available.notify_all()

        except Exception as e:
            logger.error(f"Error in recovery action: {e}")

    def _background_recovery_cleanup(self, reason: str):
        """
        Background thread for recovery cleanup operations.

        Args:
            reason: What triggered the recovery
        """
        try:
            logger.info(f"Starting background recovery cleanup for: {reason}")

            # Cleanup orphan Chrome processes
            self.check_and_cleanup_chrome()

            # If pool is empty or very depleted, reinitialize
            with self._pool_lock:
                healthy_count = sum(1 for s in self._sessions.values()
                                   if s.state == SessionState.IDLE_WARM)

            if healthy_count < 2:
                logger.info("Very few healthy sessions - attempting to create new sessions")
                # Create a few new sessions
                target_groups = ["search_engines", "directories", "general"]
                for i in range(min(3, POOL_MAX_SESSIONS - len(self._sessions))):
                    try:
                        target_group = target_groups[i % 3]
                        session = self._create_session(target_group)
                        if session:
                            self._warm_session(session)
                            logger.info(f"Created recovery session {session.session_id[:8]} for {target_group}")
                    except Exception as e:
                        logger.warning(f"Failed to create recovery session: {e}")

            logger.info(f"Background recovery cleanup completed for: {reason}")

        except Exception as e:
            logger.error(f"Error in background recovery cleanup: {e}")

    def enter_recovery_mode(self):
        """
        Enter recovery mode - use extended warmup for new sessions.
        Sessions will visit more sites and wait longer between navigations.
        """
        with self._pool_lock:
            self._recovery_mode = True
            self._recovery_started = datetime.now()
            self._recovery_success_count = 0
            logger.info("Entering recovery mode - extended warmup enabled")

    def exit_recovery_mode(self):
        """Exit recovery mode and return to normal warmup."""
        with self._pool_lock:
            self._recovery_mode = False
            self._recovery_started = None
            self._recovery_success_count = 0
            logger.info("Exited recovery mode - normal warmup resumed")

    def record_recovery_success(self):
        """Record a successful session operation during recovery."""
        with self._pool_lock:
            if not self._recovery_mode:
                return

            self._recovery_success_count += 1
            if self._recovery_success_count >= self._recovery_success_threshold:
                logger.info(f"Recovery threshold reached ({self._recovery_success_count} successes) - exiting recovery mode")
                self._recovery_mode = False
                self._recovery_started = None
                self._recovery_success_count = 0

    def is_recovering(self) -> bool:
        """Check if pool is in recovery mode."""
        return self._recovery_mode

    def get_warmup_site_count(self) -> int:
        """Get number of sites to visit during warmup (more in recovery mode)."""
        if self._recovery_mode:
            return 10  # Extended warmup
        return 5  # Normal warmup

    # ========== Session Health Check Methods ==========

    def is_session_alive(self, session: 'BrowserSession', timeout_seconds: float = 5.0) -> bool:
        """
        Check if a session's Chrome process is still running and responsive.

        Args:
            session: The browser session to check
            timeout_seconds: Maximum time to wait for response (default: 5s)

        Returns:
            True if Chrome process is alive and responsive, False otherwise
        """
        if not session or not session.driver:
            return False

        try:
            # First, quick PID check (doesn't guarantee responsiveness)
            pid = None
            if hasattr(session.driver, 'service') and hasattr(session.driver.service, 'process'):
                pid = session.driver.service.process.pid
            elif hasattr(session.driver, 'browser_pid'):
                pid = session.driver.browser_pid

            if pid:
                try:
                    os.kill(pid, 0)  # Signal 0 just checks existence
                except (ProcessLookupError, OSError):
                    return False

            # Now check actual responsiveness with timeout
            # Use a thread to avoid hanging indefinitely
            result = [False]
            exception = [None]

            def check_driver():
                try:
                    # Try to get current_url - this verifies WebDriver connection
                    _ = session.driver.current_url
                    result[0] = True
                except Exception as e:
                    exception[0] = e

            check_thread = threading.Thread(target=check_driver, daemon=True)
            check_thread.start()
            check_thread.join(timeout=timeout_seconds)

            if check_thread.is_alive():
                # Thread is still running - driver is unresponsive
                logger.warning(f"Session {session.session_id[:8]} health check timed out after {timeout_seconds}s")
                return False

            if exception[0]:
                logger.debug(f"Session {session.session_id[:8]} health check failed: {exception[0]}")
                return False

            return result[0]

        except Exception as e:
            logger.debug(f"Session health check error: {e}")
            return False

    def invalidate_session(self, session_id: str, reason: str = "manual"):
        """
        Invalidate a specific session - mark as dead and remove from pool.

        Args:
            session_id: The session ID to invalidate
            reason: Reason for invalidation (for logging)
        """
        with self._pool_lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                logger.info(f"Invalidating session {session_id[:8]}: {reason}")

                # Try to close the driver
                if session.driver:
                    self._safe_quit_driver(session.driver)

                # Remove from pool
                del self._sessions[session_id]

                # Clean up any lease
                lease_to_remove = None
                for lease_id, lease in self._leases.items():
                    if lease.session_id == session_id:
                        lease_to_remove = lease_id
                        break
                if lease_to_remove:
                    del self._leases[lease_to_remove]

    def invalidate_all_sessions(self, reason: str = "cleanup"):
        """
        Invalidate all sessions - used during cleanup to start fresh.

        Args:
            reason: Reason for invalidation (for logging)
        """
        with self._pool_lock:
            session_count = len(self._sessions)
            logger.warning(f"Invalidating all {session_count} sessions: {reason}")

            for session in list(self._sessions.values()):
                if session.driver:
                    self._safe_quit_driver(session.driver)

            self._sessions.clear()
            self._leases.clear()
            self._session_locks.clear()

            logger.info(f"Invalidated {session_count} sessions")

    def validate_and_clean_dead_sessions(self) -> int:
        """
        Check all sessions and remove dead ones.

        Returns:
            Number of dead sessions removed
        """
        dead_sessions = []

        with self._pool_lock:
            for session_id, session in self._sessions.items():
                if not self.is_session_alive(session):
                    dead_sessions.append(session_id)

        # Remove dead sessions outside the lock
        for session_id in dead_sessions:
            self.invalidate_session(session_id, reason="chrome_process_dead")

        if dead_sessions:
            logger.info(f"Cleaned {len(dead_sessions)} dead sessions")

        return len(dead_sessions)

    # ========== Pool Health Status ==========

    def get_pool_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive pool health status for external monitoring.

        Returns:
            Dict with health metrics and status flags
        """
        with self._pool_lock:
            active_sessions = len([s for s in self._sessions.values()
                                   if s.state in [SessionState.IDLE_WARM, SessionState.LEASED]])
            total_sessions = len(self._sessions)
            active_leases = len(self._leases)

        chrome_count = self._get_chrome_process_count()

        return {
            "healthy": not self._drain_mode and not self._recovery_mode and chrome_count < MAX_CHROME_PROCESSES,
            "drain_mode": self._drain_mode,
            "recovery_mode": self._recovery_mode,
            "recovery_progress": f"{self._recovery_success_count}/{self._recovery_success_threshold}" if self._recovery_mode else None,
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "active_leases": active_leases,
            "chrome_processes": chrome_count,
            "chrome_limit": MAX_CHROME_PROCESSES,
            "chrome_critical": CRITICAL_CHROME_PROCESSES,
        }

    # ========== Coordinated Cleanup ==========

    def coordinated_cleanup(self, batch_size: int = 15, batch_delay: float = 5.0) -> Dict[str, Any]:
        """
        Perform a coordinated cleanup with drain, invalidation, and recovery.

        This is the main entry point for external cleanup triggers.

        Args:
            batch_size: Number of Chrome processes to kill per batch
            batch_delay: Seconds to wait between batches

        Returns:
            Dict with cleanup results
        """
        results = {
            "started": datetime.now().isoformat(),
            "drain_success": False,
            "sessions_invalidated": 0,
            "chrome_killed": 0,
            "recovery_entered": False,
        }

        logger.info("Starting coordinated cleanup")

        # Step 1: Enter drain mode
        drain_success = self.enter_drain_mode(timeout=60)
        results["drain_success"] = drain_success

        # Step 2: Invalidate all sessions
        with self._pool_lock:
            results["sessions_invalidated"] = len(self._sessions)
        self.invalidate_all_sessions(reason="coordinated_cleanup")

        # Step 3: Staggered Chrome kill
        total_killed = 0
        while True:
            orphans = self._get_orphan_pids()
            if not orphans:
                break

            batch = orphans[:batch_size]
            for pid in batch:
                try:
                    os.kill(pid, signal.SIGKILL)
                    total_killed += 1
                except (ProcessLookupError, PermissionError):
                    pass

            if len(orphans) > batch_size:
                logger.info(f"Killed {len(batch)} orphans, {len(orphans) - batch_size} remaining, waiting {batch_delay}s")
                time.sleep(batch_delay)
            else:
                break

        results["chrome_killed"] = total_killed

        # Step 4: Exit drain mode and enter recovery mode
        self.exit_drain_mode()
        self.enter_recovery_mode()
        results["recovery_entered"] = True

        results["completed"] = datetime.now().isoformat()
        logger.info(f"Coordinated cleanup complete: {results}")

        return results

    def _get_orphan_pids(self) -> List[int]:
        """Get list of orphaned Chrome PIDs (parent = 1)."""
        orphans = []
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'chrom'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return []

            for pid_str in result.stdout.strip().split('\n'):
                if not pid_str:
                    continue
                try:
                    pid = int(pid_str)
                    with open(f'/proc/{pid}/stat', 'r') as f:
                        stat = f.read().split()
                        ppid = int(stat[3]) if len(stat) > 3 else 0
                        if ppid == 1:
                            orphans.append(pid)
                except (FileNotFoundError, PermissionError, ValueError):
                    pass
        except Exception:
            pass
        return orphans

    def shutdown(self):
        """Shutdown the pool and clean up resources."""
        logger.info("Shutting down browser pool...")
        self._shutdown.set()

        # Wait for background threads
        for thread in [self._warmer_thread, self._recycler_thread, self._heartbeat_monitor_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=5)

        # Close all browser drivers
        with self._pool_lock:
            for session in self._sessions.values():
                if session.driver:
                    self._safe_quit_driver(session.driver)

            self._sessions.clear()
            self._leases.clear()

        logger.info("Browser pool shutdown complete")


# Module-level singleton accessor
_pool_instance: Optional[EnterpriseBrowserPool] = None
_pool_lock = threading.Lock()


def get_browser_pool() -> EnterpriseBrowserPool:
    """
    Get the singleton browser pool instance.

    Returns:
        EnterpriseBrowserPool instance
    """
    global _pool_instance
    if _pool_instance is None:
        with _pool_lock:
            if _pool_instance is None:
                _pool_instance = EnterpriseBrowserPool()
    return _pool_instance
