"""
SEO Intelligence Scrapers

This module contains all scraper implementations:
- base_scraper: Shared scraping logic with Playwright
- serp_parser: Google SERP parsing utilities
- serp_scraper: Google SERP scraper for position tracking
- competitor_parser: Competitor page content extraction
- competitor_crawler: Competitor website crawler
- backlink_crawler: Backlink discovery and tracking
- citation_crawler: Citation directory scraping

All scrapers respect robots.txt and implement tier-based rate limiting.
"""

from .base_scraper import BaseScraper
from .serp_parser import SerpParser, SerpResult, SerpSnapshot, get_serp_parser
from .serp_scraper import SerpScraper, get_serp_scraper
from .competitor_parser import CompetitorParser, PageMetrics, get_competitor_parser
from .competitor_crawler import CompetitorCrawler, get_competitor_crawler
from .backlink_crawler import BacklinkCrawler, get_backlink_crawler
from .citation_crawler import CitationCrawler, CitationResult, BusinessInfo, get_citation_crawler
from .technical_auditor import TechnicalAuditor, AuditResult, AuditIssue, get_technical_auditor

__all__ = [
    "BaseScraper",
    "SerpParser",
    "SerpResult",
    "SerpSnapshot",
    "get_serp_parser",
    "SerpScraper",
    "get_serp_scraper",
    "CompetitorParser",
    "PageMetrics",
    "get_competitor_parser",
    "CompetitorCrawler",
    "get_competitor_crawler",
    "BacklinkCrawler",
    "get_backlink_crawler",
    "CitationCrawler",
    "CitationResult",
    "BusinessInfo",
    "get_citation_crawler",
    "TechnicalAuditor",
    "AuditResult",
    "AuditIssue",
    "get_technical_auditor",
]
