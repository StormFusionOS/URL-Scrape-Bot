"""
Google Business Scraper Module

Playwright-based Google Maps/Business scraper with extreme caution and no proxies.

Components:
- google_client.py: Main scraper client (Playwright-only)
- google_logger.py: Sophisticated logging module
- google_config.py: Configuration management
- google_stealth.py: Anti-detection and stealth utilities
- google_parse.py: HTML parsing utilities
- google_crawl.py: Orchestration layer (Phase 2)

Author: washdb-bot
Date: 2025-11-10
"""

__version__ = '1.0.0'
__author__ = 'washdb-bot'

from .google_logger import GoogleScraperLogger
from .google_config import GoogleConfig
from .google_crawl import GoogleCrawler, scrape_google_maps

__all__ = [
    'GoogleScraperLogger',
    'GoogleConfig',
    'GoogleCrawler',
    'scrape_google_maps',
]
