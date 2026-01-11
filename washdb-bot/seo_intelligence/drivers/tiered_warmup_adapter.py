"""
Tiered Warmup Adapter

Bridges the enterprise tiered warmup system with the existing Selenium-based browser pool.
Provides warmup URL selection in the format expected by browser_pool.py.

This adapter:
- Generates tier-sequenced URLs following blueprints
- Provides dwell times and behavior hints per tier
- Tracks domain usage to prevent duplicates
- Integrates with the reputation tracker
"""

import random
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Set, Optional
from urllib.parse import urlparse

from seo_intelligence.drivers.tiered_warmup_urls import (
    WarmupTier,
    TierConfig,
    TIER_CONFIGS,
    TIER_URLS,
    WARMUP_BLUEPRINTS,
    BLUEPRINT_WEIGHTS,
    REWARM_BLUEPRINTS,
    REWARM_BLUEPRINT_WEIGHTS,
    get_tier_config,
    get_tier_urls,
)

logger = logging.getLogger(__name__)


@dataclass
class TieredWarmupURL:
    """A warmup URL with tier-specific configuration."""
    url: str
    tier: WarmupTier
    min_wait: float
    max_wait: float
    category: str

    # Behavior hints
    scroll_probability: float = 0.0
    scroll_depth_min: float = 0.0
    scroll_depth_max: float = 0.0
    click_probability: float = 0.0

    def as_tuple(self) -> Tuple[str, float, float, str]:
        """Return in browser_pool.py expected format."""
        return (self.url, self.min_wait, self.max_wait, self.category)


class TieredWarmupAdapter:
    """
    Adapter to generate tiered warmup URLs for Selenium-based browser pool.

    Usage:
        adapter = TieredWarmupAdapter()
        urls = adapter.get_warmup_urls(count=8)
        # Returns list of (url, min_wait, max_wait, category) tuples
    """

    def __init__(
        self,
        tier_c_probability: float = 0.35,
        enforce_no_domain_reuse: bool = True,
    ):
        self.tier_c_probability = tier_c_probability
        self.enforce_no_domain_reuse = enforce_no_domain_reuse

        # Pre-cache tier URL pools
        self._tier_pools = {
            tier: list(get_tier_urls(tier))
            for tier in [WarmupTier.S, WarmupTier.A, WarmupTier.B, WarmupTier.C]
        }

    def get_warmup_urls(
        self,
        count: int = 8,
        is_rewarm: bool = False,
        excluded_domains: Optional[Set[str]] = None,
    ) -> List[Tuple[str, float, float, str]]:
        """
        Generate tiered warmup URLs for browser pool.

        Args:
            count: Target number of URLs
            is_rewarm: Use shorter re-warm blueprints
            excluded_domains: Domains to skip

        Returns:
            List of (url, min_wait, max_wait, category) tuples
        """
        if excluded_domains is None:
            excluded_domains = set()

        # Select blueprint
        blueprint = self._select_blueprint(is_rewarm)

        # Maybe skip Tier C
        if "C" in blueprint and random.random() > self.tier_c_probability:
            blueprint = [t for t in blueprint if t != "C"]

        urls = []
        domains_used = set(excluded_domains)

        for tier_letter in blueprint:
            tier = WarmupTier(tier_letter)
            config = get_tier_config(tier)

            # Check tier usage probability
            if random.random() > config.session_usage_probability:
                continue

            # How many from this tier?
            tier_count = random.randint(config.min_urls, config.max_urls)
            tier_count = min(tier_count, count - len(urls))

            if tier_count <= 0:
                continue

            # Sample URLs from this tier
            tier_urls = self._sample_tier_urls(tier, tier_count, domains_used)

            for url_data in tier_urls:
                url, subcategory = url_data
                domain = self._extract_domain(url)

                # Create tiered URL with proper wait times
                tiered_url = TieredWarmupURL(
                    url=url,
                    tier=tier,
                    min_wait=config.dwell_time_min,
                    max_wait=config.dwell_time_max,
                    category=f"{tier.value}_{subcategory}",
                    scroll_probability=config.scroll_probability,
                    scroll_depth_min=config.scroll_depth_min,
                    scroll_depth_max=config.scroll_depth_max,
                    click_probability=config.click_probability,
                )

                urls.append(tiered_url.as_tuple())
                domains_used.add(domain)

            if len(urls) >= count:
                break

        # If we don't have enough, pad with Tier A
        while len(urls) < count:
            tier = WarmupTier.A
            config = get_tier_config(tier)
            tier_urls = self._sample_tier_urls(tier, 1, domains_used)

            for url_data in tier_urls:
                url, subcategory = url_data
                urls.append((
                    url,
                    config.dwell_time_min,
                    config.dwell_time_max,
                    f"A_{subcategory}"
                ))
                domains_used.add(self._extract_domain(url))

            if not tier_urls:
                break  # No more available

        logger.info(
            f"Generated {len(urls)} tiered warmup URLs: "
            f"blueprint={'→'.join(blueprint)}"
        )

        return urls

    def get_tiered_url_objects(
        self,
        count: int = 8,
        is_rewarm: bool = False,
    ) -> List[TieredWarmupURL]:
        """
        Get warmup URLs as TieredWarmupURL objects (with full behavior hints).

        Args:
            count: Target number of URLs
            is_rewarm: Use shorter re-warm blueprints

        Returns:
            List of TieredWarmupURL objects
        """
        blueprint = self._select_blueprint(is_rewarm)

        if "C" in blueprint and random.random() > self.tier_c_probability:
            blueprint = [t for t in blueprint if t != "C"]

        urls = []
        domains_used = set()

        for tier_letter in blueprint:
            tier = WarmupTier(tier_letter)
            config = get_tier_config(tier)

            if random.random() > config.session_usage_probability:
                continue

            tier_count = random.randint(config.min_urls, config.max_urls)
            tier_count = min(tier_count, count - len(urls))

            if tier_count <= 0:
                continue

            tier_urls = self._sample_tier_urls(tier, tier_count, domains_used)

            for url_data in tier_urls:
                url, subcategory = url_data

                tiered_url = TieredWarmupURL(
                    url=url,
                    tier=tier,
                    min_wait=config.dwell_time_min,
                    max_wait=config.dwell_time_max,
                    category=f"{tier.value}_{subcategory}",
                    scroll_probability=config.scroll_probability,
                    scroll_depth_min=config.scroll_depth_min,
                    scroll_depth_max=config.scroll_depth_max,
                    click_probability=config.click_probability,
                )

                urls.append(tiered_url)
                domains_used.add(self._extract_domain(url))

            if len(urls) >= count:
                break

        return urls

    def _select_blueprint(self, is_rewarm: bool) -> List[str]:
        """Select a warmup blueprint by weighted probability."""
        if is_rewarm:
            blueprints = REWARM_BLUEPRINTS
            weights = REWARM_BLUEPRINT_WEIGHTS
        else:
            blueprints = WARMUP_BLUEPRINTS
            weights = BLUEPRINT_WEIGHTS

        return random.choices(blueprints, weights=weights, k=1)[0].copy()

    def _sample_tier_urls(
        self,
        tier: WarmupTier,
        count: int,
        excluded_domains: Set[str],
    ) -> List[Tuple[str, str]]:
        """Sample URLs from a tier pool without domain reuse."""
        pool = self._tier_pools.get(tier, [])

        if not pool:
            return []

        # Filter excluded domains
        if self.enforce_no_domain_reuse:
            available = [
                (url, cat) for url, cat in pool
                if self._extract_domain(url) not in excluded_domains
            ]
        else:
            available = pool

        if not available:
            return []

        count = min(count, len(available))
        return random.sample(available, count)

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return url


# =============================================================================
# LEGACY FORMAT ADAPTERS
# =============================================================================

def get_tiered_warmup_urls_legacy(
    count: int = 8,
    is_rewarm: bool = False,
) -> List[Tuple[str, int, int, str]]:
    """
    Get tiered warmup URLs in legacy browser_pool format.

    This is the drop-in replacement for the old warmup URL lists.

    Args:
        count: Number of URLs to generate
        is_rewarm: Use re-warm blueprints

    Returns:
        List of (url, min_wait, max_wait, category) tuples
    """
    adapter = TieredWarmupAdapter()
    return adapter.get_warmup_urls(count=count, is_rewarm=is_rewarm)


def generate_target_group_warmup_urls(target_group: str) -> List[Tuple[str, int, int, str]]:
    """
    Generate warmup URLs optimized for a specific target group.

    Args:
        target_group: "search_engines", "directories", or "general"

    Returns:
        List of warmup URL tuples
    """
    adapter = TieredWarmupAdapter()

    if target_group == "search_engines":
        # Search engines need more warmup, avoid Tier C (search engines themselves)
        adapter.tier_c_probability = 0.15
        return adapter.get_warmup_urls(count=10, is_rewarm=False)

    elif target_group == "directories":
        # Directories benefit from local/consumer context
        adapter.tier_c_probability = 0.25
        return adapter.get_warmup_urls(count=8, is_rewarm=False)

    else:  # general
        return adapter.get_warmup_urls(count=6, is_rewarm=False)


# =============================================================================
# TIERED URL POOLS FOR POOL_MODELS.PY COMPATIBILITY
# =============================================================================
# These replace the old WARMUP_HIGH_TRAFFIC_SITES etc.

def get_tier_s_urls_legacy() -> List[Tuple[str, int, int, str]]:
    """Get Tier S URLs in legacy format."""
    tier = WarmupTier.S
    config = get_tier_config(tier)
    return [
        (url, int(config.dwell_time_min), int(config.dwell_time_max), f"S_{cat}")
        for url, cat in get_tier_urls(tier)
    ]


def get_tier_a_urls_legacy() -> List[Tuple[str, int, int, str]]:
    """Get Tier A URLs in legacy format."""
    tier = WarmupTier.A
    config = get_tier_config(tier)
    return [
        (url, int(config.dwell_time_min), int(config.dwell_time_max), f"A_{cat}")
        for url, cat in get_tier_urls(tier)
    ]


def get_tier_b_urls_legacy() -> List[Tuple[str, int, int, str]]:
    """Get Tier B URLs in legacy format."""
    tier = WarmupTier.B
    config = get_tier_config(tier)
    return [
        (url, int(config.dwell_time_min), int(config.dwell_time_max), f"B_{cat}")
        for url, cat in get_tier_urls(tier)
    ]


def get_safe_warmup_urls() -> List[Tuple[str, int, int, str]]:
    """
    Get a safe-first ordered list of warmup URLs.

    This is the recommended replacement for ALL_WARMUP_URLS.
    URLs are ordered: Tier S first, then A, then B.
    Tier C is excluded from this default list.
    """
    return (
        get_tier_s_urls_legacy() +
        get_tier_a_urls_legacy() +
        get_tier_b_urls_legacy()
    )
