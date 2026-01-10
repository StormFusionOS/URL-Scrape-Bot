"""
Review Detail Scraper

Fetches latest review data from business listings on Google, Yelp, BBB, Facebook, etc.
Updates the citations table with fresh review counts, ratings, and snippets.

Usage:
    from seo_intelligence.scrapers.review_details import ReviewDetailScraper

    scraper = ReviewDetailScraper()
    results = scraper.scrape_reviews(company_id=123)
"""

import os
import re
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from urllib.parse import urlparse, quote_plus
from bs4 import BeautifulSoup

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, bindparam
from sqlalchemy.orm import Session

from seo_intelligence.services import get_task_logger
from seo_intelligence.services.governance import propose_change, ChangeType
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("review_details")


@dataclass
class ReviewData:
    """Container for review data fetched from a listing."""
    citation_id: int
    directory_name: str
    listing_url: str
    rating_value: Optional[float] = None
    rating_count: Optional[int] = None
    latest_review_date: Optional[datetime] = None
    recent_review_snippets: Optional[List[str]] = None
    fetched_at: datetime = None

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = datetime.now()

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        result = asdict(self)
        if self.latest_review_date:
            result['latest_review_date'] = self.latest_review_date.isoformat()
        result['fetched_at'] = self.fetched_at.isoformat()
        return result


class ReviewDetailScraper:
    """
    Scrapes review details from business listings.

    Supported platforms:
    - Google Business Profile
    - Yelp
    - Better Business Bureau (BBB)
    - Facebook

    Features:
    - Fetches latest review dates
    - Extracts rating values and counts
    - Captures recent review snippets
    - Updates citations table with fresh data
    """

    SUPPORTED_PLATFORMS = ['google', 'yelp', 'bbb', 'facebook']

    def __init__(
        self,
        max_listings_per_run: int = 50,
        max_snippets: int = 3,
        snippet_length: int = 200,
        timeout_seconds: int = 10,
        use_playwright: bool = False
    ):
        """
        Initialize review scraper.

        Args:
            max_listings_per_run: Maximum listings to scrape per run
            max_snippets: Maximum review snippets to collect per listing
            snippet_length: Maximum length of each snippet
            timeout_seconds: HTTP request timeout
            use_playwright: Use Playwright for dynamic content (slower but more reliable)
        """
        self.max_listings_per_run = max_listings_per_run
        self.max_snippets = max_snippets
        self.snippet_length = snippet_length
        self.timeout_seconds = timeout_seconds
        self.use_playwright = use_playwright

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database operations disabled")

        # Task logger
        self.task_logger = get_task_logger()

        # HTTP session setup (if not using Playwright)
        if not use_playwright:
            import requests
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
        else:
            self.session = None

        logger.info(f"ReviewDetailScraper initialized (max_listings={max_listings_per_run}, use_playwright={use_playwright})")

    def _get_citations_to_scrape(
        self,
        session: Session,
        company_id: Optional[int] = None,
        limit: int = None
    ) -> List[Dict]:
        """
        Get business sources to scrape for review details.

        Uses business_sources table which links to companies, falling back to
        citations table if no company filter is specified.

        Args:
            session: Database session
            company_id: Filter by specific company (None = all companies)
            limit: Maximum records to return

        Returns:
            List of source dictionaries with listing URLs
        """
        limit = limit or self.max_listings_per_run

        if company_id:
            # Query business_sources for company-specific listings
            # source_type maps to platforms (google, yelp, yp, etc.)
            query_text = """
                SELECT
                    source_id,
                    company_id,
                    source_type as directory_name,
                    profile_url as listing_url,
                    rating_value,
                    rating_count,
                    metadata
                FROM business_sources
                WHERE
                    company_id = :company_id
                    AND profile_url IS NOT NULL
                    AND profile_url != ''
                ORDER BY
                    COALESCE(
                        (metadata->>'last_review_scrape_at')::timestamp,
                        '2000-01-01'::timestamp
                    ) ASC
                LIMIT :limit
            """
            params = {"company_id": company_id, "limit": limit}
            result = session.execute(text(query_text), params)
        else:
            # Query citations table for non-company-specific lookups
            # Use bindparam with expanding=True for IN clause (psycopg3 compatibility)
            query_text = """
                SELECT
                    citation_id,
                    NULL as company_id,
                    directory_name,
                    listing_url,
                    rating as rating_value,
                    review_count as rating_count,
                    metadata
                FROM citations
                WHERE
                    directory_name IN :platforms
                    AND listing_url IS NOT NULL
                    AND listing_url != ''
                ORDER BY
                    COALESCE(
                        (metadata->>'last_review_scrape_at')::timestamp,
                        '2000-01-01'::timestamp
                    ) ASC
                LIMIT :limit
            """
            params = {"platforms": list(self.SUPPORTED_PLATFORMS), "limit": limit}
            stmt = text(query_text).bindparams(bindparam("platforms", expanding=True))
            result = session.execute(stmt, params)

        citations = []
        for row in result:
            citations.append({
                'citation_id': row[0],
                'company_id': row[1],
                'directory_name': row[2],
                'listing_url': row[3],
                'rating_value': row[4],
                'rating_count': row[5],
                'metadata': row[6] or {}
            })

        logger.info(f"Found {len(citations)} sources to scrape for reviews")
        return citations

    def _fetch_page_content(self, url: str) -> Optional[str]:
        """
        Fetch page HTML content.

        Args:
            url: Page URL

        Returns:
            HTML content or None if failed
        """
        try:
            if self.use_playwright:
                # Use Playwright for dynamic content
                from playwright.sync_api import sync_playwright

                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(url, wait_until='networkidle', timeout=self.timeout_seconds * 1000)
                    content = page.content()
                    browser.close()
                    return content
            else:
                # Simple HTTP request
                response = self.session.get(url, timeout=self.timeout_seconds)
                response.raise_for_status()
                return response.text

        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def _parse_google_reviews(self, html: str, url: str) -> ReviewData:
        """
        Parse Google Business Profile review data.

        Args:
            html: Page HTML
            url: Listing URL

        Returns:
            ReviewData object
        """
        soup = BeautifulSoup(html, 'html.parser')
        data = ReviewData(citation_id=0, directory_name='google', listing_url=url)

        # Extract rating (typically in schema.org markup or meta tags)
        # Google uses schema.org LocalBusiness markup
        rating_meta = soup.find('meta', {'itemprop': 'ratingValue'})
        if rating_meta:
            try:
                data.rating_value = float(rating_meta.get('content', 0))
            except (ValueError, TypeError):
                pass

        # Extract review count
        count_meta = soup.find('meta', {'itemprop': 'reviewCount'})
        if count_meta:
            try:
                data.rating_count = int(count_meta.get('content', 0))
            except (ValueError, TypeError):
                pass

        # Extract recent review snippets
        # Google review text is often in divs with specific classes
        review_elements = soup.find_all('div', class_=re.compile(r'review.*text', re.I))
        snippets = []
        for elem in review_elements[:self.max_snippets]:
            text = elem.get_text(strip=True)
            if text:
                snippets.append(text[:self.snippet_length])

        if snippets:
            data.recent_review_snippets = snippets

        # Try to extract latest review date
        # Google often uses time elements with datetime attribute
        time_elements = soup.find_all('time')
        dates = []
        for elem in time_elements:
            datetime_str = elem.get('datetime')
            if datetime_str:
                try:
                    dates.append(datetime.fromisoformat(datetime_str.replace('Z', '+00:00')))
                except Exception:
                    pass

        if dates:
            data.latest_review_date = max(dates)

        return data

    def _parse_yelp_reviews(self, html: str, url: str) -> ReviewData:
        """
        Parse Yelp review data.

        Args:
            html: Page HTML
            url: Listing URL

        Returns:
            ReviewData object
        """
        soup = BeautifulSoup(html, 'html.parser')
        data = ReviewData(citation_id=0, directory_name='yelp', listing_url=url)

        # Yelp rating (aggregate rating in JSON-LD or aria-label)
        rating_div = soup.find('div', {'aria-label': re.compile(r'[\d.]+ star rating', re.I)})
        if rating_div:
            match = re.search(r'([\d.]+) star', rating_div.get('aria-label', ''))
            if match:
                try:
                    data.rating_value = float(match.group(1))
                except (ValueError, TypeError):
                    pass

        # Review count (often in text like "123 reviews")
        count_text = soup.find(text=re.compile(r'\d+ reviews?', re.I))
        if count_text:
            match = re.search(r'(\d+)', count_text)
            if match:
                try:
                    data.rating_count = int(match.group(1))
                except (ValueError, TypeError):
                    pass

        # Extract review snippets
        review_elements = soup.find_all('p', class_=re.compile(r'comment', re.I))
        snippets = []
        for elem in review_elements[:self.max_snippets]:
            text = elem.get_text(strip=True)
            if text:
                snippets.append(text[:self.snippet_length])

        if snippets:
            data.recent_review_snippets = snippets

        # Extract review dates
        date_elements = soup.find_all('span', class_=re.compile(r'date', re.I))
        dates = []
        for elem in date_elements:
            text = elem.get_text(strip=True)
            # Try to parse relative dates like "2 days ago" or absolute dates
            try:
                if 'day' in text.lower():
                    days_match = re.search(r'(\d+)\s*day', text)
                    if days_match:
                        days_ago = int(days_match.group(1))
                        dates.append(datetime.now() - timedelta(days=days_ago))
                elif 'week' in text.lower():
                    weeks_match = re.search(r'(\d+)\s*week', text)
                    if weeks_match:
                        weeks_ago = int(weeks_match.group(1))
                        dates.append(datetime.now() - timedelta(weeks=weeks_ago))
            except Exception:
                pass

        if dates:
            data.latest_review_date = max(dates)

        return data

    def _parse_bbb_reviews(self, html: str, url: str) -> ReviewData:
        """
        Parse BBB review data.

        Args:
            html: Page HTML
            url: Listing URL

        Returns:
            ReviewData object
        """
        soup = BeautifulSoup(html, 'html.parser')
        data = ReviewData(citation_id=0, directory_name='bbb', listing_url=url)

        # BBB rating (often shown as "A+", "A", "B+", etc.)
        # Also has customer reviews with star ratings
        rating_element = soup.find('div', class_=re.compile(r'rating', re.I))
        if rating_element:
            # Look for star rating
            stars = rating_element.find_all('span', class_=re.compile(r'star', re.I))
            if stars:
                # Count filled stars
                filled_stars = len([s for s in stars if 'filled' in s.get('class', [])])
                data.rating_value = float(filled_stars)

        # Review count
        count_element = soup.find(text=re.compile(r'\d+\s+customer reviews?', re.I))
        if count_element:
            match = re.search(r'(\d+)', count_element)
            if match:
                try:
                    data.rating_count = int(match.group(1))
                except (ValueError, TypeError):
                    pass

        # Extract review snippets
        review_elements = soup.find_all('div', class_=re.compile(r'review.*text', re.I))
        snippets = []
        for elem in review_elements[:self.max_snippets]:
            text = elem.get_text(strip=True)
            if text:
                snippets.append(text[:self.snippet_length])

        if snippets:
            data.recent_review_snippets = snippets

        # Extract review dates
        date_elements = soup.find_all('div', class_=re.compile(r'review.*date', re.I))
        dates = []
        for elem in date_elements:
            text = elem.get_text(strip=True)
            # BBB often uses MM/DD/YYYY format
            try:
                date_obj = datetime.strptime(text, '%m/%d/%Y')
                dates.append(date_obj)
            except Exception:
                pass

        if dates:
            data.latest_review_date = max(dates)

        return data

    def _parse_facebook_reviews(self, html: str, url: str) -> ReviewData:
        """
        Parse Facebook review data.

        Args:
            html: Page HTML
            url: Listing URL

        Returns:
            ReviewData object
        """
        soup = BeautifulSoup(html, 'html.parser')
        data = ReviewData(citation_id=0, directory_name='facebook', listing_url=url)

        # Facebook rating (typically 1-5 stars)
        # Often in meta tags or JSON-LD
        rating_meta = soup.find('meta', {'property': 'og:rating'})
        if rating_meta:
            try:
                data.rating_value = float(rating_meta.get('content', 0))
            except (ValueError, TypeError):
                pass

        # Review count
        count_meta = soup.find('meta', {'property': 'og:rating:count'})
        if count_meta:
            try:
                data.rating_count = int(count_meta.get('content', 0))
            except (ValueError, TypeError):
                pass

        # Extract review snippets (Facebook uses dynamic loading, limited without Playwright)
        review_elements = soup.find_all('div', {'data-testid': re.compile(r'review', re.I)})
        snippets = []
        for elem in review_elements[:self.max_snippets]:
            text = elem.get_text(strip=True)
            if text:
                snippets.append(text[:self.snippet_length])

        if snippets:
            data.recent_review_snippets = snippets

        # Note: Facebook review dates are hard to extract without full JavaScript rendering
        # Consider this a limitation without Playwright enabled

        return data

    def _scrape_listing(self, citation: Dict) -> Optional[ReviewData]:
        """
        Scrape review data from a single listing.

        Args:
            citation: Citation dictionary

        Returns:
            ReviewData object or None if failed
        """
        url = citation['listing_url']
        directory = citation['directory_name'].lower()

        logger.info(f"Scraping {directory} listing: {url}")

        # Fetch page content
        html = self._fetch_page_content(url)
        if not html:
            return None

        # Parse based on platform
        try:
            if directory == 'google':
                data = self._parse_google_reviews(html, url)
            elif directory == 'yelp':
                data = self._parse_yelp_reviews(html, url)
            elif directory == 'bbb':
                data = self._parse_bbb_reviews(html, url)
            elif directory == 'facebook':
                data = self._parse_facebook_reviews(html, url)
            else:
                logger.warning(f"Unsupported platform: {directory}")
                return None

            # Set citation_id
            data.citation_id = citation['citation_id']

            return data

        except Exception as e:
            logger.error(f"Error parsing {directory} listing: {e}", exc_info=True)
            return None

    def _update_citation(self, session: Session, review_data: ReviewData) -> Optional[int]:
        """
        Propose citation update through governance workflow.

        Args:
            session: Database session
            review_data: Scraped review data

        Returns:
            change_id if proposed successfully
        """
        try:
            # Build update metadata
            update_metadata = {
                'last_review_scrape_at': review_data.fetched_at.isoformat(),
                'scraped_rating_value': review_data.rating_value,
                'scraped_rating_count': review_data.rating_count
            }

            if review_data.latest_review_date:
                update_metadata['latest_review_date'] = review_data.latest_review_date.isoformat()

            if review_data.recent_review_snippets:
                update_metadata['recent_review_snippets'] = review_data.recent_review_snippets

            # Build proposed update data
            proposed_data = {}

            if review_data.rating_value is not None:
                proposed_data['rating_value'] = review_data.rating_value

            if review_data.rating_count is not None:
                proposed_data['rating_count'] = review_data.rating_count

            # Always update metadata with scrape results
            proposed_data['metadata'] = update_metadata
            proposed_data['last_verified'] = datetime.now().isoformat()

            # Propose change through governance
            change_id = propose_change(
                table_name='citations',
                operation='update',
                record_id=review_data.citation_id,
                proposed_data=proposed_data,
                change_type=ChangeType.REVIEWS,
                source='review_detail_scraper',
                reason=f"Fresh review data scraped from {review_data.directory_name}",
                metadata={
                    'directory_name': review_data.directory_name,
                    'listing_url': review_data.listing_url,
                    'rating_value': review_data.rating_value,
                    'rating_count': review_data.rating_count,
                    'has_snippets': bool(review_data.recent_review_snippets)
                }
            )

            logger.debug(f"Proposed citation update {review_data.citation_id} (change_id={change_id})")
            return change_id

        except Exception as e:
            logger.error(f"Error proposing citation update {review_data.citation_id}: {e}", exc_info=True)
            return None

    def scrape_reviews(
        self,
        company_id: Optional[int] = None,
        limit: Optional[int] = None,
        delay_seconds: float = 2.0
    ) -> List[ReviewData]:
        """
        Scrape review details from business listings.

        Args:
            company_id: Filter by specific company (None = all companies)
            limit: Maximum listings to scrape (None = use default)
            delay_seconds: Delay between requests to avoid rate limiting

        Returns:
            List of scraped review data
        """
        if not self.engine:
            logger.error("Cannot scrape reviews - database not configured")
            return []

        limit = limit or self.max_listings_per_run
        results = []

        # Start task logging
        task_id = None
        if self.task_logger:
            task_id = self.task_logger.start_task(
                task_name="review_detail_scraper",
                task_type="scraper",
                metadata={"company_id": company_id, "limit": limit}
            )

        try:
            with Session(self.engine) as session:
                # Get citations to scrape
                citations = self._get_citations_to_scrape(session, company_id, limit)

                if not citations:
                    logger.info("No citations found to scrape")
                    return []

                logger.info(f"Scraping {len(citations)} listings for review details")

                # Scrape each listing
                for i, citation in enumerate(citations):
                    # Rate limiting
                    if i > 0 and delay_seconds > 0:
                        time.sleep(delay_seconds)

                    # Scrape listing
                    review_data = self._scrape_listing(citation)

                    if review_data:
                        # Update database
                        success = self._update_citation(session, review_data)

                        if success:
                            results.append(review_data)
                            logger.info(
                                f"Scraped {citation['directory_name']}: "
                                f"rating={review_data.rating_value}, "
                                f"count={review_data.rating_count}, "
                                f"snippets={len(review_data.recent_review_snippets or [])}"
                            )

                # Complete task logging
                if self.task_logger and task_id:
                    self.task_logger.complete_task(
                        task_id=task_id,
                        status="success",
                        records_processed=len(citations),
                        records_created=len(results),
                        metadata={
                            "successful_scrapes": len(results),
                            "platforms": list(set([r.directory_name for r in results]))
                        }
                    )

                logger.info(
                    f"Scraping complete: Successfully scraped {len(results)}/{len(citations)} listings"
                )

        except Exception as e:
            logger.error(f"Error scraping reviews: {e}", exc_info=True)

            if self.task_logger and task_id:
                self.task_logger.complete_task(
                    task_id=task_id,
                    status="failed",
                    error_message=str(e)
                )

            raise

        return results


def get_review_scraper(**kwargs) -> ReviewDetailScraper:
    """
    Factory function to get review scraper instance.

    Args:
        **kwargs: Arguments to pass to ReviewDetailScraper

    Returns:
        ReviewDetailScraper instance
    """
    return ReviewDetailScraper(**kwargs)


# CLI interface
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Scrape review details from business listings")
    parser.add_argument("--company-id", type=int, help="Company ID to scrape reviews for")
    parser.add_argument("--limit", type=int, default=50, help="Max listings to scrape")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between requests (seconds)")
    parser.add_argument("--use-playwright", action="store_true", help="Use Playwright for dynamic content")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    scraper = ReviewDetailScraper(
        max_listings_per_run=args.limit,
        use_playwright=args.use_playwright
    )

    results = scraper.scrape_reviews(
        company_id=args.company_id,
        delay_seconds=args.delay
    )

    print(f"\nScraped {len(results)} listings:")
    for result in results:
        print(f"  - {result.directory_name}: rating={result.rating_value}, count={result.rating_count}")
        if result.recent_review_snippets:
            print(f"    Latest snippet: {result.recent_review_snippets[0][:80]}...")
