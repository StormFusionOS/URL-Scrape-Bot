"""
SERP System Configuration

Controls which SERP backend to use:
- "legacy": Original SerpScraperSelenium (fast but unreliable)
- "enterprise": New Enterprise SERP system (slow but reliable)

Set via environment variable: SERP_BACKEND=enterprise
Or in .env file.
"""

import os
from enum import Enum
from dotenv import load_dotenv

load_dotenv()


class SerpBackend(Enum):
    LEGACY = "legacy"
    ENTERPRISE = "enterprise"


# Read from environment
_backend_str = os.getenv("SERP_BACKEND", "legacy").lower()

if _backend_str == "enterprise":
    SERP_BACKEND = SerpBackend.ENTERPRISE
else:
    SERP_BACKEND = SerpBackend.LEGACY


def use_enterprise_serp() -> bool:
    """Check if enterprise SERP is enabled."""
    return SERP_BACKEND == SerpBackend.ENTERPRISE


def get_serp_backend() -> SerpBackend:
    """Get the current SERP backend setting."""
    return SERP_BACKEND


# Configuration for Enterprise SERP
ENTERPRISE_SERP_CONFIG = {
    "num_sessions": int(os.getenv("SERP_NUM_SESSIONS", "5")),
    "max_queries_per_hour": int(os.getenv("SERP_MAX_QUERIES_PER_HOUR", "20")),
    "min_delay_seconds": int(os.getenv("SERP_MIN_DELAY_SEC", "180")),
    "max_delay_seconds": int(os.getenv("SERP_MAX_DELAY_SEC", "600")),
    "cache_ttl_hours": int(os.getenv("SERP_CACHE_TTL_HOURS", "24")),
}


def print_serp_config():
    """Print current SERP configuration."""
    print(f"SERP Backend: {SERP_BACKEND.value}")
    if SERP_BACKEND == SerpBackend.ENTERPRISE:
        print("Enterprise SERP Config:")
        for key, value in ENTERPRISE_SERP_CONFIG.items():
            print(f"  {key}: {value}")
