"""
Backlinks tracker with position classification.

Extracts and classifies outbound links from competitor pages:
- Position detection (in-body, nav, footer, aside, sidebar)
- Deduplication
- Link health tracking
- Storage to backlinks and referring_domains tables
"""
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Backlink, CompetitorPage, ReferringDomain
from ..infrastructure.http_client import get_with_retry
from ..infrastructure.task_logger import task_logger

logger = logging.getLogger(__name__)


class BacklinksTracker:
    """
    Tracks and classifies outbound links from competitor pages.

    Features:
    - Position classification (in-body vs boilerplate)
    - Deduplication by (source_url, target_url)
    - Link health monitoring
    - Aggregate referring domain stats
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize backlinks tracker.

        Args:
            database_url: Database URL (defaults to DATABASE_URL env var)
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")

        # Database setup
        self.engine = create_engine(self.database_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _classify_link_position(
        self,
        link_element,
        soup: BeautifulSoup
    ) -> str:
        """
        Classify link position in page structure.

        Args:
            link_element: BeautifulSoup link element
            soup: Full page soup

        Returns:
            Position classification: 'in-body', 'nav', 'footer', 'aside', 'sidebar', 'unknown'
        """
        try:
            # Check parent elements for semantic tags
            for parent in link_element.parents:
                if parent.name == 'nav':
                    return 'nav'
                elif parent.name == 'footer':
                    return 'footer'
                elif parent.name == 'aside':
                    return 'aside'
                elif parent.name == 'article' or parent.name == 'main':
                    return 'in-body'

            # Check for common class/id patterns
            for parent in link_element.parents:
                if parent.get('class'):
                    classes = ' '.join(parent['class']).lower()
                    if any(term in classes for term in ['sidebar', 'side-bar', 'aside']):
                        return 'sidebar'
                    elif any(term in classes for term in ['nav', 'menu', 'header']):
                        return 'nav'
                    elif any(term in classes for term in ['footer', 'bottom']):
                        return 'footer'
                    elif any(term in classes for term in ['content', 'main', 'article']):
                        return 'in-body'

                if parent.get('id'):
                    id_val = parent['id'].lower()
                    if 'sidebar' in id_val or 'aside' in id_val:
                        return 'sidebar'
                    elif 'nav' in id_val or 'menu' in id_val:
                        return 'nav'
                    elif 'footer' in id_val:
                        return 'footer'
                    elif 'content' in id_val or 'main' in id_val:
                        return 'in-body'

            # Default to unknown
            return 'unknown'

        except Exception as e:
            logger.warning(f"Error classifying link position: {e}")
            return 'unknown'

    def extract_links_from_html(
        self,
        html: str,
        source_url: str,
        source_domain: str
    ) -> List[Dict]:
        """
        Extract and classify links from HTML.

        Args:
            html: Raw HTML content
            source_url: Source page URL
            source_domain: Source domain

        Returns:
            List of link dicts with url, text, position, nofollow
        """
        links = []

        try:
            soup = BeautifulSoup(html, 'html.parser')

            for link_elem in soup.find_all('a', href=True):
                href = link_elem['href']

                # Skip relative, anchor, and mailto links
                if not href.startswith(('http://', 'https://')):
                    continue

                # Skip same-domain links (we only track external links)
                target_domain = urlparse(href).netloc
                if target_domain == source_domain:
                    continue

                # Classify position
                position = self._classify_link_position(link_elem, soup)

                # Check nofollow
                rel = link_elem.get('rel', [])
                if isinstance(rel, str):
                    rel = [rel]
                nofollow = 'nofollow' in rel

                # Get anchor text
                anchor_text = link_elem.get_text(strip=True)

                links.append({
                    'url': href,
                    'target_domain': target_domain,
                    'anchor_text': anchor_text,
                    'position': position,
                    'nofollow': nofollow
                })

            logger.debug(f"Extracted {len(links)} outbound links from {source_url}")
            return links

        except Exception as e:
            logger.error(f"Error extracting links from {source_url}: {e}")
            return []

    def store_backlinks(
        self,
        session,
        source_url: str,
        source_domain: str,
        links: List[Dict]
    ) -> int:
        """
        Store backlinks to database with deduplication.

        Args:
            session: SQLAlchemy session
            source_url: Source page URL
            source_domain: Source domain
            links: List of link dicts

        Returns:
            Number of new backlinks stored
        """
        new_count = 0

        try:
            for link in links:
                target_url = link['url']
                target_domain = link['target_domain']

                # Check if backlink already exists
                existing = session.query(Backlink).filter(
                    Backlink.source_url == source_url,
                    Backlink.target_url == target_url
                ).first()

                if existing:
                    # Update existing backlink
                    existing.last_seen = datetime.utcnow()
                    existing.position = link['position']
                    existing.anchor_text = link['anchor_text']
                    existing.nofollow = link['nofollow']
                    existing.alive = True
                else:
                    # Create new backlink
                    backlink = Backlink(
                        source_url=source_url,
                        source_domain=source_domain,
                        target_url=target_url,
                        target_domain=target_domain,
                        anchor_text=link['anchor_text'],
                        position=link['position'],
                        nofollow=link['nofollow'],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        alive=True
                    )
                    session.add(backlink)
                    new_count += 1

            session.commit()

            logger.info(f"Stored {new_count} new backlinks from {source_url}")
            return new_count

        except Exception as e:
            logger.error(f"Error storing backlinks: {e}")
            session.rollback()
            return 0

    def update_referring_domains(self, session):
        """
        Update referring_domains aggregate table.

        Computes link counts and in-body percentage per domain.

        Args:
            session: SQLAlchemy session
        """
        try:
            from sqlalchemy import func, Integer

            # Aggregate backlinks by source and target domain
            aggregates = session.query(
                Backlink.source_domain,
                Backlink.target_domain,
                func.count(Backlink.id).label('total_links'),
                func.sum(func.cast(Backlink.position == 'in-body', Integer)).label('in_body_links'),
                func.max(Backlink.last_seen).label('last_seen')
            ).filter(
                Backlink.alive == True
            ).group_by(
                Backlink.source_domain,
                Backlink.target_domain
            ).all()

            for agg in aggregates:
                source_domain = agg.source_domain
                target_domain = agg.target_domain
                total_links = agg.total_links
                in_body_links = agg.in_body_links or 0
                last_seen = agg.last_seen

                # Compute in-body percentage
                in_body_pct = (in_body_links / total_links * 100) if total_links > 0 else 0

                # Check if record exists
                existing = session.query(ReferringDomain).filter(
                    ReferringDomain.source_domain == source_domain,
                    ReferringDomain.target_domain == target_domain
                ).first()

                if existing:
                    # Update existing record
                    existing.link_count = total_links
                    existing.in_body_percentage = in_body_pct
                    existing.last_updated = datetime.utcnow()
                else:
                    # Create new record
                    referring = ReferringDomain(
                        source_domain=source_domain,
                        target_domain=target_domain,
                        link_count=total_links,
                        in_body_percentage=in_body_pct,
                        first_seen=last_seen,
                        last_updated=datetime.utcnow()
                    )
                    session.add(referring)

            session.commit()
            logger.info("Updated referring_domains aggregates")

        except Exception as e:
            logger.error(f"Error updating referring_domains: {e}")
            session.rollback()

    def process_competitor_page(self, page_id: int) -> int:
        """
        Process a competitor page to extract and store backlinks.

        Args:
            page_id: CompetitorPage database ID

        Returns:
            Number of new backlinks stored
        """
        with self.SessionLocal() as session:
            # Get page details
            page = session.query(CompetitorPage).filter(
                CompetitorPage.id == page_id
            ).first()

            if not page:
                raise ValueError(f"CompetitorPage {page_id} not found")

            logger.info(f"Processing backlinks for {page.url}")

            # Load HTML snapshot
            if not page.html_snapshot_path:
                logger.warning(f"No HTML snapshot for page {page_id}")
                return 0

            from ..competitor.snapshot import load_snapshot

            try:
                html = load_snapshot(page.html_snapshot_path)
            except Exception as e:
                logger.error(f"Failed to load snapshot: {e}")
                return 0

            # Extract links
            source_domain = urlparse(page.url).netloc
            links = self.extract_links_from_html(html, page.url, source_domain)

            # Store backlinks
            new_count = self.store_backlinks(session, page.url, source_domain, links)

            return new_count

    def process_all_pages(self) -> Dict[str, int]:
        """
        Process all competitor pages to extract backlinks.

        Returns:
            Dict with processing stats
        """
        with task_logger.log_task("backlinks_tracker", "backlinks") as log_id:
            with self.SessionLocal() as session:
                # Get all pages with snapshots
                pages = session.query(CompetitorPage).filter(
                    CompetitorPage.html_snapshot_path.isnot(None)
                ).all()

                logger.info(f"Processing {len(pages)} competitor pages")

                total_new = 0
                processed = 0
                failed = 0

                for i, page in enumerate(pages, 1):
                    try:
                        new_count = self.process_competitor_page(page.id)
                        total_new += new_count
                        processed += 1

                        # Update progress
                        task_logger.update_progress(
                            log_id,
                            items_processed=i,
                            items_new=total_new
                        )

                    except Exception as e:
                        logger.error(f"Failed to process page {page.id}: {e}")
                        failed += 1

                # Update referring_domains aggregates
                logger.info("Updating referring_domains aggregates...")
                self.update_referring_domains(session)

                results = {
                    'processed': processed,
                    'new_backlinks': total_new,
                    'failed': failed
                }

                logger.info(
                    f"Backlinks processing complete: {processed} pages, "
                    f"{total_new} new backlinks, {failed} failed"
                )

                return results
