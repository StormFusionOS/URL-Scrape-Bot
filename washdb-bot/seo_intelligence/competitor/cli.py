#!/usr/bin/env python3
"""
CLI entrypoint for competitor crawler.

Usage:
    python -m seo_intelligence.competitor.cli [--competitor-id ID] [--max-pages N]

Examples:
    # Crawl all tracked competitors
    python -m seo_intelligence.competitor.cli

    # Crawl specific competitor
    python -m seo_intelligence.competitor.cli --competitor-id 123

    # Limit pages per site
    python -m seo_intelligence.competitor.cli --max-pages 50

    # Disable embeddings generation
    python -m seo_intelligence.competitor.cli --no-embeddings

Cron schedule (weekly on Sunday at 2 AM):
    0 2 * * 0 cd /path/to/washdb-bot && python -m seo_intelligence.competitor.cli
"""
import argparse
import logging
import sys

from .crawler import CompetitorCrawler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('competitor_crawler.log')
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description='Competitor crawler for SEO intelligence system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--competitor-id',
        type=int,
        default=None,
        help='Crawl specific competitor by ID (default: all)'
    )

    parser.add_argument(
        '--max-pages',
        type=int,
        default=None,
        help='Maximum pages to crawl per site (default: 100)'
    )

    parser.add_argument(
        '--no-snapshots',
        action='store_false',
        dest='save_snapshots',
        default=True,
        help='Disable HTML snapshot saving'
    )

    parser.add_argument(
        '--no-embeddings',
        action='store_false',
        dest='generate_embeddings',
        default=True,
        help='Disable embeddings generation'
    )

    parser.add_argument(
        '--database-url',
        type=str,
        default=None,
        help='Database URL (defaults to DATABASE_URL env var)'
    )

    parser.add_argument(
        '--track-only',
        action='store_true',
        default=True,
        help='Only crawl competitors with track=True (default: True)'
    )

    parser.add_argument(
        '--all-competitors',
        action='store_false',
        dest='track_only',
        help='Crawl all competitors regardless of track flag'
    )

    args = parser.parse_args()

    logger.info("Starting competitor crawler...")
    logger.info(
        f"Configuration: competitor_id={args.competitor_id}, "
        f"max_pages={args.max_pages}, snapshots={args.save_snapshots}, "
        f"embeddings={args.generate_embeddings}"
    )

    try:
        # Initialize crawler
        crawler = CompetitorCrawler(
            database_url=args.database_url,
            max_urls_per_site=args.max_pages or 100,
            save_snapshots=args.save_snapshots,
            generate_embeddings=args.generate_embeddings
        )

        # Run crawler
        if args.competitor_id:
            # Crawl specific competitor
            results = crawler.crawl_competitor(
                competitor_id=args.competitor_id,
                max_pages=args.max_pages
            )
        else:
            # Crawl all competitors
            results = crawler.crawl_all_competitors(
                track_only=args.track_only,
                max_pages_per_site=args.max_pages
            )

        # Print summary
        logger.info("=" * 50)
        logger.info("Competitor Crawling Complete")
        logger.info("=" * 50)
        logger.info(f"Success: {results['success']}")
        logger.info(f"Failed:  {results['failed']}")
        logger.info(f"Skipped: {results['skipped']}")
        logger.info("=" * 50)

        # Exit with error code if any failed
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
