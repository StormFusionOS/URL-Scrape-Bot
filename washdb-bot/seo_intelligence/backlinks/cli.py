#!/usr/bin/env python3
"""
CLI entrypoint for backlinks tracker and LAS calculator.

Usage:
    python -m seo_intelligence.backlinks.cli [--mode MODE]

Examples:
    # Extract backlinks from all competitor pages
    python -m seo_intelligence.backlinks.cli --mode backlinks

    # Calculate LAS for all competitors
    python -m seo_intelligence.backlinks.cli --mode las

    # Run both (default)
    python -m seo_intelligence.backlinks.cli

Cron schedule (nightly at 3 AM):
    0 3 * * * cd /path/to/washdb-bot && python -m seo_intelligence.backlinks.cli
"""
import argparse
import logging
import sys

from .las_calculator import LASCalculator
from .tracker import BacklinksTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backlinks.log')
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description='Backlinks tracker and LAS calculator for SEO intelligence system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--mode',
        choices=['backlinks', 'las', 'both'],
        default='both',
        help='Operation mode (default: both)'
    )

    parser.add_argument(
        '--database-url',
        type=str,
        default=None,
        help='Database URL (defaults to DATABASE_URL env var)'
    )

    args = parser.parse_args()

    logger.info("Starting backlinks/LAS processing...")
    logger.info(f"Mode: {args.mode}")

    try:
        # Run backlinks extraction
        if args.mode in ['backlinks', 'both']:
            logger.info("=" * 50)
            logger.info("EXTRACTING BACKLINKS")
            logger.info("=" * 50)

            tracker = BacklinksTracker(database_url=args.database_url)
            backlinks_results = tracker.process_all_pages()

            logger.info("Backlinks Results:")
            logger.info(f"  Processed: {backlinks_results['processed']}")
            logger.info(f"  New Links: {backlinks_results['new_backlinks']}")
            logger.info(f"  Failed:    {backlinks_results['failed']}")

        # Run LAS calculation
        if args.mode in ['las', 'both']:
            logger.info("=" * 50)
            logger.info("CALCULATING LOCAL AUTHORITY SCORES")
            logger.info("=" * 50)

            calculator = LASCalculator(database_url=args.database_url)
            las_results = calculator.update_all_competitors()

            logger.info("LAS Results:")
            logger.info(f"  Updated: {las_results['updated']}")
            logger.info(f"  Failed:  {las_results['failed']}")

            # Show top 10 competitors
            logger.info("\nTop 10 Competitors by LAS:")
            top_competitors = calculator.get_top_competitors(limit=10)
            for i, comp in enumerate(top_competitors, 1):
                logger.info(
                    f"  {i}. {comp['name']} ({comp['domain']}): "
                    f"LAS {comp['las']:.2f}"
                )

        logger.info("=" * 50)
        logger.info("Processing Complete")
        logger.info("=" * 50)

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(130)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
