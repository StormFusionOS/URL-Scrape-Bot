#!/usr/bin/env python3
"""
CLI entrypoint for SERP scraper.

Usage:
    python -m seo_intelligence.serp.cli [--limit N] [--headless] [--proxy PROXY]

Examples:
    # Scrape all tracked queries
    python -m seo_intelligence.serp.cli

    # Scrape first 5 queries only
    python -m seo_intelligence.serp.cli --limit 5

    # Run with visible browser (for debugging)
    python -m seo_intelligence.serp.cli --no-headless

    # Run with proxy
    python -m seo_intelligence.serp.cli --proxy http://proxy:8080

Cron schedule (daily at 6 AM):
    0 6 * * * cd /path/to/washdb-bot && python -m seo_intelligence.serp.cli
"""
import argparse
import logging
import sys

from .scraper import SERPScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('serp_scraper.log')
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description='SERP scraper for SEO intelligence system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Maximum number of queries to scrape (default: all)'
    )

    parser.add_argument(
        '--headless',
        action='store_true',
        default=True,
        help='Run browser in headless mode (default: True)'
    )

    parser.add_argument(
        '--no-headless',
        action='store_false',
        dest='headless',
        help='Run browser with visible UI (for debugging)'
    )

    parser.add_argument(
        '--proxy',
        type=str,
        default=None,
        help='Proxy server URL (e.g., http://proxy:8080)'
    )

    parser.add_argument(
        '--our-domain',
        type=str,
        default=None,
        help='Our domain for marking our_rank (e.g., example.com)'
    )

    parser.add_argument(
        '--database-url',
        type=str,
        default=None,
        help='Database URL (defaults to DATABASE_URL env var)'
    )

    args = parser.parse_args()

    logger.info("Starting SERP scraper...")
    logger.info(f"Configuration: limit={args.limit}, headless={args.headless}, proxy={args.proxy}")

    try:
        # Build proxy config if provided
        proxy_config = None
        if args.proxy:
            proxy_config = {'server': args.proxy}

        # Initialize scraper
        with SERPScraper(
            database_url=args.database_url,
            our_domain=args.our_domain,
            proxy=proxy_config,
            headless=args.headless
        ) as scraper:
            # Run scraper
            results = scraper.scrape_all_tracked(limit=args.limit)

            # Print summary
            logger.info("=" * 50)
            logger.info("SERP Scraping Complete")
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
