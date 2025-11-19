#!/usr/bin/env python3
"""
CLI wrapper for Bing Local Search city-first crawler.
Used by NiceGUI to run city-first discovery as a subprocess.

Usage:
    python cli_crawl_bing_city_first.py --states RI --max-targets 10 --save
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

from scrape_bing.bing_crawl_city_first import crawl_city_targets
from runner.logging_setup import get_logger

# Load environment variables
load_dotenv()

# Logger will be initialized after parsing args to support custom log files
logger = None


async def main():
    """Main entry point for CLI city-first crawler."""
    parser = argparse.ArgumentParser(
        description="Bing Local Search city-first crawler CLI"
    )
    parser.add_argument(
        "--states",
        type=str,
        nargs="+",
        required=True,
        help="State codes to crawl (e.g., RI MA CT)",
    )
    parser.add_argument(
        "--max-targets",
        type=int,
        default=None,
        help="Maximum targets to process (default: all)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        default=True,
        help="Save results to database (default: True)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save to database (testing mode)",
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
        help="Custom log file path (default: logs/bing_crawl_city_first.log)",
    )

    args = parser.parse_args()

    # Handle no-flags
    save_to_db = not args.no_save

    # Normalize state codes
    state_ids = [s.upper() for s in args.states]

    # Initialize logger (with custom log file if provided)
    global logger
    if args.log_file:
        # Manual logger setup for custom log file
        import logging
        logger = logging.getLogger(f"cli_bing_city_first_worker_{args.worker_id or 'custom'}")
        logger.setLevel(logging.INFO)

        # Create file handler
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path)
        handler.setLevel(logging.INFO)

        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(handler)

        # Also add console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    else:
        # Use default logger
        logger = get_logger("cli_bing_city_first")

    logger.info("=" * 80)
    logger.info("BING LOCAL SEARCH CITY-FIRST CRAWLER")
    if args.worker_id:
        logger.info(f"Worker ID: {args.worker_id}")
    logger.info("=" * 80)
    logger.info(f"States: {', '.join(state_ids)}")
    logger.info(f"Max targets: {args.max_targets or 'all'}")
    logger.info(f"Save to DB: {save_to_db}")
    if args.log_file:
        logger.info(f"Log file: {args.log_file}")
    logger.info("=" * 80)

    # Create database session
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        logger.error("DATABASE_URL not found in environment")
        sys.exit(1)

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Track overall stats
        total_targets = 0
        total_businesses = 0
        total_saved = 0
        total_duplicates = 0
        total_captchas = 0

        # Run city-first crawler
        async for batch in crawl_city_targets(
            state_ids=state_ids,
            session=session,
            max_targets=args.max_targets,
            save_to_db=save_to_db,
            use_session_breaks=True,
            checkpoint_interval=10,
            recover_orphans=True
        ):
            target = batch['target']
            results = batch['results']
            stats = batch['stats']

            # Update totals
            total_targets += 1
            total_businesses += stats['total_found']
            total_saved += stats['total_saved']
            total_duplicates += stats['duplicates_skipped']
            if stats.get('captcha_detected'):
                total_captchas += 1

            # Log batch results
            logger.info("-" * 80)
            logger.info(f"COMPLETED: {target.city}, {target.state_id} - {target.category_label}")
            logger.info(f"  Found: {stats['total_found']}")
            logger.info(f"  Saved: {stats['total_saved']}")
            logger.info(f"  Duplicates: {stats['duplicates_skipped']}")
            logger.info(f"  CAPTCHA: {'YES' if stats.get('captcha_detected') else 'NO'}")
            logger.info(f"  Total Progress: {total_targets} targets | {total_businesses} businesses")
            logger.info("-" * 80)

        # Final summary
        logger.info("=" * 80)
        logger.info("CITY-FIRST CRAWL COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Targets processed: {total_targets}")
        logger.info(f"Businesses found: {total_businesses}")
        logger.info(f"Saved to database: {total_saved}")
        logger.info(f"Duplicates skipped: {total_duplicates}")
        logger.info(f"CAPTCHAs detected: {total_captchas}")
        logger.info("=" * 80)

        if total_captchas > 0:
            logger.warning(f"CAPTCHA rate: {total_captchas}/{total_targets} = {total_captchas/total_targets*100:.1f}%")

    except Exception as e:
        logger.error(f"City-first crawler failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
