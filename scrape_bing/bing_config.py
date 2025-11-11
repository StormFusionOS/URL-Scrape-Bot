"""
Bing discovery configuration for washdb-bot.

This module centralizes configuration constants and environment variable loading
for the Bing discovery provider. It handles both API and HTML fetch modes.

Environment Variables:
    BING_API_KEY: Optional Bing Web Search API v7 key (enables API mode)
    BING_CRAWL_DELAY_SECONDS: Rate limiting delay between requests (default: 3.0)
    BING_PAGES_PER_PAIR: Default pagination depth per category/location (default: 5)
    BING_MODE: Fetch mode - 'auto', 'api', or 'html' (default: 'auto')

Configuration Logic:
    - MODE='auto': Uses API if BING_API_KEY is set, otherwise falls back to HTML
    - MODE='api': Forces API mode (fails if no key)
    - MODE='html': Forces HTML scraping mode

Usage:
    from scrape_bing.bing_config import USE_API, CRAWL_DELAY_SECONDS
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==============================================================================
# Bing API Configuration
# ==============================================================================

# Bing Web Search API v7 key (optional)
# Get one at: https://www.microsoft.com/en-us/bing/apis/bing-web-search-api
BING_API_KEY = os.getenv("BING_API_KEY", "")

# Bing Web Search API base URL
BING_API_BASE = "https://api.bing.microsoft.com/v7.0/search"


# ==============================================================================
# Bing HTML Scraping Configuration
# ==============================================================================

# Bing HTML search base URLs
BING_BASE_URL_DESKTOP = "https://www.bing.com/search"
BING_BASE_URL_MOBILE = "https://www.bing.com/search"  # Mobile uses same endpoint
BING_BASE_URL = os.getenv("BING_BASE", BING_BASE_URL_MOBILE)

# Common desktop browser User-Agent
USER_AGENT_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Mobile User-Agent (often bypasses stricter bot detection)
USER_AGENT_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

# Default to mobile for better bot evasion
USER_AGENT = USER_AGENT_MOBILE

# Request headers for HTML mode
# Note: Don't manually set Accept-Encoding - let requests handle compression automatically
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# ==============================================================================
# Rate Limiting & Pagination
# ==============================================================================

# Crawl delay in seconds (between requests)
CRAWL_DELAY_SECONDS = float(os.getenv("BING_CRAWL_DELAY_SECONDS", "3.0"))

# Default pages to crawl per category/location pair
PAGES_PER_PAIR = int(os.getenv("BING_PAGES_PER_PAIR", "5"))

# Maximum results per page
# API: 50 max, HTML: typically 10-20 organic results
MAX_RESULTS_PER_PAGE = 10

# Pagination offset increment
# API: Use 'offset' parameter
# HTML: Use 'first' parameter (first=1, first=11, first=21, etc.)
RESULTS_PER_PAGE_OFFSET = 10


# ==============================================================================
# Fetch Mode Configuration
# ==============================================================================

# Fetch mode: 'auto', 'api', or 'html'
# - auto: Use API if BING_API_KEY is set, otherwise HTML
# - api: Force API mode (requires BING_API_KEY)
# - html: Force HTML scraping mode
MODE = os.getenv("BING_MODE", "auto").lower()

# Determine whether to use API mode
if MODE == "api":
    if not BING_API_KEY:
        raise ValueError("BING_MODE=api requires BING_API_KEY to be set")
    USE_API = True
elif MODE == "html":
    USE_API = False
else:  # MODE == "auto"
    USE_API = bool(BING_API_KEY)


# ==============================================================================
# Retry & Backoff Configuration
# ==============================================================================

# Maximum retry attempts on fetch failure
MAX_RETRIES = 3

# Exponential backoff base (seconds): 2, 4, 8
RETRY_BACKOFF_BASE = 2


# ==============================================================================
# Service Categories & Locations
# ==============================================================================

# Service categories to discover (reused from YP)
# These will be imported from scrape_yp.yp_crawl or defined here
CATEGORIES = [
    "pressure washing",
    "power washing",
    "soft washing",
    "window cleaning",
    "gutter cleaning",
    "roof cleaning",
    "deck cleaning",
    "concrete cleaning",
    "house cleaning exterior",
    "driveway cleaning",
]

# US States (2-letter codes) - same as YP
STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


# ==============================================================================
# Logging Configuration
# ==============================================================================

# Log level for Bing crawler (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
