#!/usr/bin/env python3
"""
Test ALL SEO Selenium modules with real URLs from database.
Uses SeleniumBase UC mode with headed browsers for maximum stealth.

Tests:
1. TechnicalAuditorSelenium - Technical SEO audit
2. CoreWebVitalsSelenium - Core Web Vitals metrics
3. BacklinkCrawlerSelenium - Backlink discovery
4. CompetitorCrawlerSelenium - Competitor analysis
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

# Setup logging
log_dir = Path(__file__).parent.parent / 'logs'
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'seo_selenium_all_tests.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('seo_selenium_all_tests')


def get_real_urls(limit: int = 10) -> list:
    """Get real business URLs from the database."""
    engine = create_engine(os.getenv('DATABASE_URL'))

    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT website, name
            FROM companies
            WHERE website IS NOT NULL
            AND website != ''
            AND claude_verified = true
            ORDER BY RANDOM()
            LIMIT :limit
        '''), {'limit': limit})

        return [(row[0], row[1]) for row in result]


def test_technical_auditor_selenium(urls: list) -> dict:
    """Test TechnicalAuditorSelenium with UC mode."""
    logger.info("=" * 60)
    logger.info("Testing: TechnicalAuditorSelenium (UC Mode, Headed)")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium

        # Non-headless for max stealth (Xvfb handles display)
        auditor = TechnicalAuditorSelenium(headless=False, use_proxy=True)

        for i, (url, name) in enumerate(urls, 1):
            logger.info(f"  [{i}/{len(urls)}] Testing: {url[:50]}...")
            start = time.time()

            try:
                result = auditor.audit_page(url)
                elapsed = time.time() - start

                if result and hasattr(result, 'passed_checks'):
                    blocked_indicators = ['captcha', 'blocked', 'forbidden', '403', '429']
                    is_blocked = any(
                        any(ind in str(issue).lower() for ind in blocked_indicators)
                        for issue in result.issues
                    )

                    if is_blocked:
                        logger.warning(f"      BLOCKED ({elapsed:.1f}s) - {name[:30]}")
                        results['blocked'] += 1
                    else:
                        logger.info(f"      OK ({elapsed:.1f}s) - Score={result.overall_score:.0f}, {len(result.passed_checks)} passed")
                        results['passed'] += 1
                else:
                    logger.warning(f"      EMPTY RESULT ({elapsed:.1f}s)")
                    results['failed'] += 1

            except Exception as e:
                elapsed = time.time() - start
                error_str = str(e).lower()
                if 'timeout' in error_str or '403' in error_str or '429' in error_str or 'captcha' in error_str:
                    logger.error(f"      BLOCKED/TIMEOUT ({elapsed:.1f}s): {str(e)[:50]}")
                    results['blocked'] += 1
                else:
                    logger.error(f"      ERROR ({elapsed:.1f}s): {str(e)[:50]}")
                    results['failed'] += 1
                results['errors'].append({'url': url, 'error': str(e)[:100]})

            time.sleep(3)

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results


def test_core_web_vitals_selenium(urls: list) -> dict:
    """Test CoreWebVitalsSelenium with UC mode."""
    logger.info("=" * 60)
    logger.info("Testing: CoreWebVitalsSelenium (UC Mode, Headed)")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers.core_web_vitals_selenium import CoreWebVitalsSelenium

        collector = CoreWebVitalsSelenium(headless=False, use_proxy=True)

        for i, (url, name) in enumerate(urls, 1):
            logger.info(f"  [{i}/{len(urls)}] Testing: {url[:50]}...")
            start = time.time()

            try:
                result = collector.measure_url(url, samples=1)
                elapsed = time.time() - start

                if result:
                    # CWVResult is a dataclass, access attributes directly
                    lcp = getattr(result, 'lcp_ms', None) or getattr(result, 'lcp', None)
                    fcp = getattr(result, 'fcp_ms', None) or getattr(result, 'fcp', None)
                    ttfb = getattr(result, 'ttfb_ms', None) or getattr(result, 'ttfb', None)
                    cls = getattr(result, 'cls', None)
                    grade = getattr(result, 'grade', 'N/A')
                    score = getattr(result, 'score', 0)

                    if lcp or fcp or ttfb or cls is not None:
                        logger.info(f"      OK ({elapsed:.1f}s) - Grade={grade}, Score={score:.0f}, LCP={lcp}ms")
                        results['passed'] += 1
                    else:
                        logger.warning(f"      NO METRICS ({elapsed:.1f}s)")
                        results['failed'] += 1
                else:
                    logger.warning(f"      NO RESULT ({elapsed:.1f}s)")
                    results['failed'] += 1

            except Exception as e:
                elapsed = time.time() - start
                error_str = str(e).lower()
                if 'timeout' in error_str or '403' in error_str or '429' in error_str or 'captcha' in error_str:
                    logger.error(f"      BLOCKED/TIMEOUT ({elapsed:.1f}s): {str(e)[:50]}")
                    results['blocked'] += 1
                else:
                    logger.error(f"      ERROR ({elapsed:.1f}s): {str(e)[:50]}")
                    results['failed'] += 1
                results['errors'].append({'url': url, 'error': str(e)[:100]})

            time.sleep(3)

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results


def test_backlink_crawler_selenium(urls: list) -> dict:
    """Test BacklinkCrawlerSelenium with UC mode."""
    logger.info("=" * 60)
    logger.info("Testing: BacklinkCrawlerSelenium (UC Mode, Headed)")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers.backlink_crawler_selenium import BacklinkCrawlerSelenium

        crawler = BacklinkCrawlerSelenium(headless=False, use_proxy=True)

        # Use first few URLs as target domains to look for
        target_domains = []
        for url, _ in urls[:3]:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            target_domains.append(domain)

        for i, (url, name) in enumerate(urls[:5], 1):  # Test 5 URLs
            logger.info(f"  [{i}/5] Testing: {url[:50]}...")
            start = time.time()

            try:
                result = crawler.check_page_for_backlinks(url, target_domains)
                elapsed = time.time() - start

                if result is not None:
                    if isinstance(result, dict):
                        backlinks = result.get('backlinks_found', 0)
                        error = result.get('error')
                        if error:
                            logger.warning(f"      ERROR ({elapsed:.1f}s) - {error[:50]}")
                            results['failed'] += 1
                        else:
                            logger.info(f"      OK ({elapsed:.1f}s) - {backlinks} backlinks found")
                            results['passed'] += 1
                    elif isinstance(result, list):
                        logger.info(f"      OK ({elapsed:.1f}s) - {len(result)} backlinks found")
                        results['passed'] += 1
                    else:
                        logger.info(f"      OK ({elapsed:.1f}s) - Result received")
                        results['passed'] += 1
                else:
                    logger.warning(f"      NO RESULT ({elapsed:.1f}s)")
                    results['failed'] += 1

            except Exception as e:
                elapsed = time.time() - start
                error_str = str(e).lower()
                if 'blocked' in error_str or 'captcha' in error_str or '403' in error_str or '429' in error_str:
                    logger.error(f"      BLOCKED ({elapsed:.1f}s): {str(e)[:50]}")
                    results['blocked'] += 1
                else:
                    logger.error(f"      ERROR ({elapsed:.1f}s): {str(e)[:50]}")
                    results['failed'] += 1
                results['errors'].append({'url': url, 'error': str(e)[:100]})

            time.sleep(3)

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results


def test_competitor_crawler_selenium(urls: list) -> dict:
    """Test CompetitorCrawlerSelenium with UC mode."""
    logger.info("=" * 60)
    logger.info("Testing: CompetitorCrawlerSelenium (UC Mode, Headed)")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium

        # Use smaller max_pages for testing
        crawler = CompetitorCrawlerSelenium(headless=False, use_proxy=True, max_pages_per_site=3)

        # Extract domains from URLs
        domains = []
        for url, name in urls[:5]:  # Test 5 domains
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            domains.append((domain, name, url))

        for i, (domain, name, url) in enumerate(domains, 1):
            logger.info(f"  [{i}/{len(domains)}] Testing: {domain}...")
            start = time.time()

            try:
                result = crawler.crawl_competitor_with_sitemap(domain, website_url=url)
                elapsed = time.time() - start

                if result:
                    pages = result.get('pages_crawled', 0)
                    words = result.get('total_words', 0) or result.get('total_word_count', 0)
                    logger.info(f"      OK ({elapsed:.1f}s) - {pages} pages, {words} words")
                    results['passed'] += 1
                else:
                    logger.warning(f"      NO RESULT ({elapsed:.1f}s)")
                    results['failed'] += 1

            except Exception as e:
                elapsed = time.time() - start
                error_str = str(e).lower()
                if 'blocked' in error_str or 'captcha' in error_str or '403' in error_str or '429' in error_str:
                    logger.error(f"      BLOCKED ({elapsed:.1f}s): {str(e)[:50]}")
                    results['blocked'] += 1
                else:
                    logger.error(f"      ERROR ({elapsed:.1f}s): {str(e)[:50]}")
                    results['failed'] += 1
                results['errors'].append({'domain': domain, 'error': str(e)[:100]})

            time.sleep(5)  # Longer delay for competitor crawling

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Test ALL SEO Selenium modules')
    parser.add_argument('--urls', type=int, default=10, help='Number of URLs to test')
    parser.add_argument('--modules', type=str, default='1,2,3,4', help='Modules to test (1=Technical, 2=CWV, 3=Backlink, 4=Competitor)')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("SEO SELENIUM UC MODULE TESTING - MAX STEALTH")
    logger.info("=" * 70)
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"URLs to test: {args.urls}")
    logger.info(f"Mode: Headed browsers (non-headless) for maximum stealth")
    logger.info(f"Proxy: Enabled")
    logger.info("=" * 70)

    # Get real URLs
    logger.info("\nFetching real URLs from database...")
    urls = get_real_urls(args.urls)
    logger.info(f"Got {len(urls)} URLs")

    for i, (url, name) in enumerate(urls, 1):
        logger.info(f"  {i}. {name[:40]} - {url[:50]}")

    # Parse modules to test
    modules_to_test = [int(m.strip()) for m in args.modules.split(',')]

    # Run tests
    all_results = {}

    if 1 in modules_to_test:
        all_results['technical_auditor_selenium'] = test_technical_auditor_selenium(urls)
        logger.info(f"\nModule 1 Summary: {all_results['technical_auditor_selenium']['passed']} passed, "
                   f"{all_results['technical_auditor_selenium']['failed']} failed, "
                   f"{all_results['technical_auditor_selenium']['blocked']} blocked")

    if 2 in modules_to_test:
        all_results['core_web_vitals_selenium'] = test_core_web_vitals_selenium(urls)
        logger.info(f"\nModule 2 Summary: {all_results['core_web_vitals_selenium']['passed']} passed, "
                   f"{all_results['core_web_vitals_selenium']['failed']} failed, "
                   f"{all_results['core_web_vitals_selenium']['blocked']} blocked")

    if 3 in modules_to_test:
        all_results['backlink_crawler_selenium'] = test_backlink_crawler_selenium(urls)
        logger.info(f"\nModule 3 Summary: {all_results['backlink_crawler_selenium']['passed']} passed, "
                   f"{all_results['backlink_crawler_selenium']['failed']} failed, "
                   f"{all_results['backlink_crawler_selenium']['blocked']} blocked")

    if 4 in modules_to_test:
        all_results['competitor_crawler_selenium'] = test_competitor_crawler_selenium(urls)
        logger.info(f"\nModule 4 Summary: {all_results['competitor_crawler_selenium']['passed']} passed, "
                   f"{all_results['competitor_crawler_selenium']['failed']} failed, "
                   f"{all_results['competitor_crawler_selenium']['blocked']} blocked")

    # Final summary
    logger.info("\n" + "=" * 70)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 70)

    total_passed = sum(r['passed'] for r in all_results.values())
    total_failed = sum(r['failed'] for r in all_results.values())
    total_blocked = sum(r['blocked'] for r in all_results.values())
    total = total_passed + total_failed + total_blocked

    for module, results in all_results.items():
        module_total = results['passed'] + results['failed'] + results['blocked']
        status = "PASS" if results['blocked'] == 0 and results['passed'] > 0 else "ISSUES"
        logger.info(f"  {module}: {results['passed']}/{module_total} passed "
                   f"({results['blocked']} blocked) - {status}")

    logger.info(f"\nOverall: {total_passed}/{total} passed ({total_blocked} blocked)")

    if total_blocked > 0:
        logger.warning("\n*** BLOCKING DETECTED! Some requests were blocked or timed out ***")
    else:
        logger.info("\n*** SUCCESS - No blocking detected! Max stealth working! ***")

    # Save results
    output_path = log_dir / f'seo_selenium_all_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'urls_tested': len(urls),
            'stealth_config': {
                'headless': False,
                'proxy': True,
                'uc_mode': True,
            },
            'results': all_results,
            'summary': {
                'total_passed': total_passed,
                'total_failed': total_failed,
                'total_blocked': total_blocked,
            }
        }, f, indent=2)

    logger.info(f"\nResults saved to: {output_path}")


if __name__ == '__main__':
    main()
