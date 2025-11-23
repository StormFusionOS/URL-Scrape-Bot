#!/usr/bin/env python3
"""
Test script for Google Maps city-first crawler.

Tests the crawler with a small number of targets to validate:
- All components work together
- Anti-detection measures are effective
- Data extraction works correctly
- Database integration functions properly

Usage:
    python test_google_crawler.py --targets 3
    python test_google_crawler.py --targets 5 --no-details
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import GoogleTarget
from scrape_google.google_crawl_city_first import crawl_city_targets
from runner.logging_setup import get_logger

# Load environment variables
load_dotenv()

# Initialize logger
logger = get_logger("test_google_crawler")


async def run_test(max_targets: int = 3, scrape_details: bool = True, save_to_db: bool = False):
    """
    Run test crawl with limited number of targets.

    Args:
        max_targets: Maximum number of targets to test
        scrape_details: Whether to scrape detailed business info
        save_to_db: Whether to save results to database
    """
    logger.info(f"\n{'='*80}")
    logger.info("GOOGLE MAPS CRAWLER TEST")
    logger.info(f"{'='*80}")
    logger.info(f"Max targets: {max_targets}")
    logger.info(f"Scrape details: {scrape_details}")
    logger.info(f"Save to DB: {save_to_db}")
    logger.info(f"{'='*80}\n")

    # Create database session
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        logger.error("DATABASE_URL not found in environment")
        return

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Show test targets
        logger.info("Test targets:")
        test_targets = (
            session.query(GoogleTarget)
            .filter(GoogleTarget.state_id == 'RI')
            .filter(GoogleTarget.status == 'PLANNED')
            .limit(max_targets)
            .all()
        )

        for idx, target in enumerate(test_targets, 1):
            logger.info(
                f"  {idx}. {target.city}, {target.state_id} - {target.category_label} "
                f"(priority={target.priority}, max_results={target.max_results})"
            )

        logger.info(f"\n{'='*80}\n")

        # Run crawler
        total_results = 0
        total_captchas = 0
        total_errors = 0

        async for batch in crawl_city_targets(
            state_ids=['RI'],
            session=session,
            max_targets=max_targets,
            scrape_details=scrape_details,
            save_to_db=save_to_db,
            use_session_breaks=False,  # Disable for quick testing
            checkpoint_interval=1,
            recover_orphans=True,
        ):
            target = batch['target']
            results = batch['results']
            stats = batch['stats']

            total_results += len(results)
            if stats.get('captcha_detected'):
                total_captchas += 1

            logger.info(f"\n{'='*80}")
            logger.info(f"BATCH RESULTS")
            logger.info(f"{'='*80}")
            logger.info(f"Target: {target.city}, {target.state_id} - {target.category_label}")
            logger.info(f"Query: {target.search_query}")
            logger.info(f"Found: {stats['total_found']} businesses")
            logger.info(f"Saved: {stats['total_saved']} businesses")
            logger.info(f"Duplicates: {stats['duplicates_skipped']}")
            logger.info(f"CAPTCHA: {'YES' if stats['captcha_detected'] else 'NO'}")

            if results:
                logger.info(f"\nSample results:")
                for idx, business in enumerate(results[:3], 1):
                    logger.info(f"  {idx}. {business.get('name', 'Unknown')}")
                    logger.info(f"     Address: {business.get('address', 'N/A')}")
                    logger.info(f"     Rating: {business.get('rating', 'N/A')}")
                    logger.info(f"     Category: {business.get('category', 'N/A')}")
                    logger.info(f"     Website: {business.get('website', 'N/A')}")
                    logger.info(f"     Place ID: {business.get('place_id', 'N/A')}")

                if len(results) > 3:
                    logger.info(f"  ... and {len(results) - 3} more")

            logger.info(f"{'='*80}\n")

        # Final summary
        logger.info(f"\n{'='*80}")
        logger.info("TEST SUMMARY")
        logger.info(f"{'='*80}")
        logger.info(f"Targets processed: {max_targets}")
        logger.info(f"Total results: {total_results}")
        logger.info(f"CAPTCHAs detected: {total_captchas}")
        logger.info(f"Errors: {total_errors}")

        if total_captchas > 0:
            logger.warning(f"\n⚠️  CAPTCHA DETECTED! Rate: {total_captchas/max_targets*100:.1f}%")
            logger.warning("Consider increasing delays or using proxies")

        logger.info(f"{'='*80}\n")

        # Show updated target status
        logger.info("Updated target status:")
        updated_targets = (
            session.query(GoogleTarget)
            .filter(GoogleTarget.id.in_([t.id for t in test_targets]))
            .all()
        )

        for target in updated_targets:
            logger.info(
                f"  {target.city} - {target.category_label}: "
                f"status={target.status}, found={target.results_found}, "
                f"saved={target.results_saved}"
            )

        logger.info(f"\n{'='*80}")
        logger.info("✓ Test complete!")
        logger.info(f"{'='*80}\n")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Google Maps city-first crawler"
    )
    parser.add_argument(
        "--targets",
        type=int,
        default=3,
        help="Number of targets to test (default: 3)",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Skip scraping detailed business info (faster)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to database",
    )

    args = parser.parse_args()

    # Run async test
    asyncio.run(run_test(
        max_targets=args.targets,
        scrape_details=not args.no_details,
        save_to_db=args.save
    ))


if __name__ == "__main__":
    main()
