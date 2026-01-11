"""
Browser Pool Data Models

Data classes and enums for the Enterprise Browser Pool system.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class SessionState(Enum):
    """Browser session states in the lifecycle."""
    COLD = "cold"              # Browser not started
    WARMING = "warming"         # Executing warm plan
    IDLE_WARM = "idle_warm"     # Ready for lease, warm
    LEASED = "leased"           # Currently in use
    RETURNING = "returning"     # Lease released, cleanup pending
    CLEANING = "cleaning"       # Context cleanup in progress
    QUARANTINED = "quarantined" # CAPTCHA/block detected
    DEAD = "dead"               # Crashed or failed


class BrowserType(Enum):
    """Browser types supported by the pool."""
    SELENIUM_UC = "selenium_uc"             # SeleniumBase Undetected Chrome
    SELENIUM_UC_FRESH = "selenium_uc_fresh" # UC with fresh profile
    CAMOUFOX = "camoufox"                   # Camoufox Firefox
    CAMOUFOX_NEW_FP = "camoufox_new_fp"     # Camoufox with new fingerprint


class RecycleAction(Enum):
    """Actions for session recycling."""
    NONE = "none"                 # No action needed
    REWARM = "rewarm"             # Re-execute warm plan
    SOFT_RECYCLE = "soft_recycle" # Clear cookies/cache, keep browser
    HARD_RECYCLE = "hard_recycle" # Close browser, start fresh
    QUARANTINE = "quarantine"     # Mark as quarantined


@dataclass
class TargetGroupConfig:
    """Configuration for a target group's warm plan and recycling."""
    name: str                                    # "search_engines", "directories", "general"
    domains: List[str]                           # Domains in this group ("*" for catch-all)

    # Pool size
    min_sessions: int = 2                        # Minimum warm sessions
    max_sessions: int = 5                        # Maximum sessions

    # Warm plan
    warmup_urls: List[Tuple[str, int, int]] = field(default_factory=list)  # (url, min_wait, max_wait)
    warmup_actions: List[str] = field(default_factory=lambda: ["scroll_down", "wait_random"])
    warmup_frequency_seconds: int = 1800         # Re-warm interval (30 min default)

    # Recycling policies
    session_ttl_minutes: int = 120               # Max session lifetime
    idle_ttl_minutes: int = 20                   # Max idle time before re-warm
    navigation_cap: int = 200                    # Max navigations before recycle

    # Rate limiting
    tier: str = "C"                              # Rate limiter tier
    min_delay_seconds: float = 8.0
    max_delay_seconds: float = 15.0


# =============================================================================
# TIERED WARMUP URL SYSTEM (Enterprise-Grade)
# =============================================================================
# URLs are organized by bot detection risk level:
# - Tier S: Ultra-safe infrastructure sites (first in sequence)
# - Tier A: Editorial/news sites (moderate, good for reading behavior)
# - Tier B: Consumer/retail sites (heavier JS, manageable)
# - Tier C: High-signal bot-aware sites (use sparingly, <35% of sessions)
# - Tier D: Never use (auth, finance, identity)
#
# The tiered system ensures warmup starts with safe sites before
# progressing to more detection-heavy sites.
# =============================================================================

from seo_intelligence.drivers.tiered_warmup_adapter import (
    get_tier_s_urls_legacy,
    get_tier_a_urls_legacy,
    get_tier_b_urls_legacy,
    get_safe_warmup_urls,
    get_tiered_warmup_urls_legacy,
    generate_target_group_warmup_urls,
    TieredWarmupAdapter,
)

# Tier S - Ultra-safe infrastructure sites (foundations, standards bodies, tech docs)
# These sites have minimal bot detection and build baseline legitimacy
WARMUP_TIER_S = get_tier_s_urls_legacy()

# Tier A - Editorial/news sites (news, blogs, magazines)
# These sites simulate reading behavior with moderate detection
WARMUP_TIER_A = get_tier_a_urls_legacy()

# Tier B - Consumer sites (retail, travel, weather)
# Commercial sites with heavier JS but manageable after warmup
WARMUP_TIER_B = get_tier_b_urls_legacy()

# Combined safe-first URL list (Tier S → A → B, no Tier C)
# Use this as the default warmup pool
ALL_WARMUP_URLS = get_safe_warmup_urls()

# Legacy compatibility aliases
WARMUP_HIGH_TRAFFIC_SITES = WARMUP_TIER_S[:5] + WARMUP_TIER_A[:5]
WARMUP_EDU_REFERENCE = WARMUP_TIER_S
WARMUP_NEWS_SITES = [u for u in WARMUP_TIER_A if 'news' in u[3] or 'magazine' in u[3]]
WARMUP_TECH_SITES = [u for u in WARMUP_TIER_S if 'tech' in u[3] or 'infra' in u[3]]
WARMUP_UTILITY_SITES = [u for u in WARMUP_TIER_B if 'utility' in u[3] or 'weather' in u[3]]
WARMUP_COMMERCE_SITES = [u for u in WARMUP_TIER_B if 'retail' in u[3] or 'travel' in u[3]]
WARMUP_LOCAL_CONTEXT = []  # Removed - causes detection on search engines
WARMUP_JS_VERIFICATION = WARMUP_TIER_A[:3]  # News sites have good JS

# Warmup configuration - Tiered approach
WARMUP_CONFIG = {
    # How many sites to visit during warmup
    # Tiered system selects from blueprints (S→A→B pattern)
    "min_sites_to_visit": 5,
    "max_sites_to_visit": 10,

    # Use tiered warmup (safer-first approach)
    "use_tiered_warmup": True,

    # Tier C probability (high-signal bot-aware sites)
    # Keep low to avoid detection; only 35% of sessions include Tier C
    "tier_c_probability": 0.35,

    # Human behavior simulation (overridden by tier-specific configs)
    "scroll_probability": 0.5,      # Default - tier configs override
    "click_probability": 0.10,      # Reduced for safety
    "read_time_min": 6,             # Increased for realism
    "read_time_max": 15,            # Increased for realism

    # Honeypot detection
    "check_invisible_links": True,
    "check_redirect_traps": True,
    "max_redirects": 3,

    # JS verification
    "verify_js_execution": True,
    "js_test_timeout": 5,

    # Tiered warmup specific
    "rewarm_uses_short_blueprint": True,  # Re-warm uses A→B only
    "enforce_no_domain_reuse": True,      # Prevent same domain in session
}


# =============================================================================
# TARGET GROUP CONFIGURATIONS
# =============================================================================
# Each target group has its own warmup strategy optimized for its scraping targets

# Use tiered warmup adapter for generating target-specific URLs
_warmup_adapter = TieredWarmupAdapter()

TARGET_GROUP_CONFIGS: Dict[str, TargetGroupConfig] = {
    "search_engines": TargetGroupConfig(
        name="search_engines",
        domains=["google.com", "bing.com", "duckduckgo.com"],
        min_sessions=2,
        max_sessions=3,
        # Search engines need extensive warmup with safe-first approach
        # Avoid Tier C (search engines themselves) to prevent detection
        warmup_urls=(
            WARMUP_TIER_S[:8] +   # Foundation first
            WARMUP_TIER_A[:6] +   # Editorial/news
            WARMUP_TIER_B[:4]     # Consumer (no search engines)
        ),
        warmup_actions=["deep_scroll", "read_content", "random_click", "js_verify"],
        warmup_frequency_seconds=1800,  # 30 minutes
        session_ttl_minutes=60,
        idle_ttl_minutes=15,
        navigation_cap=100,
        tier="A",
        min_delay_seconds=15.0,
        max_delay_seconds=30.0,
    ),

    "directories": TargetGroupConfig(
        name="directories",
        domains=[
            "yellowpages.com", "yelp.com", "bbb.org", "manta.com",
            "mapquest.com", "foursquare.com", "angi.com", "thumbtack.com",
            "homeadvisor.com",
        ],
        min_sessions=2,
        max_sessions=3,
        # Directory scraping - use consumer/utility context
        # Tiered approach: S → A → B, minimal Tier C
        warmup_urls=(
            WARMUP_TIER_S[:4] +   # Foundation
            WARMUP_TIER_A[:4] +   # Editorial
            WARMUP_TIER_B[:6]     # Consumer/utility
        ),
        warmup_actions=["deep_scroll", "read_content", "random_click"],
        warmup_frequency_seconds=1800,  # 30 minutes
        session_ttl_minutes=60,
        idle_ttl_minutes=15,
        navigation_cap=150,
        tier="C",
        min_delay_seconds=8.0,
        max_delay_seconds=15.0,
    ),

    "general": TargetGroupConfig(
        name="general",
        domains=["*"],  # Catch-all
        min_sessions=2,
        max_sessions=4,
        # General purpose - balanced tiered warmup
        warmup_urls=(
            WARMUP_TIER_S[:6] +   # Foundation
            WARMUP_TIER_A[:4] +   # Editorial
            WARMUP_TIER_B[:4]     # Consumer
        ),
        warmup_actions=["deep_scroll", "read_content", "js_verify"],
        warmup_frequency_seconds=1800,  # 30 minutes
        session_ttl_minutes=45,
        idle_ttl_minutes=12,
        navigation_cap=200,
        tier="D",
        min_delay_seconds=5.0,
        max_delay_seconds=10.0,
    ),
}


@dataclass
class BrowserSession:
    """Represents a managed browser session in the pool."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    target_group: str = "general"
    browser_type: BrowserType = BrowserType.SELENIUM_UC
    state: SessionState = SessionState.COLD

    # Browser instance (SeleniumBase Driver or CamoufoxDriver)
    driver: Optional[Any] = None

    # Lifecycle tracking
    created_at: datetime = field(default_factory=datetime.now)
    last_used_at: Optional[datetime] = None
    last_warmed_at: Optional[datetime] = None
    navigation_count: int = 0

    # Lease tracking
    lease_id: Optional[str] = None
    leased_at: Optional[datetime] = None
    lease_timeout: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    leased_by: Optional[str] = None  # Scraper module name

    # Proxy binding (sticky for session lifetime)
    proxy: Optional[Any] = None  # ResidentialProxy
    proxy_assigned_at: Optional[datetime] = None

    # Health tracking
    success_count: int = 0
    failure_count: int = 0
    captcha_count: int = 0
    consecutive_failures: int = 0
    last_error: Optional[str] = None

    # Dirty tracking
    dirty: bool = False
    dirty_reason: Optional[str] = None

    def mark_used(self):
        """Mark session as used (update last_used_at and navigation_count)."""
        self.last_used_at = datetime.now()
        self.navigation_count += 1

    def mark_success(self):
        """Record successful operation."""
        self.success_count += 1
        self.consecutive_failures = 0

    def mark_failure(self, error: str = None, is_captcha: bool = False):
        """Record failed operation."""
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_error = error
        if is_captcha:
            self.captcha_count += 1

    def mark_dirty(self, reason: str = None):
        """Mark session as needing cleanup."""
        self.dirty = True
        self.dirty_reason = reason

    def clear_dirty(self):
        """Clear dirty flag after cleanup."""
        self.dirty = False
        self.dirty_reason = None

    @property
    def is_available(self) -> bool:
        """Check if session is available for lease."""
        return self.state == SessionState.IDLE_WARM

    @property
    def is_healthy(self) -> bool:
        """Check if session is in a healthy state."""
        return self.state not in (SessionState.QUARANTINED, SessionState.DEAD)

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "target_group": self.target_group,
            "browser_type": self.browser_type.value,
            "state": self.state.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "navigation_count": self.navigation_count,
            "lease_id": self.lease_id,
            "leased_by": self.leased_by,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "captcha_count": self.captcha_count,
            "success_rate": self.success_rate,
            "dirty": self.dirty,
        }


@dataclass
class SessionLease:
    """Represents a lease on a browser session."""
    lease_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    leased_at: datetime = field(default_factory=datetime.now)
    timeout_at: Optional[datetime] = None
    leased_by: str = ""  # Module/scraper name
    target_domain: str = ""  # Primary domain being scraped

    # Heartbeat
    last_heartbeat: datetime = field(default_factory=datetime.now)
    heartbeat_interval: int = 30  # Expected seconds between heartbeats

    @property
    def is_expired(self) -> bool:
        """Check if lease has expired."""
        if self.timeout_at is None:
            return False
        return datetime.now() > self.timeout_at

    @property
    def heartbeat_stale(self) -> bool:
        """Check if heartbeat is stale (missed 2+ intervals)."""
        if self.last_heartbeat is None:
            return True
        elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
        return elapsed > (self.heartbeat_interval * 2)

    def refresh_heartbeat(self):
        """Update heartbeat timestamp."""
        self.last_heartbeat = datetime.now()

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "lease_id": self.lease_id,
            "session_id": self.session_id,
            "leased_at": self.leased_at.isoformat() if self.leased_at else None,
            "timeout_at": self.timeout_at.isoformat() if self.timeout_at else None,
            "leased_by": self.leased_by,
            "target_domain": self.target_domain,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "is_expired": self.is_expired,
            "heartbeat_stale": self.heartbeat_stale,
        }


@dataclass
class PoolStats:
    """Statistics for the browser pool."""
    total_sessions: int = 0
    sessions_by_state: Dict[str, int] = field(default_factory=dict)
    sessions_by_group: Dict[str, int] = field(default_factory=dict)
    sessions_by_type: Dict[str, int] = field(default_factory=dict)
    active_leases: int = 0
    total_leases_issued: int = 0
    total_recycled: int = 0
    total_quarantined: int = 0
    avg_lease_duration_seconds: float = 0.0
    avg_success_rate: float = 0.0

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "total_sessions": self.total_sessions,
            "sessions_by_state": self.sessions_by_state,
            "sessions_by_group": self.sessions_by_group,
            "sessions_by_type": self.sessions_by_type,
            "active_leases": self.active_leases,
            "total_leases_issued": self.total_leases_issued,
            "total_recycled": self.total_recycled,
            "total_quarantined": self.total_quarantined,
            "avg_lease_duration_seconds": self.avg_lease_duration_seconds,
            "avg_success_rate": self.avg_success_rate,
        }


# Site shortname to domain mapping
# Maps common site names used in scrapers to full domain names
SITE_TO_DOMAIN = {
    # Search engines
    "google": "google.com",
    "bing": "bing.com",
    "duckduckgo": "duckduckgo.com",
    # Directories
    "yellowpages": "yellowpages.com",
    "yp": "yellowpages.com",
    "yelp": "yelp.com",
    "bbb": "bbb.org",
    "manta": "manta.com",
    "mapquest": "mapquest.com",
    "foursquare": "foursquare.com",
    "angi": "angi.com",
    "thumbtack": "thumbtack.com",
    "homeadvisor": "homeadvisor.com",
    # GBP
    "gbp": "google.com",
    # Generic
    "generic": "general",
}


def get_target_group_for_domain(domain: str) -> str:
    """
    Determine which target group a domain belongs to.

    Args:
        domain: Domain name (e.g., "google.com", "yellowpages.com")
                Can also be a site shortname (e.g., "google", "bing", "yelp")

    Returns:
        Target group name ("search_engines", "directories", or "general")
    """
    domain_lower = domain.lower().strip()

    # Check if it's a site shortname and convert to domain
    if domain_lower in SITE_TO_DOMAIN:
        domain_lower = SITE_TO_DOMAIN[domain_lower]
        if domain_lower == "general":
            return "general"

    # Remove www. prefix if present
    if domain_lower.startswith("www."):
        domain_lower = domain_lower[4:]

    # Check each target group
    for group_name, config in TARGET_GROUP_CONFIGS.items():
        if group_name == "general":
            continue  # Check general last

        for group_domain in config.domains:
            if group_domain == "*":
                continue
            if domain_lower == group_domain or domain_lower.endswith("." + group_domain):
                return group_name

    # Default to general
    return "general"


# Browser type escalation order
ESCALATION_ORDER = [
    BrowserType.SELENIUM_UC,
    BrowserType.SELENIUM_UC_FRESH,
    BrowserType.CAMOUFOX,
    BrowserType.CAMOUFOX_NEW_FP,
]


def get_next_escalation_type(current_type: BrowserType) -> Optional[BrowserType]:
    """
    Get the next browser type in escalation order.

    Args:
        current_type: Current browser type

    Returns:
        Next browser type, or None if at max escalation
    """
    try:
        current_idx = ESCALATION_ORDER.index(current_type)
        if current_idx < len(ESCALATION_ORDER) - 1:
            return ESCALATION_ORDER[current_idx + 1]
    except ValueError:
        pass
    return None
