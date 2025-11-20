"""
On-page signal parser for competitor analysis.

Extracts SEO-relevant signals from HTML:
- Meta tags (title, description, keywords, Open Graph, Twitter Cards)
- H1/H2/H3 headers
- Schema.org structured data (JSON-LD, microdata)
- Images (src, alt)
- Videos (embeds)
- Links (classified)
"""
import json
import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class PageParser:
    """
    Parses HTML to extract on-page SEO signals.

    Features:
    - Meta tag extraction (standard, OG, Twitter)
    - Header hierarchy (H1-H6)
    - Schema.org JSON-LD and microdata
    - Image and video inventory
    - Link extraction and classification
    """

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize page parser.

        Args:
            base_url: Base URL for resolving relative links (optional)
        """
        self.base_url = base_url

    def _resolve_url(self, url: str) -> str:
        """Resolve relative URL to absolute."""
        if self.base_url and not url.startswith(('http://', 'https://', '//')):
            return urljoin(self.base_url, url)
        return url

    def parse_meta_tags(self, soup: BeautifulSoup) -> Dict:
        """
        Extract all meta tags.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Dict with meta tag data
        """
        meta_data = {
            'title': '',
            'description': '',
            'keywords': '',
            'canonical': '',
            'robots': '',
            'og': {},
            'twitter': {},
            'other': {}
        }

        try:
            # Title
            title_tag = soup.find('title')
            if title_tag:
                meta_data['title'] = title_tag.get_text(strip=True)

            # Standard meta tags
            for meta in soup.find_all('meta'):
                name = meta.get('name', '').lower()
                property_attr = meta.get('property', '').lower()
                content = meta.get('content', '')

                # Description
                if name == 'description':
                    meta_data['description'] = content

                # Keywords
                elif name == 'keywords':
                    meta_data['keywords'] = content

                # Robots
                elif name == 'robots':
                    meta_data['robots'] = content

                # Open Graph
                elif property_attr.startswith('og:'):
                    key = property_attr.replace('og:', '')
                    meta_data['og'][key] = content

                # Twitter Cards
                elif name.startswith('twitter:'):
                    key = name.replace('twitter:', '')
                    meta_data['twitter'][key] = content

                # Other named meta tags
                elif name and content:
                    meta_data['other'][name] = content

            # Canonical link
            canonical = soup.find('link', rel='canonical')
            if canonical and canonical.get('href'):
                meta_data['canonical'] = self._resolve_url(canonical['href'])

            logger.debug(f"Extracted meta tags: title={meta_data['title'][:50]}...")
            return meta_data

        except Exception as e:
            logger.error(f"Error parsing meta tags: {e}")
            return meta_data

    def parse_headers(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """
        Extract header hierarchy (H1-H6).

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Dict with header levels (h1, h2, h3, etc.)
        """
        headers = {
            'h1': [],
            'h2': [],
            'h3': [],
            'h4': [],
            'h5': [],
            'h6': []
        }

        try:
            for level in range(1, 7):
                tag_name = f'h{level}'
                for header in soup.find_all(tag_name):
                    text = header.get_text(strip=True)
                    if text:
                        headers[tag_name].append(text)

            logger.debug(
                f"Extracted headers: {len(headers['h1'])} H1, "
                f"{len(headers['h2'])} H2, {len(headers['h3'])} H3"
            )
            return headers

        except Exception as e:
            logger.error(f"Error parsing headers: {e}")
            return headers

    def parse_schema_jsonld(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Extract Schema.org JSON-LD structured data.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            List of schema objects
        """
        schema_data = []

        try:
            # Find all JSON-LD scripts
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    json_text = script.string
                    if json_text:
                        # Parse JSON
                        data = json.loads(json_text)

                        # Handle @graph format (array of schemas)
                        if isinstance(data, dict) and '@graph' in data:
                            schema_data.extend(data['@graph'])
                        elif isinstance(data, list):
                            schema_data.extend(data)
                        else:
                            schema_data.append(data)

                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON-LD: {e}")
                    continue

            logger.debug(f"Extracted {len(schema_data)} schema objects")
            return schema_data

        except Exception as e:
            logger.error(f"Error parsing schema JSON-LD: {e}")
            return schema_data

    def parse_images(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Extract image inventory.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            List of image dicts with src, alt, title
        """
        images = []

        try:
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if src:
                    images.append({
                        'src': self._resolve_url(src),
                        'alt': img.get('alt', ''),
                        'title': img.get('title', '')
                    })

            logger.debug(f"Extracted {len(images)} images")
            return images

        except Exception as e:
            logger.error(f"Error parsing images: {e}")
            return images

    def parse_videos(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Extract video embeds.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            List of video dicts with src, type
        """
        videos = []

        try:
            # HTML5 video tags
            for video in soup.find_all('video'):
                src = video.get('src', '')
                if not src:
                    # Check for source child
                    source = video.find('source')
                    if source:
                        src = source.get('src', '')

                if src:
                    videos.append({
                        'src': self._resolve_url(src),
                        'type': 'html5',
                        'poster': video.get('poster', '')
                    })

            # YouTube embeds
            for iframe in soup.find_all('iframe'):
                src = iframe.get('src', '')
                if 'youtube.com' in src or 'youtu.be' in src:
                    videos.append({
                        'src': src,
                        'type': 'youtube'
                    })
                elif 'vimeo.com' in src:
                    videos.append({
                        'src': src,
                        'type': 'vimeo'
                    })

            logger.debug(f"Extracted {len(videos)} videos")
            return videos

        except Exception as e:
            logger.error(f"Error parsing videos: {e}")
            return videos

    def parse_links(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Extract and classify links.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            List of link dicts with url, text, rel, nofollow
        """
        links = []

        try:
            for link in soup.find_all('a', href=True):
                href = link['href']
                absolute_url = self._resolve_url(href)

                # Parse rel attribute
                rel = link.get('rel', [])
                if isinstance(rel, str):
                    rel = [rel]

                # Determine if nofollow
                nofollow = 'nofollow' in rel

                # Get link text
                text = link.get_text(strip=True)

                links.append({
                    'url': absolute_url,
                    'text': text,
                    'rel': rel,
                    'nofollow': nofollow
                })

            logger.debug(f"Extracted {len(links)} links")
            return links

        except Exception as e:
            logger.error(f"Error parsing links: {e}")
            return links

    def parse_all(self, html: str, base_url: Optional[str] = None) -> Dict:
        """
        Parse all on-page signals.

        Args:
            html: Raw HTML content
            base_url: Base URL for resolving relative links (optional)

        Returns:
            Dict with all parsed data
        """
        if base_url:
            self.base_url = base_url

        soup = BeautifulSoup(html, 'html.parser')

        logger.info("Parsing on-page signals...")

        data = {
            'meta': self.parse_meta_tags(soup),
            'headers': self.parse_headers(soup),
            'schema': self.parse_schema_jsonld(soup),
            'images': self.parse_images(soup),
            'videos': self.parse_videos(soup),
            'links': self.parse_links(soup)
        }

        logger.info(
            f"Parsing complete: {len(data['headers']['h1'])} H1s, "
            f"{len(data['schema'])} schemas, {len(data['images'])} images, "
            f"{len(data['links'])} links"
        )

        return data
