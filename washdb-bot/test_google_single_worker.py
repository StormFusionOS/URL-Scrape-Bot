#!/usr/bin/env python3
"""
Test script for Google Maps single worker with browser pool optimization.

This script validates:
1. Browser pool initialization (persistent browsers)
2. HTML cache initialization
3. Single target processing with optimizations
4. Performance metrics (browser pool stats, cache hit rate)

Usage:
    python test_google_single_worker.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from scrape_google.browser_pool import get_browser_pool
from scrape_google.html_cache import get_html_cache
from scrape_google.google_crawl_city_first import crawl_single_target
from db import create_session
from db.models import GoogleTarget


async def test_browser_pool():
    """Test browser pool initialization and basic functionality."""
    print("\n" + "="*70)
    print("TEST 1: Browser Pool Initialization")
    print("="*70)

    # Get browser pool
    pool = await get_browser_pool()
    print(f"✓ Browser pool created")

    # Get stats
    stats = await pool.get_stats()
    print(f"  - Worker count: {stats['worker_count']}")
    print(f"  - Active browsers: {stats['active_browsers']}")
    print(f"  - Max uses per browser: {stats['max_uses_per_browser']}")

    # Test getting a page for worker 0
    print("\nTesting page creation for worker 0...")
    page, context = await pool.get_page(0)
    print(f"✓ Page created successfully")

    # Test navigation
    print("Testing navigation to Google Maps...")
    await page.goto("https://www.google.com/maps", timeout=10000)
    title = await page.title()
    print(f"✓ Navigation successful: {title}")

    # Close context (browser persists)
    await context.close()
    print(f"✓ Context closed (browser persists in pool)")

    # Check stats after use
    stats = await pool.get_stats()
    print(f"\nBrowser Pool Stats:")
    print(f"  - Active browsers: {stats['active_browsers']}")
    print(f"  - Total pages served: {stats['total_pages_served']}")
    print(f"  - Usage counts: {stats['usage_counts']}")

    return pool


def test_html_cache():
    """Test HTML cache initialization."""
    print("\n" + "="*70)
    print("TEST 2: HTML Cache Initialization")
    print("="*70)

    # Get HTML cache
    cache = get_html_cache()
    print(f"✓ HTML cache created")

    # Get stats
    stats = cache.get_stats()
    print(f"  - Max size: {stats['max_size']}")
    print(f"  - TTL: {stats['ttl_hours']} hours")
    print(f"  - Current size: {stats['size']}")

    # Test cache operations
    print("\nTesting cache operations...")
    test_html = "<html><body>Test page</body></html>"
    test_results = [{"name": "Test Business", "place_id": "12345"}]

    # Test miss
    result = cache.get(test_html)
    assert result is None, "Expected cache miss"
    print(f"✓ Cache miss detected correctly")

    # Test put
    cache.put(test_html, test_results)
    print(f"✓ Cache put successful")

    # Test hit
    result = cache.get(test_html)
    assert result == test_results, "Expected cache hit"
    print(f"✓ Cache hit detected correctly")

    # Get stats
    stats = cache.get_stats()
    print(f"\nHTML Cache Stats:")
    print(f"  - Total requests: {stats['total_requests']}")
    print(f"  - Hits: {stats['hits']}")
    print(f"  - Misses: {stats['misses']}")
    print(f"  - Hit rate: {stats['hit_rate_pct']:.1f}%")

    return cache


async def test_single_target_processing(pool):
    """Test processing a single Google target with optimizations."""
    print("\n" + "="*70)
    print("TEST 3: Single Target Processing")
    print("="*70)

    # Get a pending Google target from database
    session = create_session()

    try:
        # Find a pending target (preferably with low max_results for quick test)
        target = (
            session.query(GoogleTarget)
            .filter(GoogleTarget.status == "PENDING")
            .order_by(GoogleTarget.max_results.asc())
            .first()
        )

        if not target:
            print("⚠ No pending Google targets found in database")
            print("  Skipping target processing test")
            return

        print(f"\nFound target:")
        print(f"  - ID: {target.id}")
        print(f"  - City: {target.city}, {target.state_id}")
        print(f"  - Category: {target.category_label}")
        print(f"  - Max results: {target.max_results}")

        print(f"\nProcessing target with worker_id=0...")

        # Process target with browser pool (worker_id=0)
        accepted_results, stats = await crawl_single_target(
            target=target,
            session=session,
            scrape_details=False,  # Skip details for faster test
            save_to_db=True,
            worker_id=0
        )

        print(f"\n✓ Target processing complete!")
        print(f"  - Accepted results: {len(accepted_results)}")
        print(f"  - Total found: {stats.get('total_found', 0)}")
        print(f"  - Filtered out: {stats.get('filtered_out', 0)}")
        print(f"  - Total saved: {stats.get('total_saved', 0)}")

    except Exception as e:
        print(f"\n✗ Target processing failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


async def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("GOOGLE MAPS OPTIMIZATION TEST SUITE")
    print("="*70)
    print(f"Testing browser pool and HTML cache integration")
    print(f"Worker ID: 0 (simulating first worker)")
    print("="*70)

    try:
        # Test 1: Browser pool
        pool = await test_browser_pool()

        # Test 2: HTML cache
        cache = test_html_cache()

        # Test 3: Single target processing (optional - requires DB targets)
        await test_single_target_processing(pool)

        # Final stats
        print("\n" + "="*70)
        print("FINAL PERFORMANCE METRICS")
        print("="*70)

        pool_stats = await pool.get_stats()
        print(f"\nBrowser Pool:")
        print(f"  - Active browsers: {pool_stats['active_browsers']}")
        print(f"  - Total pages served: {pool_stats['total_pages_served']}")

        cache_stats = cache.get_stats()
        print(f"\nHTML Cache:")
        print(f"  - Size: {cache_stats['size']}/{cache_stats['max_size']}")
        print(f"  - Hit rate: {cache_stats['hit_rate_pct']:.1f}%")

        # Cleanup
        print("\n" + "="*70)
        print("Cleaning up...")
        await pool.cleanup()
        print("✓ Browser pool cleaned up")

        print("\n" + "="*70)
        print("TEST SUITE COMPLETE ✓")
        print("="*70)

    except Exception as e:
        print(f"\n✗ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
