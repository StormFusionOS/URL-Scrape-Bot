#!/usr/bin/env python3
"""
Integration test for YP scraper with browser pool and cache.

This test simulates a single worker processing a real YP target
to verify the full workflow with persistent browsers and caching.
"""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from scrape_yp.yp_crawl_city_first import fetch_city_category_page
from scrape_yp.yp_parser_enhanced import parse_yp_results_enhanced
from scrape_yp.browser_pool import get_browser_pool
from scrape_yp.html_cache import get_html_cache
from runner.memory_monitor import get_memory_monitor
from runner.logging_setup import get_logger

logger = get_logger("test_yp_integration")


def test_yp_scrape():
    """Test full YP scraping workflow with browser pool and cache."""
    print("\n" + "=" * 70)
    print("YP INTEGRATION TEST")
    print("=" * 70)

    # Initialize components
    print("\n[1] Initializing components...")
    pool = get_browser_pool()
    cache = get_html_cache()
    monitor = get_memory_monitor()
    print(f"✓ Browser pool: {pool.get_stats()['active_browsers']} browsers")
    print(f"✓ HTML cache: {cache.get_stats()['size']} entries")

    # Test URL: Plumbing contractors in Seattle, WA
    test_url = "https://www.yellowpages.com/seattle-wa/plumbers"
    worker_id = 0

    # First fetch (cache miss, browser creation)
    print(f"\n[2] First fetch: {test_url}")
    print("    (Should create browser, cache miss)")
    try:
        html1 = fetch_city_category_page(test_url, page=1, worker_id=worker_id)
        print(f"✓ Fetched {len(html1):,} bytes of HTML")

        # Parse results (will cache)
        results1 = parse_yp_results_enhanced(html1)
        print(f"✓ Parsed {len(results1)} listings")

        # Show cache stats
        cache_stats = cache.get_stats()
        print(f"✓ Cache: {cache_stats['size']} entries, {cache_stats['hit_rate_pct']:.1f}% hit rate")

    except Exception as e:
        print(f"✗ First fetch failed: {e}")
        logger.error(f"First fetch failed: {e}", exc_info=True)
        return False

    # Second fetch (same URL - should be MUCH faster with browser reuse)
    print(f"\n[3] Second fetch (same URL)")
    print("    (Should reuse browser, potentially cache hit)")
    try:
        html2 = fetch_city_category_page(test_url, page=1, worker_id=worker_id)
        print(f"✓ Fetched {len(html2):,} bytes of HTML")

        # Parse results (may be cache hit if HTML identical)
        results2 = parse_yp_results_enhanced(html2)
        print(f"✓ Parsed {len(results2)} listings")

        # Show cache stats
        cache_stats = cache.get_stats()
        print(f"✓ Cache: {cache_stats['size']} entries, {cache_stats['hit_rate_pct']:.1f}% hit rate")

    except Exception as e:
        print(f"✗ Second fetch failed: {e}")
        logger.error(f"Second fetch failed: {e}", exc_info=True)
        return False

    # Third fetch (page 2 - different page, browser reuse)
    print(f"\n[4] Third fetch (page 2)")
    print("    (Should reuse browser, cache miss for new page)")
    try:
        html3 = fetch_city_category_page(test_url, page=2, worker_id=worker_id)
        print(f"✓ Fetched {len(html3):,} bytes of HTML")

        # Parse results
        results3 = parse_yp_results_enhanced(html3)
        print(f"✓ Parsed {len(results3)} listings")

        # Show cache stats
        cache_stats = cache.get_stats()
        print(f"✓ Cache: {cache_stats['size']} entries, {cache_stats['hit_rate_pct']:.1f}% hit rate")

    except Exception as e:
        print(f"✗ Third fetch failed: {e}")
        logger.error(f"Third fetch failed: {e}", exc_info=True)
        return False

    # Check browser pool stats
    print(f"\n[5] Browser pool statistics:")
    pool_stats = pool.get_stats()
    print(f"  Active browsers: {pool_stats['active_browsers']}")
    print(f"  Total pages served: {pool_stats['total_pages_served']}")
    print(f"  Worker 0 usage: {pool_stats['usage_counts'].get(0, 0)}/{pool_stats['max_uses_per_browser']}")

    # Check memory usage
    print(f"\n[6] Memory statistics:")
    monitor.update_stats()
    stats = monitor.get_stats()
    sys_mem = stats['system']
    comp_mem = stats['components']

    print(f"  System: {sys_mem['used_gb']:.1f} GB / {sys_mem['total_gb']:.1f} GB ({sys_mem['percent']:.1f}%)")

    if 'browser_pool' in comp_mem and 'error' not in comp_mem['browser_pool']:
        bp = comp_mem['browser_pool']
        print(f"  Browser pool: {bp['active_browsers']} browsers (~{bp['estimated_memory_gb']:.2f} GB)")

    if 'html_cache' in comp_mem and 'error' not in comp_mem['html_cache']:
        hc = comp_mem['html_cache']
        print(f"  HTML cache: {hc['size']}/{hc['max_size']} entries, {hc['hit_rate_pct']:.1f}% hit rate")

    # Sample results
    print(f"\n[7] Sample results (first 3 from last fetch):")
    for i, result in enumerate(results3[:3], 1):
        print(f"\n  {i}. {result.get('name', 'N/A')}")
        print(f"     Website: {result.get('website', 'N/A')}")
        print(f"     Phone: {result.get('phone', 'N/A')}")

    print("\n" + "=" * 70)
    print("YP INTEGRATION TEST COMPLETE ✓")
    print("=" * 70)

    return True


def main():
    """Run integration test."""
    try:
        success = test_yp_scrape()

        if success:
            print("\n✓ Integration test PASSED")
            return 0
        else:
            print("\n✗ Integration test FAILED")
            return 1

    except Exception as e:
        logger.error(f"Integration test failed: {e}", exc_info=True)
        print(f"\n✗ Integration test FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
