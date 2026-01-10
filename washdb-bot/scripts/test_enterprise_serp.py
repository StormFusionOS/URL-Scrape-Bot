#!/usr/bin/env python3
"""
Test script for the Enterprise SERP system.

This validates that the new enterprise SERP infrastructure works correctly:
1. Session pool initialization
2. Cache functionality
3. Query scheduling
4. Human-like behavior
5. Result parsing

Usage:
    python scripts/test_enterprise_serp.py
"""

import os
import sys
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def test_cache():
    """Test the SERP result cache."""
    print("\n=== Testing SERP Cache ===")

    from seo_intelligence.services.serp_session_pool import SerpResultCache

    cache = SerpResultCache(ttl_hours=24)

    # Test set and get
    test_query = "test query for cache"
    test_result = {"organic_results": [{"title": "Test", "url": "https://test.com"}]}

    cache.set(test_query, test_result, location="Test City")
    retrieved = cache.get(test_query, location="Test City")

    if retrieved:
        print("  Cache SET/GET: OK")
    else:
        print("  Cache SET/GET: FAILED")
        return False

    # Test cache miss
    miss = cache.get("nonexistent query", location="Nowhere")
    if miss is None:
        print("  Cache MISS: OK")
    else:
        print("  Cache MISS: FAILED")
        return False

    print("  Cache test passed!")
    return True


def test_session_stats():
    """Test session statistics tracking."""
    print("\n=== Testing Session Stats ===")

    from seo_intelligence.services.serp_session_pool import SessionStats

    stats = SessionStats(session_id=0)

    # Test initial state
    assert stats.can_search == True, "New session should be able to search"
    assert stats.needs_warming == True, "New session should need warming"
    assert stats.success_rate == 1.0, "Empty stats should have 100% success rate"

    print("  Initial state: OK")

    # Test after some activity
    stats.successes = 8
    stats.failures = 2
    assert abs(stats.success_rate - 0.8) < 0.01, "Success rate should be 80%"

    print("  Success rate calculation: OK")

    # Test daily reset
    stats.searches_today = 15
    stats.reset_daily()
    assert stats.searches_today == 0, "Daily reset should clear searches_today"

    print("  Daily reset: OK")
    print("  Session stats test passed!")
    return True


def test_human_behavior_config():
    """Test human behavior configuration."""
    print("\n=== Testing Human Behavior Config ===")

    from seo_intelligence.services.serp_session_pool import HumanBehaviorConfig

    config = HumanBehaviorConfig()

    # Check defaults are reasonable
    assert config.typing_speed_cps[0] >= 2, "Typing speed should be human-like"
    assert config.typo_chance < 0.1, "Typo chance should be low"
    assert config.scroll_probability > 0.5, "Should usually scroll"
    assert len(config.warm_sites) > 0, "Should have warm sites defined"

    print("  Default config: OK")
    print("  Human behavior config test passed!")
    return True


def test_scheduler_config():
    """Test scheduler configuration."""
    print("\n=== Testing Scheduler Config ===")

    from seo_intelligence.services.serp_query_scheduler import SchedulerConfig, QueryPriority

    config = SchedulerConfig()

    # Check defaults
    assert config.max_queries_per_hour > 0, "Should have hourly limit"
    assert config.min_delay_between_queries_sec > 0, "Should have minimum delay"
    assert config.max_retries > 0, "Should have retry limit"

    print("  Default scheduler config: OK")

    # Test priority ordering
    assert QueryPriority.URGENT.value < QueryPriority.NORMAL.value, "URGENT should be higher priority"
    assert QueryPriority.NORMAL.value < QueryPriority.BACKGROUND.value, "NORMAL should be higher than BACKGROUND"

    print("  Priority ordering: OK")
    print("  Scheduler config test passed!")
    return True


def test_enterprise_serp_api():
    """Test the Enterprise SERP API interface."""
    print("\n=== Testing Enterprise SERP API ===")

    from seo_intelligence.services.enterprise_serp import EnterpriseSERP, EnterpriseSerpConfig

    config = EnterpriseSerpConfig(
        num_sessions=2,
        max_queries_per_hour=10,
        min_delay_between_queries_sec=60,
    )

    serp = EnterpriseSERP(config)

    # Check initial state
    assert serp._started == False, "Should not be started initially"

    stats = serp.get_stats()
    assert stats["started"] == False, "Stats should show not started"

    print("  Initial state: OK")
    print("  Enterprise SERP API test passed!")
    return True


def test_scraper_wrapper():
    """Test the enterprise scraper wrapper."""
    print("\n=== Testing Scraper Wrapper ===")

    # Just import to ensure no syntax errors
    from seo_intelligence.scrapers.serp_scraper_enterprise import EnterpriseSerpScraper

    print("  Import: OK")
    print("  Scraper wrapper test passed!")
    return True


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Enterprise SERP System Tests")
    print("=" * 60)

    tests = [
        ("Cache", test_cache),
        ("Session Stats", test_session_stats),
        ("Human Behavior Config", test_human_behavior_config),
        ("Scheduler Config", test_scheduler_config),
        ("Enterprise SERP API", test_enterprise_serp_api),
        ("Scraper Wrapper", test_scraper_wrapper),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"  FAILED: {name}")
        except Exception as e:
            failed += 1
            print(f"  ERROR in {name}: {e}")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


def test_live_search():
    """
    Test a live SERP search (optional - takes time).

    This actually runs a search through the enterprise system.
    Only run this if you want to verify end-to-end functionality.
    """
    print("\n=== Testing Live SERP Search ===")
    print("This will perform an actual Google search...")
    print("(This may take several minutes due to rate limiting)")

    response = input("Continue? (y/n): ")
    if response.lower() != 'y':
        print("Skipped live search test")
        return True

    from seo_intelligence.services.enterprise_serp import start_enterprise_serp, stop_enterprise_serp

    try:
        # Start the system
        print("Starting enterprise SERP system...")
        serp = start_enterprise_serp()

        # Perform a search
        print("Queuing search for 'pressure washing services'...")
        result = serp.search(
            query="pressure washing services",
            location="Boston, MA",
            timeout=600,  # 10 minute timeout
        )

        if result:
            organic = result.get("organic_results", [])
            local = result.get("local_pack", [])
            print(f"  SUCCESS: {len(organic)} organic, {len(local)} local results")

            if organic:
                print(f"  Top result: {organic[0].get('title', 'N/A')}")

            return True
        else:
            print("  FAILED: No results returned")
            return False

    except Exception as e:
        print(f"  ERROR: {e}")
        return False

    finally:
        print("Stopping enterprise SERP system...")
        stop_enterprise_serp()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test Enterprise SERP System")
    parser.add_argument("--live", action="store_true", help="Run live search test")
    args = parser.parse_args()

    success = run_all_tests()

    if args.live:
        success = test_live_search() and success

    sys.exit(0 if success else 1)
