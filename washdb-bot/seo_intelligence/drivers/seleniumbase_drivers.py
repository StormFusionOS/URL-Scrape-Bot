"""
SeleniumBase Undetected Chrome Drivers for SEO Intelligence.

This module provides domain-specific UC drivers with:
- Proxy integration via existing ProxyManager
- CAPTCHA/block detection with retry logic
- Human-like interactions (scrolling, clicking)
- Page validation before returning driver
- Virtual display (Xvfb) support for headed mode without visible windows

Based on working reference implementation (Scrape-Bot-main).
"""

import os
import time
import random
import subprocess
import tempfile
import zipfile
import shutil
import socket
import threading
from typing import Optional, Tuple
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from seo_intelligence.services.proxy_manager import get_proxy_manager
from runner.logging_setup import get_logger

logger = get_logger("seleniumbase_drivers")


# Directory to store generated proxy auth extensions
PROXY_EXTENSION_DIR = "/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/proxy_extensions"

# Port allocation for Chrome debugging - thread-safe singleton class


class PortAllocator:
    """
    Thread-safe port allocation with guaranteed cleanup.

    Tracks port allocations by driver ID to ensure ports are released
    even if driver creation fails or crashes.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._port_lock = threading.RLock()
        self._allocated_ports: set = set()
        self._port_to_driver: dict = {}
        self._PORT_RANGE_START = 9300
        self._PORT_RANGE_END = 9999
        logger.info("PortAllocator initialized")

    def allocate(self, driver_id: str = None) -> int:
        """
        Allocate a free port for Chrome debugging.

        Args:
            driver_id: Optional driver ID for tracking

        Returns:
            Available port number
        """
        with self._port_lock:
            for port in range(self._PORT_RANGE_START, self._PORT_RANGE_END):
                if port in self._allocated_ports:
                    continue
                if self._is_port_free(port):
                    self._allocated_ports.add(port)
                    if driver_id:
                        self._port_to_driver[port] = driver_id
                    logger.debug(f"Allocated debugging port {port}")
                    return port

            # Fallback: find any free port using OS
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', 0))
                    port = s.getsockname()[1]
                self._allocated_ports.add(port)
                if driver_id:
                    self._port_to_driver[port] = driver_id
                logger.warning(f"Port range exhausted, using OS-assigned port {port}")
                return port
            except Exception:
                fallback_port = random.randint(10000, 19999)
                logger.warning(f"Fallback to random port {fallback_port}")
                return fallback_port

    def release(self, port: int) -> None:
        """Release an allocated port."""
        with self._port_lock:
            self._allocated_ports.discard(port)
            self._port_to_driver.pop(port, None)
            logger.debug(f"Released debugging port {port}")

    def release_for_driver(self, driver_id: str) -> int:
        """
        Release all ports allocated to a driver.

        Args:
            driver_id: Driver ID to release ports for

        Returns:
            Number of ports released
        """
        released = 0
        with self._port_lock:
            ports_to_release = [
                p for p, d in self._port_to_driver.items()
                if d == driver_id
            ]
            for port in ports_to_release:
                self._allocated_ports.discard(port)
                self._port_to_driver.pop(port, None)
                released += 1
        if released:
            logger.debug(f"Released {released} ports for driver {driver_id}")
        return released

    def _is_port_free(self, port: int) -> bool:
        """Check if port is actually free."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                return s.connect_ex(('127.0.0.1', port)) != 0
        except Exception:
            return False

    def get_stats(self) -> dict:
        """Get allocation statistics."""
        with self._port_lock:
            return {
                "allocated_count": len(self._allocated_ports),
                "tracked_drivers": len(set(self._port_to_driver.values())),
            }


# Singleton instance
_port_allocator = None


def get_port_allocator() -> PortAllocator:
    """Get the singleton PortAllocator instance."""
    global _port_allocator
    if _port_allocator is None:
        _port_allocator = PortAllocator()
    return _port_allocator


def _get_free_debugging_port() -> int:
    """
    Get a free port for Chrome remote debugging.

    Allocates unique ports to avoid "cannot connect to chrome at 127.0.0.1:9222" errors
    when multiple UC drivers are created concurrently.

    Returns:
        Available port number
    """
    return get_port_allocator().allocate()


def _release_debugging_port(port: int) -> None:
    """Release a previously allocated debugging port."""
    get_port_allocator().release(port)


def safe_quit_driver(driver) -> None:
    """
    Safely quit a driver and release its debugging port.

    Call this instead of driver.quit() to ensure port cleanup.

    Args:
        driver: SeleniumBase driver to quit
    """
    if driver is None:
        return

    # Release the debugging port if allocated
    debug_port = getattr(driver, '_debug_port', None)
    if debug_port:
        _release_debugging_port(debug_port)

    # Quit the driver
    try:
        driver.quit()
    except Exception as e:
        logger.warning(f"Error quitting driver: {e}")


def create_proxy_auth_extension(host: str, port: int, username: str, password: str) -> Optional[str]:
    """
    Create a Chrome extension for proxy authentication.

    Chrome doesn't natively support authenticated proxies, so we create
    a small extension that intercepts proxy auth requests.

    Args:
        host: Proxy host
        port: Proxy port
        username: Proxy username
        password: Proxy password

    Returns:
        Path to the extension zip file, or None on failure
    """
    # Create extension directory if needed
    os.makedirs(PROXY_EXTENSION_DIR, exist_ok=True)

    # Create a unique filename based on proxy details
    ext_name = f"proxy_auth_{host}_{port}.zip"
    ext_path = os.path.join(PROXY_EXTENSION_DIR, ext_name)

    # If extension already exists for this proxy, reuse it
    if os.path.exists(ext_path):
        return ext_path

    # Manifest for the Chrome extension
    manifest_json = """{
    "version": "1.0.0",
    "manifest_version": 3,
    "name": "Proxy Auth Helper",
    "permissions": [
        "proxy",
        "webRequest",
        "webRequestAuthProvider"
    ],
    "host_permissions": [
        "<all_urls>"
    ],
    "background": {
        "service_worker": "background.js"
    }
}"""

    # Background script that handles proxy auth
    # Note: Manifest V3 uses a different approach for auth
    background_js = f"""
// Proxy configuration
const PROXY_HOST = "{host}";
const PROXY_PORT = {port};
const PROXY_USER = "{username}";
const PROXY_PASS = "{password}";

// Configure proxy settings
const config = {{
    mode: "fixed_servers",
    rules: {{
        singleProxy: {{
            scheme: "http",
            host: PROXY_HOST,
            port: PROXY_PORT
        }},
        bypassList: ["localhost", "127.0.0.1"]
    }}
}};

chrome.proxy.settings.set({{value: config, scope: 'regular'}}, function() {{}});

// Handle proxy authentication
chrome.webRequest.onAuthRequired.addListener(
    function(details) {{
        return {{
            authCredentials: {{
                username: PROXY_USER,
                password: PROXY_PASS
            }}
        }};
    }},
    {{urls: ["<all_urls>"]}},
    ["blocking"]
);

console.log("Proxy auth extension loaded for " + PROXY_HOST + ":" + PROXY_PORT);
"""

    try:
        # Create the extension zip file
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write manifest
            manifest_path = os.path.join(tmpdir, "manifest.json")
            with open(manifest_path, "w") as f:
                f.write(manifest_json)

            # Write background script
            bg_path = os.path.join(tmpdir, "background.js")
            with open(bg_path, "w") as f:
                f.write(background_js)

            # Create zip file
            with zipfile.ZipFile(ext_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(manifest_path, "manifest.json")
                zf.write(bg_path, "background.js")

        logger.debug(f"Created proxy auth extension: {ext_path}")
        return ext_path

    except Exception as e:
        logger.error(f"Failed to create proxy auth extension: {e}")
        return None


def create_proxy_auth_extension_mv2(host: str, port: int, username: str, password: str) -> Optional[str]:
    """
    Create a Chrome extension for proxy authentication using Manifest V2.

    Manifest V2 is deprecated but still works and has better support for
    blocking webRequest listeners needed for proxy auth.

    Args:
        host: Proxy host
        port: Proxy port
        username: Proxy username
        password: Proxy password

    Returns:
        Path to the extension zip file, or None on failure
    """
    # Create extension directory if needed
    os.makedirs(PROXY_EXTENSION_DIR, exist_ok=True)

    # Create a unique filename based on proxy details
    ext_name = f"proxy_auth_mv2_{host}_{port}.zip"
    ext_path = os.path.join(PROXY_EXTENSION_DIR, ext_name)

    # If extension already exists for this proxy, reuse it
    if os.path.exists(ext_path):
        return ext_path

    # Manifest V2 for better proxy auth support
    manifest_json = """{
    "version": "1.0.0",
    "manifest_version": 2,
    "name": "Proxy Auth Helper",
    "permissions": [
        "proxy",
        "tabs",
        "unlimitedStorage",
        "storage",
        "<all_urls>",
        "webRequest",
        "webRequestBlocking"
    ],
    "background": {
        "scripts": ["background.js"]
    }
}"""

    # Background script that configures proxy and handles auth
    background_js = f"""
var config = {{
    mode: "fixed_servers",
    rules: {{
        singleProxy: {{
            scheme: "http",
            host: "{host}",
            port: parseInt({port})
        }},
        bypassList: ["localhost"]
    }}
}};

chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

function callbackFn(details) {{
    return {{
        authCredentials: {{
            username: "{username}",
            password: "{password}"
        }}
    }};
}}

chrome.webRequest.onAuthRequired.addListener(
    callbackFn,
    {{urls: ["<all_urls>"]}},
    ['blocking']
);
"""

    try:
        # Create the extension zip file
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write manifest
            manifest_path = os.path.join(tmpdir, "manifest.json")
            with open(manifest_path, "w") as f:
                f.write(manifest_json)

            # Write background script
            bg_path = os.path.join(tmpdir, "background.js")
            with open(bg_path, "w") as f:
                f.write(background_js)

            # Create zip file
            with zipfile.ZipFile(ext_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(manifest_path, "manifest.json")
                zf.write(bg_path, "background.js")

        logger.debug(f"Created proxy auth extension (MV2): {ext_path}")
        return ext_path

    except Exception as e:
        logger.error(f"Failed to create proxy auth extension: {e}")
        return None


def cleanup_proxy_extensions(max_age_hours: int = 24):
    """Remove old proxy auth extensions."""
    if not os.path.exists(PROXY_EXTENSION_DIR):
        return

    cutoff = time.time() - (max_age_hours * 3600)

    for filename in os.listdir(PROXY_EXTENSION_DIR):
        filepath = os.path.join(PROXY_EXTENSION_DIR, filename)
        try:
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
                logger.debug(f"Cleaned up old proxy extension: {filename}")
        except Exception:
            pass


def set_browser_timezone(driver, timezone_id: str) -> bool:
    """
    Override browser timezone via Chrome DevTools Protocol.

    Args:
        driver: SeleniumBase/Selenium driver
        timezone_id: IANA timezone ID (e.g., 'America/New_York', 'America/Los_Angeles')

    Returns:
        True if successful, False otherwise
    """
    try:
        driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {
            "timezoneId": timezone_id
        })
        logger.debug(f"Set browser timezone to {timezone_id}")
        return True
    except Exception as e:
        logger.warning(f"Failed to set timezone: {e}")
        return False


def set_browser_geolocation(driver, latitude: float, longitude: float, accuracy: float = 100) -> bool:
    """
    Override browser GPS geolocation via Chrome DevTools Protocol.

    Args:
        driver: SeleniumBase/Selenium driver
        latitude: GPS latitude
        longitude: GPS longitude
        accuracy: Accuracy in meters (default 100)

    Returns:
        True if successful, False otherwise
    """
    try:
        driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy
        })
        logger.debug(f"Set browser geolocation to ({latitude}, {longitude})")
        return True
    except Exception as e:
        logger.warning(f"Failed to set geolocation: {e}")
        return False


def configure_browser_for_proxy(driver, proxy_config: dict) -> bool:
    """
    Configure browser timezone and geolocation to match proxy location.

    Args:
        driver: SeleniumBase/Selenium driver
        proxy_config: Dict from ResidentialProxyManager.get_browser_config() with:
            - timezone_id: IANA timezone ID
            - geolocation: {latitude, longitude, accuracy}

    Returns:
        True if all configurations succeeded
    """
    success = True

    # Set timezone
    timezone_id = proxy_config.get("timezone_id")
    if timezone_id:
        if not set_browser_timezone(driver, timezone_id):
            success = False

    # Set geolocation
    geo = proxy_config.get("geolocation", {})
    if geo.get("latitude") and geo.get("longitude"):
        if not set_browser_geolocation(
            driver,
            geo["latitude"],
            geo["longitude"],
            geo.get("accuracy", 100)
        ):
            success = False

    return success


# Default configuration
DEFAULT_HEADLESS = True
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_WAIT_TIME = 10

# Virtual display configuration
USE_VIRTUAL_DISPLAY = True  # Use Xvfb virtual display for headed mode
VIRTUAL_DISPLAY_NUM = 99    # Display number for Xvfb (:99)
_xvfb_process = None        # Global Xvfb process
_virtual_display_initialized = False  # Track if we've set up the display


def _ensure_virtual_display():
    """
    Ensure Xvfb virtual display is running.
    This allows headed Chrome to run without showing on the actual screen.
    """
    global _xvfb_process, _virtual_display_initialized

    if not USE_VIRTUAL_DISPLAY:
        return

    if _virtual_display_initialized:
        return

    display = f":{VIRTUAL_DISPLAY_NUM}"

    # Check if Xvfb is already running on this display
    try:
        result = subprocess.run(
            ['pgrep', '-f', f'Xvfb :{VIRTUAL_DISPLAY_NUM}'],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            os.environ['DISPLAY'] = display
            _virtual_display_initialized = True
            logger.info(f"Using existing Xvfb on {display}")
            return
    except Exception:
        pass

    # Start new Xvfb
    try:
        _xvfb_process = subprocess.Popen(
            ['Xvfb', display, '-screen', '0', '1920x1080x24', '-ac'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(0.5)  # Give Xvfb time to start
        os.environ['DISPLAY'] = display
        _virtual_display_initialized = True
        logger.info(f"Started Xvfb virtual display on {display}")
    except FileNotFoundError:
        logger.warning("Xvfb not installed. Install with: sudo apt-get install xvfb")
    except Exception as e:
        logger.warning(f"Failed to start Xvfb: {e}")


# Initialize virtual display at module load time
# This ensures ALL drivers use the virtual display
_ensure_virtual_display()


def stop_virtual_display():
    """Stop the Xvfb virtual display if we started it."""
    global _xvfb_process
    if _xvfb_process:
        _xvfb_process.terminate()
        _xvfb_process = None
        logger.info("Stopped Xvfb virtual display")


def click_element_human_like(driver, element, scroll_first: bool = True):
    """
    Performs a human-like button click with optional scrolling.

    Args:
        driver: Selenium/SeleniumBase driver
        element: Element to click
        scroll_first: Whether to scroll element into view first
    """
    try:
        if scroll_first:
            driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                element
            )
            time.sleep(random.uniform(0.5, 1.5))

        actions = ActionChains(driver)
        actions.move_to_element(element).pause(random.uniform(0.1, 0.3)).click().perform()

    except Exception as e:
        logger.debug(f"Human-like click failed, trying direct click: {e}")
        try:
            element.click()
        except Exception:
            driver.execute_script("arguments[0].click();", element)


def _get_proxy_info() -> Optional[dict]:
    """
    Get proxy info from existing ProxyManager.

    Returns:
        Dict with host, port, username, password or None
    """
    try:
        manager = get_proxy_manager()
        if not manager.is_enabled():
            return None

        proxy_info = manager.get_proxy(strategy="round_robin")
        if proxy_info is None:
            return None

        return {
            "host": proxy_info.host,
            "port": proxy_info.port,
            "username": proxy_info.username,
            "password": proxy_info.password,
        }

    except Exception as e:
        logger.warning(f"Error getting proxy: {e}")
        return None


def _get_proxy_string() -> Optional[str]:
    """
    Get proxy string for SeleniumBase from existing ProxyManager.

    Returns:
        Proxy string in format 'user:pass@host:port' or None
    """
    proxy_info = _get_proxy_info()
    if proxy_info is None:
        return None

    # SeleniumBase expects format: user:pass@host:port
    return f"{proxy_info['username']}:{proxy_info['password']}@{proxy_info['host']}:{proxy_info['port']}"


# Mobile device configuration (iPhone X)
MOBILE_VIEWPORT = {
    "width": 375,
    "height": 812,
}
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def get_uc_driver(
    headless: bool = DEFAULT_HEADLESS,
    use_proxy: bool = True,
    locale: str = "en",
    use_virtual_display: bool = True,
    mobile_mode: bool = False,
    use_proxy_extension: bool = True,  # Use extension for auth (more reliable)
    **kwargs  # Accept extra args for compatibility with get_driver_for_site
) -> Optional[Driver]:
    """
    Get a basic SeleniumBase undetected Chrome driver.

    Args:
        headless: Run in headless mode
        use_proxy: Whether to use proxy from ProxyManager
        locale: Browser locale
        use_virtual_display: Use Xvfb virtual display for headed mode (no visible window)
        mobile_mode: Emulate mobile device (iPhone X viewport and user agent)
        use_proxy_extension: Use Chrome extension for proxy auth (more reliable than direct)
        **kwargs: Additional arguments (ignored, for compatibility)

    Returns:
        SeleniumBase Driver or None on failure
    """
    try:
        # For non-headless mode, use virtual display to avoid showing on screen
        if not headless and use_virtual_display and USE_VIRTUAL_DISPLAY:
            _ensure_virtual_display()

        proxy_info = _get_proxy_info() if use_proxy else None
        proxy_extension_path = None

        # Build driver options
        driver_kwargs = {
            "uc": True,
            "headless": headless,
            "locale_code": locale,
        }

        if proxy_info:
            if use_proxy_extension:
                # Use Chrome extension for authenticated proxy (more reliable)
                proxy_extension_path = create_proxy_auth_extension_mv2(
                    host=proxy_info["host"],
                    port=proxy_info["port"],
                    username=proxy_info["username"],
                    password=proxy_info["password"],
                )
                if proxy_extension_path:
                    driver_kwargs["extension_zip"] = proxy_extension_path
                    logger.debug(f"Using proxy auth extension for {proxy_info['host']}:{proxy_info['port']}")
                else:
                    # Fallback to direct proxy string
                    proxy_string = f"{proxy_info['username']}:{proxy_info['password']}@{proxy_info['host']}:{proxy_info['port']}"
                    driver_kwargs["proxy"] = proxy_string
                    logger.warning("Proxy extension creation failed, using direct proxy string")
            else:
                # Use direct proxy string (may not work with authenticated proxies)
                proxy_string = f"{proxy_info['username']}:{proxy_info['password']}@{proxy_info['host']}:{proxy_info['port']}"
                driver_kwargs["proxy"] = proxy_string

        # Apply mobile mode settings
        if mobile_mode:
            driver_kwargs["agent"] = MOBILE_USER_AGENT
            logger.debug("Mobile mode enabled - using iPhone X user agent")

        # Allocate unique debugging port to avoid port conflicts
        debug_port = _get_free_debugging_port()
        driver_kwargs["chromium_arg"] = f"--remote-debugging-port={debug_port}"
        logger.debug(f"Using debugging port {debug_port}")

        driver = Driver(**driver_kwargs)
        # Store port on driver for cleanup later
        driver._debug_port = debug_port

        # Set mobile viewport after driver creation
        if mobile_mode:
            try:
                driver.set_window_size(
                    MOBILE_VIEWPORT["width"],
                    MOBILE_VIEWPORT["height"]
                )
                # Enable touch emulation via CDP
                driver.execute_cdp_cmd(
                    "Emulation.setTouchEmulationEnabled",
                    {"enabled": True, "maxTouchPoints": 5}
                )
                logger.debug(f"Mobile viewport set: {MOBILE_VIEWPORT['width']}x{MOBILE_VIEWPORT['height']}")
            except Exception as e:
                logger.warning(f"Could not set mobile viewport: {e}")

        log_msg = "Created UC driver"
        if proxy_info:
            log_msg += f" with proxy {proxy_info['host']}:{proxy_info['port']}"
            if proxy_extension_path:
                log_msg += " (via extension)"
        if mobile_mode:
            log_msg += " (mobile mode)"
        logger.info(log_msg)

        return driver

    except Exception as e:
        logger.error(f"Error creating UC driver: {e}")
        # Release port if it was allocated but driver creation failed
        if 'debug_port' in locals():
            _release_debugging_port(debug_port)
            logger.debug(f"Released port {debug_port} after driver creation failure")
        return None


def get_uc_driver_with_residential_proxy(
    directory: str = None,
    target_state: str = None,
    headless: bool = DEFAULT_HEADLESS,
    locale: str = "en",
    use_virtual_display: bool = True,
    mobile_mode: bool = False,
) -> Tuple[Optional['Driver'], Optional['ResidentialProxy']]:
    """
    Get a SeleniumBase driver configured with a residential proxy.

    Uses the ResidentialProxyManager to get a proxy and configures
    the browser with matching timezone and geolocation.

    Args:
        directory: Directory name for pool selection (e.g., 'yellowpages', 'yelp')
        target_state: Target state code for location matching (e.g., 'TX', 'CA')
        headless: Run in headless mode
        locale: Browser locale
        use_virtual_display: Use Xvfb for headed mode
        mobile_mode: Emulate mobile device

    Returns:
        Tuple of (Driver, ResidentialProxy) or (None, None) on failure
    """
    from seo_intelligence.services.residential_proxy_manager import get_residential_proxy_manager

    try:
        manager = get_residential_proxy_manager()

        # Get proxy based on directory or state
        if directory:
            proxy = manager.get_proxy_for_directory(directory)
        elif target_state:
            proxy = manager.get_proxy_for_state(target_state)
        else:
            proxy = manager.get_proxy_for_directory("pool_other")

        if not proxy:
            logger.warning("No healthy residential proxy available")
            return None, None

        # Create driver with proxy
        proxy_string = proxy.to_selenium_format()

        # For non-headless mode, use virtual display
        if not headless and use_virtual_display and USE_VIRTUAL_DISPLAY:
            _ensure_virtual_display()

        driver_kwargs = {
            "uc": True,
            "headless": headless,
            "locale_code": locale,
            "proxy": proxy_string,
        }

        if mobile_mode:
            driver_kwargs["agent"] = MOBILE_USER_AGENT

        # Allocate unique debugging port to avoid port conflicts
        debug_port = _get_free_debugging_port()
        driver_kwargs["chromium_arg"] = f"--remote-debugging-port={debug_port}"
        logger.debug(f"Using debugging port {debug_port} for residential proxy driver")

        driver = Driver(**driver_kwargs)
        # Store port on driver for cleanup later
        driver._debug_port = debug_port

        # Set mobile viewport if needed
        if mobile_mode:
            try:
                driver.set_window_size(MOBILE_VIEWPORT["width"], MOBILE_VIEWPORT["height"])
                driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
            except Exception as e:
                logger.warning(f"Could not set mobile viewport: {e}")

        # Configure timezone and geolocation to match proxy
        browser_config = manager.get_browser_config(proxy)
        configure_browser_for_proxy(driver, browser_config)

        logger.info(f"Created UC driver with residential proxy {proxy.host} "
                   f"({proxy.city_name}, {proxy.state} - TZ: {proxy.timezone})")

        return driver, proxy

    except Exception as e:
        logger.error(f"Error creating UC driver with residential proxy: {e}")
        # Release port if it was allocated but driver creation failed
        if 'debug_port' in locals():
            _release_debugging_port(debug_port)
            logger.debug(f"Released port {debug_port} after driver creation failure")
        return None, None


# Trust-building warmup URLs - common sites that establish normal browsing patterns
WARMUP_URLS = [
    ("https://www.google.com/", 2, 4),  # (url, min_wait, max_wait)
    ("https://www.weather.com/", 1, 3),
    ("https://www.cnn.com/", 1, 2),
    ("https://www.wikipedia.org/", 1, 2),
]

# Directory-specific warmup - visit related sites first
DIRECTORY_WARMUP = {
    "yellowpages": [
        ("https://www.google.com/search?q=local+businesses", 2, 4),
        ("https://www.whitepages.com/", 2, 3),
    ],
    "yelp": [
        ("https://www.google.com/search?q=restaurant+reviews", 2, 4),
        ("https://www.tripadvisor.com/", 2, 3),
    ],
    "manta": [
        ("https://www.google.com/search?q=business+directory", 2, 4),
    ],
}


def warmup_browser_session(
    driver,
    directory: str = None,
    warmup_count: int = 2,
    simulate_reading: bool = True
) -> bool:
    """
    Warm up browser session by visiting trust-building sites.

    This helps establish a more legitimate browsing pattern before
    hitting directory sites that have aggressive bot detection.

    Args:
        driver: SeleniumBase driver
        directory: Target directory (for directory-specific warmup)
        warmup_count: Number of warmup sites to visit (default 2)
        simulate_reading: Whether to simulate reading behavior

    Returns:
        True if warmup succeeded, False if blocked
    """
    import random

    warmup_sites = []

    # Add directory-specific warmup first
    if directory and directory in DIRECTORY_WARMUP:
        warmup_sites.extend(DIRECTORY_WARMUP[directory])

    # Add general warmup sites
    warmup_sites.extend(WARMUP_URLS)

    # Limit to warmup_count
    sites_to_visit = warmup_sites[:warmup_count]

    logger.info(f"Warming up browser session with {len(sites_to_visit)} sites...")

    for url, min_wait, max_wait in sites_to_visit:
        try:
            logger.debug(f"  Warmup: visiting {url}")
            driver.get(url)
            time.sleep(random.uniform(min_wait, max_wait))

            # Simulate reading behavior
            if simulate_reading:
                # Scroll down a bit
                try:
                    driver.execute_script("window.scrollTo(0, 300)")
                    time.sleep(random.uniform(0.5, 1.5))
                    driver.execute_script("window.scrollTo(0, 600)")
                    time.sleep(random.uniform(0.3, 0.8))
                except Exception:
                    pass

            # Check for blocks on warmup sites
            page_source = driver.page_source.lower()
            if "captcha" in page_source or "blocked" in page_source:
                logger.warning(f"  Warmup blocked at {url}")
                return False

        except Exception as e:
            logger.warning(f"  Warmup error at {url}: {e}")
            # Continue with other warmup sites

    logger.info("  Warmup complete")
    return True


def get_uc_driver_with_residential_proxy_and_warmup(
    directory: str = None,
    target_state: str = None,
    headless: bool = DEFAULT_HEADLESS,
    locale: str = "en",
    use_virtual_display: bool = True,
    mobile_mode: bool = False,
    warmup_count: int = 2,
) -> Tuple[Optional['Driver'], Optional['ResidentialProxy']]:
    """
    Get a SeleniumBase driver with residential proxy AND warmup session.

    Visits trust-building sites before returning the driver to establish
    a more legitimate browsing pattern.

    Args:
        directory: Directory name for pool selection
        target_state: Target state code for location matching
        headless: Run in headless mode
        locale: Browser locale
        use_virtual_display: Use Xvfb for headed mode
        mobile_mode: Emulate mobile device
        warmup_count: Number of warmup sites to visit (default 2)

    Returns:
        Tuple of (Driver, ResidentialProxy) or (None, None) on failure
    """
    # Get the driver with proxy
    driver, proxy = get_uc_driver_with_residential_proxy(
        directory=directory,
        target_state=target_state,
        headless=headless,
        locale=locale,
        use_virtual_display=use_virtual_display,
        mobile_mode=mobile_mode,
    )

    if not driver or not proxy:
        return None, None

    # Perform warmup
    warmup_success = warmup_browser_session(
        driver,
        directory=directory,
        warmup_count=warmup_count,
        simulate_reading=True
    )

    if not warmup_success:
        logger.warning("Warmup failed - browser may be detected")
        # Continue anyway, but log the warning

    return driver, proxy


def _check_google_page_ready(driver, wait: WebDriverWait) -> Tuple[bool, str]:
    """
    Check if Google search page is properly loaded and ready.

    Returns:
        Tuple of (success, error_message)
    """
    RECAPTCHA_ELEMENT = (By.CSS_SELECTOR, 'iframe[title="reCAPTCHA"]')
    SITE_CANT_BE_REACHED = (By.CSS_SELECTOR, 'div[class="icon icon-generic"]')
    GOOGLE_MENU_BAR = (By.CSS_SELECTOR, 'div[class*="Fgyi2e"]')
    ACCEPT_ALL_BUTTON = (By.CSS_SELECTOR, 'button[id="L2AGLb"]')
    G_RAISED_BUTTON = (By.CSS_SELECTOR, "g-raised-button")
    CHANGE_TO_ENGLISH = (By.TAG_NAME, "a")
    CLOSE_POPUP = (By.CSS_SELECTOR, 'a[role="button"][class="ZWOrEc"]')

    # Check for site unreachable
    try:
        site_unreachable = driver.find_elements(*SITE_CANT_BE_REACHED)
        if site_unreachable:
            return False, "SITE_UNREACHABLE"
    except Exception:
        pass

    # Check for CAPTCHA
    try:
        captcha = driver.find_elements(*RECAPTCHA_ELEMENT)
        if captcha:
            return False, "CAPTCHA_DETECTED"
    except Exception:
        pass

    # Handle "Accept All" cookie popup (EU)
    try:
        accept_btn = wait.until(EC.element_to_be_clickable(ACCEPT_ALL_BUTTON))
        click_element_human_like(driver, accept_btn)
        time.sleep(0.5)
    except Exception:
        pass

    # Handle location precision popup
    try:
        g_raised = driver.find_elements(*G_RAISED_BUTTON)
        if g_raised:
            texts = [el.text.lower() for el in g_raised]
            if "not now" in texts:
                not_now = g_raised[texts.index("not now")]
                click_element_human_like(driver, not_now)
            elif g_raised:
                click_element_human_like(driver, g_raised[-1])
    except Exception:
        pass

    # Handle close popup button
    try:
        close_btn = driver.find_elements(*CLOSE_POPUP)
        if close_btn:
            click_element_human_like(driver, close_btn[0])
    except Exception:
        pass

    # Handle "Change to English" link
    try:
        links = driver.find_elements(*CHANGE_TO_ENGLISH)
        english_link = [a for a in links if a.text.lower() == "change to english"]
        if english_link:
            click_element_human_like(driver, english_link[0])
            time.sleep(1)
    except Exception:
        pass

    # Verify page is showing results
    try:
        wait.until(EC.visibility_of_element_located(GOOGLE_MENU_BAR))
        return True, "OK"
    except Exception:
        return False, "PAGE_NOT_LOADED"


def _safe_maximize_window(driver):
    """
    Safely maximize window, handling Chrome 142+ CDP issues.

    Chrome 142 introduced breaking changes that can cause CDP errors.
    This wrapper catches those errors and falls back gracefully.
    """
    try:
        driver.maximize_window()
    except Exception as e:
        error_msg = str(e).lower()
        if "runtime.evaluate" in error_msg or "javascript" in error_msg:
            # Chrome 142+ CDP issue - try alternative approach
            try:
                driver.set_window_size(1920, 1080)
            except Exception:
                pass  # Continue even if resize fails
            logger.debug("maximize_window failed (Chrome 142 CDP issue), using set_window_size")
        else:
            logger.debug(f"maximize_window failed: {e}")


def get_google_serp_driver(
    headless: bool = DEFAULT_HEADLESS,
    use_proxy: bool = True,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    wait_time: int = DEFAULT_WAIT_TIME
) -> Optional[Driver]:
    """
    Get a driver configured for Google SERP scraping.

    Includes:
    - CAPTCHA detection
    - Cookie/popup handling
    - Language enforcement
    - Retry with new proxy on failure

    Args:
        headless: Run in headless mode
        use_proxy: Whether to use proxy
        retry_attempts: Number of retry attempts
        wait_time: Selenium wait time

    Returns:
        Configured Driver or None on failure
    """
    for attempt in range(retry_attempts):
        driver = None
        try:
            driver = get_uc_driver(headless=headless, use_proxy=use_proxy)
            if driver is None:
                continue

            _safe_maximize_window(driver)
            wait = WebDriverWait(driver, wait_time)

            # Navigate to Google and check page
            driver.get("https://www.google.com/search?q=whats+happening+today")
            time.sleep(random.uniform(1, 2))

            success, error = _check_google_page_ready(driver, wait)

            if success:
                # Double-check with another query
                driver.get("https://www.google.com/search?q=weather+status+now")
                time.sleep(random.uniform(0.5, 1))

                success2, _ = _check_google_page_ready(driver, wait)
                if success2:
                    logger.info(f"Google SERP driver ready (attempt {attempt + 1})")
                    return driver

            logger.warning(f"Google driver check failed: {error} (attempt {attempt + 1})")
            driver.quit()

        except Exception as e:
            logger.warning(f"Google driver setup error: {e} (attempt {attempt + 1})")
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    logger.error(f"Failed to create Google SERP driver after {retry_attempts} attempts")
    return None


def _check_yelp_page_ready(driver, wait: WebDriverWait) -> Tuple[bool, str]:
    """
    Check if Yelp page is properly loaded and ready.

    Returns:
        Tuple of (success, error_message)
    """
    PAGE_WRAPPER = (By.CSS_SELECTOR, 'div[data-testid="page-wrapper"]')
    CAPTCHA_ELEMENT = (By.CSS_SELECTOR, 'div[class="captcha"]')
    PAGE_NOT_AVAILABLE = (By.TAG_NAME, "h1")
    ACCEPT_COOKIES = (By.CSS_SELECTOR, 'button[id="onetrust-accept-btn-handler"]')

    # Check for CAPTCHA in iframes
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                captcha = driver.find_elements(*CAPTCHA_ELEMENT)
                if captcha:
                    driver.switch_to.default_content()
                    return False, "CAPTCHA_DETECTED"
            except Exception:
                pass
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
    except Exception:
        pass

    # Accept cookies if present
    try:
        accept_btn = wait.until(EC.element_to_be_clickable(ACCEPT_COOKIES))
        click_element_human_like(driver, accept_btn, scroll_first=False)
        time.sleep(0.5)
    except Exception:
        pass

    # Check for "page not available" message
    try:
        h1_elements = driver.find_elements(*PAGE_NOT_AVAILABLE)
        not_available = [el for el in h1_elements
                        if "this page is not available" in el.text.lower()]
        if not_available:
            return False, "PAGE_NOT_AVAILABLE"
    except Exception:
        pass

    # Check for page wrapper (indicates working page)
    try:
        wrapper = wait.until(EC.visibility_of_element_located(PAGE_WRAPPER))
        if wrapper:
            return True, "OK"
    except Exception:
        pass

    return False, "PAGE_NOT_LOADED"


def get_yelp_driver(
    headless: bool = DEFAULT_HEADLESS,
    use_proxy: bool = True,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    wait_time: int = DEFAULT_WAIT_TIME
) -> Optional[Driver]:
    """
    Get a driver configured for Yelp scraping.

    Includes:
    - CAPTCHA detection
    - Cookie handling
    - Page availability check
    - Retry with new proxy on failure

    Args:
        headless: Run in headless mode
        use_proxy: Whether to use proxy
        retry_attempts: Number of retry attempts
        wait_time: Selenium wait time

    Returns:
        Configured Driver or None on failure
    """
    for attempt in range(retry_attempts):
        driver = None
        try:
            driver = get_uc_driver(headless=headless, use_proxy=use_proxy)
            if driver is None:
                continue

            _safe_maximize_window(driver)
            wait = WebDriverWait(driver, wait_time)

            # Navigate to Yelp
            driver.get("https://www.yelp.com/")
            time.sleep(random.uniform(2, 3))

            success, error = _check_yelp_page_ready(driver, wait)

            if success:
                logger.info(f"Yelp driver ready (attempt {attempt + 1})")
                return driver

            logger.warning(f"Yelp driver check failed: {error} (attempt {attempt + 1})")
            driver.quit()

        except Exception as e:
            logger.warning(f"Yelp driver setup error: {e} (attempt {attempt + 1})")
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    logger.error(f"Failed to create Yelp driver after {retry_attempts} attempts")
    return None


def _check_bbb_page_ready(driver, wait: WebDriverWait) -> Tuple[bool, str]:
    """
    Check if BBB page is properly loaded and ready.

    Returns:
        Tuple of (success, error_message)
    """
    CLOUDFLARE_CHALLENGE = (
        By.CSS_SELECTOR,
        'iframe[title="Widget containing a Cloudflare security challenge"]'
    )
    ACCEPT_COOKIES = (By.CSS_SELECTOR, 'button[name="allow-all"][class="bds-button"]')

    # Check for Cloudflare challenge
    try:
        cf_elements = driver.find_elements(*CLOUDFLARE_CHALLENGE)
        if cf_elements:
            return False, "CLOUDFLARE_CHALLENGE"
    except Exception:
        pass

    # Accept cookies if present
    try:
        accept_btn = wait.until(EC.element_to_be_clickable(ACCEPT_COOKIES))
        click_element_human_like(driver, accept_btn, scroll_first=False)
        time.sleep(1)
    except Exception:
        pass

    return True, "OK"


def get_bbb_driver(
    headless: bool = DEFAULT_HEADLESS,
    use_proxy: bool = True,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    wait_time: int = DEFAULT_WAIT_TIME
) -> Optional[Driver]:
    """
    Get a driver configured for BBB (Better Business Bureau) scraping.

    Includes:
    - Cloudflare challenge detection
    - Cookie handling
    - Retry with new proxy on failure

    Args:
        headless: Run in headless mode
        use_proxy: Whether to use proxy
        retry_attempts: Number of retry attempts
        wait_time: Selenium wait time

    Returns:
        Configured Driver or None on failure
    """
    for attempt in range(retry_attempts):
        driver = None
        try:
            driver = get_uc_driver(headless=headless, use_proxy=use_proxy)
            if driver is None:
                continue

            _safe_maximize_window(driver)
            wait = WebDriverWait(driver, wait_time)

            # Navigate to BBB
            driver.get("https://www.bbb.org/")
            time.sleep(random.uniform(1, 2))

            success, error = _check_bbb_page_ready(driver, wait)

            if success:
                logger.info(f"BBB driver ready (attempt {attempt + 1})")
                return driver

            logger.warning(f"BBB driver check failed: {error} (attempt {attempt + 1})")
            driver.quit()

        except Exception as e:
            logger.warning(f"BBB driver setup error: {e} (attempt {attempt + 1})")
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    logger.error(f"Failed to create BBB driver after {retry_attempts} attempts")
    return None


def _check_yellowpages_page_ready(driver, wait: WebDriverWait) -> Tuple[bool, str]:
    """
    Check if YellowPages page is properly loaded and ready.

    Returns:
        Tuple of (success, error_message)
    """
    # Multiple possible selectors for YellowPages - they may have changed their layout
    SELECTORS_TO_TRY = [
        (By.CSS_SELECTOR, 'img[id="global-logo"]'),
        (By.CSS_SELECTOR, 'a.yp-logo'),
        (By.CSS_SELECTOR, '.yp-header'),
        (By.CSS_SELECTOR, 'header'),
        (By.CSS_SELECTOR, '[class*="logo"]'),
        (By.CSS_SELECTOR, 'nav'),
        (By.TAG_NAME, 'body'),  # Fallback - just check body exists with content
    ]

    for selector in SELECTORS_TO_TRY:
        try:
            element = wait.until(EC.presence_of_element_located(selector))
            if element:
                # For body, make sure it has real content
                if selector[1] == 'body':
                    body_text = element.text
                    if len(body_text) > 100:  # Has substantial content
                        return True, "OK"
                else:
                    return True, "OK"
        except Exception:
            continue

    return False, "PAGE_NOT_LOADED"


def get_yellowpages_driver(
    headless: bool = DEFAULT_HEADLESS,
    use_proxy: bool = True,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    wait_time: int = DEFAULT_WAIT_TIME
) -> Optional[Driver]:
    """
    Get a driver configured for YellowPages scraping.

    Args:
        headless: Run in headless mode
        use_proxy: Whether to use proxy
        retry_attempts: Number of retry attempts
        wait_time: Selenium wait time

    Returns:
        Configured Driver or None on failure
    """
    for attempt in range(retry_attempts):
        driver = None
        try:
            driver = get_uc_driver(headless=headless, use_proxy=use_proxy)
            if driver is None:
                continue

            _safe_maximize_window(driver)
            wait = WebDriverWait(driver, wait_time)

            # Navigate to YellowPages
            driver.get("https://www.yellowpages.com/")
            time.sleep(random.uniform(2, 3))

            success, error = _check_yellowpages_page_ready(driver, wait)

            if success:
                logger.info(f"YellowPages driver ready (attempt {attempt + 1})")
                return driver

            logger.warning(f"YellowPages driver check failed: {error} (attempt {attempt + 1})")
            driver.quit()

        except Exception as e:
            logger.warning(f"YellowPages driver setup error: {e} (attempt {attempt + 1})")
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    logger.error(f"Failed to create YellowPages driver after {retry_attempts} attempts")
    return None


def _check_gbp_page_ready(driver, wait: WebDriverWait) -> Tuple[bool, str]:
    """
    Check if Google Business Profile/Maps page is properly loaded and ready.

    Returns:
        Tuple of (success, error_message)
    """
    INPUT_BOX = (By.CSS_SELECTOR, 'input[role="combobox"]')
    ACCEPT_ALL_BUTTON = (By.CSS_SELECTOR, 'button[jsname="b3VHJd"]')
    ACCEPT_ALL_BUTTON_ALT = (By.CSS_SELECTOR, 'button[id="L2AGLb"]')
    G_RAISED_BUTTON = (By.CSS_SELECTOR, "g-raised-button")

    # Handle "Accept All" popups
    for selector in [ACCEPT_ALL_BUTTON, ACCEPT_ALL_BUTTON_ALT]:
        try:
            accept_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable(selector)
            )
            click_element_human_like(driver, accept_btn)
            time.sleep(0.5)
            break
        except Exception:
            pass

    # Handle location precision popup
    try:
        g_raised = driver.find_elements(*G_RAISED_BUTTON)
        if g_raised:
            texts = [el.text.lower() for el in g_raised]
            if "not now" in texts:
                not_now = g_raised[texts.index("not now")]
                click_element_human_like(driver, not_now)
    except Exception:
        pass

    # Handle "Change to English" link
    try:
        links = driver.find_elements(By.TAG_NAME, "a")
        english_link = [a for a in links if a.text.lower() == "change to english"]
        if english_link:
            click_element_human_like(driver, english_link[0])
            time.sleep(1)
    except Exception:
        pass

    # Check for input box (indicates Maps is ready)
    try:
        input_box = wait.until(EC.visibility_of_element_located(INPUT_BOX))
        if input_box:
            return True, "OK"
    except Exception:
        pass

    return False, "INPUT_NOT_FOUND"


def get_gbp_driver(
    headless: bool = DEFAULT_HEADLESS,
    use_proxy: bool = True,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    wait_time: int = DEFAULT_WAIT_TIME
) -> Optional[Driver]:
    """
    Get a driver configured for Google Business Profile (Maps) scraping.

    Includes:
    - Cookie/consent handling
    - Language enforcement
    - Retry with new proxy on failure

    Args:
        headless: Run in headless mode
        use_proxy: Whether to use proxy
        retry_attempts: Number of retry attempts
        wait_time: Selenium wait time

    Returns:
        Configured Driver or None on failure
    """
    for attempt in range(retry_attempts):
        driver = None
        try:
            driver = get_uc_driver(headless=headless, use_proxy=use_proxy)
            if driver is None:
                continue

            _safe_maximize_window(driver)
            wait = WebDriverWait(driver, wait_time)

            # First warm up with Google Search to handle consents
            driver.get("https://www.google.com/search?q=whats+happening+today")
            time.sleep(random.uniform(1, 2))

            # Handle any Google consent screens
            _check_google_page_ready(driver, wait)

            # Now go to Maps
            driver.get("https://www.google.com/maps")
            time.sleep(random.uniform(1, 2))

            success, error = _check_gbp_page_ready(driver, wait)

            if success:
                logger.info(f"GBP/Maps driver ready (attempt {attempt + 1})")
                return driver

            logger.warning(f"GBP driver check failed: {error} (attempt {attempt + 1})")
            driver.quit()

        except Exception as e:
            logger.warning(f"GBP driver setup error: {e} (attempt {attempt + 1})")
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    logger.error(f"Failed to create GBP driver after {retry_attempts} attempts")
    return None


# Convenience mapping of driver types
DRIVER_FACTORY = {
    "generic": get_uc_driver,
    "google": get_google_serp_driver,
    "google_serp": get_google_serp_driver,
    "yelp": get_yelp_driver,
    "bbb": get_bbb_driver,
    "yellowpages": get_yellowpages_driver,
    "yp": get_yellowpages_driver,
    "gbp": get_gbp_driver,
    "maps": get_gbp_driver,
}


def get_driver_for_site(
    site: str,
    headless: bool = DEFAULT_HEADLESS,
    use_proxy: bool = True,
    mobile_mode: bool = False,
    **kwargs
) -> Optional[Driver]:
    """
    Get appropriate driver for a specific site.

    Args:
        site: Site name (google, yelp, bbb, yellowpages, gbp, etc.)
        headless: Run in headless mode
        use_proxy: Whether to use proxy
        mobile_mode: Emulate mobile device (iPhone X viewport and user agent)
        **kwargs: Additional arguments for driver factory

    Returns:
        Configured Driver or None
    """
    site_lower = site.lower()
    factory = DRIVER_FACTORY.get(site_lower, get_uc_driver)

    # Only pass mobile_mode to get_uc_driver (generic driver) - site-specific drivers don't support it
    if factory == get_uc_driver:
        kwargs['mobile_mode'] = mobile_mode

    return factory(headless=headless, use_proxy=use_proxy, **kwargs)
