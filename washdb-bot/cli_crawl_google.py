#!/usr/bin/env python3
"""
CLI wrapper for Google Maps scraper - runs as standalone subprocess.
Can be killed instantly via SIGKILL.
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from scrape_google.google_scraper import GoogleMapsScraper
from db.save_discoveries import upsert_discovered


def main():
    parser = argparse.ArgumentParser(description='Run Google Maps scraper')
    parser.add_argument('--query', required=True, help='Search query')
    parser.add_argument('--location', required=True, help='Location to search')
    parser.add_argument('--max-results', type=int, default=10, help='Maximum results to fetch')
    parser.add_argument('--scrape-details', action='store_true', default=True, help='Scrape full business details')

    args = parser.parse_args()

    print(f"Starting Google Maps Scraper")
    print(f"Query: {args.query}")
    print(f"Location: {args.location}")
    print(f"Max Results: {args.max_results}")
    print(f"Scrape Details: {args.scrape_details}")
    print("-" * 60)

    # Initialize scraper
    scraper = GoogleMapsScraper()

    try:
        # Run scraper
        results = scraper.scrape(
            query=args.query,
            location=args.location,
            max_results=args.max_results,
            scrape_details=args.scrape_details
        )

        # Save to database
        if results:
            print(f"\nSaving {len(results)} results to database...")
            inserted, skipped, updated = upsert_discovered(results)

            print("-" * 60)
            print(f"Scrape Complete!")
            print(f"Total Found: {len(results)}")
            print(f"New: {inserted}")
            print(f"Updated: {updated}")
            print(f"Duplicates Skipped: {skipped}")
        else:
            print("No results found")

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Clean up
        scraper.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
