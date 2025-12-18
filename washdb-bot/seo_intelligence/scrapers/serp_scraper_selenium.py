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
from urllib.parse import quote_plus, urlencode
from dataclasses import dataclass, field

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
    get_qdrant_manager,
    get_google_coordinator,
)
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("serp_scraper_selenium")


@dataclass
class SerpInteractionConfig:
    """
    Configuration for SERP interaction scraping.

    Controls which interactive elements to expand and how much data to capture.
    Higher quality settings capture more data but are slower.
    """
    # PAA (People Also Ask) expansion
    expand_paa: bool = True
    paa_max_clicks: int = 8  # Maximum PAA questions to click
    paa_scroll_for_more: bool = True  # Scroll to load additional PAA items

    # AI Overview / SGE
    expand_ai_overview: bool = True  # Click "Show more" on AI Overview
    capture_ai_citations: bool = True  # Extract citation URLs

    # Local Pack
    expand_local_pack: bool = True
    local_pack_click_each: bool = True  # Click each local result for full details

    # Pagination
    fetch_pages: int = 1  # Number of result pages (1-5)

    # Geo/Locale control
    geo_country: str = "us"  # gl parameter
    geo_language: str = "en"  # hl parameter
    disable_personalization: bool = True  # pws=0

    # Scrolling
    scroll_to_load: bool = True
    scroll_steps: int = 4
    scroll_delay: float = 0.5

    # Wait times
    element_click_delay: float = 0.3
    content_load_wait: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'expand_paa': self.expand_paa,
            'paa_max_clicks': self.paa_max_clicks,
            'paa_scroll_for_more': self.paa_scroll_for_more,
            'expand_ai_overview': self.expand_ai_overview,
            'capture_ai_citations': self.capture_ai_citations,
            'expand_local_pack': self.expand_local_pack,
            'local_pack_click_each': self.local_pack_click_each,
            'fetch_pages': self.fetch_pages,
            'geo_country': self.geo_country,
            'geo_language': self.geo_language,
            'disable_personalization': self.disable_personalization,
            'scroll_to_load': self.scroll_to_load,
            'scroll_steps': self.scroll_steps,
            'scroll_delay': self.scroll_delay,
            'element_click_delay': self.element_click_delay,
            'content_load_wait': self.content_load_wait,
        }


# Pre-configured interaction profiles
DEFAULT_INTERACTION = SerpInteractionConfig()

HIGH_QUALITY_INTERACTION = SerpInteractionConfig(
    expand_paa=True,
    paa_max_clicks=12,
    paa_scroll_for_more=True,
    expand_ai_overview=True,
    capture_ai_citations=True,
    expand_local_pack=True,
    local_pack_click_each=True,
    fetch_pages=3,
    scroll_to_load=True,
    scroll_steps=6,
)

FAST_INTERACTION = SerpInteractionConfig(
    expand_paa=False,
    expand_ai_overview=False,
    expand_local_pack=False,
    fetch_pages=1,
    scroll_to_load=False,
)


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
        page: int = 1,
        interaction_config: Optional[SerpInteractionConfig] = None,
    ) -> str:
        """
        Build Google search URL with geo/locale and pagination support.

        Args:
            query: Search query
            location: Location context (added to query)
            num_results: Results per page
            page: Page number (1-indexed)
            interaction_config: Interaction config with geo/locale settings

        Returns:
            str: Complete Google search URL
        """
        config = interaction_config or DEFAULT_INTERACTION

        full_query = query
        if location:
            full_query = f"{query} {location}"

        # Build URL parameters
        params = {
            'q': full_query,
            'num': num_results,
        }

        # Add pagination (start parameter is 0-indexed)
        if page > 1:
            params['start'] = (page - 1) * num_results

        # Add geo/locale parameters
        if config.geo_country:
            params['gl'] = config.geo_country  # Geolocation country
        if config.geo_language:
            params['hl'] = config.geo_language  # Host language
        if config.disable_personalization:
            params['pws'] = '0'  # Disable personalized web search

        url = f"https://www.google.com/search?{urlencode(params)}"
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

    # ==========================================================================
    # SERP Interaction Methods - Expand PAA, AI Overview, Local Pack
    # ==========================================================================

    def _expand_paa_questions(
        self,
        driver,
        config: SerpInteractionConfig,
    ) -> List[Dict[str, Any]]:
        """
        Click on People Also Ask questions to reveal answers.

        Args:
            driver: Selenium driver
            config: Interaction configuration

        Returns:
            List of expanded PAA data with answers
        """
        expanded_paa = []

        try:
            # Find all PAA question containers
            paa_selectors = [
                "div.related-question-pair",
                "div[jsname='yEVEE']",
                "div.cbphWd",
                "div[data-q]",
            ]

            paa_elements = []
            for selector in paa_selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    paa_elements = elements
                    break

            if not paa_elements:
                logger.debug("No PAA elements found")
                return expanded_paa

            clicks_made = 0
            for paa_elem in paa_elements:
                if clicks_made >= config.paa_max_clicks:
                    break

                try:
                    # Check if already expanded
                    aria_expanded = paa_elem.get_attribute("aria-expanded")
                    if aria_expanded == "true":
                        continue

                    # Find the clickable element (question button)
                    clickable = None
                    try:
                        clickable = paa_elem.find_element(
                            By.CSS_SELECTOR, "div[role='button'], span[jsname]"
                        )
                    except Exception:
                        clickable = paa_elem  # Try clicking the container

                    if clickable:
                        # Scroll element into view
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});",
                            clickable
                        )
                        time.sleep(config.element_click_delay)

                        # Click to expand
                        self._human_click(driver, clickable)
                        clicks_made += 1

                        # Wait for content to load
                        time.sleep(config.content_load_wait)

                        # Extract the expanded content
                        try:
                            question_text = paa_elem.get_attribute("data-q")
                            if not question_text:
                                q_elem = paa_elem.find_element(
                                    By.CSS_SELECTOR, "div[role='button'], span"
                                )
                                question_text = q_elem.text if q_elem else ""

                            # Find answer content
                            answer_text = ""
                            source_url = ""
                            source_domain = ""

                            answer_selectors = [
                                "div.hgKElc",
                                "div.kno-rdesc",
                                "span.hgKElc",
                            ]
                            for a_sel in answer_selectors:
                                try:
                                    answer_elem = paa_elem.find_element(By.CSS_SELECTOR, a_sel)
                                    if answer_elem:
                                        answer_text = answer_elem.text
                                        break
                                except Exception:
                                    continue

                            # Find source link
                            try:
                                source_link = paa_elem.find_element(By.CSS_SELECTOR, "a[href]")
                                if source_link:
                                    source_url = source_link.get_attribute("href") or ""
                                    from urllib.parse import urlparse
                                    source_domain = urlparse(source_url).netloc
                            except Exception:
                                pass

                            if question_text:
                                expanded_paa.append({
                                    'question': question_text,
                                    'answer': answer_text,
                                    'source_url': source_url,
                                    'source_domain': source_domain,
                                    'position': clicks_made,
                                    'expanded': True,
                                })

                        except Exception as e:
                            logger.debug(f"Error extracting PAA content: {e}")

                except Exception as e:
                    logger.debug(f"Error clicking PAA element: {e}")
                    continue

            # Scroll to load more PAA if enabled
            if config.paa_scroll_for_more and clicks_made > 0:
                try:
                    # Scroll down to trigger more PAA loading
                    driver.execute_script("window.scrollBy(0, 300);")
                    time.sleep(config.content_load_wait)
                except Exception:
                    pass

            logger.info(f"Expanded {len(expanded_paa)} PAA questions")

        except Exception as e:
            logger.warning(f"Error in PAA expansion: {e}")

        return expanded_paa

    def _extract_ai_overview(
        self,
        driver,
        config: SerpInteractionConfig,
    ) -> Optional[Dict[str, Any]]:
        """
        Extract AI Overview / SGE content from SERP.

        Clicks "Show more" if available and captures citations.

        Args:
            driver: Selenium driver
            config: Interaction configuration

        Returns:
            Dict with AI overview content and citations, or None
        """
        ai_overview = None

        try:
            # Multiple selectors for AI Overview container
            ai_selectors = [
                "div[data-attrid='SGEResults']",
                "div.c3AuYc",  # AI Overview container
                "div[jsname='ub57id']",
                "div.wDYxhc.NFQFxe",  # Large expandable
                "div[data-sgrd]",  # SGE results data
            ]

            ai_container = None
            for selector in ai_selectors:
                try:
                    ai_container = driver.find_element(By.CSS_SELECTOR, selector)
                    if ai_container:
                        break
                except Exception:
                    continue

            if not ai_container:
                return None

            ai_overview = {
                'content': '',
                'citations': [],
                'expanded': False,
            }

            # Try to click "Show more" if enabled
            if config.expand_ai_overview:
                try:
                    show_more_selectors = [
                        "div[role='button'][aria-label*='Show more']",
                        "span.BNlZbe",  # Show more text
                        "div.XLEeCf",  # Expandable button
                    ]
                    for sm_sel in show_more_selectors:
                        try:
                            show_more = ai_container.find_element(By.CSS_SELECTOR, sm_sel)
                            if show_more and show_more.is_displayed():
                                self._human_click(driver, show_more)
                                time.sleep(config.content_load_wait)
                                ai_overview['expanded'] = True
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            # Extract main content
            try:
                content_text = ai_container.text
                ai_overview['content'] = content_text[:5000]  # Limit size
            except Exception:
                pass

            # Extract citations if enabled
            if config.capture_ai_citations:
                try:
                    citation_links = ai_container.find_elements(
                        By.CSS_SELECTOR, "a[href]:not([href^='#'])"
                    )
                    for link in citation_links[:20]:  # Limit to 20 citations
                        try:
                            href = link.get_attribute("href")
                            title = link.text or link.get_attribute("aria-label") or ""
                            if href and "google.com" not in href:
                                from urllib.parse import urlparse
                                ai_overview['citations'].append({
                                    'url': href,
                                    'title': title[:200],
                                    'domain': urlparse(href).netloc,
                                })
                        except Exception:
                            continue
                except Exception:
                    pass

            logger.info(f"Extracted AI Overview with {len(ai_overview['citations'])} citations")

        except Exception as e:
            logger.debug(f"No AI Overview found or error: {e}")

        return ai_overview

    def _expand_local_pack(
        self,
        driver,
        config: SerpInteractionConfig,
    ) -> List[Dict[str, Any]]:
        """
        Click on local pack listings to extract detailed information.

        Args:
            driver: Selenium driver
            config: Interaction configuration

        Returns:
            List of expanded local business details
        """
        local_results = []

        try:
            # Find local pack container
            local_selectors = [
                "div.VkpGBb",
                "div[data-attrid='kc:/local:']",
                "div.rlfl__tls",
            ]

            local_container = None
            for selector in local_selectors:
                try:
                    local_container = driver.find_element(By.CSS_SELECTOR, selector)
                    if local_container:
                        break
                except Exception:
                    continue

            if not local_container:
                return local_results

            # Find individual listings
            listing_selectors = [
                "div.VkpGBb",
                "div.rllt__link",
                "a.rllt__link",
            ]

            listings = []
            for selector in listing_selectors:
                try:
                    listings = local_container.find_elements(By.CSS_SELECTOR, selector)
                    if listings:
                        break
                except Exception:
                    continue

            for i, listing in enumerate(listings[:5], 1):  # Limit to top 5
                try:
                    local_data = {"position": i}

                    # Extract basic info before clicking
                    try:
                        name_elem = listing.find_element(
                            By.CSS_SELECTOR, "div.dbg0pd, span.OSrXXb, div.qBF1Pd"
                        )
                        local_data['name'] = name_elem.text if name_elem else ""
                    except Exception:
                        local_data['name'] = ""

                    # Click to expand if configured
                    if config.local_pack_click_each:
                        try:
                            driver.execute_script(
                                "arguments[0].scrollIntoView({block: 'center'});",
                                listing
                            )
                            time.sleep(config.element_click_delay)
                            self._human_click(driver, listing)
                            time.sleep(config.content_load_wait * 1.5)  # Longer wait for panel

                            # Extract expanded details from side panel
                            try:
                                # Rating
                                rating_elem = driver.find_element(
                                    By.CSS_SELECTOR, "span.Aq14fc, span.yi40Hd"
                                )
                                local_data['rating'] = rating_elem.text if rating_elem else ""
                            except Exception:
                                pass

                            try:
                                # Review count
                                reviews = driver.find_element(
                                    By.CSS_SELECTOR, "span.RDApEe, span.z5jxId"
                                )
                                local_data['review_count'] = reviews.text if reviews else ""
                            except Exception:
                                pass

                            try:
                                # Phone
                                phone = driver.find_element(
                                    By.CSS_SELECTOR, "span.LrzXr, a[href^='tel:']"
                                )
                                if phone:
                                    local_data['phone'] = phone.text or phone.get_attribute("href")
                            except Exception:
                                pass

                            try:
                                # Address
                                addr = driver.find_element(
                                    By.CSS_SELECTOR, "span.LrzXr[data-dtype='d3adr']"
                                )
                                local_data['address'] = addr.text if addr else ""
                            except Exception:
                                pass

                            try:
                                # Website
                                website = driver.find_element(
                                    By.CSS_SELECTOR, "a[data-rc='website'], a.lcr4fd"
                                )
                                if website:
                                    local_data['website'] = website.get_attribute("href") or ""
                            except Exception:
                                pass

                            try:
                                # Hours
                                hours = driver.find_element(By.CSS_SELECTOR, "span.zhFJpc")
                                local_data['hours'] = hours.text if hours else ""
                            except Exception:
                                pass

                            # Close the panel by clicking elsewhere
                            try:
                                driver.execute_script("document.body.click();")
                            except Exception:
                                pass

                        except Exception as e:
                            logger.debug(f"Error expanding local listing {i}: {e}")

                    if local_data.get('name'):
                        local_results.append(local_data)

                except Exception as e:
                    logger.debug(f"Error processing local listing {i}: {e}")
                    continue

            logger.info(f"Extracted {len(local_results)} local pack results")

        except Exception as e:
            logger.debug(f"Error in local pack expansion: {e}")

        return local_results

    def _scroll_and_load_serp(
        self,
        driver,
        config: SerpInteractionConfig,
    ):
        """
        Scroll through SERP to load lazy content.

        Args:
            driver: Selenium driver
            config: Interaction configuration
        """
        if not config.scroll_to_load:
            return

        try:
            for i in range(config.scroll_steps):
                driver.execute_script(
                    f"window.scrollTo(0, document.body.scrollHeight * {(i+1) / config.scroll_steps});"
                )
                time.sleep(config.scroll_delay)

            # Scroll back to top
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)

        except Exception as e:
            logger.debug(f"Error during SERP scroll: {e}")

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

    def scrape_serp(
        self,
        keyword: str,
        country: str = "us",
        language: str = "en",
        num_results: int = 100,
        use_coordinator: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Backwards-compatible method that returns a dict instead of SerpSnapshot.

        This method exists for compatibility with keyword_intelligence and
        competitive_analysis orchestrators that expect a dict return type.

        Args:
            keyword: Search query
            country: Country code (gl parameter)
            language: Language code (hl parameter)
            num_results: Number of results to request
            use_coordinator: If True, use GoogleCoordinator for rate limiting
                            and browser session sharing (recommended).
                            If False, use direct scraping (standalone mode).

        Returns:
            Dict with organic_results, people_also_ask, local_pack, etc.
            or None on failure
        """
        # If using coordinator, route through it with SHARED browser
        if use_coordinator:
            try:
                coordinator = get_google_coordinator()
                # Use execute() which provides the shared browser
                return coordinator.execute(
                    "serp",
                    lambda driver: self._scrape_serp_with_driver(driver, keyword, country, language, num_results),
                    priority=5
                )
            except Exception as e:
                logger.warning(f"Coordinator failed, falling back to direct: {e}")
                # Fall through to direct scraping

        return self._scrape_serp_direct(keyword, country, language, num_results)

    def _scrape_serp_with_driver(
        self,
        driver,
        keyword: str,
        country: str = "us",
        language: str = "en",
        num_results: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Scrape SERP using a provided driver (from GoogleCoordinator's shared browser).

        Args:
            driver: Selenium WebDriver instance
            keyword: Search query
            country: Country code
            language: Language code
            num_results: Number of results

        Returns:
            Dict with SERP data or None
        """
        import random
        import time
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.wait import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        config = SerpInteractionConfig(
            geo_country=country,
            geo_language=language,
        )

        try:
            # Navigate to Google homepage
            driver.get("https://www.google.com/")
            time.sleep(random.uniform(1, 2))

            # Simulate human behavior
            self._simulate_human_behavior(driver, intensity="light")

            # Try to search via input
            search_success = self._perform_search_via_input(driver, keyword, None)

            if not search_success:
                # Fallback to direct URL
                url = self._build_search_url(keyword, None, num_results, interaction_config=config)
                driver.get(url)
                time.sleep(random.uniform(2, 4))

            # Wait for results
            wait = WebDriverWait(driver, self.page_timeout)
            try:
                wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#search, #rso'))
                )
            except Exception:
                logger.warning("Timeout waiting for search results")

            time.sleep(random.uniform(1, 2))

            # Simulate reading
            self._simulate_human_behavior(driver, intensity="normal")

            # Get page source
            html = driver.page_source

            if not html or len(html) < 1000:
                logger.error(f"Failed to fetch SERP for: {keyword}")
                return None

            # Validate response
            is_valid, reason = self._validate_page_response(driver, driver.current_url)
            if not is_valid:
                logger.error(f"SERP validation failed: {reason}")
                return None

            # Parse the SERP
            snapshot = self.parser.parse(html, keyword, None)

            if not snapshot:
                return None

            return self._snapshot_to_dict(snapshot)

        except Exception as e:
            logger.error(f"Error in _scrape_serp_with_driver: {e}")
            return None

    def _scrape_serp_direct(
        self,
        keyword: str,
        country: str = "us",
        language: str = "en",
        num_results: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Direct SERP scraping without coordinator (internal method).

        Called by scrape_serp when use_coordinator=False or as fallback.
        """
        # Create interaction config with country/language
        config = SerpInteractionConfig(
            geo_country=country,
            geo_language=language,
        )

        # Use scrape_query_interactive for richer data, fall back to scrape_query
        snapshot = self.scrape_query_interactive(
            query=keyword,
            location=None,
            num_results=num_results,
            interaction_config=config,
        )

        if not snapshot:
            # Fallback to basic scrape_query
            snapshot = self.scrape_query(
                query=keyword,
                num_results=num_results,
            )

        if not snapshot:
            return None

        # Convert SerpSnapshot to legacy dict format expected by orchestrators
        return self._snapshot_to_dict(snapshot)

    def _snapshot_to_dict(self, snapshot: SerpSnapshot) -> Dict[str, Any]:
        """
        Convert SerpSnapshot to legacy dict format for orchestrator compatibility.

        Args:
            snapshot: SerpSnapshot object

        Returns:
            Dict in legacy format with organic_results, people_also_ask, etc.
        """
        organic_results = []
        for result in snapshot.results:
            organic_results.append({
                'position': result.position,
                'title': result.title,
                'url': result.url,
                'domain': result.domain,
                'snippet': result.description,  # SerpResult uses 'description' not 'snippet'
                'is_featured_snippet': result.is_featured,  # SerpResult uses 'is_featured' not 'is_featured_snippet'
                'sitelinks': [sl.to_dict() if hasattr(sl, 'to_dict') else sl for sl in (getattr(result, 'sitelinks', None) or [])],
                'metadata': result.metadata or {},
            })

        paa_questions = []
        for paa in (snapshot.people_also_ask or []):
            if hasattr(paa, 'question'):
                paa_questions.append({
                    'question': paa.question,
                    'answer': getattr(paa, 'answer', ''),
                    'source_url': getattr(paa, 'source_url', ''),
                    'source_domain': getattr(paa, 'source_domain', ''),
                })
            elif isinstance(paa, dict):
                paa_questions.append(paa)

        local_pack = []
        for local in (snapshot.local_pack or []):
            if isinstance(local, dict):
                local_pack.append(local)
            elif hasattr(local, 'to_dict'):
                local_pack.append(local.to_dict())

        return {
            'query': snapshot.query,
            'location': snapshot.location,
            'organic_results': organic_results,
            'total_results': snapshot.total_results,
            'people_also_ask': paa_questions,
            'local_pack': local_pack,
            'ai_overview': snapshot.ai_overview,
            'featured_snippet': {
                'title': organic_results[0]['title'] if organic_results and organic_results[0].get('is_featured_snippet') else None,
                'url': organic_results[0]['url'] if organic_results and organic_results[0].get('is_featured_snippet') else None,
                'snippet': organic_results[0]['snippet'] if organic_results and organic_results[0].get('is_featured_snippet') else None,
            } if organic_results and any(r.get('is_featured_snippet') for r in organic_results) else None,
            'has_knowledge_panel': bool(snapshot.knowledge_panel),
            'has_local_pack': len(local_pack) > 0,
            'has_people_also_ask': len(paa_questions) > 0,
            'has_featured_snippet': any(r.get('is_featured_snippet') for r in organic_results),
            'has_ai_overview': bool(snapshot.ai_overview),
            'metadata': snapshot.metadata or {},
        }

    def scrape_query_interactive(
        self,
        query: str,
        location: Optional[str] = None,
        our_domains: Optional[List[str]] = None,
        competitor_domains: Optional[Dict[str, int]] = None,
        num_results: int = 100,
        interaction_config: Optional[SerpInteractionConfig] = None,
    ) -> Optional[SerpSnapshot]:
        """
        Scrape SERP with full interactions - PAA expansion, AI Overview, local pack, pagination.

        This is an enhanced version of scrape_query that:
        - Expands People Also Ask questions to get answers
        - Extracts AI Overview/SGE content with citations
        - Clicks local pack results for detailed info
        - Supports multi-page scraping
        - Uses geo/locale parameters for consistent results

        Args:
            query: Search query
            location: Location context (e.g., "Austin, TX")
            our_domains: List of our company's domains
            competitor_domains: Dict of competitor domain -> competitor_id
            num_results: Number of results per page
            interaction_config: Configuration for interaction behavior

        Returns:
            SerpSnapshot with enriched data if successful, None otherwise
        """
        config = interaction_config or DEFAULT_INTERACTION
        all_results = []
        all_paa = []
        ai_overview_data = None
        local_pack_data = []

        logger.info(
            f"Scraping SERP (interactive) for: '{query}' "
            f"({location or 'no location'}) - {config.fetch_pages} page(s)"
        )

        try:
            with self.browser_session("google") as driver:
                # Navigate to Google first
                driver.get("https://www.google.com/")
                time.sleep(random.uniform(1, 2))
                self._simulate_human_behavior(driver, intensity="light")

                # Process each page
                for page_num in range(1, config.fetch_pages + 1):
                    url = self._build_search_url(
                        query, location, num_results,
                        page=page_num, interaction_config=config
                    )

                    if page_num == 1:
                        # First page: try human-like search
                        search_success = self._perform_search_via_input(driver, query, location)
                        if not search_success:
                            driver.get(url)
                    else:
                        # Subsequent pages: navigate directly
                        driver.get(url)

                    time.sleep(random.uniform(2, 4))

                    # Wait for results
                    wait = WebDriverWait(driver, self.page_timeout)
                    try:
                        wait.until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, '#search, #rso'))
                        )
                    except Exception:
                        logger.warning(f"Timeout waiting for results on page {page_num}")
                        if page_num == 1:
                            return None
                        break

                    # Extra wait for JS
                    time.sleep(random.uniform(1, 2))

                    # Scroll to load lazy content
                    self._scroll_and_load_serp(driver, config)

                    # Page 1: Do all the interactions
                    if page_num == 1:
                        # Extract AI Overview (only on page 1)
                        if config.expand_ai_overview:
                            ai_overview_data = self._extract_ai_overview(driver, config)

                        # Expand PAA questions
                        if config.expand_paa:
                            paa_data = self._expand_paa_questions(driver, config)
                            all_paa.extend(paa_data)

                        # Expand local pack
                        if config.expand_local_pack:
                            local_pack_data = self._expand_local_pack(driver, config)

                    # Validate response
                    is_valid, reason = self._validate_page_response(driver, url)
                    if not is_valid:
                        logger.error(f"SERP validation failed on page {page_num}: {reason}")
                        if page_num == 1:
                            return None
                        break

                    # Get final HTML after interactions
                    html = driver.page_source

                    if not html or len(html) < 1000:
                        logger.error(f"Failed to fetch SERP page {page_num}")
                        if page_num == 1:
                            return None
                        break

                    # Parse the page
                    page_snapshot = self.parser.parse(html, query, location)

                    # Adjust positions for pagination
                    position_offset = (page_num - 1) * num_results
                    for result in page_snapshot.results:
                        result.position += position_offset
                        result.metadata['page'] = page_num

                    all_results.extend(page_snapshot.results)

                    # Only get PAA/local pack from parser on page 1 if not expanded
                    if page_num == 1:
                        if not all_paa and page_snapshot.people_also_ask:
                            all_paa = page_snapshot.people_also_ask
                        if not local_pack_data and page_snapshot.local_pack:
                            local_pack_data = page_snapshot.local_pack

                    logger.info(f"Page {page_num}: {len(page_snapshot.results)} results")

                    # Rate limit between pages
                    if page_num < config.fetch_pages:
                        time.sleep(random.uniform(2, 4))

                # Build final snapshot
                final_snapshot = SerpSnapshot(
                    query=query,
                    location=location,
                    results=all_results,
                    total_results=len(all_results),
                    people_also_ask=all_paa if isinstance(all_paa, list) and all_paa and hasattr(all_paa[0], 'question') else [],
                    local_pack=local_pack_data,
                    ai_overview=ai_overview_data,
                    metadata={
                        'interaction_config': config.to_dict(),
                        'pages_fetched': min(page_num, config.fetch_pages),
                        'scraper': 'selenium_interactive',
                    }
                )

                # Convert expanded PAA dicts to PAAQuestion objects if needed
                if all_paa and isinstance(all_paa[0], dict):
                    from seo_intelligence.scrapers.serp_parser import PAAQuestion
                    final_snapshot.people_also_ask = [
                        PAAQuestion(
                            question=p.get('question', ''),
                            answer=p.get('answer', ''),
                            source_url=p.get('source_url', ''),
                            source_domain=p.get('source_domain', ''),
                            position=p.get('position', 0),
                            metadata={'expanded': p.get('expanded', False)}
                        )
                        for p in all_paa
                    ]

                # Save to database if enabled
                if self.engine:
                    with Session(self.engine) as session:
                        query_id = self._get_or_create_query(session, query, location)
                        snapshot_id = self._save_snapshot(
                            session, query_id, final_snapshot, html
                        )
                        self._save_results(
                            session, snapshot_id, final_snapshot,
                            our_domains, competitor_domains
                        )
                        self._save_paa_questions(
                            session, snapshot_id, query_id, final_snapshot
                        )

                        logger.info(
                            f"Saved interactive SERP snapshot {snapshot_id} with "
                            f"{len(final_snapshot.results)} results, "
                            f"{len(final_snapshot.people_also_ask)} PAA questions"
                        )

                return final_snapshot

        except Exception as e:
            logger.error(f"Error in interactive SERP scrape for '{query}': {e}", exc_info=True)
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
