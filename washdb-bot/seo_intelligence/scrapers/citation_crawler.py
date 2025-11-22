"""
Citation Crawler Module

Checks and tracks business citations across directories.

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
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from dataclasses import dataclass, field, asdict

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_scraper import BaseScraper
from seo_intelligence.services import get_task_logger, get_change_manager
from runner.logging_setup import get_logger
from db.models import Company, BusinessSource

# Load environment
load_dotenv()

logger = get_logger("citation_crawler")


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
    nap_score: float = 0.0  # 0-1 score for NAP accuracy
    has_reviews: bool = False
    review_count: int = 0
    rating: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Major citation directories to check
CITATION_DIRECTORIES = {
    "google_business": {
        "name": "Google Business Profile",
        "search_url": "https://www.google.com/search?q={business}+{location}",
        "tier": "A",  # Google requires Tier A
    },
    "yelp": {
        "name": "Yelp",
        "search_url": "https://www.yelp.com/search?find_desc={business}&find_loc={location}",
        "tier": "B",
    },
    "yellowpages": {
        "name": "Yellow Pages",
        "search_url": "https://www.yellowpages.com/search?search_terms={business}&geo_location_terms={location}",
        "tier": "B",
    },
    "bbb": {
        "name": "Better Business Bureau",
        "search_url": "https://www.bbb.org/search?find_text={business}&find_loc={location}",
        "tier": "B",
    },
    "facebook": {
        "name": "Facebook",
        "search_url": "https://www.facebook.com/search/pages?q={business}%20{location}",
        "tier": "B",
    },
    "angies_list": {
        "name": "Angi (Angie's List)",
        "search_url": "https://www.angi.com/companylist/{location}/{business}.htm",
        "tier": "B",
    },
    "thumbtack": {
        "name": "Thumbtack",
        "search_url": "https://www.thumbtack.com/search/{business}/{location}",
        "tier": "B",
    },
    "homeadvisor": {
        "name": "HomeAdvisor",
        "search_url": "https://www.homeadvisor.com/rated.{business}.{location}.html",
        "tier": "B",
    },
    "mapquest": {
        "name": "MapQuest",
        "search_url": "https://www.mapquest.com/search/{business}+{location}",
        "tier": "C",
    },
    "manta": {
        "name": "Manta",
        "search_url": "https://www.manta.com/search?search_source=nav&search={business}&search_location={location}",
        "tier": "C",
    },
}


class CitationCrawler(BaseScraper):
    """
    Crawler for checking business citations across directories.

    Verifies presence on major directories and checks NAP consistency.
    """

    def __init__(
        self,
        headless: bool = True,
        use_proxy: bool = True,
    ):
        """
        Initialize citation crawler.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool
        """
        super().__init__(
            name="citation_crawler",
            tier="B",  # Default tier (individual checks may override)
            headless=headless,
            respect_robots=True,
            use_proxy=use_proxy,
            max_retries=2,
            page_timeout=30000,
        )

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database storage disabled")

        logger.info("CitationCrawler initialized (tier=B)")

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number to digits only."""
        if not phone:
            return ""
        return re.sub(r'\D', '', phone)

    def _normalize_name(self, name: str) -> str:
        """Normalize business name for comparison."""
        if not name:
            return ""
        # Lowercase, remove common suffixes, extra whitespace
        normalized = name.lower().strip()
        suffixes = ['llc', 'inc', 'corp', 'co', 'company', 'ltd', 'l.l.c.', 'inc.']
        for suffix in suffixes:
            normalized = re.sub(rf'\s+{suffix}\.?$', '', normalized)
        # Remove punctuation and extra spaces
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()

    def _normalize_address(self, address: str) -> str:
        """Normalize address for comparison."""
        if not address:
            return ""
        normalized = address.lower().strip()
        # Common abbreviations
        replacements = {
            'street': 'st', 'avenue': 'ave', 'boulevard': 'blvd',
            'drive': 'dr', 'road': 'rd', 'lane': 'ln',
            'court': 'ct', 'place': 'pl', 'circle': 'cir',
            'north': 'n', 'south': 's', 'east': 'e', 'west': 'w',
            'suite': 'ste', 'apartment': 'apt', 'unit': '#',
        }
        for full, abbr in replacements.items():
            normalized = normalized.replace(full, abbr)
        # Remove punctuation and extra spaces
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
        """
        Calculate NAP matching score.

        Args:
            business: Expected business info
            found_name: Name found in listing
            found_address: Address found in listing
            found_phone: Phone found in listing

        Returns:
            Tuple of (name_match, address_match, phone_match, overall_score)
        """
        # Normalize for comparison
        expected_name = self._normalize_name(business.name)
        expected_phone = self._normalize_phone(business.phone)
        expected_address = self._normalize_address(
            f"{business.address} {business.city} {business.state}"
        )

        actual_name = self._normalize_name(found_name)
        actual_phone = self._normalize_phone(found_phone)
        actual_address = self._normalize_address(found_address)

        # Name matching (fuzzy - check if expected is contained)
        name_match = False
        if expected_name and actual_name:
            name_match = expected_name in actual_name or actual_name in expected_name
            # Also check word overlap
            if not name_match:
                expected_words = set(expected_name.split())
                actual_words = set(actual_name.split())
                overlap = len(expected_words & actual_words)
                name_match = overlap >= min(2, len(expected_words))

        # Phone matching (exact after normalization)
        phone_match = False
        if expected_phone and actual_phone:
            phone_match = expected_phone[-10:] == actual_phone[-10:]  # Compare last 10 digits

        # Address matching (fuzzy)
        address_match = False
        if expected_address and actual_address:
            # Check if key parts match
            expected_parts = set(expected_address.split())
            actual_parts = set(actual_address.split())
            overlap = len(expected_parts & actual_parts)
            address_match = overlap >= min(3, len(expected_parts) // 2 + 1)

        # Calculate overall score (weighted)
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
        """
        Extract listing information from directory search results.

        Args:
            html: Page HTML
            directory: Directory key
            business: Expected business info

        Returns:
            CitationResult or None
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        dir_info = CITATION_DIRECTORIES.get(directory, {})

        result = CitationResult(
            directory=directory,
            directory_url=dir_info.get("name", directory),
        )

        # Generic extraction logic - look for business info patterns
        page_text = soup.get_text(separator=' ', strip=True)

        # Look for phone numbers
        phone_patterns = [
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        ]
        found_phones = []
        for pattern in phone_patterns:
            found_phones.extend(re.findall(pattern, page_text))

        # Check if our business name appears
        normalized_business = self._normalize_name(business.name)
        normalized_page = page_text.lower()

        if normalized_business in normalized_page:
            result.is_listed = True

            # Try to find associated info
            found_address = ""
            found_phone = ""

            # Check for address patterns near business name
            for phone in found_phones:
                if self._normalize_phone(phone) == self._normalize_phone(business.phone):
                    found_phone = phone
                    result.phone_match = True
                    break

            # Calculate NAP score
            name_match, address_match, phone_match, nap_score = self._calculate_nap_score(
                business,
                business.name,  # Name confirmed by presence
                found_address,
                found_phone,
            )

            result.name_match = True  # Confirmed by finding name
            result.address_match = address_match
            result.phone_match = phone_match
            result.nap_score = nap_score

            # Look for review indicators
            review_patterns = [
                r'(\d+)\s*reviews?',
                r'(\d+)\s*ratings?',
            ]
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
        """Calculate data quality score (0-100) based on completeness and verification."""
        score = 0

        # Base NAP completeness (60 points max)
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

        # Additional data (20 points max)
        if website and len(website) > 0:
            score += 10
        if rating_count is not None and rating_count > 0:
            score += 10

        # Verification bonus (20 points)
        if is_verified:
            score += 20

        return score

    def _create_business_source_from_citation(
        self,
        session: Session,
        company_id: int,
        business: BusinessInfo,
        result: CitationResult,
    ) -> None:
        """
        Create or update a BusinessSource record from citation data.

        Args:
            session: Database session
            company_id: ID of the Company record
            business: Business information
            result: Citation result with directory info
        """
        # Determine source_type from directory key
        source_type_map = {
            "google_business": "google",
            "yelp": "yelp",
            "yellowpages": "yp",
            "bbb": "bbb",
            "facebook": "facebook",
            "angies_list": "angi",
            "thumbtack": "thumbtack",
            "homeadvisor": "homeadvisor",
            "mapquest": "mapquest",
            "manta": "manta",
        }
        source_type = source_type_map.get(result.directory, result.directory)

        # Calculate quality score
        quality_score = self._calculate_business_source_quality_score(
            name=business.name if result.is_listed else None,
            phone=business.phone if result.phone_match else None,
            street=business.address if result.address_match else None,
            city=business.city,
            state=business.state,
            zip_code=business.zip_code,
            website=business.website,
            is_verified=False,  # Citations don't typically have verification status
            rating_count=result.review_count if result.has_reviews else None
        )

        # Determine confidence level
        if quality_score >= 80 or result.nap_score >= 0.8:
            confidence = "high"
        elif quality_score >= 50 or result.nap_score >= 0.5:
            confidence = "medium"
        else:
            confidence = "low"

        # Build metadata
        metadata = {
            "directory_name": result.directory,
            "nap_match_score": result.nap_score,
            "name_match": result.name_match,
            "address_match": result.address_match,
            "phone_match": result.phone_match,
            "has_reviews": result.has_reviews,
            "is_present": result.is_listed,
        }
        metadata.update(result.metadata)

        # Check if BusinessSource already exists for this company + source_type
        existing_bs = session.execute(
            select(BusinessSource).where(
                BusinessSource.company_id == company_id,
                BusinessSource.source_type == source_type
            )
        ).scalar_one_or_none()

        if existing_bs:
            # Update existing BusinessSource
            if result.is_listed:
                existing_bs.source_name = result.directory_url
                existing_bs.profile_url = result.listing_url
                existing_bs.name = business.name
                existing_bs.phone = business.phone if result.phone_match else None
                existing_bs.address_raw = business.address if result.address_match else None
                existing_bs.street = business.address if result.address_match else None
                existing_bs.city = business.city
                existing_bs.state = business.state
                existing_bs.zip_code = business.zip_code
                existing_bs.website = business.website
                existing_bs.rating_value = result.rating
                existing_bs.rating_count = result.review_count if result.has_reviews else None
                existing_bs.is_verified = False
                existing_bs.listing_status = "found"
                existing_bs.data_quality_score = quality_score
                existing_bs.confidence_level = confidence
                existing_bs.metadata = metadata
            else:
                existing_bs.listing_status = "not_found"
                existing_bs.metadata = metadata

            logger.debug(f"Updated BusinessSource for company_id={company_id}, source={source_type}")
        else:
            # Create new BusinessSource record only if listed
            if result.is_listed:
                business_source = BusinessSource(
                    company_id=company_id,
                    source_type=source_type,
                    source_name=result.directory_url,
                    source_url=CITATION_DIRECTORIES.get(result.directory, {}).get("search_url", ""),
                    profile_url=result.listing_url,
                    name=business.name,
                    phone=business.phone if result.phone_match else None,
                    phone_e164=None,  # TODO: Implement E.164 normalization
                    address_raw=business.address if result.address_match else None,
                    street=business.address if result.address_match else None,
                    city=business.city,
                    state=business.state,
                    zip_code=business.zip_code,
                    website=business.website,
                    categories=None,  # Citations don't typically provide categories
                    rating_value=result.rating,
                    rating_count=result.review_count if result.has_reviews else None,
                    is_verified=False,
                    listing_status="found",
                    data_quality_score=quality_score,
                    confidence_level=confidence,
                    metadata=metadata
                )

                session.add(business_source)
                logger.debug(f"Created BusinessSource for company_id={company_id}, source={source_type}, quality={quality_score}")

    def _save_citation(
        self,
        session: Session,
        business: BusinessInfo,
        result: CitationResult,
    ) -> int:
        """
        Save citation to database.

        Args:
            session: Database session
            business: Business info
            result: Citation check result

        Returns:
            int: Citation ID
        """
        # Build metadata
        metadata = {
            "has_reviews": result.has_reviews,
            "review_count": result.review_count,
            "rating": result.rating,
        }
        metadata.update(result.metadata)

        # Try to find company by website or name for BusinessSource creation
        company = None
        if business.website:
            # Try to find by website first
            company = session.execute(
                select(Company).where(Company.website == business.website)
            ).scalar_one_or_none()

        if not company and business.name:
            # Fallback: try to find by name (case-insensitive, fuzzy match)
            company = session.execute(
                select(Company).where(Company.name.ilike(f"%{business.name}%"))
            ).first()
            if company:
                company = company[0]  # Extract from tuple

        # Check if citation exists
        existing = session.execute(
            text("""
                SELECT citation_id FROM citations
                WHERE business_name = :name AND directory_name = :directory
            """),
            {"name": business.name, "directory": result.directory}
        )
        row = existing.fetchone()

        if row:
            # Update existing
            session.execute(
                text("""
                    UPDATE citations SET
                        is_present = :is_present,
                        listing_url = :listing_url,
                        nap_match_score = :nap_score,
                        name_match = :name_match,
                        address_match = :address_match,
                        phone_match = :phone_match,
                        last_checked_at = NOW(),
                        metadata = :metadata::jsonb
                    WHERE citation_id = :id
                """),
                {
                    "id": row[0],
                    "is_present": result.is_listed,
                    "listing_url": result.listing_url,
                    "nap_score": result.nap_score,
                    "name_match": result.name_match,
                    "address_match": result.address_match,
                    "phone_match": result.phone_match,
                    "metadata": json.dumps(metadata),
                }
            )

            # Create/update BusinessSource if we found a company
            if company:
                try:
                    self._create_business_source_from_citation(
                        session=session,
                        company_id=company.id,
                        business=business,
                        result=result
                    )
                except Exception as bs_error:
                    logger.warning(f"Failed to create BusinessSource for {business.name}: {bs_error}")

            # Propose change for NAP mismatches (governance integration)
            if result.nap_score < 0.5 and result.is_listed:
                try:
                    change_manager = get_change_manager()
                    change_manager.propose_change(
                        change_type='citation_update',
                        entity_type='directory',
                        entity_id=f"{result.directory}:{business.name}",
                        proposed_value={
                            'listing_url': result.listing_url,
                            'directory': result.directory,
                        },
                        current_value={
                            'nap_score': result.nap_score,
                            'name_match': result.name_match,
                            'address_match': result.address_match,
                            'phone_match': result.phone_match,
                        },
                        reason=f"NAP inconsistency detected on {result.directory} (score: {result.nap_score:.2f})",
                        priority='medium',
                        source='citation_crawler',
                        metadata={
                            'citation_id': row[0],
                            'business_name': business.name,
                            'directory_name': result.directory,
                            'listing_url': result.listing_url,
                            'nap_score': result.nap_score,
                            'mismatches': {
                                'name': not result.name_match,
                                'address': not result.address_match,
                                'phone': not result.phone_match,
                            }
                        }
                    )
                    logger.info(f"Proposed NAP fix for {business.name} on {result.directory} (score: {result.nap_score:.2f})")
                except Exception as e:
                    logger.error(f"Error proposing citation change for {business.name}: {e}")

            session.commit()
            return row[0]

        # Create new citation
        new_result = session.execute(
            text("""
                INSERT INTO citations (
                    business_name, directory_name, is_present, listing_url,
                    nap_match_score, name_match, address_match, phone_match,
                    last_checked_at, metadata
                ) VALUES (
                    :name, :directory, :is_present, :listing_url,
                    :nap_score, :name_match, :address_match, :phone_match,
                    NOW(), :metadata::jsonb
                )
                RETURNING citation_id
            """),
            {
                "name": business.name,
                "directory": result.directory,
                "is_present": result.is_listed,
                "listing_url": result.listing_url,
                "nap_score": result.nap_score,
                "name_match": result.name_match,
                "address_match": result.address_match,
                "phone_match": result.phone_match,
                "metadata": json.dumps(metadata),
            }
        )

        # Create/update BusinessSource if we found a company
        if company:
            try:
                self._create_business_source_from_citation(
                    session=session,
                    company_id=company.id,
                    business=business,
                    result=result
                )
            except Exception as bs_error:
                logger.warning(f"Failed to create BusinessSource for {business.name}: {bs_error}")

        # Get the new citation_id before commit (for change proposal)
        citation_id = new_result.fetchone()[0]

        # Propose change for NAP mismatches (governance integration)
        if result.nap_score < 0.5 and result.is_listed:
            try:
                change_manager = get_change_manager()
                change_manager.propose_change(
                    change_type='citation_update',
                    entity_type='directory',
                    entity_id=f"{result.directory}:{business.name}",
                    proposed_value={
                        'listing_url': result.listing_url,
                        'directory': result.directory,
                    },
                    current_value={
                        'nap_score': result.nap_score,
                        'name_match': result.name_match,
                        'address_match': result.address_match,
                        'phone_match': result.phone_match,
                    },
                    reason=f"NAP inconsistency detected on {result.directory} (score: {result.nap_score:.2f})",
                    priority='medium',
                    source='citation_crawler',
                    metadata={
                        'citation_id': citation_id,
                        'business_name': business.name,
                        'directory_name': result.directory,
                        'listing_url': result.listing_url,
                        'nap_score': result.nap_score,
                        'mismatches': {
                            'name': not result.name_match,
                            'address': not result.address_match,
                            'phone': not result.phone_match,
                        }
                    }
                )
                logger.info(f"Proposed NAP fix for {business.name} on {result.directory} (score: {result.nap_score:.2f})")
            except Exception as e:
                logger.error(f"Error proposing citation change for {business.name}: {e}")

        session.commit()

        return citation_id

    def check_directory(
        self,
        business: BusinessInfo,
        directory: str,
    ) -> Optional[CitationResult]:
        """
        Check a single directory for business listing.

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
        location = f"{business.city}, {business.state}" if business.city else business.state
        location = location or business.zip_code or ""

        search_url = dir_info["search_url"].format(
            business=quote_plus(business.name),
            location=quote_plus(location),
        )

        logger.info(f"Checking {dir_info['name']} for '{business.name}'")

        try:
            with self.browser_session() as (browser, context, page):
                html = self.fetch_page(
                    url=search_url,
                    page=page,
                    wait_for="domcontentloaded",
                    extra_wait=2.0,
                )

                if not html:
                    logger.warning(f"Failed to fetch {dir_info['name']}")
                    return None

                result = self._extract_listing_info(html, directory, business)

                if result and self.engine:
                    with Session(self.engine) as session:
                        self._save_citation(session, business, result)

                return result

        except Exception as e:
            logger.error(f"Error checking {directory}: {e}")
            return None

    def check_all_directories(
        self,
        business: BusinessInfo,
        directories: Optional[List[str]] = None,
    ) -> Dict[str, CitationResult]:
        """
        Check all directories for a business.

        Args:
            business: Business information
            directories: Specific directories to check (None = all)

        Returns:
            Dict of directory -> CitationResult
        """
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
        }

        nap_scores = []

        with task_logger.log_task("citation_crawler", "scraper", {"business_count": len(businesses)}) as task:
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
_citation_crawler_instance = None


def get_citation_crawler(**kwargs) -> CitationCrawler:
    """Get or create the singleton CitationCrawler instance."""
    global _citation_crawler_instance

    if _citation_crawler_instance is None:
        _citation_crawler_instance = CitationCrawler(**kwargs)

    return _citation_crawler_instance


def main():
    """Demo/CLI interface for citation crawler."""
    import argparse

    parser = argparse.ArgumentParser(description="Citation Crawler")
    parser.add_argument("--name", "-n", help="Business name")
    parser.add_argument("--address", "-a", help="Business address")
    parser.add_argument("--city", "-c", help="City")
    parser.add_argument("--state", "-s", help="State")
    parser.add_argument("--phone", "-p", help="Phone number")
    parser.add_argument("--directory", "-d", help="Specific directory to check")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("Citation Crawler Demo Mode")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Supported directories:")
        for key, info in CITATION_DIRECTORIES.items():
            logger.info(f"  - {key}: {info['name']} (Tier {info['tier']})")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python citation_crawler.py --name 'ABC Pressure Washing' --city 'Austin' --state 'TX'")
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
        phone=args.phone or "",
    )

    crawler = get_citation_crawler()

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
