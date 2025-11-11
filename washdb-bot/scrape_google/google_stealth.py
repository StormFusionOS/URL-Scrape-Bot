"""
Google Business Scraper - Stealth & Anti-Detection Utilities

Comprehensive anti-detection measures to avoid bot detection and blocking.

Features:
- User agent rotation (realistic, recent browsers)
- Browser fingerprinting countermeasures
- Human-like behavior simulation
- Random timing variations
- Viewport randomization
- Proper headers and locale settings

Author: washdb-bot
Date: 2025-11-10
"""

import random
import asyncio
from typing import Dict, List, Tuple
from playwright.async_api import Page, BrowserContext


# Realistic user agents (updated 2024-2025)
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",

    # Chrome on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",

    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",

    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",

    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


# Realistic viewport sizes (common desktop resolutions)
VIEWPORTS = [
    {"width": 1920, "height": 1080},  # Full HD
    {"width": 1536, "height": 864},   # Common laptop
    {"width": 1440, "height": 900},   # MacBook Pro
    {"width": 1366, "height": 768},   # Common laptop
    {"width": 2560, "height": 1440},  # 2K
    {"width": 1680, "height": 1050},  # WSXGA+
]


# Realistic screen sizes (physical display dimensions)
SCREEN_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 2560, "height": 1440},
    {"width": 1680, "height": 1050},
]


# Timezones (US-based for realistic Google Maps usage)
TIMEZONES = [
    "America/New_York",      # EST
    "America/Chicago",       # CST
    "America/Denver",        # MST
    "America/Los_Angeles",   # PST
    "America/Phoenix",       # MST (no DST)
    "America/Anchorage",     # AKST
]


# Locales (US English variants)
LOCALES = [
    "en-US",
    "en-US,en;q=0.9",
]


class StealthConfig:
    """Configuration for stealth/anti-detection measures."""

    def __init__(self):
        # Randomize user agent
        self.user_agent = random.choice(USER_AGENTS)

        # Randomize viewport
        self.viewport = random.choice(VIEWPORTS)

        # Randomize screen size (should match or be larger than viewport)
        self.screen = random.choice([s for s in SCREEN_SIZES if s["width"] >= self.viewport["width"]])

        # Randomize timezone
        self.timezone = random.choice(TIMEZONES)

        # Locale
        self.locale = random.choice(LOCALES)

        # Generate realistic headers
        self.headers = self._generate_headers()

    def _generate_headers(self) -> Dict[str, str]:
        """Generate realistic HTTP headers."""
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": self.locale,
            "Cache-Control": "max-age=0",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.user_agent,
        }


async def apply_stealth(context: BrowserContext, config: StealthConfig):
    """
    Apply stealth measures to browser context.

    Args:
        context: Playwright browser context
        config: Stealth configuration
    """
    # Set extra HTTP headers
    await context.set_extra_http_headers(config.headers)

    # Set geolocation (random US location)
    # Note: This requires permission, so we'll skip for now
    # await context.grant_permissions(["geolocation"])

    # Add init scripts to mask automation indicators
    await context.add_init_script("""
        // Override the navigator.webdriver property
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Override the navigator.plugins to make it look more realistic
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {
                    name: 'Chrome PDF Plugin',
                    filename: 'internal-pdf-viewer',
                    description: 'Portable Document Format',
                },
                {
                    name: 'Chrome PDF Viewer',
                    filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                    description: '',
                },
                {
                    name: 'Native Client',
                    filename: 'internal-nacl-plugin',
                    description: '',
                }
            ]
        });

        // Override the navigator.languages to match Accept-Language
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });

        // Make the chrome object look more realistic
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };

        // Override permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // Add toString to make functions look native
        const oldToString = Function.prototype.toString;
        Function.prototype.toString = function() {
            if (this === window.navigator.permissions.query) {
                return 'function query() { [native code] }';
            }
            return oldToString.call(this);
        };
    """)


async def human_like_delay(min_ms: int = 100, max_ms: int = 500):
    """
    Add human-like random delay.

    Args:
        min_ms: Minimum delay in milliseconds
        max_ms: Maximum delay in milliseconds
    """
    delay_ms = random.uniform(min_ms, max_ms)
    await asyncio.sleep(delay_ms / 1000)


async def random_mouse_movement(page: Page):
    """
    Simulate random mouse movements on the page.

    Args:
        page: Playwright page
    """
    try:
        viewport = page.viewport_size
        if not viewport:
            return

        # Move mouse to a few random positions
        num_movements = random.randint(2, 5)
        for _ in range(num_movements):
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)

            # Move mouse with human-like curve
            await page.mouse.move(x, y)
            await human_like_delay(50, 200)
    except Exception:
        pass  # Silently fail if mouse movement fails


async def human_like_scroll(page: Page, distance: int = None):
    """
    Simulate human-like scrolling behavior.

    Args:
        page: Playwright page
        distance: Distance to scroll (if None, scroll by random amount)
    """
    try:
        if distance is None:
            distance = random.randint(300, 800)

        # Scroll in small increments with delays (like a human)
        scroll_steps = random.randint(3, 8)
        step_size = distance // scroll_steps

        for _ in range(scroll_steps):
            await page.evaluate(f"window.scrollBy(0, {step_size})")
            await human_like_delay(100, 300)

        # Random pause after scrolling
        await human_like_delay(500, 1500)
    except Exception:
        pass  # Silently fail


async def human_like_type(page: Page, selector: str, text: str):
    """
    Type text in a human-like manner (with variable delays).

    Args:
        page: Playwright page
        selector: CSS selector for input element
        text: Text to type
    """
    element = await page.query_selector(selector)
    if not element:
        return

    await element.click()
    await human_like_delay(200, 500)

    for char in text:
        await element.type(char, delay=random.uniform(80, 200))

        # Occasionally add longer pauses (like thinking)
        if random.random() < 0.1:
            await human_like_delay(300, 800)


async def random_page_interactions(page: Page):
    """
    Perform random human-like interactions on the page.

    Args:
        page: Playwright page
    """
    # Random mouse movements
    if random.random() < 0.7:
        await random_mouse_movement(page)

    # Small random scroll
    if random.random() < 0.5:
        small_scroll = random.randint(50, 200)
        await page.evaluate(f"window.scrollBy(0, {small_scroll})")
        await human_like_delay(100, 300)


def random_delay_range(base_min: int, base_max: int, variance: float = 0.3) -> Tuple[int, int]:
    """
    Add randomness to delay ranges.

    Args:
        base_min: Base minimum delay
        base_max: Base maximum delay
        variance: Variance factor (0.0 to 1.0)

    Returns:
        Tuple of (min_delay, max_delay) with randomness applied
    """
    variance_min = base_min * variance
    variance_max = base_max * variance

    new_min = int(base_min + random.uniform(-variance_min, variance_min))
    new_max = int(base_max + random.uniform(-variance_max, variance_max))

    # Ensure min < max
    return (min(new_min, new_max), max(new_min, new_max))


async def check_for_captcha(page: Page) -> bool:
    """
    Check if a CAPTCHA is present on the page.

    Args:
        page: Playwright page

    Returns:
        True if CAPTCHA detected, False otherwise
    """
    try:
        # Check for common CAPTCHA indicators
        captcha_selectors = [
            'iframe[src*="recaptcha"]',
            'iframe[src*="captcha"]',
            '[class*="captcha"]',
            '[id*="captcha"]',
            '[class*="recaptcha"]',
            '[id*="recaptcha"]',
            'div[role="presentation"]',  # Google CAPTCHA
        ]

        for selector in captcha_selectors:
            element = await page.query_selector(selector)
            if element:
                return True

        # Check page text for CAPTCHA-related text
        page_text = await page.text_content('body') or ""
        captcha_keywords = [
            "verify you're not a robot",
            "prove you're not a robot",
            "captcha",
            "unusual traffic",
            "automated requests"
        ]

        for keyword in captcha_keywords:
            if keyword.lower() in page_text.lower():
                return True

        return False
    except Exception:
        return False


async def wait_with_jitter(seconds: int, jitter: float = 0.2):
    """
    Wait for specified seconds with random jitter.

    Args:
        seconds: Base wait time in seconds
        jitter: Jitter factor (0.0 to 1.0)
    """
    jitter_amount = seconds * jitter * random.uniform(-1, 1)
    actual_wait = seconds + jitter_amount
    await asyncio.sleep(max(0.1, actual_wait))
