#!/usr/bin/env python3
"""Test remaining SEO modules (8. KeywordIntelligence, 9. CompetitiveAnalysis)."""

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
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'seo_remaining_modules_test.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('seo_remaining_test')


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


def test_keyword_intelligence(urls: list) -> dict:
    """Test Keyword Intelligence module."""
    from seo_intelligence.scrapers.keyword_intelligence_selenium import KeywordIntelligenceSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}

    try:
        intel = KeywordIntelligenceSelenium()  # Uses headed mode + proxy by default

        # Use fewer keywords with longer delays
        keywords = ["pressure washing", "gutter cleaning"]

        for keyword in keywords:
            logger.info(f"  Testing keyword analysis for: {keyword}...")

            result = intel.analyze_keyword(keyword, include_related=False, include_questions=False)
            if result:
                logger.info(f"    OK - Analysis complete")
                results['passed'] += 1
                results['details'].append({'keyword': keyword, 'result': 'success'})
            else:
                results['failed'] += 1

            logger.info(f"    Waiting 30s before next keyword...")
            time.sleep(30)

    except Exception as e:
        logger.error(f"    ERROR: {str(e)[:100]}")
        results['failed'] += 1
        results['errors'].append({'error': str(e)[:100]})

    return results


def test_competitive_analysis(urls: list) -> dict:
    """Test Competitive Analysis module."""
    from seo_intelligence.scrapers.competitive_analysis_selenium import CompetitiveAnalysisSelenium

    results = {'passed': 0, 'failed': 0, 'errors': [], 'details': []}

    try:
        analyzer = CompetitiveAnalysisSelenium()  # Uses headed mode + proxy by default

        # Use first URL as the target business
        cid, name, std_name, url = urls[0]
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')

        logger.info(f"  Testing competitive analysis for: {domain}...")

        # Use fewer keywords
        result = analyzer.analyze_serp_competitors(
            your_domain=domain,
            target_keywords=["pressure washing", "exterior cleaning"]
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
        logger.error(f"    ERROR: {str(e)[:100]}")
        results['failed'] += 1
        results['errors'].append({'error': str(e)[:100]})

    return results


def main():
    logger.info("=" * 70)
    logger.info("SEO REMAINING MODULES TEST (8 & 9)")
    logger.info("=" * 70)
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("=" * 70)

    # Get URLs
    logger.info("\nFetching verified/standardized URLs from database...")
    urls = get_verified_standardized_urls(5)
    logger.info(f"Got {len(urls)} URLs")

    for i, (cid, name, std_name, url) in enumerate(urls, 1):
        logger.info(f"  {i}. [{cid}] {std_name or name}")

    # Run remaining module tests
    all_results = {}

    modules = [
        ("8. KeywordIntelligence", test_keyword_intelligence),
        ("9. CompetitiveAnalysis", test_competitive_analysis),
    ]

    for name, test_func in modules:
        result = test_module(name, test_func, urls)
        all_results[name] = result

    # Final summary
    logger.info("\n" + "=" * 70)
    logger.info("FINAL SUMMARY - REMAINING MODULES")
    logger.info("=" * 70)

    total_passed = sum(r['passed'] for r in all_results.values())
    total_failed = sum(r['failed'] for r in all_results.values())
    modules_working = sum(1 for r in all_results.values() if r['status'] == 'pass')

    for name, result in all_results.items():
        status_icon = "OK" if result['status'] == 'pass' else "FAIL" if result['status'] == 'fail' else "ERR"
        logger.info(f"  [{status_icon}] {name}: {result['passed']} passed, {result['failed']} failed ({result['elapsed']}s)")

    logger.info(f"\n  Modules Working: {modules_working}/2")
    logger.info(f"  Total Tests: {total_passed} passed, {total_failed} failed")

    # Save results
    output_path = log_dir / f'seo_remaining_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'modules_working': modules_working,
            'results': all_results,
        }, f, indent=2, default=str)

    logger.info(f"\nResults saved to: {output_path}")

    return modules_working == 2


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
