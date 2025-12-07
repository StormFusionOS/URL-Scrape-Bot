"""
SERP Scraper Module (SeleniumBase Version)

Scrapes Google Search Engine Results Pages (SERPs) for position tracking.
Uses SeleniumBase with Undetected Chrome for better anti-detection than Playwright.

This is a drop-in replacement for serp_scraper.py using SeleniumBase instead of Playwright.

Features:
- SeleniumBase UC-based Google search crawling (better anti-detection)
- Respects rate limits (Tier A - high-value target)
- Integration with SERP parser
- Database storage of results
- Position tracking over time

Per SCRAPING_NOTES.md:
- Use Tier A rate limits (15-30s delay, 2-4 req/min)
- Store raw HTML + parsed data for audit trail
"""

import os
import json
import time
import random
from typing import Dict, Any, List, Optional
from datetime import datetime
from urllib.parse import quote_plus

from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper
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

logger = get_logger("serp_scraper_selenium")


class SerpScraperSelenium(BaseSeleniumScraper):
    """
    Google SERP Scraper using SeleniumBase (Undetected Chrome).

    This is the SeleniumBase equivalent of SerpScraper, providing better
    anti-detection than the Playwright version.

    Uses Tier A rate limits due to Google's anti-bot measures.
    """

    def __init__(
        self,
        headless: bool = True,
        use_proxy: bool = True,  # Enabled by default with UC mode
        store_raw_html: bool = True,
        enable_embeddings: bool = True,
    ):
        """
        Initialize SERP scraper.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool (recommended with UC mode)
            store_raw_html: Store raw HTML in database
            enable_embeddings: Generate embeddings for SERP snippets
        """
        super().__init__(
            name="serp_scraper_selenium",
            tier="A",  # High-value target (Google)
            headless=headless,
            respect_robots=False,  # Need to scrape search results
            use_proxy=use_proxy,
            max_retries=3,
            page_timeout=45,  # Seconds for Selenium
        )

        self.store_raw_html = store_raw_html
        self.parser = get_serp_parser()
        self.hasher = get_content_hasher()

        # Initialize embedding services
        self.enable_embeddings = enable_embeddings
        self.embedder = None
        self.qdrant = None

        if self.enable_embeddings:
            try:
                self.embedder = get_content_embedder()

                if not self.embedder.is_available():
                    logger.warning("Embedding model failed to initialize. Continuing without embeddings.")
                    self.enable_embeddings = False
                else:
                    self.qdrant = get_qdrant_manager()
                    logger.info("Embedding services initialized")
            except Exception as e:
                error_msg = str(e)
                if "meta tensor" in error_msg.lower() or "cannot copy" in error_msg.lower():
                    logger.warning("PyTorch meta tensor error - embeddings disabled.")
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

        logger.info(f"SerpScraperSelenium initialized (tier=A, store_html={store_raw_html})")

    def _build_search_url(
        self,
        query: str,
        location: Optional[str] = None,
        num_results: int = 100,
    ) -> str:
        """Build Google search URL."""
        full_query = query
        if location:
            full_query = f"{query} {location}"

        encoded_query = quote_plus(full_query)
        url = f"https://www.google.com/search?q={encoded_query}&num={num_results}"

        return url

    def _perform_search_via_input(
        self,
        driver,
        query: str,
        location: Optional[str] = None
    ) -> bool:
        """
        Perform search by typing into Google's search box (more human-like).

        Args:
            driver: SeleniumBase driver
            query: Search query
            location: Location context

        Returns:
            True if search performed, False on error
        """
        try:
            full_query = query
            if location:
                full_query = f"{query} {location}"

            # Find search input
            search_input = None
            input_selectors = [
                'input[name="q"]',
                'textarea[name="q"]',
                'input[aria-label="Search"]',
            ]

            for selector in input_selectors:
                try:
                    search_input = self.wait_for_element(
                        driver, selector, timeout=10, condition="clickable"
                    )
                    if search_input:
                        break
                except Exception:
                    continue

            if not search_input:
                logger.warning("Could not find search input, using URL navigation")
                return False

            # Click on search box
            self._human_click(driver, search_input)
            time.sleep(random.uniform(0.3, 0.7))

            # Clear and type query with human-like delays
            search_input.clear()
            self._human_type(driver, search_input, full_query, clear_first=False)

            # Submit search
            time.sleep(random.uniform(0.2, 0.5))
            search_input.send_keys(Keys.RETURN)

            # Wait for results
            time.sleep(random.uniform(2, 4))

            return True

        except Exception as e:
            logger.warning(f"Search via input failed: {e}")
            return False

    def _get_or_create_query(
        self,
        session: Session,
        query_text: str,
        location: Optional[str] = None,
    ) -> int:
        """Get existing query ID or create new query record."""
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
        """Save SERP snapshot to database."""
        snapshot_hash = self.hasher.hash_dict(snapshot.to_dict())

        metadata = {
            "total_results": snapshot.total_results,
            "local_pack_count": len(snapshot.local_pack),
            "paa_count": len(snapshot.people_also_ask),
            "related_count": len(snapshot.related_searches),
            "scraper": "selenium",  # Mark this was scraped with Selenium
        }

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
        """Save People Also Ask questions to serp_paa table."""
        if not snapshot.people_also_ask:
            return

        for paa in snapshot.people_also_ask:
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
                    "answer_snippet": paa.answer[:500] if paa.answer else None,
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
        """Save individual SERP results to database."""
        our_domains = our_domains or []
        competitor_domains = competitor_domains or {}

        for result in snapshot.results:
            is_our_company = result.domain in our_domains
            is_competitor = result.domain in competitor_domains
            competitor_id = competitor_domains.get(result.domain)

            metadata = result.metadata.copy()
            metadata["is_featured"] = result.is_featured
            metadata["is_local"] = result.is_local
            metadata["is_ad"] = result.is_ad

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

            # Generate and store embeddings
            if self.enable_embeddings and result.description:
                try:
                    snippet_embedding = self.embedder.embed_single(result.description)

                    if snippet_embedding:
                        self.qdrant.upsert_serp_snippet(
                            result_id=result_id,
                            query=snapshot.query,
                            url=result.url,
                            title=result.title,
                            snippet=result.description,
                            rank=result.position,
                            vector=snippet_embedding
                        )

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
                        logger.debug(f"Embedded SERP snippet for result {result_id}")
                except Exception as e:
                    logger.error(f"Failed to embed snippet for result {result_id}: {e}")

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
        Scrape SERP for a single query using SeleniumBase UC.

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
            with self.browser_session("google") as driver:
                # Navigate to Google first (to warm up cookies/session)
                driver.get("https://www.google.com/")
                time.sleep(random.uniform(1, 2))

                # Simulate human behavior
                self._simulate_human_behavior(driver, intensity="light")

                # Try to search via input (more human-like)
                search_success = self._perform_search_via_input(driver, query, location)

                if not search_success:
                    # Fallback to direct URL navigation
                    driver.get(url)
                    time.sleep(random.uniform(2, 4))

                # Wait for search results
                wait = WebDriverWait(driver, self.page_timeout)

                try:
                    # Wait for results container
                    wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '#search, #rso'))
                    )
                except Exception:
                    logger.warning("Timeout waiting for search results")

                # Extra wait for JS rendering
                time.sleep(random.uniform(1, 2))

                # Simulate reading behavior
                self._simulate_human_behavior(driver, intensity="normal")

                # Get page source
                html = driver.page_source

                if not html or len(html) < 1000:
                    logger.error(f"Failed to fetch SERP for query: {query}")
                    return None

                # Validate response
                is_valid, reason = self._validate_page_response(driver, url)
                if not is_valid:
                    logger.error(f"SERP validation failed: {reason}")
                    return None

                # Parse the SERP
                snapshot = self.parser.parse(html, query, location)

                if not snapshot.results:
                    logger.warning(f"No results parsed for query: {query}")

                # Save to database if enabled
                if self.engine:
                    with Session(self.engine) as session:
                        query_id = self._get_or_create_query(session, query, location)
                        snapshot_id = self._save_snapshot(
                            session, query_id, snapshot, html
                        )
                        self._save_results(
                            session, snapshot_id, snapshot,
                            our_domains, competitor_domains
                        )
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
            "scraper": "selenium",
        }

        with task_logger.log_task("serp_scraper_selenium", "scraper", {"query_count": len(queries)}) as task:
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
_serp_scraper_selenium_instance = None


def get_serp_scraper_selenium(**kwargs) -> SerpScraperSelenium:
    """Get or create the singleton SerpScraperSelenium instance."""
    global _serp_scraper_selenium_instance

    if _serp_scraper_selenium_instance is None:
        _serp_scraper_selenium_instance = SerpScraperSelenium(**kwargs)

    return _serp_scraper_selenium_instance


def main():
    """Demo/CLI interface for SERP scraper."""
    import argparse

    parser = argparse.ArgumentParser(description="SERP Scraper (SeleniumBase)")
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--location", "-l", help="Location context")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-proxy", action="store_true", help="Disable proxy")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("SERP Scraper Demo Mode (SeleniumBase)")
        logger.info("=" * 60)
        logger.info("")
        logger.info("This scraper uses SeleniumBase Undetected Chrome for better")
        logger.info("anti-detection than the Playwright version.")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python serp_scraper_selenium.py 'pressure washing austin'")
        logger.info("  python serp_scraper_selenium.py 'power washing' --location 'Austin, TX'")
        logger.info("")
        logger.info("=" * 60)
        return

    if not args.query:
        parser.print_help()
        return

    scraper = SerpScraperSelenium(
        headless=args.headless,
        use_proxy=not args.no_proxy,
    )

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

        logger.info("")
        logger.info("Statistics:")
        stats = scraper.get_stats()
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
    else:
        logger.error("Scraping failed")


if __name__ == "__main__":
    main()
