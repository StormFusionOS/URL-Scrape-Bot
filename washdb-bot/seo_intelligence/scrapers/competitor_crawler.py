"""
Competitor Crawler Module

Crawls competitor websites to analyze their SEO strategy.

Features:
- Discover competitors from SERP results
- Crawl competitor pages (homepage, services, etc.)
- Extract SEO metrics (titles, meta, schema, content)
- Track content changes via SHA-256 hashing
- Store in competitors and competitor_pages tables

Per SCRAPING_NOTES.md:
- Use Tier B rate limits (10-20s delay) for competitor sites
- Respect robots.txt for each domain
- Hash content for change detection
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
from seo_intelligence.scrapers.competitor_parser import get_competitor_parser, PageMetrics
from seo_intelligence.services import (
    get_task_logger,
    get_content_hasher,
    get_content_embedder,
    get_qdrant_manager,
    extract_main_content
)
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("competitor_crawler")


class CompetitorCrawler(BaseScraper):
    """
    Crawler for competitor website analysis.

    Discovers competitors from SERP results and crawls their pages
    to extract SEO metrics and track changes over time.
    """

    def __init__(
        self,
        headless: bool = True,
        use_proxy: bool = True,
        max_pages_per_site: int = 10,
        enable_embeddings: bool = True,
    ):
        """
        Initialize competitor crawler.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool
            max_pages_per_site: Maximum pages to crawl per competitor
            enable_embeddings: Enable Qdrant embedding generation (per SCRAPER BOT.pdf)
        """
        super().__init__(
            name="competitor_crawler",
            tier="B",  # Medium-value targets (competitor sites)
            headless=headless,
            respect_robots=True,
            use_proxy=use_proxy,
            max_retries=3,
            page_timeout=30000,
        )

        self.max_pages_per_site = max_pages_per_site
        self.parser = get_competitor_parser()
        self.hasher = get_content_hasher()
        self.enable_embeddings = enable_embeddings

        # Initialize embedding services if enabled
        if self.enable_embeddings:
            try:
                self.embedder = get_content_embedder()
                self.qdrant = get_qdrant_manager()
                logger.info("✓ Embedding services initialized")
            except Exception as e:
                logger.warning(f"Embedding services unavailable: {e}. Continuing without embeddings.")
                self.enable_embeddings = False

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database storage disabled")

        logger.info(f"CompetitorCrawler initialized (tier=B, max_pages={max_pages_per_site})")

    def _get_or_create_competitor(
        self,
        session: Session,
        domain: str,
        name: Optional[str] = None,
        website_url: Optional[str] = None,
        business_type: Optional[str] = None,
        location: Optional[str] = None,
    ) -> int:
        """
        Get existing competitor ID or create new record.

        Args:
            session: Database session
            domain: Competitor domain
            name: Business name
            website_url: Full website URL
            business_type: Type of business
            location: Location

        Returns:
            int: Competitor ID
        """
        # Check if competitor exists
        result = session.execute(
            text("SELECT competitor_id FROM competitors WHERE domain = :domain"),
            {"domain": domain}
        )
        row = result.fetchone()

        if row:
            # Update last_crawled_at
            session.execute(
                text("UPDATE competitors SET last_crawled_at = NOW() WHERE competitor_id = :id"),
                {"id": row[0]}
            )
            session.commit()
            return row[0]

        # Create new competitor
        result = session.execute(
            text("""
                INSERT INTO competitors (domain, name, website_url, business_type, location, is_active)
                VALUES (:domain, :name, :website_url, :business_type, :location, TRUE)
                RETURNING competitor_id
            """),
            {
                "domain": domain,
                "name": name or domain,
                "website_url": website_url or f"https://{domain}",
                "business_type": business_type,
                "location": location,
            }
        )
        session.commit()

        competitor_id = result.fetchone()[0]
        logger.info(f"Created new competitor: {domain} (ID: {competitor_id})")

        return competitor_id

    def _save_page(
        self,
        session: Session,
        competitor_id: int,
        metrics: PageMetrics,
        html: str,
        status_code: int = 200,
    ) -> int:
        """
        Save competitor page to database.

        Args:
            session: Database session
            competitor_id: Competitor ID
            metrics: Extracted page metrics
            html: Raw HTML content
            status_code: HTTP status code

        Returns:
            int: Page ID
        """
        # Calculate content hash
        content_hash = self.hasher.hash_content(html, normalize=True)

        # Prepare data
        h1_tags = metrics.h1_tags[:5]  # Store first 5 H1s
        schema_markup = metrics.schema_markup[:3]  # Store first 3 schemas
        links = {
            "internal_count": metrics.internal_links,
            "external_count": metrics.external_links,
            "social": metrics.social_links,
        }
        meta = {
            "h2_tags": metrics.h2_tags,
            "h3_tags": metrics.h3_tags,
            "images": metrics.images,
            "images_with_alt": metrics.images_with_alt,
            "has_contact_form": metrics.has_contact_form,
            "has_phone": metrics.has_phone,
            "has_email": metrics.has_email,
            "meta_keywords": metrics.meta_keywords,
            "canonical_url": metrics.canonical_url,
            "schema_types": metrics.schema_types,
        }

        # Insert page record
        result = session.execute(
            text("""
                INSERT INTO competitor_pages (
                    competitor_id, url, page_type, title, meta_description,
                    h1_tags, content_hash, word_count, status_code,
                    schema_markup, links, metadata
                ) VALUES (
                    :competitor_id, :url, :page_type, :title, :meta_description,
                    :h1_tags, :content_hash, :word_count, :status_code,
                    :schema_markup::jsonb, :links::jsonb, :metadata::jsonb
                )
                RETURNING page_id
            """),
            {
                "competitor_id": competitor_id,
                "url": metrics.url,
                "page_type": metrics.page_type,
                "title": metrics.title[:500] if metrics.title else "",
                "meta_description": metrics.meta_description[:1000] if metrics.meta_description else "",
                "h1_tags": h1_tags,
                "content_hash": content_hash,
                "word_count": metrics.word_count,
                "status_code": status_code,
                "schema_markup": json.dumps(schema_markup),
                "links": json.dumps(links),
                "metadata": json.dumps(meta),
            }
        )
        session.commit()

        page_id = result.fetchone()[0]

        # Generate and store embeddings (per SCRAPER BOT.pdf)
        if self.enable_embeddings:
            try:
                # Extract main content from HTML
                main_text = extract_main_content(html)

                if main_text and len(main_text.strip()) > 50:  # Only embed if substantial content
                    # Generate embeddings
                    chunks, embeddings = self.embedder.embed_content(main_text)

                    if chunks and embeddings:
                        # Store first chunk embedding in Qdrant (per spec)
                        self.qdrant.upsert_competitor_page(
                            page_id=page_id,
                            site_id=competitor_id,
                            url=metrics.url,
                            title=metrics.title or "",
                            page_type=metrics.page_type,
                            vector=embeddings[0]
                        )

                        # Update database with embedding metadata
                        session.execute(
                            text("""
                                UPDATE competitor_pages
                                SET embedding_version = :version,
                                    embedded_at = NOW(),
                                    embedding_chunk_count = :chunk_count
                                WHERE page_id = :page_id
                            """),
                            {
                                "version": os.getenv("EMBEDDING_VERSION", "v1.0"),
                                "chunk_count": len(chunks),
                                "page_id": page_id
                            }
                        )
                        session.commit()
                        logger.info(f"✓ Embedded page {page_id} ({len(chunks)} chunks, {len(main_text)} chars)")
                else:
                    logger.debug(f"Skipping embedding for page {page_id} - insufficient content")
            except Exception as e:
                logger.error(f"Failed to generate embeddings for page {page_id}: {e}")
                # Continue without embeddings - don't fail the entire save operation

        return page_id

    def _discover_pages(self, base_url: str, html: str) -> List[str]:
        """
        Discover important pages to crawl from homepage.

        Args:
            base_url: Base URL of the site
            html: Homepage HTML

        Returns:
            List of URLs to crawl
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        base_domain = urlparse(base_url).netloc
        pages = set()

        # Important page patterns
        important_patterns = [
            r'/services?', r'/about', r'/contact', r'/pricing',
            r'/gallery', r'/portfolio', r'/reviews?', r'/testimonials?',
            r'/faq', r'/blog$'
        ]

        for link in soup.find_all('a', href=True):
            href = link.get('href', '')

            # Skip empty/anchor links
            if not href or href.startswith('#'):
                continue

            # Resolve relative URLs
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)

            # Only internal links
            if parsed.netloc != base_domain:
                continue

            # Check if important page
            path = parsed.path.lower()
            for pattern in important_patterns:
                import re
                if re.search(pattern, path):
                    # Normalize URL (remove query strings)
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    pages.add(clean_url)
                    break

        return list(pages)[:self.max_pages_per_site - 1]  # Reserve 1 for homepage

    def crawl_competitor(
        self,
        domain: str,
        website_url: Optional[str] = None,
        name: Optional[str] = None,
        business_type: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Crawl a single competitor website.

        Args:
            domain: Competitor domain
            website_url: Full URL (defaults to https://{domain})
            name: Business name
            business_type: Type of business
            location: Location

        Returns:
            dict: Crawl results summary
        """
        website_url = website_url or f"https://{domain}"
        logger.info(f"Crawling competitor: {domain}")

        results = {
            "domain": domain,
            "pages_crawled": 0,
            "pages_failed": 0,
            "total_words": 0,
            "schema_types": set(),
        }

        try:
            with self.browser_session() as (browser, context, page):
                # Crawl homepage first
                html = self.fetch_page(
                    url=website_url,
                    page=page,
                    wait_for="domcontentloaded",
                    extra_wait=2.0,
                )

                if not html:
                    logger.error(f"Failed to fetch homepage for {domain}")
                    return None

                # Parse homepage
                metrics = self.parser.parse(html, website_url)

                # Save to database
                if self.engine:
                    with Session(self.engine) as session:
                        competitor_id = self._get_or_create_competitor(
                            session, domain, name, website_url, business_type, location
                        )
                        self._save_page(session, competitor_id, metrics, html)

                results["pages_crawled"] += 1
                results["total_words"] += metrics.word_count
                results["schema_types"].update(metrics.schema_types)

                # Discover and crawl additional pages
                additional_urls = self._discover_pages(website_url, html)
                logger.info(f"Discovered {len(additional_urls)} additional pages for {domain}")

                for url in additional_urls:
                    try:
                        page_html = self.fetch_page(
                            url=url,
                            page=page,
                            wait_for="domcontentloaded",
                            extra_wait=1.0,
                        )

                        if page_html:
                            page_metrics = self.parser.parse(page_html, url)

                            if self.engine:
                                with Session(self.engine) as session:
                                    self._save_page(session, competitor_id, page_metrics, page_html)

                            results["pages_crawled"] += 1
                            results["total_words"] += page_metrics.word_count
                            results["schema_types"].update(page_metrics.schema_types)
                        else:
                            results["pages_failed"] += 1

                    except Exception as e:
                        logger.warning(f"Error crawling {url}: {e}")
                        results["pages_failed"] += 1
                        continue

                # Convert set to list for JSON serialization
                results["schema_types"] = list(results["schema_types"])

                logger.info(
                    f"Crawled {domain}: {results['pages_crawled']} pages, "
                    f"{results['total_words']} words, {len(results['schema_types'])} schema types"
                )

                return results

        except Exception as e:
            logger.error(f"Error crawling competitor {domain}: {e}", exc_info=True)
            return None

    def discover_from_serp(
        self,
        serp_results: List[Dict],
        our_domains: List[str],
        business_type: Optional[str] = None,
        location: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Discover and crawl competitors from SERP results.

        Args:
            serp_results: List of SERP result dicts with 'domain', 'url', 'title'
            our_domains: Our company's domains (to exclude)
            business_type: Type of business
            location: Location context

        Returns:
            List of crawl results
        """
        crawl_results = []
        seen_domains = set(our_domains)

        for result in serp_results:
            domain = result.get('domain', '')

            # Skip our domains and already seen
            if not domain or domain in seen_domains:
                continue

            # Skip common non-competitor sites
            skip_domains = [
                'google.com', 'yelp.com', 'yellowpages.com', 'facebook.com',
                'bbb.org', 'mapquest.com', 'thumbtack.com', 'angi.com',
                'homeadvisor.com', 'houzz.com', 'porch.com',
            ]
            if any(skip in domain for skip in skip_domains):
                continue

            seen_domains.add(domain)

            # Crawl competitor
            crawl_result = self.crawl_competitor(
                domain=domain,
                website_url=result.get('url'),
                name=result.get('title', '').split(' - ')[0].split(' | ')[0],
                business_type=business_type,
                location=location,
            )

            if crawl_result:
                crawl_results.append(crawl_result)

        return crawl_results

    def run(
        self,
        competitors: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Run competitor crawler for multiple domains.

        Args:
            competitors: List of competitor dicts with 'domain' and optional metadata

        Returns:
            dict: Results summary
        """
        task_logger = get_task_logger()

        results = {
            "total_competitors": len(competitors),
            "successful": 0,
            "failed": 0,
            "total_pages": 0,
            "total_words": 0,
        }

        with task_logger.log_task("competitor_crawler", "scraper", {"count": len(competitors)}) as task:
            for competitor in competitors:
                domain = competitor.get("domain", "")

                if not domain:
                    continue

                task.increment_processed()

                crawl_result = self.crawl_competitor(
                    domain=domain,
                    website_url=competitor.get("website_url"),
                    name=competitor.get("name"),
                    business_type=competitor.get("business_type"),
                    location=competitor.get("location"),
                )

                if crawl_result:
                    results["successful"] += 1
                    results["total_pages"] += crawl_result["pages_crawled"]
                    results["total_words"] += crawl_result["total_words"]
                    task.increment_created()
                else:
                    results["failed"] += 1

        logger.info(
            f"Competitor crawl complete: {results['successful']}/{results['total_competitors']} "
            f"sites, {results['total_pages']} pages, {results['total_words']} words"
        )

        return results


# Module-level singleton
_competitor_crawler_instance = None


def get_competitor_crawler(**kwargs) -> CompetitorCrawler:
    """Get or create the singleton CompetitorCrawler instance."""
    global _competitor_crawler_instance

    if _competitor_crawler_instance is None:
        _competitor_crawler_instance = CompetitorCrawler(**kwargs)

    return _competitor_crawler_instance


def main():
    """Demo/CLI interface for competitor crawler."""
    import argparse

    parser = argparse.ArgumentParser(description="Competitor Crawler")
    parser.add_argument("domain", nargs="?", help="Competitor domain to crawl")
    parser.add_argument("--name", "-n", help="Business name")
    parser.add_argument("--location", "-l", help="Location")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-proxy", action="store_true", help="Disable proxy")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("Competitor Crawler Demo Mode")
        logger.info("=" * 60)
        logger.info("")
        logger.info("This would crawl a competitor website.")
        logger.info("Note: Actual crawling requires Playwright and proper setup.")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python competitor_crawler.py example-competitor.com")
        logger.info("  python competitor_crawler.py example.com --name 'ABC Company' --location 'Austin, TX'")
        logger.info("")
        logger.info("=" * 60)
        return

    if not args.domain:
        parser.print_help()
        return

    # Create crawler
    crawler = CompetitorCrawler(
        headless=args.headless,
        use_proxy=not args.no_proxy,
    )

    # Crawl competitor
    result = crawler.crawl_competitor(
        domain=args.domain,
        name=args.name,
        location=args.location,
    )

    if result:
        logger.info("")
        logger.info(f"Results for {args.domain}:")
        logger.info("=" * 60)
        logger.info(f"Pages crawled: {result['pages_crawled']}")
        logger.info(f"Pages failed: {result['pages_failed']}")
        logger.info(f"Total words: {result['total_words']}")
        logger.info(f"Schema types: {result['schema_types']}")
    else:
        logger.error("Crawling failed")


if __name__ == "__main__":
    main()
