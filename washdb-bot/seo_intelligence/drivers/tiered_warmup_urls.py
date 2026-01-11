"""
Tiered Warmup URL Configuration

Enterprise-grade URL pools organized by bot detection risk level.
URLs are sampled and randomized so no two browser instances follow the same warmup path.

Tier Definitions:
- Tier S: Infrastructure & Institutional (ultra-safe, minimal detection)
- Tier A: Editorial & Reading (news, blogs, low detection risk)
- Tier B: Consumer & Utility (commercial, moderate JS, manageable)
- Tier C: High-Signal, Bot-Aware (use sparingly, <40% of sessions)
- Tier D: Never Use (auth, finance, identity - explicitly excluded)
"""

from dataclasses import dataclass, field
from typing import List, Tuple
from enum import Enum


class WarmupTier(Enum):
    """Warmup URL tiers by detection risk."""
    S = "S"  # Infrastructure - ultra-safe
    A = "A"  # Editorial - low risk
    B = "B"  # Consumer - moderate
    C = "C"  # High-signal - use sparingly
    D = "D"  # Never use


@dataclass
class TierConfig:
    """Configuration for a warmup tier."""
    tier: WarmupTier
    name: str
    description: str

    # Sampling
    min_urls: int = 1
    max_urls: int = 3

    # Behavior
    scroll_probability: float = 0.0
    scroll_depth_min: float = 0.0
    scroll_depth_max: float = 0.0
    click_probability: float = 0.0
    dwell_time_min: float = 5.0
    dwell_time_max: float = 10.0

    # Usage constraints
    session_usage_probability: float = 1.0  # Probability this tier is used at all
    max_per_session: int = 4


# =============================================================================
# TIER S — Infrastructure & Institutional Trust (Ultra-Safe)
# =============================================================================
# Purpose: Baseline legitimacy, minimal bot detection, very low CAPTCHA risk
# Behavior: No scrolling, idle only, short dwell (6-15s)

TIER_S_CONFIG = TierConfig(
    tier=WarmupTier.S,
    name="Infrastructure",
    description="Ultra-safe institutional sites",
    min_urls=1,
    max_urls=4,
    scroll_probability=0.0,  # No scrolling
    scroll_depth_min=0.0,
    scroll_depth_max=0.0,
    click_probability=0.0,   # No clicking
    dwell_time_min=6.0,
    dwell_time_max=15.0,
    session_usage_probability=0.90,  # 90% of sessions
    max_per_session=4,
)

TIER_S_URLS: List[Tuple[str, str]] = [
    # Format: (url, subcategory)
    # Open source / Foundation sites
    ("https://www.wikipedia.org", "foundation"),
    ("https://en.wikipedia.org/wiki/Main_Page", "foundation"),
    ("https://www.wikimedia.org", "foundation"),
    ("https://www.gnu.org", "foundation"),
    ("https://www.apache.org", "foundation"),
    ("https://www.mozilla.org", "foundation"),

    # Programming language sites
    ("https://www.python.org", "tech"),
    ("https://nodejs.org", "tech"),
    ("https://www.php.net", "tech"),
    ("https://go.dev", "tech"),
    ("https://www.rust-lang.org", "tech"),

    # Infrastructure sites
    ("https://www.kernel.org", "infra"),
    ("https://www.postgresql.org", "infra"),
    ("https://www.mysql.com", "infra"),
    ("https://redis.io", "infra"),

    # Cloud/Hosting docs
    ("https://www.cloudflare.com", "cloud"),
    ("https://www.digitalocean.com", "cloud"),
    ("https://www.linode.com", "cloud"),
    ("https://www.vultr.com", "cloud"),
    ("https://www.netlify.com", "cloud"),
    ("https://vercel.com", "cloud"),

    # Standards bodies
    ("https://www.w3.org", "standards"),
    ("https://www.ietf.org", "standards"),
    ("https://www.icann.org", "standards"),
]


# =============================================================================
# TIER A — Editorial, News & Knowledge Consumption
# =============================================================================
# Purpose: Simulate reading and browsing behavior, moderate JS, low detection risk
# Behavior: Scroll 30-70%, optional internal click, medium dwell (10-30s)

TIER_A_CONFIG = TierConfig(
    tier=WarmupTier.A,
    name="Editorial",
    description="News, blogs, long-form content",
    min_urls=2,
    max_urls=6,
    scroll_probability=0.7,    # 70% chance to scroll
    scroll_depth_min=0.30,
    scroll_depth_max=0.70,
    click_probability=0.15,    # 15% chance to click internal link
    dwell_time_min=10.0,
    dwell_time_max=30.0,
    session_usage_probability=1.0,  # Always use Tier A
    max_per_session=6,
)

TIER_A_URLS: List[Tuple[str, str]] = [
    # Tech news/blogs - removed sites with heavy bot detection
    ("https://news.ycombinator.com", "tech_news"),
    ("https://dev.to", "tech_blog"),
    ("https://arstechnica.com", "tech_news"),
    # ("https://www.theverge.com", "tech_news"),  # Bot detection
    ("https://www.engadget.com", "tech_news"),
    # ("https://www.wired.com", "tech_news"),     # Paywall + detection
    # ("https://techcrunch.com", "tech_news"),    # Heavy JS + detection

    # Major news outlets - removed heavy detection sites
    ("https://www.npr.org", "news"),
    ("https://www.bbc.com", "news"),
    # ("https://www.bbc.com/news", "news"),       # Heavy + duplicate
    # ("https://www.theguardian.com", "news"),    # Bot detection
    ("https://www.reuters.com", "news"),
    ("https://apnews.com", "news"),
    # ("https://www.aljazeera.com", "news"),      # Bot detection

    # Long-form / Magazine (removed heavy bot detection sites)
    ("https://time.com", "magazine"),
    ("https://www.nationalgeographic.com", "magazine"),
    # ("https://www.theatlantic.com", "magazine"),  # Heavy bot detection
    # ("https://www.newyorker.com", "magazine"),    # Paywall + detection
    # ("https://www.economist.com", "magazine"),    # Paywall + detection
    # ("https://www.usatoday.com", "news"),         # Heavy ads + detection

    # Content platforms
    ("https://www.smithsonianmag.com", "magazine"),
    # ("https://www.pbs.org", "public"),  # Now has bot detection
    ("https://www.c-span.org", "public"),
]


# =============================================================================
# TIER B — Consumer, Utility & Lifestyle Signals
# =============================================================================
# Purpose: Commercial realism, heavier JS, manageable after warmup
# Behavior: Light scroll (20-40%), hover elements, no search/login

TIER_B_CONFIG = TierConfig(
    tier=WarmupTier.B,
    name="Consumer",
    description="Retail, travel, weather, reference",
    min_urls=1,
    max_urls=5,
    scroll_probability=0.5,    # 50% chance to scroll
    scroll_depth_min=0.20,
    scroll_depth_max=0.40,
    click_probability=0.05,    # 5% click probability (low)
    dwell_time_min=8.0,
    dwell_time_max=20.0,
    session_usage_probability=0.85,  # 85% of sessions
    max_per_session=5,
)

TIER_B_URLS: List[Tuple[str, str]] = [
    # Major retailers (homepage only, no search) - removed heavy bot detection sites
    ("https://www.amazon.com", "retail"),
    ("https://www.walmart.com", "retail"),
    # ("https://www.target.com", "retail"),  # Heavy bot detection
    ("https://www.costco.com", "retail"),
    ("https://www.bestbuy.com", "retail"),
    ("https://www.homedepot.com", "retail"),
    # ("https://www.lowes.com", "retail"),   # Heavy bot detection + slow
    ("https://www.ikea.com", "retail"),

    # Travel (homepage only)
    ("https://www.booking.com", "travel"),
    ("https://www.expedia.com", "travel"),
    ("https://www.tripadvisor.com", "travel"),
    ("https://www.kayak.com", "travel"),

    # Weather/Utility - removed problematic sites
    # ("https://www.weather.com", "utility"),     # Heavy ads + bot detection
    # ("https://www.accuweather.com", "utility"), # Bot detection
    ("https://www.timeanddate.com", "utility"),

    # Entertainment/Reference
    ("https://www.imdb.com", "entertainment"),
    ("https://www.rottentomatoes.com", "entertainment"),
    ("https://www.goodreads.com", "reference"),

    # Real estate - removed heavy detection sites
    # ("https://www.zillow.com", "real_estate"),  # Heavy bot detection
    ("https://www.realtor.com", "real_estate"),
]


# =============================================================================
# TIER C — High-Signal, Bot-Aware Platforms (Optional/Sparse)
# =============================================================================
# Purpose: Entropy and validation, strong fingerprinting, use sparingly
# Behavior: Fly-by visits only, no interaction, short dwell (3-8s)

TIER_C_CONFIG = TierConfig(
    tier=WarmupTier.C,
    name="High-Signal",
    description="Search engines, social, UGC platforms",
    min_urls=0,
    max_urls=2,
    scroll_probability=0.0,    # No scrolling
    scroll_depth_min=0.0,
    scroll_depth_max=0.0,
    click_probability=0.0,     # No clicking
    dwell_time_min=3.0,
    dwell_time_max=8.0,
    session_usage_probability=0.35,  # Only 35% of sessions use Tier C
    max_per_session=2,
)

TIER_C_URLS: List[Tuple[str, str]] = [
    # Search engines
    ("https://www.google.com", "search"),
    ("https://duckduckgo.com", "search"),
    ("https://www.bing.com", "search"),

    # Social/UGC (fly-by only)
    ("https://www.reddit.com", "social"),
    ("https://twitter.com", "social"),
    ("https://www.linkedin.com", "social"),
    ("https://www.pinterest.com", "social"),
    ("https://www.youtube.com", "social"),

    # Developer platforms
    ("https://stackoverflow.com", "dev"),
    ("https://github.com", "dev"),
    ("https://gitlab.com", "dev"),
]


# =============================================================================
# TIER D — Never Use for Warmup (Explicit Exclusion)
# =============================================================================
# Purpose: High-risk authentication, finance, and identity endpoints

TIER_D_URLS: List[str] = [
    # Auth providers
    "https://accounts.google.com",
    "https://login.microsoftonline.com",
    "https://appleid.apple.com",
    "https://auth0.com",
    "https://okta.com",

    # Payment/Finance
    "https://www.paypal.com",
    "https://stripe.com",
    "https://squareup.com",
    "https://www.coinbase.com",
    "https://www.binance.com",
    "https://www.kraken.com",

    # Banks
    "https://www.chase.com",
    "https://www.bankofamerica.com",
    "https://www.wellsfargo.com",
    "https://www.americanexpress.com",

    # Government/Identity
    "https://www.irs.gov",
    "https://www.ssa.gov",

    # AI providers
    "https://www.openai.com",
    "https://chat.openai.com",
    "https://claude.ai",
]


# =============================================================================
# WARMUP BLUEPRINTS
# =============================================================================
# Define valid tier sequences for warmup plans
# Each blueprint specifies which tiers to use and in what order

WARMUP_BLUEPRINTS = [
    # Standard patterns (safer-first)
    ["S", "A", "B"],          # Classic: safe → editorial → consumer
    ["S", "A", "A", "B"],     # Extended reading
    ["S", "S", "A", "B"],     # Extra foundation
    ["A", "A", "B"],          # Skip foundation (10% of sessions)
    ["S", "A", "B", "C"],     # Include high-signal (30% of sessions)
    ["S", "A", "A", "B", "C"], # Full spectrum

    # Shorter patterns for re-warm
    ["A", "B"],               # Quick re-warm
    ["S", "A"],               # Minimal re-warm
]

# Blueprint selection weights (index corresponds to WARMUP_BLUEPRINTS)
BLUEPRINT_WEIGHTS = [
    0.25,  # S → A → B (standard)
    0.20,  # S → A → A → B (extended reading)
    0.15,  # S → S → A → B (extra foundation)
    0.08,  # A → A → B (skip foundation)
    0.15,  # S → A → B → C (include high-signal)
    0.10,  # S → A → A → B → C (full spectrum)
    0.04,  # A → B (quick re-warm)
    0.03,  # S → A (minimal re-warm)
]

# Re-warm specific blueprints (shorter, no Tier C)
REWARM_BLUEPRINTS = [
    ["A", "B"],
    ["S", "A"],
    ["A", "A"],
    ["S", "A", "B"],
]

REWARM_BLUEPRINT_WEIGHTS = [0.35, 0.25, 0.20, 0.20]


# =============================================================================
# TIER CONFIGURATION LOOKUP
# =============================================================================

TIER_CONFIGS = {
    WarmupTier.S: TIER_S_CONFIG,
    WarmupTier.A: TIER_A_CONFIG,
    WarmupTier.B: TIER_B_CONFIG,
    WarmupTier.C: TIER_C_CONFIG,
}

TIER_URLS = {
    WarmupTier.S: TIER_S_URLS,
    WarmupTier.A: TIER_A_URLS,
    WarmupTier.B: TIER_B_URLS,
    WarmupTier.C: TIER_C_URLS,
}


def get_tier_config(tier: WarmupTier) -> TierConfig:
    """Get configuration for a specific tier."""
    return TIER_CONFIGS[tier]


def get_tier_urls(tier: WarmupTier) -> List[Tuple[str, str]]:
    """Get URLs for a specific tier."""
    return TIER_URLS[tier]


def is_url_blocked(url: str) -> bool:
    """Check if a URL is in the never-use list."""
    url_lower = url.lower()
    for blocked in TIER_D_URLS:
        if blocked.lower() in url_lower:
            return True
    return False
