#!/usr/bin/env python3
"""
Ultimate Stealth Scraper - Maximum Anti-Detection Playwright Scraper

This is the FALLBACK scraper when Selenium gets blocked by CAPTCHA/Cloudflare.
Designed with maximum stealth and human-like behavior.

Features:
- Playwright with stealth plugin
- Human-like mouse movements (bezier curves)
- Fingerprint spoofing/randomization
- Proxy rotation integration
- Random delays with human timing patterns
- Intelligent scrolling behavior
- Honeypot detection and avoidance
- Cookie/session management
- BeautifulSoup + Parsel parsing layer

Usage:
    from scripts.ultimate_stealth_scraper import UltimateStealthScraper

    async with UltimateStealthScraper() as scraper:
        result = await scraper.scrape_website("https://example.com")
"""

import os
import sys
import math
import json
import random
import asyncio
import hashlib
import logging
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from playwright_stealth import Stealth
from bs4 import BeautifulSoup
from parsel import Selector

# Setup
load_dotenv()

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner.logging_setup import get_logger

# Try to import proxy pool
try:
    from scrape_yp.proxy_pool import ProxyPool, ProxyInfo
    HAS_PROXY_POOL = True
except ImportError:
    HAS_PROXY_POOL = False

logger = get_logger("ultimate_stealth")


# ============================================================================
# CONFIGURATION - Stealth Settings
# ============================================================================

# Browser configurations to cycle through
BROWSER_CONFIGS = [
    {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "platform": "Win32",
        "language": "en-US",
        "timezone": "America/New_York"
    },
    {
        "viewport": {"width": 1536, "height": 864},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "platform": "Win32",
        "language": "en-US",
        "timezone": "America/Chicago"
    },
    {
        "viewport": {"width": 1440, "height": 900},
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "platform": "MacIntel",
        "language": "en-US",
        "timezone": "America/Los_Angeles"
    },
    {
        "viewport": {"width": 1366, "height": 768},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "platform": "Win32",
        "language": "en-US",
        "timezone": "America/Denver"
    },
    {
        "viewport": {"width": 1680, "height": 1050},
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "platform": "MacIntel",
        "language": "en-US",
        "timezone": "America/Phoenix"
    }
]

# Screen resolutions for fingerprint randomization
SCREEN_RESOLUTIONS = [
    (1920, 1080), (1536, 864), (1440, 900), (1366, 768),
    (1280, 720), (1680, 1050), (2560, 1440)
]

# Human typing speeds (chars per second) - SLOW for realism
TYPING_SPEED_MIN = 4
TYPING_SPEED_MAX = 8

# Human reaction times (seconds) - SLOW and variable
HUMAN_REACTION_MIN = 0.5
HUMAN_REACTION_MAX = 2.0

# Page load wait times - reasonable human delay
PAGE_LOAD_MIN = 2.0
PAGE_LOAD_MAX = 4.0

# Scroll behavior settings - SLOW human scrolling
SCROLL_SPEED_MIN = 150  # pixels - reasonable human scrolls
SCROLL_SPEED_MAX = 350  # People scroll in larger chunks
SCROLL_PAUSE_MIN = 0.1
SCROLL_PAUSE_MAX = 0.4

# Inter-action delays - time between different actions
ACTION_DELAY_MIN = 0.5
ACTION_DELAY_MAX = 1.5

# Reading simulation - pause to "read" content
READ_PAUSE_MIN = 1.0
READ_PAUSE_MAX = 3.0

# Mouse idle movement frequency
IDLE_MOUSE_PROBABILITY = 0.3  # 30% chance of random mouse movement

# Proxy settings
PROXY_FILE = os.getenv("PROXY_FILE", "/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/webshare_proxies.txt")

# IP Geolocation to Timezone mapping (for US proxies)
# Maps state/region codes to timezone
STATE_TO_TIMEZONE = {
    # Eastern Time
    'CT': 'America/New_York', 'DE': 'America/New_York', 'DC': 'America/New_York',
    'FL': 'America/New_York', 'GA': 'America/New_York', 'IN': 'America/Indiana/Indianapolis',
    'ME': 'America/New_York', 'MD': 'America/New_York', 'MA': 'America/New_York',
    'MI': 'America/Detroit', 'NH': 'America/New_York', 'NJ': 'America/New_York',
    'NY': 'America/New_York', 'NC': 'America/New_York', 'OH': 'America/New_York',
    'PA': 'America/New_York', 'RI': 'America/New_York', 'SC': 'America/New_York',
    'VT': 'America/New_York', 'VA': 'America/New_York', 'WV': 'America/New_York',
    # Central Time
    'AL': 'America/Chicago', 'AR': 'America/Chicago', 'IL': 'America/Chicago',
    'IA': 'America/Chicago', 'KS': 'America/Chicago', 'KY': 'America/Chicago',
    'LA': 'America/Chicago', 'MN': 'America/Chicago', 'MS': 'America/Chicago',
    'MO': 'America/Chicago', 'NE': 'America/Chicago', 'ND': 'America/Chicago',
    'OK': 'America/Chicago', 'SD': 'America/Chicago', 'TN': 'America/Chicago',
    'TX': 'America/Chicago', 'WI': 'America/Chicago',
    # Mountain Time
    'AZ': 'America/Phoenix', 'CO': 'America/Denver', 'ID': 'America/Boise',
    'MT': 'America/Denver', 'NM': 'America/Denver', 'UT': 'America/Denver',
    'WY': 'America/Denver',
    # Pacific Time
    'CA': 'America/Los_Angeles', 'NV': 'America/Los_Angeles', 'OR': 'America/Los_Angeles',
    'WA': 'America/Los_Angeles',
    # Alaska/Hawaii
    'AK': 'America/Anchorage', 'HI': 'Pacific/Honolulu',
}

# Timezone to offset mapping (for fingerprint)
TIMEZONE_OFFSETS = {
    'America/New_York': -300,      # EST/EDT
    'America/Chicago': -360,        # CST/CDT
    'America/Denver': -420,         # MST/MDT
    'America/Phoenix': -420,        # MST (no DST)
    'America/Los_Angeles': -480,    # PST/PDT
    'America/Anchorage': -540,      # AKST/AKDT
    'Pacific/Honolulu': -600,       # HST
    'America/Detroit': -300,
    'America/Indiana/Indianapolis': -300,
    'America/Boise': -420,
}

async def get_ip_timezone(page) -> tuple:
    """
    Get timezone based on current IP address.
    Returns (timezone_id, offset) or defaults if detection fails.
    """
    try:
        # Use a simple IP geolocation API
        response = await page.evaluate('''
            async () => {
                try {
                    const resp = await fetch('https://ipapi.co/json/', {method: 'GET'});
                    const data = await resp.json();
                    return {
                        timezone: data.timezone,
                        region_code: data.region_code,
                        country: data.country_code
                    };
                } catch (e) {
                    return null;
                }
            }
        ''')

        if response and response.get('timezone'):
            tz = response['timezone']
            offset = TIMEZONE_OFFSETS.get(tz, -300)
            return (tz, offset)

        # Fallback to state-based lookup
        if response and response.get('region_code'):
            state = response['region_code']
            if state in STATE_TO_TIMEZONE:
                tz = STATE_TO_TIMEZONE[state]
                offset = TIMEZONE_OFFSETS.get(tz, -300)
                return (tz, offset)
    except Exception as e:
        pass

    # Default to Eastern Time
    return ('America/New_York', -300)


# ============================================================================
# BEZIER CURVE - Human-Like Mouse Movement
# ============================================================================

def bezier_curve(t: float, points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Calculate point on a bezier curve at parameter t (0-1)."""
    n = len(points) - 1
    x = sum(
        (math.comb(n, i) * (1-t)**(n-i) * t**i * points[i][0])
        for i in range(n + 1)
    )
    y = sum(
        (math.comb(n, i) * (1-t)**(n-i) * t**i * points[i][1])
        for i in range(n + 1)
    )
    return (x, y)


def generate_human_curve(
    start: Tuple[float, float],
    end: Tuple[float, float],
    num_points: int = 50
) -> List[Tuple[float, float]]:
    """
    Generate a human-like mouse movement curve from start to end.
    Uses 4-point bezier curve with randomized control points.
    """
    # Calculate distance and generate control points with some randomness
    dx = end[0] - start[0]
    dy = end[1] - start[1]

    # Control points with human-like variance
    ctrl1 = (
        start[0] + dx * random.uniform(0.2, 0.4) + random.uniform(-50, 50),
        start[1] + dy * random.uniform(0.1, 0.3) + random.uniform(-30, 30)
    )
    ctrl2 = (
        start[0] + dx * random.uniform(0.6, 0.8) + random.uniform(-50, 50),
        start[1] + dy * random.uniform(0.7, 0.9) + random.uniform(-30, 30)
    )

    points = [start, ctrl1, ctrl2, end]

    # Generate curve points with non-uniform distribution (slower at ends)
    curve_points = []
    for i in range(num_points):
        # Use easing function for more natural movement
        t = i / (num_points - 1)
        # Ease in-out cubic
        if t < 0.5:
            t_eased = 4 * t * t * t
        else:
            t_eased = 1 - pow(-2 * t + 2, 3) / 2

        point = bezier_curve(t_eased, points)
        curve_points.append(point)

    return curve_points


def add_noise_to_path(path: List[Tuple[float, float]], noise_level: float = 2.0) -> List[Tuple[float, float]]:
    """Add small random noise to simulate hand tremor."""
    return [
        (x + random.gauss(0, noise_level), y + random.gauss(0, noise_level))
        for x, y in path
    ]


# ============================================================================
# FINGERPRINT RANDOMIZATION
# ============================================================================

@dataclass
class BrowserFingerprint:
    """Randomized browser fingerprint to avoid detection."""
    user_agent: str
    viewport_width: int
    viewport_height: int
    screen_width: int
    screen_height: int
    color_depth: int
    pixel_ratio: float
    platform: str
    language: str
    languages: List[str]
    timezone: str
    timezone_offset: int
    webgl_vendor: str
    webgl_renderer: str
    fonts: List[str]
    plugins_length: int
    hardware_concurrency: int
    device_memory: int
    touch_support: bool
    audio_context: float  # AudioContext fingerprint noise
    canvas_noise: float   # Canvas fingerprint noise

    @classmethod
    def generate_random(cls) -> 'BrowserFingerprint':
        """Generate a random but consistent browser fingerprint."""
        config = random.choice(BROWSER_CONFIGS)
        screen = random.choice(SCREEN_RESOLUTIONS)

        # Common WebGL configurations
        webgl_configs = [
            ("Intel Inc.", "Intel Iris OpenGL Engine"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA GeForce GTX 1060 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Series Direct3D11 vs_5_0 ps_5_0)"),
        ]
        webgl = random.choice(webgl_configs)

        # Common fonts
        common_fonts = [
            "Arial", "Arial Black", "Comic Sans MS", "Courier New", "Georgia",
            "Impact", "Lucida Console", "Lucida Sans Unicode", "Palatino Linotype",
            "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana", "Segoe UI"
        ]

        return cls(
            user_agent=config["user_agent"],
            viewport_width=config["viewport"]["width"],
            viewport_height=config["viewport"]["height"],
            screen_width=screen[0],
            screen_height=screen[1],
            color_depth=random.choice([24, 32]),
            pixel_ratio=random.choice([1.0, 1.25, 1.5, 2.0]),
            platform=config["platform"],
            language=config["language"],
            languages=[config["language"], "en"],
            timezone=config["timezone"],
            timezone_offset=random.choice([-480, -420, -360, -300, -240]),  # US timezones
            webgl_vendor=webgl[0],
            webgl_renderer=webgl[1],
            fonts=random.sample(common_fonts, k=random.randint(10, 14)),
            plugins_length=random.randint(3, 7),
            hardware_concurrency=random.choice([4, 6, 8, 12, 16]),
            device_memory=random.choice([4, 8, 16, 32]),
            touch_support=False,  # Desktop
            audio_context=random.uniform(0.0001, 0.0009),
            canvas_noise=random.uniform(0.0001, 0.0005)
        )


def get_fingerprint_injection_script(fingerprint: BrowserFingerprint) -> str:
    """Generate JavaScript to inject fingerprint spoofing."""
    return f"""
    // Override navigator properties
    Object.defineProperty(navigator, 'platform', {{
        get: () => '{fingerprint.platform}'
    }});

    Object.defineProperty(navigator, 'hardwareConcurrency', {{
        get: () => {fingerprint.hardware_concurrency}
    }});

    Object.defineProperty(navigator, 'deviceMemory', {{
        get: () => {fingerprint.device_memory}
    }});

    Object.defineProperty(navigator, 'languages', {{
        get: () => {fingerprint.languages}
    }});

    // Override screen properties
    Object.defineProperty(screen, 'width', {{
        get: () => {fingerprint.screen_width}
    }});

    Object.defineProperty(screen, 'height', {{
        get: () => {fingerprint.screen_height}
    }});

    Object.defineProperty(screen, 'colorDepth', {{
        get: () => {fingerprint.color_depth}
    }});

    // Spoof WebGL fingerprint
    const getParameterProxyHandler = {{
        apply: function(target, thisArg, argumentsList) {{
            const param = argumentsList[0];
            const result = Reflect.apply(target, thisArg, argumentsList);

            // UNMASKED_VENDOR_WEBGL
            if (param === 37445) {{
                return '{fingerprint.webgl_vendor}';
            }}
            // UNMASKED_RENDERER_WEBGL
            if (param === 37446) {{
                return '{fingerprint.webgl_renderer}';
            }}
            return result;
        }}
    }};

    // Canvas fingerprint noise
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {{
        const ctx = this.getContext('2d');
        if (ctx) {{
            const imageData = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < imageData.data.length; i += 4) {{
                imageData.data[i] ^= {int(fingerprint.canvas_noise * 255)};
            }}
            ctx.putImageData(imageData, 0, 0);
        }}
        return originalToDataURL.apply(this, arguments);
    }};

    // Timezone override
    const originalDateTimeFormat = Intl.DateTimeFormat;
    Intl.DateTimeFormat = function(locales, options) {{
        options = options || {{}};
        options.timeZone = '{fingerprint.timezone}';
        return new originalDateTimeFormat(locales, options);
    }};

    // Chrome detection bypass
    window.chrome = {{
        runtime: {{}},
        loadTimes: function() {{}},
        csi: function() {{}},
        app: {{}}
    }};

    // Permissions API mock
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({{ state: Notification.permission }}) :
        originalQuery(parameters)
    );

    // Remove webdriver flag
    Object.defineProperty(navigator, 'webdriver', {{
        get: () => undefined
    }});

    // Plugin spoofing
    Object.defineProperty(navigator, 'plugins', {{
        get: () => {{
            const plugins = [];
            for (let i = 0; i < {fingerprint.plugins_length}; i++) {{
                plugins.push({{
                    name: 'Plugin ' + i,
                    filename: 'plugin' + i + '.dll',
                    description: 'Plugin description ' + i,
                    length: 1
                }});
            }}
            return plugins;
        }}
    }});

    console.log('Stealth fingerprint injected');
    """


# ============================================================================
# HONEYPOT DETECTION
# ============================================================================

HONEYPOT_PATTERNS = [
    # CSS hidden elements
    "display: none",
    "visibility: hidden",
    "opacity: 0",
    "position: absolute; left: -9999px",
    "position: absolute; top: -9999px",
    "height: 0",
    "width: 0",
    "overflow: hidden",

    # Common honeypot class/id names
    "honey", "pot", "trap", "hidden", "invisible", "offscreen",
    "h-captcha", "hcaptcha", "recaptcha", "g-recaptcha"
]

HONEYPOT_FIELD_NAMES = [
    "honeypot", "hp", "trap", "email2", "email_confirm",
    "phone2", "website2", "url2", "fax", "company2"
]


def detect_honeypot(element_html: str, element_attrs: Dict) -> bool:
    """
    Detect if an element is likely a honeypot trap.
    Returns True if honeypot detected.
    """
    html_lower = element_html.lower()

    # Check for hidden CSS patterns
    for pattern in HONEYPOT_PATTERNS:
        if pattern in html_lower:
            return True

    # Check class and id names
    class_name = element_attrs.get('class', '')
    id_name = element_attrs.get('id', '')
    name = element_attrs.get('name', '')

    for pattern in HONEYPOT_FIELD_NAMES:
        if pattern in class_name.lower() or pattern in id_name.lower() or pattern in name.lower():
            return True

    # Check for autocomplete="off" with hidden styling (common honeypot technique)
    if element_attrs.get('autocomplete') == 'off':
        if 'tabindex="-1"' in html_lower or 'aria-hidden="true"' in html_lower:
            return True

    return False


# ============================================================================
# CAPTCHA DETECTION - Smart detection for ACTUAL challenge pages
# ============================================================================

# Titles that indicate a challenge page (not just mentions)
CHALLENGE_TITLES = [
    "just a moment",
    "attention required",
    "please wait",
    "checking your browser",
    "verify you are human",
    "security check",
    "access denied",
    "one more step",
    "please verify",
    "ddos protection",
    "are you a robot",
    "bot verification",
]

# URLs/elements that indicate an ACTIVE challenge (not just scripts loaded)
ACTIVE_CHALLENGE_INDICATORS = [
    "challenges.cloudflare.com",  # Cloudflare challenge iframe
    "cf-chl-bypass",              # Cloudflare challenge bypass token
    "cf_chl_opt",                 # Cloudflare challenge option
    "hcaptcha.com/captcha",       # Active hCaptcha
    "/recaptcha/api2/anchor",     # Active reCAPTCHA anchor
    "recaptcha/enterprise",       # reCAPTCHA enterprise challenge
    "g-recaptcha-response",       # reCAPTCHA response field (active)
]

# Body content patterns that indicate blocked (very short pages with these)
BLOCK_PHRASES = [
    "please complete the security check",
    "please stand by, while we are checking your browser",
    "this process is automatic",
    "you will be redirected",
    "enable javascript and cookies",
    "why do i have to complete a captcha",
    "ray id:",  # Cloudflare Ray ID on error pages
]


def detect_captcha(html: str) -> Tuple[bool, str]:
    """
    Detect if page contains an ACTUAL CAPTCHA challenge (not just scripts).
    Returns (is_captcha, captcha_type).

    Smart detection:
    1. Skip if page is large (> 50KB) - real challenges are tiny
    2. Check page title for challenge indicators
    3. Check for active challenge elements in small pages
    4. Check for block phrases in very short pages
    """
    html_lower = html.lower()
    html_size = len(html)

    # CRITICAL: Real challenge pages are TINY (usually < 20KB)
    # If page is large, it's definitely not a challenge - it's real content
    # that might just mention captcha/cloudflare
    if html_size > 50000:  # 50KB
        return False, None

    # Extract title
    title_match = html_lower.find('<title>')
    title_end = html_lower.find('</title>')
    title = ""
    if title_match != -1 and title_end != -1:
        title = html_lower[title_match+7:title_end].strip()

    # Check 1: Challenge page title (most reliable indicator)
    for challenge_title in CHALLENGE_TITLES:
        if challenge_title in title:
            # Determine type from page content
            if "cloudflare" in html_lower or "cf-" in html_lower:
                return True, "cloudflare"
            elif "hcaptcha" in html_lower:
                return True, "hcaptcha"
            elif "recaptcha" in html_lower:
                return True, "recaptcha"
            else:
                return True, "generic"

    # Check 2: Active challenge elements (only on small pages < 30KB)
    if html_size < 30000:
        for indicator in ACTIVE_CHALLENGE_INDICATORS:
            if indicator in html_lower:
                if "cloudflare" in indicator or "cf-" in indicator:
                    return True, "cloudflare"
                elif "hcaptcha" in indicator:
                    return True, "hcaptcha"
                elif "recaptcha" in indicator:
                    return True, "recaptcha"
                else:
                    return True, "generic"

    # Check 3: Block phrases on VERY SHORT pages (< 10KB)
    if html_size < 10000:
        for phrase in BLOCK_PHRASES:
            if phrase in html_lower:
                if "cloudflare" in html_lower or "ray id:" in html_lower:
                    return True, "cloudflare"
                elif "hcaptcha" in html_lower:
                    return True, "hcaptcha"
                elif "recaptcha" in html_lower:
                    return True, "recaptcha"
                else:
                    return True, "generic"

    # No challenge detected
    return False, None


# ============================================================================
# PARSING LAYER - BeautifulSoup + Parsel
# ============================================================================

@dataclass
class ParsedContent:
    """Parsed content from a webpage."""
    url: str
    title: str
    text_content: str
    phone_numbers: List[str]
    email_addresses: List[str]
    business_name: Optional[str]
    address: Optional[str]
    services: List[str]
    social_links: Dict[str, str]
    internal_links: List[str]
    external_links: List[str]
    meta_description: Optional[str]
    structured_data: List[Dict]
    raw_html: str
    soup: BeautifulSoup
    selector: Selector


class ContentParser:
    """Advanced content parser using BeautifulSoup + Parsel."""

    # Regex patterns
    PHONE_PATTERNS = [
        r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        r'\d{3}[-.\s]\d{3}[-.\s]\d{4}',
        r'\+1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        r'1[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}'
    ]

    EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    def __init__(self, html: str, url: str):
        self.html = html
        self.url = url
        self.soup = BeautifulSoup(html, 'lxml')
        self.selector = Selector(text=html)
        self.parsed_url = urlparse(url)
        self.base_domain = self.parsed_url.netloc

    def parse(self) -> ParsedContent:
        """Parse all content from the page."""
        return ParsedContent(
            url=self.url,
            title=self._extract_title(),
            text_content=self._extract_text(),
            phone_numbers=self._extract_phones(),
            email_addresses=self._extract_emails(),
            business_name=self._extract_business_name(),
            address=self._extract_address(),
            services=self._extract_services(),
            social_links=self._extract_social_links(),
            internal_links=self._extract_internal_links(),
            external_links=self._extract_external_links(),
            meta_description=self._extract_meta_description(),
            structured_data=self._extract_structured_data(),
            raw_html=self.html,
            soup=self.soup,
            selector=self.selector
        )

    def _extract_title(self) -> str:
        """Extract page title."""
        title = self.soup.find('title')
        if title:
            return title.get_text(strip=True)

        # Try OG title
        og_title = self.soup.find('meta', property='og:title')
        if og_title:
            return og_title.get('content', '')

        # Try H1
        h1 = self.soup.find('h1')
        if h1:
            return h1.get_text(strip=True)

        return ''

    def _extract_text(self) -> str:
        """Extract visible text content."""
        # Remove script and style elements
        for element in self.soup(['script', 'style', 'noscript', 'iframe']):
            element.decompose()

        return self.soup.get_text(separator=' ', strip=True)

    def _extract_phones(self) -> List[str]:
        """Extract phone numbers using Parsel."""
        import re
        phones = set()

        for pattern in self.PHONE_PATTERNS:
            matches = self.selector.re(pattern)
            phones.update(matches)

        # Also check tel: links
        tel_links = self.selector.css('a[href^="tel:"]::attr(href)').getall()
        for tel in tel_links:
            phone = tel.replace('tel:', '').replace('+1', '').strip()
            phones.add(phone)

        return list(phones)

    def _extract_emails(self) -> List[str]:
        """Extract email addresses."""
        import re
        emails = set()

        matches = re.findall(self.EMAIL_PATTERN, self.html)
        emails.update(matches)

        # Check mailto: links
        mailto_links = self.selector.css('a[href^="mailto:"]::attr(href)').getall()
        for mailto in mailto_links:
            email = mailto.replace('mailto:', '').split('?')[0].strip()
            emails.add(email)

        # Filter out common false positives
        filtered = [e for e in emails if not any(x in e.lower() for x in ['example', 'test', 'email@'])]

        return list(filtered)

    def _extract_business_name(self) -> Optional[str]:
        """Extract business name from structured data or meta tags."""
        # Try JSON-LD
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0] if data else {}
                if data.get('name'):
                    return data['name']
                if data.get('legalName'):
                    return data['legalName']
            except:
                pass

        # Try OG site name
        og_site = self.soup.find('meta', property='og:site_name')
        if og_site:
            return og_site.get('content')

        return None

    def _extract_address(self) -> Optional[str]:
        """Extract address from structured data or schema markup."""
        # Try schema.org address
        address = self.selector.css('[itemprop="address"]::text').get()
        if address:
            return address.strip()

        # Try JSON-LD
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0] if data else {}
                if data.get('address'):
                    addr = data['address']
                    if isinstance(addr, str):
                        return addr
                    elif isinstance(addr, dict):
                        parts = [
                            addr.get('streetAddress', ''),
                            addr.get('addressLocality', ''),
                            addr.get('addressRegion', ''),
                            addr.get('postalCode', '')
                        ]
                        return ', '.join(p for p in parts if p)
            except:
                pass

        return None

    def _extract_services(self) -> List[str]:
        """Extract services from page content."""
        services = []

        # Look in common service containers
        service_selectors = [
            '.services li', '#services li', '[class*="service"] li',
            '.service-item', '.service-card', '[class*="service-list"] li'
        ]

        for sel in service_selectors:
            items = self.selector.css(f'{sel}::text').getall()
            services.extend([s.strip() for s in items if s.strip()])

        return list(set(services))

    def _extract_social_links(self) -> Dict[str, str]:
        """Extract social media links."""
        socials = {}
        social_domains = {
            'facebook.com': 'facebook',
            'twitter.com': 'twitter',
            'x.com': 'twitter',
            'instagram.com': 'instagram',
            'linkedin.com': 'linkedin',
            'youtube.com': 'youtube',
            'tiktok.com': 'tiktok',
            'yelp.com': 'yelp',
            'google.com/maps': 'google_maps'
        }

        for link in self.soup.find_all('a', href=True):
            href = link['href']
            for domain, name in social_domains.items():
                if domain in href and name not in socials:
                    socials[name] = href
                    break

        return socials

    def _extract_internal_links(self) -> List[str]:
        """Extract internal links."""
        internal = set()

        for link in self.soup.find_all('a', href=True):
            href = link['href']
            absolute = urljoin(self.url, href)
            parsed = urlparse(absolute)

            if parsed.netloc == self.base_domain:
                internal.add(absolute)

        return list(internal)

    def _extract_external_links(self) -> List[str]:
        """Extract external links."""
        external = set()

        for link in self.soup.find_all('a', href=True):
            href = link['href']
            if href.startswith('http'):
                parsed = urlparse(href)
                if parsed.netloc != self.base_domain:
                    external.add(href)

        return list(external)

    def _extract_meta_description(self) -> Optional[str]:
        """Extract meta description."""
        meta = self.soup.find('meta', {'name': 'description'})
        if meta:
            return meta.get('content')

        # Try OG description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc:
            return og_desc.get('content')

        return None

    def _extract_structured_data(self) -> List[Dict]:
        """Extract JSON-LD structured data."""
        import json
        data = []

        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                parsed = json.loads(script.string)
                if isinstance(parsed, list):
                    data.extend(parsed)
                else:
                    data.append(parsed)
            except:
                pass

        return data


# ============================================================================
# MAIN SCRAPER CLASS
# ============================================================================

class UltimateStealthScraper:
    """
    Ultimate stealth web scraper with maximum anti-detection.
    Use as fallback when Selenium gets blocked.

    SLOW MODE by default:
    - Headed browser (visible) for maximum stealth
    - Human-like delays between all actions
    - IP-matched timezone
    - Random mouse movements and scrolling
    """

    def __init__(
        self,
        headless: bool = False,  # HEADED by default for max stealth
        use_proxy: bool = False,
        proxy_file: str = None,
        page_timeout: int = 60000,   # Longer timeout for slow mode
        navigation_timeout: int = 90000  # Longer navigation timeout
    ):
        self.headless = headless
        self.use_proxy = use_proxy
        self.proxy_file = proxy_file or PROXY_FILE
        self.page_timeout = page_timeout
        self.navigation_timeout = navigation_timeout

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.fingerprint: Optional[BrowserFingerprint] = None
        self.proxy_pool: Optional['ProxyPool'] = None
        self.current_proxy: Optional['ProxyInfo'] = None

        # Session tracking
        self.session_id = hashlib.md5(str(datetime.now()).encode()).hexdigest()[:8]
        self.requests_made = 0
        self.captcha_count = 0
        self.success_count = 0

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Initialize the browser with stealth settings and IP-matched timezone."""
        logger.info(f"[{self.session_id}] Starting Ultimate Stealth Scraper (HEADED, SLOW MODE)...")

        # Initialize proxy pool if enabled
        if self.use_proxy and HAS_PROXY_POOL:
            try:
                self.proxy_pool = ProxyPool(self.proxy_file)
                logger.info(f"[{self.session_id}] Loaded {len(self.proxy_pool.proxies)} proxies")
            except Exception as e:
                logger.warning(f"[{self.session_id}] Failed to load proxies: {e}")
                self.use_proxy = False

        # Generate initial fingerprint
        self.fingerprint = BrowserFingerprint.generate_random()

        # Start Playwright
        self.playwright = await async_playwright().start()

        # Browser launch args for stealth
        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--disable-dev-shm-usage',
            '--disable-browser-side-navigation',
            '--no-first-run',
            '--no-service-autorun',
            '--no-default-browser-check',
            '--ignore-certificate-errors',
            '--disable-extensions',
            '--disable-popup-blocking',
            f'--window-size={self.fingerprint.viewport_width},{self.fingerprint.viewport_height}'
        ]

        # Get proxy if enabled
        proxy_config = None
        if self.use_proxy and self.proxy_pool:
            self.current_proxy = self.proxy_pool.get_proxy(strategy="health_based")
            if self.current_proxy:
                proxy_config = self.current_proxy.to_playwright_format()
                logger.info(f"[{self.session_id}] Using proxy: {self.current_proxy.host}:{self.current_proxy.port}")

        # Launch browser (HEADED by default for maximum stealth)
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
            slow_mo=50  # Add 50ms delay between actions for more human-like behavior
        )

        # Step 1: Create temporary context to detect IP timezone
        logger.info(f"[{self.session_id}] Detecting IP timezone for fingerprint matching...")
        temp_context = await self.browser.new_context(
            proxy=proxy_config if proxy_config else None,
            ignore_https_errors=True
        )
        temp_page = await temp_context.new_page()

        # Detect timezone based on IP
        detected_tz, detected_offset = await get_ip_timezone(temp_page)
        logger.info(f"[{self.session_id}] Detected timezone: {detected_tz} (offset: {detected_offset})")

        # Close temp context
        await temp_page.close()
        await temp_context.close()

        # Step 2: Update fingerprint with matched timezone
        self.fingerprint.timezone = detected_tz
        self.fingerprint.timezone_offset = detected_offset

        # Step 3: Create main context with correct timezone
        context_options = {
            'viewport': {
                'width': self.fingerprint.viewport_width,
                'height': self.fingerprint.viewport_height
            },
            'user_agent': self.fingerprint.user_agent,
            'locale': self.fingerprint.language,
            'timezone_id': self.fingerprint.timezone,  # Now matches IP!
            'color_scheme': 'light',
            'ignore_https_errors': True
        }

        if proxy_config:
            context_options['proxy'] = proxy_config

        self.context = await self.browser.new_context(**context_options)

        # Create page
        self.page = await self.context.new_page()

        # Apply stealth with matched settings
        stealth = Stealth(
            navigator_platform_override=self.fingerprint.platform,
            navigator_languages_override=(self.fingerprint.language, "en"),
            webgl_vendor_override=self.fingerprint.webgl_vendor,
            webgl_renderer_override=self.fingerprint.webgl_renderer
        )
        await stealth.apply_stealth_async(self.page)

        # Inject fingerprint script with matched timezone
        await self.page.add_init_script(get_fingerprint_injection_script(self.fingerprint))

        # Set timeouts (longer for slow mode)
        self.page.set_default_timeout(self.page_timeout)
        self.page.set_default_navigation_timeout(self.navigation_timeout)

        logger.info(f"[{self.session_id}] Browser ready!")
        logger.info(f"[{self.session_id}]   Fingerprint: {self.fingerprint.user_agent[:50]}...")
        logger.info(f"[{self.session_id}]   Timezone: {self.fingerprint.timezone} (matches IP)")

    async def close(self):
        """Close browser and cleanup."""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        logger.info(
            f"[{self.session_id}] Session closed - "
            f"Requests: {self.requests_made}, Success: {self.success_count}, CAPTCHAs: {self.captcha_count}"
        )

    async def human_delay(self, min_sec: float = None, max_sec: float = None):
        """Wait with human-like random delay."""
        min_sec = min_sec or HUMAN_REACTION_MIN
        max_sec = max_sec or HUMAN_REACTION_MAX

        # Use beta distribution for more human-like timing (peak in middle)
        delay = min_sec + (max_sec - min_sec) * random.betavariate(2, 2)
        await asyncio.sleep(delay)

        # Random chance to do idle mouse movement while waiting
        if random.random() < IDLE_MOUSE_PROBABILITY:
            await self.idle_mouse_wiggle()

    async def idle_mouse_wiggle(self):
        """Small random mouse movements like a real user's hand."""
        if not self.page:
            return

        # Small random movements (as if hand is resting on mouse)
        for _ in range(random.randint(2, 5)):
            dx = random.gauss(0, 15)  # Small horizontal drift
            dy = random.gauss(0, 10)  # Small vertical drift
            try:
                current_x = self.fingerprint.viewport_width / 2 + dx
                current_y = self.fingerprint.viewport_height / 2 + dy
                await self.page.mouse.move(current_x, current_y)
                await asyncio.sleep(random.uniform(0.05, 0.15))
            except:
                pass

    async def simulate_reading(self, duration: float = None):
        """Simulate a human reading content - pauses with occasional mouse movements."""
        if duration is None:
            duration = random.uniform(READ_PAUSE_MIN, READ_PAUSE_MAX)

        logger.debug(f"Simulating reading for {duration:.1f}s")

        elapsed = 0
        while elapsed < duration:
            # Wait a bit
            wait_time = random.uniform(0.5, 1.5)
            await asyncio.sleep(wait_time)
            elapsed += wait_time

            # Random mouse micro-movements (like following text with eyes/cursor)
            if random.random() < 0.4:
                await self.idle_mouse_wiggle()

    async def random_mouse_wander(self):
        """Move mouse to random position on page like browsing user."""
        if not self.page:
            return

        # Pick random position in viewport
        x = random.randint(100, self.fingerprint.viewport_width - 100)
        y = random.randint(100, self.fingerprint.viewport_height - 100)

        await self.human_mouse_move(x, y)
        await asyncio.sleep(random.uniform(0.2, 0.8))

    async def human_mouse_move(self, x: float, y: float):
        """Move mouse to position with human-like bezier curve - SLOW and realistic."""
        if not self.page:
            return

        # Get current position (default to center)
        current_x = self.fingerprint.viewport_width / 2
        current_y = self.fingerprint.viewport_height / 2

        # Generate human-like path with enough points for smooth movement
        path = generate_human_curve((current_x, current_y), (x, y), num_points=30)
        path = add_noise_to_path(path, noise_level=2.0)  # Subtle hand tremor

        # Move through path points - realistic speed
        for point in path:
            await self.page.mouse.move(point[0], point[1])
            await asyncio.sleep(random.uniform(0.005, 0.012))  # 5-12ms between moves

    async def human_click(self, selector: str):
        """Click element with human-like behavior."""
        if not self.page:
            return

        element = await self.page.query_selector(selector)
        if not element:
            return

        # Get element bounding box
        box = await element.bounding_box()
        if not box:
            return

        # Random point within element
        x = box['x'] + box['width'] * random.uniform(0.2, 0.8)
        y = box['y'] + box['height'] * random.uniform(0.2, 0.8)

        # Move to element
        await self.human_mouse_move(x, y)
        await self.human_delay(0.1, 0.3)

        # Click
        await self.page.mouse.click(x, y)
        await self.human_delay()

    async def human_scroll(self, direction: str = "down", amount: int = None):
        """Scroll with human-like behavior."""
        if not self.page:
            return

        amount = amount or random.randint(SCROLL_SPEED_MIN, SCROLL_SPEED_MAX)

        if direction == "down":
            delta = amount
        else:
            delta = -amount

        # Scroll in small increments
        steps = random.randint(3, 8)
        step_amount = delta // steps

        for _ in range(steps):
            await self.page.mouse.wheel(0, step_amount)
            await asyncio.sleep(random.uniform(0.02, 0.08))

        await self.human_delay(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX)

    async def human_type(self, selector: str, text: str):
        """Type text with human-like timing."""
        if not self.page:
            return

        # Click field first
        await self.human_click(selector)
        await self.human_delay(0.2, 0.4)

        # Type character by character
        for char in text:
            await self.page.keyboard.type(char)

            # Variable delay between keystrokes
            base_delay = 1.0 / random.uniform(TYPING_SPEED_MIN, TYPING_SPEED_MAX)

            # Sometimes pause longer (thinking)
            if random.random() < 0.05:
                base_delay += random.uniform(0.2, 0.5)

            await asyncio.sleep(base_delay)

    async def smart_scroll_page(self):
        """Scroll through page in a SLOW, human-like way to trigger lazy loading."""
        if not self.page:
            return

        logger.debug("Starting slow human-like page scroll...")

        # Get page height
        height = await self.page.evaluate("document.body.scrollHeight")
        viewport_height = self.fingerprint.viewport_height

        # Initial pause to "look at" the top of the page
        await self.simulate_reading(random.uniform(2.0, 4.0))

        # Random mouse movement before scrolling
        await self.random_mouse_wander()

        current = 0
        scroll_count = 0
        max_scrolls = 15  # Limit total scrolls - covers most page content

        while current < height and scroll_count < max_scrolls:
            scroll_count += 1

            # Larger scroll amounts for faster but still realistic behavior
            scroll_amount = random.randint(SCROLL_SPEED_MIN, SCROLL_SPEED_MAX)

            await self.human_scroll("down", scroll_amount)
            current += scroll_amount

            # Occasionally pause to "read" content (25% chance, shorter pauses)
            if random.random() < 0.25:
                await self.simulate_reading(random.uniform(0.5, 1.5))

            # Random mouse movements while scrolling (15% chance)
            if random.random() < 0.15:
                await self.random_mouse_wander()

            # Sometimes scroll back up a bit (like re-reading) - 5% chance
            if random.random() < 0.05 and current > viewport_height:
                back_amount = random.randint(50, 150)
                await self.human_scroll("up", back_amount)
                current -= back_amount
                await self.human_delay(0.3, 0.8)

            # Update height in case of lazy loading
            height = await self.page.evaluate("document.body.scrollHeight")

            # Add variable delay between scroll actions
            await asyncio.sleep(random.uniform(0.15, 0.4))

        logger.debug(f"Scroll complete after {scroll_count} scroll actions")

        # Quick pause at bottom
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # Fast scroll back to top (just to reset position)
        logger.debug("Scrolling back to top...")
        await self.page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(random.uniform(0.2, 0.5))

    async def scrape_website(self, url: str, scroll: bool = True) -> Dict[str, Any]:
        """
        Scrape a website with full stealth measures.

        Returns dict with:
        - success: bool
        - url: str
        - final_url: str (after redirects)
        - content: ParsedContent or None
        - captcha_detected: bool
        - captcha_type: str or None
        - error: str or None
        - html: str (raw HTML)
        """
        self.requests_made += 1

        result = {
            "success": False,
            "url": url,
            "final_url": None,
            "content": None,
            "captcha_detected": False,
            "captcha_type": None,
            "error": None,
            "html": None
        }

        try:
            logger.info(f"[{self.session_id}] Scraping: {url}")

            # Random pre-navigation delay (human thinking before clicking)
            await self.human_delay(1.0, 2.5)

            # Navigate with domcontentloaded (faster, more reliable)
            response = await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Try to wait for networkidle, but don't fail if it times out
            # (modern sites often have continuous network activity)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                logger.debug(f"[{self.session_id}] Network didn't go idle, continuing anyway...")

            # Human-like pause to let page render and "look at" it
            await self.human_delay(PAGE_LOAD_MIN, PAGE_LOAD_MAX)

            # Extra wait for JS-heavy sites (Cloudflare, React, etc.)
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # Move mouse around like a real user arriving on page
            await self.random_mouse_wander()

            # Get final URL
            result["final_url"] = self.page.url

            # Get HTML
            html = await self.page.content()
            result["html"] = html

            # Check for CAPTCHA
            is_captcha, captcha_type = detect_captcha(html)
            if is_captcha:
                logger.warning(f"[{self.session_id}] CAPTCHA detected: {captcha_type}")
                result["captcha_detected"] = True
                result["captcha_type"] = captcha_type
                result["error"] = f"captcha_{captcha_type}"
                self.captcha_count += 1

                # Report proxy failure if using proxies
                if self.current_proxy and self.proxy_pool:
                    self.proxy_pool.report_failure(self.current_proxy, f"captcha_{captcha_type}")

                return result

            # Smart scroll to trigger lazy loading
            if scroll:
                await self.smart_scroll_page()
                # Re-get HTML after scrolling
                html = await self.page.content()
                result["html"] = html

            # Parse content
            parser = ContentParser(html, result["final_url"])
            result["content"] = parser.parse()

            result["success"] = True
            self.success_count += 1

            # Report proxy success if using proxies
            if self.current_proxy and self.proxy_pool:
                self.proxy_pool.report_success(self.current_proxy)

            logger.info(f"[{self.session_id}] Success: {result['final_url']}")

        except Exception as e:
            error_msg = str(e)
            result["error"] = error_msg
            logger.error(f"[{self.session_id}] Error scraping {url}: {error_msg}")

            # Report proxy failure
            if self.current_proxy and self.proxy_pool:
                self.proxy_pool.report_failure(self.current_proxy, "error")

        return result

    async def scrape_multiple_pages(
        self,
        base_url: str,
        max_pages: int = 5
    ) -> Dict[str, Any]:
        """
        Scrape base URL and discover/scrape internal pages.

        Returns dict with:
        - base_result: main page result
        - additional_pages: list of additional page results
        - all_phones: combined phone numbers
        - all_emails: combined email addresses
        """
        # Scrape base page
        base_result = await self.scrape_website(base_url)

        results = {
            "base_result": base_result,
            "additional_pages": [],
            "all_phones": set(),
            "all_emails": set()
        }

        if base_result["success"] and base_result["content"]:
            # Collect phones and emails
            results["all_phones"].update(base_result["content"].phone_numbers)
            results["all_emails"].update(base_result["content"].email_addresses)

            # Find interesting internal links
            internal_links = base_result["content"].internal_links
            priority_pages = []

            for link in internal_links:
                link_lower = link.lower()
                if any(kw in link_lower for kw in ['contact', 'about', 'service', 'team']):
                    priority_pages.append(link)

            # Scrape priority pages
            pages_scraped = 0
            for page_url in priority_pages[:max_pages - 1]:
                if pages_scraped >= max_pages - 1:
                    break

                # Random delay between pages
                await self.human_delay(2.0, 5.0)

                page_result = await self.scrape_website(page_url, scroll=False)
                results["additional_pages"].append(page_result)

                if page_result["success"] and page_result["content"]:
                    results["all_phones"].update(page_result["content"].phone_numbers)
                    results["all_emails"].update(page_result["content"].email_addresses)

                pages_scraped += 1

        # Convert sets to lists
        results["all_phones"] = list(results["all_phones"])
        results["all_emails"] = list(results["all_emails"])

        return results

    async def rotate_proxy(self):
        """Rotate to a new proxy."""
        if not self.use_proxy or not self.proxy_pool:
            return False

        new_proxy = self.proxy_pool.get_proxy(strategy="health_based")
        if not new_proxy or new_proxy == self.current_proxy:
            return False

        logger.info(f"[{self.session_id}] Rotating proxy to: {new_proxy.host}:{new_proxy.port}")

        # Need to create new context with new proxy
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()

        self.current_proxy = new_proxy

        context_options = {
            'viewport': {
                'width': self.fingerprint.viewport_width,
                'height': self.fingerprint.viewport_height
            },
            'user_agent': self.fingerprint.user_agent,
            'proxy': new_proxy.to_playwright_format()
        }

        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()
        await self._apply_stealth()
        await self.page.add_init_script(get_fingerprint_injection_script(self.fingerprint))

        return True

    async def _apply_stealth(self):
        """Apply stealth settings to current page."""
        stealth = Stealth(
            navigator_platform_override=self.fingerprint.platform,
            navigator_languages_override=(self.fingerprint.language, "en"),
            webgl_vendor_override=self.fingerprint.webgl_vendor,
            webgl_renderer_override=self.fingerprint.webgl_renderer
        )
        await stealth.apply_stealth_async(self.page)

    async def rotate_fingerprint(self):
        """Rotate browser fingerprint (requires browser restart)."""
        logger.info(f"[{self.session_id}] Rotating fingerprint...")

        self.fingerprint = BrowserFingerprint.generate_random()

        # Close current context and page
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()

        # Create new context with new fingerprint
        context_options = {
            'viewport': {
                'width': self.fingerprint.viewport_width,
                'height': self.fingerprint.viewport_height
            },
            'user_agent': self.fingerprint.user_agent,
            'locale': self.fingerprint.language,
            'timezone_id': self.fingerprint.timezone
        }

        if self.current_proxy:
            context_options['proxy'] = self.current_proxy.to_playwright_format()

        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()
        await self._apply_stealth()
        await self.page.add_init_script(get_fingerprint_injection_script(self.fingerprint))

        logger.info(f"[{self.session_id}] New fingerprint: {self.fingerprint.user_agent[:50]}...")


# ============================================================================
# QUEUE INTEGRATION FOR BLOCKED SITES
# ============================================================================

async def process_blocked_queue(engine, batch_size: int = 10, continuous: bool = False):
    """
    Process sites that were blocked by CAPTCHA and flagged for ultimate scraper.

    Reads from companies table where:
    - block_type contains 'captcha' or 'cloudflare'
    - next_retry_at has passed

    Updates standardized_name on success.

    Args:
        engine: SQLAlchemy engine
        batch_size: Number of companies to process per batch
        continuous: If True, run continuously. If False, process one batch and exit.
    """
    from sqlalchemy import create_engine, text

    logger.info("=" * 60)
    logger.info("ULTIMATE STEALTH SCRAPER - BLOCKED QUEUE PROCESSOR")
    logger.info(f"Mode: {'Continuous' if continuous else 'Single batch'}")
    logger.info(f"Batch size: {batch_size}")
    logger.info("=" * 60)

    total_success = 0
    total_blocked = 0
    batches_processed = 0

    async with UltimateStealthScraper(headless=False, use_proxy=False) as scraper:
        while True:
            with engine.connect() as conn:
                # Get blocked companies due for retry
                # Matches block types from standardization_service_browser.py:
                # - 'cloudflare' - Cloudflare challenge
                # - 'captcha' - Generic CAPTCHA (reCAPTCHA, hCaptcha)
                # - 'blocked' - Other bot blocks
                # - 'recaptcha' - Specific reCAPTCHA (from detect_captcha_or_block)
                # - 'hcaptcha' - Specific hCaptcha
                result = conn.execute(text('''
                    SELECT id, name, website, block_type
                    FROM companies
                    WHERE standardized_name IS NULL
                      AND block_type IN ('cloudflare', 'captcha', 'blocked', 'recaptcha', 'hcaptcha')
                      AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                      AND (domain_status IS NULL OR domain_status != 'dead')
                    ORDER BY last_block_at ASC NULLS FIRST
                    LIMIT :limit
                '''), {'limit': batch_size})

                companies = list(result)

            if not companies:
                if continuous:
                    logger.info("No blocked companies in queue. Sleeping 5 minutes...")
                    await asyncio.sleep(300)  # 5 minutes
                    continue
                else:
                    logger.info("No blocked companies in queue")
                    break

            logger.info(f"Processing batch of {len(companies)} blocked companies...")
            batches_processed += 1

            batch_success = 0
            batch_blocked = 0

            for company in companies:
                company_id = company[0]
                name = company[1]
                website = company[2]
                block_type = company[3]

                logger.info(f"Processing: {name} ({website}) - prev block: {block_type}")

                try:
                    # Scrape with ultimate scraper
                    result = await scraper.scrape_multiple_pages(website, max_pages=3)

                    if result["base_result"]["captcha_detected"]:
                        logger.warning(f"Still blocked by {result['base_result']['captcha_type']}")
                        batch_blocked += 1

                        # Update retry schedule with longer backoff
                        with engine.connect() as conn:
                            conn.execute(text('''
                                UPDATE companies
                                SET last_block_at = NOW(),
                                    block_count = COALESCE(block_count, 0) + 1,
                                    next_retry_at = NOW() + INTERVAL '1 week'
                                WHERE id = :id
                            '''), {'id': company_id})
                            conn.commit()

                        # Rotate fingerprint after CAPTCHA
                        await scraper.rotate_fingerprint()

                    elif result["base_result"]["success"]:
                        logger.info(f"SUCCESS! Found {len(result['all_phones'])} phones, {len(result['all_emails'])} emails")
                        batch_success += 1

                        # Extract business name from content
                        content = result["base_result"]["content"]
                        extracted_name = content.business_name or content.title

                        # Update company with scraped data
                        with engine.connect() as conn:
                            conn.execute(text('''
                                UPDATE companies
                                SET parse_metadata = :metadata,
                                    block_type = NULL,
                                    block_count = 0,
                                    last_block_at = NULL,
                                    next_retry_at = NULL,
                                    standardization_attempts = COALESCE(standardization_attempts, 0) + 1
                                WHERE id = :id
                            '''), {
                                'id': company_id,
                                'metadata': json.dumps({
                                    'phones': result['all_phones'],
                                    'emails': result['all_emails'],
                                    'business_name': extracted_name,
                                    'scraped_by': 'ultimate_stealth'
                                })
                            })
                            conn.commit()

                    else:
                        logger.warning(f"Failed: {result['base_result']['error']}")

                except Exception as e:
                    logger.error(f"Error processing {company_id}: {e}")

                # Delay between companies
                await asyncio.sleep(random.uniform(5, 10))

            total_success += batch_success
            total_blocked += batch_blocked

            logger.info(f"Batch {batches_processed} complete: {batch_success} success, {batch_blocked} still blocked")
            logger.info(f"Running totals: {total_success} success, {total_blocked} blocked")

            if not continuous:
                break

            # Brief pause between batches
            await asyncio.sleep(30)

    logger.info("=" * 60)
    logger.info("ULTIMATE STEALTH SCRAPER SHUTDOWN")
    logger.info(f"Total batches: {batches_processed}")
    logger.info(f"Total success: {total_success}")
    logger.info(f"Total still blocked: {total_blocked}")
    logger.info("=" * 60)


# ============================================================================
# CLI INTERFACE
# ============================================================================

async def main():
    """CLI interface for testing the scraper."""
    import argparse

    parser = argparse.ArgumentParser(description='Ultimate Stealth Scraper')
    parser.add_argument('url', nargs='?', help='URL to scrape')
    parser.add_argument('--process-queue', action='store_true', help='Process blocked queue')
    parser.add_argument('--continuous', action='store_true', help='Run continuously (for systemd service)')
    parser.add_argument('--batch-size', type=int, default=10, help='Batch size for queue processing')
    parser.add_argument('--headless', action='store_true', help='Run headless')
    parser.add_argument('--use-proxy', action='store_true', help='Use proxy pool')
    parser.add_argument('--multi-page', action='store_true', help='Scrape multiple pages')
    args = parser.parse_args()

    if args.process_queue:
        from sqlalchemy import create_engine
        engine = create_engine(os.getenv('DATABASE_URL'))
        try:
            await process_blocked_queue(
                engine,
                batch_size=args.batch_size,
                continuous=args.continuous
            )
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            engine.dispose()
        return

    if not args.url:
        print("Usage: python ultimate_stealth_scraper.py <url>")
        print("       python ultimate_stealth_scraper.py --process-queue [--continuous] [--batch-size N]")
        return

    async with UltimateStealthScraper(
        headless=args.headless,
        use_proxy=args.use_proxy
    ) as scraper:
        if args.multi_page:
            result = await scraper.scrape_multiple_pages(args.url)
            print(f"\nBase URL success: {result['base_result']['success']}")
            print(f"Additional pages: {len(result['additional_pages'])}")
            print(f"All phones: {result['all_phones']}")
            print(f"All emails: {result['all_emails']}")
        else:
            result = await scraper.scrape_website(args.url)
            print(f"\nSuccess: {result['success']}")
            print(f"Final URL: {result['final_url']}")
            print(f"CAPTCHA: {result['captcha_detected']} ({result['captcha_type']})")

            if result['content']:
                print(f"Title: {result['content'].title}")
                print(f"Phones: {result['content'].phone_numbers}")
                print(f"Emails: {result['content'].email_addresses}")
                print(f"Business: {result['content'].business_name}")


if __name__ == '__main__':
    asyncio.run(main())
