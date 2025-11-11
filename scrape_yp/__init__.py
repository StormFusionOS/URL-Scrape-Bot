"""
Yellow Pages scraper module for washdb-bot.

This module handles:
- Scraping business listings from Yellow Pages
- Parsing search results
- Extracting business information
"""

from scrape_yp.yp_client import (
    fetch_yp_search_page,
    parse_yp_results,
    clean_text,
)
from scrape_yp.yp_crawl import (
    crawl_category_location,
    crawl_all_states,
    CATEGORIES,
    STATES,
)

__version__ = "0.1.0"

__all__ = [
    "fetch_yp_search_page",
    "parse_yp_results",
    "clean_text",
    "crawl_category_location",
    "crawl_all_states",
    "CATEGORIES",
    "STATES",
]
