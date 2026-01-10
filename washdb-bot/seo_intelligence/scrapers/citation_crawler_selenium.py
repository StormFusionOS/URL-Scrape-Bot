"""
Citation Crawler Module (SeleniumBase Version)

Checks and tracks business citations across directories using SeleniumBase UC.

This is a drop-in replacement for citation_crawler.py using SeleniumBase instead of Playwright.
SeleniumBase with uc=True has significantly better anti-detection for citation directories.

Features:
- Check presence on major directories (Yelp, YP, BBB, Google, etc.)
- NAP (Name, Address, Phone) consistency verification
- Track citation completeness and accuracy
- Store in citations table for LAS calculation

Per SCRAPING_NOTES.md:
- Use Tier B rate limits for directories (respectable sites)
- Use YP-style stealth tactics (human delays, scrolling, jitter)
- Verify NAP consistency across listings
- Track last verified date for freshness
"""

import os
import re
import json
import time
import random

# Import YP stealth features for human-like behavior
from scrape_yp.yp_stealth import (
    human_delay,
    get_human_reading_delay,
    get_scroll_delays,
    get_random_viewport,
)
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from dataclasses import dataclass, field, asdict

from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper
from seo_intelligence.services import get_task_logger, get_change_manager, get_domain_quarantine
from runner.logging_setup import get_logger
from db.models import Company, BusinessSource

# Load environment
load_dotenv()

logger = get_logger("citation_crawler_selenium")


@dataclass
class BusinessInfo:
    """Business information for NAP matching."""
    name: str
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    website: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CitationResult:
    """Result of checking a citation directory."""
    directory: str
    directory_url: str
    is_listed: bool = False
    listing_url: Optional[str] = None
    name_match: bool = False
    address_match: bool = False
    phone_match: bool = False
    nap_score: float = 0.0
    has_reviews: bool = False
    review_count: int = 0
    rating: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Major citation directories with SeleniumBase-specific driver types
CITATION_DIRECTORIES = {
    "google_business": {
        "name": "Google Business Profile",
        "search_url": "https://www.google.com/search?q={business}+{location}&pws=0&gl=us",
        "tier": "A",
        "driver_type": "google",  # Use Google-specific driver
    },
    "yelp": {
        "name": "Yelp",
        "search_url": "https://www.yelp.com/search?find_desc={business}&find_loc={location}",
        "tier": "B",
        "driver_type": "yelp",  # Use Yelp-specific driver
    },
    "yellowpages": {
        "name": "Yellow Pages",
        "search_url": "https://www.yellowpages.com/search?search_terms={business}&geo_location_terms={location}",
        "tier": "B",
        "driver_type": "yellowpages",  # Use YellowPages-specific driver
    },
    "bbb": {
        "name": "Better Business Bureau",
        "search_url": "https://www.bbb.org/search?find_text={business}&find_loc={location}&page=1",
        "tier": "B",
        "driver_type": "bbb",  # Use BBB-specific driver
    },
    "facebook": {
        "name": "Facebook",
        "search_url": "https://www.facebook.com/public/{business}",
        "tier": "B",
        "driver_type": "generic",
        "skip": True,  # Requires login
    },
    "angies_list": {
        "name": "Angi (Angie's List)",
        "search_url": "https://www.angi.com/search?search_terms={business}&postal_code={zip}",
        "tier": "B",
        "driver_type": "generic",
    },
    "thumbtack": {
        "name": "Thumbtack",
        "search_url": "https://www.thumbtack.com/search/?search_term={business}&zip_code={zip}",
        "tier": "B",
        "driver_type": "generic",
    },
    "homeadvisor": {
        "name": "HomeAdvisor",
        "search_url": "https://www.homeadvisor.com/s/{location}/?sp=1&q={business}",
        "tier": "B",
        "driver_type": "generic",
    },
    "mapquest": {
        "name": "MapQuest",
        "search_url": "https://www.mapquest.com/search/results?query={business}&boundingBox=&page=0",
        "tier": "C",
        "driver_type": "generic",
    },
    "manta": {
        "name": "Manta",
        "search_url": "https://www.manta.com/search?search_source=nav&search={business}&search_location={location}",
        "tier": "C",
        "driver_type": "generic",
    },
}

# Directories to skip
SKIP_DIRECTORIES = {"facebook"}

# =============================================================================
# Directory-Specific Stealth Configurations
# =============================================================================
# These configs optimize stealth behavior for each directory's detection system.
# Yellow Pages and Google Business are the most aggressive at bot detection.

DIRECTORY_STEALTH_CONFIGS = {
    "yellowpages": {
        "initial_delay": (3.0, 6.0),       # Wait longer before interacting
        "scroll_intensity": "thorough",     # Full F-pattern + extra scrolls
        "min_page_time": 15,                # Spend at least 15s on each page
        "max_page_time": 30,                # But no more than 30s
        "click_random_element": True,       # Click non-critical elements
        "reading_pattern": "f_pattern",     # Use F-pattern reading simulation
        "inter_action_delay": (1.0, 3.0),   # Delay between actions
        "scroll_back_chance": 0.4,          # 40% chance to scroll back up
        "mouse_movement": True,             # Use natural mouse movement
        "typing_simulation": True,          # Natural typing with typos
    },
    "google_business": {
        "initial_delay": (2.0, 4.0),
        "scroll_intensity": "normal",
        "min_page_time": 10,
        "max_page_time": 25,
        "click_random_element": False,      # Google tracks clicks carefully
        "reading_pattern": "f_pattern",
        "inter_action_delay": (0.8, 2.0),
        "scroll_back_chance": 0.3,
        "mouse_movement": True,
        "typing_simulation": True,
        "accept_cookies_first": True,       # Handle Google consent dialog
        "avoid_rapid_searches": True,       # Max 1 search per 30s
        "search_cooldown": 30,              # Seconds between searches
    },
    "yelp": {
        "initial_delay": (2.5, 5.0),
        "scroll_intensity": "normal",
        "min_page_time": 12,
        "max_page_time": 25,
        "click_random_element": True,
        "reading_pattern": "f_pattern",
        "inter_action_delay": (1.0, 2.5),
        "scroll_back_chance": 0.35,
        "mouse_movement": True,
        "typing_simulation": True,
    },
    "bbb": {
        "initial_delay": (1.5, 3.5),
        "scroll_intensity": "light",
        "min_page_time": 8,
        "max_page_time": 20,
        "click_random_element": False,
        "reading_pattern": "z_pattern",     # BBB has simpler layouts
        "inter_action_delay": (0.5, 1.5),
        "scroll_back_chance": 0.2,
        "mouse_movement": True,
        "typing_simulation": False,
    },
    "default": {
        "initial_delay": (2.0, 4.0),
        "scroll_intensity": "normal",
        "min_page_time": 10,
        "max_page_time": 20,
        "click_random_element": False,
        "reading_pattern": "basic",
        "inter_action_delay": (0.8, 2.0),
        "scroll_back_chance": 0.25,
        "mouse_movement": True,
        "typing_simulation": False,
    },
}


def get_directory_config(directory: str) -> Dict[str, Any]:
    """Get stealth configuration for a specific directory."""
    return DIRECTORY_STEALTH_CONFIGS.get(directory, DIRECTORY_STEALTH_CONFIGS["default"])


# =============================================================================
# Directory Metrics Tracking (Phase 7)
# =============================================================================

@dataclass
class DirectoryMetrics:
    """
    Track success/failure metrics per directory for adaptive behavior.

    Monitors detection rates and adjusts delays automatically when
    a directory starts blocking requests.
    """
    directory: str
    success_count: int = 0
    captcha_count: int = 0
    block_count: int = 0
    timeout_count: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0

    @property
    def total_requests(self) -> int:
        return self.success_count + self.captcha_count + self.block_count + self.timeout_count

    @property
    def success_rate(self) -> float:
        """Calculate success rate (0-1)."""
        total = self.total_requests
        return self.success_count / total if total > 0 else 1.0

    @property
    def detection_rate(self) -> float:
        """Calculate detection rate (CAPTCHAs + blocks)."""
        total = self.total_requests
        detected = self.captcha_count + self.block_count
        return detected / total if total > 0 else 0.0

    def record_success(self):
        """Record a successful request."""
        self.success_count += 1
        self.last_success = datetime.now()
        self.consecutive_failures = 0

    def record_captcha(self):
        """Record a CAPTCHA encounter."""
        self.captcha_count += 1
        self.last_failure = datetime.now()
        self.consecutive_failures += 1

    def record_block(self):
        """Record a block/access denied."""
        self.block_count += 1
        self.last_failure = datetime.now()
        self.consecutive_failures += 1

    def record_timeout(self):
        """Record a timeout."""
        self.timeout_count += 1
        self.last_failure = datetime.now()
        self.consecutive_failures += 1

    def should_back_off(self) -> bool:
        """Check if we should slow down requests to this directory."""
        # Back off if:
        # - More than 3 consecutive failures
        # - Detection rate > 30%
        # - Success rate < 50%
        if self.consecutive_failures >= 3:
            return True
        if self.total_requests >= 5:
            if self.detection_rate > 0.3:
                return True
            if self.success_rate < 0.5:
                return True
        return False

    def get_recommended_delay_multiplier(self) -> float:
        """Get delay multiplier based on detection rate."""
        if self.consecutive_failures >= 5:
            return 3.0  # Triple delays after 5 failures
        if self.consecutive_failures >= 3:
            return 2.0  # Double delays after 3 failures
        if self.total_requests >= 10:
            if self.detection_rate > 0.4:
                return 2.5
            if self.detection_rate > 0.2:
                return 1.5
        return 1.0  # Normal speed


class DirectoryMetricsTracker:
    """
    Singleton tracker for directory metrics across all crawler instances.

    Persists metrics in memory for adaptive behavior across requests.
    """
    _instance = None
    _metrics: Dict[str, DirectoryMetrics] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._metrics = {}
        return cls._instance

    def get_metrics(self, directory: str) -> DirectoryMetrics:
        """Get or create metrics for a directory."""
        if directory not in self._metrics:
            self._metrics[directory] = DirectoryMetrics(directory=directory)
        return self._metrics[directory]

    def get_adaptive_delay(self, directory: str) -> Tuple[float, float]:
        """
        Get adaptive delay range based on directory metrics.

        Returns:
            (min_delay, max_delay) tuple adjusted for detection rate
        """
        metrics = self.get_metrics(directory)
        config = get_directory_config(directory)

        # Base delay from config
        base_delay = config.get("inter_action_delay", (1.0, 3.0))
        multiplier = metrics.get_recommended_delay_multiplier()

        adjusted_min = base_delay[0] * multiplier
        adjusted_max = base_delay[1] * multiplier

        # Log if backing off
        if multiplier > 1.0:
            logger.debug(
                f"Adaptive delay for {directory}: {multiplier:.1f}x "
                f"(success={metrics.success_rate:.0%}, detected={metrics.detection_rate:.0%})"
            )

        return (adjusted_min, adjusted_max)

    def should_skip_directory(self, directory: str) -> bool:
        """Check if we should skip a directory due to high detection."""
        metrics = self.get_metrics(directory)

        # Skip if 5+ consecutive failures
        if metrics.consecutive_failures >= 5:
            logger.warning(f"Skipping {directory} due to {metrics.consecutive_failures} consecutive failures")
            return True

        # Skip if detection rate > 70% with 10+ requests
        if metrics.total_requests >= 10 and metrics.detection_rate > 0.7:
            logger.warning(f"Skipping {directory} due to {metrics.detection_rate:.0%} detection rate")
            return True

        return False

    def get_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get summary of all directory metrics."""
        return {
            dir_name: {
                "success_rate": m.success_rate,
                "detection_rate": m.detection_rate,
                "total_requests": m.total_requests,
                "consecutive_failures": m.consecutive_failures,
            }
            for dir_name, m in self._metrics.items()
        }


# Global metrics tracker instance
_metrics_tracker: Optional[DirectoryMetricsTracker] = None


def get_metrics_tracker() -> DirectoryMetricsTracker:
    """Get the global directory metrics tracker."""
    global _metrics_tracker
    if _metrics_tracker is None:
        _metrics_tracker = DirectoryMetricsTracker()
    return _metrics_tracker


class CitationCrawlerSelenium(BaseSeleniumScraper):
    """
    Citation crawler using SeleniumBase (Undetected Chrome).

    This is the SeleniumBase equivalent of CitationCrawler, providing better
    anti-detection for citation directories (Yelp, BBB, YP, etc.).
    """

    def __init__(
        self,
        headless: bool = True,
        use_proxy: bool = True,  # Enabled by default with UC mode
    ):
        """
        Initialize citation crawler.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool (recommended with UC mode)
        """
        super().__init__(
            name="citation_crawler_selenium",
            tier="B",
            headless=headless,
            respect_robots=False,  # Need to scrape directories
            use_proxy=use_proxy,
            max_retries=3,
            page_timeout=30,
        )

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database storage disabled")

        # Per-directory CAPTCHA tracking
        self.directory_captcha_counts = {}

        # Directory success/failure/blocked tracking
        # - success: Found listing for business
        # - fail: No listing found (legitimate negative)
        # - skip: Directory skipped (login required, etc.)
        # - blocked: CAPTCHA or access denied (not a true negative)
        self.directory_stats = {
            d: {"success": 0, "fail": 0, "skip": 0, "blocked": 0}
            for d in CITATION_DIRECTORIES.keys()
        }

        # Request counter for session break simulation
        self._request_count = 0

        logger.info("CitationCrawlerSelenium initialized (tier=B, using enterprise browser pool)")

    def _simulate_human_behavior(self, driver, intensity: str = "normal", directory: str = None):
        """
        Simulate human browsing behavior with directory-specific tactics.

        Uses F-pattern or Z-pattern reading simulation based on directory config.

        Args:
            driver: Selenium driver
            intensity: "light", "normal", or "thorough"
            directory: Directory name for specific config (e.g., "yellowpages")
        """
        try:
            # Import F-pattern simulation
            from seo_intelligence.drivers.human_behavior import (
                simulate_f_pattern_selenium,
                simulate_z_pattern_selenium,
                click_safe_element_selenium,
                move_mouse_naturally_selenium,
            )

            # Get directory-specific config
            config = get_directory_config(directory) if directory else get_directory_config("default")

            # Override intensity from config if available
            if config.get("scroll_intensity"):
                intensity = config["scroll_intensity"]

            # Get YP-style scroll delays (3-7 variable delays)
            scroll_delays = get_scroll_delays()

            # Initial delay from config
            initial_delay = config.get("initial_delay", (2.0, 4.0))
            human_delay(min_seconds=initial_delay[0], max_seconds=initial_delay[1], jitter=0.5)

            # Get page dimensions
            try:
                viewport_height = driver.execute_script("return window.innerHeight")
                total_height = driver.execute_script("return document.body.scrollHeight")
            except Exception:
                viewport_height = 800
                total_height = 2000

            # Use reading pattern from config
            reading_pattern = config.get("reading_pattern", "basic")

            if reading_pattern == "f_pattern":
                # Use sophisticated F-pattern reading simulation
                simulate_f_pattern_selenium(driver, thorough=(intensity == "thorough"))

            elif reading_pattern == "z_pattern":
                # Use Z-pattern for simpler layouts
                simulate_z_pattern_selenium(driver)

            else:
                # Basic scrolling behavior (original logic)
                if intensity == "light":
                    scroll_amount = random.randint(100, 300)
                    driver.execute_script(f"window.scrollBy({{top: {scroll_amount}, behavior: 'smooth'}});")
                    human_delay(min_seconds=0.5, max_seconds=1.5, jitter=0.2)

                elif intensity == "normal":
                    for i, delay in enumerate(scroll_delays[:3]):
                        scroll_amount = random.randint(150, 400)
                        driver.execute_script(f"window.scrollBy({{top: {scroll_amount}, behavior: 'smooth'}});")
                        time.sleep(delay)

                        scroll_back_chance = config.get("scroll_back_chance", 0.3)
                        if random.random() < scroll_back_chance:
                            back_scroll = random.randint(50, 150)
                            driver.execute_script(f"window.scrollBy({{top: -{back_scroll}, behavior: 'smooth'}});")
                            time.sleep(random.uniform(0.3, 0.8))

                elif intensity == "thorough":
                    current_position = 0
                    for i, delay in enumerate(scroll_delays):
                        scroll_amount = random.randint(200, 500)
                        current_position += scroll_amount
                        driver.execute_script(f"window.scrollTo({{top: {current_position}, behavior: 'smooth'}});")
                        time.sleep(delay)

                        try:
                            new_height = driver.execute_script("return document.body.scrollHeight")
                            if new_height > total_height:
                                total_height = new_height
                        except Exception:
                            pass

                        scroll_back_chance = config.get("scroll_back_chance", 0.25)
                        if random.random() < scroll_back_chance:
                            back_scroll = random.randint(100, 250)
                            driver.execute_script(f"window.scrollBy({{top: -{back_scroll}, behavior: 'smooth'}});")
                            human_delay(min_seconds=0.5, max_seconds=1.0, jitter=0.2)

                        if current_position >= total_height:
                            break

                    human_delay(min_seconds=0.5, max_seconds=1.5, jitter=0.3)
                    scroll_target = random.randint(0, 300)
                    driver.execute_script(f"window.scrollTo({{top: {scroll_target}, behavior: 'smooth'}});")
                    human_delay(min_seconds=1.0, max_seconds=2.0, jitter=0.5)

            # Click random safe element if config allows
            if config.get("click_random_element") and random.random() < 0.3:
                try:
                    click_safe_element_selenium(driver)
                except Exception:
                    pass

            # Natural mouse movement if enabled
            if config.get("mouse_movement") and random.random() < 0.5:
                try:
                    viewport_width = driver.execute_script("return window.innerWidth")
                    # Move mouse to a random position
                    move_mouse_naturally_selenium(
                        driver,
                        random.randint(100, viewport_width - 100),
                        random.randint(100, viewport_height - 100)
                    )
                except Exception:
                    pass

            # Ensure minimum page time is met
            min_page_time = config.get("min_page_time", 10)
            max_page_time = config.get("max_page_time", 20)
            additional_wait = random.uniform(min_page_time * 0.3, max_page_time * 0.3)
            time.sleep(additional_wait)

            # Final reading pause
            reading_delay = get_human_reading_delay(200)
            time.sleep(min(reading_delay, 3.0))

        except Exception as e:
            logger.debug(f"Human behavior simulation skipped: {e}")

    def _maybe_take_session_break(self):
        """Simulate human taking breaks between requests."""
        self._request_count += 1
        if self._request_count >= random.randint(8, 15):
            break_duration = random.uniform(30, 90)
            logger.info(f"Taking {break_duration:.0f}s session break (human simulation)")
            time.sleep(break_duration)
            self._request_count = 0

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number to digits only."""
        if not phone:
            return ""
        return re.sub(r'\D', '', phone)

    def _normalize_name(self, name: str) -> str:
        """Normalize business name for comparison."""
        if not name:
            return ""
        normalized = name.lower().strip()
        suffixes = ['llc', 'inc', 'corp', 'co', 'company', 'ltd', 'l.l.c.', 'inc.']
        for suffix in suffixes:
            normalized = re.sub(rf'\s+{suffix}\.?$', '', normalized)
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()

    def _normalize_address(self, address: str) -> str:
        """Normalize address for comparison."""
        if not address:
            return ""
        normalized = address.lower().strip()
        replacements = {
            'street': 'st', 'avenue': 'ave', 'boulevard': 'blvd',
            'drive': 'dr', 'road': 'rd', 'lane': 'ln',
            'court': 'ct', 'place': 'pl', 'circle': 'cir',
            'north': 'n', 'south': 's', 'east': 'e', 'west': 'w',
            'suite': 'ste', 'apartment': 'apt', 'unit': '#',
        }
        for full, abbr in replacements.items():
            normalized = normalized.replace(full, abbr)
        normalized = re.sub(r'[^\w\s#]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()

    def _calculate_nap_score(
        self,
        business: BusinessInfo,
        found_name: str,
        found_address: str,
        found_phone: str,
    ) -> Tuple[bool, bool, bool, float]:
        """Calculate NAP matching score."""
        expected_name = self._normalize_name(business.name)
        expected_phone = self._normalize_phone(business.phone)
        expected_address = self._normalize_address(
            f"{business.address} {business.city} {business.state}"
        )

        actual_name = self._normalize_name(found_name)
        actual_phone = self._normalize_phone(found_phone)
        actual_address = self._normalize_address(found_address)

        # Name matching
        name_match = False
        if expected_name and actual_name:
            name_match = expected_name in actual_name or actual_name in expected_name
            if not name_match:
                expected_words = set(expected_name.split())
                actual_words = set(actual_name.split())
                overlap = len(expected_words & actual_words)
                name_match = overlap >= min(2, len(expected_words))

        # Phone matching
        phone_match = False
        if expected_phone and actual_phone:
            phone_match = expected_phone[-10:] == actual_phone[-10:]

        # Address matching
        address_match = False
        if expected_address and actual_address:
            expected_parts = set(expected_address.split())
            actual_parts = set(actual_address.split())
            overlap = len(expected_parts & actual_parts)
            address_match = overlap >= min(3, len(expected_parts) // 2 + 1)

        # Calculate score
        score = 0.0
        weights = {'name': 0.4, 'address': 0.3, 'phone': 0.3}

        if name_match:
            score += weights['name']
        if address_match:
            score += weights['address']
        if phone_match:
            score += weights['phone']

        return name_match, address_match, phone_match, score

    def _extract_listing_info(
        self,
        html: str,
        directory: str,
        business: BusinessInfo,
    ) -> Optional[CitationResult]:
        """Extract listing information from directory search results."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        dir_info = CITATION_DIRECTORIES.get(directory, {})

        result = CitationResult(
            directory=directory,
            directory_url=dir_info.get("name", directory),
        )

        page_text = soup.get_text(separator=' ', strip=True)

        # Debug: Log page text length
        logger.debug(f"Page text length: {len(page_text)} chars")

        # Look for phone numbers
        phone_patterns = [r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}']
        found_phones = []
        for pattern in phone_patterns:
            found_phones.extend(re.findall(pattern, page_text))

        # Check if business name appears
        normalized_business = self._normalize_name(business.name)
        normalized_page = page_text.lower()

        # Debug: Log what we're searching for
        logger.debug(f"Looking for '{normalized_business}' in page (first 500 chars: {page_text[:500]}...)")

        if normalized_business in normalized_page:
            result.is_listed = True

            found_address = ""
            found_phone = ""

            for phone in found_phones:
                if self._normalize_phone(phone) == self._normalize_phone(business.phone):
                    found_phone = phone
                    result.phone_match = True
                    break

            name_match, address_match, phone_match, nap_score = self._calculate_nap_score(
                business, business.name, found_address, found_phone
            )

            result.name_match = True
            result.address_match = address_match
            result.phone_match = phone_match
            result.nap_score = nap_score

            # Look for reviews
            review_patterns = [r'(\d+)\s*reviews?', r'(\d+)\s*ratings?']
            for pattern in review_patterns:
                match = re.search(pattern, page_text, re.I)
                if match:
                    result.has_reviews = True
                    result.review_count = int(match.group(1))
                    break

            # Look for rating
            rating_patterns = [
                r'(\d\.?\d?)\s*(?:out of 5|stars?|/5)',
                r'rating[:\s]+(\d\.?\d?)',
            ]
            for pattern in rating_patterns:
                match = re.search(pattern, page_text, re.I)
                if match:
                    try:
                        result.rating = float(match.group(1))
                    except ValueError:
                        pass
                    break

        return result

    def _calculate_business_source_quality_score(
        self,
        name: Optional[str],
        phone: Optional[str],
        street: Optional[str],
        city: Optional[str],
        state: Optional[str],
        zip_code: Optional[str],
        website: Optional[str],
        is_verified: bool,
        rating_count: Optional[int]
    ) -> int:
        """Calculate data quality score (0-100)."""
        score = 0

        if name and len(name) > 0:
            score += 15
        if phone and len(phone) > 0:
            score += 15
        if street and len(street) > 0:
            score += 10
        if city and len(city) > 0:
            score += 10
        if state and len(state) > 0:
            score += 5
        if zip_code and len(zip_code) > 0:
            score += 5
        if website and len(website) > 0:
            score += 10
        if rating_count is not None and rating_count > 0:
            score += 10
        if is_verified:
            score += 20

        return score

    def _save_citation(
        self,
        session: Session,
        business: BusinessInfo,
        result: CitationResult,
    ) -> int:
        """Save citation to database."""
        metadata = {
            "has_reviews": result.has_reviews,
            "review_count": result.review_count,
            "rating": result.rating,
            "is_present": result.is_listed,
            "name_match": result.name_match,
            "address_match": result.address_match,
            "phone_match": result.phone_match,
            "scraper": "selenium",  # Mark as Selenium-scraped
        }
        metadata.update(result.metadata)

        # Check for existing citation
        existing = session.execute(
            text("""
                SELECT citation_id FROM citations
                WHERE business_name = :name AND directory_name = :directory
            """),
            {"name": business.name, "directory": result.directory}
        )
        row = existing.fetchone()

        if row:
            session.execute(
                text("""
                    UPDATE citations SET
                        listing_url = :listing_url,
                        nap_match_score = :nap_score,
                        last_verified_at = NOW(),
                        metadata = CAST(:metadata AS jsonb)
                    WHERE citation_id = :id
                """),
                {
                    "id": row[0],
                    "listing_url": result.listing_url,
                    "nap_score": result.nap_score,
                    "metadata": json.dumps(metadata),
                }
            )
            session.commit()
            return row[0]

        # Create new citation
        new_result = session.execute(
            text("""
                INSERT INTO citations (
                    business_name, directory_name, directory_url, listing_url,
                    address, phone, nap_match_score, has_website_link,
                    discovered_at, last_verified_at, metadata
                ) VALUES (
                    :name, :directory, :directory_url, :listing_url,
                    :address, :phone, :nap_score, :has_website_link,
                    NOW(), NOW(), CAST(:metadata AS jsonb)
                )
                ON CONFLICT (directory_name, listing_url) DO UPDATE SET
                    nap_match_score = :nap_score,
                    last_verified_at = NOW(),
                    metadata = CAST(:metadata AS jsonb)
                RETURNING citation_id
            """),
            {
                "name": business.name,
                "directory": result.directory,
                "directory_url": f"https://{result.directory.lower().replace(' ', '')}.com",
                "listing_url": result.listing_url,
                "address": business.address,
                "phone": business.phone,
                "nap_score": result.nap_score,
                "has_website_link": bool(business.website),
                "metadata": json.dumps(metadata),
            }
        )

        citation_id = new_result.fetchone()[0]
        session.commit()
        return citation_id

    def _get_progressive_quarantine_minutes(self, directory: str) -> int:
        """Get progressive quarantine duration based on CAPTCHA count."""
        count = self.directory_captcha_counts.get(directory, 0)
        tiers = [60, 120, 240, 480, 1440]
        tier_index = min(count, len(tiers) - 1)
        return tiers[tier_index]

    def check_directory(
        self,
        business: BusinessInfo,
        directory: str,
    ) -> Optional[CitationResult]:
        """
        Check a single directory for business listing using SeleniumBase UC.

        Args:
            business: Business information
            directory: Directory key from CITATION_DIRECTORIES

        Returns:
            CitationResult or None
        """
        if directory not in CITATION_DIRECTORIES:
            logger.warning(f"Unknown directory: {directory}")
            return None

        dir_info = CITATION_DIRECTORIES[directory]

        # Get metrics tracker for adaptive behavior
        metrics_tracker = get_metrics_tracker()

        # Check if directory should be skipped due to high detection rate
        if metrics_tracker.should_skip_directory(directory):
            self.directory_stats[directory]["skip"] += 1
            return CitationResult(
                directory=directory,
                directory_url=dir_info["name"],
                is_listed=False,
                metadata={"skipped": True, "skip_reason": "high_detection_rate"}
            )

        # Check if directory should be skipped
        if dir_info.get("skip", False) or directory in SKIP_DIRECTORIES:
            logger.info(f"Skipping {directory}: login required")
            self.directory_stats[directory]["skip"] += 1
            return CitationResult(
                directory=directory,
                directory_url=dir_info["name"],
                is_listed=False,
                metadata={"skipped": True, "skip_reason": "login_required"}
            )

        # Check domain quarantine
        domain = urlparse(dir_info["search_url"]).netloc
        if self.domain_quarantine.is_quarantined(domain):
            quarantine_end = self.domain_quarantine.get_quarantine_end(domain)
            logger.info(f"Skipping {directory}: quarantined until {quarantine_end}")
            self.directory_stats[directory]["skip"] += 1
            return CitationResult(
                directory=directory,
                directory_url=dir_info["name"],
                is_listed=False,
                metadata={"skipped": True, "skip_reason": f"quarantined until {quarantine_end}"}
            )

        # Build location
        location = ""
        if business.city and business.state:
            location = f"{business.city}, {business.state}"
        elif business.city:
            location = business.city
        elif business.state:
            location = business.state
        elif business.zip_code:
            location = business.zip_code
        else:
            location = "USA"

        zip_code = business.zip_code or "10001"

        # Format URL
        try:
            search_url = dir_info["search_url"].format(
                business=quote_plus(business.name),
                location=quote_plus(location),
                zip=quote_plus(zip_code),
            )
        except KeyError:
            search_url = dir_info["search_url"].replace("{business}", quote_plus(business.name))
            search_url = search_url.replace("{location}", quote_plus(location))
            search_url = search_url.replace("{zip}", quote_plus(zip_code))

        driver_type = dir_info.get("driver_type", "generic")
        logger.info(f"Checking {dir_info['name']} for '{business.name}' [Enterprise Pool + UC]")

        # Check for session break (human simulation)
        self._maybe_take_session_break()

        try:
            # Use browser pool (already has residential proxies, warmup, stealth)
            # Pass directory as site to get proper target group mapping
            with self.browser_session(directory) as driver:
                # Adaptive delay before navigation (increases if detection rate is high)
                adaptive_delay = metrics_tracker.get_adaptive_delay(directory)
                human_delay(min_seconds=adaptive_delay[0], max_seconds=adaptive_delay[1], jitter=0.5)

                # Navigate to search URL
                driver.get(search_url)

                # Wait for page to load with human-like timing
                config = get_directory_config(directory)
                initial_delay = config.get("initial_delay", (3.0, 6.0))
                human_delay(min_seconds=initial_delay[0], max_seconds=initial_delay[1], jitter=1.0)

                # Simulate human behavior with directory-specific scrolling
                self._simulate_human_behavior(driver, intensity="thorough", directory=directory)

                # Get page source
                html = driver.page_source

                if not html or len(html) < 1000:
                    logger.warning(f"Failed to fetch {dir_info['name']}")
                    self.directory_stats[directory]["fail"] += 1
                    metrics_tracker.get_metrics(directory).record_timeout()
                    return None

                # Check for CAPTCHA
                html_lower = html.lower()
                captcha_indicators = [
                    "captcha", "recaptcha", "hcaptcha", "challenge",
                    "verify you are human", "are you a robot",
                    "unusual traffic", "automated requests",
                    "access denied", "blocked"
                ]

                if any(indicator in html_lower for indicator in captcha_indicators):
                    self.directory_captcha_counts[directory] = \
                        self.directory_captcha_counts.get(directory, 0) + 1
                    quarantine_minutes = self._get_progressive_quarantine_minutes(directory)

                    self.domain_quarantine.quarantine_domain(
                        domain=domain,
                        reason="CAPTCHA_DETECTED",
                        duration_minutes=quarantine_minutes
                    )

                    # Log CAPTCHA detection (browser pool handles proxy rotation internally)
                    logger.warning(
                        f"CAPTCHA detected on {directory} - quarantining domain for {quarantine_minutes} minutes"
                    )

                    # Track as blocked, not fail - CAPTCHA is not a true negative
                    self.directory_stats[directory]["blocked"] += 1
                    metrics_tracker.get_metrics(directory).record_captcha()

                    return CitationResult(
                        directory=directory,
                        directory_url=dir_info["name"],
                        is_listed=False,
                        metadata={"error": "CAPTCHA_BLOCKED", "quarantine_minutes": quarantine_minutes}
                    )

                # Extract listing info
                result = self._extract_listing_info(html, directory, business)

                if result and self.engine:
                    with Session(self.engine) as session:
                        self._save_citation(session, business, result)

                # Track stats
                if result and result.is_listed:
                    self.directory_stats[directory]["success"] += 1
                    metrics_tracker.get_metrics(directory).record_success()
                    logger.info(f"SUCCESS: Found listing on {directory} for '{business.name}'")
                else:
                    self.directory_stats[directory]["fail"] += 1
                    # Not a detection failure, just no listing found
                    metrics_tracker.get_metrics(directory).record_success()

                return result

        except Exception as e:
            logger.error(f"Error checking {directory}: {e}")
            self.directory_stats[directory]["fail"] += 1
            metrics_tracker.get_metrics(directory).record_block()
            return None

    def check_all_directories(
        self,
        business: BusinessInfo,
        directories: Optional[List[str]] = None,
    ) -> Dict[str, CitationResult]:
        """Check all directories for a business."""
        directories = directories or list(CITATION_DIRECTORIES.keys())
        results = {}

        for directory in directories:
            result = self.check_directory(business, directory)
            if result:
                results[directory] = result

        return results

    def run(
        self,
        businesses: List[BusinessInfo],
        directories: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run citation crawler for multiple businesses.

        Args:
            businesses: List of business information
            directories: Specific directories to check

        Returns:
            dict: Results summary
        """
        task_logger = get_task_logger()
        directories = directories or list(CITATION_DIRECTORIES.keys())

        results = {
            "total_businesses": len(businesses),
            "total_directories": len(directories),
            "total_checks": len(businesses) * len(directories),
            "citations_found": 0,
            "nap_accurate": 0,
            "average_nap_score": 0.0,
            "scraper": "selenium",
        }

        nap_scores = []

        with task_logger.log_task("citation_crawler_selenium", "scraper", {"business_count": len(businesses)}) as task:
            for business in businesses:
                for directory in directories:
                    task.increment_processed()

                    result = self.check_directory(business, directory)

                    if result:
                        if result.is_listed:
                            results["citations_found"] += 1
                            task.increment_created()

                            if result.nap_score >= 0.7:
                                results["nap_accurate"] += 1

                            nap_scores.append(result.nap_score)

        if nap_scores:
            results["average_nap_score"] = sum(nap_scores) / len(nap_scores)

        logger.info(
            f"Citation crawl complete: {results['citations_found']} citations found "
            f"across {results['total_businesses']} businesses"
        )

        return results


# Module-level singleton
_citation_crawler_selenium_instance = None


def get_citation_crawler_selenium(**kwargs) -> CitationCrawlerSelenium:
    """Get or create the singleton CitationCrawlerSelenium instance."""
    global _citation_crawler_selenium_instance

    if _citation_crawler_selenium_instance is None:
        _citation_crawler_selenium_instance = CitationCrawlerSelenium(**kwargs)

    return _citation_crawler_selenium_instance


def main():
    """Demo/CLI interface for citation crawler."""
    import argparse

    parser = argparse.ArgumentParser(description="Citation Crawler (SeleniumBase)")
    parser.add_argument("--name", "-n", help="Business name")
    parser.add_argument("--address", "-a", help="Business address")
    parser.add_argument("--city", "-c", help="City")
    parser.add_argument("--state", "-s", help="State")
    parser.add_argument("--zip", "-z", help="ZIP code")
    parser.add_argument("--phone", "-p", help="Phone number")
    parser.add_argument("--directory", "-d", help="Specific directory to check")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("Citation Crawler Demo Mode (SeleniumBase)")
        logger.info("=" * 60)
        logger.info("")
        logger.info("This crawler uses SeleniumBase Undetected Chrome for better")
        logger.info("anti-detection than the Playwright version.")
        logger.info("")
        logger.info("Supported directories:")
        for key, info in CITATION_DIRECTORIES.items():
            skip = " [SKIP]" if info.get("skip") else ""
            logger.info(f"  - {key}: {info['name']} (Tier {info['tier']}){skip}")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python citation_crawler_selenium.py --name 'ABC Pressure Washing' --city 'Austin' --state 'TX'")
        logger.info("")
        logger.info("=" * 60)
        return

    if not args.name:
        parser.print_help()
        return

    business = BusinessInfo(
        name=args.name,
        address=args.address or "",
        city=args.city or "",
        state=args.state or "",
        zip_code=args.zip or "",
        phone=args.phone or "",
    )

    crawler = get_citation_crawler_selenium()

    if args.directory:
        result = crawler.check_directory(business, args.directory)
        if result:
            logger.info(f"Listed: {result.is_listed}")
            logger.info(f"NAP Score: {result.nap_score:.2f}")
    else:
        results = crawler.check_all_directories(business)
        for directory, result in results.items():
            status = "FOUND" if result.is_listed else "NOT FOUND"
            logger.info(f"{directory}: {status} (NAP: {result.nap_score:.2f})")


if __name__ == "__main__":
    main()
