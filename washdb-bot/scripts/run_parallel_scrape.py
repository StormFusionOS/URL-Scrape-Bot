#!/usr/bin/env python3
"""
Launch script for parallel Yellow Pages scraping with proxies.

This script:
1. Validates configuration
2. Tests proxies
3. Stops any existing single-worker scrape
4. Launches worker pool with N workers
5. Monitors progress
"""

import os
import sys
import time
import signal
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scrape_yp.worker_config import WorkerConfig
from scrape_yp.proxy_pool import ProxyPool
from scrape_yp.worker_pool import WorkerPoolManager, create_worker_session
from db.models import YPTarget
from sqlalchemy import func


def print_banner():
    """Print startup banner."""
    print("=" * 70)
    print("  Yellow Pages Parallel Scraper with Proxy Rotation")
    print("=" * 70)
    print()


def validate_and_print_config():
    """Validate configuration and print summary."""
    print("Validating configuration...")
    try:
        WorkerConfig.validate()
        print("✓ Configuration is valid\n")
    except ValueError as e:
        print(f"✗ Configuration validation failed:\n{e}\n")
        sys.exit(1)

    WorkerConfig.print_summary()
    print()


def test_proxies():
    """Test proxies before starting."""
    if not WorkerConfig.PROXY_TEST_ON_STARTUP:
        print("Proxy testing disabled, skipping...\n")
        return

    print("Testing proxies...")
    print(f"Loading proxies from {WorkerConfig.PROXY_FILE}...")

    try:
        proxy_pool = ProxyPool(
            WorkerConfig.PROXY_FILE,
            blacklist_threshold=WorkerConfig.PROXY_BLACKLIST_THRESHOLD,
            blacklist_duration_minutes=WorkerConfig.PROXY_BLACKLIST_DURATION_MINUTES
        )

        print(f"✓ Loaded {len(proxy_pool.proxies)} proxies\n")

        # Test first 5 proxies
        print("Testing first 5 proxies (this may take a minute)...")
        test_count = min(5, len(proxy_pool.proxies))

        passed = 0
        failed = 0

        for idx in range(test_count):
            proxy = proxy_pool.proxies[idx]
            print(f"  Testing {idx+1}/{test_count}: {proxy.host}:{proxy.port}...", end=" ")

            if proxy_pool.test_proxy(proxy):
                print("✓ PASSED")
                passed += 1
            else:
                print("✗ FAILED")
                failed += 1

        print(f"\nProxy test results: {passed} passed, {failed} failed")

        if passed == 0:
            print("✗ No proxies working! Please check your proxy list.\n")
            sys.exit(1)

        print("✓ At least some proxies are working\n")

    except Exception as e:
        print(f"✗ Error testing proxies: {e}\n")
        sys.exit(1)


def stop_existing_scrapers():
    """Stop any existing single-worker scrapers."""
    print("Checking for existing scrapers...")

    import subprocess

    try:
        # Check for running cli_crawl_yp.py processes
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True,
            timeout=5
        )

        found = []
        for line in result.stdout.split('\n'):
            if 'cli_crawl_yp.py' in line and 'grep' not in line:
                parts = line.split()
                if len(parts) > 1:
                    pid = parts[1]
                    found.append(pid)

        if found:
            print(f"Found {len(found)} existing scraper(s), stopping...")
            # Import process manager for cross-platform process termination
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from niceui.utils.process_manager import find_and_kill_processes_by_name

            # Kill all matching processes
            patterns = ['run_state_workers', 'worker_pool', 'state_worker_']
            killed_count = find_and_kill_processes_by_name(patterns)
            print(f"  ✓ Stopped {killed_count} processes")
        else:
            print("✓ No existing scrapers found")

    except Exception as e:
        print(f"Warning: Could not check for existing scrapers: {e}")

    print()


def get_target_stats():
    """Get statistics about targets to process."""
    print("Checking target statistics...")

    try:
        session = create_worker_session()

        # Total targets
        total = session.query(func.count(YPTarget.id)).scalar()

        # By status
        planned = session.query(func.count(YPTarget.id)).filter(YPTarget.status == 'planned').scalar()
        in_progress = session.query(func.count(YPTarget.id)).filter(YPTarget.status == 'in_progress').scalar()
        done = session.query(func.count(YPTarget.id)).filter(YPTarget.status == 'done').scalar()
        failed = session.query(func.count(YPTarget.id)).filter(YPTarget.status == 'failed').scalar()

        session.close()

        print(f"Total targets: {total:,}")
        print(f"  Planned:     {planned:,}")
        print(f"  In Progress: {in_progress:,}")
        print(f"  Done:        {done:,} ({done/total*100 if total > 0 else 0:.1f}%)")
        print(f"  Failed:      {failed:,}")

        if planned == 0:
            print("\n⚠️  Warning: No planned targets! Generate targets first with:")
            print("     python -m scrape_yp.generate_city_targets --states <states>")
            print()
            return False

        # Estimate completion time
        workers = WorkerConfig.WORKER_COUNT
        targets_per_worker_per_hour = 60 / ((WorkerConfig.MIN_DELAY_SECONDS + WorkerConfig.MAX_DELAY_SECONDS) / 2 / 60)
        total_per_hour = workers * targets_per_worker_per_hour
        hours_remaining = planned / total_per_hour if total_per_hour > 0 else 0
        days_remaining = hours_remaining / 24

        print(f"\nEstimated completion:")
        print(f"  Workers: {workers}")
        print(f"  Speed: ~{total_per_hour:.0f} targets/hour")
        print(f"  Time: ~{hours_remaining:.1f} hours (~{days_remaining:.1f} days)")

        print()
        return True

    except Exception as e:
        print(f"✗ Error getting target stats: {e}\n")
        return False


def confirm_start():
    """Ask user to confirm before starting."""
    print("=" * 70)
    print("Ready to start parallel scraping!")
    print("=" * 70)
    print()
    print("Press Enter to start, or Ctrl+C to cancel...")

    try:
        input()
    except KeyboardInterrupt:
        print("\n\nCancelled by user\n")
        sys.exit(0)

    print()


def launch_workers():
    """Launch worker pool."""
    print("=" * 70)
    print("Launching workers...")
    print("=" * 70)
    print()

    # Parse states
    if WorkerConfig.TARGET_STATES == "ALL":
        print("Loading all available states from database...")
        session = create_worker_session()
        state_ids = session.query(YPTarget.state_id).distinct().all()
        state_ids = [s[0] for s in state_ids]
        session.close()
    else:
        state_ids = [s.strip() for s in WorkerConfig.TARGET_STATES.split(',')]

    print(f"Scraping {len(state_ids)} states: {', '.join(state_ids)}")
    print()

    # Create worker pool
    pool = WorkerPoolManager(
        num_workers=WorkerConfig.WORKER_COUNT,
        proxy_file=WorkerConfig.PROXY_FILE,
        state_ids=state_ids
    )

    # Setup signal handlers
    def signal_handler(sig, frame):
        print("\n\nReceived interrupt signal, stopping workers...")
        pool.stop()
        print("\nWorkers stopped. Exiting.\n")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start workers
    pool.start()

    print()
    print("=" * 70)
    print(f"Worker pool running with {pool.num_workers} workers")
    print("=" * 70)
    print()
    print("Monitoring:")
    print(f"  - Worker logs: logs/worker_*.log")
    print(f"  - Pool log: {WorkerConfig.WORKER_POOL_LOG_FILE}")
    print()
    print("To monitor progress:")
    print("  - Check GUI: http://127.0.0.1:8080 → Discover → Yellow Pages")
    print("  - Check database: psql -c 'SELECT status, COUNT(*) FROM yp_targets GROUP BY status;'")
    print()
    print("Press Ctrl+C to stop all workers")
    print()

    # Wait for completion
    try:
        pool.wait()
        print("\n" + "=" * 70)
        print("All workers finished!")
        print("=" * 70)
        print()
    except KeyboardInterrupt:
        print("\n\nInterrupted, stopping workers...")
        pool.stop()


def main():
    """Main entry point."""
    print_banner()
    validate_and_print_config()
    test_proxies()
    stop_existing_scrapers()

    if not get_target_stats():
        sys.exit(1)

    confirm_start()
    launch_workers()

    print("\nDone!\n")


if __name__ == "__main__":
    main()
