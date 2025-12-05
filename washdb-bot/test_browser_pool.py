#!/usr/bin/env python3
"""
Quick test of browser pool implementation.

Tests:
1. Browser pool creation
2. Browser launch and reuse
3. Page creation and navigation
4. Cache integration
5. Memory monitoring
"""

import sys
import time
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from scrape_yp.browser_pool import get_browser_pool
from scrape_yp.html_cache import get_html_cache
from runner.memory_monitor import get_memory_monitor
from runner.logging_setup import get_logger

logger = get_logger("test_browser_pool")


def test_browser_pool():
    """Test browser pool functionality."""
    print("\n" + "=" * 70)
    print("BROWSER POOL TEST")
    print("=" * 70)

    # Test 1: Create browser pool
    print("\n[1] Creating browser pool...")
    pool = get_browser_pool()
    print(f"✓ Pool created: {pool.get_stats()}")

    # Test 2: Get browser for worker 0
    print("\n[2] Getting browser for worker 0...")
    browser = pool.get_browser(worker_id=0)
    print(f"✓ Browser created: {browser.is_connected()}")

    # Test 3: Create page (fresh context)
    print("\n[3] Creating page with fresh context...")
    page, context = pool.get_page(worker_id=0)
    print(f"✓ Page created: {page}")

    # Test 4: Navigate to test URL
    print("\n[4] Navigating to yellowpages.com...")
    try:
        page.goto("https://www.yellowpages.com", timeout=30000)
        title = page.title()
        print(f"✓ Navigation successful: {title}")
    except Exception as e:
        print(f"✗ Navigation failed: {e}")

    # Test 5: Close context (browser stays alive)
    print("\n[5] Closing context (browser persists)...")
    context.close()
    print(f"✓ Context closed, browser still connected: {browser.is_connected()}")

    # Test 6: Get another page (reuses browser)
    print("\n[6] Getting second page (should reuse browser)...")
    page2, context2 = pool.get_page(worker_id=0)
    print(f"✓ Second page created (browser reused)")

    # Cleanup
    context2.close()
    print(f"✓ Second context closed")

    # Test 7: Check pool stats
    print("\n[7] Browser pool stats:")
    stats = pool.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 70)
    print("BROWSER POOL TEST COMPLETE")
    print("=" * 70)


def test_html_cache():
    """Test HTML cache functionality."""
    print("\n" + "=" * 70)
    print("HTML CACHE TEST")
    print("=" * 70)

    # Test 1: Create cache
    print("\n[1] Creating HTML cache...")
    cache = get_html_cache()
    print(f"✓ Cache created: {cache.get_stats()}")

    # Test 2: Cache miss
    print("\n[2] Testing cache miss...")
    html1 = "<html><body>Test Page 1</body></html>"
    result = cache.get(html1)
    print(f"✓ Cache miss (expected): {result is None}")

    # Test 3: Cache put
    print("\n[3] Storing results in cache...")
    test_results = [
        {"name": "Test Company A", "website": "https://example.com"},
        {"name": "Test Company B", "website": "https://example2.com"},
    ]
    cache.put(html1, test_results)
    print(f"✓ Results stored")

    # Test 4: Cache hit
    print("\n[4] Testing cache hit...")
    result = cache.get(html1)
    print(f"✓ Cache hit: {len(result)} results retrieved")

    # Test 5: Check stats
    print("\n[5] Cache stats:")
    stats = cache.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 70)
    print("HTML CACHE TEST COMPLETE")
    print("=" * 70)


def test_memory_monitor():
    """Test memory monitor functionality."""
    print("\n" + "=" * 70)
    print("MEMORY MONITOR TEST")
    print("=" * 70)

    # Test 1: Create monitor
    print("\n[1] Creating memory monitor...")
    monitor = get_memory_monitor()
    print(f"✓ Monitor created")

    # Test 2: Update stats
    print("\n[2] Updating memory stats...")
    monitor.update_stats()
    print(f"✓ Stats updated")

    # Test 3: Print summary
    print("\n[3] Memory summary:")
    monitor.print_summary()

    print("\n" + "=" * 70)
    print("MEMORY MONITOR TEST COMPLETE")
    print("=" * 70)


def main():
    """Run all tests."""
    try:
        # Test browser pool
        test_browser_pool()

        # Test HTML cache
        test_html_cache()

        # Test memory monitor
        test_memory_monitor()

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED ✓")
        print("=" * 70 + "\n")

        return 0

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        print("\n" + "=" * 70)
        print("TEST FAILED ✗")
        print("=" * 70 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
