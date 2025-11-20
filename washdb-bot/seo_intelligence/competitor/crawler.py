"""
Main competitor crawler orchestration.

Coordinates all competitor crawling components:
- URL discovery
- Page fetching
- Content parsing
- Hash comparison
- Snapshot storage
- Embedding generation
- Database updates
"""
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Set

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Competitor, CompetitorPage
from ..infrastructure.http_client import get_with_retry
from ..infrastructure.task_logger import task_logger
from .embeddings import get_embeddings_generator
from .hasher import page_hasher
from .parser import PageParser
from .snapshot import snapshot_manager
from .url_seeder import URLSeeder

logger = logging.getLogger(__name__)


class CompetitorCrawler:
    """
    Main competitor crawler orchestrator.

    Features:
    - Discovers URLs from sitemap/RSS/homepage
    - Fetches and parses pages
    - Detects content changes via hashing
    - Stores HTML snapshots
    - Generates vector embeddings
    - Updates database records
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        max_urls_per_site: int = 100,
        save_snapshots: bool = True,
        generate_embeddings: bool = True
    ):
        """
        Initialize competitor crawler.

        Args:
            database_url: Database URL (defaults to DATABASE_URL env var)
            max_urls_per_site: Maximum URLs to discover per site (default: 100)
            save_snapshots: Whether to save HTML snapshots (default: True)
            generate_embeddings: Whether to generate embeddings (default: True)
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")

        self.max_urls_per_site = max_urls_per_site
        self.save_snapshots = save_snapshots
        self.generate_embeddings = generate_embeddings

        # Database setup
        self.engine = create_engine(self.database_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

        # Initialize components
        self.url_seeder = URLSeeder(max_urls=max_urls_per_site)

    def crawl_page(
        self,
        session,
        competitor_id: int,
        url: str,
        force_update: bool = False
    ) -> bool:
        """
        Crawl a single competitor page.

        Args:
            session: SQLAlchemy session
            competitor_id: Competitor database ID
            url: Page URL to crawl
            force_update: Force update even if hash unchanged (default: False)

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Crawling: {url}")

            # Fetch page
            response = get_with_retry(url)
            if not response or response.status_code != 200:
                logger.warning(f"Failed to fetch {url}: status {response.status_code if response else 'None'}")
                return False

            html = response.text

            # Compute hash
            current_hash = page_hasher.hash_content(html)

            # Check if page exists
            page = session.query(CompetitorPage).filter(
                CompetitorPage.competitor_id == competitor_id,
                CompetitorPage.url == url
            ).first()

            # Skip if hash unchanged and not forcing update
            if page and page.last_hash == current_hash and not force_update:
                logger.debug(f"Page unchanged: {url}")
                return True

            # Parse page
            parser = PageParser(base_url=url)
            parsed_data = parser.parse_all(html, base_url=url)

            # Save snapshot if enabled
            snapshot_path = None
            if self.save_snapshots:
                snapshot_path = snapshot_manager.save_snapshot(url, html)

            # Prepare data dict for database
            page_data = {
                'meta': parsed_data['meta'],
                'headers': parsed_data['headers'],
                'schema': parsed_data['schema'],
                'images': parsed_data['images'][:20],  # Limit to first 20 images
                'videos': parsed_data['videos']
            }

            # Create or update page record
            if page:
                # Update existing page
                page.last_crawled = datetime.utcnow()
                page.last_hash = current_hash
                page.data = page_data
                if snapshot_path:
                    page.html_snapshot_path = snapshot_path

                logger.info(f"Updated page: {url}")
            else:
                # Create new page
                page = CompetitorPage(
                    competitor_id=competitor_id,
                    url=url,
                    first_seen=datetime.utcnow(),
                    last_crawled=datetime.utcnow(),
                    last_hash=current_hash,
                    data=page_data,
                    html_snapshot_path=snapshot_path
                )
                session.add(page)
                session.flush()  # Get page.id

                logger.info(f"Created new page: {url}")

            # Generate embeddings if enabled
            if self.generate_embeddings:
                try:
                    embeddings_gen = get_embeddings_generator()
                    embeddings_gen.upsert_page(
                        page_id=page.id,
                        url=url,
                        parsed_data=parsed_data
                    )
                except Exception as e:
                    logger.warning(f"Failed to generate embeddings for {url}: {e}")

            session.commit()
            return True

        except Exception as e:
            logger.error(f"Error crawling page {url}: {e}")
            return False

    def crawl_competitor(
        self,
        competitor_id: int,
        discover_urls: bool = True,
        crawl_existing: bool = True,
        max_pages: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Crawl all pages for a competitor.

        Args:
            competitor_id: Competitor database ID
            discover_urls: Whether to discover new URLs (default: True)
            crawl_existing: Whether to recrawl existing pages (default: True)
            max_pages: Maximum pages to crawl (optional)

        Returns:
            Dict with 'success', 'failed', 'skipped' counts
        """
        with self.SessionLocal() as session:
            # Get competitor details
            competitor = session.query(Competitor).filter(
                Competitor.id == competitor_id
            ).first()

            if not competitor:
                raise ValueError(f"Competitor {competitor_id} not found")

            logger.info(f"Crawling competitor: {competitor.name} ({competitor.domain})")

            urls_to_crawl: Set[str] = set()

            # Discover new URLs if requested
            if discover_urls:
                logger.info("Discovering URLs...")
                discovered_urls = self.url_seeder.discover_all(competitor.domain)
                urls_to_crawl.update(discovered_urls)
                logger.info(f"Discovered {len(discovered_urls)} URLs")

            # Add existing pages if requested
            if crawl_existing:
                existing_pages = session.query(CompetitorPage).filter(
                    CompetitorPage.competitor_id == competitor_id
                ).all()
                for page in existing_pages:
                    urls_to_crawl.add(page.url)
                logger.info(f"Added {len(existing_pages)} existing pages")

            # Limit URLs if specified
            if max_pages and len(urls_to_crawl) > max_pages:
                urls_to_crawl = set(list(urls_to_crawl)[:max_pages])
                logger.info(f"Limited to {max_pages} pages")

            # Crawl all URLs
            success_count = 0
            failed_count = 0
            skipped_count = 0

            for i, url in enumerate(urls_to_crawl, 1):
                logger.info(f"Processing URL {i}/{len(urls_to_crawl)}: {url}")

                try:
                    result = self.crawl_page(session, competitor_id, url)
                    if result:
                        success_count += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    logger.error(f"Error crawling {url}: {e}")
                    failed_count += 1

            results = {
                'success': success_count,
                'failed': failed_count,
                'skipped': skipped_count
            }

            logger.info(
                f"Competitor crawl complete: {success_count} success, "
                f"{failed_count} failed, {skipped_count} skipped"
            )

            return results

    def crawl_all_competitors(
        self,
        track_only: bool = True,
        max_pages_per_site: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Crawl all competitors.

        Args:
            track_only: Only crawl competitors with track=True (default: True)
            max_pages_per_site: Maximum pages per site (optional)

        Returns:
            Dict with aggregate counts
        """
        with task_logger.log_task("competitor_crawler", "competitor") as log_id:
            with self.SessionLocal() as session:
                # Get all competitors
                query = session.query(Competitor)
                if track_only:
                    query = query.filter(Competitor.track == True)

                competitors = query.all()

                logger.info(f"Found {len(competitors)} competitors to crawl")

                total_success = 0
                total_failed = 0
                total_skipped = 0

                for i, competitor in enumerate(competitors, 1):
                    logger.info(
                        f"Processing competitor {i}/{len(competitors)}: "
                        f"{competitor.name} ({competitor.domain})"
                    )

                    try:
                        results = self.crawl_competitor(
                            competitor.id,
                            max_pages=max_pages_per_site
                        )

                        total_success += results['success']
                        total_failed += results['failed']
                        total_skipped += results['skipped']

                        # Update task progress
                        task_logger.update_progress(
                            log_id,
                            items_processed=i,
                            items_new=total_success,
                            items_failed=total_failed
                        )

                    except Exception as e:
                        logger.error(f"Error crawling competitor {competitor.id}: {e}")
                        total_failed += 1

                results = {
                    'success': total_success,
                    'failed': total_failed,
                    'skipped': total_skipped
                }

                logger.info(
                    f"All competitors crawled: {total_success} success, "
                    f"{total_failed} failed, {total_skipped} skipped"
                )

                return results
