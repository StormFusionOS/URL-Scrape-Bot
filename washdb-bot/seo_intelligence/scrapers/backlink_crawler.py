"""
Backlink Crawler Module

Discovers and tracks backlinks pointing to our websites.

Features:
- Check common backlink sources
- Track referring domains
- Calculate domain authority estimates
- Store in backlinks and referring_domains tables

Per SCRAPING_NOTES.md:
- Use Tier C rate limits for general web crawling
- Track anchor text and link context
- Aggregate at domain level for LAS calculation
"""

import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from urllib.parse import urlparse, urljoin

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_scraper import BaseScraper
from seo_intelligence.services import get_task_logger
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("backlink_crawler")


class BacklinkCrawler(BaseScraper):
    """
    Crawler for discovering backlinks to our websites.

    Checks known backlink sources and tracks referring domains
    for Local Authority Score calculation.
    """

    def __init__(
        self,
        headless: bool = True,  # Hybrid mode: starts headless, upgrades to headed on detection
        use_proxy: bool = False,  # Disabled: datacenter proxies get detected
    ):
        """
        Initialize backlink crawler.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool
        """
        super().__init__(
            name="backlink_crawler",
            tier="C",  # Standard rate limits
            headless=headless,
            respect_robots=False,  # Disabled: need to crawl all sources
            use_proxy=use_proxy,
            max_retries=3,
            page_timeout=30000,
        )

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database storage disabled")

        logger.info("BacklinkCrawler initialized (tier=C)")

    def _get_or_create_referring_domain(
        self,
        session: Session,
        domain: str,
        domain_authority: int = 0,
    ) -> int:
        """
        Get existing referring domain ID or create new record.

        Args:
            session: Database session
            domain: Referring domain
            domain_authority: Estimated domain authority (0-100)

        Returns:
            int: Referring domain ID
        """
        # Check if domain exists
        result = session.execute(
            text("SELECT domain_id FROM referring_domains WHERE domain = :domain"),
            {"domain": domain}
        )
        row = result.fetchone()

        if row:
            # Update last seen
            session.execute(
                text("""
                    UPDATE referring_domains
                    SET total_backlinks = total_backlinks + 1,
                        last_updated_at = NOW()
                    WHERE domain_id = :id
                """),
                {"id": row[0]}
            )
            session.commit()
            return row[0]

        # Create new referring domain
        result = session.execute(
            text("""
                INSERT INTO referring_domains (domain, local_authority_score, total_backlinks, first_seen_at, last_updated_at)
                VALUES (:domain, :local_authority_score, 1, NOW(), NOW())
                RETURNING domain_id
            """),
            {
                "domain": domain,
                "local_authority_score": domain_authority,
            }
        )
        session.commit()

        domain_id = result.fetchone()[0]
        logger.info(f"Created new referring domain: {domain} (ID: {domain_id})")

        return domain_id

    def _save_backlink(
        self,
        session: Session,
        source_domain: str,
        target_url: str,
        source_url: str,
        anchor_text: str = "",
        link_type: str = "dofollow",
        context: Optional[str] = None,
    ) -> int:
        """
        Save backlink to database.

        Args:
            session: Database session
            source_domain: Domain of the page containing the link
            target_url: URL being linked to (our site)
            source_url: URL containing the link
            anchor_text: Link anchor text
            link_type: dofollow, nofollow, ugc, sponsored
            context: Surrounding text context

        Returns:
            int: Backlink ID
        """
        # Extract target domain from target_url
        target_domain = urlparse(target_url).netloc
        if target_domain.startswith('www.'):
            target_domain = target_domain[4:]

        # Check if backlink already exists
        result = session.execute(
            text("""
                SELECT backlink_id FROM backlinks
                WHERE source_url = :source_url AND target_url = :target_url
            """),
            {"source_url": source_url, "target_url": target_url}
        )
        existing = result.fetchone()

        if existing:
            # Update last seen
            session.execute(
                text("""
                    UPDATE backlinks
                    SET last_seen_at = NOW(), is_active = TRUE
                    WHERE backlink_id = :id
                """),
                {"id": existing[0]}
            )
            session.commit()
            return existing[0]

        # Create new backlink
        metadata = {}
        if context:
            metadata["context"] = context[:500]  # Limit context length

        result = session.execute(
            text("""
                INSERT INTO backlinks (
                    target_domain, target_url, source_domain, source_url,
                    anchor_text, link_type, is_active, discovered_at, last_seen_at, metadata
                ) VALUES (
                    :target_domain, :target_url, :source_domain, :source_url,
                    :anchor_text, :link_type, TRUE, NOW(), NOW(), CAST(:metadata AS jsonb)
                )
                ON CONFLICT (target_url, source_url) DO UPDATE SET
                    last_seen_at = NOW(),
                    is_active = TRUE
                RETURNING backlink_id
            """),
            {
                "target_domain": target_domain,
                "target_url": target_url,
                "source_domain": source_domain,
                "source_url": source_url,
                "anchor_text": anchor_text[:500] if anchor_text else "",
                "link_type": link_type,
                "metadata": json.dumps(metadata),
            }
        )
        session.commit()

        return result.fetchone()[0]

    def _detect_link_placement(self, link, soup) -> Dict[str, Any]:
        """
        Detect where a link is placed on the page.

        Analyzes link position to determine if it's in:
        - navigation: Header nav, menu links
        - footer: Footer section
        - sidebar: Aside, sidebar widgets
        - content: Main article body (editorial)
        - comments: User-generated comments section
        - author_bio: Author bio sections

        Args:
            link: BeautifulSoup link element
            soup: Full page soup for context

        Returns:
            Dict with placement info:
            - placement: navigation/footer/sidebar/content/comments/author_bio
            - is_editorial: True if in main content body
            - surrounding_word_count: Words in containing paragraph/block
        """
        placement = "content"  # Default
        is_editorial = True

        # Get all ancestors for analysis
        ancestors = list(link.parents)
        ancestor_tags = [a.name for a in ancestors if a.name]
        ancestor_classes = []
        ancestor_ids = []

        for a in ancestors:
            if hasattr(a, 'get'):
                classes = a.get('class', [])
                if classes:
                    if isinstance(classes, list):
                        ancestor_classes.extend([c.lower() for c in classes])
                    else:
                        ancestor_classes.append(classes.lower())
                id_attr = a.get('id', '')
                if id_attr:
                    ancestor_ids.append(id_attr.lower())

        # Convert to sets for faster lookup
        ancestor_class_set = set(ancestor_classes)
        ancestor_id_set = set(ancestor_ids)

        # Check for navigation
        nav_indicators = {'nav', 'navigation', 'menu', 'navbar', 'header-menu', 'main-menu', 'primary-nav'}
        if 'nav' in ancestor_tags or 'header' in ancestor_tags:
            placement = "navigation"
            is_editorial = False
        elif ancestor_class_set & nav_indicators or ancestor_id_set & nav_indicators:
            placement = "navigation"
            is_editorial = False

        # Check for footer
        footer_indicators = {'footer', 'foot', 'bottom', 'site-footer', 'page-footer'}
        if 'footer' in ancestor_tags:
            placement = "footer"
            is_editorial = False
        elif ancestor_class_set & footer_indicators or ancestor_id_set & footer_indicators:
            placement = "footer"
            is_editorial = False

        # Check for sidebar
        sidebar_indicators = {'sidebar', 'aside', 'widget', 'side-bar', 'right-col', 'left-col'}
        if 'aside' in ancestor_tags:
            placement = "sidebar"
            is_editorial = False
        elif ancestor_class_set & sidebar_indicators or ancestor_id_set & sidebar_indicators:
            placement = "sidebar"
            is_editorial = False

        # Check for comments section
        comment_indicators = {'comment', 'comments', 'discussion', 'respond', 'reply', 'user-content'}
        if ancestor_class_set & comment_indicators or ancestor_id_set & comment_indicators:
            placement = "comments"
            is_editorial = False

        # Check for author bio
        author_indicators = {'author', 'bio', 'about-author', 'author-box', 'byline'}
        if ancestor_class_set & author_indicators or ancestor_id_set & author_indicators:
            placement = "author_bio"
            is_editorial = False

        # Calculate surrounding word count
        surrounding_word_count = 0
        parent = link.parent
        if parent:
            # Try to find the containing paragraph or content block
            content_parent = None
            for ancestor in [parent] + list(parent.parents)[:3]:
                if ancestor.name in ['p', 'article', 'section', 'div']:
                    content_parent = ancestor
                    break

            if content_parent:
                text = content_parent.get_text(strip=True)
                surrounding_word_count = len(text.split())

        return {
            "placement": placement,
            "is_editorial": is_editorial,
            "surrounding_word_count": surrounding_word_count,
        }

    def _extract_backlinks_from_page(
        self,
        html: str,
        source_url: str,
        target_domains: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Extract backlinks to target domains from a page.

        Args:
            html: Page HTML content
            source_url: URL of the source page
            target_domains: List of domains to look for links to

        Returns:
            List of backlink dictionaries with placement detection
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        backlinks = []

        for link in soup.find_all('a', href=True):
            href = link.get('href', '')

            # Skip empty or anchor links
            if not href or href.startswith('#'):
                continue

            # Resolve relative URLs
            full_url = urljoin(source_url, href)
            parsed = urlparse(full_url)
            link_domain = parsed.netloc.lower()

            # Remove www prefix for matching
            if link_domain.startswith('www.'):
                link_domain = link_domain[4:]

            # Check if link points to one of our target domains
            for target in target_domains:
                target_clean = target.lower()
                if target_clean.startswith('www.'):
                    target_clean = target_clean[4:]

                if link_domain == target_clean or link_domain.endswith('.' + target_clean):
                    # Extract anchor text
                    anchor_text = link.get_text(strip=True)

                    # Determine link type from rel attribute
                    rel = link.get('rel', [])
                    if isinstance(rel, str):
                        rel = [rel]

                    link_type = "dofollow"
                    if 'nofollow' in rel:
                        link_type = "nofollow"
                    elif 'ugc' in rel:
                        link_type = "ugc"
                    elif 'sponsored' in rel:
                        link_type = "sponsored"

                    # Get surrounding context
                    context = ""
                    parent = link.parent
                    if parent:
                        context = parent.get_text(strip=True)[:200]

                    # Detect link placement (NEW)
                    placement_info = self._detect_link_placement(link, soup)

                    backlinks.append({
                        "target_url": full_url,
                        "source_url": source_url,
                        "anchor_text": anchor_text,
                        "link_type": link_type,
                        "context": context,
                        # New placement fields
                        "placement": placement_info["placement"],
                        "is_editorial": placement_info["is_editorial"],
                        "surrounding_word_count": placement_info["surrounding_word_count"],
                    })
                    break

        return backlinks

    def check_page_for_backlinks(
        self,
        source_url: str,
        target_domains: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Check a single page for backlinks to target domains.

        Args:
            source_url: URL to check for backlinks
            target_domains: List of our domains to find links to

        Returns:
            List of found backlinks
        """
        logger.info(f"Checking {source_url} for backlinks to {target_domains}")

        try:
            with self.browser_session() as (browser, context, page):
                html = self.fetch_page(
                    url=source_url,
                    page=page,
                    wait_for="domcontentloaded",
                    extra_wait=1.0,
                )

                if not html:
                    logger.warning(f"Failed to fetch {source_url}")
                    return []

                backlinks = self._extract_backlinks_from_page(
                    html, source_url, target_domains
                )

                # Save to database
                if backlinks and self.engine:
                    source_domain = urlparse(source_url).netloc
                    if source_domain.startswith('www.'):
                        source_domain = source_domain[4:]

                    with Session(self.engine) as session:
                        # Also track in referring_domains table for analytics
                        self._get_or_create_referring_domain(session, source_domain)

                        for bl in backlinks:
                            self._save_backlink(
                                session,
                                source_domain=source_domain,
                                target_url=bl["target_url"],
                                source_url=bl["source_url"],
                                anchor_text=bl["anchor_text"],
                                link_type=bl["link_type"],
                                context=bl["context"],
                            )

                logger.info(f"Found {len(backlinks)} backlinks on {source_url}")
                return backlinks

        except Exception as e:
            logger.error(f"Error checking {source_url} for backlinks: {e}")
            return []

    def run(
        self,
        source_urls: List[str],
        target_domains: List[str],
    ) -> Dict[str, Any]:
        """
        Run backlink crawler for multiple source URLs.

        Args:
            source_urls: List of URLs to check for backlinks
            target_domains: List of our domains to find links to

        Returns:
            dict: Results summary
        """
        task_logger = get_task_logger()

        results = {
            "total_sources": len(source_urls),
            "successful": 0,
            "failed": 0,
            "total_backlinks": 0,
            "backlinks_by_type": {
                "dofollow": 0,
                "nofollow": 0,
                "ugc": 0,
                "sponsored": 0,
            },
        }

        with task_logger.log_task("backlink_crawler", "scraper", {"source_count": len(source_urls)}) as task:
            for source_url in source_urls:
                task.increment_processed()

                backlinks = self.check_page_for_backlinks(source_url, target_domains)

                if backlinks:
                    results["successful"] += 1
                    results["total_backlinks"] += len(backlinks)

                    for bl in backlinks:
                        link_type = bl.get("link_type", "dofollow")
                        if link_type in results["backlinks_by_type"]:
                            results["backlinks_by_type"][link_type] += 1

                    task.increment_created(len(backlinks))
                else:
                    results["failed"] += 1

        logger.info(
            f"Backlink crawl complete: {results['successful']}/{results['total_sources']} "
            f"sources checked, {results['total_backlinks']} backlinks found"
        )

        return results


# Module-level singleton
_backlink_crawler_instance = None


def get_backlink_crawler(**kwargs) -> BacklinkCrawler:
    """Get or create the singleton BacklinkCrawler instance."""
    global _backlink_crawler_instance

    if _backlink_crawler_instance is None:
        _backlink_crawler_instance = BacklinkCrawler(**kwargs)

    return _backlink_crawler_instance


def main():
    """Demo/CLI interface for backlink crawler."""
    import argparse

    parser = argparse.ArgumentParser(description="Backlink Crawler")
    parser.add_argument("--source", "-s", help="Source URL to check")
    parser.add_argument("--target", "-t", action="append", help="Target domain(s)")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("Backlink Crawler Demo Mode")
        logger.info("=" * 60)
        logger.info("")
        logger.info("This would check pages for backlinks to your domains.")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python backlink_crawler.py --source 'https://example.com/page' --target 'mysite.com'")
        logger.info("")
        logger.info("=" * 60)
        return

    if not args.source or not args.target:
        parser.print_help()
        return

    crawler = get_backlink_crawler()
    backlinks = crawler.check_page_for_backlinks(args.source, args.target)

    logger.info(f"Found {len(backlinks)} backlinks")
    for bl in backlinks:
        logger.info(f"  - {bl['anchor_text']}: {bl['target_url']} ({bl['link_type']})")


if __name__ == "__main__":
    main()
