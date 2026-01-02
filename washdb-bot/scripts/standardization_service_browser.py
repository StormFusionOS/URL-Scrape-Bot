#!/usr/bin/env python3
"""
Selenium-Based Standardization Service with Full Stealth Tactics
Runs 24/7 to standardize business names using a headed Selenium browser.

IMPORTANT - SAFE STANDARDIZATION BEHAVIOR:
==========================================
The ORIGINAL business name from the database is ALWAYS preserved.
Website content is ONLY used as optional context to help the LLM understand
abbreviations or validate spelling. The website content can NEVER replace
the original business name.

Example of safe behavior:
- Original: "NDBC Handyman Services LLC"
- Website title: "Handyman Services in Leesburg VA"
- Result: "NDBC Handyman Services" (keeps NDBC, removes LLC)
- The website title is IGNORED as a replacement source

All standardization uses standardize_business_name() which:
1. Takes the ORIGINAL name as the PRIMARY and REQUIRED source
2. Uses website content only as optional CONTEXT (never replacement)
3. Validates that output preserves words from the original name
4. Blocks any LLM output that tries to replace the original name

This service:
1. Opens a SeleniumBase undetected Chrome browser (via Xvfb virtual display)
2. Visits company websites one by one with human-like behavior
3. Extracts business name from page content FOR CONTEXT ONLY
4. Uses local LLM to clean/standardize the ORIGINAL name (not replace it)
5. Stores the standardized name with source "selenium_original_preserved"

Uses Selenium with full stealth tactics from SEO scrapers:
- Human-like scrolling and clicking
- Random delays between actions
- Cookie/popup dismissal
- CAPTCHA/block detection
- Safe window maximize for Chrome 142+
"""

import os
import sys
import json
import time
import logging
import signal
import requests
import re
import random
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict
from dataclasses import dataclass

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
# Use override=False to ensure systemd Environment= directives take precedence
load_dotenv(override=False)

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# Selenium imports
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, StaleElementReferenceException
from selenium_stealth import stealth

# Import SEO browser pool for warmed sessions and escalation
try:
    from seo_intelligence.drivers.browser_pool import get_browser_pool, EnterpriseBrowserPool
    from seo_intelligence.drivers.browser_escalation import BrowserEscalationManager, BrowserTier
    SEO_POOL_AVAILABLE = True
except ImportError as e:
    SEO_POOL_AVAILABLE = False
    print(f"SEO browser pool not available: {e}")

# Import HeartbeatManager for watchdog integration
try:
    from services.heartbeat_manager import HeartbeatManager
    from db.database_manager import get_db_manager
    HEARTBEAT_MANAGER_AVAILABLE = True
except ImportError as e:
    HEARTBEAT_MANAGER_AVAILABLE = False
    print(f"HeartbeatManager not available: {e}")

# Configuration
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434/api/generate')
MODEL_NAME = os.getenv('OLLAMA_MODEL', 'unified-washdb')
BATCH_SIZE = 50  # Smaller batches since browser scraping is slower
POLL_INTERVAL = 60  # seconds to wait when no work
HEARTBEAT_INTERVAL = 30
LOG_DIR = Path(__file__).parent.parent / 'logs'
DATA_DIR = Path(__file__).parent.parent / 'data'

# Browser settings
HEADLESS = os.getenv('BROWSER_HEADLESS', 'false').lower() == 'true'
DISPLAY = os.getenv('DISPLAY', ':99')
PAGE_TIMEOUT = 20  # seconds

# Rate limiting settings (optimized for better throughput)
MIN_DELAY_BETWEEN_REQUESTS = 5.0   # Minimum seconds between requests
MAX_DELAY_BETWEEN_REQUESTS = 10.0  # Maximum seconds between requests
BLOCK_COOLDOWN_THRESHOLD = 10      # INCREASED: Number of blocks before cooldown (was 5)
BLOCK_COOLDOWN_SECONDS = 180       # REDUCED: 3 minute cooldown (was 5 min)
BROWSER_RESTART_THRESHOLD = 30     # INCREASED: Restart browser after this many blocks (was 20)
BLOCK_WINDOW_SECONDS = 600         # INCREASED: Window to track blocks (10 minutes)

# Retry queue settings - blocked sites go to Ultimate Playwright scraper
RETRY_BACKOFF_BASE_HOURS = 1       # 1 hour = 60 minutes for first retry (Ultimate scraper)
RETRY_BACKOFF_MAX_HOURS = 168      # Max retry delay (7 days)
MAX_STANDARDIZATION_ATTEMPTS = 5   # Max attempts before giving up

# SEO Browser Pool settings
USE_SEO_BROWSER_POOL = os.getenv('USE_SEO_BROWSER_POOL', 'false').lower() == 'true'  # Disabled - pool causes stalls
POOL_LEASE_TIMEOUT = 60            # Seconds to wait for pool session
POOL_LEASE_DURATION = 300          # Seconds to hold pool session

# User agent rotation pool (realistic 2024-2025 browsers)
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]

# Viewport sizes for randomization
VIEWPORTS = [
    {"width": 1920, "height": 1080},  # Full HD
    {"width": 1536, "height": 864},   # Common laptop
    {"width": 1440, "height": 900},   # MacBook Pro
    {"width": 1366, "height": 768},   # Common laptop
    {"width": 1680, "height": 1050},  # WSXGA+
]

def get_random_user_agent() -> str:
    """Get a random user agent from the pool."""
    return random.choice(USER_AGENTS)

def get_random_viewport() -> dict:
    """Get a random viewport size."""
    return random.choice(VIEWPORTS)

# Setup logging
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'standardization_browser.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global state
running = True
stats = {
    'total_processed': 0,
    'total_success': 0,
    'total_errors': 0,
    'total_browser_errors': 0,
    'total_blocked': 0,  # CAPTCHA/bot blocks detected
    'total_popups_dismissed': 0,  # Cookie popups dismissed
    'total_cooldowns': 0,  # Number of times we entered cooldown
    'total_browser_restarts': 0,  # Number of browser restarts due to blocks
    'session_start': datetime.now(timezone.utc).isoformat(),
    'last_batch_time': None,
}

# Module-level heartbeat manager for watchdog integration
_heartbeat_manager = None


class BlockTracker:
    """
    Tracks CAPTCHA/block events to implement cooldown and browser restart logic.
    Mimics the domain quarantine approach from SEO scrapers.
    """

    def __init__(self, window_seconds: int = BLOCK_WINDOW_SECONDS):
        self.window_seconds = window_seconds
        self.block_times = []  # List of timestamps when blocks occurred
        self.total_blocks_since_restart = 0
        self._lock = threading.Lock()

    def record_block(self):
        """Record a block event."""
        with self._lock:
            now = time.time()
            self.block_times.append(now)
            self.total_blocks_since_restart += 1
            # Clean up old entries
            self._cleanup()

    def _cleanup(self):
        """Remove block entries older than the window."""
        cutoff = time.time() - self.window_seconds
        self.block_times = [t for t in self.block_times if t > cutoff]

    def get_recent_block_count(self) -> int:
        """Get number of blocks in the recent window."""
        with self._lock:
            self._cleanup()
            return len(self.block_times)

    def should_cooldown(self) -> bool:
        """Check if we should enter cooldown due to too many recent blocks."""
        return self.get_recent_block_count() >= BLOCK_COOLDOWN_THRESHOLD

    def should_restart_browser(self) -> bool:
        """Check if we should restart browser due to accumulated blocks."""
        with self._lock:
            return self.total_blocks_since_restart >= BROWSER_RESTART_THRESHOLD

    def reset_restart_counter(self):
        """Reset the restart counter after browser restart."""
        with self._lock:
            self.total_blocks_since_restart = 0

    def get_stats(self) -> dict:
        """Get current block tracking stats."""
        with self._lock:
            self._cleanup()
            return {
                'recent_blocks': len(self.block_times),
                'blocks_since_restart': self.total_blocks_since_restart,
                'cooldown_threshold': BLOCK_COOLDOWN_THRESHOLD,
                'restart_threshold': BROWSER_RESTART_THRESHOLD,
            }


# Global block tracker
block_tracker = BlockTracker()


def get_request_delay() -> float:
    """Get a randomized delay between requests (human-like behavior)."""
    return random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)


@dataclass
class PageData:
    """Data extracted from a web page"""
    success: bool
    error: Optional[str] = None
    url: str = ""
    title: Optional[str] = None
    h1_text: Optional[str] = None
    json_ld: Optional[Dict] = None
    og_title: Optional[str] = None
    og_site_name: Optional[str] = None
    page_text: Optional[str] = None


# =============================================================================
# STEALTH HELPER FUNCTIONS (from SEO scrapers)
# =============================================================================

def click_element_human_like(driver, element, scroll_first: bool = True):
    """
    Performs a human-like button click with optional scrolling.
    Copied from seleniumbase_drivers.py for anti-bot stealth.
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


def human_like_scroll(driver, scroll_amount: int = None):
    """
    Perform human-like scrolling on the page.
    Simulates natural reading behavior.
    """
    try:
        if scroll_amount is None:
            # Random scroll amount (30-70% of viewport)
            viewport_height = driver.execute_script("return window.innerHeight")
            scroll_amount = int(viewport_height * random.uniform(0.3, 0.7))

        # Smooth scroll with slight randomization
        current_pos = driver.execute_script("return window.pageYOffset")
        target_pos = current_pos + scroll_amount

        # Scroll in small increments for human-like behavior
        steps = random.randint(3, 6)
        step_size = scroll_amount // steps

        for _ in range(steps):
            driver.execute_script(f"window.scrollBy(0, {step_size + random.randint(-20, 20)})")
            time.sleep(random.uniform(0.05, 0.15))

    except Exception as e:
        logger.debug(f"Human-like scroll failed: {e}")


def safe_maximize_window(driver):
    """
    Safely maximize window, handling Chrome 142+ CDP issues.
    Chrome 142 introduced breaking changes that can cause CDP errors.
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


def random_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Add a random human-like delay."""
    time.sleep(random.uniform(min_sec, max_sec))


def dismiss_popups(driver):
    """
    Try to dismiss common cookie consent and popup dialogs.
    """
    # Common cookie consent button selectors
    consent_selectors = [
        'button[id*="accept"]',
        'button[class*="accept"]',
        'button[id*="consent"]',
        'button[class*="consent"]',
        'button[id*="cookie"]',
        'button[class*="cookie"]',
        'a[id*="accept"]',
        'a[class*="accept"]',
        '[data-testid*="accept"]',
        '[aria-label*="Accept"]',
        '[aria-label*="accept"]',
        'button:contains("Accept")',
        'button:contains("I agree")',
        'button:contains("Got it")',
        'button:contains("OK")',
    ]

    for selector in consent_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for elem in elements:
                if elem.is_displayed() and elem.is_enabled():
                    text = elem.text.lower()
                    if any(word in text for word in ['accept', 'agree', 'ok', 'got it', 'consent', 'allow']):
                        click_element_human_like(driver, elem, scroll_first=False)
                        logger.debug(f"Dismissed popup with selector: {selector}")
                        time.sleep(0.3)
                        return True
        except Exception:
            continue

    return False


def detect_captcha_or_block(driver) -> Tuple[bool, str]:
    """
    Detect if the page shows a CAPTCHA or bot-blocking page.
    Returns (is_blocked, reason).

    Improved detection to avoid false positives from:
    - <meta name="robots"> tags (contains 'robot')
    - reCAPTCHA scripts loaded but not triggered
    - Normal page content mentioning 'blocked' or 'captcha'
    """
    try:
        page_source = driver.page_source.lower()
        page_title = driver.title.lower() if driver.title else ""

        # Check page title first - most reliable indicator
        title_indicators = [
            'captcha',
            'robot check',
            'are you human',
            'access denied',
            'blocked',
            'forbidden',
            'just a moment',  # Cloudflare
            'attention required',  # Cloudflare
        ]

        for indicator in title_indicators:
            if indicator in page_title:
                return True, f"CAPTCHA/block in title: {indicator}"

        # Check for VISIBLE CAPTCHA challenge elements (not just scripts)
        try:
            # Visible reCAPTCHA challenge box
            recaptcha_visible = driver.find_elements(By.CSS_SELECTOR,
                'iframe[src*="recaptcha"][style*="visibility: visible"], '
                'iframe[src*="recaptcha"]:not([style*="display: none"]), '
                '.g-recaptcha:not([style*="display: none"]), '
                '#recaptcha-anchor'
            )
            if recaptcha_visible:
                # Double-check it's actually visible
                for elem in recaptcha_visible:
                    try:
                        if elem.is_displayed():
                            return True, "Visible reCAPTCHA challenge"
                    except:
                        pass

            # hCaptcha challenge
            hcaptcha_visible = driver.find_elements(By.CSS_SELECTOR,
                'iframe[src*="hcaptcha"], .h-captcha'
            )
            for elem in hcaptcha_visible:
                try:
                    if elem.is_displayed():
                        return True, "Visible hCaptcha challenge"
                except:
                    pass

        except Exception:
            pass

        # Cloudflare challenge page detection (specific patterns)
        cloudflare_patterns = [
            'checking your browser before accessing',
            'please wait while we verify your browser',
            'this process is automatic',
            'ray id:',  # Cloudflare Ray ID on challenge pages
            'cloudflare-static/challenge-platform',
            'enable javascript and cookies to continue',
        ]

        for pattern in cloudflare_patterns:
            if pattern in page_source:
                return True, f"Cloudflare challenge: {pattern}"

        # Generic CAPTCHA challenge phrases (specific, not just keywords)
        challenge_phrases = [
            'please complete the captcha',
            'solve this captcha',
            'verify you are human',
            'prove you are human',
            'are you a robot',
            'i am not a robot',
            'confirm you are not a robot',
            'human verification required',
            'bot detection',
            'automated access',
            'unusual traffic',
            'too many requests',
        ]

        for phrase in challenge_phrases:
            if phrase in page_source:
                return True, f"CAPTCHA challenge: {phrase}"

        # Access denied patterns (must be in visible body, not scripts)
        # Check for error page indicators
        try:
            body_text = driver.find_element(By.TAG_NAME, 'body').text.lower()

            error_patterns = [
                'access denied',
                '403 forbidden',
                'you have been blocked',
                'your ip has been blocked',
                'request blocked',
            ]

            for pattern in error_patterns:
                if pattern in body_text:
                    return True, f"Access blocked: {pattern}"

        except Exception:
            pass

        return False, "OK"

    except Exception as e:
        logger.debug(f"Error checking for CAPTCHA/block: {e}")
        return False, "Check failed"


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global running
    logger.info(f"Received signal {signum}, shutting down...")
    running = False


def get_engine():
    """Create database connection"""
    return create_engine(
        os.getenv('DATABASE_URL'),
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


def ensure_virtual_display():
    """Ensure Xvfb virtual display is running"""
    try:
        result = subprocess.run(
            ['xdpyinfo', '-display', ':99'],
            capture_output=True,
            timeout=2
        )
        if result.returncode == 0:
            os.environ['DISPLAY'] = ':99'
            logger.info("Virtual display :99 is available")
            return True
    except Exception:
        pass

    # Try to start Xvfb
    try:
        subprocess.Popen(
            ['Xvfb', ':99', '-screen', '0', '1920x1080x24', '-ac'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(2)
        os.environ['DISPLAY'] = ':99'
        logger.info("Started virtual display :99")
        return True
    except Exception as e:
        logger.error(f"Could not start Xvfb: {e}")
        return False


def create_selenium_driver(headless: bool = False) -> Optional[Driver]:
    """
    Create a SeleniumBase undetected Chrome driver with full stealth features.

    Includes:
    - Undetected Chrome mode (uc=True)
    - selenium-stealth for additional fingerprint evasion
    - Random user agent rotation
    - Random viewport size
    - Virtual display support for headed mode

    Args:
        headless: Whether to run in headless mode

    Returns:
        SeleniumBase Driver or None on failure
    """
    try:
        # Ensure virtual display is available for headed mode
        if not headless:
            ensure_virtual_display()

        # Get random user agent for this session
        user_agent = get_random_user_agent()
        viewport = get_random_viewport()

        driver = Driver(
            uc=True,  # Undetected Chrome - bypasses bot detection
            headless=headless,
            locale_code="en",
            agent=user_agent,  # Random user agent
            # Additional stealth settings
            disable_csp=True,  # Disable Content Security Policy
            no_sandbox=True,   # Required for some environments
        )

        # Apply selenium-stealth for additional fingerprint evasion
        try:
            stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
                run_on_insecure_origins=False,
            )
            logger.debug("Applied selenium-stealth to driver")
        except Exception as e:
            logger.warning(f"Could not apply selenium-stealth: {e}")

        # Set random viewport size
        try:
            driver.set_window_size(viewport["width"], viewport["height"])
            logger.debug(f"Set viewport to {viewport['width']}x{viewport['height']}")
        except Exception:
            # Fall back to safe maximize
            safe_maximize_window(driver)

        # Set reasonable timeouts
        driver.set_page_load_timeout(PAGE_TIMEOUT)
        driver.implicitly_wait(5)

        logger.info(f"Created stealth driver with UA: {user_agent[:50]}...")
        return driver

    except Exception as e:
        logger.error(f"Error creating Selenium driver: {e}")
        return None


def extract_page_data(driver: Driver, url: str) -> PageData:
    """
    Navigate to URL and extract page data using Selenium with full stealth behavior.

    Includes:
    - Human-like waiting and delays
    - CAPTCHA/block detection
    - Cookie popup dismissal
    - Human-like scrolling before extraction

    Args:
        driver: Selenium driver
        url: URL to fetch

    Returns:
        PageData object with extracted information
    """
    try:
        # Navigate to URL
        driver.get(url)

        # Human-like initial wait (randomized)
        random_delay(2.0, 4.0)

        # Wait for page to load
        try:
            WebDriverWait(driver, PAGE_TIMEOUT).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except TimeoutException:
            return PageData(success=False, error="Page load timeout", url=url)

        # Check for CAPTCHA or bot blocking
        is_blocked, block_reason = detect_captcha_or_block(driver)
        if is_blocked:
            logger.warning(f"Page blocked: {block_reason} for {url}")
            return PageData(success=False, error=f"Blocked: {block_reason}", url=url)

        # Try to dismiss any popups (cookies, etc.)
        dismiss_popups(driver)
        random_delay(0.3, 0.8)

        # Human-like scroll to simulate reading behavior
        human_like_scroll(driver)
        random_delay(0.5, 1.0)

        # Extract title
        title = None
        try:
            title = driver.title
        except Exception:
            pass

        # Extract H1
        h1_text = None
        try:
            h1_elements = driver.find_elements(By.TAG_NAME, "h1")
            if h1_elements:
                h1_text = h1_elements[0].text.strip()
        except Exception:
            pass

        # Extract JSON-LD
        json_ld = None
        try:
            ld_scripts = driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]')
            for script in ld_scripts:
                try:
                    data = json.loads(script.get_attribute('innerHTML'))
                    # Handle array of objects
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get('@type') in ['LocalBusiness', 'Organization', 'WebSite']:
                                json_ld = item
                                break
                    elif isinstance(data, dict):
                        if data.get('@type') in ['LocalBusiness', 'Organization', 'WebSite']:
                            json_ld = data
                        # Handle nested @graph
                        elif '@graph' in data:
                            for item in data['@graph']:
                                if isinstance(item, dict) and item.get('@type') in ['LocalBusiness', 'Organization', 'WebSite']:
                                    json_ld = item
                                    break
                    if json_ld:
                        break
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

        # Extract OG tags
        og_title = None
        og_site_name = None
        try:
            og_title_elem = driver.find_elements(By.CSS_SELECTOR, 'meta[property="og:title"]')
            if og_title_elem:
                og_title = og_title_elem[0].get_attribute('content')

            og_site_name_elem = driver.find_elements(By.CSS_SELECTOR, 'meta[property="og:site_name"]')
            if og_site_name_elem:
                og_site_name = og_site_name_elem[0].get_attribute('content')
        except Exception:
            pass

        # Get page text (limited)
        page_text = None
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            page_text = body.text[:2000] if body else None
        except Exception:
            pass

        return PageData(
            success=True,
            url=url,
            title=title,
            h1_text=h1_text,
            json_ld=json_ld,
            og_title=og_title,
            og_site_name=og_site_name,
            page_text=page_text,
        )

    except WebDriverException as e:
        return PageData(success=False, error=f"WebDriver error: {str(e)[:100]}", url=url)
    except Exception as e:
        return PageData(success=False, error=f"Error: {str(e)[:100]}", url=url)


def is_error_page(text: str) -> bool:
    """Check if text indicates an error page or non-business content"""
    if not text:
        return True

    text_lower = text.lower().strip()

    # Exact matches that are definitely not business names
    exact_error_matches = [
        'home', 'homepage', 'welcome', 'sign in', 'sign up', 'login', 'log in',
        'untitled', 'new page', 'test', 'loading', 'please wait',
        'privacy error', 'security error', 'certificate error',
        'website disabled', 'account suspended', 'suspended',
        'error 500', 'error 404', 'error 403', 'error',
        'just another wordpress site', 'another wordpress site',
        'my site', 'my website', 'my blog', 'blog', 'news',
    ]

    if text_lower in exact_error_matches:
        return True

    # Substring patterns
    error_patterns = [
        '403 forbidden', '404 not found', '500 internal server error',
        '502 bad gateway', '503 service unavailable',
        'access denied', 'page not found', 'website expired',
        'site not found', 'domain for sale', 'this domain',
        'parked domain', 'coming soon', 'under construction',
        'squarespace', 'wix.com', 'godaddy', 'wordpress.com',  # Platform names alone
        'hugedomains', 'is for sale', 'buy this domain',  # Domain sale pages
        'just a moment', 'checking your browser',  # Cloudflare
        'attention required', 'enable javascript',
        'privacy error', 'ssl error', 'certificate error', 'connection error',
        'website disabled', 'account suspended', 'site suspended',
        'free website', 'get your free', 'default page',
        'web server default', 'apache2 default', 'nginx welcome',
        'congratulations', 'your new site',  # Default hosting pages
        'error occurred', 'something went wrong', 'oops',
        'not available', 'temporarily unavailable',
        'verify you are human', 'security check',  # CAPTCHA pages
        'recaptcha', 'hcaptcha', 'captcha',
    ]

    for pattern in error_patterns:
        if pattern in text_lower:
            return True

    return False


def extract_business_name_from_page(page_data: PageData) -> Tuple[Optional[str], str]:
    """
    Extract business name from page data using multiple sources.

    Priority order:
    1. JSON-LD name (most reliable structured data)
    2. OG site_name (social media metadata)
    3. Title tag (cleaned of taglines)
    4. H1 heading (often the business name)

    Returns:
        Tuple of (extracted_name, source_type)
    """
    # Check if the page is an error page first
    if is_error_page(page_data.title) or is_error_page(page_data.h1_text):
        return None, 'error_page'

    # 1. JSON-LD structured data
    if page_data.json_ld:
        json_name = page_data.json_ld.get('name')
        if json_name and len(json_name) > 2 and len(json_name) < 100:
            if not is_error_page(json_name):
                return json_name.strip(), 'json_ld'

    # 2. OG site name
    if page_data.og_site_name and len(page_data.og_site_name) > 2 and len(page_data.og_site_name) < 100:
        if not is_error_page(page_data.og_site_name):
            return page_data.og_site_name.strip(), 'og_site_name'

    # 3. Title tag (clean it up)
    if page_data.title:
        title = page_data.title
        # Remove common title patterns like "| Company Name" or "- Professional Services"
        separators = [' | ', ' - ', ' :: ', ' -- ', ' ~ ']
        for sep in separators:
            if sep in title:
                parts = title.split(sep)
                # Usually the company name is the first or last part
                # Take the shorter one if it looks like a company name
                for part in parts:
                    part = part.strip()
                    # Skip generic parts
                    if part.lower() in ['home', 'homepage', 'welcome', 'official site']:
                        continue
                    if len(part) > 3 and len(part) < 80:
                        if not is_error_page(part):
                            return part, 'title'
        # No separator found, use the whole title if reasonable length
        if len(title) > 2 and len(title) < 80:
            if not is_error_page(title):
                return title.strip(), 'title_full'

    # 4. H1 heading
    if page_data.h1_text and len(page_data.h1_text) > 2 and len(page_data.h1_text) < 100:
        # Skip generic H1s
        h1_lower = page_data.h1_text.lower()
        if h1_lower not in ['welcome', 'home', 'homepage', 'contact us', 'about us']:
            if not is_error_page(page_data.h1_text):
                return page_data.h1_text.strip(), 'h1'

    # 5. OG title as fallback
    if page_data.og_title and len(page_data.og_title) > 2 and len(page_data.og_title) < 100:
        if not is_error_page(page_data.og_title):
            return page_data.og_title.strip(), 'og_title'

    return None, 'none'


def _call_llm_for_standardization(prompt: str, original_name: str) -> Tuple[Optional[str], float]:
    """
    Internal helper to call the LLM with a prompt and validate the result.

    IMPORTANT: This is a private helper function. Always use standardize_business_name()
    which ensures the original name is preserved.

    Args:
        prompt: The LLM prompt to use
        original_name: The original name (for validation)

    Returns:
        Tuple of (standardized_name, confidence)
    """
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.1,
                    'num_predict': 50,
                }
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json().get('response', '').strip()
            # Clean up common LLM artifacts
            result = result.strip('"\' ').strip()
            if result and len(result) > 1 and len(result) < 200:
                # CRITICAL VALIDATION: Ensure result preserves original name structure
                original_words = set(w.lower() for w in original_name.split() if len(w) > 2)
                result_words = set(w.lower() for w in result.split() if len(w) > 2)

                # At least one significant word from original MUST be in result
                if original_words and not original_words.intersection(result_words):
                    logger.warning(f"BLOCKED: LLM tried to replace name: '{original_name}' -> '{result}'")
                    return None, 0.0

                # Quality check: Reject if spaces were merged (camelCase issue)
                if ' ' in original_name and ' ' not in result and len(result) > 15:
                    logger.warning(f"Rejected merged output: '{original_name}' -> '{result}'")
                    return None, 0.0

                return result, 0.85

        return None, 0.0

    except Exception as e:
        logger.error(f"LLM error for '{original_name}': {e}")
        return None, 0.0


def standardize_business_name(original_name: str, website_context: Optional[str] = None) -> Tuple[Optional[str], float]:
    """
    Standardize a business name while ALWAYS preserving the original name structure.

    THIS IS THE ONLY FUNCTION THAT SHOULD BE USED FOR STANDARDIZATION.

    The original business name from the database is ALWAYS the primary source.
    Website context is ONLY used to help understand abbreviations or validate spelling,
    it can NEVER replace the original name.

    Args:
        original_name: The original business name from the database (REQUIRED, PRIMARY SOURCE)
        website_context: Optional name from website (context only, NEVER replaces original)

    Returns:
        Tuple of (standardized_name, confidence)
        The standardized_name will ALWAYS be based on original_name, never website_context
    """
    if not original_name or not original_name.strip():
        return None, 0.0

    original_name = original_name.strip()

    # Determine if we have useful website context
    has_context = (
        website_context and
        website_context.strip() and
        website_context.lower().strip() != original_name.lower().strip()
    )

    if has_context:
        # Use website context to help understand the original name
        prompt = f"""<s>[INST] You are a business name standardization assistant.

CRITICAL: Your task is to STANDARDIZE the ORIGINAL business name. You must NOT replace it.

ORIGINAL name (from database - THIS IS PRIMARY): {original_name}
Website hint (context only - DO NOT USE AS REPLACEMENT): {website_context}

Rules:
1. Output MUST be based on the ORIGINAL name, not the website hint
2. Standardize to proper title case
3. Remove legal suffixes (LLC, Inc, Corp, etc.)
4. Keep spaces between words
5. Keep abbreviations from original (NDBC, ABC, etc.) exactly as-is
6. The website hint is ONLY for understanding context, NEVER for replacement

Examples of CORRECT behavior:
- Original: "NDBC Handyman Services LLC" + Website: "Handyman Services in Leesburg"
  Output: "NDBC Handyman Services" (kept NDBC from original, removed LLC)
- Original: "ABC Clean Co." + Website: "ABC Professional Cleaning"
  Output: "ABC Clean" (standardized original, ignored website version)

Examples of WRONG behavior (NEVER DO THIS):
- Original: "NDBC Handyman" -> Output: "Handyman Services in Leesburg" (WRONG - replaced original)
- Original: "ABC Clean" -> Output: "Professional Cleaning Services" (WRONG - replaced original)

Output ONLY the standardized version of the ORIGINAL name: [/INST]"""
    else:
        # No website context, just standardize the original name
        prompt = f"""<s>[INST] You are a business name standardization assistant.

Standardize this business name:
- Use proper title case
- Remove legal suffixes (LLC, Inc, Corp, etc.)
- Remove special characters (except apostrophes)
- Keep spaces between words
- Keep abbreviations exactly as-is

Input: {original_name}

Output ONLY the standardized name: [/INST]"""

    result, confidence = _call_llm_for_standardization(prompt, original_name)

    # If LLM failed or was blocked, return None (don't fall back to anything unsafe)
    if not result:
        return None, 0.0

    return result, confidence


# DEPRECATED: Keep for backwards compatibility but logs warning
def standardize_with_llm_and_context(original_name: str, website_name: Optional[str] = None) -> Tuple[Optional[str], float]:
    """
    DEPRECATED: Use standardize_business_name() instead.
    This function is kept only for backwards compatibility and redirects to the safe version.
    """
    logger.debug("standardize_with_llm_and_context is deprecated, using standardize_business_name")
    return standardize_business_name(original_name, website_name)


def get_companies_to_standardize(engine, limit: int = BATCH_SIZE) -> list:
    """
    Get VERIFIED companies needing standardization using SMART QUEUE system.

    Priority order:
    1. Easy domains: Never blocked, alive domain status, no previous failures
    2. Retry-ready: Previously blocked but next_retry_at has passed
    3. Unknown domains: Never checked domain status

    Excludes:
    - Dead domains (domain_status = 'dead')
    - Domains in retry cooldown (next_retry_at > NOW())
    - Domains that exceeded MAX_STANDARDIZATION_ATTEMPTS
    """
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT id, name, website, domain_status, block_count, standardization_attempts
            FROM companies
            WHERE standardized_name IS NULL
              AND (verified = true OR llm_verified = true)
              AND website IS NOT NULL
              AND name IS NOT NULL
              AND LENGTH(name) > 2
              -- Exclude dead domains
              AND (domain_status IS NULL OR domain_status != 'dead')
              -- Exclude domains in retry cooldown (haven't reached retry time yet)
              AND (next_retry_at IS NULL OR next_retry_at <= NOW())
              -- Exclude domains that exceeded max attempts
              AND (standardization_attempts IS NULL OR standardization_attempts < :max_attempts)
            ORDER BY
              -- Priority 1: Easy domains (never blocked, alive or unknown domain status)
              CASE
                WHEN (block_count IS NULL OR block_count = 0)
                     AND (domain_status IS NULL OR domain_status = 'alive' OR domain_status = 'unknown')
                THEN 0
              -- Priority 2: Retry-ready domains (blocked but ready to retry)
                WHEN next_retry_at IS NOT NULL AND next_retry_at <= NOW()
                THEN 1
              -- Priority 3: Unknown domains
                ELSE 2
              END,
              -- Secondary sort: fewer attempts first
              COALESCE(standardization_attempts, 0),
              -- Tertiary: older companies first
              id
            LIMIT :limit
        '''), {'limit': limit, 'max_attempts': MAX_STANDARDIZATION_ATTEMPTS})

        companies = [
            {
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'domain_status': row[3],
                'block_count': row[4] or 0,
                'attempts': row[5] or 0
            }
            for row in result
        ]
        return companies


def update_standardized_name(engine, company_id: int, std_name: str, confidence: float, source: str):
    """Update company with standardized name and reset failure tracking."""
    with engine.connect() as conn:
        conn.execute(text('''
            UPDATE companies
            SET standardized_name = :std_name,
                standardized_name_source = :source,
                standardized_name_confidence = :confidence,
                standardization_status = 'completed',
                -- Reset failure tracking on success
                next_retry_at = NULL
            WHERE id = :id
        '''), {
            'id': company_id,
            'std_name': std_name,
            'source': source,
            'confidence': confidence
        })
        conn.commit()


def record_standardization_attempt(engine, company_id: int):
    """Record a standardization attempt for tracking."""
    with engine.connect() as conn:
        conn.execute(text('''
            UPDATE companies
            SET standardization_attempts = COALESCE(standardization_attempts, 0) + 1
            WHERE id = :id
        '''), {'id': company_id})
        conn.commit()


def record_block_and_schedule_retry(engine, company_id: int, block_type: str):
    """
    Record a block event and schedule retry with exponential backoff.

    Backoff schedule:
    - Attempt 1: 6 hours
    - Attempt 2: 12 hours
    - Attempt 3: 24 hours
    - Attempt 4: 48 hours
    - Attempt 5: 168 hours (7 days)
    """
    with engine.connect() as conn:
        # Get current attempt count
        result = conn.execute(text('''
            SELECT COALESCE(standardization_failures, 0) as failures
            FROM companies WHERE id = :id
        '''), {'id': company_id})
        row = result.fetchone()
        failures = row[0] if row else 0

        # Calculate backoff delay (exponential with cap)
        backoff_hours = min(
            RETRY_BACKOFF_BASE_HOURS * (2 ** failures),
            RETRY_BACKOFF_MAX_HOURS
        )

        conn.execute(text('''
            UPDATE companies
            SET block_count = COALESCE(block_count, 0) + 1,
                last_block_at = NOW(),
                block_type = :block_type,
                standardization_failures = COALESCE(standardization_failures, 0) + 1,
                next_retry_at = NOW() + INTERVAL ':hours hours'
            WHERE id = :id
        '''.replace(':hours', str(int(backoff_hours)))), {
            'id': company_id,
            'block_type': block_type
        })
        conn.commit()

        logger.info(f"Scheduled retry for company {company_id} in {backoff_hours} hours (failure #{failures + 1})")


def record_dns_failure(engine, company_id: int):
    """Record DNS failure and mark domain as dead."""
    with engine.connect() as conn:
        conn.execute(text('''
            UPDATE companies
            SET domain_status = 'dead',
                last_domain_check = NOW(),
                standardization_failures = COALESCE(standardization_failures, 0) + 1
            WHERE id = :id
        '''), {'id': company_id})
        conn.commit()


def write_heartbeat():
    """Write heartbeat file for monitoring"""
    heartbeat = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'status': 'running' if running else 'stopping',
        'model': MODEL_NAME,
        'browser_mode': 'selenium_headed' if not HEADLESS else 'selenium_headless',
        **stats
    }

    heartbeat_file = DATA_DIR / 'standardization_browser_heartbeat.json'
    with open(heartbeat_file, 'w') as f:
        json.dump(heartbeat, f, indent=2)


def get_pending_count(engine) -> int:
    """
    Get count of VERIFIED companies needing standardization.
    Uses same criteria as smart queue (excludes dead domains and those in cooldown).
    """
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT COUNT(*) FROM companies
            WHERE standardized_name IS NULL
              AND (verified = true OR llm_verified = true)
              AND website IS NOT NULL
              AND name IS NOT NULL
              AND LENGTH(name) > 2
              -- Exclude dead domains
              AND (domain_status IS NULL OR domain_status != 'dead')
              -- Exclude domains in retry cooldown
              AND (next_retry_at IS NULL OR next_retry_at <= NOW())
              -- Exclude domains that exceeded max attempts
              AND (standardization_attempts IS NULL OR standardization_attempts < :max_attempts)
        '''), {'max_attempts': MAX_STANDARDIZATION_ATTEMPTS})
        return result.scalar()


def get_queue_stats(engine) -> dict:
    """Get detailed stats about the standardization queue."""
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT
                COUNT(*) FILTER (WHERE standardized_name IS NULL AND (verified = true OR llm_verified = true)) as total_pending,
                COUNT(*) FILTER (WHERE domain_status = 'dead') as dead_domains,
                COUNT(*) FILTER (WHERE next_retry_at IS NOT NULL AND next_retry_at > NOW()) as in_cooldown,
                COUNT(*) FILTER (WHERE standardization_attempts >= :max_attempts) as max_attempts_exceeded,
                COUNT(*) FILTER (WHERE block_count > 0) as blocked_domains,
                COUNT(*) FILTER (WHERE domain_status = 'alive' AND (block_count IS NULL OR block_count = 0)) as easy_domains
            FROM companies
            WHERE website IS NOT NULL
        '''), {'max_attempts': MAX_STANDARDIZATION_ATTEMPTS})
        row = result.fetchone()
        return {
            'total_pending': row[0],
            'dead_domains': row[1],
            'in_cooldown': row[2],
            'max_attempts_exceeded': row[3],
            'blocked_domains': row[4],
            'easy_domains': row[5]
        }


def process_company_with_browser(driver: Driver, company: dict) -> Tuple[bool, str]:
    """
    Process a single company using the Selenium browser.

    IMPORTANT: The original business name is ALWAYS preserved. Website content
    is only used as optional context to help with standardization, never to replace.

    Args:
        driver: Selenium Driver instance
        company: Company dict with id, name, website

    Returns:
        Tuple of (success, standardized_name or error_message)
    """
    website = company['website']
    original_name = company['name']

    try:
        # Fetch the page with browser
        page_data = extract_page_data(driver, website)

        if not page_data.success:
            return False, f"Browser fetch failed: {page_data.error}"

        # Extract business name from page FOR CONTEXT ONLY
        # This is NEVER used to replace the original name
        website_context, _ = extract_business_name_from_page(page_data)

        # Standardize the ORIGINAL name (website context is optional hint only)
        # standardize_business_name() guarantees the original name is preserved
        std_name, confidence = standardize_business_name(original_name, website_context)

        if std_name:
            # Source always indicates original name was used
            # "preserved" means original name structure was maintained
            result_source = "original_preserved"
            return True, f"{std_name}|{confidence}|{result_source}"
        else:
            return False, "LLM standardization failed"

    except Exception as e:
        return False, f"Error: {str(e)}"


def process_company_with_pool(pool: 'EnterpriseBrowserPool', company: dict) -> Tuple[bool, str]:
    """
    Process a single company using the SEO browser pool with warmed sessions.

    This uses the enterprise browser pool which has:
    - Pre-warmed sessions with browsing history
    - Automatic escalation through browser types on CAPTCHA
    - Session reputation tracking

    Args:
        pool: EnterpriseBrowserPool instance
        company: Company dict with id, name, website

    Returns:
        Tuple of (success, standardized_name or error_message)
    """
    website = company['website']
    original_name = company['name']
    lease = None
    detected_captcha = False
    detected_block = False

    try:
        # Extract domain from website
        from urllib.parse import urlparse
        domain = urlparse(website).netloc or website

        # Acquire a warmed session from the pool
        lease = pool.acquire_session(
            target_domain=domain,
            requester="standardization_service",
            timeout_seconds=POOL_LEASE_TIMEOUT,
            lease_duration_seconds=POOL_LEASE_DURATION,
        )

        if lease is None:
            logger.warning(f"Pool session unavailable for {domain}, skipping")
            return False, "Pool session unavailable"

        # Get driver from the lease
        driver = pool.get_driver(lease)

        if driver is None:
            logger.warning(f"Pool driver unavailable for {domain}")
            pool.release_session(lease, dirty=True, dirty_reason="No driver")
            return False, "Pool driver unavailable"

        logger.debug(f"Pool session acquired: {lease.lease_id[:8]} for {domain}")

        # Fetch the page with the pooled browser
        page_data = extract_page_data(driver, website)

        if not page_data.success:
            error_lower = page_data.error.lower() if page_data.error else ""
            detected_captcha = "captcha" in error_lower or "recaptcha" in error_lower
            detected_block = "blocked" in error_lower or "forbidden" in error_lower
            return False, f"Browser fetch failed: {page_data.error}"

        # Extract business name from page FOR CONTEXT ONLY
        website_context, _ = extract_business_name_from_page(page_data)

        # Standardize the ORIGINAL name
        std_name, confidence = standardize_business_name(original_name, website_context)

        if std_name:
            result_source = "pool_original_preserved"
            return True, f"{std_name}|{confidence}|{result_source}"
        else:
            return False, "LLM standardization failed"

    except Exception as e:
        error_str = str(e).lower()
        detected_captcha = "captcha" in error_str
        detected_block = "blocked" in error_str or "forbidden" in error_str
        return False, f"Error: {str(e)}"

    finally:
        # Always release the session back to the pool
        if lease:
            pool.release_session(
                lease,
                dirty=detected_captcha or detected_block,
                dirty_reason="CAPTCHA" if detected_captcha else ("Block" if detected_block else None),
                detected_captcha=detected_captcha,
                detected_block=detected_block,
            )
            logger.debug(f"Pool session released: {lease.lease_id[:8]}")


def process_batch_with_pool(engine, pool: 'EnterpriseBrowserPool') -> int:
    """
    Process a batch of companies using the SEO browser pool.

    Returns:
        Number of companies processed
    """
    companies = get_companies_to_standardize(engine)

    if not companies:
        return 0

    batch_success = 0
    batch_errors = 0

    for company in companies:
        if not running:
            break

        # Check if we need cooldown
        if block_tracker.should_cooldown():
            recent_blocks = block_tracker.get_recent_block_count()
            logger.warning(f"COOLDOWN: {recent_blocks} blocks. Pausing for {BLOCK_COOLDOWN_SECONDS}s...")
            stats['total_cooldowns'] += 1
            time.sleep(BLOCK_COOLDOWN_SECONDS)
            logger.info("Cooldown complete, resuming...")

        try:
            # Record the attempt
            record_standardization_attempt(engine, company['id'])

            success, result = process_company_with_pool(pool, company)

            if success:
                parts = result.split('|')
                std_name = parts[0]
                confidence = float(parts[1])
                source = f"seo_{parts[2]}"  # Prefix with "seo_" to indicate pool source

                update_standardized_name(engine, company['id'], std_name, confidence, source)
                batch_success += 1
                logger.info(f"Standardized: '{company['name']}' -> '{std_name}' (source: {source})")

                # Record success for watchdog
                if _heartbeat_manager:
                    _heartbeat_manager.record_job_complete()
                    _heartbeat_manager.set_current_work(company_id=company['id'], module='standardization')
            else:
                batch_errors += 1

                # Handle specific error types
                is_block = 'Blocked' in result or 'CAPTCHA' in result
                is_recaptcha = 'reCAPTCHA' in result.lower()

                if is_block or is_recaptcha:
                    block_tracker.record_block()
                    schedule_retry(engine, company['id'], "captcha" if is_recaptcha else "block")
                    logger.warning(f"Failed to standardize '{company['name']}': {result}")
                else:
                    logger.warning(f"Failed to standardize '{company['name']}': {result}")

                # Record failure for watchdog
                if _heartbeat_manager:
                    _heartbeat_manager.record_job_failed(
                        error=result[:200],
                        module_name='standardization',
                        company_id=company['id']
                    )

        except Exception as e:
            batch_errors += 1
            logger.error(f"Error processing '{company['name']}': {e}")
            # Record exception for watchdog
            if _heartbeat_manager:
                _heartbeat_manager.record_job_failed(
                    error=str(e)[:200],
                    module_name='standardization',
                    company_id=company.get('id')
                )

        # Small delay between requests
        time.sleep(random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS))

    # Update stats
    stats['total_success'] += batch_success
    stats['total_errors'] += batch_errors

    if batch_success > 0 or batch_errors > 0:
        logger.info(f"Processed {len(companies)} companies. Total: {stats['total_success']} success, {stats['total_errors']} errors ({stats.get('total_blocks', 0)} blocked)")

    return len(companies)


def process_batch(engine, driver: Driver) -> Tuple[int, bool]:
    """
    Process a batch of companies with rate limiting and block tracking.

    Returns:
        Tuple of (processed_count, needs_browser_restart)
    """
    companies = get_companies_to_standardize(engine)

    if not companies:
        return 0, False

    batch_success = 0
    batch_errors = 0
    batch_browser_errors = 0
    needs_restart = False

    for i, company in enumerate(companies):
        if not running:
            break

        # Check if we need cooldown due to too many recent blocks
        if block_tracker.should_cooldown():
            recent_blocks = block_tracker.get_recent_block_count()
            logger.warning(f"COOLDOWN: {recent_blocks} blocks in last {BLOCK_WINDOW_SECONDS}s. Pausing for {BLOCK_COOLDOWN_SECONDS}s...")
            stats['total_cooldowns'] += 1
            time.sleep(BLOCK_COOLDOWN_SECONDS)
            logger.info("Cooldown complete, resuming...")

        # Check if we need browser restart
        if block_tracker.should_restart_browser():
            logger.warning(f"BROWSER RESTART needed: {block_tracker.total_blocks_since_restart} blocks since last restart")
            needs_restart = True
            break

        try:
            # Record the attempt for tracking
            record_standardization_attempt(engine, company['id'])

            success, result = process_company_with_browser(driver, company)

            if success:
                # Parse result: "standardized_name|confidence|source"
                parts = result.split('|')
                std_name = parts[0]
                confidence = float(parts[1])
                source = f"selenium_{parts[2]}"  # Prefix with "selenium_" to indicate source

                update_standardized_name(engine, company['id'], std_name, confidence, source)
                batch_success += 1
                logger.info(f"Standardized: '{company['name']}' -> '{std_name}' (source: {source})")

                # Record success for watchdog
                if _heartbeat_manager:
                    _heartbeat_manager.record_job_complete()
                    _heartbeat_manager.set_current_work(company_id=company['id'], module='standardization')
            else:
                batch_errors += 1

                # Detect and handle specific error types for smart queue
                is_dns_failure = 'ERR_NAME_NOT_RESOLVED' in result or 'ERR_NAME_RESOLUTION' in result
                is_recaptcha = 'reCAPTCHA' in result or 'recaptcha' in result.lower()
                is_hcaptcha = 'hCaptcha' in result or 'hcaptcha' in result.lower()
                is_cloudflare = 'Cloudflare' in result or 'cloudflare' in result.lower() or 'turnstile' in result.lower()
                is_block = 'Blocked' in result or 'CAPTCHA' in result or 'block' in result.lower()

                if is_dns_failure:
                    # Dead domain - mark for permanent skip
                    record_dns_failure(engine, company['id'])
                    logger.info(f"Marked domain as dead for company {company['id']}")
                elif is_recaptcha or is_hcaptcha or is_cloudflare or is_block:
                    # Block detected - schedule retry with backoff
                    # Use specific block types for ultimate scraper fallback
                    if is_recaptcha:
                        block_type = 'recaptcha'
                    elif is_hcaptcha:
                        block_type = 'hcaptcha'
                    elif is_cloudflare:
                        block_type = 'cloudflare'
                    else:
                        block_type = 'captcha'  # Generic CAPTCHA/block
                    record_block_and_schedule_retry(engine, company['id'], block_type)
                    stats['total_blocked'] += 1
                    block_tracker.record_block()  # Track for cooldown/restart
                    logger.info(f"Block type '{block_type}' - flagged for ultimate scraper fallback")

                # Track browser errors
                if 'Browser' in result or 'fetch' in result.lower() or 'WebDriver' in result:
                    batch_browser_errors += 1

                logger.warning(f"Failed to standardize '{company['name']}': {result}")

                # Record failure for watchdog
                if _heartbeat_manager:
                    _heartbeat_manager.record_job_failed(
                        error=result[:200],
                        module_name='standardization',
                        company_id=company['id']
                    )

        except Exception as e:
            batch_errors += 1
            logger.error(f"Error processing {company['id']}: {e}")
            # Record exception for watchdog
            if _heartbeat_manager:
                _heartbeat_manager.record_job_failed(
                    error=str(e)[:200],
                    module_name='standardization',
                    company_id=company.get('id')
                )

        # Add human-like delay between requests (except after last item)
        if i < len(companies) - 1 and running:
            delay = get_request_delay()
            logger.debug(f"Waiting {delay:.1f}s before next request...")
            time.sleep(delay)

    stats['total_processed'] += batch_success + batch_errors
    stats['total_success'] += batch_success
    stats['total_errors'] += batch_errors
    stats['total_browser_errors'] += batch_browser_errors
    stats['last_batch_time'] = datetime.now(timezone.utc).isoformat()

    return batch_success + batch_errors, needs_restart


def ensure_ollama_model_loaded() -> bool:
    """
    Ensure the standardization model is LOADED and RUNNING in Ollama.

    This is critical because Ollama can only have ONE model loaded at a time on this GPU.
    We must check /api/ps (running models), not just /api/tags (installed models).

    Returns:
        True if our model is loaded and working, False otherwise
    """
    try:
        # Step 1: Check what model is currently RUNNING (not just installed)
        ps_response = requests.get('http://localhost:11434/api/ps', timeout=10)
        if ps_response.status_code == 200:
            running_models = ps_response.json().get('models', [])
            if running_models:
                loaded_model = running_models[0].get('name', '')
                if MODEL_NAME in loaded_model or f'{MODEL_NAME}:latest' in loaded_model:
                    logger.info(f"Correct model {MODEL_NAME} is loaded and ready")
                    return True
                else:
                    logger.error(f"WRONG MODEL LOADED: '{loaded_model}' is active, but we need '{MODEL_NAME}'")
                    logger.error("The scheduler should switch models. Service will wait...")
                    return False

        # Step 2: No model loaded - try to load ours
        logger.info(f"No model loaded. Attempting to load {MODEL_NAME}...")
        test_response = requests.post(
            OLLAMA_URL,
            json={
                'model': MODEL_NAME,
                'prompt': 'test',
                'stream': False,
                'options': {'num_predict': 5}
            },
            timeout=120  # First load can take time
        )

        if test_response.status_code == 200:
            logger.info(f"Model {MODEL_NAME} loaded successfully")
            return True
        else:
            logger.error(f"Failed to load model: HTTP {test_response.status_code}")
            return False

    except requests.exceptions.Timeout:
        logger.error("Timeout connecting to Ollama - is it running?")
        return False
    except Exception as e:
        logger.error(f"Error checking Ollama model: {e}")
        return False


def ensure_ollama_model():
    """Legacy wrapper - redirects to ensure_ollama_model_loaded()"""
    return ensure_ollama_model_loaded()


def main():
    global running

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("=" * 60)
    logger.info("SELENIUM STEALTH STANDARDIZATION SERVICE STARTING")
    logger.info("=" * 60)
    logger.info(f"Model: {MODEL_NAME}")
    logger.info(f"Batch size: {BATCH_SIZE}")
    logger.info(f"Poll interval: {POLL_INTERVAL}s")
    logger.info(f"Browser mode: {'headless' if HEADLESS else 'headed (Xvfb)'}")
    logger.info("Stealth features enabled:")
    logger.info("  - Undetected Chrome (uc=True)")
    logger.info("  - selenium-stealth fingerprint evasion")
    logger.info(f"  - User agent rotation ({len(USER_AGENTS)} agents)")
    logger.info(f"  - Viewport randomization ({len(VIEWPORTS)} sizes)")
    logger.info("  - Human-like scrolling and delays")
    logger.info("  - Cookie popup dismissal")
    logger.info("  - CAPTCHA/block detection")
    logger.info("Rate limiting features:")
    logger.info(f"  - Request delay: {MIN_DELAY_BETWEEN_REQUESTS}-{MAX_DELAY_BETWEEN_REQUESTS}s between requests")
    logger.info(f"  - Block cooldown: {BLOCK_COOLDOWN_SECONDS}s after {BLOCK_COOLDOWN_THRESHOLD} blocks")
    logger.info(f"  - Browser restart: after {BROWSER_RESTART_THRESHOLD} accumulated blocks")

    # Check Ollama model - wait for scheduler to load correct model if needed
    MAX_WAIT_MINUTES = 30  # Wait up to 30 min for scheduler to switch models
    CHECK_INTERVAL = 60   # Check every minute
    wait_start = time.time()

    while not ensure_ollama_model_loaded():
        elapsed_minutes = (time.time() - wait_start) / 60
        if elapsed_minutes > MAX_WAIT_MINUTES:
            logger.error(f"Waited {MAX_WAIT_MINUTES} minutes for correct model. Exiting.")
            logger.error("Check if the scheduler (model_scheduler.sh) is running.")
            sys.exit(1)
        logger.info(f"Waiting for scheduler to load correct model... ({elapsed_minutes:.1f} min elapsed)")
        time.sleep(CHECK_INTERVAL)

    logger.info("LLM model check passed - correct model is loaded")

    # Check virtual display for headed mode
    if not HEADLESS:
        if not ensure_virtual_display():
            logger.error("Cannot start headed browser without virtual display")
            sys.exit(1)

    engine = get_engine()

    # Initialize HeartbeatManager for watchdog integration
    global _heartbeat_manager
    if HEARTBEAT_MANAGER_AVAILABLE:
        try:
            import socket as sock
            _heartbeat_manager = HeartbeatManager(
                db_manager=get_db_manager(),
                worker_name=f"standardization_{sock.gethostname()}",
                worker_type='standardization_browser',
                service_unit='washdb-standardization-browser'
            )
            _heartbeat_manager.start(config={
                'model': MODEL_NAME,
                'headless': HEADLESS,
                'batch_size': BATCH_SIZE,
            })
            logger.info("HeartbeatManager started - watchdog integration enabled")
        except Exception as e:
            logger.warning(f"Failed to start HeartbeatManager: {e}")
            _heartbeat_manager = None

    # Get initial pending count
    pending = get_pending_count(engine)
    logger.info(f"Pending companies with websites: {pending:,}")

    # Check if we should use SEO browser pool
    use_pool = USE_SEO_BROWSER_POOL and SEO_POOL_AVAILABLE
    pool = None

    if use_pool:
        logger.info("=" * 60)
        logger.info("USING SEO BROWSER POOL (warmed sessions + escalation)")
        logger.info("=" * 60)
        try:
            pool = get_browser_pool()
            logger.info(f"Browser pool initialized: {pool._enabled}")
        except Exception as e:
            logger.warning(f"Failed to initialize browser pool: {e}")
            logger.info("Falling back to direct browser mode")
            use_pool = False

    last_heartbeat = 0
    driver = None

    try:
        if use_pool and pool:
            # Use SEO browser pool mode
            logger.info("Using SEO browser pool for warmed sessions...")

            while running:
                try:
                    # Write heartbeat periodically
                    now = time.time()
                    if now - last_heartbeat > HEARTBEAT_INTERVAL:
                        stats['pending_count'] = get_pending_count(engine)
                        stats['block_stats'] = block_tracker.get_stats()
                        write_heartbeat()
                        last_heartbeat = now

                    # Process a batch using the pool
                    processed = process_batch_with_pool(engine, pool)

                    if processed == 0:
                        logger.info(f"No pending companies. Waiting {POLL_INTERVAL}s...")
                        for _ in range(POLL_INTERVAL):
                            if not running:
                                break
                            time.sleep(1)

                except Exception as e:
                    logger.error(f"Error in pool main loop: {e}")
                    time.sleep(30)

            # Cleanup pool on exit
            logger.info("Shutting down browser pool...")
            try:
                pool.shutdown()
            except:
                pass
            return

        # Fallback: Direct browser mode (original behavior)
        logger.info("Starting Selenium undetected Chrome browser...")
        driver = create_selenium_driver(headless=HEADLESS)
        if not driver:
            logger.error("Failed to create Selenium driver")
            sys.exit(1)
        logger.info("Selenium browser started successfully")

        while running:
            try:
                # Write heartbeat periodically
                now = time.time()
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    stats['pending_count'] = get_pending_count(engine)
                    stats['block_stats'] = block_tracker.get_stats()
                    write_heartbeat()
                    last_heartbeat = now

                # Process a batch
                processed, needs_restart = process_batch(engine, driver)

                if processed > 0:
                    block_stats = block_tracker.get_stats()
                    logger.info(f"Processed {processed} companies. Total: {stats['total_success']:,} success, {stats['total_errors']:,} errors ({stats['total_blocked']:,} blocked)")

                # Handle browser restart due to accumulated blocks
                if needs_restart:
                    logger.warning("Restarting browser due to accumulated blocks...")
                    stats['total_browser_restarts'] += 1
                    try:
                        driver.quit()
                    except:
                        pass
                    time.sleep(5)  # Brief pause before restart
                    driver = create_selenium_driver(headless=HEADLESS)
                    if driver:
                        block_tracker.reset_restart_counter()
                        logger.info(f"Browser restarted successfully (restart #{stats['total_browser_restarts']})")
                    else:
                        logger.error("Could not restart browser after blocks")
                        time.sleep(60)
                        driver = create_selenium_driver(headless=HEADLESS)

                if processed == 0 and not needs_restart:
                    # No work available, wait before polling again
                    logger.info(f"No pending companies. Waiting {POLL_INTERVAL}s...")
                    for _ in range(POLL_INTERVAL):
                        if not running:
                            break
                        time.sleep(1)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                # Try to restart browser if it crashed
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    try:
                        driver = create_selenium_driver(headless=HEADLESS)
                        if driver:
                            block_tracker.reset_restart_counter()
                            logger.info("Selenium browser restarted after error")
                        else:
                            logger.error("Could not restart Selenium browser")
                            time.sleep(30)
                    except Exception as be:
                        logger.error(f"Could not restart browser: {be}")
                        time.sleep(30)
                time.sleep(10)

    finally:
        # Cleanup
        if driver:
            try:
                driver.quit()
            except:
                pass
            logger.info("Selenium browser stopped")

        # Stop HeartbeatManager
        if _heartbeat_manager:
            try:
                _heartbeat_manager.stop('stopped')
                logger.info("HeartbeatManager stopped")
            except Exception as e:
                logger.warning(f"Failed to stop HeartbeatManager: {e}")

    # Final heartbeat
    stats['status'] = 'stopped'
    write_heartbeat()

    logger.info("=" * 60)
    logger.info("SELENIUM-BASED STANDARDIZATION SERVICE STOPPED")
    logger.info(f"Total processed: {stats['total_success']:,}")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
