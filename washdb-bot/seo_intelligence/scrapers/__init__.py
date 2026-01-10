"""
SEO Intelligence Scrapers

This module contains all scraper implementations using SeleniumBase for browser pool integration:
- base_selenium_scraper: Shared scraping logic with SeleniumBase (Undetected Chrome)
- serp_parser: Google SERP parsing utilities
- serp_scraper_selenium: Google SERP scraper for position tracking
- competitor_parser: Competitor page content extraction
- competitor_crawler_selenium: Competitor website crawler
- backlink_crawler_selenium: Backlink discovery and tracking
- citation_crawler_selenium: Citation directory scraping
- technical_auditor_selenium: Page-level SEO auditing with Core Web Vitals
- core_web_vitals_selenium: SeleniumBase-based CWV measurement
- autocomplete_scraper_selenium: Google autocomplete keyword discovery
- keyword_intelligence_selenium: Unified keyword research orchestrator
- competitive_analysis_selenium: Competitive intelligence orchestrator

All scrapers integrate with the EnterpriseBrowserPool for session management.
"""

# Base scrapers
from .base_scraper import BaseScraper
from .base_selenium_scraper import BaseSeleniumScraper

# Parser utilities (no browser needed)
from .serp_parser import SerpParser, SerpResult, SerpSnapshot, get_serp_parser
from .competitor_parser import CompetitorParser, PageMetrics, get_competitor_parser

# Selenium scrapers with browser pool integration
from .serp_scraper_selenium import SerpScraperSelenium, get_serp_scraper_selenium
from .competitor_crawler_selenium import (
    CompetitorCrawlerSelenium,
    SitemapURL,
    InternalLink,
    InternalLinkGraph,
    SitemapDiscovery,
    get_competitor_crawler_selenium,
)
from .backlink_crawler_selenium import BacklinkCrawlerSelenium, get_backlink_crawler_selenium
from .citation_crawler_selenium import (
    CitationCrawlerSelenium,
    CitationResult,
    BusinessInfo,
    get_citation_crawler_selenium,
)
from .technical_auditor_selenium import (
    TechnicalAuditorSelenium,
    AuditResult,
    AuditIssue,
    IssueSeverity,
    IssueCategory,
    get_technical_auditor_selenium,
)
from .autocomplete_scraper_selenium import (
    AutocompleteScraperSelenium,
    AutocompleteSuggestion,
    get_autocomplete_scraper_selenium,
)
from .core_web_vitals_selenium import (
    CoreWebVitalsSelenium,
    CWVResult,
    MobileDesktopComparison,
    get_cwv_selenium,
)
from .keyword_intelligence_selenium import (
    KeywordIntelligenceSelenium,
    KeywordAnalysis,
    get_keyword_intelligence_selenium,
)
from .competitive_analysis_selenium import (
    CompetitiveAnalysisSelenium,
    CompetitiveAnalysisResult,
    CompetitorProfile,
    get_competitive_analysis_selenium,
)

# Backward-compatible aliases (point to Selenium versions)
SerpScraper = SerpScraperSelenium
CompetitorCrawler = CompetitorCrawlerSelenium
BacklinkCrawler = BacklinkCrawlerSelenium
CitationCrawler = CitationCrawlerSelenium
TechnicalAuditor = TechnicalAuditorSelenium
AutocompleteScraper = AutocompleteScraperSelenium
CoreWebVitalsCollector = CoreWebVitalsSelenium
KeywordIntelligence = KeywordIntelligenceSelenium
CompetitiveAnalysis = CompetitiveAnalysisSelenium

# Factory function aliases
get_serp_scraper = get_serp_scraper_selenium
get_competitor_crawler = get_competitor_crawler_selenium
get_backlink_crawler = get_backlink_crawler_selenium
get_citation_crawler = get_citation_crawler_selenium
get_technical_auditor = get_technical_auditor_selenium
get_autocomplete_scraper = get_autocomplete_scraper_selenium
get_cwv_collector = get_cwv_selenium
get_keyword_intelligence = get_keyword_intelligence_selenium
get_competitive_analysis = get_competitive_analysis_selenium

__all__ = [
    # Base classes
    "BaseScraper",
    "BaseSeleniumScraper",
    # Parsers
    "SerpParser",
    "SerpResult",
    "SerpSnapshot",
    "get_serp_parser",
    "CompetitorParser",
    "PageMetrics",
    "get_competitor_parser",
    # Selenium scrapers (preferred)
    "SerpScraperSelenium",
    "get_serp_scraper_selenium",
    "CompetitorCrawlerSelenium",
    "SitemapURL",
    "InternalLink",
    "InternalLinkGraph",
    "SitemapDiscovery",
    "get_competitor_crawler_selenium",
    "BacklinkCrawlerSelenium",
    "get_backlink_crawler_selenium",
    "CitationCrawlerSelenium",
    "CitationResult",
    "BusinessInfo",
    "get_citation_crawler_selenium",
    "TechnicalAuditorSelenium",
    "AuditResult",
    "AuditIssue",
    "IssueSeverity",
    "IssueCategory",
    "get_technical_auditor_selenium",
    "AutocompleteScraperSelenium",
    "AutocompleteSuggestion",
    "get_autocomplete_scraper_selenium",
    "CoreWebVitalsSelenium",
    "CWVResult",
    "MobileDesktopComparison",
    "get_cwv_selenium",
    "KeywordIntelligenceSelenium",
    "KeywordAnalysis",
    "get_keyword_intelligence_selenium",
    "CompetitiveAnalysisSelenium",
    "CompetitiveAnalysisResult",
    "CompetitorProfile",
    "get_competitive_analysis_selenium",
    # Backward-compatible aliases
    "SerpScraper",
    "get_serp_scraper",
    "CompetitorCrawler",
    "get_competitor_crawler",
    "BacklinkCrawler",
    "get_backlink_crawler",
    "CitationCrawler",
    "get_citation_crawler",
    "TechnicalAuditor",
    "get_technical_auditor",
    "AutocompleteScraper",
    "get_autocomplete_scraper",
    "CoreWebVitalsCollector",
    "get_cwv_collector",
    "KeywordIntelligence",
    "get_keyword_intelligence",
    "CompetitiveAnalysis",
    "get_competitive_analysis",
]
