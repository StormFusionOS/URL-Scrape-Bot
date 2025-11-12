"""
Yellow Pages scraper module for washdb-bot.

City-First Scraping Strategy:
- Targets all 31,254 US cities individually
- Population-based prioritization (3 tiers)
- Shallow pagination (1-3 pages per city)
- Early-exit optimization
- 85%+ precision filtering

Modules:
- yp_crawl_city_first: City-first crawler
- yp_parser_enhanced: Enhanced HTML parsing
- yp_filter: Advanced filtering and scoring
- generate_city_targets: Target generation
- city_slug: City slug normalization
"""

# Enhanced modules (used by city-first)
from scrape_yp.yp_parser_enhanced import (
    parse_yp_results_enhanced,
    parse_single_listing_enhanced,
    extract_category_tags,
)
from scrape_yp.yp_filter import (
    YPFilter,
    filter_yp_listings,
)

# City-first modules
from scrape_yp.city_slug import (
    generate_city_slug,
    calculate_population_tier,
    tier_to_max_pages,
)

__version__ = "2.0.0"  # City-First

__all__ = [
    # Enhanced parsing and filtering
    "parse_yp_results_enhanced",
    "parse_single_listing_enhanced",
    "extract_category_tags",
    "YPFilter",
    "filter_yp_listings",
    # City-first utilities
    "generate_city_slug",
    "calculate_population_tier",
    "tier_to_max_pages",
]
