#!/usr/bin/env python3
"""
Launch script for 5-worker state-partitioned scraping system (Yellow Pages).

This script:
1. Validates configuration and database connectivity
2. Shows state assignments and proxy distribution
3. Displays target statistics per state
4. Launches the worker pool manager
5. Monitors progress

Usage:
    python scripts/run_state_workers_5.py
    python scripts/run_state_workers_5.py --workers 5
    python scripts/run_state_workers_5.py --test  # Test with 2 workers only
"""

import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from sqlalchemy import text
from runner.logging_setup import get_logger
from scrape_yp.state_assignments_5worker import get_states_for_worker, get_proxy_assignments, validate_assignments
from scrape_yp.state_worker_pool_5 import StateWorkerPoolManager
from db import create_session
from db.models import YPTarget

logger = get_logger("run_state_workers_5")


def validate_environment():
    """Validate environment and configuration."""
    logger.info("="*70)
    logger.info("VALIDATING ENVIRONMENT")
    logger.info("="*70)

    # Check .env file
    env_path = Path(".env")
    if not env_path.exists():
        logger.error("❌ .env file not found!")
        return False

    logger.info("✓ .env file found")

    # Load environment
    load_dotenv()

    # Check proxy file
    proxy_file = os.getenv("PROXY_FILE", "data/webshare_proxies.txt")
    proxy_path = Path(proxy_file)

    if not proxy_path.exists():
        logger.error(f"❌ Proxy file not found: {proxy_file}")
        return False

    # Count proxies
    with open(proxy_path, 'r') as f:
        proxy_count = sum(1 for line in f if line.strip() and not line.startswith('#'))

    logger.info(f"✓ Proxy file found: {proxy_count} proxies available")

    if proxy_count < 50:
        logger.warning(f"⚠️  Only {proxy_count} proxies available (recommended: 50)")
    else:
        logger.info(f"✓ Sufficient proxies: {proxy_count}/50")

    # Check database connectivity
    try:
        session = create_session()
        result = session.execute(text("SELECT 1")).scalar()
        session.close()
        logger.info("✓ Database connection successful")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

    # Validate state assignments
    try:
        validate_assignments()
        logger.info("✓ State assignments validated")
    except Exception as e:
        logger.error(f"❌ State assignment validation failed: {e}")
        return False

    logger.info("="*70)
    logger.info("✓ Environment validation PASSED")
    logger.info("="*70)
    return True


def show_state_assignments(num_workers: int):
    """Display state assignments for all workers."""
    logger.info("")
    logger.info("="*70)
    logger.info(f"STATE ASSIGNMENTS ({num_workers} WORKERS)")
    logger.info("="*70)

    for worker_id in range(num_workers):
        states = get_states_for_worker(worker_id)
        proxies = get_proxy_assignments(worker_id)

        logger.info(f"Worker {worker_id}:")
        logger.info(f"  States:  {', '.join(states)}")
        logger.info(f"  Proxies: {proxies[0]}-{proxies[-1]} ({len(proxies)} total)")
        logger.info("")

    logger.info("="*70)


def show_target_statistics(num_workers: int):
    """Show target statistics per worker."""
    logger.info("")
    logger.info("="*70)
    logger.info("TARGET STATISTICS BY WORKER")
    logger.info("="*70)

    try:
        session = create_session()

        total_planned = 0
        total_in_progress = 0
        total_done = 0
        total_failed = 0

        for worker_id in range(num_workers):
            states = get_states_for_worker(worker_id)

            # Count targets by status
            planned = session.query(YPTarget).filter(
                YPTarget.state_id.in_(states),
                YPTarget.status == "planned"
            ).count()

            in_progress = session.query(YPTarget).filter(
                YPTarget.state_id.in_(states),
                YPTarget.status == "in_progress"
            ).count()

            done = session.query(YPTarget).filter(
                YPTarget.state_id.in_(states),
                YPTarget.status == "done"
            ).count()

            failed = session.query(YPTarget).filter(
                YPTarget.state_id.in_(states),
                YPTarget.status == "failed"
            ).count()

            total = planned + in_progress + done + failed

            logger.info(f"Worker {worker_id} ({', '.join(states)}):")
            logger.info(f"  Total targets:   {total:,}")
            logger.info(f"  Planned:         {planned:,}")
            logger.info(f"  In Progress:     {in_progress:,}")
            logger.info(f"  Done:            {done:,}")
            logger.info(f"  Failed:          {failed:,}")

            if total > 0:
                progress_pct = ((done + failed) / total) * 100
                logger.info(f"  Progress:        {progress_pct:.1f}%")

            logger.info("")

            total_planned += planned
            total_in_progress += in_progress
            total_done += done
            total_failed += failed

        session.close()

        # Overall totals
        grand_total = total_planned + total_in_progress + total_done + total_failed
        logger.info("-"*70)
        logger.info(f"OVERALL TOTALS:")
        logger.info(f"  Total targets:   {grand_total:,}")
        logger.info(f"  Planned:         {total_planned:,}")
        logger.info(f"  In Progress:     {total_in_progress:,}")
        logger.info(f"  Done:            {total_done:,}")
        logger.info(f"  Failed:          {total_failed:,}")

        if grand_total > 0:
            overall_progress = ((total_done + total_failed) / grand_total) * 100
            logger.info(f"  Progress:        {overall_progress:.1f}%")

            # Estimate completion time
            if overall_progress > 0 and total_done > 0:
                # Assume 5 workers, ~3 targets/min/worker = 15 targets/min
                remaining = total_planned + total_in_progress
                targets_per_min = num_workers * 3
                minutes_remaining = remaining / targets_per_min
                hours_remaining = minutes_remaining / 60
                days_remaining = hours_remaining / 24

                logger.info(f"  Estimated time:  {days_remaining:.1f} days ({hours_remaining:.1f} hours)")

        logger.info("="*70)

    except Exception as e:
        logger.error(f"Error getting target statistics: {e}", exc_info=True)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Launch 5-worker state-partitioned worker pool (YP)")
    parser.add_argument("--workers", type=int, default=5, help="Number of workers (default: 5)")
    parser.add_argument("--test", action="store_true", help="Test mode: only 2 workers")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    # Test mode: reduce workers
    num_workers = 2 if args.test else args.workers

    if args.test:
        logger.info("🧪 TEST MODE: Running with 2 workers only")
        logger.info("")

    # Validate environment
    if not validate_environment():
        logger.error("❌ Environment validation failed. Please fix errors and try again.")
        sys.exit(1)

    # Show assignments
    show_state_assignments(num_workers)

    # Show statistics
    show_target_statistics(num_workers)

    # Confirm before starting
    logger.info("")
    logger.info("="*70)
    logger.info(f"Ready to launch {num_workers} workers")
    logger.info("="*70)

    # Ask for confirmation unless --yes or --test flag is provided
    if not args.yes and not args.test:
        response = input("\nStart workers? [y/N]: ")
        if response.lower() != 'y':
            logger.info("Cancelled by user")
            sys.exit(0)

    # Build configuration
    config = {
        "proxy_file": os.getenv("PROXY_FILE", "data/webshare_proxies.txt"),
        "num_workers": num_workers,
        "min_delay_seconds": float(os.getenv("MIN_DELAY_SECONDS", "10.0")),
        "max_delay_seconds": float(os.getenv("MAX_DELAY_SECONDS", "20.0")),
        "max_targets_per_browser": int(os.getenv("MAX_TARGETS_PER_BROWSER", "100")),
        "blacklist_threshold": int(os.getenv("PROXY_BLACKLIST_THRESHOLD", "10")),
        "blacklist_duration_minutes": int(os.getenv("PROXY_BLACKLIST_DURATION_MINUTES", "60")),
        "headless": os.getenv("BROWSER_HEADLESS", "true").lower() == "true",
        "min_confidence_score": float(os.getenv("MIN_CONFIDENCE_SCORE", "50.0")),
        "include_sponsored": os.getenv("INCLUDE_SPONSORED", "false").lower() == "true",
        "enable_monitor": False,  # Disable monitor for now
    }

    logger.info("")
    logger.info("Configuration:")
    for key, value in config.items():
        logger.info(f"  {key}: {value}")

    # Create and start pool
    logger.info("")
    logger.info("="*70)
    logger.info("LAUNCHING WORKER POOL")
    logger.info("="*70)

    try:
        pool = StateWorkerPoolManager(config)
        pool.start()

        logger.info("")
        logger.info("✓ Worker pool started successfully")
        logger.info("  Monitor logs in logs/state_worker_*.log")
        logger.info("  Press Ctrl+C to stop")
        logger.info("")

        # Wait for completion
        pool.wait()

    except KeyboardInterrupt:
        logger.info("")
        logger.info("Keyboard interrupt received, shutting down...")
        pool.stop()

    except Exception as e:
        logger.error(f"Error running worker pool: {e}", exc_info=True)
        sys.exit(1)

    logger.info("")
    logger.info("="*70)
    logger.info("WORKER POOL STOPPED")
    logger.info("="*70)


if __name__ == "__main__":
    main()
