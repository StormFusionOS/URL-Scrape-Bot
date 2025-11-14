#!/usr/bin/env python3
"""
HomeAdvisor Discovery Pipeline - Unified CLI Launcher

Launches both phases of the pipeline concurrently:
- Phase 1: Discovery (scrapes HomeAdvisor list pages → saves to staging table)
- Phase 2: URL Finder (finds external URLs → saves to companies table)

Usage:
    # Run full pipeline for all categories/states (default 3 pages per state)
    python cli_crawl_ha_pipeline.py

    # Run with custom limits
    python cli_crawl_ha_pipeline.py --categories "power washing,window cleaning" --states "TX,CA" --pages 5

    # Run Phase 2 only (process existing staging queue)
    python cli_crawl_ha_pipeline.py --phase2-only

Architecture:
    Phase 1 (Discovery)          Phase 2 (URL Finder)
    -------------------          --------------------
    Scrape HA lists    →  ha_staging table  ←  Poll every 30s
    Save to staging                             Find URLs (DuckDuckGo)
                                                Dedup by domain
                                                Save to companies table
                                                Delete from staging
"""
import argparse
import asyncio
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from runner.logging_setup import get_logger
from db.save_to_staging import get_staging_stats

logger = get_logger("ha_pipeline")

# Shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down pipeline...")
    shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def run_phase1_discovery(categories: list[str] = None, states: list[str] = None, pages_per_state: int = 3) -> dict:
    """
    Run Phase 1: Discovery (synchronous).

    Launches the ha_crawl module to scrape HomeAdvisor and populate staging table.

    Args:
        categories: List of service categories (None = default)
        states: List of state codes (None = all states)
        pages_per_state: Number of pages to scrape per category/state

    Returns:
        Dict with summary stats from crawl_all_states()
    """
    logger.info("=" * 60)
    logger.info("Phase 1: Discovery Starting")
    logger.info("=" * 60)

    try:
        from scrape_ha.ha_crawl import crawl_all_states

        results = crawl_all_states(
            categories=categories,
            states=states,
            limit_per_state=pages_per_state,
            save_to_db=True
        )

        logger.info("=" * 60)
        logger.info("Phase 1: Discovery Complete")
        logger.info(f"  Found: {results['total_found']} businesses")
        logger.info(f"  Saved: {results['total_saved']} to staging")
        logger.info(f"  Skipped: {results['total_skipped']} duplicates")
        logger.info("=" * 60)

        return results

    except Exception as e:
        logger.error(f"Phase 1 failed: {e}", exc_info=True)
        raise


async def run_phase2_worker():
    """
    Run Phase 2: URL Finder Worker (asynchronous).

    Launches the url_finder_worker module to process staging queue.
    Runs until shutdown signal is received.
    """
    logger.info("=" * 60)
    logger.info("Phase 2: URL Finder Starting")
    logger.info("=" * 60)

    try:
        from scrape_ha.url_finder_worker import worker_loop

        await worker_loop()

        logger.info("=" * 60)
        logger.info("Phase 2: URL Finder Complete")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Phase 2 failed: {e}", exc_info=True)
        raise


async def run_both_phases(categories: list[str] = None, states: list[str] = None, pages_per_state: int = 3):
    """
    Run both phases concurrently.

    Phase 1 runs to completion, Phase 2 runs continuously until shutdown.

    Args:
        categories: List of service categories
        states: List of state codes
        pages_per_state: Number of pages per category/state
    """
    logger.info("=" * 60)
    logger.info("HomeAdvisor Discovery Pipeline")
    logger.info("=" * 60)
    logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")

    # Show staging stats before starting
    try:
        stats = get_staging_stats()
        logger.info("Staging Table (Before):")
        logger.info(f"  Total:    {stats['total']}")
        logger.info(f"  Pending:  {stats['pending']}")
        logger.info(f"  In Retry: {stats['in_retry']}")
        logger.info(f"  Failed:   {stats['failed']}")
        logger.info("")
    except Exception as e:
        logger.warning(f"Could not get staging stats: {e}")

    # Create tasks for both phases
    phase1_task = asyncio.create_task(
        asyncio.to_thread(run_phase1_discovery, categories, states, pages_per_state)
    )

    phase2_task = asyncio.create_task(run_phase2_worker())

    try:
        # Wait for Phase 1 to complete (Phase 2 runs indefinitely)
        phase1_results = await phase1_task

        logger.info("")
        logger.info("Phase 1 has completed. Phase 2 continues processing queue...")
        logger.info("Press Ctrl+C to stop the pipeline.")
        logger.info("")

        # Wait for Phase 2 (until shutdown signal)
        await phase2_task

    except asyncio.CancelledError:
        logger.info("Pipeline tasks cancelled")
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
    finally:
        # Cancel any remaining tasks
        if not phase1_task.done():
            phase1_task.cancel()
        if not phase2_task.done():
            phase2_task.cancel()

        # Show final stats
        try:
            stats = get_staging_stats()
            logger.info("")
            logger.info("=" * 60)
            logger.info("Staging Table (Final):")
            logger.info(f"  Total:    {stats['total']}")
            logger.info(f"  Pending:  {stats['pending']}")
            logger.info(f"  In Retry: {stats['in_retry']}")
            logger.info(f"  Failed:   {stats['failed']}")
            logger.info("=" * 60)
        except Exception as e:
            logger.warning(f"Could not get final staging stats: {e}")

        logger.info("")
        logger.info(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)


def parse_comma_separated(value: str) -> list[str]:
    """Parse comma-separated string into list."""
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="HomeAdvisor Discovery Pipeline (Phase 1 + Phase 2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline with defaults
  %(prog)s

  # Custom categories and states
  %(prog)s --categories "power washing,window cleaning" --states "TX,CA,NY"

  # More pages per state
  %(prog)s --pages 5

  # Run Phase 2 only (process existing staging queue)
  %(prog)s --phase2-only

  # Run Phase 1 only (discovery without URL finding)
  %(prog)s --phase1-only

Pipeline Architecture:
  Phase 1: Scrape HA → Staging Table
  Phase 2: Staging Table → Find URLs → Companies Table
        """
    )

    parser.add_argument(
        "--categories",
        type=str,
        help="Comma-separated service categories (default: power washing, window cleaning, etc.)"
    )

    parser.add_argument(
        "--states",
        type=str,
        help="Comma-separated state codes (default: all 50 states)"
    )

    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Number of pages to scrape per category/state (default: 3)"
    )

    parser.add_argument(
        "--phase1-only",
        action="store_true",
        help="Run Phase 1 only (discovery, no URL finding)"
    )

    parser.add_argument(
        "--phase2-only",
        action="store_true",
        help="Run Phase 2 only (URL finder worker, no discovery)"
    )

    args = parser.parse_args()

    # Parse categories and states
    categories = parse_comma_separated(args.categories)
    states = parse_comma_separated(args.states)

    try:
        if args.phase1_only:
            # Run Phase 1 only
            logger.info("Running Phase 1 only (discovery)")
            run_phase1_discovery(categories, states, args.pages)

        elif args.phase2_only:
            # Run Phase 2 only
            logger.info("Running Phase 2 only (URL finder worker)")
            asyncio.run(run_phase2_worker())

        else:
            # Run both phases
            logger.info("Running both phases concurrently")
            asyncio.run(run_both_phases(categories, states, args.pages))

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
