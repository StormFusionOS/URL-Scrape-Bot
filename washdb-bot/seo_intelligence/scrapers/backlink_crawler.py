"""
Backlink Crawler Module (Playwright Version)

Discovers and tracks backlinks pointing to our websites.

Features:
- Check common backlink sources
- Track referring domains
- Calculate domain authority estimates
- Store in backlinks and referring_domains tables
- Enhanced backlink metadata: placement, rel attributes, context

Per SCRAPING_NOTES.md:
- Use YP-style stealth tactics (2-5s delays, human behavior simulation)
- Track anchor text and link context
- Aggregate at domain level for LAS calculation

KNOWN LIMITATIONS:
- Common Crawl CDX API searches for pages ON a domain, not pages LINKING TO
  a domain. The search_common_crawl() method is marked as deprecated and
  documented to return unreliable results for backlink discovery.
- For reliable backlink discovery, consider paid APIs (Ahrefs, Majestic, Moz).

NOTE: The SeleniumBase version (backlink_crawler_selenium.py) is recommended
for production use due to better anti-detection.
"""

import os
import json
import sys
import time
import random
import requests
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from urllib.parse import urlparse, urljoin, quote
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_scraper import BaseScraper
from seo_intelligence.services import get_task_logger
from runner.logging_setup import get_logger

# Import YP stealth features for anti-detection
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scrape_yp.yp_stealth import (
    get_playwright_context_params,
    human_delay,
    get_exponential_backoff_delay,
    get_enhanced_playwright_init_scripts,
    get_human_reading_delay,
    get_scroll_delays,
    SessionBreakManager,
)

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
        Initialize backlink crawler with YP-style stealth features.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool
        """
        super().__init__(
            name="backlink_crawler",
            tier="D",  # Using Tier D (8-15s) but will override with custom YP-style delays
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

        # Session break manager (take breaks after N requests to appear human)
        self.session_manager = SessionBreakManager(
            requests_per_session=50  # Take break after 50 requests
        )
        self.request_count = 0

        logger.info("BacklinkCrawler initialized with YP-style stealth features")

    def _get_stealth_context_options(self) -> dict:
        """
        Override base method to use YP-style randomized context parameters.

        Returns:
            dict: Playwright context options with YP-style stealth features
        """
        # Use YP stealth module for consistent anti-detection across crawlers
        yp_context_params = get_playwright_context_params()

        # Merge with any additional base scraper params
        base_options = super()._get_stealth_context_options()

        # YP params take precedence for key stealth features
        merged_options = {**base_options, **yp_context_params}

        logger.debug(f"Using YP-style context: viewport={merged_options.get('viewport')}, "
                    f"timezone={merged_options.get('timezone_id')}")

        return merged_options

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

    def search_common_crawl(
        self,
        domain: str,
        max_results: int = 100,
        index: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        [DEPRECATED] Search Common Crawl index for pages containing our domain.

        WARNING: This method is fundamentally broken for backlink discovery.
        The CDX API searches for pages ON a domain (domain/*), not pages that
        LINK TO that domain. It returns the target domain's own URLs, not
        inbound links from other sites.

        For reliable backlink discovery, use:
        - search_bing_backlinks() for free discovery (mentions + links)
        - Paid APIs (Ahrefs, Majestic, Moz) for comprehensive backlink data

        This method is kept for backwards compatibility but results should
        not be trusted for backlink analysis.

        Args:
            domain: Domain to find backlinks for (e.g., "example.com")
            max_results: Maximum number of results to return (default 100)
            index: Specific Common Crawl index to use (default: latest)

        Returns:
            List of URLs on the target domain (NOT backlinks!)
        """
        import warnings
        warnings.warn(
            "search_common_crawl() returns pages ON the domain, not pages LINKING TO it. "
            "This method is deprecated for backlink discovery. Use search_bing_backlinks() instead.",
            DeprecationWarning,
            stacklevel=2
        )

        logger.warning(
            f"[DEPRECATED] search_common_crawl() called for {domain}. "
            "This method returns the domain's own URLs, not inbound backlinks."
        )

        # Clean domain
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]

        # Use latest index if not specified
        if not index:
            try:
                # Get list of available indexes
                index_list_url = "https://index.commoncrawl.org/collinfo.json"
                response = requests.get(index_list_url, timeout=10)
                response.raise_for_status()
                indexes = response.json()

                if indexes:
                    # Use the most recent index
                    index = indexes[0]["id"]
                    logger.info(f"Using Common Crawl index: {index}")
                else:
                    logger.error("No Common Crawl indexes available")
                    return []
            except Exception as e:
                logger.error(f"Failed to get Common Crawl index list: {e}")
                return []

        # Search for URLs containing our domain
        # Using the CDX Server API: https://index.commoncrawl.org/CC-MAIN-YYYY-WW/
        base_url = f"https://index.commoncrawl.org/{index}-index"

        # Search for pages that contain our domain in their content
        # This finds pages that link to our domain
        search_url = domain + "/*"

        params = {
            'url': search_url,
            'output': 'json',
            'limit': max_results,
        }

        backlink_sources = []
        seen_domains: Set[str] = set()

        try:
            # Make request with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = requests.get(
                        base_url,
                        params=params,
                        timeout=30,
                    )
                    response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"Common Crawl request failed (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(2 ** attempt)  # Exponential backoff

            # Parse CDXJ results (newline-delimited JSON)
            for line in response.text.strip().split('\n'):
                if not line:
                    continue

                try:
                    record = json.loads(line)

                    # Extract key fields from CDX record
                    url = record.get('url', '')
                    timestamp = record.get('timestamp', '')
                    mime_type = record.get('mime', '')
                    status = record.get('status', '')

                    # Skip non-HTML pages and error responses
                    if status != '200' or not mime_type.startswith('text/html'):
                        continue

                    # Parse URL to get domain
                    parsed = urlparse(url)
                    source_domain = parsed.netloc.lower()
                    if source_domain.startswith('www.'):
                        source_domain = source_domain[4:]

                    # Skip if we've already found this domain
                    if source_domain in seen_domains:
                        continue

                    # Skip if it's the same as our target domain (self-links)
                    if source_domain == domain:
                        continue

                    seen_domains.add(source_domain)

                    # Format timestamp (YYYYMMDDHHMMSS -> ISO format)
                    crawl_date = None
                    if len(timestamp) >= 8:
                        try:
                            from datetime import datetime
                            crawl_date = datetime.strptime(timestamp[:8], '%Y%m%d').isoformat()
                        except:
                            pass

                    backlink_sources.append({
                        'source_url': url,
                        'source_domain': source_domain,
                        'target_domain': domain,
                        'discovered_via': 'common_crawl',
                        'crawl_date': crawl_date,
                        'cc_index': index,
                        'mime_type': mime_type,
                    })

                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse CDX record: {e}")
                    continue

            logger.info(f"Found {len(backlink_sources)} unique backlink sources from Common Crawl")

        except Exception as e:
            logger.error(f"Common Crawl search failed: {e}")

        return backlink_sources

    def search_bing_backlinks(
        self,
        domain: str,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Use Bing's link: operator to find pages linking to our domain.

        Bing allows searching for backlinks using the "link:" operator.
        This method scrapes Bing search results to discover backlinks for free.

        Args:
            domain: Domain to find backlinks for (e.g., "example.com")
            max_results: Maximum number of results to scrape (default 50)

        Returns:
            List of backlink sources found via Bing
        """
        logger.info(f"Searching Bing for backlinks to {domain} (max {max_results} results)")

        # Clean domain
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]

        backlink_sources = []
        seen_domains: Set[str] = set()

        # Use Bing's link: operator
        # Note: Bing deprecated link: in 2017, but linkfromdomain: still works
        query = f"linkfromdomain:{domain}"

        # Alternative: Use site-specific search to find mentions
        # This is more reliable than link: operator
        alternative_query = f'"{domain}"'

        try:
            # We'll use Playwright to scrape Bing search results
            with self.browser_session() as (browser, context, page):
                # Search Bing
                search_url = f"https://www.bing.com/search?q={quote(alternative_query)}"

                logger.info(f"Fetching Bing results from: {search_url}")

                # Apply human delay before search
                human_delay(min_seconds=1.0, max_seconds=3.0, jitter=0.5)

                html = self.fetch_page(
                    url=search_url,
                    page=page,
                    wait_for="domcontentloaded",
                    extra_wait=2.0,
                )

                if not html:
                    logger.warning("Failed to fetch Bing search results")
                    return []

                # Parse search results
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')

                # Bing search results are in <li class="b_algo"> elements
                results = soup.find_all('li', class_='b_algo')

                logger.info(f"Found {len(results)} Bing search results")

                for result in results[:max_results]:
                    try:
                        # Extract link
                        link_elem = result.find('h2')
                        if not link_elem:
                            continue

                        a_tag = link_elem.find('a', href=True)
                        if not a_tag:
                            continue

                        url = a_tag['href']

                        # Parse URL
                        parsed = urlparse(url)
                        source_domain = parsed.netloc.lower()
                        if source_domain.startswith('www.'):
                            source_domain = source_domain[4:]

                        # Skip if same domain
                        if source_domain == domain:
                            continue

                        # Skip if already seen
                        if source_domain in seen_domains:
                            continue

                        seen_domains.add(source_domain)

                        # Extract snippet/context
                        snippet_elem = result.find('p') or result.find('div', class_='b_caption')
                        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                        backlink_sources.append({
                            'source_url': url,
                            'source_domain': source_domain,
                            'target_domain': domain,
                            'discovered_via': 'bing_search',
                            'context': snippet[:200],
                        })

                    except Exception as e:
                        logger.debug(f"Failed to parse Bing result: {e}")
                        continue

                logger.info(f"Found {len(backlink_sources)} unique backlink sources from Bing")

        except Exception as e:
            logger.error(f"Bing search failed: {e}")

        return backlink_sources

    def check_page_for_backlinks(
        self,
        source_url: str,
        target_domains: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Check a single page for backlinks to target domains using YP-style stealth.

        Args:
            source_url: URL to check for backlinks
            target_domains: List of our domains to find links to

        Returns:
            List of found backlinks
        """
        logger.info(f"Checking {source_url} for backlinks to {target_domains}")

        # Check if we need a session break (YP-style human behavior)
        self.request_count += 1
        break_taken = self.session_manager.increment()
        if break_taken:
            logger.info(f"[SESSION BREAK] Break taken after {self.request_count} requests")

        # Apply YP-style human delay BEFORE creating browser (2-5 seconds + jitter)
        human_delay(min_seconds=2.0, max_seconds=5.0, jitter=0.5)

        try:
            with self.browser_session() as (browser, context, page):
                # Add YP-style enhanced anti-detection scripts to the page
                init_scripts = get_enhanced_playwright_init_scripts()
                for script in init_scripts:
                    page.add_init_script(script)

                # Fetch page
                html = self.fetch_page(
                    url=source_url,
                    page=page,
                    wait_for="domcontentloaded",
                    extra_wait=1.0,
                )

                if not html:
                    logger.warning(f"Failed to fetch {source_url}")
                    return []

                # Simulate human behavior: scroll through page (YP-style)
                try:
                    scroll_delays = get_scroll_delays()
                    for i, scroll_delay in enumerate(scroll_delays):
                        # Scroll down in increments (simulate reading)
                        scroll_amount = random.randint(200, 600)
                        page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                        time.sleep(scroll_delay)

                    # Simulate human reading the page (YP-style)
                    content_length = len(html) // 2  # Rough estimate of visible content
                    reading_delay = get_human_reading_delay(min(content_length, 2000))

                    # Take a portion of the reading delay (we already scrolled)
                    remaining_delay = reading_delay * random.uniform(0.3, 0.6)
                    time.sleep(remaining_delay)

                except Exception as e:
                    logger.debug(f"Error during human behavior simulation: {e}")
                    # Continue even if simulation fails

                # Extract backlinks
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
