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
- Verify NAP consistency across listings
- Track last verified date for freshness
"""

import os
import re
import json
import time
import random
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

        # Directory success/failure tracking
        self.directory_stats = {
            d: {"success": 0, "fail": 0, "skip": 0}
            for d in CITATION_DIRECTORIES.keys()
        }

        logger.info("CitationCrawlerSelenium initialized (tier=B, SeleniumBase UC mode)")

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
        logger.info(f"Checking {dir_info['name']} for '{business.name}' [SeleniumBase UC]")

        try:
            with self.browser_session(driver_type) as driver:
                # Human delay before navigation
                time.sleep(random.uniform(1.5, 3.0))

                # Navigate to search URL
                driver.get(search_url)

                # Wait for page to load
                time.sleep(random.uniform(2, 4))

                # Simulate human behavior
                self._simulate_human_behavior(driver, intensity="normal")

                # Get page source
                html = driver.page_source

                if not html or len(html) < 1000:
                    logger.warning(f"Failed to fetch {dir_info['name']}")
                    self.directory_stats[directory]["fail"] += 1
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

                    logger.warning(
                        f"CAPTCHA detected on {directory} - quarantining for {quarantine_minutes} minutes"
                    )
                    self.directory_stats[directory]["fail"] += 1

                    return CitationResult(
                        directory=directory,
                        directory_url=dir_info["name"],
                        is_listed=False,
                        metadata={"error": "CAPTCHA_DETECTED", "quarantine_minutes": quarantine_minutes}
                    )

                # Extract listing info
                result = self._extract_listing_info(html, directory, business)

                if result and self.engine:
                    with Session(self.engine) as session:
                        self._save_citation(session, business, result)

                # Track stats
                if result and result.is_listed:
                    self.directory_stats[directory]["success"] += 1
                    logger.info(f"SUCCESS: Found listing on {directory} for '{business.name}'")
                else:
                    self.directory_stats[directory]["fail"] += 1

                return result

        except Exception as e:
            logger.error(f"Error checking {directory}: {e}")
            self.directory_stats[directory]["fail"] += 1
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
