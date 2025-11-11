#!/usr/bin/env python3
"""
Main CLI runner for washdb-bot.

This script orchestrates the complete workflow:
- Discovering businesses from Yellow Pages
- Scraping individual business websites
- Updating database with findings
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from db import upsert_discovered, update_batch
from runner.logging_setup import get_logger
from scrape_yp import crawl_all_states, CATEGORIES, STATES


# Initialize logger
logger = get_logger("main")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="washdb-bot: Discover and scrape business information",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover businesses from Yellow Pages only
  python runner/main.py --discover-only

  # Scrape existing businesses' websites only
  python runner/main.py --scrape-only

  # Run both discovery and scraping
  python runner/main.py --auto

  # Custom categories and states
  python runner/main.py --auto --categories "pressure washing,window cleaning" --states "TX,CA"

  # Update only businesses missing email
  python runner/main.py --scrape-only --only-missing-email --update-limit 100
        """,
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--discover-only",
        action="store_true",
        help="Only discover businesses from Yellow Pages",
    )
    mode_group.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only scrape existing businesses' websites",
    )
    mode_group.add_argument(
        "--auto",
        action="store_true",
        help="Run both discovery and scraping",
    )

    # Discovery options
    discovery_group = parser.add_argument_group("Discovery Options")
    discovery_group.add_argument(
        "--categories",
        type=str,
        help=f"Comma-separated categories (default: all {len(CATEGORIES)} categories)",
    )
    discovery_group.add_argument(
        "--states",
        type=str,
        help=f"Comma-separated state codes (default: all {len(STATES)} states)",
    )
    discovery_group.add_argument(
        "--pages-per-pair",
        type=int,
        default=3,
        help="Search depth: number of result pages per category-state combination (default: 3, max: 50)",
    )

    # Scraping options
    scrape_group = parser.add_argument_group("Scraping Options")
    scrape_group.add_argument(
        "--update-limit",
        type=int,
        default=100,
        help="Maximum number of companies to update (default: 100)",
    )
    scrape_group.add_argument(
        "--stale-days",
        type=int,
        default=30,
        help="Consider companies stale after N days (default: 30)",
    )
    scrape_group.add_argument(
        "--only-missing-email",
        action="store_true",
        help="Only update companies missing email addresses",
    )

    return parser.parse_args()


def run_discovery(args):
    """
    Run Yellow Pages discovery workflow.

    Args:
        args: Parsed command-line arguments

    Returns:
        Tuple of (total_discovered, total_inserted, total_updated)
    """
    logger.info("=" * 70)
    logger.info("DISCOVERY MODE: Crawling Yellow Pages")
    logger.info("=" * 70)

    # Parse categories
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",")]
        logger.info(f"Using custom categories: {categories}")
    else:
        categories = CATEGORIES
        logger.info(f"Using all {len(categories)} default categories")

    # Parse states
    if args.states:
        states = [s.strip().upper() for s in args.states.split(",")]
        logger.info(f"Using custom states: {states}")
    else:
        states = STATES
        logger.info(f"Using all {len(states)} states")

    logger.info(f"Search depth (pages per category-state): {args.pages_per_pair}")
    logger.info("")

    # Prepare CSV output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = Path("data") / f"new_urls_{timestamp}.csv"
    csv_path.parent.mkdir(exist_ok=True)

    total_discovered = 0
    total_inserted = 0
    total_updated = 0
    total_skipped = 0

    # Open CSV file for writing new URLs
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(
            ["timestamp", "category", "state", "name", "website", "domain", "phone"]
        )

        # Crawl all state-category combinations
        for batch in crawl_all_states(
            categories=categories,
            states=states,
            limit_per_state=args.pages_per_pair,
        ):
            category = batch["category"]
            state = batch["state"]
            results = batch["results"]
            count = batch["count"]

            logger.info(f"Processing batch: {category} in {state} - {count} results")

            if count == 0:
                logger.info("  No results in batch, skipping")
                continue

            try:
                # Upsert to database
                inserted, skipped, updated = upsert_discovered(results)

                total_discovered += count
                total_inserted += inserted
                total_updated += updated
                total_skipped += skipped

                logger.info(
                    f"  Database: {inserted} inserted, {updated} updated, {skipped} skipped"
                )

                # Write new URLs to CSV (only inserted ones)
                for result in results:
                    if result.get("website"):
                        csv_writer.writerow(
                            [
                                datetime.now().isoformat(),
                                category,
                                state,
                                result.get("name", ""),
                                result.get("website", ""),
                                result.get("domain", ""),
                                result.get("phone", ""),
                            ]
                        )

            except Exception as e:
                logger.error(f"Error processing batch: {e}", exc_info=True)
                continue

    logger.info("")
    logger.info("=" * 70)
    logger.info("DISCOVERY SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total discovered:     {total_discovered}")
    logger.info(f"Total inserted:       {total_inserted}")
    logger.info(f"Total updated:        {total_updated}")
    logger.info(f"Total skipped:        {total_skipped}")
    logger.info(f"New URLs CSV:         {csv_path}")
    logger.info("=" * 70)

    return (total_discovered, total_inserted, total_updated)


def run_scraping(args):
    """
    Run website scraping/update workflow.

    Args:
        args: Parsed command-line arguments

    Returns:
        Dict with update summary
    """
    logger.info("=" * 70)
    logger.info("SCRAPING MODE: Updating company details from websites")
    logger.info("=" * 70)
    logger.info(f"Update limit:         {args.update_limit}")
    logger.info(f"Stale days:           {args.stale_days}")
    logger.info(f"Only missing email:   {args.only_missing_email}")
    logger.info("")

    try:
        summary = update_batch(
            limit=args.update_limit,
            stale_days=args.stale_days,
            only_missing_email=args.only_missing_email,
        )

        logger.info("")
        logger.info("=" * 70)
        logger.info("SCRAPING SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total processed:      {summary['total_processed']}")
        logger.info(f"Successfully updated: {summary['updated']}")
        logger.info(f"Skipped (no changes): {summary['skipped']}")
        logger.info(f"Errors:               {summary['errors']}")

        if summary["fields_updated"]:
            logger.info("")
            logger.info("Fields updated:")
            for field, count in sorted(summary["fields_updated"].items()):
                logger.info(f"  {field:20s}: {count}")

        logger.info("=" * 70)

        return summary

    except Exception as e:
        logger.error(f"Scraping workflow failed: {e}", exc_info=True)
        return {
            "total_processed": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 1,
            "fields_updated": {},
        }


def main():
    """Main entry point."""
    args = parse_args()

    logger.info("=" * 70)
    logger.info("washdb-bot - Business Discovery and Scraping Tool")
    logger.info("=" * 70)
    logger.info("")

    exit_code = 0
    discovery_stats = None
    scraping_stats = None

    try:
        # Run discovery if requested
        if args.discover_only or args.auto:
            discovery_stats = run_discovery(args)
            logger.info("")

        # Run scraping if requested
        if args.scrape_only or args.auto:
            scraping_stats = run_scraping(args)
            logger.info("")

        # Final summary
        logger.info("=" * 70)
        logger.info("OVERALL SUMMARY")
        logger.info("=" * 70)

        if discovery_stats:
            total_discovered, total_inserted, total_updated = discovery_stats
            logger.info(f"Discovery: {total_discovered} found, {total_inserted} new, {total_updated} updated")

        if scraping_stats:
            logger.info(
                f"Scraping:  {scraping_stats['updated']} enriched, "
                f"{scraping_stats['errors']} errors"
            )

        logger.info("")
        logger.info("✓ Run completed successfully")
        logger.info("=" * 70)

    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("Interrupted by user (Ctrl+C)")
        exit_code = 130

    except Exception as e:
        logger.error("")
        logger.error("=" * 70)
        logger.error("FATAL ERROR")
        logger.error("=" * 70)
        logger.error(f"{e}", exc_info=True)
        logger.error("=" * 70)
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
