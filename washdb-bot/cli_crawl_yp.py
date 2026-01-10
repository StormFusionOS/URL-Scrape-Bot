#!/usr/bin/env python3
"""
Yellow Pages Crawler CLI - City-First Approach (Default)

This is the main CLI for the Yellow Pages scraper using the city-first strategy.
Targets are auto-generated from city_registry at startup if they don't exist.

Usage:
    python cli_crawl_yp.py --states RI --min-score 50
    python cli_crawl_yp.py --states "CA,TX,FL" --max-targets 1000
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.save_discoveries import upsert_discovered
from runner.logging_setup import get_logger
from runner.safety import create_safety_limits_from_env, create_rate_limiter_from_env
from scrape_yp.yp_crawl_city_first import crawl_city_targets

# Load environment variables
load_dotenv()

# Initialize logger
logger = get_logger("cli_yp")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in .env file")


def ensure_targets_exist(session, state_ids: list[str]) -> int:
    """
    Ensure targets exist for the specified states.
    Auto-generates from city_registry if no targets found.
    Also checks if category configuration has changed and regenerates if needed.

    Args:
        session: SQLAlchemy session
        state_ids: List of 2-letter state codes

    Returns:
        Number of planned targets available
    """
    from db.models import YPTarget
    from scrape_yp.generate_city_targets import check_and_regenerate_if_needed

    # Check if category configuration has changed
    # This will regenerate targets if yp_category_slugs.csv or other config files changed
    regenerated = check_and_regenerate_if_needed(state_ids)
    if regenerated:
        # Targets were regenerated, return the new count
        return (
            session.query(YPTarget)
            .filter(
                YPTarget.state_id.in_(state_ids),
                YPTarget.status == "planned"
            )
            .count()
        )

    # Check if targets exist for these states
    existing_count = (
        session.query(YPTarget)
        .filter(
            YPTarget.state_id.in_(state_ids),
            YPTarget.status == "planned"
        )
        .count()
    )

    if existing_count > 0:
        logger.info(f"Found {existing_count:,} existing planned targets")
        return existing_count

    # No planned targets - check if any targets exist at all (might be done/failed)
    total_count = (
        session.query(YPTarget)
        .filter(YPTarget.state_id.in_(state_ids))
        .count()
    )

    if total_count > 0:
        # Targets exist but none are planned - show status breakdown
        done_count = session.query(YPTarget).filter(
            YPTarget.state_id.in_(state_ids),
            YPTarget.status == "done"
        ).count()
        logger.info(f"All targets completed: {done_count:,} done out of {total_count:,} total")
        return 0

    # No targets at all - auto-generate from city_registry
    logger.info("No targets found - auto-generating from city_registry...")

    from scrape_yp.generate_city_targets import generate_targets

    try:
        targets_created = generate_targets(
            session,
            state_ids=state_ids,
            clear_existing=False  # Don't clear - we know there are none
        )
        logger.info(f"Auto-generated {targets_created:,} targets")
        return targets_created
    except Exception as e:
        logger.error(f"Failed to auto-generate targets: {e}")
        raise


def progress_callback(target_idx: int, total_targets: int, target, results: list, stats: dict):
    """Progress callback for crawl updates."""
    progress_pct = (target_idx / total_targets) * 100
    logger.info(
        f"Progress: {target_idx}/{total_targets} ({progress_pct:.1f}%) | "
        f"City: {target.city} | Category: {target.category_label} | "
        f"Results: {len(results)} | Acceptance: {stats.get('acceptance_rate', 0):.1f}%"
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Yellow Pages city-first crawler (auto-generates targets from city_registry)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run crawler on Rhode Island (targets auto-generated if needed)
  python cli_crawl_yp.py --states RI

  # Multiple states with custom settings
  python cli_crawl_yp.py --states "CA,TX,FL" --min-score 40 --max-targets 500

  # Dry run (no database saves)
  python cli_crawl_yp.py --states RI --dry-run

Note: Targets are automatically generated from city_registry on first run.
      No manual target generation step is required.
        """
    )

    parser.add_argument(
        "--states",
        type=str,
        required=True,
        help="Comma-separated list of state codes (e.g., 'RI,CA,TX')",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=50.0,
        help="Minimum confidence score (0-100, default: 50.0)",
    )
    parser.add_argument(
        "--include-sponsored",
        action="store_true",
        help="Include sponsored/ad listings (default: False)",
    )
    parser.add_argument(
        "--max-targets",
        type=int,
        default=None,
        help="Maximum number of targets to process (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without saving to database",
    )
    parser.add_argument(
        "--disable-monitoring",
        action="store_true",
        help="Disable monitoring and health checks (default: enabled)",
    )
    parser.add_argument(
        "--disable-adaptive-rate-limiting",
        action="store_true",
        help="Disable adaptive rate limiting (default: enabled)",
    )
    parser.add_argument(
        "--no-session-breaks",
        action="store_true",
        help="Disable session breaks every 50 requests (default: enabled)",
    )
    parser.add_argument(
        "--worker-id",
        type=int,
        default=None,
        help="Worker ID (1-5) for multi-worker deployments",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Custom log file path (default: logs/cli_yp.log)",
    )

    args = parser.parse_args()

    # Configure custom log file if specified
    if args.log_file:
        import logging
        # Add file handler to logger
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(file_handler)

    # Parse state list
    state_ids = [s.strip().upper() for s in args.states.split(",")]

    print("=" * 80)
    print("Yellow Pages Crawler - City-First (Default)")
    if args.worker_id:
        print(f"Worker ID: {args.worker_id}")
    print("=" * 80)
    print(f"States: {', '.join(state_ids)}")
    print(f"Min Score: {args.min_score}")
    print(f"Include Sponsored: {args.include_sponsored}")
    print(f"Max Targets: {args.max_targets or 'All'}")
    print(f"Dry Run: {args.dry_run}")
    if args.log_file:
        print(f"Log File: {args.log_file}")
    print()
    print("Anti-Detection & Monitoring:")
    print(f"  Monitoring: {'Disabled' if args.disable_monitoring else 'Enabled ✓'}")
    print(f"  Adaptive Rate Limiting: {'Disabled' if args.disable_adaptive_rate_limiting else 'Enabled ✓'}")
    print(f"  Session Breaks: {'Disabled' if args.no_session_breaks else 'Enabled ✓'}")
    print()
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    # Create database engine
    engine = create_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Ensure targets exist (auto-generate from city_registry if needed)
        target_count = ensure_targets_exist(session, state_ids)

        if target_count == 0:
            print("⚠️  No planned targets available for these states!")
            print("    (All targets may already be completed)")
            print()
            return 1

        print(f"✓ Found {target_count:,} planned targets")
        if args.max_targets and args.max_targets < target_count:
            print(f"  (will process {args.max_targets} of {target_count})")
        print()

        # Initialize safety limits
        safety = create_safety_limits_from_env()
        limiter = create_rate_limiter_from_env()

        # Run crawler
        total_results_saved = 0
        total_targets_processed = 0
        total_early_exits = 0
        total_errors = 0

        for batch in crawl_city_targets(
            state_ids=state_ids,
            session=session,
            min_score=args.min_score,
            include_sponsored=args.include_sponsored,
            max_targets=args.max_targets,
            progress_callback=progress_callback,
            use_session_breaks=not args.no_session_breaks,
            use_monitoring=not args.disable_monitoring,
            use_adaptive_rate_limiting=not args.disable_adaptive_rate_limiting,
        ):
            # Check safety limits before processing
            if not safety.check_should_continue():
                logger.warning("Safety limit reached, stopping crawler")
                break

            # Apply rate limiting
            import time
            delay = limiter.get_delay()
            if delay > 0:
                logger.debug(f"Rate limit delay: {delay:.1f}s")
                time.sleep(delay)

            target = batch['target']
            results = batch['results']
            stats = batch['stats']

            total_targets_processed += 1
            if stats.get('early_exit'):
                total_early_exits += 1

            # Record page processed
            safety.record_page_processed()

            if results and not args.dry_run:
                # Save to database
                try:
                    inserted, skipped, updated = upsert_discovered(results)
                    total_results_saved += inserted + updated

                    logger.info(
                        f"Saved: {inserted} new, {updated} updated, {skipped} skipped"
                    )

                    # Record success
                    safety.record_success()
                    limiter.record_success()

                except Exception as e:
                    logger.error(f"Failed to save results: {e}")
                    total_errors += 1

                    # Record failure
                    safety.record_failure(str(e))
                    limiter.record_failure()

            elif results:
                logger.info(f"Dry run: would have saved {len(results)} results")
                # Count dry run as success
                safety.record_success()
                limiter.record_success()
            else:
                # No results - record as failure
                safety.record_failure("No results found for target")
                limiter.record_failure()

        # Final summary
        print()
        print("=" * 80)
        print("Crawl Summary")
        print("=" * 80)
        print(f"States: {', '.join(state_ids)}")
        print(f"Targets Processed: {total_targets_processed}")
        print(f"Early Exits: {total_early_exits} ({total_early_exits/total_targets_processed*100:.1f}%)" if total_targets_processed > 0 else "Early Exits: 0")
        print(f"Results Saved: {total_results_saved}")
        print(f"Errors: {total_errors}")
        print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        # Log safety limits summary
        print()
        safety.log_summary()

        return 0

    except KeyboardInterrupt:
        print("\n\nCrawl interrupted by user (Ctrl+C)")
        logger.warning("Crawl interrupted by user")

        # Log safety summary even on interruption
        if 'safety' in locals():
            print()
            safety.log_summary()

        return 130

    except Exception as e:
        print(f"\n\nError: {e}")
        logger.error(f"Crawl failed: {e}", exc_info=True)

        # Log safety summary even on error
        if 'safety' in locals():
            print()
            safety.log_summary()

        return 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
