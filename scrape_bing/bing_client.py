"""
Bing client module - query building, fetching, parsing, and rate limiting.

This module handles the low-level interactions with Bing search, supporting
both HTML scraping and API modes. It provides:

- Query building: Constructs Bing search queries from category/location pairs
- Fetch layer: HTTP requests with retry logic, backoff, and rate limiting
- Parser: Extracts normalized business data from SERP HTML or API JSON
- Mode switching: Automatically uses API or HTML based on configuration

Responsibilities:
    - build_bing_query(): Compose search queries with proper encoding
    - fetch_bing_search_page(): Execute HTTP requests with retry/backoff
    - parse_bing_results(): Extract business info from raw page payloads
    - Rate limiting and polite crawling behavior
    - Robust error handling and logging

Usage:
    from scrape_bing.bing_client import fetch_bing_search_page, parse_bing_results

    # Fetch a page
    payload = fetch_bing_search_page("pressure washing Peoria IL", page=1)

    # Parse results
    businesses = parse_bing_results(payload)
"""

import logging
import time
import re
import os
import random
from typing import Optional, Union, Dict, List, Any
from urllib.parse import urlencode, quote_plus
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from datetime import datetime

from scrape_bing.bing_config import (
    BING_API_KEY,
    BING_API_BASE,
    BING_BASE_URL,
    HEADERS,
    USER_AGENT,
    USE_API,
    CRAWL_DELAY_SECONDS,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
    MAX_RESULTS_PER_PAGE,
    RESULTS_PER_PAGE_OFFSET,
)

# Import URL helpers from db.models
from db.models import canonicalize_url, domain_from_url

# Playwright imports (lazy loaded)
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Playwright not available - HTML mode will use simple HTTP requests")

# Configure logging
logger = logging.getLogger(__name__)


# ==============================================================================
# Rate Limiting State
# ==============================================================================

_last_request_time = 0.0


def _apply_rate_limit():
    """
    Apply polite rate limiting between requests with randomization.

    Enforces CRAWL_DELAY_SECONDS (+/- random jitter) between consecutive
    requests to avoid overwhelming the server, respect ToS, and make traffic
    patterns look more human-like.

    Randomization prevents bot detection by:
    - Varying request intervals (not perfectly timed like a bot)
    - Making traffic analysis harder
    - Mimicking human behavior (inconsistent timing)
    """
    global _last_request_time

    # Add random jitter: -20% to +50% of base delay
    # E.g., 3s base becomes 2.4s to 4.5s
    jitter = random.uniform(-0.2, 0.5)
    randomized_delay = CRAWL_DELAY_SECONDS * (1 + jitter)

    elapsed = time.time() - _last_request_time
    if elapsed < randomized_delay:
        sleep_time = randomized_delay - elapsed
        logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s (base: {CRAWL_DELAY_SECONDS}s, jitter: {jitter:+.1%})")
        time.sleep(sleep_time)

    _last_request_time = time.time()


# ==============================================================================
# Playwright Helper
# ==============================================================================

def _fetch_with_playwright(url: str, wait_for_selector: str = "li.b_algo", timeout: int = 30000) -> str:
    """
    Fetch HTML using Playwright to execute JavaScript and get rendered content with stealth mode.

    Uses anti-detection techniques to bypass bot detection:
    - Realistic viewport and screen dimensions
    - Proper locale and timezone settings
    - Disabled automation indicators
    - Random mouse movements
    - Realistic wait times

    Args:
        url: URL to fetch
        wait_for_selector: CSS selector to wait for before capturing HTML
        timeout: Maximum wait time in milliseconds

    Returns:
        Fully rendered HTML content as string

    Raises:
        Exception: If Playwright is not available or fetch fails
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed. Install with: playwright install chromium")

    logger.debug(f"Fetching with Playwright (stealth mode): {url}")

    with sync_playwright() as p:
        # Launch browser with stealth arguments
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',  # Disable automation detection
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
            ]
        )

        context = None
        try:
            # Create context with realistic MOBILE browser fingerprint (better for bot evasion)
            context = browser.new_context(
                viewport={'width': 390, 'height': 844},  # iPhone 14 Pro
                screen={'width': 390, 'height': 844},
                user_agent=USER_AGENT,
                locale='en-US',
                timezone_id='America/New_York',
                permissions=['geolocation'],
                geolocation={'longitude': -74.0060, 'latitude': 40.7128},  # NYC
                color_scheme='light',
                is_mobile=True,  # Important: identifies as mobile device
                has_touch=True,   # Mobile devices have touch
            )

            # Comprehensive JavaScript evasion - override multiple detection vectors
            context.add_init_script("""
                // 1. Core automation indicators
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });

                // 2. Mock realistic plugin array (Safari iOS doesn't expose plugins)
                Object.defineProperty(navigator, 'plugins', {
                    get: () => []  // Mobile Safari has empty plugins
                });

                // 3. Mock languages with regional variations
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });

                // 4. Hardware concurrency (mobile devices typically have 4-8 cores)
                Object.defineProperty(navigator, 'hardwareConcurrency', {
                    get: () => 6  // iPhone 14 Pro has 6-core CPU
                });

                // 5. Device memory (mobile typically 4-8GB)
                Object.defineProperty(navigator, 'deviceMemory', {
                    get: () => 6
                });

                // 6. Platform consistency (must match user agent)
                Object.defineProperty(navigator, 'platform', {
                    get: () => 'iPhone'
                });

                // 7. Mock permissions API
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );

                // 8. Battery API (mobile devices should have battery)
                Object.defineProperty(navigator, 'getBattery', {
                    value: () => Promise.resolve({
                        charging: false,
                        chargingTime: Infinity,
                        dischargingTime: 18000,  // 5 hours
                        level: 0.73
                    })
                });

                // 9. Connection API (simulate mobile network)
                Object.defineProperty(navigator, 'connection', {
                    get: () => ({
                        effectiveType: '4g',
                        downlink: 10,
                        rtt: 50,
                        saveData: false
                    })
                });

                // 10. WebGL vendor/renderer masking (prevent fingerprinting)
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) {  // UNMASKED_VENDOR_WEBGL
                        return 'Apple Inc.';
                    }
                    if (parameter === 37446) {  // UNMASKED_RENDERER_WEBGL
                        return 'Apple GPU';
                    }
                    return getParameter.call(this, parameter);
                };

                // 11. Canvas fingerprinting noise (add tiny variations)
                const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function() {
                    const context = this.getContext('2d');
                    if (context) {
                        // Add microscopic noise to prevent fingerprinting
                        const imageData = context.getImageData(0, 0, this.width, this.height);
                        for (let i = 0; i < imageData.data.length; i += 4) {
                            imageData.data[i] += Math.random() < 0.1 ? 1 : 0;
                        }
                        context.putImageData(imageData, 0, 0);
                    }
                    return originalToDataURL.apply(this, arguments);
                };

                // 12. Chrome-specific objects (not present on Safari iOS, keep for consistency)
                delete window.chrome;

                // 13. Mock ServiceWorker for more realistic browser environment
                if (!navigator.serviceWorker) {
                    Object.defineProperty(navigator, 'serviceWorker', {
                        get: () => ({
                            register: () => Promise.reject(new Error('ServiceWorker not supported')),
                            ready: Promise.reject(new Error('ServiceWorker not supported'))
                        })
                    });
                }

                // 14. Mock media devices (cameras/microphones)
                if (navigator.mediaDevices) {
                    const enumerateDevices = navigator.mediaDevices.enumerateDevices;
                    navigator.mediaDevices.enumerateDevices = function() {
                        return enumerateDevices.call(this).then(devices => {
                            // Return realistic mobile device set
                            return [
                                { deviceId: 'default', kind: 'audioinput', label: 'Microphone' },
                                { deviceId: 'default', kind: 'videoinput', label: 'Front Camera' },
                                { deviceId: 'rear', kind: 'videoinput', label: 'Back Camera' }
                            ];
                        });
                    };
                }
            """)

            page = context.new_page()

            # Add extra headers with realistic referer
            headers_with_referer = HEADERS.copy()
            headers_with_referer['Referer'] = 'https://www.bing.com/'
            headers_with_referer['Origin'] = 'https://www.bing.com'
            headers_with_referer['Sec-Fetch-Site'] = 'same-origin'
            headers_with_referer['Sec-Fetch-Mode'] = 'navigate'
            headers_with_referer['Sec-Fetch-Dest'] = 'document'
            page.set_extra_http_headers(headers_with_referer)

            # Navigate to page
            logger.debug(f"Navigating to: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)

            # Wait a bit for initial JavaScript execution (randomized 1.2-2.0s)
            initial_wait = random.randint(1200, 2000)
            logger.debug(f"Initial wait: {initial_wait}ms")
            page.wait_for_timeout(initial_wait)

            # Try to wait for search results (don't fail if not found)
            try:
                logger.debug(f"Waiting for selector: {wait_for_selector}")
                page.wait_for_selector(wait_for_selector, timeout=8000, state='attached')
                logger.debug("Search results found!")
            except Exception as e:
                logger.warning(f"Selector '{wait_for_selector}' not found: {e}")
                logger.debug("Proceeding without search results - may be empty page or bot detection")

            # Additional wait for late-loading JavaScript (randomized 1.5-3.0s)
            late_wait = random.randint(1500, 3000)
            logger.debug(f"Late-load wait: {late_wait}ms")
            page.wait_for_timeout(late_wait)

            # Simulate realistic human behavior - varied scrolling patterns
            try:
                # 1. Mouse movement simulation (move to random position)
                page.mouse.move(
                    random.randint(50, 300),
                    random.randint(100, 400),
                    steps=random.randint(5, 15)  # Gradual movement, not instant
                )
                page.wait_for_timeout(random.randint(200, 500))

                # 2. Varied scroll patterns (mimics reading behavior)
                scroll_pattern = random.choice(['quick_scan', 'slow_read', 'middle_focus'])

                if scroll_pattern == 'quick_scan':
                    # Quick scroll down and back up (skimming)
                    for _ in range(2):
                        scroll_amount = random.randint(300, 600)
                        page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                        page.wait_for_timeout(random.randint(400, 800))
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(random.randint(300, 600))

                elif scroll_pattern == 'slow_read':
                    # Slower, more deliberate scrolling (reading)
                    for _ in range(3):
                        scroll_amount = random.randint(150, 350)
                        page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                        page.wait_for_timeout(random.randint(800, 1500))  # Longer pauses
                    # Sometimes scroll back up to re-read
                    if random.random() < 0.4:
                        page.evaluate(f"window.scrollBy(0, -{random.randint(100, 300)})")
                        page.wait_for_timeout(random.randint(500, 1000))

                else:  # middle_focus
                    # Scroll to middle, pause, return
                    page.evaluate(f"window.scrollTo(0, {random.randint(400, 700)})")
                    page.wait_for_timeout(random.randint(1000, 2000))
                    # Small adjustments (fine-tuning view)
                    page.evaluate(f"window.scrollBy(0, {random.randint(-100, 100)})")
                    page.wait_for_timeout(random.randint(500, 1000))

                # 3. Random micro-movements (realistic eye scanning)
                if random.random() < 0.5:
                    page.mouse.move(
                        random.randint(100, 350),
                        random.randint(150, 500),
                        steps=random.randint(3, 8)
                    )

            except Exception as e:
                logger.debug(f"Human behavior simulation warning: {e}")

            html = page.content()
            logger.debug(f"Playwright fetch complete: {len(html)} bytes")

            # Check if we got actual results
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'lxml')
            result_count = len(soup.select('li.b_algo'))
            logger.info(f"Playwright rendered {result_count} search results")

            return html

        finally:
            if context:
                context.close()
            browser.close()


# ==============================================================================
# Query Builder
# ==============================================================================

def build_bing_query(category: str, location: str, page: int = 1) -> str:
    """
    Build a Bing search query from category and location.

    Constructs a search query string for Bing using the given service category
    and geographic location. Handles pagination parameters for multi-page crawls.

    Args:
        category: Service category (e.g., "pressure washing")
        location: Geographic location (e.g., "TX", "Peoria IL")
        page: Page number (1-indexed) for pagination

    Returns:
        Formatted query string ready for Bing search

    Example:
        >>> build_bing_query("pressure washing", "TX", page=1)
        '"pressure washing" Texas'
    """
    logger.debug(f"Building query: category={category}, location={location}, page={page}")

    # State code to full name mapping
    STATE_NAMES = {
        "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
        "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
        "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
        "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
        "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
        "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
        "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
        "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
        "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
        "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
        "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
        "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
        "WI": "Wisconsin", "WY": "Wyoming",
    }

    # Expand state code to full name if applicable
    location_expanded = STATE_NAMES.get(location.upper(), location)

    # Quote category for exact phrase matching
    query = f'"{category}" {location_expanded}'

    logger.debug(f"Built query: '{query}'")
    return query


# ==============================================================================
# Fetch Layer
# ==============================================================================

def fetch_bing_search_page(
    query: str,
    page: int = 1,
    mode: Optional[str] = None
) -> Union[str, Dict[str, Any]]:
    """
    Fetch a Bing search results page (HTML or API JSON).

    Executes an HTTP request to Bing search, with automatic mode selection
    (API vs HTML), retry logic, exponential backoff, and rate limiting.

    Args:
        query: Search query string
        page: Page number (1-indexed) for pagination
        mode: Override fetch mode ('api', 'html', or None for auto)

    Returns:
        - HTML string if using HTML mode
        - JSON dict if using API mode

    Raises:
        requests.RequestException: On network errors after retries exhausted
        ValueError: If API mode requested but no API key available

    Example:
        >>> payload = fetch_bing_search_page("pressure washing TX", page=1)
        >>> isinstance(payload, (str, dict))
        True
    """
    use_api = USE_API if mode is None else (mode == 'api')

    # Validate API mode
    if use_api and not BING_API_KEY:
        raise ValueError("API mode requested but BING_API_KEY is not set")

    logger.info(f"Fetching Bing SERP: query='{query}', page={page}, mode={'API' if use_api else 'HTML'}")

    # Apply rate limiting
    _apply_rate_limit()

    # Create HTTP session
    session = create_http_session()

    try:
        if use_api:
            # ============ API MODE ============
            # Calculate offset for pagination (0-indexed)
            offset = (page - 1) * RESULTS_PER_PAGE_OFFSET

            # Build API request
            params = {
                'q': query,
                'count': MAX_RESULTS_PER_PAGE,
                'offset': offset,
                'mkt': 'en-US',
                'safesearch': 'Moderate',
            }

            headers = {
                'Ocp-Apim-Subscription-Key': BING_API_KEY,
            }

            url = BING_API_BASE
            logger.debug(f"API request: {url}?{urlencode(params)}")

            response = session.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()

            logger.info(f"✓ Successfully fetched API page {page} ({len(response.text)} bytes)")
            return response.json()

        else:
            # ============ HTML MODE ============
            # Calculate first parameter for pagination (1, 11, 21, 31, ...)
            first = 1 + (page - 1) * RESULTS_PER_PAGE_OFFSET

            # Build HTML request
            params = {
                'q': query,
                'first': first,
            }

            url = f"{BING_BASE_URL}?{urlencode(params)}"
            logger.debug(f"HTML request: {url}")

            # Use Playwright to render JavaScript if available, otherwise fall back to simple requests
            if PLAYWRIGHT_AVAILABLE:
                logger.debug("Using Playwright to render JavaScript")
                try:
                    html = _fetch_with_playwright(url, wait_for_selector="body")
                    logger.info(f"✓ Successfully fetched HTML page {page} with Playwright ({len(html)} bytes)")
                    return html
                except Exception as e:
                    logger.warning(f"Playwright fetch failed: {e}, falling back to simple HTTP")
                    # Fall through to simple HTTP request

            # Fallback: Simple HTTP request (won't render JavaScript)
            response = session.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()

            logger.info(f"✓ Successfully fetched HTML page {page} ({len(response.text)} bytes)")
            return response.text

    except requests.Timeout as e:
        logger.error(f"Request timeout: {e}")
        raise
    except requests.HTTPError as e:
        logger.error(f"HTTP error {e.response.status_code}: {e}")
        raise
    except requests.RequestException as e:
        logger.error(f"Request failed: {e}")
        raise
    finally:
        session.close()


# ==============================================================================
# Parser
# ==============================================================================

def parse_bing_results(
    payload: Union[str, Dict[str, Any]],
    mode: str = 'html'
) -> List[Dict[str, Any]]:
    """
    Parse Bing search results into normalized discovery dicts.

    Extracts business information from raw Bing SERP payload (HTML or API JSON)
    and converts to a standardized format matching the database schema.

    Args:
        payload: Raw page payload (HTML string or API JSON dict)
        mode: Parse mode ('html' or 'api')

    Returns:
        List of normalized discovery dicts with fields:
            - name: Business name (from result title)
            - website: Canonical URL
            - domain: Extracted domain (via domain_from_url helper)
            - source: Always 'BING'
            - snippet: Optional raw snippet for enrichment

    Example:
        >>> html = '<html>...</html>'
        >>> results = parse_bing_results(html, mode='html')
        >>> len(results) > 0
        True
        >>> results[0]['source']
        'BING'
    """
    logger.debug(f"Parsing Bing results: mode={mode}, payload_type={type(payload).__name__}")

    results = []

    try:
        if mode == 'api' or isinstance(payload, dict):
            # ============ API MODE ============
            results = _parse_api_json(payload)
        else:
            # ============ HTML MODE ============
            results = _parse_html(payload)

        logger.info(f"Parsed {len(results)} results from Bing SERP")
        return results

    except Exception as e:
        logger.error(f"Error parsing Bing results: {e}", exc_info=True)
        # Never crash - return empty list
        return []


def _parse_api_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse Bing API JSON response.

    Args:
        data: API JSON response dict

    Returns:
        List of normalized discovery dicts
    """
    results = []

    # Extract web pages from API response
    web_pages = data.get('webPages', {}).get('value', [])

    for item in web_pages:
        try:
            # Extract fields
            name = item.get('name', '')
            url = item.get('url', '')
            snippet = item.get('snippet', '')

            # Skip if no URL
            if not url:
                logger.debug(f"Skipping result with no URL: {name}")
                continue

            # Skip obvious non-business results
            if _is_non_business_url(url):
                logger.debug(f"Skipping non-business URL: {url}")
                continue

            # Canonicalize URL
            try:
                canonical_url = canonicalize_url(url)
                domain = domain_from_url(canonical_url)
            except Exception as e:
                logger.warning(f"Failed to canonicalize URL '{url}': {e}")
                continue

            # Build normalized result
            result = {
                'name': _clean_title(name),
                'website': canonical_url,
                'domain': domain,
                'source': 'BING',
                'snippet': snippet,
                'discovered_at': datetime.now().isoformat(),
            }

            results.append(result)
            logger.debug(f"Parsed API result: {result['name']} - {result['domain']}")

        except Exception as e:
            logger.warning(f"Failed to parse API result: {e}")
            continue

    return results


def _parse_html(html: str) -> List[Dict[str, Any]]:
    """
    Parse Bing HTML SERP.

    Args:
        html: Raw HTML string

    Returns:
        List of normalized discovery dicts
    """
    results = []
    soup = BeautifulSoup(html, 'lxml')

    # Find organic search results
    # Bing uses various selectors for desktop AND mobile, try multiple patterns
    result_items = (
        soup.select('li.b_algo') or                    # Desktop organic results
        soup.select('ol#b_results > li') or            # Desktop list items
        soup.select('li[class*="b_algo"]') or          # Partial class match
        soup.select('.b_algo') or                      # Any element with b_algo class
        soup.select('[data-tag="web"]') or             # Mobile web results
        soup.select('.tilk') or                        # Mobile result container
        soup.select('.tile_container') or              # Another mobile pattern
        []
    )

    logger.debug(f"Found {len(result_items)} potential result items in HTML")

    for item in result_items:
        try:
            # Skip ads (typically have class containing 'ad' or data-ad attribute)
            if item.get('class') and any('ad' in str(c).lower() for c in item.get('class', [])):
                logger.debug("Skipping ad result")
                continue

            if item.get('data-ad'):
                logger.debug("Skipping sponsored result")
                continue

            # Extract title and URL
            link = item.select_one('h2 a') or item.select_one('a')

            if not link:
                logger.debug("No link found in result item")
                continue

            url = link.get('href', '')
            name = link.get_text(strip=True)

            # Skip if no URL
            if not url:
                logger.debug(f"Skipping result with no URL: {name}")
                continue

            # Skip Bing internal links
            if 'bing.com' in url.lower():
                logger.debug(f"Skipping Bing internal link: {url}")
                continue

            # Skip obvious non-business results
            if _is_non_business_url(url):
                logger.debug(f"Skipping non-business URL: {url}")
                continue

            # Extract snippet
            snippet_elem = item.select_one('p') or item.select_one('div.b_caption p')
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''

            # Canonicalize URL
            try:
                canonical_url = canonicalize_url(url)
                domain = domain_from_url(canonical_url)
            except Exception as e:
                logger.warning(f"Failed to canonicalize URL '{url}': {e}")
                continue

            # Build normalized result
            result = {
                'name': _clean_title(name),
                'website': canonical_url,
                'domain': domain,
                'source': 'BING',
                'snippet': snippet,
                'discovered_at': datetime.now().isoformat(),
            }

            results.append(result)
            logger.debug(f"Parsed HTML result: {result['name']} - {result['domain']}")

        except Exception as e:
            logger.warning(f"Failed to parse HTML result: {e}")
            continue

    return results


def _clean_title(title: str) -> str:
    """
    Clean extracted title text.

    Args:
        title: Raw title string

    Returns:
        Cleaned title string
    """
    if not title:
        return ""

    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', title)
    cleaned = cleaned.strip()

    # Remove common suffixes
    cleaned = re.sub(r'\s*[|\-–]\s*Bing$', '', cleaned, flags=re.IGNORECASE)

    return cleaned


def _is_non_business_url(url: str) -> bool:
    """
    Check if URL is obviously not a business website.

    Args:
        url: URL to check

    Returns:
        True if URL should be skipped
    """
    url_lower = url.lower()

    # Skip social media, directories, and aggregators
    non_business_domains = [
        'facebook.com', 'linkedin.com', 'twitter.com', 'instagram.com',
        'yelp.com', 'yellowpages.com', 'homeadvisor.com', 'thumbtack.com',
        'angi.com', 'bbb.org', 'manta.com', 'mapquest.com',
        'wikipedia.org', 'youtube.com', 'amazon.com', 'ebay.com',
    ]

    for domain in non_business_domains:
        if domain in url_lower:
            return True

    return False


# ==============================================================================
# Helper Functions
# ==============================================================================

def create_http_session() -> requests.Session:
    """
    Create a requests Session with retry adapter.

    Configures automatic retries with exponential backoff for transient errors.

    Returns:
        Configured requests.Session instance
    """
    session = requests.Session()

    # Configure retry strategy
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF_BASE,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )

    # Mount adapter with retry strategy
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session
