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

__version__ = "0.1.0"

__all__ = [
    "fetch_yp_search_page",
    "parse_yp_results",
    "clean_text",
]
