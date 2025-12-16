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
from typing import Optional, Tuple
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from seo_intelligence.services.proxy_manager import get_proxy_manager
from runner.logging_setup import get_logger

logger = get_logger("seleniumbase_drivers")


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


def _get_proxy_string() -> Optional[str]:
    """
    Get proxy string for SeleniumBase from existing ProxyManager.

    Returns:
        Proxy string in format 'user:pass@host:port' or None
    """
    try:
        manager = get_proxy_manager()
        if not manager.is_enabled():
            return None

        proxy_info = manager.get_proxy(strategy="round_robin")
        if proxy_info is None:
            return None

        # SeleniumBase expects format: user:pass@host:port
        return f"{proxy_info.username}:{proxy_info.password}@{proxy_info.host}:{proxy_info.port}"

    except Exception as e:
        logger.warning(f"Error getting proxy: {e}")
        return None


def get_uc_driver(
    headless: bool = DEFAULT_HEADLESS,
    use_proxy: bool = True,
    locale: str = "en",
    use_virtual_display: bool = True,
    **kwargs  # Accept extra args for compatibility with get_driver_for_site
) -> Optional[Driver]:
    """
    Get a basic SeleniumBase undetected Chrome driver.

    Args:
        headless: Run in headless mode
        use_proxy: Whether to use proxy from ProxyManager
        locale: Browser locale
        use_virtual_display: Use Xvfb virtual display for headed mode (no visible window)
        **kwargs: Additional arguments (ignored, for compatibility)

    Returns:
        SeleniumBase Driver or None on failure
    """
    try:
        # For non-headless mode, use virtual display to avoid showing on screen
        if not headless and use_virtual_display and USE_VIRTUAL_DISPLAY:
            _ensure_virtual_display()

        proxy = _get_proxy_string() if use_proxy else None

        if proxy:
            driver = Driver(
                uc=True,
                headless=headless,
                proxy=proxy,
                locale_code=locale
            )
            logger.debug(f"Created UC driver with proxy")
        else:
            driver = Driver(
                uc=True,
                headless=headless,
                locale_code=locale
            )
            logger.debug("Created UC driver without proxy")

        return driver

    except Exception as e:
        logger.error(f"Error creating UC driver: {e}")
        return None


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
    **kwargs
) -> Optional[Driver]:
    """
    Get appropriate driver for a specific site.

    Args:
        site: Site name (google, yelp, bbb, yellowpages, gbp, etc.)
        headless: Run in headless mode
        use_proxy: Whether to use proxy
        **kwargs: Additional arguments for driver factory

    Returns:
        Configured Driver or None
    """
    site_lower = site.lower()
    factory = DRIVER_FACTORY.get(site_lower, get_uc_driver)
    return factory(headless=headless, use_proxy=use_proxy, **kwargs)
