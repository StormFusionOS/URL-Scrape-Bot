"""
SEO Intelligence Scrapers

This module contains all scraper implementations:
- base_scraper: Shared scraping logic with Playwright
- serp_parser: Google SERP parsing utilities
- serp_scraper: Google SERP scraper for position tracking
- (Future) competitor_crawler: Competitor page analysis
- (Future) backlink_crawler: Backlink discovery
- (Future) citation_crawler: Citation directory scraping

All scrapers respect robots.txt and implement tier-based rate limiting.
"""

from .base_scraper import BaseScraper
from .serp_parser import SerpParser, SerpResult, SerpSnapshot, get_serp_parser
from .serp_scraper import SerpScraper, get_serp_scraper

__all__ = [
    "BaseScraper",
    "SerpParser",
    "SerpResult",
    "SerpSnapshot",
    "get_serp_parser",
    "SerpScraper",
    "get_serp_scraper",
]
