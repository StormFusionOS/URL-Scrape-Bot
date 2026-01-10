#!/usr/bin/env python3
"""
Test SEO modules with real URLs from the database.
Tests for blocking/detection issues.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path

# Add project root to path
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
        logging.FileHandler(log_dir / 'seo_real_url_tests.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('seo_real_url_tests')

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

def test_technical_auditor(urls: list) -> dict:
    """Test TechnicalAuditor module."""
    logger.info("=" * 60)
    logger.info("Testing Module 1: TechnicalAuditor")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers import TechnicalAuditor
        auditor = TechnicalAuditor(headless=True)

        for i, (url, name) in enumerate(urls, 1):
            logger.info(f"  [{i}/{len(urls)}] Testing: {url[:50]}...")
            start = time.time()

            try:
                result = auditor.audit_page(url)
                elapsed = time.time() - start

                if result and result.get('passed_checks') is not None:
                    # Check for blocking indicators
                    issues = result.get('issues', [])
                    blocked_indicators = ['captcha', 'blocked', 'forbidden', '403', '429']
                    is_blocked = any(
                        any(ind in str(issue).lower() for ind in blocked_indicators)
                        for issue in issues
                    )

                    if is_blocked:
                        logger.warning(f"      BLOCKED ({elapsed:.1f}s) - {name[:30]}")
                        results['blocked'] += 1
                    else:
                        logger.info(f"      OK ({elapsed:.1f}s) - {len(result.get('passed_checks', []))} checks passed")
                        results['passed'] += 1
                else:
                    logger.warning(f"      EMPTY RESULT ({elapsed:.1f}s)")
                    results['failed'] += 1

            except Exception as e:
                elapsed = time.time() - start
                error_str = str(e).lower()
                if 'timeout' in error_str or '403' in error_str or '429' in error_str:
                    logger.error(f"      BLOCKED/TIMEOUT ({elapsed:.1f}s): {str(e)[:50]}")
                    results['blocked'] += 1
                else:
                    logger.error(f"      ERROR ({elapsed:.1f}s): {str(e)[:50]}")
                    results['failed'] += 1
                results['errors'].append({'url': url, 'error': str(e)[:100]})

            # Small delay between requests
            time.sleep(2)

        auditor.close()

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results

def test_core_web_vitals(urls: list) -> dict:
    """Test CoreWebVitalsCollector module."""
    logger.info("=" * 60)
    logger.info("Testing Module 2: CoreWebVitalsCollector")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers import CoreWebVitalsCollector
        collector = CoreWebVitalsCollector(headless=True)

        for i, (url, name) in enumerate(urls, 1):
            logger.info(f"  [{i}/{len(urls)}] Testing: {url[:50]}...")
            start = time.time()

            try:
                result = collector.measure_url(url, samples=1)
                elapsed = time.time() - start

                if result and (result.get('lcp_ms') or result.get('fcp_ms')):
                    logger.info(f"      OK ({elapsed:.1f}s) - LCP={result.get('lcp_ms')}ms, Grade={result.get('grade')}")
                    results['passed'] += 1
                else:
                    logger.warning(f"      NO DATA ({elapsed:.1f}s)")
                    results['failed'] += 1

            except Exception as e:
                elapsed = time.time() - start
                logger.error(f"      ERROR ({elapsed:.1f}s): {str(e)[:50]}")
                results['failed'] += 1
                results['errors'].append({'url': url, 'error': str(e)[:100]})

            time.sleep(2)

        collector.close()

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results

def test_backlink_crawler(urls: list) -> dict:
    """Test BacklinkCrawler module."""
    logger.info("=" * 60)
    logger.info("Testing Module 6: BacklinkCrawler")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers import BacklinkCrawler
        crawler = BacklinkCrawler(headless=True)

        # Use first few URLs as target domains to check for
        target_domains = [url.replace('http://', '').replace('https://', '').split('/')[0]
                        for url, _ in urls[:3]]

        for i, (url, name) in enumerate(urls[:5], 1):  # Just test 5
            logger.info(f"  [{i}/5] Testing: {url[:50]}...")
            start = time.time()

            try:
                result = crawler.check_page_for_backlinks(url, target_domains)
                elapsed = time.time() - start

                if result is not None:
                    backlinks = result.get('backlinks_found', 0) if isinstance(result, dict) else 0
                    logger.info(f"      OK ({elapsed:.1f}s) - {backlinks} backlinks found")
                    results['passed'] += 1
                else:
                    logger.warning(f"      NO RESULT ({elapsed:.1f}s)")
                    results['failed'] += 1

            except Exception as e:
                elapsed = time.time() - start
                error_str = str(e).lower()
                if 'blocked' in error_str or 'captcha' in error_str or '403' in error_str:
                    logger.error(f"      BLOCKED ({elapsed:.1f}s): {str(e)[:50]}")
                    results['blocked'] += 1
                else:
                    logger.error(f"      ERROR ({elapsed:.1f}s): {str(e)[:50]}")
                    results['failed'] += 1
                results['errors'].append({'url': url, 'error': str(e)[:100]})

            time.sleep(3)

        crawler.close()

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results

def test_competitor_crawler(urls: list) -> dict:
    """Test CompetitorCrawler module."""
    logger.info("=" * 60)
    logger.info("Testing Module 7: CompetitorCrawler")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers import CompetitorCrawler
        crawler = CompetitorCrawler(headless=True, max_pages=3)

        # Extract domains from URLs
        domains = []
        for url, name in urls[:5]:  # Just test 5 domains
            domain = url.replace('http://', '').replace('https://', '').split('/')[0]
            domains.append((domain, name))

        for i, (domain, name) in enumerate(domains, 1):
            logger.info(f"  [{i}/{len(domains)}] Testing: {domain}...")
            start = time.time()

            try:
                result = crawler.crawl_competitor(domain, max_depth=1)
                elapsed = time.time() - start

                if result:
                    pages = result.get('pages_crawled', 0)
                    words = result.get('total_word_count', 0)
                    logger.info(f"      OK ({elapsed:.1f}s) - {pages} pages, {words} words")
                    results['passed'] += 1
                else:
                    logger.warning(f"      NO RESULT ({elapsed:.1f}s)")
                    results['failed'] += 1

            except Exception as e:
                elapsed = time.time() - start
                error_str = str(e).lower()
                if 'blocked' in error_str or 'captcha' in error_str or '403' in error_str:
                    logger.error(f"      BLOCKED ({elapsed:.1f}s): {str(e)[:50]}")
                    results['blocked'] += 1
                else:
                    logger.error(f"      ERROR ({elapsed:.1f}s): {str(e)[:50]}")
                    results['failed'] += 1
                results['errors'].append({'domain': domain, 'error': str(e)[:100]})

            time.sleep(5)  # Longer delay for competitor crawling

        crawler.close()

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Test SEO modules with real URLs')
    parser.add_argument('--urls', type=int, default=10, help='Number of URLs to test')
    parser.add_argument('--modules', type=str, default='1,2,6,7', help='Modules to test (comma-separated)')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("SEO MODULE REAL URL TESTING")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"URLs to test: {args.urls}")
    logger.info(f"Modules: {args.modules}")
    logger.info("=" * 60)

    # Get real URLs from database
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
        all_results['technical_auditor'] = test_technical_auditor(urls)
        logger.info(f"\nModule 1 Summary: {all_results['technical_auditor']['passed']} passed, "
                   f"{all_results['technical_auditor']['failed']} failed, "
                   f"{all_results['technical_auditor']['blocked']} blocked")

    if 2 in modules_to_test:
        all_results['core_web_vitals'] = test_core_web_vitals(urls)
        logger.info(f"\nModule 2 Summary: {all_results['core_web_vitals']['passed']} passed, "
                   f"{all_results['core_web_vitals']['failed']} failed, "
                   f"{all_results['core_web_vitals']['blocked']} blocked")

    if 6 in modules_to_test:
        all_results['backlink_crawler'] = test_backlink_crawler(urls)
        logger.info(f"\nModule 6 Summary: {all_results['backlink_crawler']['passed']} passed, "
                   f"{all_results['backlink_crawler']['failed']} failed, "
                   f"{all_results['backlink_crawler']['blocked']} blocked")

    if 7 in modules_to_test:
        all_results['competitor_crawler'] = test_competitor_crawler(urls)
        logger.info(f"\nModule 7 Summary: {all_results['competitor_crawler']['passed']} passed, "
                   f"{all_results['competitor_crawler']['failed']} failed, "
                   f"{all_results['competitor_crawler']['blocked']} blocked")

    # Final summary
    logger.info("\n" + "=" * 60)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 60)

    total_passed = sum(r['passed'] for r in all_results.values())
    total_failed = sum(r['failed'] for r in all_results.values())
    total_blocked = sum(r['blocked'] for r in all_results.values())
    total = total_passed + total_failed + total_blocked

    for module, results in all_results.items():
        status = "PASS" if results['blocked'] == 0 and results['passed'] > 0 else "ISSUES"
        logger.info(f"  {module}: {results['passed']}/{results['passed']+results['failed']+results['blocked']} passed "
                   f"({results['blocked']} blocked) - {status}")

    logger.info(f"\nOverall: {total_passed}/{total} passed ({total_blocked} blocked)")

    if total_blocked > 0:
        logger.warning("\n*** BLOCKING DETECTED! Some requests were blocked or timed out ***")
    else:
        logger.info("\n*** No blocking detected - stealth features working ***")

    # Save results
    output_path = log_dir / f'seo_real_url_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'urls_tested': len(urls),
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
