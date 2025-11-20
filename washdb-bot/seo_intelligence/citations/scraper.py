"""
Citations scraper with NAP extraction and review signals.

Scrapes directory listings to track:
- NAP (Name, Address, Phone) consistency
- Business hours
- Review ratings and counts
- Citation health
"""
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Citation
from ..infrastructure.http_client import get_with_retry
from ..infrastructure.task_logger import task_logger

logger = logging.getLogger(__name__)


class CitationsScraper:
    """
    Scrapes and monitors business citations.

    Features:
    - NAP extraction with normalization
    - Review signals (rating, count)
    - Citation storage and tracking
    - Consistency checking
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        canonical_name: Optional[str] = None,
        canonical_address: Optional[str] = None,
        canonical_phone: Optional[str] = None
    ):
        """
        Initialize citations scraper.

        Args:
            database_url: Database URL (defaults to DATABASE_URL env var)
            canonical_name: Canonical business name for matching
            canonical_address: Canonical address for matching
            canonical_phone: Canonical phone for matching
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")

        self.canonical_name = canonical_name
        self.canonical_address = canonical_address
        self.canonical_phone = canonical_phone

        # Database setup
        self.engine = create_engine(self.database_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number to digits only."""
        if not phone:
            return ""
        return re.sub(r'[^\d]', '', phone)

    def _normalize_address(self, address: str) -> str:
        """Normalize address for comparison."""
        if not address:
            return ""

        # Convert to lowercase
        normalized = address.lower()

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        # Standardize abbreviations
        replacements = {
            ' street': ' st',
            ' avenue': ' ave',
            ' road': ' rd',
            ' drive': ' dr',
            ' suite': ' ste',
            ' floor': ' fl'
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        return normalized

    def _extract_nap_generic(self, html: str, url: str) -> Dict:
        """
        Generic NAP extraction from HTML.

        Args:
            html: HTML content
            url: Page URL

        Returns:
            Dict with name, address, phone, rating, review_count
        """
        soup = BeautifulSoup(html, 'html.parser')

        nap = {
            'name': '',
            'address': '',
            'phone': '',
            'rating': None,
            'review_count': None
        }

        # Try schema.org microdata
        for item in soup.find_all(attrs={'itemtype': re.compile(r'schema.org/(Local)?Business')}):
            # Name
            name_elem = item.find(attrs={'itemprop': 'name'})
            if name_elem:
                nap['name'] = name_elem.get_text(strip=True)

            # Address
            address_elem = item.find(attrs={'itemprop': 'address'})
            if address_elem:
                # Check for structured address
                street = address_elem.find(attrs={'itemprop': 'streetAddress'})
                city = address_elem.find(attrs={'itemprop': 'addressLocality'})
                state = address_elem.find(attrs={'itemprop': 'addressRegion'})
                zip_code = address_elem.find(attrs={'itemprop': 'postalCode'})

                if street:
                    parts = [
                        street.get_text(strip=True) if street else '',
                        city.get_text(strip=True) if city else '',
                        state.get_text(strip=True) if state else '',
                        zip_code.get_text(strip=True) if zip_code else ''
                    ]
                    nap['address'] = ', '.join(filter(None, parts))
                else:
                    nap['address'] = address_elem.get_text(strip=True)

            # Phone
            phone_elem = item.find(attrs={'itemprop': 'telephone'})
            if phone_elem:
                nap['phone'] = phone_elem.get_text(strip=True)

            # Rating
            rating_elem = item.find(attrs={'itemprop': 'ratingValue'})
            if rating_elem:
                try:
                    nap['rating'] = float(rating_elem.get_text(strip=True))
                except ValueError:
                    pass

            # Review count
            review_elem = item.find(attrs={'itemprop': 'reviewCount'})
            if review_elem:
                try:
                    nap['review_count'] = int(review_elem.get_text(strip=True))
                except ValueError:
                    pass

        # Fallback: search for tel: links
        if not nap['phone']:
            tel_link = soup.find('a', href=re.compile(r'^tel:'))
            if tel_link:
                nap['phone'] = tel_link.get_text(strip=True)

        logger.debug(f"Extracted NAP from {url}: {nap['name']}, {nap['phone']}")
        return nap

    def scrape_citation(
        self,
        directory_name: str,
        profile_url: str
    ) -> bool:
        """
        Scrape a single citation.

        Args:
            directory_name: Name of directory (e.g., 'Google Business', 'Yelp')
            profile_url: URL to business profile

        Returns:
            True if successful, False otherwise
        """
        with self.SessionLocal() as session:
            try:
                logger.info(f"Scraping citation: {directory_name} - {profile_url}")

                # Fetch profile page
                response = get_with_retry(profile_url)
                if not response or response.status_code != 200:
                    logger.warning(f"Failed to fetch {profile_url}")
                    return False

                html = response.text

                # Extract NAP
                nap = self._extract_nap_generic(html, profile_url)

                # Check NAP matching
                name_match = bool(
                    self.canonical_name and
                    self.canonical_name.lower() in nap['name'].lower()
                ) if nap['name'] else False

                phone_match = bool(
                    self.canonical_phone and
                    self._normalize_phone(self.canonical_phone) == self._normalize_phone(nap['phone'])
                ) if nap['phone'] else False

                address_match = bool(
                    self.canonical_address and
                    self._normalize_address(self.canonical_address) in self._normalize_address(nap['address'])
                ) if nap['address'] else False

                # Check if citation exists
                existing = session.query(Citation).filter(
                    Citation.directory_name == directory_name,
                    Citation.profile_url == profile_url
                ).first()

                if existing:
                    # Update existing citation
                    existing.last_checked = datetime.utcnow()
                    existing.nap_name = nap['name']
                    existing.nap_address = nap['address']
                    existing.nap_phone = nap['phone']
                    existing.name_match = name_match
                    existing.phone_match = phone_match
                    existing.address_match = address_match
                    existing.rating = nap['rating']
                    existing.review_count = nap['review_count']

                    logger.info(f"Updated citation: {directory_name}")
                else:
                    # Create new citation
                    citation = Citation(
                        directory_name=directory_name,
                        profile_url=profile_url,
                        nap_name=nap['name'],
                        nap_address=nap['address'],
                        nap_phone=nap['phone'],
                        name_match=name_match,
                        phone_match=phone_match,
                        address_match=address_match,
                        rating=nap['rating'],
                        review_count=nap['review_count'],
                        first_seen=datetime.utcnow(),
                        last_checked=datetime.utcnow()
                    )
                    session.add(citation)

                    logger.info(f"Created new citation: {directory_name}")

                session.commit()
                return True

            except Exception as e:
                logger.error(f"Error scraping citation {directory_name}: {e}")
                session.rollback()
                return False

    def scrape_all_citations(
        self,
        citations_list: List[Dict[str, str]]
    ) -> Dict[str, int]:
        """
        Scrape multiple citations.

        Args:
            citations_list: List of dicts with 'directory_name' and 'profile_url'

        Returns:
            Dict with 'success', 'failed' counts
        """
        with task_logger.log_task("citations_scraper", "citations") as log_id:
            success_count = 0
            failed_count = 0

            for i, citation_info in enumerate(citations_list, 1):
                directory_name = citation_info['directory_name']
                profile_url = citation_info['profile_url']

                try:
                    result = self.scrape_citation(directory_name, profile_url)
                    if result:
                        success_count += 1
                    else:
                        failed_count += 1

                    # Update progress
                    task_logger.update_progress(
                        log_id,
                        items_processed=i,
                        items_new=success_count,
                        items_failed=failed_count
                    )

                except Exception as e:
                    logger.error(f"Failed to process citation: {e}")
                    failed_count += 1

            results = {
                'success': success_count,
                'failed': failed_count
            }

            logger.info(
                f"Citations scraping complete: {success_count} success, {failed_count} failed"
            )

            return results

    def get_citation_consistency_report(self) -> Dict:
        """
        Generate citation consistency report.

        Returns:
            Dict with consistency stats
        """
        with self.SessionLocal() as session:
            from sqlalchemy import func

            total = session.query(func.count(Citation.id)).scalar() or 0

            if total == 0:
                return {'total': 0}

            name_matches = session.query(func.count(Citation.id)).filter(
                Citation.name_match == True
            ).scalar() or 0

            phone_matches = session.query(func.count(Citation.id)).filter(
                Citation.phone_match == True
            ).scalar() or 0

            address_matches = session.query(func.count(Citation.id)).filter(
                Citation.address_match == True
            ).scalar() or 0

            avg_rating = session.query(func.avg(Citation.rating)).filter(
                Citation.rating.isnot(None)
            ).scalar() or 0

            total_reviews = session.query(func.sum(Citation.review_count)).filter(
                Citation.review_count.isnot(None)
            ).scalar() or 0

            return {
                'total': total,
                'name_match_pct': (name_matches / total * 100) if total > 0 else 0,
                'phone_match_pct': (phone_matches / total * 100) if total > 0 else 0,
                'address_match_pct': (address_matches / total * 100) if total > 0 else 0,
                'avg_rating': float(avg_rating),
                'total_reviews': int(total_reviews)
            }
