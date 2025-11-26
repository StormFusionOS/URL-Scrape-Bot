"""
Yelp Business Scraper

City-first scraping strategy for Yelp with:
- Playwright-based browser automation
- Advanced anti-detection measures
- Multi-worker parallel processing
- Database-driven target management
- Quality filtering and deduplication

Main modules:
- yelp_crawl_city_first: Main crawler implementation
- yelp_stealth: Anti-detection utilities
- yelp_parse: HTML parsing and data extraction
- yelp_filter: Business filtering and scoring
"""

__version__ = "1.0.0"
__author__ = "washdb-bot"

from scrape_yelp.yelp_crawl_city_first import crawl_city_targets, crawl_single_target
from scrape_yelp.yelp_stealth import get_playwright_context_params, SessionBreakManager
from scrape_yelp.yelp_parse import YelpParser
from scrape_yelp.yelp_filter import YelpFilter

__all__ = [
    "crawl_city_targets",
    "crawl_single_target",
    "get_playwright_context_params",
    "SessionBreakManager",
    "YelpParser",
    "YelpFilter",
]
