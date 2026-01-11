"""
Competitor Intelligence Configuration

Defines settings for competitor tracking that differ from national SEO:
- More aggressive refresh intervals
- Deeper scraping depths
- Different rate limiting
"""

from datetime import timedelta
from typing import Dict, Any
import os


# =============================================================================
# REFRESH INTERVALS (vs 90 days for national)
# =============================================================================

REFRESH_INTERVALS = {
    1: timedelta(days=1),      # Priority 1: Daily - top competitors
    2: timedelta(days=2),      # Priority 2: Every other day
    3: timedelta(days=7),      # Priority 3: Weekly - less threatening
}

DEFAULT_PRIORITY_TIER = 2


# =============================================================================
# MODULE CONFIGURATION
# =============================================================================

MODULE_ORDER = [
    # Phase 1: Site & Content
    "site_crawl",         # Deep site structure + content
    "content_archive",    # Full content archiving + diff detection
    "blog_track",         # Blog discovery + publishing velocity

    # Phase 2: Search & Keywords
    "serp_track",         # Keyword position tracking
    "keyword_gaps",       # Keyword gap analysis

    # Phase 3: Social & Ads
    "social_track",       # Social media profile detection
    "ad_detect",          # Google/Facebook ad observation

    # Phase 4: Citations & Reviews
    "citation_check",     # Directory presence
    "review_aggregate",   # Review scores across platforms
    "review_deep_scrape", # Individual review extraction
    "review_analysis",    # Sentiment + anomaly detection

    # Phase 5: Technical & Pricing
    "technical_audit",    # Performance benchmarking
    "service_extract",    # Services/pricing detection
    "pricing_intel",      # Price history + packages

    # Phase 6: Synthesis
    "marketing_monitor",  # Marketing activity synthesis
    "intel_synthesis",    # Gap analysis + threat scoring
]

MODULE_TIMEOUTS = {
    # Core modules
    "site_crawl": 1800,        # 30 minutes
    "serp_track": 2700,        # 45 minutes
    "citation_check": 600,     # 10 minutes
    "review_aggregate": 900,   # 15 minutes
    "technical_audit": 600,    # 10 minutes
    "service_extract": 1200,   # 20 minutes
    "intel_synthesis": 900,    # 15 minutes

    # New deep intelligence modules
    "content_archive": 900,    # 15 minutes
    "blog_track": 600,         # 10 minutes
    "keyword_gaps": 300,       # 5 minutes
    "social_track": 600,       # 10 minutes
    "ad_detect": 900,          # 15 minutes
    "review_deep_scrape": 2700,# 45 minutes (pagination)
    "review_analysis": 600,    # 10 minutes
    "pricing_intel": 900,      # 15 minutes
    "marketing_monitor": 300,  # 5 minutes
}

# Modules that run daily vs weekly
DAILY_MODULES = [
    "site_crawl", "serp_track", "review_aggregate",
    "review_deep_scrape", "review_analysis", "intel_synthesis"
]
WEEKLY_MODULES = [
    "citation_check", "technical_audit", "service_extract",
    "content_archive", "blog_track", "keyword_gaps",
    "social_track", "ad_detect", "pricing_intel", "marketing_monitor"
]

# Google-heavy modules that need extra delay
GOOGLE_MODULES = ["serp_track", "keyword_gaps", "ad_detect", "review_deep_scrape"]


# =============================================================================
# RATE LIMITING (more aggressive than national)
# =============================================================================

DELAY_BETWEEN_MODULES = int(os.getenv("COMPETITOR_DELAY_MODULES", "3"))
DELAY_GOOGLE_MODULE = int(os.getenv("COMPETITOR_DELAY_GOOGLE", "15"))
DELAY_BETWEEN_COMPETITORS = int(os.getenv("COMPETITOR_DELAY_BETWEEN", "20"))
DELAY_NO_WORK = int(os.getenv("COMPETITOR_DELAY_NO_WORK", "60"))


# =============================================================================
# SCRAPING DEPTH (deeper than national)
# =============================================================================

SITE_CRAWL_PAGES = int(os.getenv("COMPETITOR_CRAWL_PAGES", "50"))
KEYWORDS_PER_COMPETITOR = int(os.getenv("COMPETITOR_KEYWORDS", "100"))
CITATIONS_DIRECTORIES = int(os.getenv("COMPETITOR_CITATIONS", "15"))

# Review sources to track
REVIEW_SOURCES = [
    "google",
    "yelp",
    "facebook",
    "bbb",
    "angi",
    "thumbtack",
    "homeadvisor",
]


# =============================================================================
# BROWSER POOL CONFIGURATION
# =============================================================================

BROWSER_TARGET_GROUP = "competitor_intel"
BROWSER_POOL_MIN_SESSIONS = int(os.getenv("COMPETITOR_POOL_MIN", "5"))
BROWSER_POOL_MAX_SESSIONS = int(os.getenv("COMPETITOR_POOL_MAX", "10"))


# =============================================================================
# ALERT THRESHOLDS
# =============================================================================

ALERT_THRESHOLDS = {
    "ranking_drop": 5,         # Alert if position drops by 5+
    "ranking_gain": 3,         # Alert if competitor gains 3+ positions
    "new_service": True,       # Alert on any new service detected
    "price_change": 0.10,      # Alert on 10%+ price change
    "review_spike": 5,         # Alert on 5+ reviews in 7 days
    "rating_drop": 0.3,        # Alert on 0.3+ rating drop
}


# =============================================================================
# THREAT SCORING WEIGHTS
# =============================================================================

THREAT_WEIGHTS = {
    "serp_overlap": 0.30,      # Same keywords ranked
    "location_proximity": 0.25, # Geographic overlap
    "service_match": 0.20,     # Same services offered
    "review_strength": 0.15,   # Review count and rating
    "domain_authority": 0.10,  # SEO strength
}


# =============================================================================
# DEEP REVIEW INTELLIGENCE
# =============================================================================

REVIEW_SCRAPE_CONFIG = {
    "max_reviews_per_source": 200,    # Max reviews to scrape per platform
    "incremental_scrape": True,       # Stop at known reviews
    "scrape_responses": True,         # Also scrape owner responses
    "min_delay_between_pages": 5.0,   # Seconds between pagination
    "max_delay_between_pages": 12.0,
}

SENTIMENT_CONFIG = {
    "analyzer": "vader",              # vader, textblob
    "confidence_threshold": 0.6,      # Minimum confidence to label
}

# Complaint/Praise category detection
REVIEW_CATEGORIES = {
    "complaints": {
        "pricing": ["expensive", "overpriced", "overcharged", "hidden fees", "cost too much"],
        "communication": ["no response", "didnt call", "never showed", "ghosted", "unreachable"],
        "quality": ["poor quality", "not clean", "missed spots", "incomplete", "sloppy"],
        "timing": ["late", "delayed", "took forever", "slow", "behind schedule"],
        "damage": ["damaged", "broke", "scratched", "ruined", "destroyed"],
        "professionalism": ["rude", "unprofessional", "disrespectful", "attitude"],
    },
    "praise": {
        "quality": ["thorough", "detailed", "perfect", "spotless", "excellent"],
        "professionalism": ["professional", "courteous", "respectful", "friendly"],
        "pricing": ["fair price", "reasonable", "good value", "affordable"],
        "communication": ["responsive", "great communication", "kept informed"],
        "timeliness": ["on time", "punctual", "quick", "efficient"],
    },
}

ANOMALY_THRESHOLDS = {
    "spike_threshold": 5,             # Reviews in one day
    "burst_multiplier": 3.0,          # vs normal velocity
    "template_similarity": 0.85,      # Response similarity threshold
    "new_reviewer_pct": 0.5,          # % of reviews from 1-review accounts
}


# =============================================================================
# PRICING INTELLIGENCE
# =============================================================================

PRICING_CONFIG = {
    "change_threshold": 0.10,         # 10% change triggers alert
    "history_days": 365,              # Days of price history to keep
    "package_expiry_warning_days": 7, # Warn before package expires
}

# Enhanced price patterns
PRICE_PATTERNS_EXTENDED = {
    "starting_at": [
        r'starting\s+(?:at|from)\s*\$(\d+)',
        r'(?:as\s+low\s+as|from)\s*\$(\d+)',
        r'prices?\s+start\s+(?:at|from)\s*\$(\d+)',
    ],
    "minimum_charge": [
        r'minimum\s+(?:charge|fee|price)?\s*[:of]?\s*\$(\d+)',
        r'\$(\d+)\s+minimum',
        r'min\s*[:.]?\s*\$(\d+)',
    ],
    "tiered": [
        r'(?:up\s+to|under)\s+(\d+)\s*(?:sqft|sq\s*ft).*?\$(\d+)',
        r'(\d+)\s*[-–]\s*(\d+)\s*(?:sqft|sq\s*ft).*?\$(\d+)',
    ],
    "per_unit": [
        r'\$(\d+\.?\d*)\s*(?:per|/|each)\s*(window|story|floor|room|car|vehicle)',
    ],
}


# =============================================================================
# CONTENT & SEO DEEP DIVE
# =============================================================================

CONTENT_CONFIG = {
    "archive_full_text": True,        # Store full page content
    "compute_readability": True,      # Calculate readability scores
    "track_changes": True,            # Diff detection
    "change_threshold_pct": 10,       # % change to trigger alert
}

BLOG_CONFIG = {
    "max_posts_to_track": 100,        # Per competitor
    "check_frequency_days": 7,        # How often to check for new posts
    "extract_full_content": True,     # Store full blog post content
}

KEYWORD_GAP_CONFIG = {
    "min_opportunity_score": 30,      # Minimum score to report
    "priority_thresholds": {
        "high": 70,
        "medium": 50,
        "low": 30,
    },
}


# =============================================================================
# SOCIAL & MARKETING
# =============================================================================

SOCIAL_PLATFORMS = [
    "facebook",
    "instagram",
    "youtube",
    "linkedin",
    "twitter",
    "tiktok",
]

SOCIAL_CONFIG = {
    "track_followers": True,
    "track_posts": True,
    "max_posts_per_platform": 50,
    "check_frequency_days": 7,
}

AD_DETECTION_CONFIG = {
    "detect_google_ads": True,        # Via SERP observation
    "detect_facebook_ads": True,      # Via Ad Library API
    "track_ad_copy": True,
}

MARKETING_CONFIG = {
    "campaign_detection": True,       # Detect promotional campaigns
    "engagement_spike_threshold": 3.0, # 3x normal engagement
}


# =============================================================================
# LOGGING
# =============================================================================

LOG_DIR = os.getenv("COMPETITOR_LOG_DIR", "logs/competitor_intel")
LOG_LEVEL = os.getenv("COMPETITOR_LOG_LEVEL", "INFO")


# =============================================================================
# DATABASE
# =============================================================================

# Job tracking table
JOB_TRACKING_TABLE = "competitor_job_tracking"

# Heartbeat settings
HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 300  # 5 minutes - mark stale after this


def get_module_config(module_name: str) -> Dict[str, Any]:
    """Get configuration for a specific module."""
    return {
        "timeout": MODULE_TIMEOUTS.get(module_name, 600),
        "is_daily": module_name in DAILY_MODULES,
        "delay_after": DELAY_GOOGLE_MODULE if module_name == "serp_track" else DELAY_BETWEEN_MODULES,
    }
