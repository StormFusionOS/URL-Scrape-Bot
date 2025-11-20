"""
URL seeding for competitor crawling.

Discovers URLs from multiple sources:
- Sitemap.xml parsing
- RSS/Atom feed parsing
- Homepage link extraction
"""
import logging
import xml.etree.ElementTree as ET
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup

from ..infrastructure.http_client import get_with_retry

logger = logging.getLogger(__name__)


class URLSeeder:
    """
    Discovers URLs from competitor sites for crawling.

    Features:
    - Sitemap.xml parsing (with sitemap index support)
    - RSS/Atom feed parsing
    - Homepage link extraction
    - URL deduplication and filtering
    """

    def __init__(self, max_urls: int = 1000):
        """
        Initialize URL seeder.

        Args:
            max_urls: Maximum URLs to discover per source (default: 1000)
        """
        self.max_urls = max_urls

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by removing fragments and trailing slashes."""
        parsed = urlparse(url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        # Remove trailing slash except for root
        if normalized.endswith('/') and len(parsed.path) > 1:
            normalized = normalized[:-1]
        return normalized

    def discover_from_sitemap(
        self,
        sitemap_url: str,
        max_depth: int = 2
    ) -> Set[str]:
        """
        Discover URLs from sitemap.xml.

        Args:
            sitemap_url: URL to sitemap.xml
            max_depth: Maximum depth for sitemap index recursion (default: 2)

        Returns:
            Set of discovered URLs
        """
        urls = set()

        try:
            logger.info(f"Fetching sitemap: {sitemap_url}")
            response = get_with_retry(sitemap_url, check_robots=False)

            if not response or response.status_code != 200:
                logger.warning(f"Failed to fetch sitemap: {sitemap_url}")
                return urls

            # Parse XML
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as e:
                logger.error(f"Invalid XML in sitemap {sitemap_url}: {e}")
                return urls

            # Get namespace
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            # Check if this is a sitemap index
            sitemap_tags = root.findall('.//sm:sitemap', ns)
            if sitemap_tags and max_depth > 0:
                logger.info(f"Found sitemap index with {len(sitemap_tags)} sitemaps")
                # Recursively fetch sub-sitemaps
                for sitemap_tag in sitemap_tags[:self.max_urls]:
                    loc = sitemap_tag.find('sm:loc', ns)
                    if loc is not None and loc.text:
                        sub_urls = self.discover_from_sitemap(
                            loc.text,
                            max_depth=max_depth - 1
                        )
                        urls.update(sub_urls)

                        if len(urls) >= self.max_urls:
                            break
            else:
                # Parse URL entries
                url_tags = root.findall('.//sm:url', ns)
                logger.info(f"Found {len(url_tags)} URLs in sitemap")

                for url_tag in url_tags[:self.max_urls]:
                    loc = url_tag.find('sm:loc', ns)
                    if loc is not None and loc.text:
                        normalized = self._normalize_url(loc.text)
                        urls.add(normalized)

            logger.info(f"Discovered {len(urls)} URLs from sitemap")
            return urls

        except Exception as e:
            logger.error(f"Error discovering URLs from sitemap {sitemap_url}: {e}")
            return urls

    def discover_from_rss(self, rss_url: str) -> Set[str]:
        """
        Discover URLs from RSS/Atom feed.

        Args:
            rss_url: URL to RSS/Atom feed

        Returns:
            Set of discovered URLs
        """
        urls = set()

        try:
            logger.info(f"Fetching RSS feed: {rss_url}")
            response = get_with_retry(rss_url, check_robots=False)

            if not response or response.status_code != 200:
                logger.warning(f"Failed to fetch RSS feed: {rss_url}")
                return urls

            # Parse feed using feedparser
            feed = feedparser.parse(response.content)

            if not feed.entries:
                logger.warning(f"No entries found in feed: {rss_url}")
                return urls

            logger.info(f"Found {len(feed.entries)} entries in feed")

            for entry in feed.entries[:self.max_urls]:
                # Get link from entry
                if hasattr(entry, 'link'):
                    normalized = self._normalize_url(entry.link)
                    urls.add(normalized)

            logger.info(f"Discovered {len(urls)} URLs from RSS feed")
            return urls

        except Exception as e:
            logger.error(f"Error discovering URLs from RSS {rss_url}: {e}")
            return urls

    def discover_from_homepage(
        self,
        homepage_url: str,
        same_domain_only: bool = True
    ) -> Set[str]:
        """
        Discover URLs from homepage links.

        Args:
            homepage_url: Homepage URL
            same_domain_only: Only return links to same domain (default: True)

        Returns:
            Set of discovered URLs
        """
        urls = set()

        try:
            logger.info(f"Fetching homepage: {homepage_url}")
            response = get_with_retry(homepage_url)

            if not response or response.status_code != 200:
                logger.warning(f"Failed to fetch homepage: {homepage_url}")
                return urls

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract domain for filtering
            homepage_domain = urlparse(homepage_url).netloc

            # Find all links
            for link in soup.find_all('a', href=True):
                href = link['href']

                # Resolve relative URLs
                absolute_url = urljoin(homepage_url, href)

                # Filter by domain if requested
                if same_domain_only:
                    link_domain = urlparse(absolute_url).netloc
                    if link_domain != homepage_domain:
                        continue

                # Skip non-HTTP links
                if not absolute_url.startswith(('http://', 'https://')):
                    continue

                normalized = self._normalize_url(absolute_url)
                urls.add(normalized)

                if len(urls) >= self.max_urls:
                    break

            logger.info(f"Discovered {len(urls)} URLs from homepage")
            return urls

        except Exception as e:
            logger.error(f"Error discovering URLs from homepage {homepage_url}: {e}")
            return urls

    def discover_all(
        self,
        base_url: str,
        try_sitemap: bool = True,
        try_rss: bool = True,
        try_homepage: bool = True
    ) -> Set[str]:
        """
        Discover URLs from all available sources.

        Args:
            base_url: Base URL of competitor site
            try_sitemap: Try sitemap.xml discovery (default: True)
            try_rss: Try RSS feed discovery (default: True)
            try_homepage: Try homepage link extraction (default: True)

        Returns:
            Set of all discovered URLs
        """
        all_urls = set()

        # Ensure base_url has scheme
        if not base_url.startswith(('http://', 'https://')):
            base_url = f'https://{base_url}'

        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        logger.info(f"Discovering URLs for: {domain}")

        # Try sitemap.xml
        if try_sitemap:
            sitemap_urls = [
                f"{domain}/sitemap.xml",
                f"{domain}/sitemap_index.xml",
                f"{domain}/sitemap-index.xml",
                f"{domain}/post-sitemap.xml"
            ]

            for sitemap_url in sitemap_urls:
                urls = self.discover_from_sitemap(sitemap_url)
                if urls:
                    all_urls.update(urls)
                    break  # Stop after first successful sitemap

        # Try RSS feeds
        if try_rss:
            rss_urls = [
                f"{domain}/feed",
                f"{domain}/feed/",
                f"{domain}/rss",
                f"{domain}/rss.xml",
                f"{domain}/atom.xml"
            ]

            for rss_url in rss_urls:
                urls = self.discover_from_rss(rss_url)
                if urls:
                    all_urls.update(urls)
                    break  # Stop after first successful feed

        # Try homepage links
        if try_homepage:
            urls = self.discover_from_homepage(domain)
            all_urls.update(urls)

        logger.info(f"Total discovered URLs for {domain}: {len(all_urls)}")

        return all_urls
