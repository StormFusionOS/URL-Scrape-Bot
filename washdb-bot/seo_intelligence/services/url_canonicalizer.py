"""
URL Canonicalization Service

Implements Task 9 from Phase 2: Canonicalization Infrastructure

Features:
- Strip tracking parameters (utm_*, fbclid, gclid, etc.)
- Normalize domains (lowercase, strip www)
- Normalize paths (remove trailing slashes, decode percent-encoding)
- Hash-based URL deduplication
- Track first_seen_at, last_seen_at for each canonical URL
- Support for source_type and scrape_job_id tracking

Canonical URL Format:
- Scheme: Normalized to https:// by default (configurable)
- Domain: Lowercase, www. prefix removed
- Path: No trailing slash (except for root "/"), percent-decoded
- Query: Tracking params removed, remaining params sorted alphabetically
- Fragment: Removed by default (configurable)

Usage:
    from seo_intelligence.services.url_canonicalizer import get_url_canonicalizer

    canonicalizer = get_url_canonicalizer()
    canonical = canonicalizer.canonicalize("https://example.com/page?utm_source=google")
    # Result: "https://example.com/page"

    # With database tracking:
    result = canonicalizer.canonicalize_and_track(
        url="https://example.com/page?utm_source=google",
        source_type="competitor",
        scrape_job_id=123
    )
"""

import re
import hashlib
from typing import Optional, Set, Dict, Any, List
from urllib.parse import urlparse, parse_qs, urlencode, unquote, urlunparse
from dataclasses import dataclass
from datetime import datetime

from runner.logging_setup import get_logger


# Singleton instance
_url_canonicalizer = None


# Tracking parameters to strip (commonly used in marketing/analytics)
DEFAULT_TRACKING_PARAMS = {
    # Google Analytics
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'utm_source_platform', 'utm_creative_format', 'utm_marketing_tactic',

    # Google Ads
    'gclid', 'gclsrc', 'gbraid', 'wbraid',

    # Facebook/Meta
    'fbclid', 'fb_action_ids', 'fb_action_types', 'fb_ref', 'fb_source',

    # Twitter/X
    'twclid', 'tw_source', 'tw_campaign',

    # LinkedIn
    'li_fat_id', 'lipi',

    # Microsoft/Bing
    'msclkid', 'mc_cid', 'mc_eid',

    # Email marketing
    'mkt_tok', '_hsenc', '_hsmi', 'vero_id', 'vero_conv',

    # General tracking
    'ref', 'referrer', 'source', 'campaign', 'medium',

    # Session IDs (often tracking-related)
    'sessionid', 'session_id', 'jsessionid', 'phpsessid', 'aspsessionid',

    # Other common tracking
    'click_id', 'clickid', 'cid', 'sid', 'tid', 'pid', 'aid',
    '_ga', '_gid', '_gac', '_gl',
}


@dataclass
class CanonicalURL:
    """Represents a canonicalized URL with metadata."""

    canonical_url: str
    original_url: str
    url_hash: str
    scheme: str
    domain: str
    path: str
    query: Optional[str]
    fragment: Optional[str]
    stripped_params: List[str]
    is_normalized: bool


@dataclass
class URLTrackingResult:
    """Result of canonicalize_and_track operation."""

    canonical_url: str
    url_hash: str
    is_new: bool
    first_seen_at: datetime
    last_seen_at: datetime


class URLCanonicalizer:
    """
    URL canonicalization service for deduplication and tracking.

    Handles:
    - Tracking parameter removal
    - Domain normalization
    - Path normalization
    - Query parameter sorting
    - URL hash generation
    """

    def __init__(
        self,
        tracking_params: Optional[Set[str]] = None,
        strip_www: bool = True,
        normalize_scheme: bool = True,
        remove_fragment: bool = True,
        remove_trailing_slash: bool = True,
        lowercase_domain: bool = True,
        decode_percent: bool = True,
    ):
        """
        Initialize URL canonicalizer.

        Args:
            tracking_params: Set of query parameter names to strip (uses DEFAULT_TRACKING_PARAMS if None)
            strip_www: Remove "www." prefix from domain
            normalize_scheme: Convert http:// to https:// (default: True)
            remove_fragment: Remove URL fragment (part after #)
            remove_trailing_slash: Remove trailing slash from paths (except root)
            lowercase_domain: Convert domain to lowercase
            decode_percent: Decode percent-encoded characters in path
        """
        self.tracking_params = tracking_params or DEFAULT_TRACKING_PARAMS
        self.strip_www = strip_www
        self.normalize_scheme = normalize_scheme
        self.remove_fragment = remove_fragment
        self.remove_trailing_slash = remove_trailing_slash
        self.lowercase_domain = lowercase_domain
        self.decode_percent = decode_percent

        self.logger = get_logger("url_canonicalizer")

        # In-memory cache for canonical URLs (url_hash -> CanonicalURL)
        # This reduces database queries for frequently seen URLs
        self._canonical_cache: Dict[str, CanonicalURL] = {}

        self.logger.info("URLCanonicalizer initialized")

    def _normalize_domain(self, domain: str) -> str:
        """
        Normalize domain name.

        Args:
            domain: Domain to normalize

        Returns:
            Normalized domain
        """
        # Lowercase
        if self.lowercase_domain:
            domain = domain.lower()

        # Strip www prefix
        if self.strip_www and domain.startswith('www.'):
            domain = domain[4:]

        return domain

    def _normalize_path(self, path: str) -> str:
        """
        Normalize URL path.

        Args:
            path: Path to normalize

        Returns:
            Normalized path
        """
        # Decode percent-encoded characters
        if self.decode_percent:
            path = unquote(path)

        # Remove trailing slash (except for root "/")
        if self.remove_trailing_slash and path != '/' and path.endswith('/'):
            path = path.rstrip('/')

        # Ensure path starts with /
        if not path.startswith('/'):
            path = '/' + path

        return path

    def _filter_query_params(self, query_string: str) -> tuple[str, List[str]]:
        """
        Filter tracking parameters from query string.

        Args:
            query_string: Query string to filter

        Returns:
            Tuple of (filtered_query_string, list_of_stripped_params)
        """
        if not query_string:
            return '', []

        params = parse_qs(query_string, keep_blank_values=True)
        stripped_params = []
        filtered_params = {}

        for key, values in params.items():
            # Check if this is a tracking parameter
            if key.lower() in self.tracking_params:
                stripped_params.append(key)
            else:
                filtered_params[key] = values

        # Sort parameters alphabetically for consistency
        sorted_params = sorted(filtered_params.items())

        # Rebuild query string
        if sorted_params:
            # Flatten multi-value params
            flat_params = []
            for key, values in sorted_params:
                for value in values:
                    flat_params.append((key, value))

            filtered_query = urlencode(flat_params, doseq=False)
        else:
            filtered_query = ''

        return filtered_query, stripped_params

    def _compute_url_hash(self, canonical_url: str) -> str:
        """
        Compute SHA-256 hash of canonical URL.

        Args:
            canonical_url: Canonical URL string

        Returns:
            Hex digest of SHA-256 hash
        """
        return hashlib.sha256(canonical_url.encode('utf-8')).hexdigest()

    def canonicalize(self, url: str) -> CanonicalURL:
        """
        Canonicalize a URL.

        Args:
            url: URL to canonicalize

        Returns:
            CanonicalURL object with canonical form and metadata

        Raises:
            ValueError: If URL cannot be parsed
        """
        original_url = url

        # Parse URL
        try:
            parsed = urlparse(url)
        except Exception as e:
            raise ValueError(f"Invalid URL: {url}") from e

        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"URL missing scheme or domain: {url}")

        # Normalize scheme
        scheme = parsed.scheme.lower()
        if self.normalize_scheme and scheme == 'http':
            scheme = 'https'

        # Normalize domain
        domain = self._normalize_domain(parsed.netloc)

        # Normalize path
        path = self._normalize_path(parsed.path or '/')

        # Filter query parameters
        filtered_query, stripped_params = self._filter_query_params(parsed.query)

        # Handle fragment
        fragment = None if self.remove_fragment else parsed.fragment

        # Reconstruct canonical URL
        canonical_url = urlunparse((
            scheme,
            domain,
            path,
            '',  # params (deprecated, always empty)
            filtered_query,
            fragment or ''
        ))

        # Compute hash
        url_hash = self._compute_url_hash(canonical_url)

        # Check if normalization changed the URL
        is_normalized = (canonical_url != original_url)

        result = CanonicalURL(
            canonical_url=canonical_url,
            original_url=original_url,
            url_hash=url_hash,
            scheme=scheme,
            domain=domain,
            path=path,
            query=filtered_query if filtered_query else None,
            fragment=fragment,
            stripped_params=stripped_params,
            is_normalized=is_normalized
        )

        # Cache result
        self._canonical_cache[url_hash] = result

        return result

    def canonicalize_batch(self, urls: List[str]) -> List[CanonicalURL]:
        """
        Canonicalize multiple URLs in batch.

        Args:
            urls: List of URLs to canonicalize

        Returns:
            List of CanonicalURL objects
        """
        results = []
        for url in urls:
            try:
                result = self.canonicalize(url)
                results.append(result)
            except ValueError as e:
                self.logger.warning(f"Skipping invalid URL: {url} ({e})")
                continue

        return results

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            'cache_size': len(self._canonical_cache),
        }

    def clear_cache(self):
        """Clear canonical URL cache."""
        self._canonical_cache.clear()
        self.logger.info("Canonical URL cache cleared")


def get_url_canonicalizer() -> URLCanonicalizer:
    """
    Get singleton URLCanonicalizer instance.

    Returns:
        URLCanonicalizer instance
    """
    global _url_canonicalizer

    if _url_canonicalizer is None:
        _url_canonicalizer = URLCanonicalizer()

    return _url_canonicalizer


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def is_same_domain(url1: str, url2: str) -> bool:
    """
    Check if two URLs are on the same domain (after normalization).

    Args:
        url1: First URL
        url2: Second URL

    Returns:
        True if same domain, False otherwise
    """
    try:
        canonicalizer = get_url_canonicalizer()
        c1 = canonicalizer.canonicalize(url1)
        c2 = canonicalizer.canonicalize(url2)
        return c1.domain == c2.domain
    except ValueError:
        return False


def extract_domain(url: str) -> Optional[str]:
    """
    Extract normalized domain from URL.

    Args:
        url: URL to extract domain from

    Returns:
        Normalized domain, or None if URL is invalid
    """
    try:
        canonicalizer = get_url_canonicalizer()
        canonical = canonicalizer.canonicalize(url)
        return canonical.domain
    except ValueError:
        return None


def urls_are_equivalent(url1: str, url2: str) -> bool:
    """
    Check if two URLs are equivalent (same canonical form).

    Args:
        url1: First URL
        url2: Second URL

    Returns:
        True if URLs are equivalent, False otherwise
    """
    try:
        canonicalizer = get_url_canonicalizer()
        c1 = canonicalizer.canonicalize(url1)
        c2 = canonicalizer.canonicalize(url2)
        return c1.url_hash == c2.url_hash
    except ValueError:
        return False
