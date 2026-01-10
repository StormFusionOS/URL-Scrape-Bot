#!/usr/bin/env python3
"""
Full SEO Scrape Script

Runs all 7 SEO modules on provided URLs and exports results to CSV.

Usage:
    # Basic usage (headless mode - default)
    ./venv/bin/python scripts/full_seo_scrape.py --urls "https://example.com,https://site2.com"
    ./venv/bin/python scripts/full_seo_scrape.py --file urls.txt
    ./venv/bin/python scripts/full_seo_scrape.py --modules 1,2,3 --urls "..."

    # Stealth mode with headed browsers (better anti-detection, recommended for Google)
    ./venv/bin/python scripts/full_seo_scrape.py --headed --urls "https://example.com"

Options:
    --urls, -u      Comma-separated list of URLs
    --file, -f      File containing URLs (one per line)
    --modules, -m   Comma-separated module numbers (default: 1,2,3,4,5,6,7)
    --output, -o    Output filename (without extension)
    --format        Export format: csv, json, or both (default: csv)
    --headed        Use headed browsers with virtual display :99 for better anti-detection
                    Requires Xvfb running: Xvfb :99 -screen 0 1920x1080x24 -ac &
"""

import sys
import os
import csv
import json
import time
import argparse
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger

logger = get_logger("full_seo_scrape")

# Global headless setting (can be overridden via --headed flag)
USE_HEADLESS = True
VIRTUAL_DISPLAY = ":99"


def setup_display_for_headed():
    """Set up virtual display for headed browser mode."""
    global USE_HEADLESS
    if not USE_HEADLESS:
        os.environ["DISPLAY"] = VIRTUAL_DISPLAY
        logger.info(f"Using headed browser mode with virtual display {VIRTUAL_DISPLAY}")

# Output directory
OUTPUT_DIR = Path("exports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class SEOResult:
    """Container for all SEO analysis results for a single URL."""
    url: str
    domain: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Module 1: Technical Audit
    tech_passed_checks: int = 0
    tech_total_checks: int = 0
    tech_issues: str = ""
    tech_has_ssl: bool = False
    tech_has_sitemap: bool = False
    tech_has_robots: bool = False
    tech_mobile_friendly: bool = False
    tech_load_time_ms: float = 0

    # Module 2: Core Web Vitals
    cwv_lcp_ms: float = 0
    cwv_cls: float = 0
    cwv_inp_ms: float = 0
    cwv_fcp_ms: float = 0
    cwv_ttfb_ms: float = 0
    cwv_grade: str = ""

    # Module 3: SERP Analysis (for related queries)
    serp_organic_results: int = 0
    serp_has_local_pack: bool = False
    serp_has_paa: bool = False
    serp_position: int = 0
    serp_competitors: str = ""

    # Module 4: Autocomplete Suggestions
    autocomplete_suggestions: str = ""
    autocomplete_count: int = 0

    # Module 5: Citation Status
    citation_yellowpages: str = ""
    citation_yelp: str = ""
    citation_google_business: str = ""

    # Module 6: Backlinks Found
    backlinks_found: int = 0
    backlinks_details: str = ""

    # Module 7: Competitor Analysis
    competitor_pages_crawled: int = 0
    competitor_word_count: int = 0
    competitor_schema_types: str = ""
    competitor_internal_links: int = 0

    # Errors
    errors: str = ""


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def run_module_1_technical_audit(url: str, result: SEOResult) -> None:
    """Run TechnicalAuditor module."""
    try:
        from seo_intelligence.scrapers import TechnicalAuditor

        auditor = TechnicalAuditor(headless=USE_HEADLESS)
        audit = auditor.audit_page(url)

        if audit:
            result.tech_passed_checks = audit.passed_checks if hasattr(audit, 'passed_checks') else 0
            result.tech_total_checks = audit.total_checks if hasattr(audit, 'total_checks') else 0

            # Parse issues
            if hasattr(audit, 'issues') and audit.issues:
                result.tech_issues = "; ".join(str(i) for i in audit.issues[:5])

            # Check specific metrics
            if hasattr(audit, 'ssl_info'):
                result.tech_has_ssl = bool(audit.ssl_info)
            if hasattr(audit, 'sitemap_found'):
                result.tech_has_sitemap = audit.sitemap_found
            if hasattr(audit, 'robots_found'):
                result.tech_has_robots = audit.robots_found
            if hasattr(audit, 'mobile_friendly'):
                result.tech_mobile_friendly = audit.mobile_friendly
            if hasattr(audit, 'load_time_ms'):
                result.tech_load_time_ms = audit.load_time_ms

        logger.info(f"  [Module 1] Technical Audit: {result.tech_passed_checks}/{result.tech_total_checks} checks passed")

    except Exception as e:
        result.errors += f"Module 1: {e}; "
        logger.error(f"  [Module 1] Error: {e}")


def run_module_2_core_web_vitals(url: str, result: SEOResult) -> None:
    """Run CoreWebVitalsCollector module."""
    try:
        from seo_intelligence.scrapers import CoreWebVitalsCollector

        collector = CoreWebVitalsCollector(headless=USE_HEADLESS)
        cwv = collector.measure_url(url)

        if cwv:
            result.cwv_lcp_ms = cwv.lcp_ms if hasattr(cwv, 'lcp_ms') else 0
            result.cwv_cls = cwv.cls if hasattr(cwv, 'cls') else 0
            result.cwv_inp_ms = cwv.inp_ms if hasattr(cwv, 'inp_ms') else 0
            result.cwv_fcp_ms = cwv.fcp_ms if hasattr(cwv, 'fcp_ms') else 0
            result.cwv_ttfb_ms = cwv.ttfb_ms if hasattr(cwv, 'ttfb_ms') else 0
            result.cwv_grade = cwv.grade if hasattr(cwv, 'grade') else ""

        logger.info(f"  [Module 2] Core Web Vitals: LCP={result.cwv_lcp_ms}ms, CLS={result.cwv_cls}, Grade={result.cwv_grade}")

    except Exception as e:
        result.errors += f"Module 2: {e}; "
        logger.error(f"  [Module 2] Error: {e}")


def run_module_3_serp_scraper(domain: str, result: SEOResult) -> None:
    """Run SerpScraperSelenium module."""
    try:
        from seo_intelligence.scrapers.serp_scraper_selenium import get_serp_scraper_selenium

        scraper = get_serp_scraper_selenium()

        # Search for the domain to see ranking
        query = f"site:{domain}"
        serp = scraper.scrape_query(query)

        if serp:
            result.serp_organic_results = serp.organic_results if hasattr(serp, 'organic_results') else 0
            result.serp_has_local_pack = serp.has_local_pack if hasattr(serp, 'has_local_pack') else False
            result.serp_has_paa = serp.has_paa if hasattr(serp, 'has_paa') else False

            # Find position in results
            if hasattr(serp, 'results') and serp.results:
                for i, r in enumerate(serp.results[:10], 1):
                    if domain in str(r.get('url', '')):
                        result.serp_position = i
                        break

                # Get competitor domains
                competitors = [r.get('domain', '') for r in serp.results[:5] if domain not in r.get('url', '')]
                result.serp_competitors = ", ".join(competitors[:3])

        logger.info(f"  [Module 3] SERP: {result.serp_organic_results} results, position={result.serp_position}")

    except Exception as e:
        result.errors += f"Module 3: {e}; "
        logger.error(f"  [Module 3] Error: {e}")


def run_module_4_autocomplete(domain: str, result: SEOResult) -> None:
    """Run AutocompleteScraperSelenium module."""
    try:
        from seo_intelligence.scrapers.autocomplete_scraper_selenium import get_autocomplete_scraper_selenium

        scraper = get_autocomplete_scraper_selenium()

        # Get suggestions for company name/domain
        suggestions = scraper.get_suggestions(domain.replace('.com', '').replace('.', ' '))

        if suggestions:
            result.autocomplete_count = len(suggestions)
            # Format suggestions
            suggestion_texts = []
            for s in suggestions[:10]:
                if hasattr(s, 'text'):
                    suggestion_texts.append(s.text)
                elif isinstance(s, str):
                    suggestion_texts.append(s)
            result.autocomplete_suggestions = "; ".join(suggestion_texts)

        logger.info(f"  [Module 4] Autocomplete: {result.autocomplete_count} suggestions")

    except Exception as e:
        result.errors += f"Module 4: {e}; "
        logger.error(f"  [Module 4] Error: {e}")


def run_module_5_citations(business_name: str, result: SEOResult) -> None:
    """Run CitationCrawler module."""
    try:
        from seo_intelligence.scrapers import CitationCrawler, BusinessInfo

        crawler = CitationCrawler(headless=USE_HEADLESS)

        # Create business info from domain
        business = BusinessInfo(
            name=business_name,
            phone="",
            address="",
            city="",
            state="",
        )

        directories = ["yellowpages", "yelp", "google_business"]

        for directory in directories:
            try:
                citation = crawler.check_directory(business, directory)
                if citation:
                    status = "found" if citation.found else "not found"
                    if hasattr(citation, 'reason'):
                        status = citation.reason
                else:
                    status = "checked"

                if directory == "yellowpages":
                    result.citation_yellowpages = status
                elif directory == "yelp":
                    result.citation_yelp = status
                elif directory == "google_business":
                    result.citation_google_business = status

            except Exception as e:
                if directory == "yellowpages":
                    result.citation_yellowpages = f"error: {e}"
                elif directory == "yelp":
                    result.citation_yelp = f"error: {e}"
                elif directory == "google_business":
                    result.citation_google_business = f"error: {e}"

        logger.info(f"  [Module 5] Citations: YP={result.citation_yellowpages}, Yelp={result.citation_yelp}")

    except Exception as e:
        result.errors += f"Module 5: {e}; "
        logger.error(f"  [Module 5] Error: {e}")


def run_module_6_backlinks(url: str, result: SEOResult, target_domains: List[str] = None) -> None:
    """Run BacklinkCrawler module."""
    try:
        from seo_intelligence.scrapers import BacklinkCrawler

        crawler = BacklinkCrawler(headless=USE_HEADLESS)

        # Default target domains for comparison
        if not target_domains:
            target_domains = ["yelp.com", "yellowpages.com", "bbb.org"]

        backlinks = crawler.check_page_for_backlinks(url, target_domains)

        if backlinks:
            result.backlinks_found = len(backlinks) if hasattr(backlinks, '__len__') else 0

            # Format backlink details
            if hasattr(backlinks, 'backlinks') and backlinks.backlinks:
                details = []
                for bl in backlinks.backlinks[:5]:
                    if hasattr(bl, 'url'):
                        details.append(bl.url)
                result.backlinks_details = "; ".join(details)

        logger.info(f"  [Module 6] Backlinks: {result.backlinks_found} found")

    except Exception as e:
        result.errors += f"Module 6: {e}; "
        logger.error(f"  [Module 6] Error: {e}")


def run_module_7_competitor(domain: str, result: SEOResult) -> None:
    """Run CompetitorCrawler module."""
    try:
        from seo_intelligence.scrapers import CompetitorCrawler

        crawler = CompetitorCrawler(headless=USE_HEADLESS, max_pages_per_site=5)
        competitor = crawler.crawl_competitor(domain)

        if competitor:
            result.competitor_pages_crawled = competitor.pages_crawled if hasattr(competitor, 'pages_crawled') else 0
            result.competitor_word_count = competitor.total_word_count if hasattr(competitor, 'total_word_count') else 0
            result.competitor_internal_links = competitor.internal_links if hasattr(competitor, 'internal_links') else 0

            if hasattr(competitor, 'schema_types') and competitor.schema_types:
                result.competitor_schema_types = ", ".join(competitor.schema_types[:5])

        logger.info(f"  [Module 7] Competitor: {result.competitor_pages_crawled} pages, {result.competitor_word_count} words")

    except Exception as e:
        result.errors += f"Module 7: {e}; "
        logger.error(f"  [Module 7] Error: {e}")


def run_full_seo_scrape(urls: List[str], modules: List[int] = None) -> List[SEOResult]:
    """Run full SEO scrape on all URLs."""
    if modules is None:
        modules = [1, 2, 3, 4, 5, 6, 7]

    results = []
    total = len(urls)

    logger.info(f"Starting full SEO scrape on {total} URLs")
    logger.info(f"Modules to run: {modules}")
    logger.info("=" * 60)

    for i, url in enumerate(urls, 1):
        # Normalize URL
        if not url.startswith("http"):
            url = f"https://{url}"

        domain = extract_domain(url)
        business_name = domain.replace('.com', '').replace('.', ' ').title()

        logger.info(f"\n[{i}/{total}] Analyzing: {url}")
        logger.info(f"  Domain: {domain}")

        result = SEOResult(url=url, domain=domain)

        # Run each enabled module
        if 1 in modules:
            run_module_1_technical_audit(url, result)
            time.sleep(2)

        if 2 in modules:
            run_module_2_core_web_vitals(url, result)
            time.sleep(2)

        if 3 in modules:
            run_module_3_serp_scraper(domain, result)
            time.sleep(3)

        if 4 in modules:
            run_module_4_autocomplete(domain, result)
            time.sleep(2)

        if 5 in modules:
            run_module_5_citations(business_name, result)
            time.sleep(2)

        if 6 in modules:
            run_module_6_backlinks(url, result)
            time.sleep(2)

        if 7 in modules:
            run_module_7_competitor(domain, result)
            time.sleep(2)

        results.append(result)

        # Progress update
        logger.info(f"  Completed {i}/{total}")

        # Pause between URLs to avoid rate limiting
        if i < total:
            logger.info("  Pausing 5 seconds...")
            time.sleep(5)

    return results


def export_to_csv(results: List[SEOResult], filename: str = None) -> str:
    """Export results to CSV file."""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"seo_scrape_results_{timestamp}.csv"

    filepath = OUTPUT_DIR / filename

    # Get field names from dataclass
    fieldnames = [f.name for f in SEOResult.__dataclass_fields__.values()]

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow(asdict(result))

    logger.info(f"Results exported to: {filepath}")
    return str(filepath)


def export_to_json(results: List[SEOResult], filename: str = None) -> str:
    """Export results to JSON file."""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"seo_scrape_results_{timestamp}.json"

    filepath = OUTPUT_DIR / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump([asdict(r) for r in results], f, indent=2, default=str)

    logger.info(f"Results exported to: {filepath}")
    return str(filepath)


def main():
    global USE_HEADLESS

    parser = argparse.ArgumentParser(description="Full SEO Scrape with CSV Export")
    parser.add_argument("--urls", "-u", type=str, help="Comma-separated list of URLs")
    parser.add_argument("--file", "-f", type=str, help="File containing URLs (one per line)")
    parser.add_argument("--modules", "-m", type=str, default="1,2,3,4,5,6,7",
                        help="Comma-separated module numbers (default: 1,2,3,4,5,6,7)")
    parser.add_argument("--output", "-o", type=str, help="Output filename (without extension)")
    parser.add_argument("--format", type=str, default="csv", choices=["csv", "json", "both"],
                        help="Export format (default: csv)")
    parser.add_argument("--headed", action="store_true",
                        help="Use headed browsers (better anti-detection, uses virtual display :99)")
    args = parser.parse_args()

    # Configure browser mode
    if args.headed:
        USE_HEADLESS = False
        setup_display_for_headed()
        logger.info("STEALTH MODE: Using headed browsers with virtual display for better anti-detection")
    else:
        logger.info("Running in headless mode (use --headed for better anti-detection)")

    # Parse URLs
    urls = []
    if args.urls:
        urls = [u.strip() for u in args.urls.split(",") if u.strip()]
    elif args.file:
        with open(args.file, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    else:
        print("Error: Please provide --urls or --file")
        print("Example: ./venv/bin/python scripts/full_seo_scrape.py --urls 'https://example.com,https://site2.com'")
        return 1

    if not urls:
        print("Error: No URLs provided")
        return 1

    # Parse modules
    modules = [int(m.strip()) for m in args.modules.split(",")]

    logger.info("=" * 60)
    logger.info("FULL SEO SCRAPE")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"URLs: {len(urls)}")
    logger.info(f"Modules: {modules}")
    logger.info("=" * 60)

    # Run scrape
    results = run_full_seo_scrape(urls, modules)

    # Export
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = args.output or f"seo_scrape_{timestamp}"

    export_paths = []
    if args.format in ["csv", "both"]:
        csv_path = export_to_csv(results, f"{base_name}.csv")
        export_paths.append(csv_path)

    if args.format in ["json", "both"]:
        json_path = export_to_json(results, f"{base_name}.json")
        export_paths.append(json_path)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SCRAPE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total URLs processed: {len(results)}")
    logger.info(f"Export files:")
    for path in export_paths:
        logger.info(f"  - {path}")

    # Print quick summary stats
    successful = sum(1 for r in results if not r.errors)
    logger.info(f"\nSuccess rate: {successful}/{len(results)} ({successful/len(results)*100:.1f}%)")

    print(f"\n\nExport complete! Files saved to:")
    for path in export_paths:
        print(f"  {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
