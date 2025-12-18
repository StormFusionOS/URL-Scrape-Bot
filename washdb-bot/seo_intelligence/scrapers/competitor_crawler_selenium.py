"""
Competitor Crawler Module (SeleniumBase Version)

Crawls competitor websites to analyze their SEO strategy.
Uses SeleniumBase with undetected Chrome for anti-detection.

Features:
- Discover competitors from SERP results
- Crawl competitor pages (homepage, services, etc.)
- Extract SEO metrics (titles, meta, schema, content)
- Track content changes via SHA-256 hashing
- Store in competitors and competitor_pages tables
- Sitemap-based page discovery (robots.txt parsing, sitemap index handling)
- Internal link graph building with anchor text analysis
- Smart URL prioritization (services, locations, blog pages)

Per SCRAPING_NOTES.md:
- Use Tier B rate limits (10-20s delay) for competitor sites
- Respect robots.txt for each domain
- Hash content for change detection
"""

import os
import re
import json
import time
import random
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse, urljoin
from collections import defaultdict

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper
from seo_intelligence.scrapers.competitor_parser import get_competitor_parser, PageMetrics
from seo_intelligence.services import (
    get_task_logger,
    get_content_hasher,
    get_content_embedder,
    get_qdrant_manager,
    extract_main_content
)
from seo_intelligence.services.section_embedder import get_section_embedder
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("competitor_crawler_selenium")


# ============================================================================
# Sitemap Discovery Data Classes
# ============================================================================

@dataclass
class SitemapURL:
    """Represents a URL from a sitemap with metadata."""
    url: str
    lastmod: Optional[str] = None
    changefreq: Optional[str] = None
    priority: Optional[float] = None
    page_type: str = "unknown"  # homepage, services, location, blog, about, etc.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "lastmod": self.lastmod,
            "changefreq": self.changefreq,
            "priority": self.priority,
            "page_type": self.page_type,
        }


@dataclass
class InternalLink:
    """Represents an internal link with anchor text and context."""
    source_url: str
    target_url: str
    anchor_text: str
    position: str = "body"  # nav, header, footer, sidebar, body
    rel_attributes: List[str] = field(default_factory=list)
    context_snippet: Optional[str] = None  # Surrounding text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source_url,
            "target": self.target_url,
            "anchor": self.anchor_text,
            "position": self.position,
            "rel": self.rel_attributes,
            "context": self.context_snippet,
        }


@dataclass
class InternalLinkGraph:
    """
    Graph of internal links for a site.

    Tracks which pages link to which, with anchor text and context.
    Used to understand site structure and page importance.
    """
    domain: str
    links: List[InternalLink] = field(default_factory=list)
    page_scores: Dict[str, float] = field(default_factory=dict)  # URL -> importance score

    def add_link(self, link: InternalLink) -> None:
        """Add a link to the graph."""
        self.links.append(link)

    def get_inbound_links(self, url: str) -> List[InternalLink]:
        """Get all links pointing to a URL."""
        return [l for l in self.links if l.target_url == url]

    def get_outbound_links(self, url: str) -> List[InternalLink]:
        """Get all links from a URL."""
        return [l for l in self.links if l.source_url == url]

    def calculate_page_scores(self) -> Dict[str, float]:
        """
        Calculate page importance scores based on inbound links.

        Simple scoring:
        - Base score: 1.0
        - +0.5 for each inbound link from navigation
        - +0.3 for each inbound link from body
        - +0.1 for each inbound link from footer
        """
        scores = defaultdict(lambda: 1.0)

        for link in self.links:
            if link.position == "nav" or link.position == "header":
                scores[link.target_url] += 0.5
            elif link.position == "body":
                scores[link.target_url] += 0.3
            elif link.position == "footer":
                scores[link.target_url] += 0.1
            else:
                scores[link.target_url] += 0.2

        self.page_scores = dict(scores)
        return self.page_scores

    def get_top_pages(self, limit: int = 20) -> List[Tuple[str, float]]:
        """Get top pages by importance score."""
        if not self.page_scores:
            self.calculate_page_scores()

        sorted_pages = sorted(
            self.page_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_pages[:limit]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "link_count": len(self.links),
            "top_pages": self.get_top_pages(10),
            "links_sample": [l.to_dict() for l in self.links[:50]],
        }


class SitemapDiscovery:
    """
    Discovers and parses sitemaps for a domain.

    Features:
    - Fetches robots.txt to find sitemap locations
    - Handles sitemap indexes (nested sitemaps)
    - Extracts URLs with lastmod and priority metadata
    - Smart prioritization by URL patterns
    """

    # XML namespace for sitemaps
    SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # URL patterns for page type classification
    PAGE_TYPE_PATTERNS = {
        "services": [r'/services?/', r'/service/', r'/what-we-do', r'/solutions?/'],
        "locations": [r'/locations?/', r'/areas?/', r'/service-area', r'/cities/'],
        "blog": [r'/blog/', r'/news/', r'/articles?/', r'/posts?/'],
        "about": [r'/about', r'/our-story', r'/team', r'/company'],
        "contact": [r'/contact', r'/get-quote', r'/request', r'/schedule'],
        "portfolio": [r'/portfolio', r'/gallery', r'/projects?/', r'/work/'],
        "pricing": [r'/pricing', r'/rates', r'/cost', r'/packages?/'],
        "faq": [r'/faq', r'/questions', r'/help/'],
        "reviews": [r'/reviews?/', r'/testimonials?/'],
    }

    def __init__(self, timeout: int = 15):
        """
        Initialize sitemap discovery.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; SEOBot/1.0; +http://example.com/bot)"
        })

    def discover_sitemaps(self, domain: str) -> List[str]:
        """
        Discover sitemap URLs for a domain.

        Checks:
        1. robots.txt for Sitemap: directives
        2. Common sitemap locations

        Args:
            domain: Domain to check (e.g., "example.com")

        Returns:
            List of sitemap URLs
        """
        sitemaps = []
        base_url = f"https://{domain}"

        # 1. Check robots.txt
        robots_url = f"{base_url}/robots.txt"
        try:
            resp = self.session.get(robots_url, timeout=self.timeout)
            if resp.status_code == 200:
                for line in resp.text.split("\n"):
                    line = line.strip()
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url and sitemap_url not in sitemaps:
                            sitemaps.append(sitemap_url)
                            logger.debug(f"Found sitemap in robots.txt: {sitemap_url}")
        except Exception as e:
            logger.debug(f"Failed to fetch robots.txt for {domain}: {e}")

        # 2. Check common sitemap locations
        common_locations = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/sitemaps/sitemap.xml",
            "/wp-sitemap.xml",  # WordPress
        ]

        for path in common_locations:
            sitemap_url = f"{base_url}{path}"
            if sitemap_url in sitemaps:
                continue

            try:
                resp = self.session.head(sitemap_url, timeout=self.timeout)
                if resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "")
                    if "xml" in content_type or "text" in content_type:
                        sitemaps.append(sitemap_url)
                        logger.debug(f"Found sitemap at common location: {sitemap_url}")
            except Exception:
                pass

        logger.info(f"Discovered {len(sitemaps)} sitemaps for {domain}")
        return sitemaps

    def parse_sitemap(
        self,
        sitemap_url: str,
        max_urls: int = 500,
        follow_index: bool = True,
    ) -> List[SitemapURL]:
        """
        Parse a sitemap and extract URLs.

        Handles both regular sitemaps and sitemap indexes.

        Args:
            sitemap_url: URL of the sitemap
            max_urls: Maximum URLs to extract
            follow_index: Whether to follow sitemap index entries

        Returns:
            List of SitemapURL objects
        """
        urls = []

        try:
            resp = self.session.get(sitemap_url, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch sitemap {sitemap_url}: {resp.status_code}")
                return urls

            # Parse XML
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError as e:
                logger.warning(f"Failed to parse sitemap XML {sitemap_url}: {e}")
                return urls

            # Check if this is a sitemap index
            index_entries = root.findall(".//sm:sitemap", self.SITEMAP_NS)
            if index_entries and follow_index:
                logger.info(f"Found sitemap index with {len(index_entries)} sitemaps")
                for entry in index_entries[:20]:  # Limit to 20 sub-sitemaps
                    loc = entry.find("sm:loc", self.SITEMAP_NS)
                    if loc is not None and loc.text:
                        child_urls = self.parse_sitemap(
                            loc.text,
                            max_urls=max_urls - len(urls),
                            follow_index=False,  # Don't recurse further
                        )
                        urls.extend(child_urls)
                        if len(urls) >= max_urls:
                            break
                return urls[:max_urls]

            # Parse regular sitemap
            url_entries = root.findall(".//sm:url", self.SITEMAP_NS)

            for entry in url_entries:
                if len(urls) >= max_urls:
                    break

                loc = entry.find("sm:loc", self.SITEMAP_NS)
                if loc is None or not loc.text:
                    continue

                url = loc.text.strip()

                # Extract optional metadata
                lastmod = entry.find("sm:lastmod", self.SITEMAP_NS)
                changefreq = entry.find("sm:changefreq", self.SITEMAP_NS)
                priority_elem = entry.find("sm:priority", self.SITEMAP_NS)

                sitemap_url_obj = SitemapURL(
                    url=url,
                    lastmod=lastmod.text if lastmod is not None else None,
                    changefreq=changefreq.text if changefreq is not None else None,
                    priority=float(priority_elem.text) if priority_elem is not None else None,
                    page_type=self._classify_url(url),
                )
                urls.append(sitemap_url_obj)

            logger.info(f"Parsed {len(urls)} URLs from {sitemap_url}")

        except Exception as e:
            logger.error(f"Error parsing sitemap {sitemap_url}: {e}")

        return urls

    def _classify_url(self, url: str) -> str:
        """
        Classify a URL by page type based on patterns.

        Args:
            url: URL to classify

        Returns:
            Page type string
        """
        path = urlparse(url).path.lower()

        # Check homepage
        if path == "/" or path == "":
            return "homepage"

        # Check against patterns
        for page_type, patterns in self.PAGE_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, path):
                    return page_type

        return "other"

    def prioritize_urls(
        self,
        urls: List[SitemapURL],
        max_urls: int = 50,
    ) -> List[SitemapURL]:
        """
        Prioritize URLs for crawling.

        Priority order:
        1. Homepage
        2. Services pages
        3. Locations pages
        4. About/Contact
        5. Blog posts (recent first by lastmod)
        6. Other pages

        Args:
            urls: List of SitemapURL objects
            max_urls: Maximum URLs to return

        Returns:
            Prioritized list of SitemapURL objects
        """
        priority_order = {
            "homepage": 0,
            "services": 1,
            "locations": 2,
            "pricing": 3,
            "about": 4,
            "contact": 5,
            "portfolio": 6,
            "reviews": 7,
            "faq": 8,
            "blog": 9,
            "other": 10,
        }

        def sort_key(sitemap_url: SitemapURL) -> Tuple:
            type_priority = priority_order.get(sitemap_url.page_type, 10)

            # Use sitemap priority if available (higher is better)
            xml_priority = sitemap_url.priority or 0.5

            # Use lastmod for freshness (more recent is better)
            lastmod_value = sitemap_url.lastmod or "2000-01-01"

            return (type_priority, -xml_priority, -hash(lastmod_value))

        sorted_urls = sorted(urls, key=sort_key)

        # Ensure diversity: limit per page type
        result = []
        type_counts = defaultdict(int)
        max_per_type = {
            "homepage": 1,
            "services": 10,
            "locations": 10,
            "blog": 5,
            "other": 10,
        }

        for url in sorted_urls:
            limit = max_per_type.get(url.page_type, 5)
            if type_counts[url.page_type] < limit:
                result.append(url)
                type_counts[url.page_type] += 1
                if len(result) >= max_urls:
                    break

        return result

    def get_all_urls(
        self,
        domain: str,
        max_urls: int = 100,
        prioritize: bool = True,
    ) -> List[SitemapURL]:
        """
        Discover sitemaps and get prioritized URLs for a domain.

        Args:
            domain: Domain to crawl
            max_urls: Maximum URLs to return
            prioritize: Whether to apply smart prioritization

        Returns:
            List of SitemapURL objects
        """
        # Discover sitemaps
        sitemaps = self.discover_sitemaps(domain)

        if not sitemaps:
            logger.warning(f"No sitemaps found for {domain}")
            return []

        # Parse all sitemaps
        all_urls = []
        seen_urls = set()

        for sitemap_url in sitemaps:
            urls = self.parse_sitemap(sitemap_url, max_urls=max_urls * 2)
            for url in urls:
                if url.url not in seen_urls:
                    seen_urls.add(url.url)
                    all_urls.append(url)

        # Prioritize if requested
        if prioritize:
            return self.prioritize_urls(all_urls, max_urls)

        return all_urls[:max_urls]


# Default mobile viewport (iPhone X)
MOBILE_VIEWPORT = {"width": 375, "height": 812}


class CompetitorCrawlerSelenium(BaseSeleniumScraper):
    """
    Crawler for competitor website analysis using SeleniumBase.

    Uses SeleniumBase UC mode for undetected Chrome browsing.
    Discovers competitors from SERP results and crawls their pages
    to extract SEO metrics and track changes over time.
    """

    def __init__(
        self,
        headless: bool = False,  # Non-headless by default for max stealth
        use_proxy: bool = True,  # Enable proxy for better anti-detection
        max_pages_per_site: int = 10,
        max_pages: int = None,  # Alias for max_pages_per_site (backwards compatibility)
        enable_embeddings: bool = True,
        mobile_mode: bool = False,
    ):
        """
        Initialize competitor crawler with SeleniumBase UC drivers.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool
            max_pages_per_site: Maximum pages to crawl per competitor
            enable_embeddings: Enable Qdrant embedding generation (per SCRAPER BOT.pdf)
            mobile_mode: Use mobile viewport and user agent
        """
        super().__init__(
            name="competitor_crawler_selenium",
            tier="B",  # Medium-value targets (competitor sites)
            headless=headless,
            use_proxy=use_proxy,
            max_retries=3,
            page_timeout=30000,
            mobile_mode=mobile_mode,
        )
        self._mobile_mode = mobile_mode

        # Handle max_pages alias for backwards compatibility
        if max_pages is not None:
            max_pages_per_site = max_pages
        self.max_pages_per_site = max_pages_per_site
        self.parser = get_competitor_parser()
        self.hasher = get_content_hasher()
        self.enable_embeddings = enable_embeddings

        # Initialize embedding services if enabled
        if self.enable_embeddings:
            try:
                self.embedder = get_content_embedder()
                self.qdrant = get_qdrant_manager()
                self.section_embedder = get_section_embedder()
                logger.info("Embedding services initialized (page + section level)")
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

        # Sitemap discovery
        self.sitemap_discovery = SitemapDiscovery()

        logger.info(f"CompetitorCrawlerSelenium initialized (tier=B, max_pages={max_pages_per_site})")

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
                    CAST(:schema_markup AS jsonb), CAST(:links AS jsonb), CAST(:metadata AS jsonb)
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
                        logger.info(f"Embedded page {page_id} ({len(chunks)} chunks, {len(main_text)} chars)")

                        # Also embed sections (section-level semantic search)
                        if metrics.content_sections and len(metrics.content_sections) > 0:
                            try:
                                section_count = self.section_embedder.embed_and_store_sections(
                                    page_id=page_id,
                                    site_id=competitor_id,
                                    url=metrics.url,
                                    page_type=metrics.page_type,
                                    sections=metrics.content_sections
                                )
                                logger.info(f"Embedded {section_count} sections for page {page_id}")
                            except Exception as e:
                                logger.error(f"Failed to embed sections for page {page_id}: {e}")
                else:
                    logger.debug(f"Skipping embedding for page {page_id} - insufficient content")
            except Exception as e:
                logger.error(f"Failed to generate embeddings for page {page_id}: {e}")
                # Continue without embeddings - don't fail the entire save operation

        return page_id

    def _detect_tech_stack(self, html: str, url: str) -> Dict[str, Any]:
        """
        Detect technology stack used by the website.

        Detects:
        - CMS (WordPress, Wix, Squarespace, Shopify, etc.)
        - Analytics platforms (GA4, Plausible, Fathom, etc.)
        - Marketing tools (HubSpot, Mailchimp, ActiveCampaign, etc.)
        - Advertising (Google Ads, Facebook Pixel, LinkedIn Insight, etc.)
        - A/B testing tools (Optimizely, VWO, Google Optimize, etc.)
        - CDN/Performance (Cloudflare, Fastly, etc.)
        - Frameworks (React, Vue, Angular, Next.js, etc.)

        Args:
            html: Page HTML content
            url: Page URL for additional checks

        Returns:
            Dict with detected technologies by category
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        html_lower = html.lower()

        tech_stack = {
            "cms": [],
            "analytics": [],
            "marketing": [],
            "advertising": [],
            "ab_testing": [],
            "cdn_performance": [],
            "frameworks": [],
            "ecommerce": [],
            "chat_support": [],
            "forms": [],
            "other": [],
        }

        # ============================================================
        # CMS Detection
        # ============================================================
        cms_signatures = {
            "WordPress": [
                ("meta", {"name": "generator", "content": re.compile(r"wordpress", re.I)}),
                ("link", {"href": re.compile(r"/wp-content/", re.I)}),
                ("script", {"src": re.compile(r"/wp-includes/", re.I)}),
            ],
            "Wix": [
                ("meta", {"name": "generator", "content": re.compile(r"wix", re.I)}),
                ("script", {"src": re.compile(r"static\.wixstatic\.com", re.I)}),
            ],
            "Squarespace": [
                ("meta", {"name": "generator", "content": re.compile(r"squarespace", re.I)}),
                ("script", {"src": re.compile(r"squarespace", re.I)}),
            ],
            "Shopify": [
                ("meta", {"name": "generator", "content": re.compile(r"shopify", re.I)}),
                ("link", {"href": re.compile(r"cdn\.shopify\.com", re.I)}),
            ],
            "Webflow": [
                ("meta", {"name": "generator", "content": re.compile(r"webflow", re.I)}),
                ("html", {"data-wf-site": True}),
            ],
            "Weebly": [
                ("script", {"src": re.compile(r"weebly", re.I)}),
            ],
            "Joomla": [
                ("meta", {"name": "generator", "content": re.compile(r"joomla", re.I)}),
            ],
            "Drupal": [
                ("meta", {"name": "generator", "content": re.compile(r"drupal", re.I)}),
                ("script", {"src": re.compile(r"/sites/default/files/", re.I)}),
            ],
            "GoDaddy Website Builder": [
                ("script", {"src": re.compile(r"godaddy", re.I)}),
                ("meta", {"content": re.compile(r"godaddy", re.I)}),
            ],
            "HubSpot CMS": [
                ("script", {"src": re.compile(r"hubspot", re.I)}),
                ("meta", {"name": "generator", "content": re.compile(r"hubspot", re.I)}),
            ],
            "Ghost": [
                ("meta", {"name": "generator", "content": re.compile(r"ghost", re.I)}),
            ],
            "Duda": [
                ("script", {"src": re.compile(r"duda", re.I)}),
            ],
        }

        for cms_name, signatures in cms_signatures.items():
            for tag, attrs in signatures:
                if tag == "html":
                    # Check HTML tag attributes
                    html_tag = soup.find("html")
                    if html_tag:
                        for attr_name in attrs:
                            if html_tag.get(attr_name):
                                tech_stack["cms"].append({"name": cms_name, "confidence": "high"})
                                break
                else:
                    matches = soup.find_all(tag, attrs)
                    if matches:
                        tech_stack["cms"].append({"name": cms_name, "confidence": "high"})
                        break

        # String-based CMS detection as fallback
        if "wp-content" in html_lower and not any(c["name"] == "WordPress" for c in tech_stack["cms"]):
            tech_stack["cms"].append({"name": "WordPress", "confidence": "medium"})

        # ============================================================
        # Analytics Detection
        # ============================================================
        analytics_patterns = {
            "Google Analytics 4": [
                r"gtag\s*\(\s*['\"]config['\"]",
                r"googletagmanager\.com/gtag",
                r"G-[A-Z0-9]{10}",
            ],
            "Google Analytics (Universal)": [
                r"google-analytics\.com/analytics\.js",
                r"UA-\d{6,}-\d",
            ],
            "Google Tag Manager": [
                r"googletagmanager\.com/gtm\.js",
                r"GTM-[A-Z0-9]+",
            ],
            "Plausible": [
                r"plausible\.io/js",
            ],
            "Fathom": [
                r"usefathom\.com",
                r"cdn\.usefathom\.com",
            ],
            "Matomo": [
                r"matomo\.js",
                r"piwik\.js",
            ],
            "Hotjar": [
                r"static\.hotjar\.com",
                r"hotjar\.com",
            ],
            "Microsoft Clarity": [
                r"clarity\.ms",
            ],
            "Heap": [
                r"heap-\d+\.js",
                r"heapanalytics\.com",
            ],
            "Mixpanel": [
                r"mixpanel\.com",
                r"cdn\.mxpnl\.com",
            ],
            "Segment": [
                r"cdn\.segment\.com",
                r"api\.segment\.io",
            ],
            "Amplitude": [
                r"amplitude\.com",
                r"cdn\.amplitude\.com",
            ],
        }

        for analytics_name, patterns in analytics_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["analytics"].append({"name": analytics_name, "confidence": "high"})
                    break

        # ============================================================
        # Marketing Tools Detection
        # ============================================================
        marketing_patterns = {
            "HubSpot": [
                r"js\.hs-scripts\.com",
                r"js\.hsforms\.net",
                r"hbspt\.forms",
            ],
            "Mailchimp": [
                r"list-manage\.com",
                r"chimpstatic\.com",
            ],
            "ActiveCampaign": [
                r"trackcmp\.net",
                r"activehosted\.com",
            ],
            "Klaviyo": [
                r"klaviyo\.com",
                r"static\.klaviyo\.com",
            ],
            "ConvertKit": [
                r"convertkit\.com",
            ],
            "Constant Contact": [
                r"constantcontact\.com",
            ],
            "Salesforce": [
                r"force\.com",
                r"salesforce\.com",
            ],
            "Marketo": [
                r"marketo\.net",
                r"munchkin\.marketo\.net",
            ],
            "Pardot": [
                r"pardot\.com",
                r"pi\.pardot\.com",
            ],
            "Drip": [
                r"getdrip\.com",
            ],
            "SendGrid": [
                r"sendgrid\.net",
            ],
            "MailerLite": [
                r"mailerlite\.com",
            ],
        }

        for tool_name, patterns in marketing_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["marketing"].append({"name": tool_name, "confidence": "high"})
                    break

        # ============================================================
        # Advertising Detection
        # ============================================================
        advertising_patterns = {
            "Google Ads": [
                r"googleads\.g\.doubleclick\.net",
                r"googleadservices\.com",
                r"AW-\d+",
            ],
            "Facebook Pixel": [
                r"connect\.facebook\.net",
                r"fbq\s*\(\s*['\"]init['\"]",
                r"facebook\.com/tr",
            ],
            "LinkedIn Insight Tag": [
                r"snap\.licdn\.com",
                r"linkedin\.com/px",
            ],
            "Twitter Pixel": [
                r"static\.ads-twitter\.com",
                r"analytics\.twitter\.com",
            ],
            "Pinterest Tag": [
                r"pintrk\s*\(",
                r"ct\.pinterest\.com",
            ],
            "TikTok Pixel": [
                r"analytics\.tiktok\.com",
            ],
            "Microsoft Ads": [
                r"bat\.bing\.com",
            ],
            "Bing UET": [
                r"bat\.bing\.com/bat\.js",
            ],
            "Criteo": [
                r"static\.criteo\.net",
                r"dis\.criteo\.com",
            ],
            "AdRoll": [
                r"d\.adroll\.com",
            ],
            "Taboola": [
                r"cdn\.taboola\.com",
            ],
            "Outbrain": [
                r"outbrain\.com",
            ],
        }

        for ad_name, patterns in advertising_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["advertising"].append({"name": ad_name, "confidence": "high"})
                    break

        # ============================================================
        # A/B Testing Detection
        # ============================================================
        ab_testing_patterns = {
            "Google Optimize": [
                r"googleoptimize\.com",
                r"optimize\.google\.com",
            ],
            "Optimizely": [
                r"cdn\.optimizely\.com",
                r"optimizely\.com/js",
            ],
            "VWO": [
                r"dev\.visualwebsiteoptimizer\.com",
                r"vwo_\$",
            ],
            "AB Tasty": [
                r"abtasty\.com",
            ],
            "LaunchDarkly": [
                r"launchdarkly\.com",
            ],
            "Split.io": [
                r"split\.io",
            ],
            "Convert": [
                r"cdn\.convert\.com",
            ],
        }

        for tool_name, patterns in ab_testing_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["ab_testing"].append({"name": tool_name, "confidence": "high"})
                    break

        # ============================================================
        # CDN / Performance Detection
        # ============================================================
        cdn_patterns = {
            "Cloudflare": [
                r"cloudflare\.com",
                r"cdnjs\.cloudflare\.com",
                r"__cf_bm",  # Cloudflare bot management cookie
            ],
            "Fastly": [
                r"fastly\.net",
            ],
            "Akamai": [
                r"akamai\.net",
                r"akamaized\.net",
            ],
            "AWS CloudFront": [
                r"cloudfront\.net",
            ],
            "Netlify": [
                r"netlify\.app",
                r"netlify\.com",
            ],
            "Vercel": [
                r"vercel\.app",
                r"vercel\.com",
            ],
            "jsDelivr": [
                r"cdn\.jsdelivr\.net",
            ],
            "unpkg": [
                r"unpkg\.com",
            ],
        }

        for cdn_name, patterns in cdn_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["cdn_performance"].append({"name": cdn_name, "confidence": "high"})
                    break

        # ============================================================
        # JavaScript Frameworks Detection
        # ============================================================
        framework_patterns = {
            "React": [
                r"react\.production\.min\.js",
                r"react-dom",
                r"__REACT_DEVTOOLS_GLOBAL_HOOK__",
                r"data-reactroot",
            ],
            "Vue.js": [
                r"vue\.min\.js",
                r"vue@\d",
                r"__VUE__",
            ],
            "Angular": [
                r"angular\.min\.js",
                r"ng-version",
                r"ng-app",
            ],
            "Next.js": [
                r"_next/static",
                r"__NEXT_DATA__",
            ],
            "Nuxt.js": [
                r"/_nuxt/",
                r"__NUXT__",
            ],
            "jQuery": [
                r"jquery\.min\.js",
                r"jquery-\d",
                r"jquery/\d",
            ],
            "Bootstrap": [
                r"bootstrap\.min\.(js|css)",
                r"bootstrap@\d",
            ],
            "Tailwind CSS": [
                r"tailwindcss",
                r"tailwind\.min\.css",
            ],
            "Gatsby": [
                r"gatsby",
                r"___gatsby",
            ],
            "Svelte": [
                r"svelte",
            ],
            "Alpine.js": [
                r"alpine\.min\.js",
                r"alpinejs",
            ],
        }

        for framework_name, patterns in framework_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["frameworks"].append({"name": framework_name, "confidence": "high"})
                    break

        # ============================================================
        # E-commerce Detection
        # ============================================================
        ecommerce_patterns = {
            "Shopify": [
                r"cdn\.shopify\.com",
                r"myshopify\.com",
            ],
            "WooCommerce": [
                r"woocommerce",
                r"wc-add-to-cart",
            ],
            "BigCommerce": [
                r"bigcommerce\.com",
            ],
            "Magento": [
                r"magento",
                r"mage/",
            ],
            "PrestaShop": [
                r"prestashop",
            ],
            "Stripe": [
                r"js\.stripe\.com",
                r"stripe\.com/v3",
            ],
            "PayPal": [
                r"paypal\.com/sdk",
                r"paypalobjects\.com",
            ],
            "Square": [
                r"squareup\.com",
                r"square\.site",
            ],
        }

        for ecom_name, patterns in ecommerce_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["ecommerce"].append({"name": ecom_name, "confidence": "high"})
                    break

        # ============================================================
        # Chat / Support Detection
        # ============================================================
        chat_patterns = {
            "Intercom": [
                r"widget\.intercom\.io",
                r"intercomcdn\.com",
            ],
            "Zendesk": [
                r"zendesk\.com",
                r"zdassets\.com",
            ],
            "Drift": [
                r"js\.driftt\.com",
                r"drift\.com",
            ],
            "LiveChat": [
                r"livechatinc\.com",
            ],
            "Crisp": [
                r"crisp\.chat",
                r"client\.crisp\.chat",
            ],
            "Tawk.to": [
                r"tawk\.to",
                r"embed\.tawk\.to",
            ],
            "Freshchat": [
                r"wchat\.freshchat\.com",
            ],
            "HubSpot Chat": [
                r"js\.usemessages\.com",
            ],
            "Facebook Messenger": [
                r"facebook\.com/customer_chat",
            ],
        }

        for chat_name, patterns in chat_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["chat_support"].append({"name": chat_name, "confidence": "high"})
                    break

        # ============================================================
        # Form Tools Detection
        # ============================================================
        form_patterns = {
            "Typeform": [
                r"typeform\.com",
            ],
            "JotForm": [
                r"jotform\.com",
            ],
            "Gravity Forms": [
                r"gravityforms",
            ],
            "WPForms": [
                r"wpforms",
            ],
            "Ninja Forms": [
                r"ninja-forms",
            ],
            "Contact Form 7": [
                r"wpcf7",
            ],
            "Formstack": [
                r"formstack\.com",
            ],
            "Calendly": [
                r"calendly\.com",
                r"assets\.calendly\.com",
            ],
        }

        for form_name, patterns in form_patterns.items():
            for pattern in patterns:
                if re.search(pattern, html, re.I):
                    tech_stack["forms"].append({"name": form_name, "confidence": "high"})
                    break

        # ============================================================
        # Compile Summary
        # ============================================================
        # Remove duplicates within each category
        for category in tech_stack:
            seen = set()
            unique = []
            for item in tech_stack[category]:
                if item["name"] not in seen:
                    seen.add(item["name"])
                    unique.append(item)
            tech_stack[category] = unique

        # Add summary counts
        tech_stack["summary"] = {
            "total_technologies": sum(len(v) for v in tech_stack.values() if isinstance(v, list)),
            "categories_detected": [k for k, v in tech_stack.items() if isinstance(v, list) and len(v) > 0],
        }

        return tech_stack

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
                if re.search(pattern, path):
                    # Normalize URL (remove query strings)
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    pages.add(clean_url)
                    break

        return list(pages)[:self.max_pages_per_site - 1]  # Reserve 1 for homepage

    def _discover_pages_from_sitemap(
        self,
        domain: str,
        max_urls: int = None,
    ) -> List[Dict[str, Any]]:
        """
        Discover pages via sitemap instead of link following.

        This is more reliable for getting a complete picture of a site's
        structure, especially for larger sites.

        Args:
            domain: Domain to discover pages for
            max_urls: Maximum URLs to return (defaults to max_pages_per_site)

        Returns:
            List of URL dicts with metadata
        """
        max_urls = max_urls or self.max_pages_per_site

        try:
            sitemap_urls = self.sitemap_discovery.get_all_urls(
                domain,
                max_urls=max_urls,
                prioritize=True,
            )

            if not sitemap_urls:
                logger.info(f"No sitemap URLs found for {domain}, falling back to link discovery")
                return []

            # Convert to dict format
            return [
                {
                    "url": su.url,
                    "page_type": su.page_type,
                    "lastmod": su.lastmod,
                    "priority": su.priority,
                    "source": "sitemap",
                }
                for su in sitemap_urls
            ]

        except Exception as e:
            logger.warning(f"Sitemap discovery failed for {domain}: {e}")
            return []

    def _extract_internal_links(
        self,
        html: str,
        source_url: str,
        domain: str,
    ) -> List[InternalLink]:
        """
        Extract internal links with anchor text and position from HTML.

        Args:
            html: Page HTML
            source_url: URL of the source page
            domain: Domain for filtering internal links

        Returns:
            List of InternalLink objects
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        links = []

        # Define position markers
        nav_selectors = ['nav', 'header', '[role="navigation"]', '.nav', '.navbar', '.menu']
        footer_selectors = ['footer', '[role="contentinfo"]', '.footer']
        sidebar_selectors = ['aside', '.sidebar', '[role="complementary"]']

        def get_link_position(element) -> str:
            """Determine link position based on parent elements."""
            for parent in element.parents:
                # Check navigation
                for sel in nav_selectors:
                    if parent.name == sel.lstrip('.') or (parent.get('class') and sel.lstrip('.') in ' '.join(parent.get('class', []))):
                        return "nav"
                    if parent.get('role') == 'navigation':
                        return "nav"

                # Check footer
                for sel in footer_selectors:
                    if parent.name == 'footer':
                        return "footer"
                    if parent.get('role') == 'contentinfo':
                        return "footer"
                    if parent.get('class') and 'footer' in ' '.join(parent.get('class', [])):
                        return "footer"

                # Check sidebar
                for sel in sidebar_selectors:
                    if parent.name == 'aside':
                        return "sidebar"
                    if parent.get('role') == 'complementary':
                        return "sidebar"
                    if parent.get('class') and 'sidebar' in ' '.join(parent.get('class', [])):
                        return "sidebar"

                # Check header
                if parent.name == 'header':
                    return "header"

            return "body"

        def get_context_snippet(element, max_length: int = 100) -> Optional[str]:
            """Get surrounding text context for a link."""
            parent = element.find_parent(['p', 'li', 'td', 'div'])
            if parent:
                text = parent.get_text(strip=True)
                if len(text) > max_length:
                    text = text[:max_length] + "..."
                return text
            return None

        # Find all anchor tags
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')

            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue

            # Resolve relative URLs
            full_url = urljoin(source_url, href)
            parsed = urlparse(full_url)

            # Only internal links
            if domain not in parsed.netloc:
                continue

            # Normalize URL
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"

            # Skip self-links
            if clean_url == source_url:
                continue

            # Extract anchor text
            anchor_text = a_tag.get_text(strip=True)
            if not anchor_text:
                # Try img alt or title
                img = a_tag.find('img')
                if img:
                    anchor_text = img.get('alt', '') or img.get('title', '')
                if not anchor_text:
                    anchor_text = a_tag.get('title', '')

            # Get rel attributes
            rel_attrs = a_tag.get('rel', [])
            if isinstance(rel_attrs, str):
                rel_attrs = rel_attrs.split()

            # Determine position
            position = get_link_position(a_tag)

            # Get context
            context = None
            if position == "body":
                context = get_context_snippet(a_tag)

            links.append(InternalLink(
                source_url=source_url,
                target_url=clean_url,
                anchor_text=anchor_text[:200] if anchor_text else "",
                position=position,
                rel_attributes=rel_attrs,
                context_snippet=context,
            ))

        return links

    def build_link_graph(
        self,
        domain: str,
        pages: List[Dict[str, Any]],
        crawl_for_links: bool = False,
    ) -> InternalLinkGraph:
        """
        Build internal link graph for a competitor site.

        Args:
            domain: Domain being analyzed
            pages: List of pages with 'url' and optionally 'html'
            crawl_for_links: Whether to crawl pages to extract links

        Returns:
            InternalLinkGraph with all discovered links
        """
        graph = InternalLinkGraph(domain=domain)

        for page in pages:
            url = page.get('url')
            html = page.get('html')

            if not url:
                continue

            # If we have HTML, extract links
            if html:
                links = self._extract_internal_links(html, url, domain)
                for link in links:
                    graph.add_link(link)

        # Calculate page importance scores
        graph.calculate_page_scores()

        logger.info(f"Built link graph for {domain}: {len(graph.links)} links, "
                   f"{len(graph.page_scores)} unique pages")

        return graph

    def crawl_competitor_with_artifact(
        self,
        domain: str,
        website_url: Optional[str] = None,
        name: Optional[str] = None,
        business_type: Optional[str] = None,
        location: Optional[str] = None,
        save_artifact: bool = True,
        quality_profile: Optional['ScrapeQualityProfile'] = None,
    ) -> Tuple[Optional[Dict[str, Any]], List['PageArtifact']]:
        """
        Crawl a competitor with comprehensive artifact capture for each page.

        This method captures raw HTML, screenshots, console logs, and metadata
        for each page crawled, allowing offline re-parsing and analysis.

        Args:
            domain: Competitor domain
            website_url: Full URL (defaults to https://{domain})
            name: Business name
            business_type: Type of business
            location: Location
            save_artifact: Whether to save artifacts to disk
            quality_profile: Quality profile for artifact capture

        Returns:
            Tuple of (crawl results dict, list of PageArtifacts)
        """
        from seo_intelligence.models.artifacts import (
            PageArtifact,
            ScrapeQualityProfile,
            ArtifactStorage,
            HIGH_QUALITY_PROFILE,
            DEFAULT_QUALITY_PROFILE,
        )
        import time as time_module

        profile = quality_profile or DEFAULT_QUALITY_PROFILE
        artifacts = []
        storage = ArtifactStorage() if save_artifact else None

        website_url = website_url or f"https://{domain}"
        logger.info(f"Crawling competitor with artifact capture: {domain}")

        results = {
            "domain": domain,
            "pages_crawled": 0,
            "pages_failed": 0,
            "total_words": 0,
            "schema_types": set(),
            "tech_stack": None,
            "artifacts_captured": 0,
        }

        try:
            with self.browser_session(site="generic") as driver:
                # Configure viewport
                if profile.viewport_width and profile.viewport_height:
                    driver.set_window_size(profile.viewport_width, profile.viewport_height)

                # Crawl homepage first
                start_time = time_module.time()
                driver.get(website_url)

                # Wait based on profile
                if profile.wait_strategy == "networkidle":
                    time.sleep(3.0)
                else:
                    time.sleep(random.uniform(2.0, 4.0))

                # Extra wait if configured
                if profile.extra_wait_seconds > 0:
                    time.sleep(profile.extra_wait_seconds)

                # Scroll page if configured
                if profile.scroll_page:
                    for i in range(profile.scroll_steps):
                        driver.execute_script(f"window.scrollTo(0, {(i + 1) * 500})")
                        time.sleep(profile.scroll_delay)
                    # Scroll back to top
                    driver.execute_script("window.scrollTo(0, 0)")
                    time.sleep(0.5)

                html = driver.page_source
                final_url = driver.current_url
                fetch_duration = int((time_module.time() - start_time) * 1000)

                if not html:
                    logger.error(f"Failed to fetch homepage for {domain}")
                    return None, artifacts

                # Create homepage artifact
                homepage_artifact = PageArtifact(
                    url=website_url,
                    final_url=final_url,
                    status_code=200,
                    html_raw=html,
                    engine="seleniumbase",
                    fetch_duration_ms=fetch_duration,
                    quality_profile=profile.to_dict(),
                    viewport={"width": profile.viewport_width, "height": profile.viewport_height},
                    metadata={
                        "scraper": "competitor_crawler_selenium",
                        "domain": domain,
                        "page_type": "homepage",
                    }
                )

                # Capture screenshot if configured
                if profile.capture_screenshot:
                    try:
                        screenshot_path = f"/tmp/competitor_{homepage_artifact.url_hash}_homepage.png"
                        driver.save_screenshot(screenshot_path)
                        homepage_artifact.screenshot_path = screenshot_path
                    except Exception as e:
                        logger.debug(f"Screenshot capture failed: {e}")

                # Capture console logs if available
                if profile.capture_console:
                    try:
                        logs = driver.get_log('browser')
                        for log in logs:
                            if log.get('level') == 'SEVERE':
                                homepage_artifact.console_errors.append(log.get('message', ''))
                            elif log.get('level') == 'WARNING':
                                homepage_artifact.console_warnings.append(log.get('message', ''))
                    except Exception:
                        pass

                # Parse homepage
                metrics = self.parser.parse(html, website_url)

                # Detect technology stack
                try:
                    tech_stack = self._detect_tech_stack(html, website_url)
                    results["tech_stack"] = tech_stack
                    homepage_artifact.metadata["tech_stack_summary"] = tech_stack.get("summary", {})
                except Exception as e:
                    logger.warning(f"Failed to detect tech stack for {domain}: {e}")

                # Save homepage artifact
                if storage:
                    artifact_path = storage.save(homepage_artifact)
                    homepage_artifact.metadata['artifact_path'] = artifact_path

                artifacts.append(homepage_artifact)
                results["artifacts_captured"] += 1

                # Save homepage to database
                competitor_id = None
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
                        start_time = time_module.time()
                        driver.get(url)

                        # Wait based on profile
                        if profile.wait_strategy == "networkidle":
                            time.sleep(2.0)
                        else:
                            time.sleep(random.uniform(1.5, 3.0))

                        if profile.extra_wait_seconds > 0:
                            time.sleep(profile.extra_wait_seconds * 0.5)  # Shorter wait for subpages

                        page_html = driver.page_source
                        page_final_url = driver.current_url
                        page_fetch_duration = int((time_module.time() - start_time) * 1000)

                        if page_html:
                            page_metrics = self.parser.parse(page_html, url)

                            # Create artifact for this page
                            page_artifact = PageArtifact(
                                url=url,
                                final_url=page_final_url,
                                status_code=200,
                                html_raw=page_html,
                                engine="seleniumbase",
                                fetch_duration_ms=page_fetch_duration,
                                quality_profile=profile.to_dict(),
                                viewport={"width": profile.viewport_width, "height": profile.viewport_height},
                                metadata={
                                    "scraper": "competitor_crawler_selenium",
                                    "domain": domain,
                                    "page_type": page_metrics.page_type,
                                }
                            )

                            # Capture screenshot if configured
                            if profile.capture_screenshot:
                                try:
                                    screenshot_path = f"/tmp/competitor_{page_artifact.url_hash}.png"
                                    driver.save_screenshot(screenshot_path)
                                    page_artifact.screenshot_path = screenshot_path
                                except Exception:
                                    pass

                            # Save artifact
                            if storage:
                                artifact_path = storage.save(page_artifact)
                                page_artifact.metadata['artifact_path'] = artifact_path

                            artifacts.append(page_artifact)
                            results["artifacts_captured"] += 1

                            # Save to database
                            if self.engine and competitor_id:
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
                    f"Crawled {domain} with artifacts: {results['pages_crawled']} pages, "
                    f"{results['artifacts_captured']} artifacts, {results['total_words']} words"
                )

                return results, artifacts

        except Exception as e:
            logger.error(f"Error crawling competitor {domain}: {e}", exc_info=True)
            return None, artifacts

    def crawl_competitor_with_sitemap(
        self,
        domain: str,
        website_url: Optional[str] = None,
        name: Optional[str] = None,
        business_type: Optional[str] = None,
        location: Optional[str] = None,
        use_sitemap: bool = True,
        build_link_graph: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Crawl a competitor using sitemap-based discovery.

        This is the enhanced version that:
        1. Discovers pages via sitemap first
        2. Falls back to link discovery if no sitemap
        3. Builds internal link graph
        4. Uses smart prioritization

        Args:
            domain: Competitor domain
            website_url: Full URL (defaults to https://{domain})
            name: Business name
            business_type: Type of business
            location: Location
            use_sitemap: Whether to use sitemap discovery
            build_link_graph: Whether to build internal link graph

        Returns:
            dict: Enhanced crawl results with link graph
        """
        website_url = website_url or f"https://{domain}"
        logger.info(f"Crawling competitor (enhanced): {domain}")

        results = {
            "domain": domain,
            "pages_crawled": 0,
            "pages_failed": 0,
            "total_words": 0,
            "schema_types": set(),
            "sitemap_found": False,
            "link_graph": None,
            "discovery_method": "link_following",
            "tech_stack": None,
        }

        try:
            with self.browser_session(site="generic") as driver:
                # 1. Try sitemap discovery first
                sitemap_urls = []
                if use_sitemap:
                    sitemap_pages = self._discover_pages_from_sitemap(domain)
                    if sitemap_pages:
                        results["sitemap_found"] = True
                        results["discovery_method"] = "sitemap"
                        sitemap_urls = [p["url"] for p in sitemap_pages]
                        logger.info(f"Found {len(sitemap_urls)} URLs via sitemap for {domain}")

                # 2. Crawl homepage first
                driver.get(website_url)
                time.sleep(random.uniform(2.0, 4.0))
                html = driver.page_source

                if not html:
                    logger.error(f"Failed to fetch homepage for {domain}")
                    return None

                # Parse homepage
                metrics = self.parser.parse(html, website_url)

                # Detect technology stack from homepage (Phase 2.4)
                try:
                    tech_stack = self._detect_tech_stack(html, website_url)
                    results["tech_stack"] = tech_stack
                    logger.info(
                        f"Detected tech stack for {domain}: "
                        f"{tech_stack['summary']['total_technologies']} technologies in "
                        f"{len(tech_stack['summary']['categories_detected'])} categories"
                    )
                except Exception as e:
                    logger.warning(f"Failed to detect tech stack for {domain}: {e}")
                    results["tech_stack"] = None

                # Track pages with HTML for link graph
                pages_with_html = [{"url": website_url, "html": html}]

                # Save to database
                competitor_id = None
                if self.engine:
                    with Session(self.engine) as session:
                        competitor_id = self._get_or_create_competitor(
                            session, domain, name, website_url, business_type, location
                        )
                        self._save_page(session, competitor_id, metrics, html)

                results["pages_crawled"] += 1
                results["total_words"] += metrics.word_count
                results["schema_types"].update(metrics.schema_types)

                # 3. Determine which pages to crawl
                if sitemap_urls:
                    # Use sitemap URLs (excluding homepage)
                    additional_urls = [u for u in sitemap_urls if u != website_url][:self.max_pages_per_site - 1]
                else:
                    # Fall back to link discovery
                    additional_urls = self._discover_pages(website_url, html)

                logger.info(f"Crawling {len(additional_urls)} additional pages for {domain}")

                # 4. Crawl additional pages
                for url in additional_urls:
                    try:
                        driver.get(url)
                        time.sleep(random.uniform(1.5, 3.0))
                        page_html = driver.page_source

                        if page_html:
                            page_metrics = self.parser.parse(page_html, url)
                            pages_with_html.append({"url": url, "html": page_html})

                            if self.engine and competitor_id:
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

                # 5. Build internal link graph
                if build_link_graph and pages_with_html:
                    graph = self.build_link_graph(domain, pages_with_html)
                    results["link_graph"] = graph.to_dict()

                # Convert set to list for JSON serialization
                results["schema_types"] = list(results["schema_types"])

                logger.info(
                    f"Crawled {domain} (enhanced): {results['pages_crawled']} pages, "
                    f"{results['total_words']} words, "
                    f"discovery={results['discovery_method']}"
                )

                return results

        except Exception as e:
            logger.error(f"Error crawling competitor {domain}: {e}", exc_info=True)
            return None

    def crawl_competitor(
        self,
        domain: str,
        website_url: Optional[str] = None,
        name: Optional[str] = None,
        business_type: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Crawl a single competitor website using SeleniumBase UC.

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
            "tech_stack": None,
        }

        try:
            with self.browser_session(site="generic") as driver:
                # Crawl homepage first
                driver.get(website_url)

                # Wait for page load
                time.sleep(random.uniform(2.0, 4.0))

                html = driver.page_source

                if not html:
                    logger.error(f"Failed to fetch homepage for {domain}")
                    return None

                # Parse homepage
                metrics = self.parser.parse(html, website_url)

                # Detect technology stack from homepage (Phase 2.4)
                try:
                    tech_stack = self._detect_tech_stack(html, website_url)
                    results["tech_stack"] = tech_stack
                    logger.info(
                        f"Detected tech stack for {domain}: "
                        f"{tech_stack['summary']['total_technologies']} technologies"
                    )
                except Exception as e:
                    logger.warning(f"Failed to detect tech stack for {domain}: {e}")

                # Save to database
                competitor_id = None
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
                        # Navigate to additional page
                        driver.get(url)
                        time.sleep(random.uniform(1.5, 3.0))

                        page_html = driver.page_source

                        if page_html:
                            page_metrics = self.parser.parse(page_html, url)

                            if self.engine and competitor_id:
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

        with task_logger.log_task("competitor_crawler_selenium", "scraper", {"count": len(competitors)}) as task:
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
_competitor_crawler_selenium_instance = None


def get_competitor_crawler_selenium(**kwargs) -> CompetitorCrawlerSelenium:
    """Get or create the singleton CompetitorCrawlerSelenium instance."""
    global _competitor_crawler_selenium_instance

    if _competitor_crawler_selenium_instance is None:
        _competitor_crawler_selenium_instance = CompetitorCrawlerSelenium(**kwargs)

    return _competitor_crawler_selenium_instance
