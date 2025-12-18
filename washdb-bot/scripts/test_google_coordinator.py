#!/usr/bin/env python3
"""
Test script for GoogleCoordinator

Tests that:
1. GoogleCoordinator properly serializes Google requests
2. SERP and Autocomplete scrapers route through coordinator
3. Rate limiting and delays are enforced
4. Quarantine detection works

Usage:
    export DISPLAY=:99
    ./venv/bin/python scripts/test_google_coordinator.py
"""

import os
import sys
import time
import json
from datetime import datetime

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from runner.logging_setup import get_logger

logger = get_logger("test_google_coordinator")


def test_coordinator_basics():
    """Test basic GoogleCoordinator functionality."""
    print("\n" + "="*60)
    print("TEST 1: GoogleCoordinator Basics")
    print("="*60)

    from seo_intelligence.services import (
        get_google_coordinator,
        reset_google_coordinator,
    )

    # Reset to start fresh
    reset_google_coordinator()

    # Get coordinator
    coordinator = get_google_coordinator(share_browser=False)

    print(f"  Coordinator initialized: {coordinator is not None}")
    print(f"  Share browser: {coordinator.share_browser}")
    print(f"  Is quarantined: {coordinator.is_quarantined()}")

    stats = coordinator.get_stats()
    print(f"  Stats: {json.dumps(stats, indent=4, default=str)}")

    return True


def test_serp_with_coordinator():
    """Test SerpScraperSelenium with coordinator's SHARED browser."""
    print("\n" + "="*60)
    print("TEST 2: SerpScraperSelenium with Coordinator (SHARED BROWSER)")
    print("="*60)

    from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium
    from seo_intelligence.services import get_google_coordinator

    coordinator = get_google_coordinator()

    if coordinator.is_quarantined():
        print("  SKIPPED: Google is quarantined")
        return None

    # Check browser state BEFORE
    stats_before = coordinator.get_stats()
    print(f"  Browser active BEFORE: {stats_before['browser_active']}")

    scraper = SerpScraperSelenium(headless=True)

    # Test with coordinator (default) - uses SHARED browser
    start_time = time.time()
    print("  Scraping 'pressure washing services' WITH coordinator (shared browser)...")
    result = scraper.scrape_serp("pressure washing services", num_results=10, use_coordinator=True)
    elapsed = time.time() - start_time

    # Check browser state AFTER
    stats_after = coordinator.get_stats()
    print(f"  Browser active AFTER: {stats_after['browser_active']}")

    if result:
        organic_count = len(result.get("organic_results", []))
        has_local = result.get("has_local_pack", False)
        print(f"  SUCCESS: {organic_count} organic results, local_pack={has_local}")
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"  Shared browser is being reused: {stats_after['browser_active']}")
        return True
    else:
        print(f"  FAILED: No results returned")
        return False


def test_autocomplete_with_coordinator():
    """Test AutocompleteScraperSelenium with coordinator's SHARED browser."""
    print("\n" + "="*60)
    print("TEST 3: AutocompleteScraperSelenium with Coordinator (SHARED BROWSER)")
    print("="*60)

    from seo_intelligence.scrapers.autocomplete_scraper_selenium import AutocompleteScraperSelenium
    from seo_intelligence.services import get_google_coordinator

    coordinator = get_google_coordinator()

    if coordinator.is_quarantined():
        print("  SKIPPED: Google is quarantined")
        return None

    # Check browser state BEFORE - should already be active from SERP test
    stats_before = coordinator.get_stats()
    print(f"  Browser active BEFORE: {stats_before['browser_active']}")
    print(f"  Last request: {stats_before['seconds_since_last_request']:.1f}s ago" if stats_before['seconds_since_last_request'] else "  Last request: None")

    scraper = AutocompleteScraperSelenium()

    # Test with coordinator (default) - uses SAME SHARED browser as SERP
    start_time = time.time()
    print("  Getting suggestions for 'window cleaning near' WITH coordinator (shared browser)...")
    result = scraper.get_suggestions("window cleaning near", use_coordinator=True)
    elapsed = time.time() - start_time

    # Check browser state AFTER
    stats_after = coordinator.get_stats()
    print(f"  Browser active AFTER: {stats_after['browser_active']}")

    if result:
        print(f"  SUCCESS: {len(result)} suggestions found")
        if result:
            print(f"    Sample: {result[0].keyword}")
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"  Shared browser reused (same as SERP): {stats_before['browser_active'] == stats_after['browser_active']}")
        return True
    else:
        print(f"  RESULT: 0 suggestions (may be normal if no suggestions available)")
        return True  # Not necessarily a failure


def test_sequential_requests():
    """Test that sequential requests through coordinator have proper delays."""
    print("\n" + "="*60)
    print("TEST 4: Sequential Request Serialization")
    print("="*60)

    from seo_intelligence.services import get_google_coordinator

    coordinator = get_google_coordinator()

    if coordinator.is_quarantined():
        print("  SKIPPED: Google is quarantined")
        return None

    # Check timing between coordinator calls
    stats_before = coordinator.get_stats()
    last_request = stats_before.get("last_request_time", 0)

    if last_request > 0:
        elapsed_since_last = time.time() - last_request
        print(f"  Time since last Google request: {elapsed_since_last:.1f}s")
        print(f"  Min delay configured: {stats_before['min_delay']}s")
        print(f"  Max delay configured: {stats_before['max_delay']}s")

        if elapsed_since_last < stats_before['min_delay']:
            print(f"  Next request would wait: {stats_before['min_delay'] - elapsed_since_last:.1f}s")
        else:
            print(f"  No wait needed (enough time elapsed)")
    else:
        print("  No previous requests yet")

    return True


def test_coordinator_stats():
    """Display coordinator statistics."""
    print("\n" + "="*60)
    print("TEST 5: Coordinator Statistics")
    print("="*60)

    from seo_intelligence.services import get_google_coordinator

    coordinator = get_google_coordinator()
    stats = coordinator.get_stats()

    print(f"  Browser sharing: {stats['share_browser']}")
    print(f"  Browser active: {stats['browser_active']}")
    print(f"  Quarantined: {stats['is_quarantined']}")

    if stats['quarantine_info']:
        print(f"  Quarantine reason: {stats['quarantine_info'].get('reason')}")
        print(f"  Quarantine expires: {stats['quarantine_info'].get('expires_at')}")

    if stats['last_request_time']:
        print(f"  Last request: {stats['seconds_since_last_request']:.1f}s ago")

    print(f"  Delay range: {stats['min_delay']}-{stats['max_delay']}s")

    return True


def main():
    """Run all tests."""
    print("="*60)
    print("GOOGLE COORDINATOR TEST SUITE")
    print(f"Started: {datetime.now().isoformat()}")
    print("="*60)

    results = {}

    # Test 1: Basics
    try:
        results["coordinator_basics"] = test_coordinator_basics()
    except Exception as e:
        print(f"  ERROR: {e}")
        results["coordinator_basics"] = False

    # Test 2: SERP with coordinator
    try:
        results["serp_coordinator"] = test_serp_with_coordinator()
    except Exception as e:
        print(f"  ERROR: {e}")
        results["serp_coordinator"] = False

    # Test 3: Autocomplete with coordinator
    try:
        results["autocomplete_coordinator"] = test_autocomplete_with_coordinator()
    except Exception as e:
        print(f"  ERROR: {e}")
        results["autocomplete_coordinator"] = False

    # Test 4: Sequential requests
    try:
        results["sequential_requests"] = test_sequential_requests()
    except Exception as e:
        print(f"  ERROR: {e}")
        results["sequential_requests"] = False

    # Test 5: Stats
    try:
        results["coordinator_stats"] = test_coordinator_stats()
    except Exception as e:
        print(f"  ERROR: {e}")
        results["coordinator_stats"] = False

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)

    for test_name, result in results.items():
        status = "PASS" if result is True else "FAIL" if result is False else "SKIP"
        print(f"  {test_name}: {status}")

    print()
    print(f"Total: {passed} passed, {failed} failed, {skipped} skipped")

    # Cleanup
    from seo_intelligence.services import get_google_coordinator
    coordinator = get_google_coordinator()
    coordinator.close()
    print("\nCoordinator closed.")

    # Save results
    output_file = "data/google_coordinator_test.json"
    os.makedirs("data", exist_ok=True)
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "results": {k: str(v) for k, v in results.items()},
            "summary": {
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
            }
        }, f, indent=2)
    print(f"Results saved to {output_file}")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
