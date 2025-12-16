#!/usr/bin/env python3
"""
Selenium-Based Standardization Service with Full Stealth Tactics
Runs 24/7 to standardize business names using a headed Selenium browser.

This service:
1. Opens a SeleniumBase undetected Chrome browser (via Xvfb virtual display)
2. Visits company websites one by one with human-like behavior
3. Extracts business name from page content (title, JSON-LD, H1, OG tags)
4. Uses local LLM to clean/standardize the extracted name
5. Stores the standardized name in the database

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict
from dataclasses import dataclass

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# Selenium imports
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, StaleElementReferenceException

# Configuration
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434/api/generate')
MODEL_NAME = os.getenv('STANDARDIZATION_MODEL', 'standardization-mistral7b')
BATCH_SIZE = 50  # Smaller batches since browser scraping is slower
POLL_INTERVAL = 60  # seconds to wait when no work
HEARTBEAT_INTERVAL = 30
LOG_DIR = Path(__file__).parent.parent / 'logs'
DATA_DIR = Path(__file__).parent.parent / 'data'

# Browser settings
HEADLESS = os.getenv('BROWSER_HEADLESS', 'false').lower() == 'true'
DISPLAY = os.getenv('DISPLAY', ':99')
PAGE_TIMEOUT = 20  # seconds

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
    'session_start': datetime.now(timezone.utc).isoformat(),
    'last_batch_time': None,
}


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
    """
    try:
        page_source = driver.page_source.lower()
        page_title = driver.title.lower() if driver.title else ""

        # CAPTCHA indicators
        captcha_indicators = [
            'recaptcha',
            'hcaptcha',
            'captcha',
            'robot',
            'human verification',
            'verify you are human',
            'are you a robot',
            'prove you are human',
        ]

        for indicator in captcha_indicators:
            if indicator in page_source or indicator in page_title:
                return True, f"CAPTCHA detected: {indicator}"

        # Cloudflare challenge
        if 'checking your browser' in page_source or 'just a moment' in page_source:
            return True, "Cloudflare challenge"

        # Access denied / blocked
        block_indicators = [
            'access denied',
            'blocked',
            '403 forbidden',
            'not authorized',
            'permission denied',
        ]

        for indicator in block_indicators:
            if indicator in page_source:
                return True, f"Access blocked: {indicator}"

        # Check for reCAPTCHA iframe
        try:
            captcha_iframe = driver.find_elements(By.CSS_SELECTOR, 'iframe[title*="reCAPTCHA"]')
            if captcha_iframe:
                return True, "reCAPTCHA iframe detected"
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
    - Virtual display support for headed mode
    - Safe window maximize for Chrome 142+
    - Human-like user agent

    Args:
        headless: Whether to run in headless mode

    Returns:
        SeleniumBase Driver or None on failure
    """
    try:
        # Ensure virtual display is available for headed mode
        if not headless:
            ensure_virtual_display()

        driver = Driver(
            uc=True,  # Undetected Chrome - bypasses bot detection
            headless=headless,
            locale_code="en",
            # Additional stealth settings
            disable_csp=True,  # Disable Content Security Policy
            no_sandbox=True,   # Required for some environments
        )

        # Safe maximize window (handles Chrome 142+ CDP issues)
        safe_maximize_window(driver)

        # Set reasonable timeouts
        driver.set_page_load_timeout(PAGE_TIMEOUT)
        driver.implicitly_wait(5)

        logger.debug("Created Selenium UC driver with stealth features")
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

    text_lower = text.lower()
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


def standardize_with_llm(name: str) -> Tuple[Optional[str], float]:
    """
    Call LLM to standardize a business name.

    Args:
        name: Raw extracted business name

    Returns:
        Tuple of (standardized_name, confidence)
    """
    prompt = f"""<s>[INST] You are a business name standardization assistant.

Convert this business name to proper title case format:
- Remove legal suffixes (LLC, Inc, Corp, etc.)
- Remove special characters and symbols (except apostrophes)
- Fix ALL CAPS or all lowercase
- Keep it concise and professional
- IMPORTANT: Keep spaces between words! Do not merge words together.

Input: {name}

Output ONLY the standardized name with proper spacing, nothing else. [/INST]"""

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
                # Quality check: Reject if spaces were merged (camelCase issue)
                if ' ' in name and ' ' not in result and len(result) > 15:
                    logger.warning(f"Rejected merged output: '{name}' -> '{result}'")
                    return None, 0.0
                return result, 0.85

        return None, 0.0

    except Exception as e:
        logger.error(f"LLM error for '{name}': {e}")
        return None, 0.0


def get_companies_to_standardize(engine, limit: int = BATCH_SIZE) -> list:
    """
    Get companies needing standardization that have websites.
    Prioritizes verified companies.
    """
    with engine.connect() as conn:
        # First priority: verified companies with websites, no standardization
        result = conn.execute(text('''
            SELECT id, name, website
            FROM companies
            WHERE standardized_name IS NULL
            AND claude_verified = true
            AND website IS NOT NULL
            AND name IS NOT NULL
            AND LENGTH(name) > 2
            ORDER BY id
            LIMIT :limit
        '''), {'limit': limit})

        companies = [{'id': row[0], 'name': row[1], 'website': row[2]} for row in result]

        # If we got enough, return
        if len(companies) >= limit:
            return companies

        # Otherwise, get unverified companies with websites
        remaining = limit - len(companies)
        result = conn.execute(text('''
            SELECT id, name, website
            FROM companies
            WHERE standardized_name IS NULL
            AND (claude_verified IS NULL OR claude_verified = false)
            AND website IS NOT NULL
            AND name IS NOT NULL
            AND LENGTH(name) > 2
            ORDER BY id
            LIMIT :limit
        '''), {'limit': remaining})

        companies.extend([{'id': row[0], 'name': row[1], 'website': row[2]} for row in result])

        return companies


def update_standardized_name(engine, company_id: int, std_name: str, confidence: float, source: str):
    """Update company with standardized name"""
    with engine.connect() as conn:
        conn.execute(text('''
            UPDATE companies
            SET standardized_name = :std_name,
                standardized_name_source = :source,
                standardized_name_confidence = :confidence
            WHERE id = :id
        '''), {
            'id': company_id,
            'std_name': std_name,
            'source': source,
            'confidence': confidence
        })
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
    """Get count of companies needing standardization with websites"""
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT COUNT(*) FROM companies
            WHERE standardized_name IS NULL
            AND website IS NOT NULL
            AND name IS NOT NULL
            AND LENGTH(name) > 2
        '''))
        return result.scalar()


def process_company_with_browser(driver: Driver, company: dict) -> Tuple[bool, str]:
    """
    Process a single company using the Selenium browser.

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

        # Extract business name from page
        extracted_name, source = extract_business_name_from_page(page_data)

        if not extracted_name:
            # Fall back to original name if extraction failed
            extracted_name = original_name
            source = 'original_name'

        # Standardize with LLM
        std_name, confidence = standardize_with_llm(extracted_name)

        if std_name:
            return True, f"{std_name}|{confidence}|{source}"
        else:
            return False, "LLM standardization failed"

    except Exception as e:
        return False, f"Error: {str(e)}"


def process_batch(engine, driver: Driver) -> int:
    """Process a batch of companies"""
    companies = get_companies_to_standardize(engine)

    if not companies:
        return 0

    batch_success = 0
    batch_errors = 0
    batch_browser_errors = 0

    for company in companies:
        if not running:
            break

        try:
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
            else:
                batch_errors += 1
                # Track specific error types
                if 'Browser' in result or 'fetch' in result.lower() or 'WebDriver' in result:
                    batch_browser_errors += 1
                if 'Blocked' in result or 'CAPTCHA' in result or 'block' in result.lower():
                    stats['total_blocked'] += 1
                logger.warning(f"Failed to standardize '{company['name']}': {result}")

        except Exception as e:
            batch_errors += 1
            logger.error(f"Error processing {company['id']}: {e}")

    stats['total_processed'] += batch_success + batch_errors
    stats['total_success'] += batch_success
    stats['total_errors'] += batch_errors
    stats['total_browser_errors'] += batch_browser_errors
    stats['last_batch_time'] = datetime.now(timezone.utc).isoformat()

    return batch_success + batch_errors


def ensure_ollama_model():
    """Ensure the standardization model is available"""
    try:
        response = requests.get('http://localhost:11434/api/tags', timeout=10)
        if response.status_code == 200:
            models = [m['name'] for m in response.json().get('models', [])]
            if MODEL_NAME in models or f'{MODEL_NAME}:latest' in models:
                logger.info(f"Model {MODEL_NAME} is available")
                return True
            else:
                logger.warning(f"Model {MODEL_NAME} not found. Available: {models}")
                return False
    except Exception as e:
        logger.error(f"Cannot connect to Ollama: {e}")
        return False


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
    logger.info("  - Human-like scrolling and delays")
    logger.info("  - Cookie popup dismissal")
    logger.info("  - CAPTCHA/block detection")
    logger.info("  - Safe window maximize (Chrome 142+)")

    # Check Ollama model
    if not ensure_ollama_model():
        logger.error("Cannot start without standardization model")
        sys.exit(1)

    # Check virtual display for headed mode
    if not HEADLESS:
        if not ensure_virtual_display():
            logger.error("Cannot start headed browser without virtual display")
            sys.exit(1)

    engine = get_engine()

    # Get initial pending count
    pending = get_pending_count(engine)
    logger.info(f"Pending companies with websites: {pending:,}")

    last_heartbeat = 0
    driver = None

    try:
        # Start browser
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
                    write_heartbeat()
                    last_heartbeat = now

                # Process a batch
                processed = process_batch(engine, driver)

                if processed > 0:
                    logger.info(f"Processed {processed} companies. Total: {stats['total_success']:,} success, {stats['total_errors']:,} errors ({stats['total_browser_errors']:,} browser errors)")
                else:
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

    # Final heartbeat
    stats['status'] = 'stopped'
    write_heartbeat()

    logger.info("=" * 60)
    logger.info("SELENIUM-BASED STANDARDIZATION SERVICE STOPPED")
    logger.info(f"Total processed: {stats['total_success']:,}")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
