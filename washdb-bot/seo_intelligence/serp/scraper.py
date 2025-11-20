"""
SERP scraper using Playwright for Google search results.

Fetches and parses Google SERPs for tracked keywords, extracting:
- Top 10 organic results
- Featured snippets
- People Also Ask (PAA) questions
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from playwright.sync_api import Browser, Page, sync_playwright
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import SearchQuery, SerpSnapshot, SerpResult
from ..infrastructure.task_logger import task_logger
from ..infrastructure.rate_limiter import rate_limiter
from .extractor import extract_all_serp_data

logger = logging.getLogger(__name__)


class SERPScraper:
    """
    SERP scraper using Playwright for rendering JavaScript.

    Features:
    - Chromium browser with optional proxy
    - Rate limiting and robots.txt compliance
    - Extracts organic results, featured snippets, PAA
    - Stores to serp_snapshots and serp_results tables
    - Marks our_rank when our domain appears
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        our_domain: Optional[str] = None,
        proxy: Optional[Dict[str, str]] = None,
        headless: bool = True,
        user_agent: Optional[str] = None
    ):
        """
        Initialize SERP scraper.

        Args:
            database_url: Database URL (defaults to DATABASE_URL env var)
            our_domain: Our domain for marking our_rank (e.g., 'example.com')
            proxy: Proxy configuration (e.g., {'server': 'http://proxy:8080'})
            headless: Run browser in headless mode (default: True)
            user_agent: Custom user agent (optional)
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")

        self.our_domain = our_domain or os.getenv("OUR_DOMAIN")
        self.proxy = proxy
        self.headless = headless
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        # Database setup
        self.engine = create_engine(self.database_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

        # Playwright browser (initialized on demand)
        self._playwright = None
        self._browser: Optional[Browser] = None

    def _init_browser(self):
        """Initialize Playwright browser if not already running."""
        if self._browser is None:
            logger.info("Launching Playwright browser...")
            self._playwright = sync_playwright().start()

            # Browser launch options
            launch_options = {
                'headless': self.headless,
                'args': [
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            }

            if self.proxy:
                launch_options['proxy'] = self.proxy

            self._browser = self._playwright.chromium.launch(**launch_options)
            logger.info("Browser launched successfully")

    def _create_context(self):
        """Create new browser context with anti-detection measures."""
        self._init_browser()

        context = self._browser.new_context(
            user_agent=self.user_agent,
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/New_York'
        )

        # Add anti-detection scripts
        context.add_init_script("""
            // Remove webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Add plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Add languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)

        return context

    def _build_serp_url(self, query: str, search_engine: str = "Google", locale: str = "en-US") -> str:
        """
        Build SERP URL for query.

        Args:
            query: Search query
            search_engine: Search engine (default: Google)
            locale: Locale code (default: en-US)

        Returns:
            SERP URL
        """
        if search_engine.lower() == "google":
            # Google search with parameters for organic results
            encoded_query = quote_plus(query)

            # Extract language and region from locale (e.g., en-US -> en, US)
            lang = locale.split('-')[0] if '-' in locale else 'en'
            region = locale.split('-')[1] if '-' in locale else 'US'

            return f"https://www.google.com/search?q={encoded_query}&hl={lang}&gl={region}&num=10"
        else:
            raise ValueError(f"Unsupported search engine: {search_engine}")

    def fetch_serp(
        self,
        query: str,
        search_engine: str = "Google",
        locale: str = "en-US",
        wait_for_selector: str = "div#search",
        timeout: int = 30000
    ) -> Tuple[Page, str]:
        """
        Fetch SERP page using Playwright.

        Args:
            query: Search query
            search_engine: Search engine (default: Google)
            locale: Locale code (default: en-US)
            wait_for_selector: Selector to wait for (default: div#search)
            timeout: Page load timeout in ms (default: 30000)

        Returns:
            Tuple of (Page object, HTML content)

        Raises:
            Exception: If page fetch fails
        """
        url = self._build_serp_url(query, search_engine, locale)

        # Apply rate limiting
        rate_limiter.wait(url)

        logger.info(f"Fetching SERP for query: '{query}' from {search_engine}")

        context = self._create_context()
        page = context.new_page()

        try:
            # Navigate to SERP
            response = page.goto(url, wait_until='domcontentloaded', timeout=timeout)

            if response is None or not response.ok:
                status = response.status if response else 'unknown'
                raise Exception(f"Failed to fetch SERP (status: {status})")

            # Wait for search results to load
            try:
                page.wait_for_selector(wait_for_selector, timeout=timeout)
            except Exception as e:
                logger.warning(f"Wait for selector '{wait_for_selector}' timed out: {e}")

            # Additional wait to ensure dynamic content loads
            page.wait_for_timeout(2000)

            # Get page content
            html = page.content()

            logger.info(f"Successfully fetched SERP for '{query}' ({len(html)} bytes)")

            return page, html

        except Exception as e:
            page.close()
            context.close()
            raise Exception(f"Error fetching SERP for '{query}': {e}")

    def _store_serp_data(
        self,
        session,
        query_id: int,
        organic_results: List[Dict],
        featured_snippet: Optional[Dict],
        paa_questions: List[Dict]
    ):
        """
        Store SERP data to database.

        Args:
            session: SQLAlchemy session
            query_id: SearchQuery ID
            organic_results: List of organic result dicts
            featured_snippet: Featured snippet dict (or None)
            paa_questions: List of PAA question dicts
        """
        from urllib.parse import urlparse

        # Get today's date for snapshot
        snapshot_date = datetime.utcnow().date()

        # Check if snapshot already exists for today
        existing_snapshot = session.query(SerpSnapshot).filter(
            SerpSnapshot.query_id == query_id,
            SerpSnapshot.snapshot_date >= snapshot_date,
            SerpSnapshot.snapshot_date < snapshot_date + timedelta(days=1)
        ).first()

        if existing_snapshot:
            logger.warning(
                f"Snapshot already exists for query {query_id} on {snapshot_date}, "
                f"deleting old snapshot"
            )
            # Delete old results for this snapshot
            session.query(SerpResult).filter(
                SerpResult.snapshot_id == existing_snapshot.id
            ).delete()
            session.delete(existing_snapshot)
            session.flush()

        # Determine our_rank (position where our domain appears)
        our_rank = None
        if self.our_domain:
            for result in organic_results:
                result_url = result.get('url', '')
                if result_url:
                    domain = urlparse(result_url).netloc
                    if self.our_domain.lower() in domain.lower():
                        our_rank = result.get('position')
                        logger.info(f"Found our domain at position {our_rank}")
                        break

        # Create snapshot
        snapshot = SerpSnapshot(
            query_id=query_id,
            snapshot_date=datetime.utcnow(),
            our_rank=our_rank,
            featured_snippet_data=featured_snippet if featured_snippet else None,
            paa_questions={'questions': paa_questions} if paa_questions else None
        )
        session.add(snapshot)
        session.flush()  # Get snapshot.id

        # Create result records
        for result in organic_results:
            serp_result = SerpResult(
                snapshot_id=snapshot.id,
                position=result.get('position'),
                url=result.get('url'),
                title=result.get('title'),
                description=result.get('description')
            )
            session.add(serp_result)

        session.commit()

        logger.info(
            f"Stored SERP snapshot {snapshot.id} with {len(organic_results)} results "
            f"(our_rank: {our_rank})"
        )

    def scrape_query(
        self,
        query_id: int,
        expand_paa: bool = True,
        max_paa: int = 5
    ) -> bool:
        """
        Scrape SERP for a specific search query.

        Args:
            query_id: SearchQuery ID to scrape
            expand_paa: Whether to expand PAA questions (default: True)
            max_paa: Maximum PAA questions to expand (default: 5)

        Returns:
            True if successful, False otherwise
        """
        with self.SessionLocal() as session:
            # Get query details
            query = session.query(SearchQuery).filter(SearchQuery.id == query_id).first()
            if not query:
                raise ValueError(f"SearchQuery {query_id} not found")

            if not query.track:
                logger.info(f"Query {query_id} ('{query.query_text}') is not tracked, skipping")
                return False

            logger.info(f"Scraping query {query_id}: '{query.query_text}'")

            try:
                # Fetch SERP
                page, html = self.fetch_serp(
                    query.query_text,
                    query.search_engine,
                    query.locale
                )

                # Extract SERP data
                serp_data = extract_all_serp_data(
                    page,
                    expand_paa=expand_paa,
                    max_paa=max_paa
                )

                organic_results = serp_data['organic_results']
                featured_snippet = serp_data['featured_snippet']
                paa_questions = serp_data['paa_questions']

                # Clean up
                page.close()
                page.context.close()

                # Store to database
                self._store_serp_data(
                    session,
                    query_id,
                    organic_results,
                    featured_snippet,
                    paa_questions
                )

                logger.info(f"Successfully scraped query {query_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to scrape query {query_id}: {e}")
                return False

    def scrape_all_tracked(self, limit: Optional[int] = None) -> Dict[str, int]:
        """
        Scrape all tracked search queries.

        Args:
            limit: Maximum number of queries to scrape (optional)

        Returns:
            Dict with 'success', 'failed', 'skipped' counts
        """
        with task_logger.log_task("serp_scraper", "serp") as log_id:
            with self.SessionLocal() as session:
                # Get all tracked queries
                query_filter = SearchQuery.track == True
                if limit:
                    queries = session.query(SearchQuery).filter(query_filter).limit(limit).all()
                else:
                    queries = session.query(SearchQuery).filter(query_filter).all()

                logger.info(f"Found {len(queries)} tracked queries to scrape")

                success_count = 0
                failed_count = 0
                skipped_count = 0

                for i, query in enumerate(queries, 1):
                    logger.info(f"Processing query {i}/{len(queries)}: '{query.query_text}'")

                    try:
                        result = self.scrape_query(query.id)
                        if result:
                            success_count += 1
                        else:
                            skipped_count += 1
                    except Exception as e:
                        logger.error(f"Error scraping query {query.id}: {e}")
                        failed_count += 1

                    # Update task progress
                    task_logger.update_progress(
                        log_id,
                        items_processed=i,
                        items_new=success_count,
                        items_failed=failed_count
                    )

                results = {
                    'success': success_count,
                    'failed': failed_count,
                    'skipped': skipped_count
                }

                logger.info(
                    f"SERP scraping complete: {success_count} success, "
                    f"{failed_count} failed, {skipped_count} skipped"
                )

                return results

    def close(self):
        """Close browser and cleanup resources."""
        if self._browser:
            self._browser.close()
            self._browser = None

        if self._playwright:
            self._playwright.stop()
            self._playwright = None

        logger.info("Browser closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
