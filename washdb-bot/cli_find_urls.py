#!/usr/bin/env python3
"""
CLI wrapper for URL Finder Bot

Usage:
    python cli_find_urls.py              # Process all HA companies
    python cli_find_urls.py --limit 10   # Process first 10 companies
    python cli_find_urls.py -l 50        # Process first 50 companies
"""
import argparse
import asyncio
import sys

from scrape_ha.url_finder import find_urls_for_ha_companies
from runner.logging_setup import get_logger

logger = get_logger("cli_find_urls")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Find external URLs for HomeAdvisor companies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli_find_urls.py              # Process all companies
  python cli_find_urls.py --limit 10   # Process first 10
  python cli_find_urls.py -l 50        # Process first 50
        """,
    )

    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=None,
        help="Maximum number of companies to process (default: all)",
    )

    args = parser.parse_args()

    try:
        # Run URL finder
        found, failed = asyncio.run(find_urls_for_ha_companies(args.limit))

        # Exit code based on results
        if found == 0 and failed > 0:
            sys.exit(1)  # All failed
        else:
            sys.exit(0)  # Success (at least some found)

    except KeyboardInterrupt:
        logger.info("\n\nInterrupted by user")
        sys.exit(130)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
