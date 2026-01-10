#!/usr/bin/env python3
"""
Full SEO Audit - Run all 9 SEO modules on 20 verified/standardized URLs.
Designed for external review and audit.

Modules tested:
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
import dataclasses
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# Setup logging - dedicated log file for this audit
log_dir = Path(__file__).parent.parent / 'logs'
log_dir.mkdir(exist_ok=True)

AUDIT_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = log_dir / f'seo_full_audit_{AUDIT_TIMESTAMP}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('seo_full_audit')


def serialize_for_json(obj):
    """Convert objects to JSON-serializable format.

    Properly handles dataclasses, datetime, and objects with to_dict() methods.
    Avoids the 'ClassName(...)' string representation from default=str.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    elif hasattr(obj, 'to_dict'):
        return obj.to_dict()
    elif hasattr(obj, '__dict__'):
        # For regular objects, try to serialize their __dict__
        return {k: serialize_for_json(v) for k, v in obj.__dict__.items()
                if not k.startswith('_')}
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, (set, frozenset)):
        return list(obj)
    elif isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    else:
        # Fallback to string, but log a warning
        return str(obj)


def get_verified_standardized_urls(limit: int = 20) -> list:
    """Get verified AND standardized business URLs from database."""
    engine = create_engine(os.getenv('DATABASE_URL'))

    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT id, name, standardized_name, website, city, state
            FROM companies
            WHERE verified = true
            AND standardized_name IS NOT NULL
            AND website IS NOT NULL
            AND LENGTH(website) > 10
            AND website LIKE 'http%'
            ORDER BY RANDOM()
            LIMIT :limit
        '''), {'limit': limit})

        return [dict(row._mapping) for row in result]


def test_module(name: str, test_func, *args, **kwargs) -> dict:
    """Generic module test wrapper with detailed logging."""
    logger.info(f"\n{'='*70}")
    logger.info(f"MODULE: {name}")
    logger.info(f"{'='*70}")

    result = {
        'module': name,
        'status': 'unknown',
        'passed': 0,
        'failed': 0,
        'errors': [],
        'details': [],
        'start_time': datetime.now().isoformat(),
    }
    start = time.time()

    try:
        test_result = test_func(*args, **kwargs)
        result.update(test_result)
        result['status'] = 'pass' if test_result.get('passed', 0) > 0 else 'fail'
    except Exception as e:
        logger.error(f"Module error: {e}", exc_info=True)
        result['status'] = 'error'
        result['errors'].append(str(e))

    result['elapsed_seconds'] = round(time.time() - start, 1)
    result['end_time'] = datetime.now().isoformat()

    logger.info(f"RESULT: {result['status'].upper()}")
    logger.info(f"  Passed: {result['passed']}, Failed: {result['failed']}")
    logger.info(f"  Elapsed: {result['elapsed_seconds']}s")

    return result


def test_technical_auditor(urls: list) -> dict:
    """Test Technical Auditor module on multiple URLs."""
    from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    auditor = TechnicalAuditorSelenium(headless=False, use_proxy=False)

    for company in urls[:5]:  # Test 5 URLs for this module
        url = company['website']
        name = company['standardized_name']
        logger.info(f"  Auditing: {name} - {url[:60]}...")

        try:
            result = auditor.audit_page(url)
            if result and hasattr(result, 'overall_score'):
                score = result.overall_score
                issues = len(result.issues) if hasattr(result, 'issues') else 0
                logger.info(f"    OK - Score: {score:.0f}/100, Issues: {issues}")
                results['passed'] += 1
                results['details'].append({
                    'company': name,
                    'url': url,
                    'score': score,
                    'issues': issues,
                    'status': 'success'
                })
            else:
                logger.warning(f"    FAIL - No result returned")
                results['failed'] += 1
                results['details'].append({
                    'company': name,
                    'url': url,
                    'status': 'no_result'
                })
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:100]}")
            results['failed'] += 1
            results['errors'].append({'url': url, 'error': str(e)[:200]})
            results['details'].append({
                'company': name,
                'url': url,
                'status': 'error',
                'error': str(e)[:200]
            })

        time.sleep(3)

    return results


def test_core_web_vitals(urls: list) -> dict:
    """Test Core Web Vitals module."""
    from seo_intelligence.scrapers.core_web_vitals_selenium import CoreWebVitalsSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    collector = CoreWebVitalsSelenium(headless=False, use_proxy=False)

    for company in urls[:5]:  # Test 5 URLs
        url = company['website']
        name = company['standardized_name']
        logger.info(f"  Measuring: {name} - {url[:60]}...")

        try:
            result = collector.measure_url(url, samples=1)
            if result:
                lcp = getattr(result, 'lcp_ms', None) or getattr(result, 'lcp', None)
                grade = getattr(result, 'grade', 'N/A')
                score = getattr(result, 'score', 0)
                logger.info(f"    OK - Grade: {grade}, LCP: {lcp}ms, Score: {score:.1f}")
                results['passed'] += 1
                results['details'].append({
                    'company': name,
                    'url': url,
                    'grade': grade,
                    'lcp_ms': lcp,
                    'score': score,
                    'status': 'success'
                })
            else:
                results['failed'] += 1
                results['details'].append({
                    'company': name,
                    'url': url,
                    'status': 'no_result'
                })
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:100]}")
            results['failed'] += 1
            results['errors'].append({'url': url, 'error': str(e)[:200]})

        time.sleep(3)

    return results


def test_backlink_crawler(urls: list) -> dict:
    """Test Backlink Crawler module.

    Uses discover_backlinks() to find external pages linking to the domain,
    rather than checking the company's own site (which would find internal links).
    """
    from seo_intelligence.scrapers.backlink_crawler_selenium import BacklinkCrawlerSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    crawler = BacklinkCrawlerSelenium(headless=False, use_proxy=False)

    for company in urls[:5]:  # Test 5 URLs
        url = company['website']
        name = company['standardized_name']
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')

        logger.info(f"  Discovering backlinks: {name} - {domain}...")

        try:
            # Use discover_backlinks() to find EXTERNAL pages linking to this domain
            # This uses Bing search to find pages that mention/link to the domain
            result = crawler.discover_backlinks(domain, max_results=20, verify=True)
            if result is not None:
                count = len(result) if isinstance(result, list) else 0
                logger.info(f"    OK - {count} external backlinks discovered")
                results['passed'] += 1
                results['details'].append({
                    'company': name,
                    'domain': domain,
                    'backlinks_found': count,
                    'status': 'success'
                })
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:100]}")
            results['failed'] += 1
            results['errors'].append({'url': url, 'error': str(e)[:200]})

        time.sleep(3)

    return results


def test_citation_crawler(urls: list) -> dict:
    """Test Citation Crawler module.

    Tracks blocked directories separately from failed (CAPTCHA != not found).
    """
    from seo_intelligence.scrapers.citation_crawler_selenium import CitationCrawlerSelenium, BusinessInfo

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': [], 'details': []}
    crawler = CitationCrawlerSelenium(headless=False, use_proxy=False)

    for company in urls[:3]:  # Test 3 URLs (citation checking is slow)
        name = company['standardized_name']
        url = company['website']
        city = company.get('city', '')
        state = company.get('state', '')

        logger.info(f"  Checking citations: {name}...")

        try:
            business = BusinessInfo(
                name=name,
                phone="",
                address="",
                city=city,
                state=state,
                website=url
            )
            result = crawler.check_all_directories(business, directories=['yellowpages', 'yelp'])
            if result:
                found = len([r for r in result.values() if r.is_listed])
                # Count blocked directories (CAPTCHA)
                blocked = len([r for r in result.values()
                              if r.metadata and r.metadata.get('error') == 'CAPTCHA_BLOCKED'])
                total = len(result)

                if blocked > 0:
                    logger.info(f"    WARN - {found}/{total} citations found, {blocked} directories blocked")
                    results['blocked'] += blocked
                else:
                    logger.info(f"    OK - {found}/{total} citations found")

                results['passed'] += 1
                results['details'].append({
                    'company': name,
                    'citations_found': found,
                    'citations_checked': total,
                    'directories_blocked': blocked,
                    'status': 'success' if blocked == 0 else 'partial'
                })
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:100]}")
            results['failed'] += 1
            results['errors'].append({'business': name, 'error': str(e)[:200]})

        time.sleep(5)

    # Log summary of directory stats
    stats = crawler.directory_stats
    logger.info(f"  Directory stats: {stats}")

    return results


def test_competitor_crawler(urls: list) -> dict:
    """Test Competitor Crawler module."""
    from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    crawler = CompetitorCrawlerSelenium(headless=False, use_proxy=False, max_pages_per_site=2)

    for company in urls[:5]:  # Test 5 URLs
        url = company['website']
        name = company['standardized_name']
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')

        logger.info(f"  Crawling competitor: {name} - {domain}...")

        try:
            result = crawler.crawl_competitor_with_sitemap(domain, website_url=url)
            if result:
                pages = result.get('pages_crawled', 0)
                words = result.get('total_words', 0) or result.get('total_word_count', 0)
                logger.info(f"    OK - {pages} pages, {words} words")
                results['passed'] += 1
                results['details'].append({
                    'company': name,
                    'domain': domain,
                    'pages_crawled': pages,
                    'total_words': words,
                    'status': 'success'
                })
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:100]}")
            results['failed'] += 1
            results['errors'].append({'domain': domain, 'error': str(e)[:200]})

        time.sleep(3)

    return results


def test_serp_scraper(urls: list) -> dict:
    """Test SERP Scraper module with industry keywords.

    Uses company city/state for geo-targeting on 'near me' queries to get
    market-relevant local results instead of generic national results.
    """
    from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    scraper = SerpScraperSelenium(headless=False, use_proxy=True)

    # Get a representative location from the companies for geo-targeting
    # Use first company with city/state, or default to "United States"
    default_location = "United States"
    for company in urls:
        city = company.get('city', '')
        state = company.get('state', '')
        if city and state:
            default_location = f"{city}, {state}"
            logger.info(f"  Using geo-location: {default_location}")
            break

    # Industry-relevant queries
    queries = [
        ("pressure washing services near me", default_location),  # Use local geo
        ("window cleaning company", default_location),  # Use local geo
        ("roof cleaning cost", "United States"),  # Generic - no geo needed
        ("gutter cleaning services", default_location),  # Use local geo
        ("soft wash house cleaning", "United States"),  # Generic - no geo needed
    ]

    for query, location in queries:
        logger.info(f"  Scraping SERP: '{query}' (location: {location})...")

        try:
            result = scraper.scrape_query(query, location=location)
            if result and hasattr(result, 'results'):
                count = len(result.results)
                local = len(result.local_pack) if hasattr(result, 'local_pack') else 0
                paa = len(result.people_also_ask) if hasattr(result, 'people_also_ask') else 0
                logger.info(f"    OK - {count} organic, {local} local, {paa} PAA")
                results['passed'] += 1
                results['details'].append({
                    'query': query,
                    'location': location,
                    'organic_results': count,
                    'local_results': local,
                    'paa_questions': paa,
                    'status': 'success'
                })
            else:
                results['failed'] += 1
                results['details'].append({
                    'query': query,
                    'location': location,
                    'status': 'no_result'
                })
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:100]}")
            results['failed'] += 1
            results['errors'].append({'query': query, 'error': str(e)[:200]})

        logger.info(f"    Waiting 20s before next query...")
        time.sleep(20)

    return results


def test_autocomplete_scraper(urls: list) -> dict:
    """Test Autocomplete Scraper module."""
    from seo_intelligence.scrapers.autocomplete_scraper_selenium import AutocompleteScraperSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}
    scraper = AutocompleteScraperSelenium()  # Uses headed + proxy by default now

    keywords = [
        "pressure washing",
        "window cleaning",
        "roof cleaning",
        "gutter cleaning",
        "soft wash"
    ]

    for keyword in keywords:
        logger.info(f"  Getting suggestions: '{keyword}'...")

        try:
            suggestions = scraper.get_suggestions(keyword)
            if suggestions:
                logger.info(f"    OK - {len(suggestions)} suggestions")
                results['passed'] += 1
                results['details'].append({
                    'keyword': keyword,
                    'suggestion_count': len(suggestions),
                    'suggestions': suggestions[:5],  # First 5 for brevity
                    'status': 'success'
                })
            else:
                results['failed'] += 1
        except Exception as e:
            logger.error(f"    ERROR: {str(e)[:100]}")
            results['failed'] += 1
            results['errors'].append({'keyword': keyword, 'error': str(e)[:200]})

        logger.info(f"    Waiting 15s before next keyword...")
        time.sleep(15)

    return results


def test_keyword_intelligence(urls: list) -> dict:
    """Test Keyword Intelligence module."""
    from seo_intelligence.scrapers.keyword_intelligence_selenium import KeywordIntelligenceSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}

    try:
        intel = KeywordIntelligenceSelenium()  # Uses headed + proxy by default now

        keywords = ["pressure washing", "roof cleaning", "gutter cleaning"]

        for keyword in keywords:
            logger.info(f"  Analyzing keyword: '{keyword}'...")

            try:
                result = intel.analyze_keyword(keyword, include_related=False, include_questions=False)
                if result:
                    volume = getattr(result, 'volume_estimate', 'N/A')
                    difficulty = getattr(result, 'difficulty', 'N/A')
                    opportunity = getattr(result, 'opportunity', 'N/A')
                    logger.info(f"    OK - Volume: {volume}, Difficulty: {difficulty}, Opportunity: {opportunity}")
                    results['passed'] += 1
                    results['details'].append({
                        'keyword': keyword,
                        'volume_estimate': str(volume),
                        'difficulty': str(difficulty),
                        'opportunity': str(opportunity),
                        'status': 'success'
                    })
                else:
                    results['failed'] += 1
            except Exception as e:
                logger.error(f"    ERROR: {str(e)[:100]}")
                results['failed'] += 1
                results['errors'].append({'keyword': keyword, 'error': str(e)[:200]})

            logger.info(f"    Waiting 30s before next keyword...")
            time.sleep(30)

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'error': str(e)[:200]})

    return results


def test_competitive_analysis(urls: list) -> dict:
    """Test Competitive Analysis module."""
    from seo_intelligence.scrapers.competitive_analysis_selenium import CompetitiveAnalysisSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}

    try:
        analyzer = CompetitiveAnalysisSelenium()  # Uses headed + proxy by default now

        # Test with 2 companies
        for company in urls[:2]:
            url = company['website']
            name = company['standardized_name']
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')

            logger.info(f"  Competitive analysis for: {name} ({domain})...")

            try:
                result = analyzer.analyze_serp_competitors(
                    your_domain=domain,
                    target_keywords=["pressure washing", "cleaning services"]
                )
                if result:
                    competitors = len(result.competitors) if hasattr(result, 'competitors') else 0
                    keyword_gaps = len(result.keyword_gaps) if hasattr(result, 'keyword_gaps') else 0
                    content_gaps = len(result.content_gaps) if hasattr(result, 'content_gaps') else 0
                    logger.info(f"    OK - {competitors} competitors, {keyword_gaps} keyword gaps, {content_gaps} content gaps")
                    results['passed'] += 1
                    results['details'].append({
                        'company': name,
                        'domain': domain,
                        'competitors_found': competitors,
                        'keyword_gaps': keyword_gaps,
                        'content_gaps': content_gaps,
                        'status': 'success'
                    })
                else:
                    results['failed'] += 1
            except Exception as e:
                logger.error(f"    ERROR: {str(e)[:100]}")
                results['failed'] += 1
                results['errors'].append({'domain': domain, 'error': str(e)[:200]})

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'error': str(e)[:200]})

    return results


def main():
    logger.info("=" * 70)
    logger.info("SEO FULL AUDIT - 9 MODULES x 20 URLs")
    logger.info("=" * 70)
    logger.info(f"Audit ID: {AUDIT_TIMESTAMP}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"Started: {datetime.now().isoformat()}")
    logger.info("=" * 70)

    # Get URLs
    logger.info("\nFetching 20 verified/standardized URLs from database...")
    urls = get_verified_standardized_urls(20)
    logger.info(f"Retrieved {len(urls)} URLs:\n")

    for i, company in enumerate(urls, 1):
        logger.info(f"  {i:2d}. [{company['id']}] {company['standardized_name']}")
        logger.info(f"      {company['website'][:70]}")

    # Warm browser pool before audit to avoid timeouts
    logger.info("\nWarming browser pool before audit...")
    try:
        from seo_intelligence.drivers.browser_pool import get_browser_pool
        pool = get_browser_pool()

        if pool.is_enabled():
            # Wait for pool to warm up (max 2 hours)
            max_wait = 7200
            min_warm_sessions = 3
            start_wait = time.time()

            while time.time() - start_wait < max_wait:
                stats = pool.get_stats()
                warm_count = stats.sessions_by_state.get('idle_warm', 0)
                total = stats.total_sessions

                if warm_count >= min_warm_sessions:
                    logger.info(f"Browser pool ready: {warm_count}/{total} sessions warm")
                    break

                elapsed = int(time.time() - start_wait)
                logger.info(f"Waiting for pool warmup... {warm_count}/{total} sessions warm ({elapsed}s/{max_wait}s)")
                time.sleep(5)
            else:
                stats = pool.get_stats()
                warm_count = stats.sessions_by_state.get('idle_warm', 0)
                logger.warning(f"Pool warmup timeout - continuing with {warm_count} warm sessions")
        else:
            logger.info("Browser pool disabled - using direct drivers")
    except Exception as e:
        logger.warning(f"Browser pool warmup failed: {e} - continuing without pool")

    # Run all 9 module tests
    all_results = {
        'audit_id': AUDIT_TIMESTAMP,
        'started': datetime.now().isoformat(),
        'urls_count': len(urls),
        'urls': urls,
        'modules': {}
    }

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
        all_results['modules'][name] = result

    # Final summary
    all_results['completed'] = datetime.now().isoformat()

    logger.info("\n" + "=" * 70)
    logger.info("FINAL SUMMARY - ALL 9 MODULES")
    logger.info("=" * 70)

    total_passed = sum(r['passed'] for r in all_results['modules'].values())
    total_failed = sum(r['failed'] for r in all_results['modules'].values())
    modules_working = sum(1 for r in all_results['modules'].values() if r['status'] == 'pass')

    for name, result in all_results['modules'].items():
        status_icon = "PASS" if result['status'] == 'pass' else "FAIL" if result['status'] == 'fail' else "ERR"
        logger.info(f"  [{status_icon}] {name}: {result['passed']} passed, {result['failed']} failed ({result['elapsed_seconds']}s)")

    logger.info(f"\n  Modules Working: {modules_working}/9")
    logger.info(f"  Total Tests: {total_passed} passed, {total_failed} failed")

    all_results['summary'] = {
        'modules_working': modules_working,
        'modules_total': 9,
        'tests_passed': total_passed,
        'tests_failed': total_failed,
    }

    # Save results to JSON with proper serialization
    # Uses serialize_for_json to convert dataclasses/objects to dicts
    results_file = log_dir / f'seo_full_audit_results_{AUDIT_TIMESTAMP}.json'
    with open(results_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=serialize_for_json)

    logger.info(f"\nResults saved to: {results_file}")
    logger.info(f"Log saved to: {LOG_FILE}")
    logger.info(f"\nAudit completed: {datetime.now().isoformat()}")

    return modules_working >= 7  # Success if 7+ modules working


if __name__ == '__main__':
    try:
        success = main()
    except KeyboardInterrupt:
        logger.info("\nAudit interrupted by user")
        success = False
    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=True)
        success = False

    sys.exit(0 if success else 1)
