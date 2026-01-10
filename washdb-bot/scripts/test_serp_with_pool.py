#!/usr/bin/env python3
"""
Test SERP scraping with the Enterprise Browser Pool enabled.

This script demonstrates the browser pool integration with the SERP scraper.
"""

import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Enable browser pool
os.environ["BROWSER_POOL_ENABLED"] = "true"
os.environ["BROWSER_POOL_MIN_SESSIONS"] = "2"
os.environ["BROWSER_POOL_MAX_SESSIONS"] = "4"

from runner.logging_setup import get_logger
from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium
from seo_intelligence.drivers import get_browser_pool, get_pool_metrics, reset_pool_metrics

logger = get_logger("test_serp_pool")


def main():
    print("=" * 70)
    print("SERP Scraper Test with Enterprise Browser Pool")
    print("=" * 70)
    print()

    # Reset metrics for clean test
    reset_pool_metrics()

    # Check pool status
    pool = get_browser_pool()
    print(f"Pool enabled: {pool.is_enabled()}")
    print(f"Waiting for pool to initialize (this may take up to 60 seconds)...")
    print()

    # Wait for pool to have at least one warm session
    start_wait = time.time()
    max_wait = 90  # seconds
    while time.time() - start_wait < max_wait:
        stats = pool.get_stats()
        warm_count = stats.sessions_by_state.get('idle_warm', 0)
        warming_count = stats.sessions_by_state.get('warming', 0)
        total = stats.total_sessions

        print(f"  Pool status: {total} total, {warm_count} warm, {warming_count} warming...")

        if warm_count > 0:
            print(f"  Pool ready with {warm_count} warm session(s)")
            break

        time.sleep(5)
    else:
        print("  Warning: Pool initialization timed out, proceeding anyway")

    print()

    # Create SERP scraper
    scraper = SerpScraperSelenium(
        headless=True,
        use_proxy=True,
    )

    # Test query
    keyword = "pressure washing services austin tx"

    print(f"Running SERP scrape:")
    print(f"  Keyword: {keyword}")
    print()

    try:
        # Run the scrape (use_coordinator=False to use browser pool directly)
        start_time = time.time()
        result = scraper.scrape_serp(
            keyword=keyword,
            num_results=10,
            use_coordinator=False,  # Use browser pool instead of GoogleCoordinator
        )
        elapsed = time.time() - start_time

        print()
        print(f"Scrape completed in {elapsed:.1f} seconds")
        print()

        if result:
            print(f"Results:")
            print(f"  Query: {result.get('query', 'N/A')}")
            print(f"  Total results: {result.get('total_results', 0)}")

            organic = result.get('organic_results', [])
            print(f"  Organic results: {len(organic)}")

            if organic:
                print()
                print("  Top 5 organic results:")
                for i, r in enumerate(organic[:5], 1):
                    title = r.get('title', 'No title')[:50]
                    url = r.get('url', 'No URL')[:60]
                    print(f"    {i}. {title}")
                    print(f"       {url}")

            local = result.get('local_pack', [])
            if local:
                print()
                print(f"  Local pack results: {len(local)}")
                for i, r in enumerate(local[:3], 1):
                    name = r.get('name', 'No name')
                    print(f"    {i}. {name}")
        else:
            print("No results returned")

    except Exception as e:
        print(f"Error during scrape: {e}")
        import traceback
        traceback.print_exc()

    # Show pool metrics
    print()
    print("=" * 70)
    print("Pool Metrics")
    print("=" * 70)

    metrics = get_pool_metrics().get_summary()
    print(f"  Uptime: {metrics['uptime_human']}")
    print(f"  Total leases issued: {metrics['total_leases_issued']}")
    print(f"  Success rate: {metrics['overall_success_rate']:.1%}")
    print(f"  Warmup success rate: {metrics['warmup_success_rate']:.1%}")
    print(f"  Total recycles: {metrics['total_recycles']}")

    if metrics['lease_duration_stats']['count'] > 0:
        duration_stats = metrics['lease_duration_stats']
        print(f"  Lease duration: avg={duration_stats['avg']:.1f}s, "
              f"p50={duration_stats['percentiles']['p50']:.1f}s, "
              f"p95={duration_stats['percentiles']['p95']:.1f}s")

    # Show final pool stats
    print()
    stats = pool.get_stats()
    print(f"Final pool state:")
    print(f"  Total sessions: {stats.total_sessions}")
    print(f"  Sessions by state: {stats.sessions_by_state}")
    print(f"  Sessions by group: {stats.sessions_by_group}")

    # Shutdown pool
    print()
    print("Shutting down pool...")
    pool.shutdown()
    print("Done!")


if __name__ == "__main__":
    main()
