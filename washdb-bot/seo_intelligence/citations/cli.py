#!/usr/bin/env python3
"""
CLI entrypoint for citations scraper.

Usage:
    python -m seo_intelligence.citations.cli --citations-file citations.json

Example citations.json:
    [
        {"directory_name": "Google Business", "profile_url": "https://..."},
        {"directory_name": "Yelp", "profile_url": "https://..."}
    ]

Cron schedule (weekly on Monday at 4 AM):
    0 4 * * 1 cd /path/to/washdb-bot && python -m seo_intelligence.citations.cli --citations-file /path/to/citations.json
"""
import argparse
import json
import logging
import sys

from .scraper import CitationsScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('citations.log')
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description='Citations scraper for SEO intelligence system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--citations-file',
        type=str,
        required=True,
        help='Path to JSON file with citations list'
    )

    parser.add_argument(
        '--canonical-name',
        type=str,
        default=None,
        help='Canonical business name for NAP matching'
    )

    parser.add_argument(
        '--canonical-address',
        type=str,
        default=None,
        help='Canonical address for NAP matching'
    )

    parser.add_argument(
        '--canonical-phone',
        type=str,
        default=None,
        help='Canonical phone for NAP matching'
    )

    parser.add_argument(
        '--database-url',
        type=str,
        default=None,
        help='Database URL (defaults to DATABASE_URL env var)'
    )

    args = parser.parse_args()

    logger.info("Starting citations scraper...")

    try:
        # Load citations list
        with open(args.citations_file, 'r') as f:
            citations_list = json.load(f)

        logger.info(f"Loaded {len(citations_list)} citations from {args.citations_file}")

        # Initialize scraper
        scraper = CitationsScraper(
            database_url=args.database_url,
            canonical_name=args.canonical_name,
            canonical_address=args.canonical_address,
            canonical_phone=args.canonical_phone
        )

        # Run scraper
        results = scraper.scrape_all_citations(citations_list)

        # Get consistency report
        report = scraper.get_citation_consistency_report()

        # Print results
        logger.info("=" * 50)
        logger.info("Citations Scraping Complete")
        logger.info("=" * 50)
        logger.info(f"Success: {results['success']}")
        logger.info(f"Failed:  {results['failed']}")
        logger.info("")
        logger.info("Citation Consistency Report:")
        logger.info(f"  Total Citations: {report.get('total', 0)}")
        logger.info(f"  Name Match:      {report.get('name_match_pct', 0):.1f}%")
        logger.info(f"  Phone Match:     {report.get('phone_match_pct', 0):.1f}%")
        logger.info(f"  Address Match:   {report.get('address_match_pct', 0):.1f}%")
        logger.info(f"  Avg Rating:      {report.get('avg_rating', 0):.2f}")
        logger.info(f"  Total Reviews:   {report.get('total_reviews', 0)}")
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
