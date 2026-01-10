#!/usr/bin/env python3
"""
Test ALL 9 SEO modules with verified/standardized URLs from database.
Uses SeleniumBase UC mode for browser-based modules.

Modules:
1. TechnicalAuditor - Technical SEO audit
2. CoreWebVitals - Core Web Vitals metrics
3. BacklinkCrawler - Backlink discovery
4. CitationCrawler - Citation directory checking
5. CompetitorCrawler - Competitor website analysis
6. SerpScraper - Google SERP rankings
7. AutocompleteScraper - Keyword suggestions
8. KeywordIntelligence - Keyword research
9. CompetitiveAnalysis - Competitive intelligence
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# Import GoogleCoordinator for shared browser management
from seo_intelligence.services import get_google_coordinator

# Setup logging
log_dir = Path(__file__).parent.parent / 'logs'
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'seo_all_9_modules_test.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('seo_9_modules_test')


def get_verified_standardized_urls(limit: int = 10) -> list:
    """Get verified AND standardized business URLs from database."""
    engine = create_engine(os.getenv('DATABASE_URL'))

    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT id, name, standardized_name, website
            FROM companies
            WHERE verified = true
            AND standardized_name IS NOT NULL
            AND website IS NOT NULL
            AND LENGTH(website) > 10
            AND website LIKE 'http%'
            ORDER BY RANDOM()
            LIMIT :limit
        '''), {'limit': limit})

        return [(row[0], row[1], row[2], row[3]) for row in result]


def test_module(name: str, test_func, *args, **kwargs) -> dict:
    """Generic module test wrapper."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing: {name}")
    logger.info(f"{'='*60}")

    result = {'module': name, 'status': 'unknown', 'passed': 0, 'failed': 0, 'errors': []}
    start = time.time()

    try:
        test_result = test_func(*args, **kwargs)
        result.update(test_result)
        result['status'] = 'pass' if test_result.get('passed', 0) > 0 else 'fail'
    except Exception as e:
        logger.error(f"Module error: {e}")
        result['status'] = 'error'
        result['errors'].append(str(e)[:200])

    result['elapsed'] = round(time.time() - start, 1)
    logger.info(f"Result: {result['status'].upper()} - {result['passed']} passed, {result['failed']} failed ({result['elapsed']}s)")
    return result


def test_technical_auditor(urls: list) -> dict:
    """Test Technical Auditor module."""
    from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    auditor = TechnicalAuditorSelenium(headless=False, use_proxy=False)

    for cid, name, std_name, url in urls[:1]:  # Test 1 URL only
        logger.info(f"  Testing: {url[:50]}...")
        try:
            result = auditor.audit_page(url)
            if result and hasattr(result, 'overall_score'):
                logger.info(f"    OK - Score: {result.overall_score:.0f}/100")
                results['passed'] += 1
                results['details'].append({'url': url, 'score': result.overall_score})
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:50]}")
            results['failed'] += 1
            results['errors'].append({'url': url, 'error': str(e)[:100]})
        time.sleep(5)

    return results


def test_core_web_vitals(urls: list) -> dict:
    """Test Core Web Vitals module."""
    from seo_intelligence.scrapers.core_web_vitals_selenium import CoreWebVitalsSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    collector = CoreWebVitalsSelenium(headless=False, use_proxy=False)

    for cid, name, std_name, url in urls[:1]:  # Test 1 URL only
        logger.info(f"  Testing: {url[:50]}...")
        try:
            result = collector.measure_url(url, samples=1)
            if result:
                lcp = getattr(result, 'lcp_ms', None) or getattr(result, 'lcp', None)
                grade = getattr(result, 'grade', 'N/A')
                logger.info(f"    OK - Grade: {grade}, LCP: {lcp}ms")
                results['passed'] += 1
                results['details'].append({'url': url, 'grade': grade, 'lcp': lcp})
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:50]}")
            results['failed'] += 1
            results['errors'].append({'url': url, 'error': str(e)[:100]})
        time.sleep(5)

    return results


def test_backlink_crawler(urls: list) -> dict:
    """Test Backlink Crawler module."""
    from seo_intelligence.scrapers.backlink_crawler_selenium import BacklinkCrawlerSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    crawler = BacklinkCrawlerSelenium(headless=False, use_proxy=False)

    # Get target domain from first URL
    target_domains = []
    for _, _, _, url in urls[:1]:
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        target_domains.append(domain)

    for cid, name, std_name, url in urls[:1]:  # Test 1 URL only
        logger.info(f"  Testing: {url[:50]}...")
        try:
            result = crawler.check_page_for_backlinks(url, target_domains)
            if result is not None:
                count = len(result) if isinstance(result, list) else result.get('backlinks_found', 0)
                logger.info(f"    OK - {count} backlinks found")
                results['passed'] += 1
                results['details'].append({'url': url, 'backlinks': count})
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:50]}")
            results['failed'] += 1
            results['errors'].append({'url': url, 'error': str(e)[:100]})
        time.sleep(5)

    return results


def test_citation_crawler(urls: list) -> dict:
    """Test Citation Crawler module."""
    from seo_intelligence.scrapers.citation_crawler_selenium import CitationCrawlerSelenium, BusinessInfo

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    crawler = CitationCrawlerSelenium(headless=False, use_proxy=False)

    for cid, name, std_name, url in urls[:1]:  # Test 1 URL only
        logger.info(f"  Testing citations for: {std_name[:30]}...")
        try:
            business = BusinessInfo(
                name=std_name or name,
                phone="",
                address="",
                city="",
                state="",
                website=url
            )
            # Use check_all_directories with single directory
            result = crawler.check_all_directories(business, directories=['yellowpages'])
            if result:
                found = len([r for r in result.values() if r.is_listed])
                logger.info(f"    OK - {found}/{len(result)} citations found")
                results['passed'] += 1
                results['details'].append({'business': std_name, 'citations_found': found})
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:50]}")
            results['failed'] += 1
            results['errors'].append({'business': std_name, 'error': str(e)[:100]})
        time.sleep(5)

    return results


def test_competitor_crawler(urls: list) -> dict:
    """Test Competitor Crawler module."""
    from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    crawler = CompetitorCrawlerSelenium(headless=False, use_proxy=False, max_pages_per_site=1)

    for cid, name, std_name, url in urls[:1]:  # Test 1 URL only
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        logger.info(f"  Testing: {domain}...")
        try:
            result = crawler.crawl_competitor_with_sitemap(domain, website_url=url)
            if result:
                pages = result.get('pages_crawled', 0)
                words = result.get('total_words', 0) or result.get('total_word_count', 0)
                logger.info(f"    OK - {pages} pages, {words} words")
                results['passed'] += 1
                results['details'].append({'domain': domain, 'pages': pages, 'words': words})
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:50]}")
            results['failed'] += 1
            results['errors'].append({'domain': domain, 'error': str(e)[:100]})
        time.sleep(5)

    return results


def test_serp_scraper(urls: list) -> dict:
    """Test SERP Scraper module."""
    from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    scraper = SerpScraperSelenium(headless=False, use_proxy=False)

    # Multiple queries with long delays between each
    queries = ["pressure washing services", "window cleaning near me", "gutter cleaning cost"]

    for query in queries:
        logger.info(f"  Testing query: {query}...")
        try:
            result = scraper.scrape_query(query, location="United States")
            if result and hasattr(result, 'results'):
                count = len(result.results)
                logger.info(f"    OK - {count} results found")
                results['passed'] += 1
                results['details'].append({'query': query, 'results': count})
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:50]}")
            results['failed'] += 1
            results['errors'].append({'query': query, 'error': str(e)[:100]})

        logger.info(f"    Waiting 20s before next query...")
        time.sleep(20)  # 20 second delay between queries

    return results


def test_autocomplete_scraper(urls: list) -> dict:
    """Test Autocomplete Scraper module."""
    from seo_intelligence.scrapers.autocomplete_scraper_selenium import AutocompleteScraperSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    scraper = AutocompleteScraperSelenium(headless=False, use_proxy=False)

    # Multiple keywords with long delays between each
    keywords = ["pressure washing", "roof cleaning services", "soft wash house"]

    for keyword in keywords:
        logger.info(f"  Testing: {keyword}...")
        try:
            suggestions = scraper.get_suggestions(keyword)
            if suggestions:
                logger.info(f"    OK - {len(suggestions)} suggestions")
                results['passed'] += 1
                results['details'].append({'keyword': keyword, 'suggestions': len(suggestions)})
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:50]}")
            results['failed'] += 1
            results['errors'].append({'keyword': keyword, 'error': str(e)[:100]})

        logger.info(f"    Waiting 15s before next keyword...")
        time.sleep(15)  # 15 second delay between keywords

    return results


def test_keyword_intelligence(urls: list) -> dict:
    """Test Keyword Intelligence module."""
    from seo_intelligence.scrapers.keyword_intelligence_selenium import KeywordIntelligenceSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}

    try:
        intel = KeywordIntelligenceSelenium(headless=False, use_proxy=False)

        # Multiple keywords with delays
        keywords = ["roof cleaning", "driveway cleaning", "deck restoration"]

        for keyword in keywords:
            logger.info(f"  Testing keyword analysis for: {keyword}...")

            result = intel.analyze_keyword(keyword, include_related=False, include_questions=False)
            if result:
                logger.info(f"    OK - Analysis complete")
                results['passed'] += 1
                results['details'].append({'keyword': keyword, 'result': 'success'})
            else:
                results['failed'] += 1

            logger.info(f"    Waiting 25s before next keyword...")
            time.sleep(25)  # 25 second delay between keywords

    except Exception as e:
        logger.error(f"    ERROR: {str(e)[:50]}")
        results['failed'] += 1
        results['errors'].append({'error': str(e)[:100]})

    return results


def test_competitive_analysis(urls: list) -> dict:
    """Test Competitive Analysis module."""
    from seo_intelligence.scrapers.competitive_analysis_selenium import CompetitiveAnalysisSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}

    try:
        analyzer = CompetitiveAnalysisSelenium(headless=False, use_proxy=False)

        # Use first URL as the target business
        cid, name, std_name, url = urls[0]
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')

        logger.info(f"  Testing competitive analysis for: {domain}...")

        # Multiple keywords for competitive analysis
        result = analyzer.analyze_serp_competitors(
            your_domain=domain,
            target_keywords=["gutter cleaning", "roof washing", "exterior cleaning"]
        )
        if result:
            competitors = len(result.competitors) if hasattr(result, 'competitors') else 0
            keyword_gaps = len(result.keyword_gaps) if hasattr(result, 'keyword_gaps') else 0
            content_gaps = len(result.content_gaps) if hasattr(result, 'content_gaps') else 0
            logger.info(f"    OK - {competitors} competitors, {keyword_gaps} keyword gaps, {content_gaps} content gaps")
            results['passed'] += 1
            results['details'].append({
                'domain': domain,
                'competitors': competitors,
                'keyword_gaps': keyword_gaps,
                'content_gaps': content_gaps
            })
        else:
            results['failed'] += 1
    except Exception as e:
        logger.error(f"    ERROR: {str(e)[:50]}")
        results['failed'] += 1
        results['errors'].append({'error': str(e)[:100]})

    return results


def main():
    logger.info("=" * 70)
    logger.info("SEO 9-MODULE TEST SUITE")
    logger.info("=" * 70)
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("Testing all 9 SEO modules with verified/standardized URLs")
    logger.info("=" * 70)

    # Initialize GoogleCoordinator early for shared browser session
    # This ensures all Google-based modules (SERP, Autocomplete, KeywordIntel, CompetitiveAnalysis)
    # share the same browser instance with stealth tactics
    logger.info("\nInitializing GoogleCoordinator for shared browser session...")
    coordinator = get_google_coordinator()
    coordinator.reconfigure(headless=False, use_proxy=False)
    logger.info("  GoogleCoordinator ready (shared browser, UC stealth mode)")

    # Get URLs
    logger.info("\nFetching verified/standardized URLs from database...")
    urls = get_verified_standardized_urls(10)
    logger.info(f"Got {len(urls)} URLs:\n")

    for i, (cid, name, std_name, url) in enumerate(urls, 1):
        logger.info(f"  {i}. [{cid}] {std_name or name}")
        logger.info(f"      {url[:60]}")

    # Run all 9 module tests
    all_results = {}

    modules = [
        ("1. TechnicalAuditor", test_technical_auditor),
        ("2. CoreWebVitals", test_core_web_vitals),
        ("3. BacklinkCrawler", test_backlink_crawler),
        ("4. CitationCrawler", test_citation_crawler),
        ("5. CompetitorCrawler", test_competitor_crawler),
        ("6. SerpScraper", test_serp_scraper),
        ("7. AutocompleteScraper", test_autocomplete_scraper),
        ("8. KeywordIntelligence", test_keyword_intelligence),
        ("9. CompetitiveAnalysis", test_competitive_analysis),
    ]

    for name, test_func in modules:
        result = test_module(name, test_func, urls)
        all_results[name] = result

    # Final summary
    logger.info("\n" + "=" * 70)
    logger.info("FINAL SUMMARY - ALL 9 MODULES")
    logger.info("=" * 70)

    total_passed = sum(r['passed'] for r in all_results.values())
    total_failed = sum(r['failed'] for r in all_results.values())
    modules_working = sum(1 for r in all_results.values() if r['status'] == 'pass')

    for name, result in all_results.items():
        status_icon = "OK" if result['status'] == 'pass' else "FAIL" if result['status'] == 'fail' else "ERR"
        logger.info(f"  [{status_icon}] {name}: {result['passed']} passed, {result['failed']} failed ({result['elapsed']}s)")

    logger.info(f"\n  Modules Working: {modules_working}/9")
    logger.info(f"  Total Tests: {total_passed} passed, {total_failed} failed")

    # Save results
    output_path = log_dir / f'seo_9_modules_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'urls_tested': len(urls),
            'modules_working': modules_working,
            'results': all_results,
        }, f, indent=2, default=str)

    logger.info(f"\nResults saved to: {output_path}")

    # Clean up GoogleCoordinator
    logger.info("\nCleaning up GoogleCoordinator...")
    try:
        coordinator = get_google_coordinator()
        coordinator.close()
        logger.info("  GoogleCoordinator closed")
    except Exception as e:
        logger.warning(f"  Cleanup warning: {e}")

    return modules_working >= 7  # Success if 7+ modules working


if __name__ == '__main__':
    try:
        success = main()
    finally:
        # Ensure cleanup even on error
        try:
            coordinator = get_google_coordinator()
            coordinator.close()
        except:
            pass
    sys.exit(0 if success else 1)
