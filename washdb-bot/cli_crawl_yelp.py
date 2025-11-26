#!/usr/bin/env python3
"""
CLI script to run Yelp city-first crawler.

Usage:
    python cli_crawl_yelp.py --states RI --max-targets 10
    python cli_crawl_yelp.py --states RI,CA,TX --scrape-details
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import YelpTarget
from scrape_yelp.yelp_crawl_city_first import crawl_city_targets
from runner.logging_setup import get_logger

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in .env file")

logger = get_logger("cli_crawl_yelp")


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run Yelp city-first crawler"
    )
    parser.add_argument(
        "--states",
        type=str,
        required=True,
        help="Comma-separated list of state codes (e.g., 'RI,CA,TX')"
    )
    parser.add_argument(
        "--max-targets",
        type=int,
        default=None,
        help="Maximum number of targets to process (default: all)"
    )
    parser.add_argument(
        "--scrape-details",
        action="store_true",
        help="Scrape full business details (slower but more complete)"
    )
    parser.add_argument(
        "--no-session-breaks",
        action="store_true",
        help="Disable session breaks (not recommended)"
    )

    args = parser.parse_args()

    # Parse state list
    state_ids = [s.strip().upper() for s in args.states.split(",")]

    logger.info(f"Starting Yelp crawler for states: {', '.join(state_ids)}")
    logger.info(f"Max targets: {args.max_targets or 'All'}")
    logger.info(f"Scrape details: {args.scrape_details}")
    logger.info(f"Session breaks: {not args.no_session_breaks}")

    # Connect to database
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        total_results = 0
        total_targets = 0

        # Run crawler
        async for batch in crawl_city_targets(
            state_ids=state_ids,
            session=session,
            max_targets=args.max_targets,
            scrape_details=args.scrape_details,
            save_to_db=True,
            use_session_breaks=not args.no_session_breaks,
            checkpoint_interval=10,
            recover_orphans=True,
            orphan_timeout_minutes=60,
        ):
            target = batch['target']
            results = batch['results']
            stats = batch['stats']

            total_results += len(results)
            total_targets += 1

            logger.info(
                f"Completed target: {target.city}, {target.state_id} - {target.category_label} | "
                f"Found: {stats['total_found']}, Saved: {stats['total_saved']}"
            )

        logger.info(f"\n{'='*80}")
        logger.info(f"Crawler completed successfully!")
        logger.info(f"  Targets processed: {total_targets}")
        logger.info(f"  Total results: {total_results}")
        logger.info(f"{'='*80}\n")

    except KeyboardInterrupt:
        logger.warning("\n\nCrawler interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
