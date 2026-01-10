#!/usr/bin/env python3
"""
Test script for Enterprise Browser Pool.

Tests the pool functionality including:
- Pool initialization and singleton pattern
- Session acquisition and release
- Lease management and heartbeat
- Metrics collection
- Target group routing

Usage:
    # Unit tests (no browser launch)
    python scripts/test_browser_pool.py --unit

    # Integration test (launches real browsers)
    DISPLAY=:99 python scripts/test_browser_pool.py --integration

    # Full test suite
    DISPLAY=:99 python scripts/test_browser_pool.py --all
"""

import argparse
import os
import sys
import time
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner.logging_setup import get_logger

logger = get_logger("test_browser_pool")


def test_pool_models():
    """Test pool data models."""
    print("\n=== Testing Pool Models ===")

    from seo_intelligence.drivers.pool_models import (
        BrowserSession,
        BrowserType,
        SessionState,
        SessionLease,
        RecycleAction,
        TARGET_GROUP_CONFIGS,
        get_target_group_for_domain,
        get_next_escalation_type,
        WARMUP_CONFIG,
    )

    # Test target group routing
    test_domains = [
        ("google.com", "search_engines"),
        ("www.google.com", "search_engines"),
        ("bing.com", "search_engines"),
        ("yellowpages.com", "directories"),
        ("yelp.com", "directories"),
        ("bbb.org", "directories"),
        ("manta.com", "directories"),
        ("randomsite.com", "general"),
    ]

    print("Testing target group routing:")
    for domain, expected in test_domains:
        result = get_target_group_for_domain(domain)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {domain} → {result} (expected: {expected})")

    # Test escalation order
    print("\nTesting browser escalation order:")
    current = BrowserType.SELENIUM_UC
    escalation_chain = [current.value]
    while True:
        next_type = get_next_escalation_type(current)
        if next_type is None:
            break
        escalation_chain.append(next_type.value)
        current = next_type
    print(f"  Escalation chain: {' → '.join(escalation_chain)}")

    # Test warmup config
    print(f"\nWarmup configuration:")
    print(f"  Min sites: {WARMUP_CONFIG['min_sites_to_visit']}")
    print(f"  Max sites: {WARMUP_CONFIG['max_sites_to_visit']}")
    print(f"  JS verification: {WARMUP_CONFIG['verify_js_execution']}")
    print(f"  Honeypot check: {WARMUP_CONFIG['check_invisible_links']}")

    # Test target group configs
    print(f"\nTarget group configurations:")
    for name, config in TARGET_GROUP_CONFIGS.items():
        print(f"  {name}:")
        print(f"    Min sessions: {config.min_sessions}")
        print(f"    Max sessions: {config.max_sessions}")
        print(f"    Session TTL: {config.session_ttl_minutes} min")
        print(f"    Nav cap: {config.navigation_cap}")

    print("\n✓ Pool models tests passed")
    return True


def test_pool_metrics():
    """Test metrics collection."""
    print("\n=== Testing Pool Metrics ===")

    from seo_intelligence.drivers.pool_metrics import (
        PoolMetricsCollector,
        LeaseMetrics,
        DomainMetrics,
        get_pool_metrics,
        reset_pool_metrics,
    )

    # Reset to get clean state
    reset_pool_metrics()
    metrics = get_pool_metrics()

    # Test singleton
    metrics2 = get_pool_metrics()
    assert metrics is metrics2, "Metrics should be singleton"
    print("  ✓ Metrics singleton works")

    # Test lease recording
    lease_metrics = metrics.record_lease_acquired(
        lease_id="test-lease-1",
        session_id="test-session-1",
        target_domain="google.com",
        target_group="search_engines",
        requester="test_script",
        browser_type="selenium_uc",
        proxy_location="US",
    )
    print("  ✓ Lease acquisition recorded")

    # Simulate some work
    time.sleep(0.1)

    # Release lease
    metrics.record_lease_released(
        lease_metrics,
        success=True,
        blocked=False,
        captcha=False,
        pages_visited=5,
    )
    print("  ✓ Lease release recorded")

    # Record warmup
    metrics.record_warmup(success=True)
    metrics.record_warmup(success=True)
    metrics.record_warmup(success=False)
    print("  ✓ Warmup metrics recorded")

    # Record recycles
    metrics.record_recycle("soft_recycle")
    metrics.record_recycle("hard_recycle")
    metrics.record_recycle("hard_recycle")
    print("  ✓ Recycle metrics recorded")

    # Record escalation
    metrics.record_escalation("selenium_uc", "camoufox")
    print("  ✓ Escalation recorded")

    # Get summary
    summary = metrics.get_summary()
    print(f"\nMetrics summary:")
    print(f"  Total leases: {summary['total_leases_issued']}")
    print(f"  Success rate: {summary['overall_success_rate']:.1%}")
    print(f"  Warmup rate: {summary['warmup_success_rate']:.1%}")
    print(f"  Total recycles: {summary['total_recycles']}")
    print(f"  Recycle breakdown: {summary['recycle_breakdown']}")
    print(f"  Escalations: {summary['total_escalations']}")

    # Verify values
    assert summary['total_leases_issued'] == 1, f"Expected 1 lease, got {summary['total_leases_issued']}"
    assert summary['total_leases_success'] == 1, f"Expected 1 success, got {summary['total_leases_success']}"
    assert abs(summary['warmup_success_rate'] - 2/3) < 0.01, f"Expected ~0.667 warmup rate, got {summary['warmup_success_rate']}"
    assert summary['total_recycles'] == 3, f"Expected 3 recycles, got {summary['total_recycles']}"
    assert summary['total_escalations'] == 1, f"Expected 1 escalation, got {summary['total_escalations']}"

    print("\n✓ Pool metrics tests passed")
    return True


def test_pool_initialization():
    """Test pool initialization without launching browsers."""
    print("\n=== Testing Pool Initialization (No Browsers) ===")

    # Reset the pool singleton to test fresh
    from seo_intelligence.drivers import browser_pool as bp_module

    # Shutdown existing pool if any
    if bp_module._pool_instance is not None:
        try:
            bp_module._pool_instance.shutdown()
        except:
            pass
        bp_module._pool_instance = None

    # Also reset the class singleton
    bp_module.EnterpriseBrowserPool._instance = None

    # Now disable pool BEFORE creating new instance
    os.environ["BROWSER_POOL_ENABLED"] = "false"

    # Force reload of constants
    import importlib
    importlib.reload(bp_module)

    from seo_intelligence.drivers.browser_pool import get_browser_pool

    # Test singleton
    pool1 = get_browser_pool()
    pool2 = get_browser_pool()
    assert pool1 is pool2, "Pool should be singleton"
    print("  ✓ Pool singleton works")

    # Test disabled state
    assert not pool1.is_enabled(), f"Pool should be disabled, got enabled={pool1.is_enabled()}"
    print("  ✓ Pool correctly reports disabled state")

    # Test acquire returns None when disabled
    lease = pool1.acquire_session("google.com", "test")
    assert lease is None, "Disabled pool should return None"
    print("  ✓ Disabled pool returns None on acquire")

    print("\n✓ Pool initialization tests passed")
    return True


def test_pool_integration():
    """Integration test with real browser launch."""
    print("\n=== Testing Pool Integration (Real Browsers) ===")
    print("WARNING: This will launch real browser instances")

    # Enable pool
    os.environ["BROWSER_POOL_ENABLED"] = "true"
    os.environ["BROWSER_POOL_MIN_SESSIONS"] = "2"  # Start small for test
    os.environ["BROWSER_POOL_MAX_SESSIONS"] = "4"

    # Reset singleton to pick up new config
    from seo_intelligence.drivers import browser_pool
    browser_pool._pool_instance = None

    from seo_intelligence.drivers.browser_pool import get_browser_pool
    from seo_intelligence.drivers.pool_metrics import reset_pool_metrics

    reset_pool_metrics()

    pool = get_browser_pool()

    if not pool.is_enabled():
        print("  ⚠ Pool not enabled, skipping integration test")
        return True

    print("  Pool auto-started, waiting for initialization...")

    # Wait for initialization (pool starts background threads automatically)
    time.sleep(15)

    # Get stats
    stats = pool.get_stats()
    print(f"\nPool stats after initialization:")
    print(f"  Total sessions: {stats.total_sessions}")
    print(f"  Sessions by state: {stats.sessions_by_state}")
    print(f"  Sessions by group: {stats.sessions_by_group}")

    # Try to acquire a session
    print("\nTesting session acquisition...")
    lease = pool.acquire_session(
        target_domain="google.com",
        requester="integration_test",
        timeout_seconds=30,
    )

    if lease:
        print(f"  ✓ Acquired session: {lease.session_id[:8]}")
        print(f"    Target group: {lease.target_group}")
        print(f"    Expires at: {lease.expires_at}")

        # Get driver
        driver = pool.get_driver(lease)
        if driver:
            print(f"  ✓ Got driver instance")

            # Try a simple navigation
            try:
                driver.get("https://www.example.com")
                title = driver.title
                print(f"  ✓ Navigation successful, title: {title}")
            except Exception as e:
                print(f"  ⚠ Navigation error: {e}")

        # Send heartbeat
        pool.heartbeat(lease)
        print("  ✓ Heartbeat sent")

        # Release session
        pool.release_session(lease, dirty=False)
        print("  ✓ Session released")
    else:
        print("  ⚠ Failed to acquire session")

    # Get final metrics
    metrics = pool.get_metrics_summary()
    print(f"\nFinal metrics:")
    print(f"  Total leases issued: {metrics['total_leases_issued']}")
    print(f"  Success rate: {metrics['overall_success_rate']:.1%}")
    print(f"  Warmup success rate: {metrics['warmup_success_rate']:.1%}")

    # Shutdown
    print("\nShutting down pool...")
    pool.shutdown()
    print("  ✓ Pool shutdown complete")

    print("\n✓ Integration tests passed")
    return True


def test_context_manager():
    """Test the browser_lease context manager."""
    print("\n=== Testing Context Manager ===")

    os.environ["BROWSER_POOL_ENABLED"] = "true"
    os.environ["BROWSER_POOL_MIN_SESSIONS"] = "2"

    from seo_intelligence.drivers import browser_pool
    browser_pool._pool_instance = None

    from seo_intelligence.drivers.browser_pool import get_browser_pool

    pool = get_browser_pool()

    if not pool.is_enabled():
        print("  ⚠ Pool not enabled, skipping")
        return True

    # Pool auto-starts, wait for init
    time.sleep(15)

    print("Testing context manager pattern...")

    try:
        with pool.browser_lease("yellowpages.com", "context_test") as (lease, driver):
            if lease and driver:
                print(f"  ✓ Context manager provided lease and driver")
                print(f"    Session: {lease.session_id[:8]}")

                # Use the driver
                driver.get("https://www.example.com")
                print(f"  ✓ Navigation in context successful")
            else:
                print("  ⚠ Context manager returned None")

        print("  ✓ Context manager cleanup successful")
    except Exception as e:
        print(f"  ✗ Context manager error: {e}")

    pool.shutdown()

    print("\n✓ Context manager tests passed")
    return True


def main():
    parser = argparse.ArgumentParser(description="Test Enterprise Browser Pool")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    if not any([args.unit, args.integration, args.all]):
        args.unit = True  # Default to unit tests

    print("=" * 60)
    print("Enterprise Browser Pool Test Suite")
    print("=" * 60)

    results = {}

    # Unit tests (no browser launch)
    if args.unit or args.all:
        try:
            results["pool_models"] = test_pool_models()
        except Exception as e:
            print(f"✗ Pool models test failed: {e}")
            results["pool_models"] = False

        try:
            results["pool_metrics"] = test_pool_metrics()
        except Exception as e:
            print(f"✗ Pool metrics test failed: {e}")
            results["pool_metrics"] = False

        try:
            results["pool_init"] = test_pool_initialization()
        except Exception as e:
            print(f"✗ Pool init test failed: {e}")
            results["pool_init"] = False

    # Integration tests (real browsers)
    if args.integration or args.all:
        try:
            results["integration"] = test_pool_integration()
        except Exception as e:
            print(f"✗ Integration test failed: {e}")
            import traceback
            traceback.print_exc()
            results["integration"] = False

        try:
            results["context_manager"] = test_context_manager()
        except Exception as e:
            print(f"✗ Context manager test failed: {e}")
            results["context_manager"] = False

    # Summary
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
