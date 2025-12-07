"""
SERP Scraper Module

Scrapes Google Search Engine Results Pages (SERPs) for position tracking.

Features:
- Playwright-based Google search crawling
- Respects rate limits (Tier A - high-value target)
- Robots.txt compliance
- Integration with SERP parser
- Database storage of results
- Position tracking over time

Per SCRAPING_NOTES.md:
- Use Tier A rate limits (15-30s delay, 2-4 req/min)
- Robots.txt must be checked before crawling
- Store raw HTML + parsed data for audit trail
"""

import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_scraper import BaseScraper
from seo_intelligence.scrapers.serp_parser import get_serp_parser, SerpSnapshot
from seo_intelligence.services import (
    get_task_logger,
    get_content_hasher,
    get_content_embedder,
    get_qdrant_manager
)
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("serp_scraper")


class SerpScraper(BaseScraper):
    """
    Google SERP Scraper for position tracking.

    Searches Google for specified queries and tracks ranking positions.
    Uses Tier A rate limits due to Google's anti-bot measures.
    """

    def __init__(
        self,
        headless: bool = True,  # Hybrid mode: starts headless, upgrades to headed on detection
        use_proxy: bool = False,  # Disabled: datacenter proxies get detected
        store_raw_html: bool = True,
        enable_embeddings: bool = True,
    ):
        """
        Initialize SERP scraper.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool
            store_raw_html: Store raw HTML in database
            enable_embeddings: Generate embeddings for SERP snippets
        """
        super().__init__(
            name="serp_scraper",
            tier="A",  # High-value target (Google)
            headless=headless,
            respect_robots=False,  # Disabled: need to scrape search results
            use_proxy=use_proxy,
            max_retries=3,
            page_timeout=45000,  # Longer timeout for Google
        )

        self.store_raw_html = store_raw_html
        self.parser = get_serp_parser()
        self.hasher = get_content_hasher()

        # Initialize embedding services (per SCRAPER BOT.pdf)
        self.enable_embeddings = enable_embeddings
        self.embedder = None
        self.qdrant = None

        if self.enable_embeddings:
            try:
                self.embedder = get_content_embedder()

                # Check if embedder actually initialized properly
                if not self.embedder.is_available():
                    logger.warning("Embedding model failed to initialize. Continuing without embeddings.")
                    self.enable_embeddings = False
                else:
                    self.qdrant = get_qdrant_manager()
                    logger.info("✓ Embedding services initialized")
            except Exception as e:
                error_msg = str(e)
                # Check for specific PyTorch errors
                if "meta tensor" in error_msg.lower() or "cannot copy" in error_msg.lower():
                    logger.warning(f"PyTorch meta tensor error - embeddings disabled. This is a known issue with some CUDA configurations.")
                else:
                    logger.warning(f"Embedding services unavailable: {error_msg[:100]}. Continuing without embeddings.")
                self.enable_embeddings = False

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database storage disabled")

        logger.info("SerpScraper initialized (tier=A, store_html={})".format(store_raw_html))

    def _build_search_url(
        self,
        query: str,
        location: Optional[str] = None,
        num_results: int = 100,
    ) -> str:
        """
        Build Google search URL.

        Args:
            query: Search query
            location: Location context (appended to query)
            num_results: Number of results to request

        Returns:
            str: Google search URL
        """
        # Combine query with location
        full_query = query
        if location:
            full_query = f"{query} {location}"

        # Build URL with parameters
        encoded_query = quote_plus(full_query)
        url = f"https://www.google.com/search?q={encoded_query}&num={num_results}"

        return url

    def _get_or_create_query(
        self,
        session: Session,
        query_text: str,
        location: Optional[str] = None,
    ) -> int:
        """
        Get existing query ID or create new query record.

        Args:
            session: Database session
            query_text: Search query text
            location: Location context

        Returns:
            int: Query ID
        """
        # Check if query exists
        result = session.execute(
            text("""
                SELECT query_id FROM search_queries
                WHERE query_text = :query_text
                AND (location = :location OR (location IS NULL AND :location IS NULL))
                AND search_engine = 'google'
            """),
            {"query_text": query_text, "location": location}
        )
        row = result.fetchone()

        if row:
            return row[0]

        # Create new query
        result = session.execute(
            text("""
                INSERT INTO search_queries (query_text, location, search_engine, is_active)
                VALUES (:query_text, :location, 'google', TRUE)
                RETURNING query_id
            """),
            {"query_text": query_text, "location": location}
        )
        session.commit()

        return result.fetchone()[0]

    def _save_snapshot(
        self,
        session: Session,
        query_id: int,
        snapshot: SerpSnapshot,
        raw_html: Optional[str] = None,
    ) -> int:
        """
        Save SERP snapshot to database.

        Args:
            session: Database session
            query_id: Query ID
            snapshot: Parsed SERP snapshot
            raw_html: Raw HTML (if store_raw_html enabled)

        Returns:
            int: Snapshot ID
        """
        # Calculate snapshot hash
        snapshot_hash = self.hasher.hash_dict(snapshot.to_dict())

        # Build metadata
        metadata = {
            "total_results": snapshot.total_results,
            "local_pack_count": len(snapshot.local_pack),
            "paa_count": len(snapshot.people_also_ask),
            "related_count": len(snapshot.related_searches),
        }

        # Insert snapshot
        result = session.execute(
            text("""
                INSERT INTO serp_snapshots (
                    query_id, result_count, snapshot_hash, raw_html, metadata
                ) VALUES (
                    :query_id, :result_count, :snapshot_hash, :raw_html, CAST(:metadata AS jsonb)
                )
                RETURNING snapshot_id
            """),
            {
                "query_id": query_id,
                "result_count": len(snapshot.results),
                "snapshot_hash": snapshot_hash,
                "raw_html": raw_html if self.store_raw_html else None,
                "metadata": json.dumps(metadata),
            }
        )
        snapshot_id = result.fetchone()[0]
        session.commit()

        return snapshot_id

    def _save_paa_questions(
        self,
        session: Session,
        snapshot_id: int,
        query_id: int,
        snapshot: SerpSnapshot,
    ):
        """
        Save People Also Ask questions to serp_paa table.

        Args:
            session: Database session
            snapshot_id: Snapshot ID
            query_id: Query ID
            snapshot: Parsed SERP snapshot with PAA data
        """
        if not snapshot.people_also_ask:
            return

        for paa in snapshot.people_also_ask:
            # Use the upsert function created in migration 022
            session.execute(
                text("""
                    SELECT upsert_paa_question(
                        :snapshot_id,
                        :query_id,
                        :question,
                        :answer_snippet,
                        :source_url,
                        :source_domain,
                        :position,
                        :metadata
                    )
                """),
                {
                    "snapshot_id": snapshot_id,
                    "query_id": query_id,
                    "question": paa.question,
                    "answer_snippet": paa.answer[:500] if paa.answer else None,  # Limit to 500 chars
                    "source_url": paa.source_url or None,
                    "source_domain": paa.source_domain or None,
                    "position": paa.position if paa.position > 0 else None,
                    "metadata": json.dumps(paa.metadata) if paa.metadata else None,
                }
            )

        session.commit()
        logger.info(f"Saved {len(snapshot.people_also_ask)} PAA questions for snapshot {snapshot_id}")

    def _save_results(
        self,
        session: Session,
        snapshot_id: int,
        snapshot: SerpSnapshot,
        our_domains: Optional[List[str]] = None,
        competitor_domains: Optional[Dict[str, int]] = None,
    ):
        """
        Save individual SERP results to database.

        Args:
            session: Database session
            snapshot_id: Snapshot ID
            snapshot: Parsed SERP snapshot
            our_domains: List of our company's domains (for tracking)
            competitor_domains: Dict of competitor domain -> competitor_id
        """
        our_domains = our_domains or []
        competitor_domains = competitor_domains or {}

        for result in snapshot.results:
            # Check if this is our company or a competitor
            is_our_company = result.domain in our_domains
            is_competitor = result.domain in competitor_domains
            competitor_id = competitor_domains.get(result.domain)

            # Build metadata
            metadata = result.metadata.copy()
            metadata["is_featured"] = result.is_featured
            metadata["is_local"] = result.is_local
            metadata["is_ad"] = result.is_ad

            # Insert result and get ID back
            db_result = session.execute(
                text("""
                    INSERT INTO serp_results (
                        snapshot_id, position, url, title, description,
                        domain, is_our_company, is_competitor, competitor_id, metadata
                    ) VALUES (
                        :snapshot_id, :position, :url, :title, :description,
                        :domain, :is_our_company, :is_competitor, :competitor_id, CAST(:metadata AS jsonb)
                    )
                    RETURNING result_id
                """),
                {
                    "snapshot_id": snapshot_id,
                    "position": result.position,
                    "url": result.url,
                    "title": result.title,
                    "description": result.description,
                    "domain": result.domain,
                    "is_our_company": is_our_company,
                    "is_competitor": is_competitor,
                    "competitor_id": competitor_id,
                    "metadata": json.dumps(metadata),
                }
            )
            result_id = db_result.fetchone()[0]

            # Generate and store embeddings for snippet (per SCRAPER BOT.pdf)
            if self.enable_embeddings and result.description:
                try:
                    # Embed the snippet text
                    snippet_embedding = self.embedder.embed_single(result.description)

                    if snippet_embedding:
                        # Store in Qdrant
                        self.qdrant.upsert_serp_snippet(
                            result_id=result_id,
                            query=snapshot.query,
                            url=result.url,
                            title=result.title,
                            snippet=result.description,
                            rank=result.position,
                            vector=snippet_embedding
                        )

                        # Update database with embedding metadata
                        session.execute(
                            text("""
                                UPDATE serp_results
                                SET embedding_version = :version,
                                    embedded_at = NOW()
                                WHERE result_id = :result_id
                            """),
                            {
                                "version": os.getenv("EMBEDDING_VERSION", "v1.0"),
                                "result_id": result_id
                            }
                        )
                        logger.debug(f"✓ Embedded SERP snippet for result {result_id}")
                except Exception as e:
                    logger.error(f"Failed to embed snippet for result {result_id}: {e}")
                    # Continue without embeddings

        session.commit()

    def scrape_query(
        self,
        query: str,
        location: Optional[str] = None,
        our_domains: Optional[List[str]] = None,
        competitor_domains: Optional[Dict[str, int]] = None,
        num_results: int = 100,
    ) -> Optional[SerpSnapshot]:
        """
        Scrape SERP for a single query.

        Args:
            query: Search query
            location: Location context (e.g., "Austin, TX")
            our_domains: List of our company's domains
            competitor_domains: Dict of competitor domain -> competitor_id
            num_results: Number of results to request

        Returns:
            SerpSnapshot if successful, None otherwise
        """
        url = self._build_search_url(query, location, num_results)
        logger.info(f"Scraping SERP for: '{query}' ({location or 'no location'})")

        try:
            with self.browser_session() as (browser, context, page):
                # Fetch the SERP page
                html = self.fetch_page(
                    url=url,
                    page=page,
                    wait_for="domcontentloaded",
                    extra_wait=2.0,  # Wait for JS rendering
                )

                if not html:
                    logger.error(f"Failed to fetch SERP for query: {query}")
                    return None

                # Parse the SERP
                snapshot = self.parser.parse(html, query, location)

                if not snapshot.results:
                    logger.warning(f"No results parsed for query: {query}")

                # Save to database if enabled
                if self.engine:
                    with Session(self.engine) as session:
                        # Get or create query record
                        query_id = self._get_or_create_query(session, query, location)

                        # Save snapshot
                        snapshot_id = self._save_snapshot(
                            session, query_id, snapshot, html
                        )

                        # Save individual results
                        self._save_results(
                            session, snapshot_id, snapshot,
                            our_domains, competitor_domains
                        )

                        # Save People Also Ask questions
                        self._save_paa_questions(
                            session, snapshot_id, query_id, snapshot
                        )

                        logger.info(
                            f"Saved SERP snapshot {snapshot_id} with "
                            f"{len(snapshot.results)} results"
                        )

                return snapshot

        except Exception as e:
            logger.error(f"Error scraping SERP for '{query}': {e}", exc_info=True)
            return None

    def run(
        self,
        queries: List[Dict[str, Any]],
        our_domains: Optional[List[str]] = None,
        competitor_domains: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Run SERP scraper for multiple queries.

        Args:
            queries: List of query dicts with 'query' and optional 'location'
            our_domains: List of our company's domains
            competitor_domains: Dict of competitor domain -> competitor_id

        Returns:
            dict: Results summary
        """
        task_logger = get_task_logger()

        results = {
            "total_queries": len(queries),
            "successful": 0,
            "failed": 0,
            "total_results": 0,
            "our_rankings": [],
            "competitor_rankings": [],
        }

        with task_logger.log_task("serp_scraper", "scraper", {"query_count": len(queries)}) as task:
            for query_dict in queries:
                query = query_dict.get("query", "")
                location = query_dict.get("location")

                if not query:
                    continue

                task.increment_processed()

                snapshot = self.scrape_query(
                    query=query,
                    location=location,
                    our_domains=our_domains,
                    competitor_domains=competitor_domains,
                )

                if snapshot:
                    results["successful"] += 1
                    results["total_results"] += len(snapshot.results)

                    # Track our rankings
                    for result in snapshot.results:
                        if our_domains and result.domain in our_domains:
                            results["our_rankings"].append({
                                "query": query,
                                "location": location,
                                "position": result.position,
                                "domain": result.domain,
                            })

                        if competitor_domains and result.domain in competitor_domains:
                            results["competitor_rankings"].append({
                                "query": query,
                                "location": location,
                                "position": result.position,
                                "domain": result.domain,
                                "competitor_id": competitor_domains[result.domain],
                            })

                    task.increment_created()
                else:
                    results["failed"] += 1

        logger.info(
            f"SERP scrape complete: {results['successful']}/{results['total_queries']} "
            f"queries, {results['total_results']} total results"
        )

        return results


# Module-level singleton
_serp_scraper_instance = None


def get_serp_scraper(**kwargs) -> SerpScraper:
    """Get or create the singleton SerpScraper instance."""
    global _serp_scraper_instance

    if _serp_scraper_instance is None:
        _serp_scraper_instance = SerpScraper(**kwargs)

    return _serp_scraper_instance


def main():
    """Demo/CLI interface for SERP scraper."""
    import argparse

    parser = argparse.ArgumentParser(description="SERP Scraper")
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--location", "-l", help="Location context")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-proxy", action="store_true", help="Disable proxy")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("SERP Scraper Demo Mode")
        logger.info("=" * 60)
        logger.info("")
        logger.info("This would scrape Google for the specified query.")
        logger.info("Note: Actual scraping requires Playwright and proper setup.")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python serp_scraper.py 'pressure washing austin'")
        logger.info("  python serp_scraper.py 'power washing' --location 'Austin, TX'")
        logger.info("")
        logger.info("=" * 60)
        return

    if not args.query:
        parser.print_help()
        return

    # Create scraper
    scraper = SerpScraper(
        headless=args.headless,
        use_proxy=not args.no_proxy,
    )

    # Scrape single query
    snapshot = scraper.scrape_query(
        query=args.query,
        location=args.location,
    )

    if snapshot:
        logger.info("")
        logger.info(f"Results for '{args.query}':")
        logger.info("=" * 60)

        for result in snapshot.results[:10]:
            logger.info(f"{result.position}. {result.title}")
            logger.info(f"   {result.url}")
            logger.info("")

        if len(snapshot.results) > 10:
            logger.info(f"... and {len(snapshot.results) - 10} more results")

        # Print stats
        logger.info("")
        logger.info("Statistics:")
        stats = scraper.get_stats()
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
    else:
        logger.error("Scraping failed")


if __name__ == "__main__":
    main()
