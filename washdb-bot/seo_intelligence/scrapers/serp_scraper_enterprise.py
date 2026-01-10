"""
Enterprise SERP Scraper

Drop-in replacement for SerpScraperSelenium that uses the enterprise SERP system.
This provides reliable SERP data through persistent, warm browser sessions.

Usage:
    from seo_intelligence.scrapers.serp_scraper_enterprise import EnterpriseSerpScraper

    scraper = EnterpriseSerpScraper()
    result = scraper.scrape_serp("pressure washing near me")
"""

import os
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger
from seo_intelligence.services.enterprise_serp import (
    EnterpriseSERP,
    get_enterprise_serp,
    start_enterprise_serp,
)

load_dotenv()

logger = get_logger("serp_scraper_enterprise")


class EnterpriseSerpScraper:
    """
    Enterprise SERP scraper with the same interface as SerpScraperSelenium.

    This is a drop-in replacement that uses the enterprise session pool
    for reliable SERP data collection.
    """

    def __init__(
        self,
        headless: bool = False,  # Ignored - enterprise always runs headed
        use_proxy: bool = True,
        tier: str = "A",
    ):
        """
        Initialize enterprise SERP scraper.

        Args:
            headless: Ignored (enterprise always runs headed for better evasion)
            use_proxy: Whether to use residential proxies
            tier: Ignored (enterprise manages its own rate limiting)
        """
        self.use_proxy = use_proxy
        self._serp: Optional[EnterpriseSERP] = None
        self._ensure_started()

    def _ensure_started(self):
        """Ensure the enterprise SERP system is running."""
        if self._serp is None:
            self._serp = get_enterprise_serp()

            if not self._serp._started:
                logger.info("Starting enterprise SERP system...")
                proxy_list = None
                if self.use_proxy:
                    proxy_list = self._get_proxy_list()
                self._serp.start(proxy_list)

    def _get_proxy_list(self) -> List[str]:
        """Get residential proxy list from Webshare."""
        try:
            from seo_intelligence.services.residential_proxy_manager import (
                get_residential_proxy_manager
            )
            manager = get_residential_proxy_manager()
            proxies = []

            for _ in range(5):  # Get 5 proxies
                proxy_info = manager.get_proxy()
                if proxy_info:
                    url = proxy_info.get("url")
                    if not url:
                        ip = proxy_info.get("ip", proxy_info.get("proxy_address"))
                        port = proxy_info.get("port")
                        if ip and port:
                            url = f"http://{ip}:{port}"
                    if url:
                        proxies.append(url)

            logger.info(f"Got {len(proxies)} residential proxies")
            return proxies

        except Exception as e:
            logger.warning(f"Could not get residential proxies: {e}")
            return []

    def scrape_serp(
        self,
        keyword: str,
        location: str = None,
        use_coordinator: bool = True,  # Ignored - enterprise has its own coordinator
        company_id: int = None,
        timeout: int = 1800,
    ) -> Optional[Dict[str, Any]]:
        """
        Scrape SERP for a keyword.

        This method blocks until results are available or timeout is reached.
        The enterprise system handles all the complexity of rate limiting,
        session management, and human-like behavior.

        Args:
            keyword: Search keyword
            location: Geographic location for local results
            use_coordinator: Ignored (enterprise manages its own sessions)
            company_id: Company ID for tracking
            timeout: Maximum seconds to wait for result

        Returns:
            SERP results dict or None if failed
        """
        self._ensure_started()

        logger.info(f"Enterprise SERP scraping: '{keyword[:50]}...'")

        try:
            result = self._serp.search(
                query=keyword,
                location=location,
                timeout=timeout,
                use_cache=True,
            )

            if result:
                # Store result in database
                self._store_result(keyword, result, company_id)

                organic_count = len(result.get("organic_results", []))
                local_count = len(result.get("local_pack", []))
                logger.info(f"Enterprise SERP success: {organic_count} organic, {local_count} local")

                return result
            else:
                logger.warning(f"Enterprise SERP returned no results for '{keyword[:30]}...'")
                return None

        except Exception as e:
            logger.error(f"Enterprise SERP error for '{keyword[:30]}...': {e}")
            return None

    def scrape_serp_async(
        self,
        keyword: str,
        location: str = None,
        priority: str = "normal",
        callback: callable = None,
        company_id: int = None,
    ) -> str:
        """
        Queue a SERP scrape for async processing.

        Args:
            keyword: Search keyword
            location: Geographic location
            priority: Priority level (urgent, high, normal, low, background)
            callback: Function to call when result is ready
            company_id: Company ID for tracking

        Returns:
            Job ID for tracking
        """
        self._ensure_started()

        return self._serp.search_async(
            query=keyword,
            location=location,
            priority=priority,
            callback=callback,
            company_id=company_id,
        )

    def get_async_result(self, job_id: str, wait: bool = False, timeout: int = 60) -> Optional[dict]:
        """Get result of an async scrape."""
        self._ensure_started()
        return self._serp.get_result(job_id, wait=wait, timeout=timeout)

    def _store_result(self, keyword: str, result: dict, company_id: int = None):
        """Store SERP result in database using proper schema.

        Saves to:
        - search_queries: query text and location
        - serp_snapshots: snapshot with result count and metadata
        - serp_results: individual organic results
        - serp_paa: People Also Ask questions
        - serp_local_pack: local pack results
        """
        import json
        import hashlib
        from urllib.parse import urlparse

        try:
            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                logger.warning("DATABASE_URL not set, cannot store SERP result")
                return

            engine = create_engine(db_url)
            with Session(engine) as session:
                # 1. Get or create search query
                location = result.get("location", "United States")
                query_result = session.execute(
                    text("""
                        INSERT INTO search_queries (query_text, location, search_engine)
                        VALUES (:query, :location, 'google')
                        ON CONFLICT (query_text, location, search_engine)
                        DO UPDATE SET updated_at = NOW()
                        RETURNING query_id
                    """),
                    {"query": keyword, "location": location}
                )
                query_id = query_result.fetchone()[0]

                # 2. Create snapshot
                organic_results = result.get("organic_results", [])
                local_pack = result.get("local_pack", [])
                paa_questions = result.get("people_also_ask", [])

                # Create metadata with all SERP features
                metadata = {
                    "company_id": company_id,
                    "local_pack_count": len(local_pack),
                    "paa_count": len(paa_questions),
                    "featured_snippet": result.get("featured_snippet"),
                    "related_searches": result.get("related_searches", []),
                    "ai_overview": result.get("ai_overview"),
                    "knowledge_panel": result.get("knowledge_panel"),
                    "ads_count": len(result.get("ads", [])),
                    "intent": result.get("intent"),
                    "complexity": result.get("complexity"),
                    "source": "enterprise_serp",
                }

                # Create hash of results for deduplication
                hash_content = json.dumps(organic_results, sort_keys=True)
                snapshot_hash = hashlib.sha256(hash_content.encode()).hexdigest()[:64]

                snapshot_result = session.execute(
                    text("""
                        INSERT INTO serp_snapshots (
                            query_id, result_count, snapshot_hash, metadata
                        ) VALUES (
                            :query_id, :result_count, :snapshot_hash, :metadata
                        )
                        RETURNING snapshot_id
                    """),
                    {
                        "query_id": query_id,
                        "result_count": len(organic_results),
                        "snapshot_hash": snapshot_hash,
                        "metadata": json.dumps(metadata),
                    }
                )
                snapshot_id = snapshot_result.fetchone()[0]

                # 3. Save organic results
                for i, item in enumerate(organic_results):
                    url = item.get("url", item.get("link", ""))
                    if not url:
                        continue

                    try:
                        domain = urlparse(url).netloc.replace("www.", "")
                    except Exception:
                        domain = ""

                    session.execute(
                        text("""
                            INSERT INTO serp_results (
                                snapshot_id, position, url, title, description, domain, metadata
                            ) VALUES (
                                :snapshot_id, :position, :url, :title, :description, :domain, :metadata
                            )
                        """),
                        {
                            "snapshot_id": snapshot_id,
                            "position": i + 1,
                            "url": url[:2000],  # Truncate if too long
                            "title": (item.get("title", "") or "")[:500],
                            "description": (item.get("snippet", item.get("description", "")) or "")[:2000],
                            "domain": domain[:500],
                            "metadata": json.dumps({
                                "displayed_url": item.get("displayed_url"),
                                "sitelinks": item.get("sitelinks", []),
                            }),
                        }
                    )

                # 4. Save People Also Ask questions
                for i, paa in enumerate(paa_questions):
                    question = paa if isinstance(paa, str) else paa.get("question", "")
                    answer = "" if isinstance(paa, str) else paa.get("answer", "")

                    if question:
                        session.execute(
                            text("""
                                INSERT INTO serp_paa (
                                    snapshot_id, query_id, question, answer_snippet, position
                                ) VALUES (
                                    :snapshot_id, :query_id, :question, :answer_snippet, :position
                                )
                            """),
                            {
                                "snapshot_id": snapshot_id,
                                "query_id": query_id,
                                "question": question[:500],
                                "answer_snippet": (answer or "")[:2000],
                                "position": i + 1,
                            }
                        )

                # 5. Save local pack results
                for i, local in enumerate(local_pack):
                    session.execute(
                        text("""
                            INSERT INTO serp_local_pack (
                                snapshot_id, query_id, business_name, position,
                                phone, website, rating, review_count, category, metadata
                            ) VALUES (
                                :snapshot_id, :query_id, :name, :position,
                                :phone, :website, :rating, :reviews, :category, :metadata
                            )
                        """),
                        {
                            "snapshot_id": snapshot_id,
                            "query_id": query_id,
                            "name": (local.get("name", local.get("title", "")) or "")[:500],
                            "position": i + 1,
                            "phone": (local.get("phone", "") or "")[:30],
                            "website": (local.get("website", local.get("link", "")) or "")[:500],
                            "rating": local.get("rating"),
                            "reviews": local.get("reviews", local.get("review_count")),
                            "category": (local.get("category", local.get("type", "")) or "")[:200],
                            "metadata": json.dumps({
                                "address": local.get("address"),
                                "hours": local.get("hours"),
                            }),
                        }
                    )

                session.commit()
                logger.info(f"Stored SERP snapshot {snapshot_id}: {len(organic_results)} organic, {len(local_pack)} local, {len(paa_questions)} PAA")

        except Exception as e:
            logger.error(f"Failed to store SERP result: {e}")

    def get_stats(self) -> dict:
        """Get enterprise SERP system statistics."""
        self._ensure_started()
        return self._serp.get_stats()

    def close(self):
        """Close the scraper (no-op for enterprise - pool is shared)."""
        # Don't actually close the enterprise system since it's shared
        pass


# Convenience function
def get_enterprise_scraper(**kwargs) -> EnterpriseSerpScraper:
    """Get an enterprise SERP scraper instance."""
    return EnterpriseSerpScraper(**kwargs)
