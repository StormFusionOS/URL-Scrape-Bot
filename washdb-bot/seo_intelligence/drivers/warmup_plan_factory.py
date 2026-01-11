"""
Warmup Plan Factory

Generates randomized, tiered warmup plans for browser instances.
Ensures no two browser sessions follow the same warmup path.

Key responsibilities:
- Select randomized blueprints by weighted probability
- Sample URLs from tier pools without domain reuse
- Enforce tier-specific constraints
- Support both fresh warmup and re-warm scenarios
"""

import random
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Set
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
    is_url_blocked,
)

logger = logging.getLogger(__name__)


@dataclass
class WarmupStep:
    """A single step in a warmup plan."""
    url: str
    tier: WarmupTier
    tier_config: TierConfig
    subcategory: str

    # Randomized behavior parameters
    should_scroll: bool = False
    scroll_depth: float = 0.0
    should_click: bool = False
    dwell_time: float = 5.0

    def __str__(self) -> str:
        return f"[{self.tier.value}] {self.url} (dwell={self.dwell_time:.1f}s)"


@dataclass
class WarmupPlan:
    """Complete warmup plan for a browser session."""
    plan_id: str
    blueprint: List[str]
    steps: List[WarmupStep] = field(default_factory=list)
    is_rewarm: bool = False

    # Tracking
    domains_used: Set[str] = field(default_factory=set)
    total_dwell_time: float = 0.0

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = f"wp_{random.randint(10000, 99999)}"

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def tier_summary(self) -> str:
        """Get summary of tiers used."""
        tiers = [s.tier.value for s in self.steps]
        return "→".join(tiers)

    def __str__(self) -> str:
        return (
            f"WarmupPlan({self.plan_id}): {self.step_count} steps, "
            f"blueprint={self.tier_summary}, dwell={self.total_dwell_time:.1f}s"
        )


class WarmupPlanFactory:
    """
    Factory for creating randomized warmup plans.

    Usage:
        factory = WarmupPlanFactory()
        plan = factory.create_plan()
        # or for re-warm
        plan = factory.create_rewarm_plan()
    """

    def __init__(
        self,
        max_urls_per_session: int = 15,
        min_urls_per_session: int = 4,
        tier_c_probability: float = 0.35,
        enforce_no_domain_reuse: bool = True,
    ):
        """
        Initialize the factory.

        Args:
            max_urls_per_session: Maximum URLs in a single warmup
            min_urls_per_session: Minimum URLs in a single warmup
            tier_c_probability: Probability of including Tier C
            enforce_no_domain_reuse: Prevent same domain twice in session
        """
        self.max_urls = max_urls_per_session
        self.min_urls = min_urls_per_session
        self.tier_c_probability = tier_c_probability
        self.enforce_no_domain_reuse = enforce_no_domain_reuse

        # Pre-cache tier URL pools
        self._tier_pools = {
            tier: list(get_tier_urls(tier))
            for tier in [WarmupTier.S, WarmupTier.A, WarmupTier.B, WarmupTier.C]
        }

        logger.info(
            f"WarmupPlanFactory initialized: max={max_urls_per_session}, "
            f"tier_c_prob={tier_c_probability}"
        )

    def create_plan(self, session_id: Optional[str] = None) -> WarmupPlan:
        """
        Create a new warmup plan for a fresh browser session.

        Args:
            session_id: Optional session identifier for logging

        Returns:
            WarmupPlan with randomized steps
        """
        # Select blueprint
        blueprint = self._select_blueprint(is_rewarm=False)

        # Check if we should skip Tier C
        if "C" in blueprint and random.random() > self.tier_c_probability:
            blueprint = [t for t in blueprint if t != "C"]

        plan = WarmupPlan(
            plan_id=session_id or f"wp_{random.randint(10000, 99999)}",
            blueprint=blueprint,
            is_rewarm=False,
        )

        # Generate steps for each tier in blueprint
        for tier_letter in blueprint:
            tier = WarmupTier(tier_letter)
            config = get_tier_config(tier)

            # Should we even use this tier?
            if random.random() > config.session_usage_probability:
                continue

            # How many URLs from this tier?
            url_count = random.randint(config.min_urls, config.max_urls)
            url_count = min(url_count, config.max_per_session)

            # Check plan limits
            remaining_capacity = self.max_urls - plan.step_count
            if remaining_capacity <= 0:
                break
            url_count = min(url_count, remaining_capacity)

            # Sample URLs
            urls = self._sample_urls(tier, url_count, plan.domains_used)

            for url, subcategory in urls:
                step = self._create_step(url, tier, config, subcategory)
                plan.steps.append(step)
                plan.total_dwell_time += step.dwell_time

                # Track domain
                domain = self._extract_domain(url)
                plan.domains_used.add(domain)

        # Validate minimum
        if plan.step_count < self.min_urls:
            # Add more from Tier A (safest additional tier)
            additional_needed = self.min_urls - plan.step_count
            tier = WarmupTier.A
            config = get_tier_config(tier)
            urls = self._sample_urls(tier, additional_needed, plan.domains_used)

            for url, subcategory in urls:
                step = self._create_step(url, tier, config, subcategory)
                plan.steps.append(step)
                plan.total_dwell_time += step.dwell_time
                plan.domains_used.add(self._extract_domain(url))

        # Shuffle to avoid predictable tier ordering
        if len(plan.steps) > 2:
            # Keep first step (always Tier S if present), shuffle rest
            first_step = plan.steps[0] if plan.steps[0].tier == WarmupTier.S else None
            if first_step:
                rest = plan.steps[1:]
                random.shuffle(rest)
                plan.steps = [first_step] + rest
            else:
                random.shuffle(plan.steps)

        logger.info(f"Created warmup plan: {plan}")
        return plan

    def create_rewarm_plan(self, session_id: Optional[str] = None) -> WarmupPlan:
        """
        Create a shortened re-warm plan for an idle browser.

        Re-warm plans:
        - Use shorter blueprints
        - Never include Tier C
        - Faster dwell times

        Args:
            session_id: Optional session identifier

        Returns:
            WarmupPlan for re-warming
        """
        blueprint = self._select_blueprint(is_rewarm=True)

        plan = WarmupPlan(
            plan_id=session_id or f"rw_{random.randint(10000, 99999)}",
            blueprint=blueprint,
            is_rewarm=True,
        )

        for tier_letter in blueprint:
            tier = WarmupTier(tier_letter)
            config = get_tier_config(tier)

            # Fewer URLs for re-warm (1-2 per tier)
            url_count = random.randint(1, 2)

            urls = self._sample_urls(tier, url_count, plan.domains_used)

            for url, subcategory in urls:
                step = self._create_step(url, tier, config, subcategory)
                # Reduce dwell time for re-warm
                step.dwell_time = step.dwell_time * 0.6
                plan.steps.append(step)
                plan.total_dwell_time += step.dwell_time
                plan.domains_used.add(self._extract_domain(url))

        logger.info(f"Created re-warm plan: {plan}")
        return plan

    def _select_blueprint(self, is_rewarm: bool = False) -> List[str]:
        """Select a blueprint by weighted random choice."""
        if is_rewarm:
            blueprints = REWARM_BLUEPRINTS
            weights = REWARM_BLUEPRINT_WEIGHTS
        else:
            blueprints = WARMUP_BLUEPRINTS
            weights = BLUEPRINT_WEIGHTS

        return random.choices(blueprints, weights=weights, k=1)[0].copy()

    def _sample_urls(
        self,
        tier: WarmupTier,
        count: int,
        excluded_domains: Set[str],
    ) -> List[Tuple[str, str]]:
        """
        Sample URLs from a tier pool.

        Args:
            tier: The tier to sample from
            count: Number of URLs to sample
            excluded_domains: Domains to avoid (already used)

        Returns:
            List of (url, subcategory) tuples
        """
        pool = self._tier_pools.get(tier, [])

        if not pool:
            logger.warning(f"Empty URL pool for tier {tier.value}")
            return []

        # Filter out excluded domains
        if self.enforce_no_domain_reuse:
            available = [
                (url, cat) for url, cat in pool
                if self._extract_domain(url) not in excluded_domains
            ]
        else:
            available = pool

        if not available:
            logger.warning(f"No available URLs for tier {tier.value} after exclusions")
            return []

        # Random sample
        count = min(count, len(available))
        return random.sample(available, count)

    def _create_step(
        self,
        url: str,
        tier: WarmupTier,
        config: TierConfig,
        subcategory: str,
    ) -> WarmupStep:
        """Create a warmup step with randomized behavior parameters."""
        # Determine if we scroll
        should_scroll = random.random() < config.scroll_probability
        scroll_depth = 0.0
        if should_scroll:
            scroll_depth = random.uniform(
                config.scroll_depth_min,
                config.scroll_depth_max
            )

        # Determine if we click
        should_click = random.random() < config.click_probability

        # Randomize dwell time
        dwell_time = random.uniform(
            config.dwell_time_min,
            config.dwell_time_max
        )

        return WarmupStep(
            url=url,
            tier=tier,
            tier_config=config,
            subcategory=subcategory,
            should_scroll=should_scroll,
            scroll_depth=scroll_depth,
            should_click=should_click,
            dwell_time=dwell_time,
        )

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for deduplication."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www prefix for matching
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return url


# =============================================================================
# FACTORY SINGLETON
# =============================================================================

_factory_instance: Optional[WarmupPlanFactory] = None


def get_warmup_plan_factory(**kwargs) -> WarmupPlanFactory:
    """Get or create the warmup plan factory singleton."""
    global _factory_instance
    if _factory_instance is None:
        _factory_instance = WarmupPlanFactory(**kwargs)
    return _factory_instance


def create_warmup_plan(session_id: Optional[str] = None) -> WarmupPlan:
    """Convenience function to create a warmup plan."""
    factory = get_warmup_plan_factory()
    return factory.create_plan(session_id)


def create_rewarm_plan(session_id: Optional[str] = None) -> WarmupPlan:
    """Convenience function to create a re-warm plan."""
    factory = get_warmup_plan_factory()
    return factory.create_rewarm_plan(session_id)


# =============================================================================
# PLAN VALIDATION
# =============================================================================

def validate_plan(plan: WarmupPlan) -> Tuple[bool, List[str]]:
    """
    Validate a warmup plan for safety and correctness.

    Returns:
        (is_valid, list_of_issues)
    """
    issues = []

    # Check minimum steps
    if plan.step_count < 2:
        issues.append(f"Plan has only {plan.step_count} steps (minimum 2)")

    # Check for blocked URLs
    for step in plan.steps:
        if is_url_blocked(step.url):
            issues.append(f"Blocked URL in plan: {step.url}")

    # Check domain reuse
    domains_seen = set()
    for step in plan.steps:
        domain = urlparse(step.url).netloc.lower()
        if domain in domains_seen:
            issues.append(f"Domain reuse detected: {domain}")
        domains_seen.add(domain)

    # Check Tier C usage
    tier_c_count = sum(1 for s in plan.steps if s.tier == WarmupTier.C)
    if tier_c_count > 2:
        issues.append(f"Too many Tier C URLs: {tier_c_count} (max 2)")

    # Check total dwell time (sanity check)
    if plan.total_dwell_time > 300:  # 5 minutes max
        issues.append(f"Total dwell time too high: {plan.total_dwell_time:.1f}s")

    is_valid = len(issues) == 0
    return is_valid, issues
