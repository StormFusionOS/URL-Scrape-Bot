#!/usr/bin/env python3
"""
Comprehensive test script for all 9 SEO Selenium modules.

Tests:
1. CoreWebVitalsSelenium
2. TechnicalAuditorSelenium
3. CompetitorCrawlerSelenium
4. BacklinkCrawlerSelenium
5. CitationCrawlerSelenium
6. SerpScraperSelenium
7. AutocompleteScraperSelenium
8. KeywordIntelligenceSelenium
9. CompetitiveAnalysisSelenium
"""

import os
import sys
import json
from datetime import datetime

# Add project root to path
sys.path.insert(0, '/home/rivercityscrape/URL-Scrape-Bot/washdb-bot')

from dotenv import load_dotenv
load_dotenv()

# Test URL
TEST_URL = "http://beebeluxuryautodetail.com/?utm_source=GBP&utm_medium=Click&utm_campaign=organic"
TEST_DOMAIN = "beebeluxuryautodetail.com"

results = {
    "test_url": TEST_URL,
    "test_domain": TEST_DOMAIN,
    "modules_loaded": 0,
    "modules_initialized": 0,
    "results": {}
}


def test_module(name, import_func, init_func, test_func):
    """Test a single module."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print('='*60)

    result = {"success": 0, "fail": 0, "results": []}

    # Step 1: Import
    try:
        module = import_func()
        print(f"  [OK] Import successful")
        results["modules_loaded"] += 1
    except Exception as e:
        print(f"  [FAIL] Import error: {e}")
        result["fail"] = 1
        result["results"].append({"error": f"Import: {str(e)}"})
        return result

    # Step 2: Initialize
    try:
        instance = init_func(module)
        print(f"  [OK] Init successful")
        results["modules_initialized"] += 1
    except Exception as e:
        print(f"  [FAIL] Init error: {e}")
        result["fail"] = 1
        result["results"].append({"error": f"Init: {str(e)}"})
        return result

    # Step 3: Functional test
    try:
        test_result = test_func(instance)
        if test_result:
            print(f"  [OK] Test successful")
            result["success"] = 1
            result["results"].append(test_result)
        else:
            print(f"  [FAIL] Test returned empty")
            result["fail"] = 1
    except Exception as e:
        print(f"  [FAIL] Test error: {e}")
        result["fail"] = 1
        result["results"].append({"error": f"Test: {str(e)}"})

    return result


# ============================================================================
# Module 1: CoreWebVitalsSelenium
# ============================================================================
def test_cwv():
    def import_func():
        from seo_intelligence.scrapers.core_web_vitals_selenium import CoreWebVitalsSelenium
        return CoreWebVitalsSelenium

    def init_func(cls):
        return cls(headless=True)

    def test_func(instance):
        result = instance.measure_url(TEST_URL)
        if result:
            return {
                "grade": result.grade,
                "lcp_ms": result.lcp_ms,
                "cls_value": result.cls_value,  # Fixed: was 'cls'
                "tbt_ms": result.tbt_ms,
            }
        return None

    return test_module("CoreWebVitalsSelenium", import_func, init_func, test_func)


# ============================================================================
# Module 2: TechnicalAuditorSelenium
# ============================================================================
def test_auditor():
    def import_func():
        from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium
        return TechnicalAuditorSelenium

    def init_func(cls):
        return cls(headless=True)

    def test_func(instance):
        result = instance.audit_page(TEST_URL)
        if result:
            return {
                "overall_score": result.overall_score,
                "issues_count": len(result.issues) if result.issues else 0,
            }
        return None

    return test_module("TechnicalAuditorSelenium", import_func, init_func, test_func)


# ============================================================================
# Module 3: CompetitorCrawlerSelenium
# ============================================================================
def test_competitor():
    def import_func():
        from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium
        return CompetitorCrawlerSelenium

    def init_func(cls):
        return cls(headless=True)

    def test_func(instance):
        result = instance.crawl_competitor(TEST_URL)
        if result:
            return {
                "domain": result.domain if hasattr(result, 'domain') else str(result)[:50],
                "page_count": result.page_count if hasattr(result, 'page_count') else 0,
            }
        return None

    return test_module("CompetitorCrawlerSelenium", import_func, init_func, test_func)


# ============================================================================
# Module 4: BacklinkCrawlerSelenium
# ============================================================================
def test_backlink():
    def import_func():
        from seo_intelligence.scrapers.backlink_crawler_selenium import BacklinkCrawlerSelenium
        return BacklinkCrawlerSelenium

    def init_func(cls):
        # Note: BacklinkCrawler accepts headless parameter
        return cls(headless=True)

    def test_func(instance):
        # Correct method: discover_backlinks() or check_page_for_backlinks()
        # Using discover_backlinks for a quick test (Bing search)
        result = instance.discover_backlinks(TEST_DOMAIN, max_results=5, verify=False)
        if result is not None:
            return {
                "backlinks_found": len(result),
                "sample": result[0] if result else None,
            }
        return {"backlinks_found": 0}

    return test_module("BacklinkCrawlerSelenium", import_func, init_func, test_func)


# ============================================================================
# Module 5: CitationCrawlerSelenium
# ============================================================================
def test_citation():
    def import_func():
        from seo_intelligence.scrapers.citation_crawler_selenium import CitationCrawlerSelenium, BusinessInfo
        return (CitationCrawlerSelenium, BusinessInfo)

    def init_func(module_tuple):
        cls, _ = module_tuple
        return cls(headless=True)

    def test_func(instance):
        # Citation crawler needs BusinessInfo object
        from seo_intelligence.scrapers.citation_crawler_selenium import BusinessInfo

        business = BusinessInfo(
            name="Beebe Luxury Auto Detail",
            city="",
            state="",
        )

        # Check just one directory (yellowpages) for speed
        result = instance.check_directory(business, "yellowpages")
        if result:
            return {
                "directory": result.directory,
                "is_listed": result.is_listed,
                "nap_score": result.nap_score,
            }
        return {"checked": True, "result": "no_listing"}

    return test_module("CitationCrawlerSelenium", import_func, init_func, test_func)


# ============================================================================
# Module 6: SerpScraperSelenium
# ============================================================================
def test_serp():
    def import_func():
        from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium
        return SerpScraperSelenium

    def init_func(cls):
        # SerpScraperSelenium accepts headless parameter
        return cls(headless=True)

    def test_func(instance):
        # Use scrape_serp method (returns dict for compatibility)
        result = instance.scrape_serp("auto detailing", num_results=10)
        if result:
            return {
                "query": result.get("query", ""),
                "results_count": len(result.get("organic_results", [])),
                "has_local_pack": result.get("has_local_pack", False),
            }
        return None

    return test_module("SerpScraperSelenium", import_func, init_func, test_func)


# ============================================================================
# Module 7: AutocompleteScraperSelenium
# ============================================================================
def test_autocomplete():
    def import_func():
        from seo_intelligence.scrapers.autocomplete_scraper_selenium import AutocompleteScraperSelenium
        return AutocompleteScraperSelenium

    def init_func(cls):
        # AutocompleteScraperSelenium does NOT accept headless - it's hardcoded
        return cls()

    def test_func(instance):
        result = instance.get_suggestions("auto detailing near me")
        if result:
            return {
                "suggestions_count": len(result),
                "sample": result[0].keyword if result else None,
            }
        return {"suggestions_count": 0}

    return test_module("AutocompleteScraperSelenium", import_func, init_func, test_func)


# ============================================================================
# Module 8: KeywordIntelligenceSelenium
# ============================================================================
def test_keyword_intelligence():
    def import_func():
        from seo_intelligence.scrapers.keyword_intelligence_selenium import KeywordIntelligenceSelenium
        return KeywordIntelligenceSelenium

    def init_func(cls):
        # KeywordIntelligenceSelenium does NOT accept headless - it's hardcoded
        return cls()

    def test_func(instance):
        # Use analyze_keyword for a single keyword test
        result = instance.analyze_keyword("car wash near me", include_related=False, include_questions=False)
        if result:
            return {
                "keyword": result.keyword,
                "volume_category": result.volume.category.value if result.volume else None,
                "difficulty_level": result.difficulty.level.value if result.difficulty else None,
            }
        return None

    return test_module("KeywordIntelligenceSelenium", import_func, init_func, test_func)


# ============================================================================
# Module 9: CompetitiveAnalysisSelenium
# ============================================================================
def test_competitive_analysis():
    def import_func():
        from seo_intelligence.scrapers.competitive_analysis_selenium import CompetitiveAnalysisSelenium
        return CompetitiveAnalysisSelenium

    def init_func(cls):
        # CompetitiveAnalysisSelenium does NOT accept headless - it's hardcoded
        return cls()

    def test_func(instance):
        # Use compare_domains for a simple test
        result = instance.compare_domains(
            TEST_DOMAIN,
            "example.com",
            seed_keywords=["auto detailing"]
        )
        if result:
            return {
                "domain_a": result.get("comparison", {}).get("domain_a"),
                "domain_b": result.get("comparison", {}).get("domain_b"),
                "total_keywords": result.get("comparison", {}).get("total_keywords", 0),
            }
        return None

    return test_module("CompetitiveAnalysisSelenium", import_func, init_func, test_func)


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("SEO MODULE COMPREHENSIVE TEST")
    print(f"Started: {datetime.now().isoformat()}")
    print("="*60)

    # Run all tests
    results["results"]["cwv"] = test_cwv()
    results["results"]["auditor"] = test_auditor()
    results["results"]["competitor"] = test_competitor()
    results["results"]["backlink"] = test_backlink()
    results["results"]["citation"] = test_citation()
    results["results"]["serp"] = test_serp()
    results["results"]["autocomplete"] = test_autocomplete()
    results["results"]["keyword"] = test_keyword_intelligence()
    results["results"]["competitive"] = test_competitive_analysis()

    # Summary
    passed = sum(1 for r in results["results"].values() if r["success"] > 0)
    failed = sum(1 for r in results["results"].values() if r["fail"] > 0 and r["success"] == 0)
    skipped = sum(1 for r in results["results"].values() if r["fail"] == 0 and r["success"] == 0)

    results["summary"] = {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Modules Loaded: {results['modules_loaded']}/9")
    print(f"Modules Initialized: {results['modules_initialized']}/9")
    print(f"Tests Passed: {passed}/9")
    print(f"Tests Failed: {failed}/9")
    print(f"Tests Skipped: {skipped}/9")

    # Save results
    output_path = "/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/seo_all_modules_test.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")
