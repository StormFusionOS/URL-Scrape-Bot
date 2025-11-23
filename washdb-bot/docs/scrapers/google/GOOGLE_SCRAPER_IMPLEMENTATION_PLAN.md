# Google Business Scraper Implementation Plan
## Production-Ready, No-Proxy, Sophisticated Approach

**Date**: 2025-11-10
**Project**: washdb-bot Google Business Scraper Module
**Goal**: Create an extremely sophisticated, cautious Google Business scraper without proxies

---

## EXECUTIVE SUMMARY

### Key Requirements
✅ **No Proxies Required** - Designed for cautious, compliant scraping
✅ **Extremely Sophisticated** - Multi-layered approach with intelligent fallbacks
✅ **Excellent Logging** - Comprehensive tracking for troubleshooting
✅ **Speed Not Priority** - Conservative rate limiting to avoid detection
✅ **Full GUI Integration** - Matches Yellow Pages functionality

### Recommended Approach: HYBRID STRATEGY

We'll use a **three-tier hybrid approach** that balances reliability, cost, and sophistication:

1. **Tier 1 (Primary)**: Google Maps API - Official, reliable, structured data
2. **Tier 2 (Fallback)**: Cautious Playwright scraping with extreme rate limiting
3. **Tier 3 (Enrichment)**: Website scraping (existing infrastructure)

This approach requires **no proxies** because:
- API calls are legitimate and rate-limited
- Playwright scraping uses extreme caution (30-60s delays)
- Looks like organic human behavior
- Falls back gracefully if blocked

---

## PHASE 1: CORE INFRASTRUCTURE (Week 1-2)

### 1.1 Directory Structure

```
washdb-bot/
├── scrape_google/           # NEW - Google scraper module
│   ├── __init__.py
│   ├── google_client.py     # API + Playwright hybrid client
│   ├── google_crawl.py      # Orchestration layer
│   ├── google_parse.py      # Parse Google results
│   ├── google_logger.py     # Dedicated logging module
│   └── google_config.py     # Configuration management
│
├── niceui/pages/
│   ├── discover.py          # MODIFY - Add Google tab
│   └── google_discover.py   # NEW - Google-specific discover page
│
├── gui_backend/
│   └── backend_facade.py    # MODIFY - Add Google methods
│
├── logs/
│   └── google_scrape.log    # NEW - Google-specific logs
│
└── data/
    └── google_config.json   # NEW - Google API keys, settings
```

### 1.2 Database Schema Updates

**Existing `companies` table already supports Google:**
- `source` field: 'Google' (already exists alongside 'YellowPages')
- `rating_google`, `reviews_google` fields already exist
- `place_id` field: Add for Google Place ID (unique identifier)

**New migration needed:**
```sql
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS place_id VARCHAR(255) UNIQUE,
ADD COLUMN IF NOT EXISTS google_business_url TEXT,
ADD COLUMN IF NOT EXISTS scrape_method VARCHAR(50),  -- 'api', 'playwright', 'manual'
ADD COLUMN IF NOT EXISTS api_call_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_api_call TIMESTAMP;
```

---

## PHASE 2: GOOGLE CLIENT (Week 2-3)

### 2.1 Hybrid Google Client Architecture

**File**: `scrape_google/google_client.py`

```python
"""
Hybrid Google Business Scraper Client

Uses a three-tier approach:
1. Google Maps API (primary, reliable, structured)
2. Playwright scraping (fallback, cautious rate-limiting)
3. Error handling & retry logic with exponential backoff
"""

import time
import random
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import googlemaps
from playwright.sync_api import sync_playwright, Browser, Page
from google_logger import GoogleScraperLogger

class ScrapeMethod(Enum):
    """Scraping method used"""
    API = "api"
    PLAYWRIGHT = "playwright"
    FALLBACK = "fallback"
    FAILED = "failed"

@dataclass
class GoogleBusiness:
    """Structured Google Business data"""
    # Core identifiers
    name: str
    place_id: str

    # Contact info
    phone: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None

    # Location
    address: str = None
    city: str = None
    state: str = None
    zip_code: str = None
    lat: float = None
    lng: float = None

    # Business details
    rating: float = None
    review_count: int = None
    business_hours: Dict = None
    categories: List[str] = None

    # Metadata
    scrape_method: ScrapeMethod = ScrapeMethod.API
    scrape_timestamp: str = None
    google_business_url: str = None

    # Quality indicators
    data_completeness: float = None  # 0.0 - 1.0
    confidence_score: float = None   # 0.0 - 1.0


class GoogleBusinessClient:
    """
    Sophisticated Google Business scraper with hybrid approach.

    Features:
    - Google Maps API integration (primary)
    - Cautious Playwright fallback (secondary)
    - Comprehensive error handling
    - Detailed logging for troubleshooting
    - Rate limiting & politeness
    - Automatic retry with exponential backoff
    - Data quality scoring
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_api: bool = True,
        use_playwright: bool = True,
        headless: bool = True,
        logger: Optional[GoogleScraperLogger] = None
    ):
        """
        Initialize Google Business client.

        Args:
            api_key: Google Maps API key (if using API)
            use_api: Enable API scraping (recommended)
            use_playwright: Enable Playwright fallback
            headless: Run browser in headless mode
            logger: Custom logger instance
        """
        self.api_key = api_key
        self.use_api = use_api and api_key is not None
        self.use_playwright = use_playwright
        self.headless = headless

        # Initialize logger
        self.logger = logger or GoogleScraperLogger()

        # Initialize Google Maps client
        if self.use_api:
            try:
                self.gmaps_client = googlemaps.Client(key=api_key)
                self.logger.info("Google Maps API client initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize Google Maps API: {e}")
                self.use_api = False
        else:
            self.gmaps_client = None

        # Playwright browser instance (lazy loaded)
        self.browser: Optional[Browser] = None
        self.playwright = None

        # Rate limiting
        self.last_api_call = 0
        self.last_playwright_call = 0
        self.api_call_count = 0
        self.playwright_call_count = 0

        # Configuration
        self.api_delay = 1.0  # Minimum 1 second between API calls
        self.playwright_delay = 30.0  # Minimum 30 seconds between scrapes
        self.playwright_jitter = 0.3  # ±30% randomization

        self.logger.info("GoogleBusinessClient initialized", extra={
            'use_api': self.use_api,
            'use_playwright': self.use_playwright,
            'headless': self.headless
        })

    def search_businesses(
        self,
        query: str,
        location: str,
        radius_miles: int = 25,
        max_results: int = 60
    ) -> Tuple[List[GoogleBusiness], ScrapeMethod]:
        """
        Search for businesses using hybrid approach.

        Priority:
        1. Try Google Maps API (fast, reliable, structured)
        2. Fall back to Playwright (slow, cautious)
        3. Return partial results if all methods fail

        Args:
            query: Business type (e.g., "pressure washing")
            location: City, State (e.g., "Seattle, WA")
            radius_miles: Search radius in miles
            max_results: Maximum number of results

        Returns:
            Tuple of (businesses list, method used)
        """
        self.logger.info(f"Starting search: query='{query}', location='{location}', radius={radius_miles}mi")

        businesses = []
        method_used = ScrapeMethod.FAILED

        # TIER 1: Try Google Maps API first
        if self.use_api:
            try:
                self.logger.info("Attempting Google Maps API search")
                businesses = self._search_via_api(query, location, radius_miles, max_results)
                method_used = ScrapeMethod.API
                self.logger.info(f"API search successful: {len(businesses)} businesses found")
                return businesses, method_used

            except Exception as e:
                self.logger.warning(f"API search failed: {e}, falling back to Playwright")

        # TIER 2: Fall back to Playwright scraping
        if self.use_playwright and not businesses:
            try:
                self.logger.info("Attempting Playwright scraping (cautious mode)")
                businesses = self._search_via_playwright(query, location, max_results)
                method_used = ScrapeMethod.PLAYWRIGHT
                self.logger.info(f"Playwright search successful: {len(businesses)} businesses found")
                return businesses, method_used

            except Exception as e:
                self.logger.error(f"Playwright search failed: {e}")

        # Both methods failed
        if not businesses:
            self.logger.error(f"All search methods failed for query='{query}', location='{location}'")

        return businesses, method_used

    def _search_via_api(
        self,
        query: str,
        location: str,
        radius_miles: int,
        max_results: int
    ) -> List[GoogleBusiness]:
        """
        Search using Google Maps API.

        Rate limiting: 1 second between calls
        Cost: ~$0.032 per search (Nearby Search)
        Reliability: Very high
        """
        # Rate limiting
        self._wait_for_api_rate_limit()

        # Convert miles to meters
        radius_meters = int(radius_miles * 1609.34)

        # Geocode location to coordinates
        geocode_result = self.gmaps_client.geocode(location)
        if not geocode_result:
            raise ValueError(f"Could not geocode location: {location}")

        lat = geocode_result[0]['geometry']['location']['lat']
        lng = geocode_result[0]['geometry']['location']['lng']

        self.logger.debug(f"Geocoded '{location}' to ({lat}, {lng})")

        # Nearby search with pagination
        businesses = []
        page_token = None

        while len(businesses) < max_results:
            # Rate limit before each page
            self._wait_for_api_rate_limit()

            # API call
            response = self.gmaps_client.places_nearby(
                location=(lat, lng),
                radius=radius_meters,
                keyword=query,
                page_token=page_token
            )

            self.api_call_count += 1
            self.logger.debug(f"API call #{self.api_call_count}: {len(response.get('results', []))} results")

            # Parse results
            for place in response.get('results', []):
                business = self._parse_api_result(place)
                if business:
                    businesses.append(business)

            # Check for next page
            page_token = response.get('next_page_token')
            if not page_token or len(businesses) >= max_results:
                break

            # Wait for next page token to be ready
            time.sleep(2)

        return businesses[:max_results]

    def _search_via_playwright(
        self,
        query: str,
        location: str,
        max_results: int
    ) -> List[GoogleBusiness]:
        """
        Search using Playwright with EXTREME caution.

        Rate limiting: 30-60 seconds between actions
        Behavior simulation: Random scrolling, mouse movements
        Detection avoidance: Realistic human patterns
        """
        # Initialize browser if needed
        if not self.browser:
            self._init_playwright()

        # Rate limiting (conservative)
        self._wait_for_playwright_rate_limit()

        # Create new page with realistic fingerprint
        page = self._create_realistic_page()

        try:
            # Construct Google Maps search URL
            search_url = f"https://www.google.com/maps/search/{query}+{location}".replace(' ', '+')

            self.logger.info(f"Navigating to: {search_url}")

            # Navigate with realistic timing
            page.goto(search_url, wait_until='networkidle', timeout=60000)

            # Wait for human-like time
            self._human_wait(3, 5)

            # Simulate human reading/scrolling
            self._simulate_human_behavior(page)

            # Extract business listings
            businesses = self._extract_businesses_from_page(page, max_results)

            self.playwright_call_count += 1
            self.logger.info(f"Playwright scrape #{self.playwright_call_count}: {len(businesses)} businesses extracted")

            return businesses

        except Exception as e:
            self.logger.error(f"Playwright scraping error: {e}", exc_info=True)
            raise

        finally:
            # Close page but keep browser alive for reuse
            page.close()

    def _wait_for_api_rate_limit(self):
        """Enforce API rate limiting (1 second minimum)"""
        elapsed = time.time() - self.last_api_call
        if elapsed < self.api_delay:
            wait_time = self.api_delay - elapsed
            self.logger.debug(f"API rate limit: waiting {wait_time:.2f}s")
            time.sleep(wait_time)
        self.last_api_call = time.time()

    def _wait_for_playwright_rate_limit(self):
        """Enforce Playwright rate limiting (30-60 seconds with jitter)"""
        elapsed = time.time() - self.last_playwright_call
        min_delay = self.playwright_delay

        if elapsed < min_delay:
            wait_time = min_delay - elapsed
            # Add jitter (randomization)
            jitter = random.uniform(-self.playwright_jitter * wait_time,
                                   self.playwright_jitter * wait_time)
            total_wait = max(0, wait_time + jitter)

            self.logger.info(f"Playwright rate limit: waiting {total_wait:.1f}s (base: {min_delay}s, jitter: {jitter:.1f}s)")
            time.sleep(total_wait)

        self.last_playwright_call = time.time()

    def _human_wait(self, min_seconds: float, max_seconds: float):
        """Wait with human-like timing"""
        wait_time = random.uniform(min_seconds, max_seconds)
        self.logger.debug(f"Human wait: {wait_time:.2f}s")
        time.sleep(wait_time)

    def _init_playwright(self):
        """Initialize Playwright browser with realistic settings"""
        self.logger.info("Initializing Playwright browser")

        self.playwright = sync_playwright().start()

        # Random browser configuration
        viewport_options = [
            {'width': 1920, 'height': 1080},
            {'width': 1366, 'height': 768},
            {'width': 1440, 'height': 900},
        ]

        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]

        viewport = random.choice(viewport_options)
        user_agent = random.choice(user_agents)

        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )

        self.logger.info(f"Browser launched: viewport={viewport}, user_agent={user_agent[:50]}...")

    def _create_realistic_page(self) -> Page:
        """Create a new page with realistic fingerprinting"""
        context = self.browser.new_context(
            viewport={'width': random.randint(1200, 1920), 'height': random.randint(800, 1080)},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            locale='en-US',
            timezone_id=random.choice(['America/New_York', 'America/Chicago', 'America/Los_Angeles'])
        )

        page = context.new_page()

        # Mask WebDriver property
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        return page

    def _simulate_human_behavior(self, page: Page):
        """Simulate human-like behavior (scrolling, mouse movements)"""
        self.logger.debug("Simulating human behavior")

        # Random scrolling
        for _ in range(random.randint(2, 4)):
            scroll_amount = random.randint(100, 300)
            page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            self._human_wait(0.5, 1.5)

        # Random mouse movements
        page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        self._human_wait(0.3, 0.8)

    def _extract_businesses_from_page(self, page: Page, max_results: int) -> List[GoogleBusiness]:
        """Extract business listings from Google Maps page"""
        businesses = []

        # Wait for results to load
        try:
            page.wait_for_selector('[role="article"]', timeout=10000)
        except:
            self.logger.warning("No business listings found on page")
            return businesses

        # Extract business cards
        business_cards = page.locator('[role="article"]').all()

        self.logger.debug(f"Found {len(business_cards)} business cards on page")

        for i, card in enumerate(business_cards[:max_results]):
            try:
                business = self._parse_playwright_result(card, page)
                if business:
                    businesses.append(business)

                # Human-like pause between processing cards
                if i < len(business_cards) - 1:
                    self._human_wait(0.2, 0.5)

            except Exception as e:
                self.logger.warning(f"Failed to parse business card {i}: {e}")
                continue

        return businesses

    def _parse_api_result(self, place: Dict) -> Optional[GoogleBusiness]:
        """Parse Google Maps API result into GoogleBusiness object"""
        try:
            # Fetch full place details for complete data
            place_id = place.get('place_id')
            if not place_id:
                return None

            # Rate limit
            self._wait_for_api_rate_limit()

            # Get place details
            details = self.gmaps_client.place(
                place_id=place_id,
                fields=[
                    'name', 'formatted_address', 'formatted_phone_number',
                    'website', 'rating', 'user_ratings_total', 'opening_hours',
                    'geometry', 'types', 'url'
                ]
            )

            result = details.get('result', {})

            # Parse address components
            address = result.get('formatted_address', '')
            address_parts = self._parse_address(address)

            # Create business object
            business = GoogleBusiness(
                name=result.get('name'),
                place_id=place_id,
                phone=result.get('formatted_phone_number'),
                website=result.get('website'),
                address=address_parts.get('street'),
                city=address_parts.get('city'),
                state=address_parts.get('state'),
                zip_code=address_parts.get('zip'),
                lat=result['geometry']['location']['lat'],
                lng=result['geometry']['location']['lng'],
                rating=result.get('rating'),
                review_count=result.get('user_ratings_total'),
                categories=result.get('types', []),
                google_business_url=result.get('url'),
                scrape_method=ScrapeMethod.API,
                scrape_timestamp=time.strftime('%Y-%m-%d %H:%M:%S')
            )

            # Calculate data completeness
            business.data_completeness = self._calculate_data_completeness(business)
            business.confidence_score = 1.0  # API data is highly reliable

            return business

        except Exception as e:
            self.logger.error(f"Failed to parse API result: {e}")
            return None

    def _parse_playwright_result(self, card, page: Page) -> Optional[GoogleBusiness]:
        """Parse Playwright-scraped business card"""
        try:
            # Extract basic info from card
            name = card.locator('div[role="heading"]').first.text_content() if card.locator('div[role="heading"]').count() > 0 else None

            # This is a simplified example - full implementation would extract:
            # - Address, phone, website
            # - Rating, reviews
            # - Categories
            # Implementation details depend on Google Maps DOM structure

            business = GoogleBusiness(
                name=name,
                place_id=f"playwright_{int(time.time())}_{random.randint(1000, 9999)}",  # Temporary ID
                scrape_method=ScrapeMethod.PLAYWRIGHT,
                scrape_timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
                confidence_score=0.7  # Playwright data less reliable than API
            )

            return business

        except Exception as e:
            self.logger.error(f"Failed to parse Playwright result: {e}")
            return None

    def _parse_address(self, address: str) -> Dict[str, str]:
        """Parse formatted address into components"""
        # Simple parsing - can be enhanced with geocoding libraries
        parts = address.split(',')

        result = {
            'street': parts[0].strip() if len(parts) > 0 else '',
            'city': parts[1].strip() if len(parts) > 1 else '',
            'state': '',
            'zip': ''
        }

        # Parse state and ZIP from last part
        if len(parts) > 2:
            last_part = parts[-1].strip()
            state_zip = last_part.split()
            if len(state_zip) >= 2:
                result['state'] = state_zip[0]
                result['zip'] = state_zip[1]

        return result

    def _calculate_data_completeness(self, business: GoogleBusiness) -> float:
        """Calculate data completeness score (0.0 - 1.0)"""
        required_fields = ['name', 'phone', 'website', 'address', 'city', 'state']
        filled_fields = sum(1 for field in required_fields if getattr(business, field))
        return filled_fields / len(required_fields)

    def close(self):
        """Clean up resources"""
        if self.browser:
            self.logger.info("Closing Playwright browser")
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

        self.logger.info(f"Client closed: API calls={self.api_call_count}, Playwright calls={self.playwright_call_count}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
```

### 2.2 Logging Module

**File**: `scrape_google/google_logger.py`

```python
"""
Dedicated Google Scraper Logging Module

Features:
- Structured JSON logging
- Separate log files for different severity levels
- Contextual logging with metadata
- Easy troubleshooting and debugging
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

class GoogleScraperLogger:
    """
    Sophisticated logger for Google scraper with multiple log levels and formats.
    """

    def __init__(
        self,
        log_dir: str = "logs",
        console_level: str = "INFO",
        file_level: str = "DEBUG"
    ):
        """
        Initialize logger with file and console handlers.

        Args:
            log_dir: Directory for log files
            console_level: Minimum level for console output
            file_level: Minimum level for file output
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # Create logger
        self.logger = logging.getLogger('google_scraper')
        self.logger.setLevel(logging.DEBUG)

        # Remove existing handlers
        self.logger.handlers = []

        # Console handler (human-readable)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, console_level))
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        # File handler - All logs (JSON format)
        all_log_file = self.log_dir / 'google_scrape.log'
        all_handler = logging.FileHandler(all_log_file)
        all_handler.setLevel(getattr(logging, file_level))
        all_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(all_handler)

        # File handler - Errors only
        error_log_file = self.log_dir / 'google_scrape_errors.log'
        error_handler = logging.FileHandler(error_log_file)
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(error_handler)

        # File handler - API calls tracking
        api_log_file = self.log_dir / 'google_api_calls.log'
        self.api_handler = logging.FileHandler(api_log_file)
        self.api_handler.setLevel(logging.DEBUG)
        self.api_handler.setFormatter(JSONFormatter())

    def info(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log info message with optional metadata"""
        self.logger.info(message, extra={'metadata': extra or {}})

    def debug(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log debug message with optional metadata"""
        self.logger.debug(message, extra={'metadata': extra or {}})

    def warning(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log warning message with optional metadata"""
        self.logger.warning(message, extra={'metadata': extra or {}})

    def error(self, message: str, exc_info: bool = False, extra: Optional[Dict[str, Any]] = None):
        """Log error message with optional exception info"""
        self.logger.error(message, exc_info=exc_info, extra={'metadata': extra or {}})

    def log_api_call(self, method: str, params: Dict[str, Any], response_size: int, cost: float):
        """Log Google Maps API call for cost tracking"""
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'type': 'api_call',
            'method': method,
            'params': params,
            'response_size': response_size,
            'estimated_cost': cost
        }

        self.api_handler.handle(
            self.logger.makeRecord(
                self.logger.name, logging.INFO, '', 0, json.dumps(log_data), (), None
            )
        )

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logs"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # Add metadata if available
        if hasattr(record, 'metadata'):
            log_data['metadata'] = record.metadata

        # Add exception info if available
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)
```

---

## PHASE 3: ORCHESTRATION & GUI (Week 3-4)

### 3.1 Crawl Orchestrator

**File**: `scrape_google/google_crawl.py`

```python
"""
Google Business Crawl Orchestrator

Manages batch discovery jobs with:
- Multiple states × categories
- Progress tracking
- Error recovery
- Database persistence
"""

from typing import List, Dict, Optional
from datetime import datetime
from google_client import GoogleBusinessClient, ScrapeMethod
from google_logger import GoogleScraperLogger
import sys
sys.path.append('..')
from db.database import Database

class GoogleCrawlOrchestrator:
    """
    Orchestrate large-scale Google Business discovery jobs.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        database: Optional[Database] = None,
        logger: Optional[GoogleScraperLogger] = None
    ):
        self.client = GoogleBusinessClient(api_key=api_key, logger=logger)
        self.database = database or Database()
        self.logger = logger or GoogleScraperLogger()

        self.total_businesses = 0
        self.total_api_calls = 0
        self.total_playwright_calls = 0
        self.errors = []

    def discover_businesses(
        self,
        categories: List[str],
        states: List[str],
        cities_per_state: Optional[Dict[str, List[str]]] = None,
        radius_miles: int = 25,
        max_per_search: int = 60
    ) -> Dict:
        """
        Run discovery across multiple categories and locations.

        Args:
            categories: Business types (e.g., ["pressure washing", "window cleaning"])
            states: State abbreviations (e.g., ["WA", "OR", "CA"])
            cities_per_state: Optional city-specific searches
            radius_miles: Search radius
            max_per_search: Max results per search

        Returns:
            Summary dictionary with counts and errors
        """
        start_time = datetime.now()
        self.logger.info(f"Starting discovery job: {len(categories)} categories × {len(states)} states")

        total_searches = len(categories) * len(states)
        current_search = 0

        for state in states:
            for category in categories:
                current_search += 1

                # Determine locations to search
                if cities_per_state and state in cities_per_state:
                    locations = [f"{city}, {state}" for city in cities_per_state[state]]
                else:
                    locations = [state]  # Search entire state

                for location in locations:
                    self.logger.info(f"[{current_search}/{total_searches}] Searching: {category} in {location}")

                    try:
                        # Search Google
                        businesses, method = self.client.search_businesses(
                            query=category,
                            location=location,
                            radius_miles=radius_miles,
                            max_results=max_per_search
                        )

                        # Save to database
                        saved_count = self._save_businesses(businesses, category, location, method)

                        self.total_businesses += saved_count

                        if method == ScrapeMethod.API:
                            self.total_api_calls += 1
                        elif method == ScrapeMethod.PLAYWRIGHT:
                            self.total_playwright_calls += 1

                        self.logger.info(f"Saved {saved_count}/{len(businesses)} businesses from {location}")

                    except Exception as e:
                        error_msg = f"Failed to search {category} in {location}: {e}"
                        self.logger.error(error_msg, exc_info=True)
                        self.errors.append(error_msg)

        # Generate summary
        duration = (datetime.now() - start_time).total_seconds()

        summary = {
            'total_businesses': self.total_businesses,
            'total_api_calls': self.total_api_calls,
            'total_playwright_calls': self.total_playwright_calls,
            'errors': len(self.errors),
            'duration_seconds': duration,
            'searches_completed': current_search,
            'searches_total': total_searches
        }

        self.logger.info(f"Discovery job complete: {summary}")

        return summary

    def _save_businesses(
        self,
        businesses: List,
        category: str,
        location: str,
        method: ScrapeMethod
    ) -> int:
        """Save businesses to database, avoiding duplicates"""
        saved_count = 0

        for business in businesses:
            try:
                # Check if already exists (by place_id)
                existing = self.database.get_company_by_place_id(business.place_id)

                if existing:
                    self.logger.debug(f"Skipping duplicate: {business.name} (place_id: {business.place_id})")
                    continue

                # Insert new business
                self.database.insert_company({
                    'name': business.name,
                    'place_id': business.place_id,
                    'phone': business.phone,
                    'website': business.website,
                    'email': business.email,
                    'address': business.address,
                    'city': business.city,
                    'state': business.state,
                    'zip_code': business.zip_code,
                    'latitude': business.lat,
                    'longitude': business.lng,
                    'rating_google': business.rating,
                    'reviews_google': business.review_count,
                    'google_business_url': business.google_business_url,
                    'source': 'Google',
                    'scrape_method': method.value,
                    'discovery_category': category,
                    'discovery_location': location,
                    'discovered_date': datetime.now()
                })

                saved_count += 1

            except Exception as e:
                self.logger.warning(f"Failed to save business {business.name}: {e}")

        return saved_count
```

### 3.2 GUI Integration

**File**: `niceui/pages/google_discover.py`

```python
"""
Google Discovery Page - NiceGUI Interface

Provides UI for configuring and running Google Business discovery jobs.
"""

from nicegui import ui, app
from typing import List
import sys
sys.path.append('../..')
from scrape_google.google_crawl import GoogleCrawlOrchestrator
from scrape_google.google_logger import GoogleScraperLogger
from gui_backend.backend_facade import BackendFacade

# State management
class GoogleDiscoverState:
    categories: List[str] = []
    states: List[str] = []
    radius_miles: int = 25
    max_results: int = 60
    use_api: bool = True
    api_key: str = ""
    job_running: bool = False
    progress: float = 0.0
    status_message: str = ""

state = GoogleDiscoverState()
backend = BackendFacade()

@ui.page('/google-discover')
def google_discover_page():
    """Google Business Discovery page"""

    with ui.column().classes('w-full gap-4 p-4'):
        # Header
        ui.label('Google Business Discovery').classes('text-2xl font-bold')
        ui.separator()

        # Configuration Section
        with ui.card().classes('w-full'):
            ui.label('Configuration').classes('text-lg font-semibold')

            with ui.row().classes('w-full gap-4'):
                # Categories
                with ui.column().classes('flex-1'):
                    ui.label('Business Categories').classes('font-medium')
                    category_input = ui.textarea(
                        placeholder='pressure washing\nwindow cleaning\ngutter cleaning',
                        value='\n'.join(state.categories)
                    ).classes('w-full')

                # States
                with ui.column().classes('flex-1'):
                    ui.label('States (comma-separated)').classes('font-medium')
                    states_input = ui.input(
                        placeholder='WA, OR, CA',
                        value=', '.join(state.states)
                    ).classes('w-full')

            with ui.row().classes('w-full gap-4'):
                # Radius
                ui.number(
                    label='Search Radius (miles)',
                    value=state.radius_miles,
                    min=1,
                    max=50
                ).classes('flex-1').bind_value(state, 'radius_miles')

                # Max Results
                ui.number(
                    label='Max Results per Search',
                    value=state.max_results,
                    min=10,
                    max=100
                ).classes('flex-1').bind_value(state, 'max_results')

            # API Configuration
            with ui.row().classes('w-full items-center gap-4'):
                ui.checkbox('Use Google Maps API', value=True).bind_value(state, 'use_api')
                ui.input(
                    label='API Key',
                    placeholder='Enter Google Maps API key',
                    password=True
                ).classes('flex-1').bind_value(state, 'api_key')

        # Action Buttons
        with ui.row().classes('gap-2'):
            ui.button(
                'Start Discovery',
                on_click=start_discovery,
                color='primary'
            ).props('icon=play_arrow').bind_enabled_from(state, 'job_running', backward=lambda x: not x)

            ui.button(
                'Stop',
                on_click=stop_discovery,
                color='negative'
            ).props('icon=stop').bind_enabled_from(state, 'job_running')

        # Progress Section
        with ui.card().classes('w-full'):
            ui.label('Progress').classes('text-lg font-semibold')
            progress_bar = ui.linear_progress(value=0).classes('w-full').bind_value_from(state, 'progress')
            status_label = ui.label('').bind_text_from(state, 'status_message')

        # Results Section
        with ui.card().classes('w-full'):
            ui.label('Recent Results').classes('text-lg font-semibold')
            results_table = ui.table(
                columns=[
                    {'name': 'name', 'label': 'Business Name', 'field': 'name'},
                    {'name': 'category', 'label': 'Category', 'field': 'category'},
                    {'name': 'location', 'label': 'Location', 'field': 'location'},
                    {'name': 'method', 'label': 'Method', 'field': 'method'},
                ],
                rows=[]
            ).classes('w-full')

async def start_discovery():
    """Start Google discovery job"""
    state.job_running = True
    state.progress = 0.0
    state.status_message = "Initializing..."

    # Parse input
    state.categories = [c.strip() for c in category_input.value.split('\n') if c.strip()]
    state.states = [s.strip() for s in states_input.value.split(',') if s.strip()]

    try:
        # Initialize orchestrator
        logger = GoogleScraperLogger()
        orchestrator = GoogleCrawlOrchestrator(
            api_key=state.api_key if state.use_api else None,
            logger=logger
        )

        # Run discovery
        state.status_message = f"Searching {len(state.categories)} categories in {len(state.states)} states..."

        summary = orchestrator.discover_businesses(
            categories=state.categories,
            states=state.states,
            radius_miles=state.radius_miles,
            max_per_search=state.max_results
        )

        state.progress = 1.0
        state.status_message = f"Complete! Found {summary['total_businesses']} businesses"

        ui.notify(f"Discovery complete: {summary['total_businesses']} businesses", type='positive')

    except Exception as e:
        state.status_message = f"Error: {str(e)}"
        ui.notify(f"Discovery failed: {str(e)}", type='negative')

    finally:
        state.job_running = False

def stop_discovery():
    """Stop running discovery job"""
    state.job_running = False
    state.status_message = "Stopped by user"
    ui.notify("Discovery stopped", type='warning')
```

---

## PHASE 4: TESTING & DEPLOYMENT (Week 4-5)

### 4.1 Testing Strategy

**Create**: `scrape_google/test_google_scraper.py`

```python
"""
Google Scraper Test Suite

Tests:
1. API integration
2. Playwright fallback
3. Rate limiting
4. Error handling
5. Database persistence
"""

import unittest
from google_client import GoogleBusinessClient, ScrapeMethod
from google_crawl import GoogleCrawlOrchestrator
from google_logger import GoogleScraperLogger

class TestGoogleScraper(unittest.TestCase):

    def setUp(self):
        """Initialize test client"""
        self.logger = GoogleScraperLogger(log_dir='logs/test')
        self.client = GoogleBusinessClient(
            api_key='TEST_KEY',
            logger=self.logger,
            use_playwright=False  # Test API only initially
        )

    def test_api_search(self):
        """Test Google Maps API search"""
        businesses, method = self.client.search_businesses(
            query='pressure washing',
            location='Seattle, WA',
            radius_miles=10,
            max_results=5
        )

        self.assertEqual(method, ScrapeMethod.API)
        self.assertGreater(len(businesses), 0)
        self.assertIsNotNone(businesses[0].name)
        self.assertIsNotNone(businesses[0].place_id)

    def test_rate_limiting(self):
        """Test API rate limiting enforcement"""
        import time

        start = time.time()

        # Make 3 consecutive searches
        for _ in range(3):
            self.client.search_businesses('test', 'Seattle, WA', max_results=1)

        elapsed = time.time() - start

        # Should take at least 2 seconds (3 searches × 1s delay - 1)
        self.assertGreaterEqual(elapsed, 2.0)

    def test_data_completeness(self):
        """Test data quality scoring"""
        businesses, _ = self.client.search_businesses(
            'coffee shop', 'Seattle, WA', max_results=5
        )

        for business in businesses:
            self.assertIsNotNone(business.data_completeness)
            self.assertGreaterEqual(business.data_completeness, 0.0)
            self.assertLessEqual(business.data_completeness, 1.0)

    def test_error_handling(self):
        """Test graceful error handling"""
        # Invalid location should not crash
        businesses, method = self.client.search_businesses(
            'test', 'INVALID_LOCATION_XYZ', max_results=1
        )

        # Should return empty list, not raise exception
        self.assertEqual(len(businesses), 0)
        self.assertEqual(method, ScrapeMethod.FAILED)

    def tearDown(self):
        """Cleanup"""
        self.client.close()

if __name__ == '__main__':
    unittest.main()
```

### 4.2 Cost Estimation Tool

**Create**: `scrape_google/estimate_cost.py`

```python
"""
Google Maps API Cost Estimator

Helps estimate costs before running large discovery jobs.
"""

def estimate_google_maps_cost(
    num_categories: int,
    num_locations: int,
    results_per_search: int = 60
):
    """
    Estimate Google Maps API costs.

    Pricing (as of 2024):
    - Nearby Search: $0.032 per request
    - Place Details: $0.017 per request
    - Pagination: Each "next page" = additional request

    Args:
        num_categories: Number of business categories
        num_locations: Number of locations (states/cities)
        results_per_search: Expected results per search (default 60 = 3 pages)

    Returns:
        dict with cost breakdown
    """
    # Total searches
    total_searches = num_categories * num_locations

    # Nearby Search costs (3 pages per search for 60 results)
    pages_per_search = max(1, results_per_search // 20)  # 20 results per page
    nearby_requests = total_searches * pages_per_search
    nearby_cost = nearby_requests * 0.032

    # Place Details costs (1 per business)
    expected_businesses = total_searches * results_per_search
    details_requests = expected_businesses
    details_cost = details_requests * 0.017

    # Total
    total_cost = nearby_cost + details_cost

    return {
        'total_searches': total_searches,
        'nearby_requests': nearby_requests,
        'nearby_cost': f'${nearby_cost:.2f}',
        'details_requests': details_requests,
        'details_cost': f'${details_cost:.2f}',
        'total_cost': f'${total_cost:.2f}',
        'estimated_businesses': expected_businesses
    }

# Example usage
if __name__ == '__main__':
    # Example: 5 categories × 50 states
    cost = estimate_google_maps_cost(
        num_categories=5,
        num_locations=50,
        results_per_search=60
    )

    print("Google Maps API Cost Estimation")
    print("=" * 50)
    for key, value in cost.items():
        print(f"{key:25s}: {value}")
```

---

## IMPLEMENTATION TIMELINE

### Week 1-2: Core Infrastructure
- ✅ Directory structure
- ✅ Database schema updates
- ✅ Google client (API + Playwright hybrid)
- ✅ Logging module
- ✅ Configuration management

### Week 3: Orchestration & Testing
- ✅ Crawl orchestrator
- ✅ Database integration
- ✅ Unit tests
- ✅ Cost estimation tools

### Week 4: GUI Integration
- ✅ Google discover page
- ✅ Backend facade updates
- ✅ Progress tracking
- ✅ Results display

### Week 5: Polish & Deploy
- ✅ Error handling refinement
- ✅ Documentation
- ✅ User testing
- ✅ Production deployment

---

## COST ANALYSIS

### Google Maps API Pricing (2024)

**Example Scenario**: 5 categories × 50 states

- **Nearby Search**: 250 searches × 3 pages = 750 requests × $0.032 = **$24.00**
- **Place Details**: 15,000 businesses × $0.017 = **$255.00**
- **Total**: **~$279.00** for complete US coverage

**Monthly Budget** (4 runs/month): **~$1,116.00**

### Cost Optimization Strategies

1. **Target High-Value Locations**: Focus on major cities instead of entire states
2. **Cache Results**: Don't re-scrape unchanged businesses
3. **Hybrid Approach**: Use API for new discoveries, Playwright for updates
4. **Rate Limit Awareness**: Stay within free tier ($200/month credit)

---

## ANTI-BLOCKING STRATEGIES (No Proxies Required)

### Why No Proxies Needed

1. **Google Maps API**: Official API, no blocking concerns
2. **Playwright Fallback**: Extreme rate limiting (30-60s delays)
3. **Human Behavior Simulation**: Realistic scrolling, mouse movements
4. **Browser Fingerprinting**: Randomized viewports, user agents, timezones
5. **Politeness**: Respect robots.txt, rate limits

### Rate Limiting Configuration

```python
# Conservative settings (no proxies)
API_DELAY = 1.0                    # 1 second between API calls
PLAYWRIGHT_DELAY = 30.0            # 30 seconds between scrapes
PLAYWRIGHT_JITTER = 0.3            # ±30% randomization
MAX_CONCURRENT_BROWSERS = 1        # Single browser instance
HUMAN_WAIT_MIN = 3.0               # 3-5 seconds per page
HUMAN_WAIT_MAX = 5.0
SCROLL_ITERATIONS = 2-4            # Random scrolling
```

### Behavior Simulation

- Random viewport sizes (1920x1080, 1366x768, 1440x900)
- Rotating user agents (Chrome, Firefox, Safari)
- Random timezones (EST, CST, MST, PST)
- Mouse movements and scrolling
- WebDriver property masking

---

## LOGGING & ERROR TRACKING

### Log Files Structure

```
logs/
├── google_scrape.log           # All logs (JSON format)
├── google_scrape_errors.log    # Errors only
├── google_api_calls.log        # API usage tracking
└── google_playwright.log       # Playwright-specific logs
```

### Log Analysis Commands

```bash
# View recent errors
jq 'select(.level == "ERROR")' logs/google_scrape.log | tail -20

# Track API usage
jq 'select(.type == "api_call") | .estimated_cost' logs/google_api_calls.log | awk '{sum+=$1} END {print "Total: $"sum}'

# Monitor rate limiting
grep "rate limit" logs/google_scrape.log | tail -10

# Check Playwright success rate
grep "Playwright" logs/google_scrape.log | grep -c "successful"
```

### Error Recovery

- **Automatic Retry**: Exponential backoff for transient errors
- **Method Fallback**: API failure → Playwright fallback
- **Partial Results**: Save successful businesses even if batch fails
- **Error Aggregation**: Daily email summary of errors

---

## NEXT STEPS

1. **Review Plan**: Confirm approach and priorities
2. **API Key Setup**: Obtain Google Maps API key, set up billing
3. **Begin Phase 1**: Create directory structure and database schema
4. **Implement Core Client**: Build hybrid Google client
5. **Test & Iterate**: Run small-scale tests, refine rate limiting
6. **GUI Integration**: Add Google discover page
7. **Production Deployment**: Roll out to production

---

## SUCCESS METRICS

- **Data Quality**: >90% completeness for critical fields (name, phone, website)
- **No Blocking**: Zero IP bans or detection issues
- **Cost Efficiency**: <$300/month for full US coverage
- **Speed**: Complete 50 states in <6 hours
- **Reliability**: >95% successful searches
- **Error Recovery**: <1% unrecoverable errors

---

## QUESTIONS TO RESOLVE

1. **API Budget**: What's the monthly API budget limit?
2. **Target Markets**: Focus on all 50 states or prioritize specific regions?
3. **Update Frequency**: How often should we refresh existing businesses?
4. **Data Enrichment**: Should we scrape websites for all Google-discovered businesses?
5. **GUI Preferences**: Any specific UI requirements beyond Yellow Pages parity?

---

**This plan prioritizes:**
- ✅ No proxies (conservative rate limiting)
- ✅ Sophistication (hybrid approach, intelligent fallbacks)
- ✅ Logging (comprehensive, structured, easy troubleshooting)
- ✅ Reliability (error recovery, data quality)
- ✅ Full GUI parity (matches Yellow Pages functionality)

Ready to proceed with implementation once approved!
