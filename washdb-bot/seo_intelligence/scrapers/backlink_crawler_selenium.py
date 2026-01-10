"""
Backlink Crawler Module (SeleniumBase Version)

Discovers and tracks backlinks pointing to our websites.
Uses SeleniumBase with undetected Chrome for anti-detection.

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
"""

import os
import json
import sys
import time
import random
import requests
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
from urllib.parse import urlparse, urljoin, quote
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper
from seo_intelligence.services import get_task_logger
from runner.logging_setup import get_logger

# Import YP stealth features for timing delays
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scrape_yp.yp_stealth import (
    human_delay,
    get_human_reading_delay,
    get_scroll_delays,
    SessionBreakManager,
)

# Load environment
load_dotenv()

logger = get_logger("backlink_crawler_selenium")


class BacklinkCrawlerSelenium(BaseSeleniumScraper):
    """
    Crawler for discovering backlinks to our websites using SeleniumBase.

    Uses SeleniumBase UC mode for undetected Chrome browsing.
    Checks known backlink sources and tracks referring domains
    for Local Authority Score calculation.
    """

    def __init__(
        self,
        headless: bool = False,  # Non-headless by default for max stealth
        use_proxy: bool = True,  # Enable proxy for better anti-detection
        mobile_mode: bool = False,
    ):
        """
        Initialize backlink crawler with SeleniumBase UC drivers.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool
            mobile_mode: Use mobile viewport and user agent
        """
        super().__init__(
            name="backlink_crawler_selenium",
            tier="D",  # Using Tier D (8-15s) but will override with custom YP-style delays
            headless=headless,
            use_proxy=use_proxy,
            max_retries=3,
            page_timeout=30000,
            mobile_mode=mobile_mode,
        )
        self._mobile_mode = mobile_mode

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

        logger.info("BacklinkCrawlerSelenium initialized with SeleniumBase UC drivers")

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
            Dict with placement info
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

        Note:
            Internal links (where source_domain == target_domain) are filtered out.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        backlinks = []

        # Get source domain for internal link filtering
        source_parsed = urlparse(source_url)
        source_domain = source_parsed.netloc.lower()
        if source_domain.startswith('www.'):
            source_domain = source_domain[4:]

        # Check if source page is on a target domain (internal link scenario)
        source_is_target = False
        for target in target_domains:
            target_clean = target.lower().replace('www.', '')
            if source_domain == target_clean or source_domain.endswith('.' + target_clean):
                source_is_target = True
                logger.debug(f"Source {source_url} is on target domain {target} - will skip internal links")
                break

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
                    # Skip internal links (source page is on the same domain as target)
                    if source_is_target and (source_domain == link_domain or source_domain.endswith('.' + link_domain)):
                        logger.debug(f"Skipping internal link: {source_url} -> {full_url}")
                        continue
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

                    # Detect link placement
                    placement_info = self._detect_link_placement(link, soup)

                    backlinks.append({
                        "target_url": full_url,
                        "source_url": source_url,
                        "anchor_text": anchor_text,
                        "link_type": link_type,
                        "context": context,
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
        - search_duckduckgo_backlinks() for free discovery (mentions + links)
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
            "This method is deprecated for backlink discovery. Use search_duckduckgo_backlinks() instead.",
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
        base_url = f"https://index.commoncrawl.org/{index}-index"

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

                    # Format timestamp
                    crawl_date = None
                    if len(timestamp) >= 8:
                        try:
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

    def _check_for_captcha_or_block(self, html: str) -> Tuple[bool, str]:
        """
        Check if the page contains a CAPTCHA or block indicator.

        Args:
            html: Page HTML source

        Returns:
            Tuple of (is_blocked, reason)
        """
        if not html:
            return True, "EMPTY_RESPONSE"

        html_lower = html.lower()

        # CAPTCHA indicators
        captcha_indicators = [
            'captcha', 'recaptcha', 'g-recaptcha', 'hcaptcha',
            'one last step', 'verify you are human', 'security check',
            'unusual traffic', 'verify?partner=', 'challenge/verify',
        ]

        for indicator in captcha_indicators:
            if indicator in html_lower:
                return True, f"CAPTCHA_DETECTED:{indicator}"

        # Block indicators
        block_indicators = [
            'access denied', 'blocked', '403 forbidden',
            'your request has been blocked',
        ]

        for indicator in block_indicators:
            if indicator in html_lower:
                return True, f"BLOCKED:{indicator}"

        return False, "OK"

    def _search_bing_with_driver(
        self,
        driver,
        query: str,
        domain: str,
        max_results: int,
    ) -> Tuple[List[Dict[str, Any]], bool, str]:
        """
        Execute Bing search with given driver and return results.

        Args:
            driver: Selenium driver (already warmed up)
            query: Search query
            domain: Target domain
            max_results: Max results to scrape

        Returns:
            Tuple of (results, is_blocked, reason)
        """
        from bs4 import BeautifulSoup

        backlink_sources = []
        seen_domains: Set[str] = set()

        search_url = f"https://www.bing.com/search?q={quote(query)}"
        logger.info(f"Fetching Bing results from: {search_url}")

        # Apply long human delay before search to avoid CAPTCHA (30-60s)
        delay_before = random.uniform(30.0, 60.0)
        logger.info(f"Waiting {delay_before:.1f}s before Bing search...")
        human_delay(min_seconds=30.0, max_seconds=60.0, jitter=5.0)

        driver.get(search_url)

        # Wait for results with human-like behavior (15-25s)
        time.sleep(random.uniform(15.0, 25.0))

        # Simulate reading the page
        self._simulate_human_behavior(driver, intensity="normal")

        # Get page source
        html = driver.page_source

        # Check for CAPTCHA/block
        is_blocked, reason = self._check_for_captcha_or_block(html)
        if is_blocked:
            logger.warning(f"Bing search blocked: {reason}")
            return [], True, reason

        # Parse search results
        soup = BeautifulSoup(html, 'html.parser')

        # Bing search results are in <li class="b_algo"> elements
        results = soup.find_all('li', class_='b_algo')

        logger.info(f"Found {len(results)} Bing search results")

        # If no results found, might still be blocked
        if len(results) == 0:
            # Check for "No results" message vs actual block
            if 'no results' in html.lower() or 'did not match any' in html.lower():
                return [], False, "NO_RESULTS"
            else:
                # Likely blocked - results container exists but is empty
                return [], True, "RESULTS_EMPTY_POSSIBLE_BLOCK"

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
                    'verified': False,
                    'contains_link': None,
                })

            except Exception as e:
                logger.debug(f"Failed to parse Bing result: {e}")
                continue

        return backlink_sources, False, "OK"

    def search_bing_backlinks(
        self,
        domain: str,
        max_results: int = 50,
        verify_links: bool = True,
        max_escalation_attempts: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Use Bing search to find pages mentioning/linking to our domain.

        Uses SeleniumBase UC mode with:
        - Browser warming before search
        - CAPTCHA/block detection
        - Automatic browser escalation on block
        - Proxy rotation

        Note: Bing deprecated the "link:" operator in 2017. This method
        searches for domain mentions which may include both links and
        text-only mentions. Use verify_links=True to confirm actual backlinks.

        Args:
            domain: Domain to find backlinks for (e.g., "example.com")
            max_results: Maximum number of results to scrape (default 50)
            verify_links: If True, verify each result contains an actual link
            max_escalation_attempts: Max times to try with different browser tiers

        Returns:
            List of backlink sources found via Bing
        """
        logger.info(f"Searching Bing for backlinks to {domain} (max {max_results} results, verify={verify_links})")

        # Clean domain
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]

        # Randomize search query pattern to look more natural
        # Avoid obvious bot patterns like "-site:" operator
        # We filter out self-links in the parsing code anyway
        query_templates = [
            f'"{domain}"',                          # Simple quoted domain
            f'"www.{domain}"',                      # With www
            f'{domain} website',                    # Natural search
            f'{domain} company',                    # Business search
            f'"{domain}" reviews',                  # Review search
            f'link:{domain}',                       # Bing link operator (natural)
        ]
        query = random.choice(query_templates)
        logger.info(f"Using search pattern: {query}")

        backlink_sources = []

        for attempt in range(max_escalation_attempts):
            try:
                logger.info(f"Attempt {attempt + 1}/{max_escalation_attempts}")

                # Use browser pool via browser_session (pool handles warmup and escalation)
                with self.browser_session("bing") as driver:
                    if driver is None:
                        logger.error("Failed to get driver from pool")
                        continue

                    # Execute search
                    backlink_sources, is_blocked, reason = self._search_bing_with_driver(
                        driver, query, domain, max_results
                    )

                    if is_blocked:
                        logger.warning(f"Search blocked: {reason}")
                        # Wait before retry with long exponential backoff (60-120s per attempt)
                        wait_time = (attempt + 1) * 60 + random.randint(0, 60)
                        logger.info(f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                        # Raise to trigger pool's block reporting via exception handling
                        raise RuntimeError(f"Bing blocked: {reason}")

                    # Success!
                    logger.info(f"Found {len(backlink_sources)} unique backlink sources from Bing")
                    break

            except RuntimeError as e:
                if "blocked" in str(e).lower():
                    logger.warning(f"Bing search attempt {attempt + 1} blocked, will retry")
                    continue
                raise

            except Exception as e:
                logger.error(f"Bing search attempt {attempt + 1} failed: {e}")
                # Wait before retry (30-60s)
                wait_time = 30 + random.randint(0, 30)
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

        # Optionally verify results contain actual backlinks
        if verify_links and backlink_sources:
            verified_sources = []
            for source in backlink_sources[:min(10, len(backlink_sources))]:
                backlinks = self.check_page_for_backlinks(
                    source['source_url'],
                    [domain]
                )
                if backlinks:
                    source['verified'] = True
                    source['contains_link'] = True
                    source['found_backlinks'] = backlinks
                    verified_sources.append(source)
                else:
                    source['verified'] = True
                    source['contains_link'] = False
                    source['is_mention_only'] = True
                    verified_sources.append(source)

            logger.info(f"Verified {len([s for s in verified_sources if s.get('contains_link')])} "
                       f"actual backlinks out of {len(verified_sources)} checked")

            return verified_sources

        return backlink_sources

    def _search_duckduckgo_with_driver(
        self,
        driver,
        query: str,
        domain: str,
        max_results: int,
    ) -> Tuple[List[Dict[str, Any]], bool, str]:
        """
        Execute DuckDuckGo search with given driver and return results.

        Args:
            driver: Selenium driver (already warmed up)
            query: Search query
            domain: Target domain
            max_results: Max results to scrape

        Returns:
            Tuple of (results, is_blocked, reason)
        """
        from bs4 import BeautifulSoup

        backlink_sources = []
        seen_domains: Set[str] = set()

        # DuckDuckGo search URL
        search_url = f"https://duckduckgo.com/?q={quote(query)}&ia=web"
        logger.info(f"Fetching DuckDuckGo results from: {search_url}")

        # Apply moderate human delay before search (5-15s - DDG is less aggressive)
        delay_before = random.uniform(5.0, 15.0)
        logger.info(f"Waiting {delay_before:.1f}s before DuckDuckGo search...")
        human_delay(min_seconds=5.0, max_seconds=15.0, jitter=2.0)

        driver.get(search_url)

        # Wait for JavaScript to render results (DDG is JS-heavy)
        time.sleep(random.uniform(5.0, 10.0))

        # Scroll down to trigger lazy loading
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
            time.sleep(random.uniform(1.0, 2.0))
        except Exception:
            pass

        # Simulate reading the page
        self._simulate_human_behavior(driver, intensity="light")

        # Get page source
        html = driver.page_source

        # Check for CAPTCHA/block (DDG rarely blocks, but check anyway)
        is_blocked, reason = self._check_for_captcha_or_block(html)
        if is_blocked:
            logger.warning(f"DuckDuckGo search blocked: {reason}")
            return [], True, reason

        # Parse search results
        soup = BeautifulSoup(html, 'html.parser')

        # DuckDuckGo results are in article tags with data-testid="result"
        # or in older format: div elements with result classes
        results = soup.find_all('article', attrs={'data-testid': 'result'})

        # Fallback: try other selectors if no results found
        if not results:
            results = soup.find_all('div', class_='result')
        if not results:
            results = soup.find_all('div', class_='links_main')
        if not results:
            # Try finding all result links
            results = soup.select('[data-testid="result-title-a"]')

        logger.info(f"Found {len(results)} DuckDuckGo search results")

        # If no results found, check if actually blocked
        if len(results) == 0:
            # Check for "No results" message
            no_results_indicators = ['no results', 'did not match', 'nothing found']
            if any(ind in html.lower() for ind in no_results_indicators):
                return [], False, "NO_RESULTS"
            # Check if page loaded at all
            if 'duckduckgo' not in html.lower():
                return [], True, "PAGE_NOT_LOADED"
            # May just be empty for this query
            return [], False, "EMPTY_RESULTS"

        for result in results[:max_results]:
            try:
                # Extract link - try multiple selectors
                a_tag = None

                # Try data-testid selector first (modern DDG)
                a_tag = result.find('a', attrs={'data-testid': 'result-title-a'})

                # Fallback to first link in result
                if not a_tag:
                    a_tag = result.find('a', href=True)

                if not a_tag or not a_tag.get('href'):
                    continue

                url = a_tag['href']

                # Skip DDG internal links
                if 'duckduckgo.com' in url:
                    continue

                # Parse URL
                parsed = urlparse(url)
                source_domain = parsed.netloc.lower()
                if source_domain.startswith('www.'):
                    source_domain = source_domain[4:]

                # Skip if same domain (internal links)
                if source_domain == domain or domain in source_domain:
                    continue

                # Skip if already seen
                if source_domain in seen_domains:
                    continue

                seen_domains.add(source_domain)

                # Extract snippet/context
                snippet_elem = result.find('span', attrs={'data-testid': 'result-snippet'})
                if not snippet_elem:
                    snippet_elem = result.find('p') or result.find('div', class_='snippet')
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                backlink_sources.append({
                    'source_url': url,
                    'source_domain': source_domain,
                    'target_domain': domain,
                    'discovered_via': 'duckduckgo_search',
                    'context': snippet[:200],
                    'verified': False,
                    'contains_link': None,
                })

            except Exception as e:
                logger.debug(f"Failed to parse DuckDuckGo result: {e}")
                continue

        return backlink_sources, False, "OK"

    def search_duckduckgo_backlinks(
        self,
        domain: str,
        max_results: int = 50,
        verify_links: bool = True,
        max_escalation_attempts: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Use DuckDuckGo search to find pages mentioning/linking to our domain.

        DuckDuckGo is generally less aggressive with bot detection than Bing,
        making it more reliable for automated backlink discovery.

        Uses SeleniumBase UC mode with:
        - Browser warming before search
        - CAPTCHA/block detection
        - Automatic browser escalation on block
        - Proxy rotation

        Args:
            domain: Domain to find backlinks for (e.g., "example.com")
            max_results: Maximum number of results to scrape (default 50)
            verify_links: If True, verify each result contains an actual link
            max_escalation_attempts: Max times to try with different browser tiers

        Returns:
            List of backlink sources found via DuckDuckGo
        """
        logger.info(f"Searching DuckDuckGo for backlinks to {domain} (max {max_results} results, verify={verify_links})")

        # Clean domain
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]

        # Randomize search query pattern to look natural
        query_templates = [
            f'"{domain}"',                          # Simple quoted domain
            f'"www.{domain}"',                      # With www
            f'{domain} site',                       # Natural search
            f'{domain} website',                    # Website search
            f'"{domain}" link',                     # Link search
        ]
        query = random.choice(query_templates)
        logger.info(f"Using search pattern: {query}")

        backlink_sources = []

        for attempt in range(max_escalation_attempts):
            try:
                logger.info(f"Attempt {attempt + 1}/{max_escalation_attempts}")

                # Use browser pool via browser_session
                with self.browser_session("duckduckgo") as driver:
                    if driver is None:
                        logger.error("Failed to get driver from pool")
                        continue

                    # Execute search
                    backlink_sources, is_blocked, reason = self._search_duckduckgo_with_driver(
                        driver, query, domain, max_results
                    )

                    if is_blocked:
                        logger.warning(f"Search blocked: {reason}")
                        # Wait before retry (shorter than Bing since DDG is less aggressive)
                        wait_time = (attempt + 1) * 20 + random.randint(0, 20)
                        logger.info(f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                        raise RuntimeError(f"DuckDuckGo blocked: {reason}")

                    # Success!
                    logger.info(f"Found {len(backlink_sources)} unique backlink sources from DuckDuckGo")
                    break

            except RuntimeError as e:
                if "blocked" in str(e).lower():
                    logger.warning(f"DuckDuckGo search attempt {attempt + 1} blocked, will retry")
                    continue
                raise

            except Exception as e:
                logger.error(f"DuckDuckGo search attempt {attempt + 1} failed: {e}")
                # Wait before retry (15-30s)
                wait_time = 15 + random.randint(0, 15)
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

        # Optionally verify results contain actual backlinks
        if verify_links and backlink_sources:
            verified_sources = []
            for source in backlink_sources[:min(10, len(backlink_sources))]:
                backlinks = self.check_page_for_backlinks(
                    source['source_url'],
                    [domain]
                )
                if backlinks:
                    source['verified'] = True
                    source['contains_link'] = True
                    source['found_backlinks'] = backlinks
                    verified_sources.append(source)
                else:
                    source['verified'] = True
                    source['contains_link'] = False
                    source['is_mention_only'] = True
                    verified_sources.append(source)

            logger.info(f"Verified {len([s for s in verified_sources if s.get('contains_link')])} "
                       f"actual backlinks out of {len(verified_sources)} checked")

            return verified_sources

        return backlink_sources

    def search_wayback_machine(
        self,
        domain: str,
        target_domain: str,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Search Wayback Machine for historical snapshots containing links to target domain.

        Uses the Wayback Machine CDX API to find archived pages that might contain
        backlinks. Then fetches archived versions to verify link presence.

        This is useful for:
        - Finding historical backlinks that may have been removed
        - Discovering links from sites that have changed
        - Building link velocity data (when links were first/last seen)

        Args:
            domain: Source domain to search for snapshots (e.g., "example.com")
            target_domain: Our domain we're looking for links TO
            max_results: Maximum snapshots to check

        Returns:
            List of backlink sources found via Wayback Machine
        """
        logger.info(f"Searching Wayback Machine for {domain} -> {target_domain} links")

        backlink_sources = []
        seen_urls = set()

        # Clean domains
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]
        target_domain = target_domain.lower().strip()
        if target_domain.startswith('www.'):
            target_domain = target_domain[4:]

        try:
            # Search Wayback Machine CDX API for all captures of the domain
            cdx_url = "https://web.archive.org/cdx/search/cdx"
            params = {
                'url': f'{domain}/*',
                'output': 'json',
                'filter': 'statuscode:200',
                'filter': 'mimetype:text/html',
                'limit': max_results * 2,  # Get more to filter
                'fl': 'original,timestamp,statuscode',
                'collapse': 'urlkey',  # Dedupe by URL
            }

            response = requests.get(cdx_url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            if not data or len(data) < 2:
                logger.info(f"No Wayback Machine captures found for {domain}")
                return []

            # Skip header row
            captures = data[1:]
            logger.info(f"Found {len(captures)} Wayback Machine captures for {domain}")

            # Check a sample of captures for backlinks
            checked = 0
            for capture in captures[:max_results]:
                if checked >= max_results // 2:  # Limit verification checks
                    break

                try:
                    original_url = capture[0]
                    timestamp = capture[1]

                    # Skip if already seen
                    if original_url in seen_urls:
                        continue
                    seen_urls.add(original_url)

                    # Construct Wayback URL
                    wayback_url = f"https://web.archive.org/web/{timestamp}/{original_url}"

                    # Fetch archived page
                    human_delay(min_seconds=1.0, max_seconds=2.0, jitter=0.3)

                    archive_response = requests.get(
                        wayback_url,
                        timeout=15,
                        headers={'User-Agent': 'BacklinkCrawler/1.0'}
                    )

                    if archive_response.status_code != 200:
                        continue

                    html = archive_response.text

                    # Check for links to target domain
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')

                    found_link = False
                    link_details = {}

                    for link in soup.find_all('a', href=True):
                        href = link.get('href', '')

                        # Skip Wayback navigation links
                        if 'web.archive.org' in href:
                            continue

                        # Check if link points to target domain
                        href_lower = href.lower()
                        if target_domain in href_lower:
                            found_link = True
                            anchor_text = link.get_text(strip=True)

                            # Get surrounding context
                            context = ""
                            parent = link.parent
                            if parent:
                                context = parent.get_text(strip=True)[:200]

                            # Determine link type
                            rel = link.get('rel', [])
                            if isinstance(rel, str):
                                rel = [rel]
                            link_type = "dofollow"
                            if 'nofollow' in rel:
                                link_type = "nofollow"

                            link_details = {
                                'anchor_text': anchor_text,
                                'link_type': link_type,
                                'context': context,
                                'target_url': href,
                            }
                            break

                    if found_link:
                        # Parse timestamp to date
                        crawl_date = None
                        if len(timestamp) >= 8:
                            try:
                                crawl_date = datetime.strptime(timestamp[:8], '%Y%m%d').isoformat()
                            except:
                                pass

                        source_domain = urlparse(original_url).netloc
                        if source_domain.startswith('www.'):
                            source_domain = source_domain[4:]

                        backlink_sources.append({
                            'source_url': original_url,
                            'source_domain': source_domain,
                            'target_domain': target_domain,
                            'discovered_via': 'wayback_machine',
                            'wayback_url': wayback_url,
                            'wayback_timestamp': timestamp,
                            'crawl_date': crawl_date,
                            'verified': True,
                            'contains_link': True,
                            **link_details,
                        })

                        logger.debug(f"Found historical backlink: {original_url} -> {target_domain}")

                    checked += 1

                except Exception as e:
                    logger.debug(f"Error checking Wayback capture: {e}")
                    continue

            logger.info(f"Found {len(backlink_sources)} historical backlinks via Wayback Machine")

        except Exception as e:
            logger.error(f"Wayback Machine search failed: {e}")

        return backlink_sources

    def discover_backlinks(
        self,
        domain: str,
        max_results: int = 50,
        verify: bool = True,
        include_historical: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Comprehensive backlink discovery using multiple methods.

        Combines Bing search with optional verification. This is the
        recommended entry point for backlink discovery.

        Args:
            domain: Domain to find backlinks for
            max_results: Maximum results to return
            verify: Whether to verify backlinks exist on found pages
            include_historical: Also search Wayback Machine for historical links

        Returns:
            List of discovered backlink sources
        """
        logger.info(f"Starting comprehensive backlink discovery for {domain}")

        all_sources = []
        seen_urls = set()

        # Method 1: DuckDuckGo search (primary free method - more reliable than Bing)
        ddg_results = self.search_duckduckgo_backlinks(
            domain,
            max_results=max_results,
            verify_links=verify
        )
        for result in ddg_results:
            if result['source_url'] not in seen_urls:
                seen_urls.add(result['source_url'])
                all_sources.append(result)

        # Method 2: Wayback Machine for historical links (optional)
        if include_historical:
            # Search for top referring domains from DuckDuckGo results
            referring_domains = set()
            for source in all_sources[:10]:
                rd = source.get('source_domain')
                if rd and rd != domain:
                    referring_domains.add(rd)

            # Check Wayback Machine for historical snapshots
            for rd in list(referring_domains)[:5]:  # Limit to avoid too many requests
                wayback_results = self.search_wayback_machine(
                    rd,
                    target_domain=domain,
                    max_results=10
                )
                for result in wayback_results:
                    if result['source_url'] not in seen_urls:
                        seen_urls.add(result['source_url'])
                        all_sources.append(result)

        logger.info(f"Discovered {len(all_sources)} backlink sources for {domain}")

        return all_sources

    def discover_backlinks_with_artifact(
        self,
        domain: str,
        max_results: int = 50,
        verify: bool = True,
        save_artifact: bool = True,
        quality_profile: Optional['ScrapeQualityProfile'] = None,
    ) -> Tuple[List[Dict[str, Any]], List['PageArtifact']]:
        """
        Discover backlinks with comprehensive artifact capture for each verified page.

        This method captures raw HTML, screenshots, and metadata for each page
        checked for backlinks, allowing offline re-parsing and analysis.

        Args:
            domain: Domain to find backlinks for
            max_results: Maximum results to return
            verify: Whether to verify backlinks exist on found pages
            save_artifact: Whether to save artifacts to disk
            quality_profile: Quality profile for artifact capture

        Returns:
            Tuple of (list of backlink sources, list of PageArtifacts)
        """
        from seo_intelligence.models.artifacts import (
            PageArtifact,
            ScrapeQualityProfile,
            ArtifactStorage,
            HIGH_QUALITY_PROFILE,
            DEFAULT_QUALITY_PROFILE,
        )
        from datetime import datetime, timezone
        import time

        profile = quality_profile or DEFAULT_QUALITY_PROFILE
        artifacts = []
        storage = ArtifactStorage() if save_artifact else None

        logger.info(f"Starting backlink discovery with artifact capture for {domain}")

        # First, discover potential backlink sources via DuckDuckGo
        all_sources = []
        seen_urls = set()

        # Method 1: DuckDuckGo search (primary free method - more reliable than Bing)
        ddg_results = self.search_duckduckgo_backlinks(
            domain,
            max_results=max_results,
            verify_links=False  # We'll verify manually with artifact capture
        )

        for result in ddg_results:
            if result['source_url'] not in seen_urls:
                seen_urls.add(result['source_url'])
                all_sources.append(result)

        logger.info(f"Found {len(all_sources)} potential backlink sources for {domain}")

        # Now verify each source with artifact capture
        verified_sources = []
        for source in all_sources[:min(20, len(all_sources))]:  # Limit verification
            source_url = source['source_url']

            try:
                # Apply human delay
                human_delay(min_seconds=2.0, max_seconds=4.0, jitter=0.5)

                with self.browser_session(site="generic") as driver:
                    start_time = time.time()

                    # Configure viewport if specified
                    if profile.viewport_width and profile.viewport_height:
                        driver.set_window_size(profile.viewport_width, profile.viewport_height)

                    # Navigate to page
                    driver.get(source_url)

                    # Wait based on profile
                    if profile.wait_strategy == "networkidle":
                        time.sleep(3.0)
                    else:
                        time.sleep(random.uniform(1.5, 2.5))

                    # Extra wait if configured
                    if profile.extra_wait_seconds > 0:
                        time.sleep(profile.extra_wait_seconds)

                    # Get final URL after redirects
                    final_url = driver.current_url

                    # Get page source
                    html = driver.page_source

                    # Calculate fetch duration
                    fetch_duration = int((time.time() - start_time) * 1000)

                    # Create artifact
                    artifact = PageArtifact(
                        url=source_url,
                        final_url=final_url,
                        status_code=200,
                        html_raw=html,
                        engine="seleniumbase",
                        fetch_duration_ms=fetch_duration,
                        quality_profile=profile.to_dict(),
                        viewport={"width": profile.viewport_width, "height": profile.viewport_height},
                        metadata={
                            "scraper": "backlink_crawler_selenium",
                            "target_domain": domain,
                            "source_domain": source.get('source_domain', ''),
                            "discovered_via": source.get('discovered_via', 'bing_search'),
                        }
                    )

                    # Capture screenshot if configured
                    if profile.capture_screenshot:
                        try:
                            screenshot_path = f"/tmp/backlink_{artifact.url_hash}.png"
                            driver.save_screenshot(screenshot_path)
                            artifact.screenshot_path = screenshot_path
                        except Exception as e:
                            logger.debug(f"Screenshot capture failed: {e}")

                    # Capture console logs if available
                    if profile.capture_console:
                        try:
                            logs = driver.get_log('browser')
                            for log in logs:
                                if log.get('level') == 'SEVERE':
                                    artifact.console_errors.append(log.get('message', ''))
                                elif log.get('level') == 'WARNING':
                                    artifact.console_warnings.append(log.get('message', ''))
                        except Exception:
                            pass

                    # Extract backlinks from page
                    backlinks = self._extract_backlinks_from_page(
                        html, source_url, [domain]
                    )

                    # Update source with verification results
                    if backlinks:
                        source['verified'] = True
                        source['contains_link'] = True
                        source['found_backlinks'] = backlinks
                        verified_sources.append(source)

                        # Add backlink details to artifact metadata
                        artifact.metadata['backlinks_found'] = len(backlinks)
                        artifact.metadata['backlinks'] = backlinks[:5]  # First 5

                        # Save to database
                        if self.engine:
                            source_domain = urlparse(source_url).netloc
                            if source_domain.startswith('www.'):
                                source_domain = source_domain[4:]

                            with Session(self.engine) as session:
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
                    else:
                        source['verified'] = True
                        source['contains_link'] = False
                        source['is_mention_only'] = True

                    # Save artifact
                    if storage:
                        artifact_path = storage.save(artifact)
                        artifact.metadata['artifact_path'] = artifact_path

                    artifacts.append(artifact)

            except Exception as e:
                logger.warning(f"Error verifying backlink source {source_url}: {e}")
                source['verified'] = False
                source['error'] = str(e)

        logger.info(
            f"Backlink discovery complete: {len(verified_sources)} verified backlinks, "
            f"{len(artifacts)} artifacts captured"
        )

        return verified_sources, artifacts

    def check_page_for_backlinks(
        self,
        source_url: str,
        target_domains: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Check a single page for backlinks to target domains using SeleniumBase UC.

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
            with self.browser_session(site="generic") as driver:
                # Navigate to page
                driver.get(source_url)

                # Wait for page load
                time.sleep(random.uniform(1.5, 3.0))

                # Get page source
                html = driver.page_source

                if not html:
                    logger.warning(f"Failed to fetch {source_url}")
                    return []

                # Simulate human behavior: scroll through page
                try:
                    scroll_delays = get_scroll_delays()
                    for i, scroll_delay in enumerate(scroll_delays):
                        # Scroll down in increments (simulate reading)
                        scroll_amount = random.randint(200, 600)
                        driver.execute_script(f"window.scrollBy(0, {scroll_amount})")
                        time.sleep(scroll_delay)

                    # Simulate human reading the page
                    content_length = len(html) // 2
                    reading_delay = get_human_reading_delay(min(content_length, 2000))

                    # Take a portion of the reading delay
                    remaining_delay = reading_delay * random.uniform(0.3, 0.6)
                    time.sleep(remaining_delay)

                except Exception as e:
                    logger.debug(f"Error during human behavior simulation: {e}")

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

        with task_logger.log_task("backlink_crawler_selenium", "scraper", {"source_count": len(source_urls)}) as task:
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
_backlink_crawler_selenium_instance = None


def get_backlink_crawler_selenium(**kwargs) -> BacklinkCrawlerSelenium:
    """Get or create the singleton BacklinkCrawlerSelenium instance."""
    global _backlink_crawler_selenium_instance

    if _backlink_crawler_selenium_instance is None:
        _backlink_crawler_selenium_instance = BacklinkCrawlerSelenium(**kwargs)

    return _backlink_crawler_selenium_instance
