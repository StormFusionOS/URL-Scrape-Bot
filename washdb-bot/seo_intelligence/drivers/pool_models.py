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
# COMPREHENSIVE WARMUP URL POOLS
# =============================================================================
# These are curated lists of safe, high-traffic sites that:
# 1. Never block legitimate traffic
# 2. Handle JS properly (for verification)
# 3. Are not honeypots
# 4. Build realistic browsing fingerprints
# 5. Set cookies that make browsers look "lived in"
#
# Format: (url, min_wait_seconds, max_wait_seconds, category)
# =============================================================================

# High-traffic commercial sites - safe, never rate-limit, build realistic patterns
# NOTE: Replaced .gov sites which were causing proxy provider issues (rate limiting)
WARMUP_HIGH_TRAFFIC_SITES = [
    ("https://www.linkedin.com/", 2, 4, "social"),
    ("https://www.pinterest.com/", 2, 4, "social"),
    ("https://medium.com/", 2, 3, "content"),
    ("https://www.quora.com/", 2, 4, "content"),
    ("https://www.indeed.com/", 2, 3, "jobs"),
    ("https://www.glassdoor.com/", 2, 3, "jobs"),
    ("https://www.zillow.com/", 3, 5, "real_estate"),
    ("https://www.realtor.com/", 2, 4, "real_estate"),
    ("https://www.allrecipes.com/", 2, 3, "lifestyle"),
    ("https://www.foodnetwork.com/", 2, 3, "lifestyle"),
]

# Educational/Reference sites - very safe, high traffic, good JS
WARMUP_EDU_REFERENCE = [
    ("https://www.wikipedia.org/", 2, 4, "reference"),
    ("https://en.wikipedia.org/wiki/Main_Page", 3, 5, "reference"),
    ("https://www.britannica.com/", 2, 4, "reference"),
    ("https://www.khanacademy.org/", 3, 5, "education"),
    ("https://www.coursera.org/", 2, 4, "education"),
    ("https://www.archive.org/", 2, 4, "reference"),
    ("https://www.wolframalpha.com/", 2, 3, "reference"),
]

# Major news sites - high traffic, expect automation, good for cookies
WARMUP_NEWS_SITES = [
    ("https://www.reuters.com/", 3, 5, "news"),
    ("https://apnews.com/", 3, 5, "news"),
    ("https://www.npr.org/", 2, 4, "news"),
    ("https://www.bbc.com/", 3, 5, "news"),
    ("https://www.pbs.org/", 2, 4, "news"),
    ("https://www.c-span.org/", 2, 3, "news"),
]

# Major tech/services - high traffic, sophisticated but not blocking
WARMUP_TECH_SITES = [
    ("https://www.google.com/", 2, 4, "search"),
    ("https://www.bing.com/", 2, 3, "search"),
    ("https://duckduckgo.com/", 2, 3, "search"),
    ("https://www.microsoft.com/", 2, 4, "tech"),
    ("https://www.apple.com/", 2, 4, "tech"),
    ("https://github.com/", 2, 4, "tech"),
    ("https://stackoverflow.com/", 3, 5, "tech"),
]

# Weather/utility sites - public service, never block
WARMUP_UTILITY_SITES = [
    ("https://www.accuweather.com/", 2, 4, "weather"),
    ("https://www.wunderground.com/", 2, 3, "weather"),
    ("https://www.timeanddate.com/", 2, 3, "utility"),
    ("https://www.speedtest.net/", 3, 5, "utility"),
]

# Shopping/Commerce - high traffic, builds realistic patterns
WARMUP_COMMERCE_SITES = [
    ("https://www.amazon.com/", 3, 5, "shopping"),
    ("https://www.ebay.com/", 2, 4, "shopping"),
    ("https://www.etsy.com/", 2, 4, "shopping"),
    ("https://www.target.com/", 2, 4, "shopping"),
    ("https://www.homedepot.com/", 2, 4, "shopping"),
    ("https://www.lowes.com/", 2, 4, "shopping"),
]

# Directory/Local search context - builds context for directory scraping
WARMUP_LOCAL_CONTEXT = [
    ("https://www.google.com/search?q=plumber+near+me", 3, 5, "local_search"),
    ("https://www.google.com/search?q=local+contractors", 3, 5, "local_search"),
    ("https://www.google.com/search?q=home+services", 3, 5, "local_search"),
    ("https://www.google.com/maps", 3, 5, "maps"),
    ("https://www.mapquest.com/", 2, 4, "maps"),
]

# JS-heavy sites for rendering verification
WARMUP_JS_VERIFICATION = [
    ("https://www.google.com/maps", 3, 5, "js_heavy"),
    ("https://www.youtube.com/", 3, 5, "js_heavy"),
    ("https://twitter.com/", 2, 4, "js_heavy"),
    ("https://www.reddit.com/", 3, 5, "js_heavy"),
]

# Combine all warmup pools
ALL_WARMUP_URLS = (
    WARMUP_HIGH_TRAFFIC_SITES +
    WARMUP_EDU_REFERENCE +
    WARMUP_NEWS_SITES +
    WARMUP_TECH_SITES +
    WARMUP_UTILITY_SITES +
    WARMUP_COMMERCE_SITES +
    WARMUP_LOCAL_CONTEXT +
    WARMUP_JS_VERIFICATION
)

# Warmup configuration
WARMUP_CONFIG = {
    # How many sites to visit during warmup (quality over speed)
    # Reduced from 10-15 to 5-8 to lower browser crash risk
    "min_sites_to_visit": 5,
    "max_sites_to_visit": 8,

    # Human behavior simulation
    "scroll_probability": 0.7,      # 70% chance to scroll on each page
    "click_probability": 0.2,       # 20% chance to click a safe link (reduced for stability)
    "read_time_min": 2,             # Minimum seconds to "read" page
    "read_time_max": 5,             # Maximum seconds to "read" page

    # Honeypot detection
    "check_invisible_links": True,   # Detect invisible honeypot links
    "check_redirect_traps": True,    # Detect redirect honeypots
    "max_redirects": 3,              # Max redirects before aborting

    # JS verification
    "verify_js_execution": True,     # Run JS verification checks
    "js_test_timeout": 5,            # Seconds to wait for JS tests
}


# =============================================================================
# TARGET GROUP CONFIGURATIONS
# =============================================================================
# Each target group has its own warmup strategy optimized for its scraping targets

TARGET_GROUP_CONFIGS: Dict[str, TargetGroupConfig] = {
    "search_engines": TargetGroupConfig(
        name="search_engines",
        domains=["google.com", "bing.com", "duckduckgo.com"],
        min_sessions=4,
        max_sessions=8,
        # Search engines need extensive warmup with diverse browsing
        warmup_urls=(
            WARMUP_HIGH_TRAFFIC_SITES[:5] +
            WARMUP_NEWS_SITES[:4] +
            WARMUP_TECH_SITES +
            WARMUP_COMMERCE_SITES[:3] +
            WARMUP_JS_VERIFICATION[:2]
        ),
        warmup_actions=["deep_scroll", "read_content", "random_click", "js_verify"],
        warmup_frequency_seconds=1800,  # 30 minutes
        session_ttl_minutes=120,        # 2 hours
        idle_ttl_minutes=20,
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
        min_sessions=6,
        max_sessions=12,
        # Directory scraping needs local search context
        warmup_urls=(
            WARMUP_HIGH_TRAFFIC_SITES[:3] +
            WARMUP_LOCAL_CONTEXT +
            WARMUP_COMMERCE_SITES[:4] +
            WARMUP_UTILITY_SITES[:2] +
            WARMUP_EDU_REFERENCE[:2]
        ),
        warmup_actions=["deep_scroll", "read_content", "random_click", "local_search_behavior"],
        warmup_frequency_seconds=2400,  # 40 minutes
        session_ttl_minutes=60,         # 1 hour
        idle_ttl_minutes=15,
        navigation_cap=200,
        tier="C",
        min_delay_seconds=8.0,
        max_delay_seconds=15.0,
    ),

    "general": TargetGroupConfig(
        name="general",
        domains=["*"],  # Catch-all
        min_sessions=5,
        max_sessions=10,
        # General purpose needs balanced warmup
        warmup_urls=(
            WARMUP_HIGH_TRAFFIC_SITES[:4] +
            WARMUP_EDU_REFERENCE[:3] +
            WARMUP_NEWS_SITES[:3] +
            WARMUP_UTILITY_SITES +
            WARMUP_TECH_SITES[:3]
        ),
        warmup_actions=["deep_scroll", "read_content", "js_verify"],
        warmup_frequency_seconds=3600,  # 1 hour
        session_ttl_minutes=30,
        idle_ttl_minutes=10,
        navigation_cap=300,
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
