"""
Bing discovery provider for washdb-bot.

This package provides business discovery capabilities using Bing search,
supporting both HTML scraping and API modes.

Modules:
    bing_config: Configuration constants and environment settings
    bing_client: Query building, fetching, parsing, rate limiting
    bing_crawl: Multi-page crawl orchestration and de-duplication
    bing_db: Database integration for saving Bing discoveries

Usage:
    from scrape_bing import crawl_category_location, save_bing_discoveries

Example:
    # Crawl and save to database
    results = crawl_category_location(
        category="pressure washing",
        location="TX",
        max_pages=5
    )
    stats = save_bing_discoveries(results)
    print(f"Saved: {stats['inserted']} new, {stats['updated']} updated")
"""

from scrape_bing.bing_client import (
    fetch_bing_search_page,
    parse_bing_results,
    build_bing_query,
)
from scrape_bing.bing_crawl import (
    crawl_category_location,
    crawl_all_states,
    CATEGORIES,
    STATES,
)
from scrape_bing.bing_config import (
    BING_BASE_URL,
    CRAWL_DELAY_SECONDS,
    PAGES_PER_PAIR,
    USE_API,
)
from scrape_bing.bing_db import (
    save_bing_discoveries,
    save_bing_crawl_results,
)

__all__ = [
    # Client functions
    "fetch_bing_search_page",
    "parse_bing_results",
    "build_bing_query",
    # Crawl functions
    "crawl_category_location",
    "crawl_all_states",
    # Database functions
    "save_bing_discoveries",
    "save_bing_crawl_results",
    # Constants
    "CATEGORIES",
    "STATES",
    "BING_BASE_URL",
    "CRAWL_DELAY_SECONDS",
    "PAGES_PER_PAIR",
    "USE_API",
]
