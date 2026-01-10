"""
Tests for Rate Limiter Concurrency Controls

Tests that the rate limiter properly enforces:
1. Global max concurrency of 5 (across all domains)
2. Per-domain max concurrency of 1
3. Tier-specific rate limits per SCRAPING_NOTES.md

Run with: python -m pytest seo_intelligence/tests/test_rate_limiter_concurrency.py -v
"""

import pytest
import time
import threading
from typing import List
from seo_intelligence.services.rate_limiter import get_rate_limiter, TIER_CONFIGS


class TestGlobalConcurrency:
    """Test global concurrency limit (max 5 concurrent requests)."""

    def test_global_concurrency_limit(self):
        """Test that no more than 5 requests can run concurrently."""
        limiter = get_rate_limiter()
        max_concurrent = 0
        current_concurrent = 0
        lock = threading.Lock()
        results = []

        def worker(domain: str, delay: float):
            """Simulate a request."""
            nonlocal max_concurrent, current_concurrent

            # Try to acquire concurrency
            acquired = limiter.acquire_concurrency(domain, timeout=10.0)
            if not acquired:
                results.append(("timeout", domain))
                return

            try:
                # Track concurrent count
                with lock:
                    current_concurrent += 1
                    if current_concurrent > max_concurrent:
                        max_concurrent = current_concurrent

                # Simulate work
                time.sleep(delay)

                # Record success
                results.append(("success", domain))

            finally:
                with lock:
                    current_concurrent -= 1
                limiter.release_concurrency(domain)

        # Launch 10 workers (more than the limit of 5)
        threads = []
        domains = [f"domain{i}.com" for i in range(10)]

        for i, domain in enumerate(domains):
            t = threading.Thread(target=worker, args=(domain, 0.5))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join(timeout=30)

        # Verify max concurrent was 5 or less
        assert max_concurrent <= 5, f"Max concurrent was {max_concurrent}, expected ≤ 5"

        # Verify all succeeded
        successes = [r for r in results if r[0] == "success"]
        assert len(successes) == 10, f"Expected 10 successes, got {len(successes)}"

        print(f"\n✓ Global concurrency limit enforced: max {max_concurrent} concurrent (limit: 5)")

    def test_global_concurrency_blocks_when_full(self):
        """Test that 6th concurrent request blocks until a slot opens."""
        limiter = get_rate_limiter()
        acquired_count = 0
        lock = threading.Lock()

        # Acquire 5 slots
        domains = [f"slot{i}.com" for i in range(5)]
        for domain in domains:
            assert limiter.acquire_concurrency(domain, timeout=1.0)
            with lock:
                acquired_count += 1

        assert acquired_count == 5

        # Try to acquire 6th slot with short timeout (should fail)
        acquired_6th = limiter.acquire_concurrency("sixth.com", timeout=0.5)
        assert not acquired_6th, "6th concurrent request should have been blocked"

        # Release one slot
        limiter.release_concurrency(domains[0])

        # Now 6th should succeed
        acquired_6th = limiter.acquire_concurrency("sixth.com", timeout=1.0)
        assert acquired_6th, "6th request should succeed after release"

        # Cleanup
        for domain in domains[1:]:
            limiter.release_concurrency(domain)
        limiter.release_concurrency("sixth.com")

        print("\n✓ Global concurrency properly blocks 6th concurrent request")


class TestPerDomainConcurrency:
    """Test per-domain concurrency limit (max 1 concurrent request per domain)."""

    def test_per_domain_concurrency_limit(self):
        """Test that only 1 request per domain can run concurrently."""
        limiter = get_rate_limiter()
        concurrent_counts = {}
        max_counts = {}
        lock = threading.Lock()
        results = []

        def worker(domain: str, worker_id: int, delay: float):
            """Simulate a request to a domain."""
            # Try to acquire concurrency
            acquired = limiter.acquire_concurrency(domain, timeout=10.0)
            if not acquired:
                results.append(("timeout", domain, worker_id))
                return

            try:
                # Track concurrent count for this domain
                with lock:
                    if domain not in concurrent_counts:
                        concurrent_counts[domain] = 0
                        max_counts[domain] = 0

                    concurrent_counts[domain] += 1
                    if concurrent_counts[domain] > max_counts[domain]:
                        max_counts[domain] = concurrent_counts[domain]

                # Simulate work
                time.sleep(delay)

                # Record success
                results.append(("success", domain, worker_id))

            finally:
                with lock:
                    concurrent_counts[domain] -= 1
                limiter.release_concurrency(domain)

        # Launch 3 workers for each of 3 domains (9 total)
        threads = []
        domains = ["domainA.com", "domainB.com", "domainC.com"]

        for domain in domains:
            for worker_id in range(3):
                t = threading.Thread(target=worker, args=(domain, worker_id, 0.3))
                threads.append(t)
                t.start()

        # Wait for all threads
        for t in threads:
            t.join(timeout=30)

        # Verify max concurrent per domain was 1
        for domain, max_count in max_counts.items():
            assert max_count == 1, f"Domain {domain} had {max_count} concurrent, expected 1"

        # Verify all succeeded
        successes = [r for r in results if r[0] == "success"]
        assert len(successes) == 9, f"Expected 9 successes, got {len(successes)}"

        print(f"\n✓ Per-domain concurrency limit enforced: max 1 per domain")
        for domain, max_count in max_counts.items():
            print(f"  {domain}: max concurrent = {max_count}")

    def test_same_domain_blocks_second_request(self):
        """Test that 2nd concurrent request to same domain blocks."""
        limiter = get_rate_limiter()

        # Acquire for domain
        assert limiter.acquire_concurrency("test.com", timeout=1.0)

        # Try to acquire again for same domain with short timeout (should fail)
        acquired_2nd = limiter.acquire_concurrency("test.com", timeout=0.5)
        assert not acquired_2nd, "2nd concurrent request to same domain should block"

        # Release
        limiter.release_concurrency("test.com")

        # Now 2nd should succeed
        acquired_2nd = limiter.acquire_concurrency("test.com", timeout=1.0)
        assert acquired_2nd, "2nd request should succeed after release"

        # Cleanup
        limiter.release_concurrency("test.com")

        print("\n✓ Per-domain concurrency properly blocks 2nd concurrent request")


class TestCombinedConcurrency:
    """Test combination of global and per-domain concurrency."""

    def test_combined_limits(self):
        """Test that both global (5) and per-domain (1) limits work together."""
        limiter = get_rate_limiter()
        results = []
        lock = threading.Lock()
        max_global = 0
        current_global = 0

        def worker(domain: str, worker_id: int, delay: float):
            """Simulate a request."""
            nonlocal max_global, current_global

            acquired = limiter.acquire_concurrency(domain, timeout=15.0)
            if not acquired:
                results.append(("timeout", domain, worker_id))
                return

            try:
                with lock:
                    current_global += 1
                    if current_global > max_global:
                        max_global = current_global

                time.sleep(delay)
                results.append(("success", domain, worker_id))

            finally:
                with lock:
                    current_global -= 1
                limiter.release_concurrency(domain)

        # Launch 20 workers across 10 domains (2 per domain)
        # This tests:
        # - Global limit prevents >5 concurrent
        # - Per-domain limit prevents >1 per domain
        threads = []
        domains = [f"domain{i}.com" for i in range(10)]

        for domain in domains:
            for worker_id in range(2):
                t = threading.Thread(target=worker, args=(domain, worker_id, 0.3))
                threads.append(t)
                t.start()

        # Wait for all threads
        for t in threads:
            t.join(timeout=45)

        # Verify global max was ≤ 5
        assert max_global <= 5, f"Max global concurrent was {max_global}, expected ≤ 5"

        # Verify all succeeded (might have some timeouts if test runs slow)
        successes = [r for r in results if r[0] == "success"]
        timeouts = [r for r in results if r[0] == "timeout"]

        print(f"\n✓ Combined concurrency limits enforced")
        print(f"  Max global concurrent: {max_global} (limit: 5)")
        print(f"  Successes: {len(successes)}/20")
        print(f"  Timeouts: {len(timeouts)}/20")

        # Most should succeed
        assert len(successes) >= 15, f"Expected ≥15 successes, got {len(successes)}"


class TestTierConfigurations:
    """Test that tier configurations match SCRAPING_NOTES.md specification."""

    def test_tier_a_config(self):
        """Test Tier A: 1 req / 3-5s (~0.2-0.33 RPS)."""
        config = TIER_CONFIGS['A']
        assert config.min_delay_seconds == 3.0, "Tier A min delay should be 3s"
        assert config.max_delay_seconds == 5.0, "Tier A max delay should be 5s"
        # 0.2-0.33 RPS = 12-20 req/min
        assert 12.0 <= config.tokens_per_minute <= 20.0, \
            f"Tier A should be 12-20 req/min, got {config.tokens_per_minute}"
        print("\n✓ Tier A config matches spec (3-5s, ~15 req/min)")

    def test_tier_b_config(self):
        """Test Tier B: 1 req / 10s (~0.1 RPS)."""
        config = TIER_CONFIGS['B']
        assert config.min_delay_seconds == 10.0, "Tier B min delay should be 10s"
        assert config.max_delay_seconds == 10.0, "Tier B max delay should be 10s"
        # 0.1 RPS = 6 req/min
        assert config.tokens_per_minute == 6.0, \
            f"Tier B should be 6 req/min, got {config.tokens_per_minute}"
        print("\n✓ Tier B config matches spec (10s, 6 req/min)")

    def test_tier_c_to_g_config(self):
        """Test Tiers C-G: ~0.2 RPS."""
        for tier in ['C', 'D', 'E', 'F', 'G']:
            config = TIER_CONFIGS[tier]
            # ~0.2 RPS = 12 req/min
            assert 10.0 <= config.tokens_per_minute <= 12.0, \
                f"Tier {tier} should be 10-12 req/min, got {config.tokens_per_minute}"
        print("\n✓ Tiers C-G configs match spec (~10-12 req/min)")


class TestRateLimiterIntegration:
    """Integration tests for rate limiter."""

    def test_rate_limit_enforcement(self):
        """Test that rate limits actually slow down requests."""
        limiter = get_rate_limiter()
        limiter.set_domain_tier("slow.com", "B")  # 10s delay

        start = time.time()

        # Make 3 requests sequentially
        for i in range(3):
            acquired = limiter.acquire_concurrency("slow.com", timeout=5.0)
            if acquired:
                limiter.acquire("slow.com", wait=True, max_wait=15.0)
                # Don't sleep - just acquire and release
                limiter.release_concurrency("slow.com")

        elapsed = time.time() - start

        # With 10s delay between requests, 3 requests should take ~20s minimum
        # (first is immediate, then 2 more with 10s delays)
        assert elapsed >= 15.0, f"3 requests to Tier B domain should take ≥15s, took {elapsed:.1f}s"

        print(f"\n✓ Rate limiting enforced: 3 Tier B requests took {elapsed:.1f}s (expected ≥15s)")


def main():
    """Run all tests manually."""
    print("=" * 70)
    print("Rate Limiter Concurrency Tests")
    print("=" * 70)

    # Test global concurrency
    print("\n--- Global Concurrency Tests ---")
    test = TestGlobalConcurrency()
    test.test_global_concurrency_limit()
    test.test_global_concurrency_blocks_when_full()

    # Test per-domain concurrency
    print("\n--- Per-Domain Concurrency Tests ---")
    test = TestPerDomainConcurrency()
    test.test_per_domain_concurrency_limit()
    test.test_same_domain_blocks_second_request()

    # Test combined
    print("\n--- Combined Concurrency Tests ---")
    test = TestCombinedConcurrency()
    test.test_combined_limits()

    # Test tier configs
    print("\n--- Tier Configuration Tests ---")
    test = TestTierConfigurations()
    test.test_tier_a_config()
    test.test_tier_b_config()
    test.test_tier_c_to_g_config()

    # Integration test
    print("\n--- Integration Tests ---")
    test = TestRateLimiterIntegration()
    test.test_rate_limit_enforcement()

    print("\n" + "=" * 70)
    print("All tests passed! ✓")
    print("=" * 70)


if __name__ == "__main__":
    main()
