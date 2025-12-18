#!/usr/bin/env python3
"""
SEO Module Testing Script

Tests each SEO module one at a time on 10 test inputs.
Outputs results to logs/seo_module_tests/

Usage:
    ./venv/bin/python scripts/test_seo_modules.py
    ./venv/bin/python scripts/test_seo_modules.py --module 1  # Test only module 1
    ./venv/bin/python scripts/test_seo_modules.py --module 3 --limit 5  # Test module 3 with 5 URLs
"""

import sys
import json
import time
import argparse
import traceback
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger

logger = get_logger("seo_module_tests")

# Test data
TEST_URLS = [
    "https://www.example.com",
    "https://www.wikipedia.org",
    "https://www.github.com",
    "https://www.reddit.com",
    "https://www.stackoverflow.com",
    "https://www.medium.com",
    "https://www.nytimes.com",
    "https://www.bbc.com",
    "https://www.cnn.com",
    "https://www.techcrunch.com",
]

TEST_QUERIES = [
    "pressure washing services",
    "car wash near me",
    "window cleaning company",
    "roof cleaning cost",
    "gutter cleaning services",
    "power washing prices",
    "soft wash house cleaning",
    "commercial pressure washing",
    "driveway cleaning service",
    "deck cleaning and staining",
]

TEST_BUSINESS = {
    "name": "River City Pressure Washing",
    "phone": "555-123-4567",
    "address": "123 Main St",
    "city": "Austin",
    "state": "TX",
}

TEST_DIRECTORIES = ["yellowpages", "yelp", "google_business"]
TEST_DOMAINS = ["example.com", "wikipedia.org", "github.com"]

OUTPUT_DIR = Path("logs/seo_module_tests")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def test_module(name: str, test_func, inputs: list, module_num: int) -> dict:
    """Run tests for a single module."""
    results = {
        "module": name,
        "module_num": module_num,
        "started_at": datetime.now().isoformat(),
        "tests": [],
        "passed": 0,
        "failed": 0,
        "errors": [],
    }

    logger.info(f"\n{'='*60}")
    logger.info(f"Testing Module {module_num}: {name}")
    logger.info(f"{'='*60}")
    logger.info(f"Running {len(inputs)} tests...")

    for i, input_data in enumerate(inputs):
        input_str = str(input_data)[:80]
        logger.info(f"  [{i+1}/{len(inputs)}] Testing: {input_str}")

        try:
            start = time.time()
            result = test_func(input_data)
            duration = time.time() - start

            # Check if result is valid
            success = result is not None

            # Get a preview of the result
            if result is not None:
                if hasattr(result, 'to_dict'):
                    result_preview = str(result.to_dict())[:500]
                elif hasattr(result, '__dict__'):
                    result_preview = str(result.__dict__)[:500]
                elif isinstance(result, (dict, list)):
                    result_preview = str(result)[:500]
                else:
                    result_preview = str(result)[:500]
            else:
                result_preview = "None"

            results["tests"].append({
                "input": str(input_data),
                "success": success,
                "duration_seconds": round(duration, 2),
                "result_preview": result_preview,
            })

            if success:
                results["passed"] += 1
                logger.info(f"      OK ({duration:.1f}s)")
            else:
                results["failed"] += 1
                results["errors"].append(f"{input_data}: Returned None")
                logger.warning(f"      FAIL: Returned None")

        except Exception as e:
            results["tests"].append({
                "input": str(input_data),
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
            results["failed"] += 1
            results["errors"].append(f"{input_data}: {e}")
            logger.error(f"      ERROR: {e}")

    results["completed_at"] = datetime.now().isoformat()

    # Calculate pass rate
    total = results["passed"] + results["failed"]
    pass_rate = (results["passed"] / total * 100) if total > 0 else 0
    results["pass_rate"] = round(pass_rate, 1)

    # Save results
    output_file = OUTPUT_DIR / f"module_{module_num}_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"\nModule {module_num} Results: {results['passed']}/{total} passed ({pass_rate:.1f}%)")
    logger.info(f"Results saved to: {output_file}")

    return results


# ==================== Module Test Functions ====================

def test_1_technical_auditor(limit: int = 10):
    """Test TechnicalAuditor module."""
    from seo_intelligence.scrapers.technical_auditor import TechnicalAuditor

    auditor = TechnicalAuditor(headless=True)

    def run_audit(url):
        return auditor.audit_page(url)

    return test_module("technical_auditor", run_audit, TEST_URLS[:limit], 1)


def test_2_core_web_vitals(limit: int = 10):
    """Test CoreWebVitalsCollector module."""
    from seo_intelligence.scrapers.core_web_vitals import CoreWebVitalsCollector

    collector = CoreWebVitalsCollector(headless=True)

    def measure_url(url):
        return collector.measure_url(url)  # Uses default samples

    return test_module("core_web_vitals", measure_url, TEST_URLS[:limit], 2)


def test_3_serp_scraper(limit: int = 10):
    """Test SerpScraperSelenium module."""
    from seo_intelligence.scrapers.serp_scraper_selenium import get_serp_scraper_selenium

    scraper = get_serp_scraper_selenium()

    def scrape_query(query):
        return scraper.scrape_query(query)

    return test_module("serp_scraper", scrape_query, TEST_QUERIES[:limit], 3)


def test_4_autocomplete_scraper(limit: int = 10):
    """Test AutocompleteScraperSelenium module."""
    from seo_intelligence.scrapers.autocomplete_scraper_selenium import get_autocomplete_scraper_selenium

    scraper = get_autocomplete_scraper_selenium()

    def get_suggestions(query):
        return scraper.get_suggestions(query)

    return test_module("autocomplete_scraper", get_suggestions, TEST_QUERIES[:limit], 4)


def test_5_citation_crawler(limit: int = 3):
    """Test CitationCrawler module."""
    from seo_intelligence.scrapers.citation_crawler import CitationCrawler, BusinessInfo

    crawler = CitationCrawler(headless=True)

    # Create test inputs (business + directory pairs)
    test_inputs = TEST_DIRECTORIES[:limit]

    # Convert dict to BusinessInfo dataclass
    business_info = BusinessInfo(
        name=TEST_BUSINESS["name"],
        phone=TEST_BUSINESS.get("phone", ""),
        address=TEST_BUSINESS.get("address", ""),
        city=TEST_BUSINESS.get("city", ""),
        state=TEST_BUSINESS.get("state", ""),
    )

    def check_directory(directory):
        return crawler.check_directory(business_info, directory)

    return test_module("citation_crawler", check_directory, test_inputs, 5)


def test_6_backlink_crawler(limit: int = 5):
    """Test BacklinkCrawler module."""
    from seo_intelligence.scrapers.backlink_crawler import BacklinkCrawler

    crawler = BacklinkCrawler(headless=True)

    def check_backlinks(url):
        return crawler.check_page_for_backlinks(url, TEST_DOMAINS)

    return test_module("backlink_crawler", check_backlinks, TEST_URLS[:limit], 6)


def test_7_competitor_crawler(limit: int = 3):
    """Test CompetitorCrawler module."""
    from seo_intelligence.scrapers.competitor_crawler import CompetitorCrawler

    crawler = CompetitorCrawler(headless=True, max_pages_per_site=3)

    def crawl_competitor(domain):
        return crawler.crawl_competitor(domain)

    return test_module("competitor_crawler", crawl_competitor, TEST_DOMAINS[:limit], 7)


# ==================== Main Entry Point ====================

def main():
    parser = argparse.ArgumentParser(description="Test SEO modules")
    parser.add_argument("--module", "-m", type=int, choices=range(1, 8),
                        help="Test only specific module (1-7)")
    parser.add_argument("--limit", "-l", type=int, default=10,
                        help="Limit number of tests per module (default: 10)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("SEO MODULE TESTING - Starting")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    all_results = []

    # Map of module tests
    tests = {
        1: ("TechnicalAuditor", test_1_technical_auditor),
        2: ("CoreWebVitals", test_2_core_web_vitals),
        3: ("SerpScraper", test_3_serp_scraper),
        4: ("AutocompleteScraper", test_4_autocomplete_scraper),
        5: ("CitationCrawler", test_5_citation_crawler),
        6: ("BacklinkCrawler", test_6_backlink_crawler),
        7: ("CompetitorCrawler", test_7_competitor_crawler),
    }

    # Determine which modules to test
    if args.module:
        modules_to_test = [args.module]
    else:
        modules_to_test = list(tests.keys())

    for module_num in modules_to_test:
        name, test_func = tests[module_num]

        try:
            # Adjust limit for certain modules
            if module_num in [5]:  # Citation crawler has fewer inputs
                limit = min(args.limit, 3)
            elif module_num in [7]:  # Competitor crawler is slow
                limit = min(args.limit, 3)
            elif module_num in [6]:  # Backlink crawler
                limit = min(args.limit, 5)
            else:
                limit = args.limit

            result = test_func(limit=limit)
            all_results.append(result)

        except Exception as e:
            logger.error(f"[Module {module_num}] Failed to initialize: {e}")
            logger.error(traceback.format_exc())
            all_results.append({
                "module": name,
                "module_num": module_num,
                "error": str(e),
                "passed": 0,
                "failed": 1,
            })

        # Pause between modules to avoid rate limiting
        if module_num != modules_to_test[-1]:
            logger.info("\nPausing 5 seconds before next module...")
            time.sleep(5)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 60)

    total_passed = sum(r.get("passed", 0) for r in all_results)
    total_failed = sum(r.get("failed", 0) for r in all_results)
    total_tests = total_passed + total_failed

    for r in all_results:
        passed = r.get("passed", 0)
        failed = r.get("failed", 0)
        total = passed + failed
        status = "PASS" if failed == 0 else "FAIL" if passed == 0 else "PARTIAL"
        pass_rate = r.get("pass_rate", 0)
        logger.info(f"  Module {r.get('module_num', '?')}: {r['module']:25} {status:8} ({passed}/{total} = {pass_rate}%)")

    overall_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
    logger.info(f"\nOverall: {total_passed}/{total_tests} tests passed ({overall_rate:.1f}%)")

    # Save combined results
    combined_file = OUTPUT_DIR / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(combined_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_passed": total_passed,
            "total_failed": total_failed,
            "overall_pass_rate": round(overall_rate, 1),
            "modules": all_results,
        }, f, indent=2, default=str)

    logger.info(f"\nCombined results saved to: {combined_file}")

    # Return exit code based on results
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
