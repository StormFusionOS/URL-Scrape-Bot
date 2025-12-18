#!/usr/bin/env python3
"""
Test SEO modules using SeleniumBase Undetected Chrome.
Tests the Selenium versions which have better anti-detection.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path

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
        logging.FileHandler(log_dir / 'seo_selenium_tests.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('seo_selenium_tests')

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
    logger.info("Testing: TechnicalAuditorSelenium (UC Mode)")
    logger.info("=" * 60)

    results = {'passed': 0, 'failed': 0, 'blocked': 0, 'errors': []}

    try:
        from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium
        
        # Use non-headless for better stealth (Xvfb handles display)
        auditor = TechnicalAuditorSelenium(headless=False, use_proxy=True)

        for i, (url, name) in enumerate(urls, 1):
            logger.info(f"  [{i}/{len(urls)}] Testing: {url[:50]}...")
            start = time.time()

            try:
                result = auditor.audit_page(url)
                elapsed = time.time() - start

                # AuditResult is a dataclass with attributes, not a dict
                if result and hasattr(result, 'passed_checks'):
                    # Check for blocking indicators in issues
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

            # Delay between requests
            time.sleep(3)

    except Exception as e:
        logger.error(f"Module init error: {e}")
        results['errors'].append({'init': str(e)})

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Test SEO modules with SeleniumBase UC')
    parser.add_argument('--urls', type=int, default=5, help='Number of URLs to test')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("SEO MODULE SELENIUM UC TESTING")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"URLs to test: {args.urls}")
    logger.info("=" * 60)

    # Get real URLs
    logger.info("\nFetching real URLs from database...")
    urls = get_real_urls(args.urls)
    logger.info(f"Got {len(urls)} URLs")

    for i, (url, name) in enumerate(urls, 1):
        logger.info(f"  {i}. {name[:40]} - {url[:50]}")

    # Run tests
    results = test_technical_auditor_selenium(urls)
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("RESULTS SUMMARY")
    logger.info("=" * 60)
    
    total = results['passed'] + results['failed'] + results['blocked']
    logger.info(f"  Passed:  {results['passed']}/{total}")
    logger.info(f"  Failed:  {results['failed']}/{total}")
    logger.info(f"  Blocked: {results['blocked']}/{total}")
    
    if results['blocked'] > 0:
        logger.warning("\n*** BLOCKING DETECTED! ***")
    else:
        logger.info("\n*** SUCCESS - No blocking detected! ***")

    # Save results
    output_path = log_dir / f'seo_selenium_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'urls_tested': len(urls),
            'results': results,
        }, f, indent=2)

    logger.info(f"\nResults saved to: {output_path}")


if __name__ == '__main__':
    main()
