"""
SEO Intelligence System

AI-powered SEO intelligence tracking and analysis system.

This package provides:
- SERP monitoring and position tracking
- Competitor analysis and page crawling
- Backlink discovery and Local Authority Score (LAS)
- Citation tracking with NAP matching
- Technical/accessibility audits
- Review-mode governance for all changes

Architecture:
- Write-only data source (all changes go through change_log)
- No paid APIs (ethical scraping with robots.txt compliance)
- Token bucket rate limiting
- Content change detection via SHA-256 hashing
- Time-series data with partitioning support

Quick Start:
    # CLI usage
    python -m seo_intelligence status
    python -m seo_intelligence serp --query "pressure washing austin"
    python -m seo_intelligence audit --url https://example.com
    python -m seo_intelligence changes --list

    # Python API
    from seo_intelligence.services import get_change_manager, get_las_calculator
    from seo_intelligence.scrapers import get_technical_auditor, get_serp_scraper
"""

__version__ = "1.0.0"
__author__ = "Washbot Team"

# Public API - Services
from .services import (
    get_task_logger,
    get_rate_limiter,
    get_robots_checker,
    get_content_hasher,
    get_proxy_manager,
    get_las_calculator,
    get_change_manager,
)

# Public API - Scrapers
from .scrapers import (
    get_serp_scraper,
    get_serp_parser,
    get_competitor_crawler,
    get_competitor_parser,
    get_backlink_crawler,
    get_citation_crawler,
    get_technical_auditor,
)

__all__ = [
    # Services
    "get_task_logger",
    "get_rate_limiter",
    "get_robots_checker",
    "get_content_hasher",
    "get_proxy_manager",
    "get_las_calculator",
    "get_change_manager",
    # Scrapers
    "get_serp_scraper",
    "get_serp_parser",
    "get_competitor_crawler",
    "get_competitor_parser",
    "get_backlink_crawler",
    "get_citation_crawler",
    "get_technical_auditor",
]
