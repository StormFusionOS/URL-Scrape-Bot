#!/usr/bin/env python3
"""
Anti-detection and stealth utilities for Yellow Pages scraping.

This module provides tools to make the scraper appear more human-like and avoid detection:
- Diverse user agent rotation
- Random delays with jitter
- Viewport randomization
- Timezone randomization
- Browser fingerprint variations
"""

import random
import time
from typing import Tuple, Dict, Any


# Diverse pool of realistic user agents (Chrome, Firefox, Safari on Windows, Mac, Linux)
# Updated regularly to match current browser versions
USER_AGENT_POOL = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",

    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",

    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",

    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",

    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",

    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",

    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",

    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
]


def get_random_user_agent() -> str:
    """
    Get a random user agent from the pool.

    Returns:
        Random user agent string
    """
    return random.choice(USER_AGENT_POOL)


def get_random_viewport() -> Tuple[int, int]:
    """
    Get a random viewport size that looks realistic.

    Common desktop resolutions with slight variations to avoid fingerprinting.

    Returns:
        Tuple of (width, height)
    """
    # Common desktop resolutions
    base_resolutions = [
        (1920, 1080),  # Full HD (most common)
        (1366, 768),   # Laptop
        (1536, 864),   # Laptop
        (1440, 900),   # MacBook
        (2560, 1440),  # 2K
        (1600, 900),   # HD+
        (1280, 720),   # HD
    ]

    # Pick a base resolution
    width, height = random.choice(base_resolutions)

    # Add small random variation (-20 to +20 pixels) to avoid exact fingerprinting
    width += random.randint(-20, 20)
    height += random.randint(-20, 20)

    return (width, height)


def get_random_timezone() -> str:
    """
    Get a random US timezone.

    Returns:
        Timezone string (e.g., 'America/New_York')
    """
    us_timezones = [
        'America/New_York',      # Eastern
        'America/Chicago',       # Central
        'America/Denver',        # Mountain
        'America/Los_Angeles',   # Pacific
        'America/Phoenix',       # Arizona (no DST)
        'America/Anchorage',     # Alaska
        'Pacific/Honolulu',      # Hawaii
    ]

    return random.choice(us_timezones)


def get_random_delay(min_seconds: float = 2.0, max_seconds: float = 5.0, jitter: float = 0.5) -> float:
    """
    Get a random delay with jitter to appear more human-like.

    Args:
        min_seconds: Minimum delay in seconds
        max_seconds: Maximum delay in seconds
        jitter: Additional random jitter factor (0-1)

    Returns:
        Delay in seconds
    """
    base_delay = random.uniform(min_seconds, max_seconds)

    # Add jitter (small random variation)
    jitter_amount = random.uniform(-jitter, jitter)

    return max(0.5, base_delay + jitter_amount)


def human_delay(min_seconds: float = 2.0, max_seconds: float = 5.0, jitter: float = 0.5):
    """
    Sleep for a random human-like delay.

    Args:
        min_seconds: Minimum delay in seconds
        max_seconds: Maximum delay in seconds
        jitter: Additional random jitter factor (0-1)
    """
    delay = get_random_delay(min_seconds, max_seconds, jitter)
    time.sleep(delay)


def get_playwright_context_params() -> Dict[str, Any]:
    """
    Get randomized Playwright context parameters for anti-detection.

    Returns:
        Dict of parameters to pass to browser.new_context()
    """
    width, height = get_random_viewport()

    return {
        'user_agent': get_random_user_agent(),
        'viewport': {'width': width, 'height': height},
        'locale': 'en-US',
        'timezone_id': get_random_timezone(),
        'permissions': [],
        'geolocation': None,
        'color_scheme': random.choice(['light', 'dark', 'no-preference']),
        'device_scale_factor': random.choice([1, 1.5, 2]),  # Normal, HiDPI, Retina
    }


def get_exponential_backoff_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """
    Calculate exponential backoff delay for retry logic.

    Args:
        attempt: Attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap in seconds

    Returns:
        Delay in seconds
    """
    # Exponential: 1s, 2s, 4s, 8s, 16s, 32s, 60s (capped)
    delay = min(base_delay * (2 ** attempt), max_delay)

    # Add jitter to avoid thundering herd
    jitter = random.uniform(0, delay * 0.3)

    return delay + jitter


def get_session_break_delay() -> float:
    """
    Get a session break delay to simulate human taking a break.

    Returns:
        Delay in seconds (30-90 seconds)
    """
    # Longer break to simulate human stepping away
    base_delay = random.uniform(30, 90)

    # Add some jitter
    jitter = random.uniform(-5, 10)

    return max(30, base_delay + jitter)


def session_break():
    """
    Take a session break (30-90 seconds).
    Simulates human taking a coffee break, getting distracted, etc.
    """
    delay = get_session_break_delay()
    time.sleep(delay)


def get_human_reading_delay(content_length: int = 500) -> float:
    """
    Calculate a realistic human reading delay based on content length.

    Assumes average reading speed of ~200-300 words per minute.
    Average word is ~5 characters, so ~1000-1500 chars per minute.

    Args:
        content_length: Approximate content length in characters

    Returns:
        Delay in seconds
    """
    # Estimate reading time (chars per second)
    chars_per_second = random.uniform(17, 25)  # ~1000-1500 chars/min

    # Calculate base reading time
    base_delay = content_length / chars_per_second

    # Add randomization (people read at varying speeds)
    multiplier = random.uniform(0.7, 1.3)
    delay = base_delay * multiplier

    # Minimum 2 seconds (even short content takes time to scan)
    # Maximum 30 seconds (humans don't read THAT slowly on listings)
    delay = max(2.0, min(delay, 30.0))

    # Add small jitter
    delay += random.uniform(-0.5, 1.0)

    return max(1.0, delay)


def human_reading_delay(content_length: int = 500):
    """
    Sleep for a realistic human reading delay.

    Args:
        content_length: Approximate content length in characters
    """
    delay = get_human_reading_delay(content_length)
    time.sleep(delay)


def get_scroll_delays() -> list[float]:
    """
    Get realistic scroll delays for simulating human scrolling behavior.

    Returns:
        List of delays (typically 3-7 scroll actions)
    """
    num_scrolls = random.randint(3, 7)
    delays = []

    for _ in range(num_scrolls):
        # Each scroll takes 0.3-1.5 seconds
        delay = random.uniform(0.3, 1.5)
        delays.append(delay)

    return delays


def get_enhanced_playwright_init_scripts() -> list[str]:
    """
    Get enhanced JavaScript init scripts for better anti-detection.

    Returns:
        List of JavaScript code snippets to inject
    """
    scripts = []

    # 1. Mask WebDriver property
    scripts.append("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    # 2. Add realistic plugins
    scripts.append("""
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                return [
                    {
                        name: 'Chrome PDF Plugin',
                        filename: 'internal-pdf-viewer',
                        description: 'Portable Document Format',
                        length: 1
                    },
                    {
                        name: 'Chrome PDF Viewer',
                        filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                        description: '',
                        length: 1
                    },
                    {
                        name: 'Native Client',
                        filename: 'internal-nacl-plugin',
                        description: '',
                        length: 2
                    }
                ];
            }
        });
    """)

    # 3. Override permissions
    scripts.append("""
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    """)

    # 4. Add realistic languages
    scripts.append("""
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
    """)

    # 5. Hide automation flags
    scripts.append("""
        // Delete Chrome automation flags
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

        // Override chrome property
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
    """)

    # 6. Add realistic hardware concurrency
    scripts.append("""
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => """ + str(random.choice([2, 4, 8, 16])) + """
        });
    """)

    # 7. Add realistic device memory (if supported)
    scripts.append("""
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => """ + str(random.choice([4, 8, 16])) + """
        });
    """)

    return scripts


class SessionBreakManager:
    """
    Manages session breaks to avoid looking like a continuous bot.

    Takes breaks after every N requests to simulate human behavior.
    """

    def __init__(self, requests_per_session: int = 50):
        """
        Initialize session break manager.

        Args:
            requests_per_session: Number of requests before taking a break (default: 50)
        """
        self.requests_per_session = requests_per_session
        self.request_count = 0
        self.total_breaks = 0

    def increment(self) -> bool:
        """
        Increment request count and check if break is needed.

        Returns:
            True if break was taken, False otherwise
        """
        self.request_count += 1

        # Check if we should take a break
        if self.request_count >= self.requests_per_session:
            self._take_break()
            return True

        return False

    def _take_break(self):
        """Take a session break and reset counter."""
        delay = get_session_break_delay()
        self.total_breaks += 1

        # Log the break (if logger available)
        try:
            from runner.logging_setup import get_logger
            logger = get_logger("session_break")
            logger.info(
                f"Taking session break #{self.total_breaks} "
                f"after {self.request_count} requests ({delay:.1f}s)..."
            )
        except Exception:
            pass

        time.sleep(delay)

        # Reset counter with some randomization
        # Don't always break at exactly 50 requests
        variance = random.randint(-5, 10)
        self.requests_per_session = max(40, 50 + variance)
        self.request_count = 0

    def force_break(self):
        """Force a session break immediately."""
        self._take_break()


def randomize_operation_order(operations: list) -> list:
    """
    Randomize the order of operations to avoid predictable patterns.

    Some operations should stay in order (like authentication before requests),
    but others can be randomized to look more human.

    Args:
        operations: List of operations (strings or tuples)

    Returns:
        Shuffled list
    """
    # Create a copy to avoid modifying original
    shuffled = operations.copy()

    # Shuffle the list
    random.shuffle(shuffled)

    return shuffled
