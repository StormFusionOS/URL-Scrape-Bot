#!/usr/bin/env python3
"""
Test Competitor Crawling with the Enterprise Browser Pool enabled.

This script demonstrates the browser pool integration with the competitor crawler.
"""

import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Enable browser pool
os.environ["BROWSER_POOL_ENABLED"] = "true"
# At least one session per group (3 groups: search_engines, directories, general)
os.environ["BROWSER_POOL_MIN_SESSIONS"] = "3"
os.environ["BROWSER_POOL_MAX_SESSIONS"] = "6"

from runner.logging_setup import get_logger
from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium
from seo_intelligence.drivers import get_browser_pool, get_pool_metrics, reset_pool_metrics

logger = get_logger("test_competitor_pool")


def main():
    print("=" * 70)
    print("Competitor Crawler Test with Enterprise Browser Pool")
    print("=" * 70)
    print()

    # Reset metrics for clean test
    reset_pool_metrics()

    # Check pool status
    pool = get_browser_pool()
    print(f"Pool enabled: {pool.is_enabled()}")
    print(f"Waiting for pool to initialize...")
    print()

    # Wait for pool to have at least one warm session for 'general' group
    start_wait = time.time()
    max_wait = 120  # seconds
    while time.time() - start_wait < max_wait:
        stats = pool.get_stats()
        warm_count = stats.sessions_by_state.get('idle_warm', 0)
        warming_count = stats.sessions_by_state.get('warming', 0)
        total = stats.total_sessions

        # Check if we have any general sessions
        general_count = stats.sessions_by_group.get('general', 0)

        print(f"  Pool status: {total} total, {warm_count} warm, {warming_count} warming (general: {general_count})...")

        if warm_count > 0 and general_count > 0:
            print(f"  Pool ready with {warm_count} warm session(s)")
            break

        time.sleep(5)
    else:
        print("  Warning: Pool initialization timed out, proceeding anyway")

    print()

    # Create competitor crawler
    crawler = CompetitorCrawlerSelenium(
        headless=True,
        use_proxy=True,
    )

    # Test competitor - a real pressure washing business site
    test_domain = "example.com"  # Safe test domain

    print(f"Running competitor crawl:")
    print(f"  Domain: {test_domain}")
    print()

    try:
        # Run the crawl
        start_time = time.time()
        result = crawler.crawl_competitor(
            domain=test_domain,
            name="Example Business",
            business_type="pressure_washing",
            location="Austin, TX",
        )
        elapsed = time.time() - start_time

        print()
        print(f"Crawl completed in {elapsed:.1f} seconds")
        print()

        if result:
            print(f"Results:")
            print(f"  Domain: {result.get('domain', 'N/A')}")
            print(f"  Pages crawled: {result.get('pages_crawled', 0)}")
            print(f"  Pages failed: {result.get('pages_failed', 0)}")
            print(f"  Total words: {result.get('total_words', 0)}")

            schema_types = result.get('schema_types', set())
            if schema_types:
                print(f"  Schema types: {', '.join(schema_types)}")

            tech_stack = result.get('tech_stack')
            if tech_stack:
                print(f"  Tech stack detected: Yes")
        else:
            print("No results returned (site may be blocking or unavailable)")

    except Exception as e:
        print(f"Error during crawl: {e}")
        import traceback
        traceback.print_exc()

    # Now let's test with a real business site
    print()
    print("=" * 70)
    print("Testing with a real pressure washing business site...")
    print("=" * 70)

    real_domain = "blueskypressurewashing.com"
    print(f"  Domain: {real_domain}")
    print()

    try:
        start_time = time.time()
        result = crawler.crawl_competitor(
            domain=real_domain,
            name="Blue Sky Pressure Washing",
            business_type="pressure_washing",
            location="Austin, TX",
        )
        elapsed = time.time() - start_time

        print()
        print(f"Crawl completed in {elapsed:.1f} seconds")
        print()

        if result:
            print(f"Results:")
            print(f"  Domain: {result.get('domain', 'N/A')}")
            print(f"  Pages crawled: {result.get('pages_crawled', 0)}")
            print(f"  Pages failed: {result.get('pages_failed', 0)}")
            print(f"  Total words: {result.get('total_words', 0)}")

            schema_types = result.get('schema_types', set())
            if schema_types:
                if isinstance(schema_types, set):
                    print(f"  Schema types: {', '.join(schema_types)}")
                else:
                    print(f"  Schema types: {schema_types}")
        else:
            print("No results returned")

    except Exception as e:
        print(f"Error during crawl: {e}")

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

    # Show group metrics
    group_metrics = metrics.get('group_metrics', {})
    if group_metrics:
        print()
        print("  Metrics by target group:")
        for group, gm in group_metrics.items():
            print(f"    {group}: {gm['total_leases']} leases, {gm['success_rate']:.1%} success")

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
