"""
Content Hasher Service

Provides SHA-256 hashing for change detection in scraped content.

Features:
- Hash HTML content for change detection
- DOM normalization to ignore non-content changes
- Configurable normalization strategies
- Hash comparison and change detection

Per SCRAPING_NOTES.md:
- "Use SHA-256 hashing to detect content changes"
- "Normalize DOM before hashing to avoid false positives from dynamic elements"
- "Store hashes in competitor_pages.content_hash and serp_snapshots.snapshot_hash"
"""

import hashlib
import re
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup, Comment

from runner.logging_setup import get_logger

# Initialize logger
logger = get_logger("content_hasher")


class ContentHasher:
    """
    Service for hashing HTML content with DOM normalization.

    Normalizes HTML before hashing to avoid false positives from:
    - Dynamic timestamps
    - Session IDs
    - Analytics scripts
    - Cookie banners
    - Ads
    """

    def __init__(
        self,
        normalize: bool = True,
        remove_scripts: bool = True,
        remove_styles: bool = True,
        remove_comments: bool = True,
        remove_dynamic_attrs: bool = True
    ):
        """
        Initialize content hasher.

        Args:
            normalize: Whether to normalize HTML before hashing
            remove_scripts: Remove <script> tags
            remove_styles: Remove <style> tags
            remove_comments: Remove HTML comments
            remove_dynamic_attrs: Remove dynamic attributes (data-*, aria-*, etc.)
        """
        self.normalize = normalize
        self.remove_scripts = remove_scripts
        self.remove_styles = remove_styles
        self.remove_comments = remove_comments
        self.remove_dynamic_attrs = remove_dynamic_attrs

        logger.info(
            f"ContentHasher initialized: "
            f"normalize={normalize}, "
            f"remove_scripts={remove_scripts}, "
            f"remove_styles={remove_styles}"
        )

    def _normalize_html(self, html: str) -> str:
        """
        Normalize HTML to remove dynamic/non-content elements.

        Args:
            html: Raw HTML string

        Returns:
            str: Normalized HTML
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Remove comments
            if self.remove_comments:
                for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                    comment.extract()

            # Remove script tags
            if self.remove_scripts:
                for script in soup.find_all('script'):
                    script.decompose()

            # Remove style tags
            if self.remove_styles:
                for style in soup.find_all('style'):
                    style.decompose()

            # Remove dynamic attributes
            if self.remove_dynamic_attrs:
                # List of dynamic attributes to remove
                dynamic_attrs = [
                    'data-', 'aria-', 'ng-', 'v-',  # Framework attributes
                    'style',  # Inline styles (often dynamic)
                    'class',  # Classes can change dynamically
                    'id',  # IDs can be generated
                ]

                for tag in soup.find_all(True):
                    attrs_to_remove = []
                    for attr in tag.attrs:
                        # Remove if matches any dynamic prefix
                        if any(attr.startswith(prefix) for prefix in dynamic_attrs):
                            attrs_to_remove.append(attr)

                    for attr in attrs_to_remove:
                        del tag[attr]

            # Remove common ad containers
            ad_selectors = [
                {'class': re.compile(r'ad|advertisement|banner|sponsored', re.I)},
                {'id': re.compile(r'ad|advertisement|banner|sponsored', re.I)},
            ]

            for selector in ad_selectors:
                for ad_elem in soup.find_all(attrs=selector):
                    ad_elem.decompose()

            # Get text content only (removes most dynamic elements)
            normalized = soup.get_text(separator=' ', strip=True)

            # Normalize whitespace
            normalized = re.sub(r'\s+', ' ', normalized).strip()

            logger.debug(f"Normalized HTML: {len(html)} -> {len(normalized)} chars")
            return normalized

        except Exception as e:
            logger.error(f"Error normalizing HTML: {e}", exc_info=True)
            # Fall back to raw HTML
            return html

    def hash_content(self, content: str, normalize: Optional[bool] = None) -> str:
        """
        Generate SHA-256 hash of content.

        Args:
            content: Content to hash (HTML, text, etc.)
            normalize: Override instance normalization setting (default: None = use instance setting)

        Returns:
            str: SHA-256 hash (64 hex characters)
        """
        if normalize is None:
            normalize = self.normalize

        # Normalize if enabled
        if normalize and content:
            content = self._normalize_html(content)

        # Generate SHA-256 hash
        hash_obj = hashlib.sha256(content.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()

        logger.debug(f"Generated hash: {hash_hex[:16]}... (from {len(content)} chars)")
        return hash_hex

    def hash_dict(self, data: Dict[str, Any]) -> str:
        """
        Generate SHA-256 hash of a dictionary (for structured data).

        Args:
            data: Dictionary to hash

        Returns:
            str: SHA-256 hash (64 hex characters)
        """
        import json

        # Convert dict to sorted JSON string for consistent hashing
        json_str = json.dumps(data, sort_keys=True)

        # Generate SHA-256 hash
        hash_obj = hashlib.sha256(json_str.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()

        logger.debug(f"Generated dict hash: {hash_hex[:16]}...")
        return hash_hex

    def compare_hashes(self, hash1: str, hash2: str) -> bool:
        """
        Compare two hashes for equality.

        Args:
            hash1: First hash
            hash2: Second hash

        Returns:
            bool: True if hashes match, False otherwise
        """
        match = hash1 == hash2
        logger.debug(f"Hash comparison: {hash1[:8]}... vs {hash2[:8]}... = {'MATCH' if match else 'DIFFERENT'}")
        return match

    def has_changed(self, old_content: str, new_content: str, normalize: Optional[bool] = None) -> bool:
        """
        Check if content has changed by comparing hashes.

        Args:
            old_content: Previous content
            new_content: Current content
            normalize: Override instance normalization setting

        Returns:
            bool: True if content changed, False if same
        """
        old_hash = self.hash_content(old_content, normalize)
        new_hash = self.hash_content(new_content, normalize)

        changed = old_hash != new_hash

        if changed:
            logger.info(f"Content CHANGED: {old_hash[:8]}... -> {new_hash[:8]}...")
        else:
            logger.debug(f"Content UNCHANGED: {old_hash[:8]}...")

        return changed

    def get_content_signature(self, html: str) -> Dict[str, Any]:
        """
        Get comprehensive content signature including hash and metadata.

        Args:
            html: HTML content

        Returns:
            dict: Signature with hash, length, normalized length, etc.
        """
        raw_hash = self.hash_content(html, normalize=False)
        normalized_hash = self.hash_content(html, normalize=True)
        normalized_content = self._normalize_html(html) if self.normalize else html

        return {
            'raw_hash': raw_hash,
            'normalized_hash': normalized_hash,
            'raw_length': len(html),
            'normalized_length': len(normalized_content),
            'hash_algorithm': 'sha256',
        }


# Module-level singleton
_content_hasher_instance = None


def get_content_hasher() -> ContentHasher:
    """Get or create the singleton ContentHasher instance."""
    global _content_hasher_instance

    if _content_hasher_instance is None:
        _content_hasher_instance = ContentHasher()

    return _content_hasher_instance


def main():
    """Demo: Test content hashing."""
    logger.info("=" * 60)
    logger.info("Content Hasher Demo")
    logger.info("=" * 60)
    logger.info("")

    hasher = get_content_hasher()

    # Test 1: Hash simple content
    logger.info("Test 1: Hash simple content")
    content1 = "<html><body><h1>Hello World</h1><p>This is a test.</p></body></html>"
    hash1 = hasher.hash_content(content1)
    logger.info(f"  Content: {content1[:50]}...")
    logger.info(f"  Hash: {hash1}")
    logger.info("")

    # Test 2: Hash with dynamic elements
    logger.info("Test 2: Hash with dynamic elements (should normalize)")
    content2 = """
    <html>
    <head>
        <script>console.log('dynamic');</script>
        <style>.test { color: red; }</style>
    </head>
    <body>
        <h1>Hello World</h1>
        <p>This is a test.</p>
        <!-- Comment -->
        <div data-timestamp="123456789">Dynamic timestamp</div>
    </body>
    </html>
    """
    hash2_normalized = hasher.hash_content(content2, normalize=True)
    hash2_raw = hasher.hash_content(content2, normalize=False)
    logger.info(f"  Normalized hash: {hash2_normalized}")
    logger.info(f"  Raw hash: {hash2_raw}")
    logger.info(f"  Hashes match (should be True): {hash1 == hash2_normalized}")
    logger.info("")

    # Test 3: Change detection
    logger.info("Test 3: Change detection")
    old_content = "<html><body><h1>Version 1</h1></body></html>"
    new_content = "<html><body><h1>Version 2</h1></body></html>"
    changed = hasher.has_changed(old_content, new_content)
    logger.info(f"  Old: {old_content}")
    logger.info(f"  New: {new_content}")
    logger.info(f"  Changed: {changed}")
    logger.info("")

    # Test 4: No change with dynamic elements
    logger.info("Test 4: No change detection with dynamic elements")
    old_dynamic = '<html><body><h1>Test</h1><script>var t=123;</script></body></html>'
    new_dynamic = '<html><body><h1>Test</h1><script>var t=456;</script></body></html>'
    changed = hasher.has_changed(old_dynamic, new_dynamic, normalize=True)
    logger.info(f"  Changed (normalized): {changed} (should be False)")
    logger.info("")

    # Test 5: Content signature
    logger.info("Test 5: Content signature")
    signature = hasher.get_content_signature(content2)
    logger.info(f"  Raw hash: {signature['raw_hash'][:16]}...")
    logger.info(f"  Normalized hash: {signature['normalized_hash'][:16]}...")
    logger.info(f"  Raw length: {signature['raw_length']} chars")
    logger.info(f"  Normalized length: {signature['normalized_length']} chars")
    logger.info("")

    # Test 6: Dictionary hashing
    logger.info("Test 6: Dictionary hashing")
    data1 = {'name': 'Test', 'value': 123, 'items': ['a', 'b', 'c']}
    data2 = {'value': 123, 'name': 'Test', 'items': ['a', 'b', 'c']}  # Same data, different order
    hash_d1 = hasher.hash_dict(data1)
    hash_d2 = hasher.hash_dict(data2)
    logger.info(f"  Dict 1 hash: {hash_d1[:16]}...")
    logger.info(f"  Dict 2 hash: {hash_d2[:16]}...")
    logger.info(f"  Hashes match (should be True): {hash_d1 == hash_d2}")
    logger.info("")

    logger.info("=" * 60)
    logger.info("Demo complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
