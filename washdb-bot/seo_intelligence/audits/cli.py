#!/usr/bin/env python3
"""
CLI entrypoint for technical auditor.

Usage:
    python -m seo_intelligence.audits.cli [--competitor-id ID]

Cron schedule (monthly on 1st at 5 AM):
    0 5 1 * * cd /path/to/washdb-bot && python -m seo_intelligence.audits.cli
"""
import argparse
import logging
import sys

from .auditor import TechnicalAuditor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('audits.log')
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description='Technical auditor for SEO intelligence system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--competitor-id',
        type=int,
        default=None,
        help='Audit specific competitor by ID (default: all)'
    )

    parser.add_argument(
        '--database-url',
        type=str,
        default=None,
        help='Database URL (defaults to DATABASE_URL env var)'
    )

    parser.add_argument(
        '--all-competitors',
        action='store_false',
        dest='track_only',
        default=True,
        help='Audit all competitors regardless of track flag'
    )

    args = parser.parse_args()

    logger.info("Starting technical auditor...")

    try:
        # Initialize auditor
        auditor = TechnicalAuditor(database_url=args.database_url)

        # Run audits
        if args.competitor_id:
            # Audit specific competitor
            results = auditor.audit_competitor(competitor_id=args.competitor_id)
        else:
            # Audit all competitors
            results = auditor.audit_all_competitors(track_only=args.track_only)

        # Print summary
        logger.info("=" * 50)
        logger.info("Technical Audits Complete")
        logger.info("=" * 50)
        logger.info(f"Success: {results['success']}")
        logger.info(f"Failed:  {results['failed']}")
        logger.info("=" * 50)

        # Exit with error if any failed
        if results['failed'] > 0:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(130)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
