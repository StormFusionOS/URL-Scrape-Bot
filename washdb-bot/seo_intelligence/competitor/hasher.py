"""
DOM hashing for change detection.

Computes content hashes to detect when competitor pages have been updated.
Uses SHA-256 hashing of normalized page content (HTML with whitespace normalized).
"""
import hashlib
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class PageHasher:
    """
    Computes content hashes for change detection.

    Features:
    - SHA-256 hashing of normalized content
    - Removes dynamic elements (timestamps, ads, comments)
    - Whitespace normalization
    - Configurable exclusion patterns
    """

    def __init__(
        self,
        exclude_selectors: Optional[list] = None,
        exclude_attributes: Optional[list] = None
    ):
        """
        Initialize page hasher.

        Args:
            exclude_selectors: CSS selectors to exclude from hash (e.g., ['.ads', '#comments'])
            exclude_attributes: HTML attributes to exclude (e.g., ['data-timestamp', 'data-ad-id'])
        """
        self.exclude_selectors = exclude_selectors or [
            '.ad',
            '.ads',
            '.advertisement',
            '#comments',
            '.comments',
            '.social-share',
            '.timestamp',
            'script',
            'style',
            'noscript'
        ]

        self.exclude_attributes = exclude_attributes or [
            'data-timestamp',
            'data-ad-id',
            'data-tracking-id',
            'data-nonce'
        ]

    def _normalize_html(self, html: str, remove_excluded: bool = True) -> str:
        """
        Normalize HTML for consistent hashing.

        Args:
            html: Raw HTML content
            remove_excluded: Whether to remove excluded elements (default: True)

        Returns:
            Normalized HTML string
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Remove excluded elements
        if remove_excluded:
            for selector in self.exclude_selectors:
                for elem in soup.select(selector):
                    elem.decompose()

        # Remove excluded attributes
        for tag in soup.find_all(True):
            for attr in self.exclude_attributes:
                if attr in tag.attrs:
                    del tag.attrs[attr]

        # Get text representation
        text = soup.get_text(separator=' ', strip=True)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    def hash_content(
        self,
        html: str,
        algorithm: str = 'sha256',
        normalize: bool = True
    ) -> str:
        """
        Compute hash of page content.

        Args:
            html: Raw HTML content
            algorithm: Hash algorithm (default: sha256)
            normalize: Whether to normalize HTML before hashing (default: True)

        Returns:
            Hex digest of content hash
        """
        try:
            # Normalize if requested
            if normalize:
                content = self._normalize_html(html)
            else:
                content = html

            # Compute hash
            if algorithm == 'sha256':
                hasher = hashlib.sha256()
            elif algorithm == 'md5':
                hasher = hashlib.md5()
            elif algorithm == 'sha1':
                hasher = hashlib.sha1()
            else:
                raise ValueError(f"Unsupported hash algorithm: {algorithm}")

            hasher.update(content.encode('utf-8'))
            hash_value = hasher.hexdigest()

            logger.debug(f"Computed {algorithm} hash: {hash_value[:16]}...")
            return hash_value

        except Exception as e:
            logger.error(f"Error computing hash: {e}")
            raise

    def hash_sections(self, html: str) -> dict:
        """
        Compute hashes of different page sections.

        Args:
            html: Raw HTML content

        Returns:
            Dict with section hashes (head, body, main_content)
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')

            hashes = {}

            # Hash head section
            head = soup.find('head')
            if head:
                head_content = self._normalize_html(str(head))
                hashes['head'] = hashlib.sha256(head_content.encode('utf-8')).hexdigest()

            # Hash body section
            body = soup.find('body')
            if body:
                body_content = self._normalize_html(str(body))
                hashes['body'] = hashlib.sha256(body_content.encode('utf-8')).hexdigest()

            # Hash main content (article, main, or largest content div)
            main_content = soup.find('main') or soup.find('article')
            if main_content:
                main_text = self._normalize_html(str(main_content))
                hashes['main_content'] = hashlib.sha256(main_text.encode('utf-8')).hexdigest()

            return hashes

        except Exception as e:
            logger.error(f"Error computing section hashes: {e}")
            return {}

    def has_changed(
        self,
        html: str,
        previous_hash: str,
        algorithm: str = 'sha256'
    ) -> bool:
        """
        Check if page content has changed.

        Args:
            html: Current HTML content
            previous_hash: Previous content hash
            algorithm: Hash algorithm (default: sha256)

        Returns:
            True if content has changed, False otherwise
        """
        current_hash = self.hash_content(html, algorithm=algorithm)
        changed = current_hash != previous_hash

        if changed:
            logger.info(
                f"Content changed: {previous_hash[:16]}... -> {current_hash[:16]}..."
            )
        else:
            logger.debug("Content unchanged")

        return changed


# Global hasher instance
page_hasher = PageHasher()


# Convenience functions
def hash_content(html: str, algorithm: str = 'sha256') -> str:
    """Compute hash of page content."""
    return page_hasher.hash_content(html, algorithm=algorithm)


def hash_sections(html: str) -> dict:
    """Compute hashes of different page sections."""
    return page_hasher.hash_sections(html)


def has_changed(html: str, previous_hash: str, algorithm: str = 'sha256') -> bool:
    """Check if page content has changed."""
    return page_hasher.has_changed(html, previous_hash, algorithm=algorithm)
