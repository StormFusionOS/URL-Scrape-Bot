#!/usr/bin/env python3
"""
CLI wrapper for Yellow Pages crawler - runs as standalone subprocess.
Can be killed instantly via SIGKILL.
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from scrape_yp.yp_crawl import crawl_all_states
from db.save_discoveries import upsert_discovered


def main():
    parser = argparse.ArgumentParser(description='Run Yellow Pages crawler')
    parser.add_argument('--categories', required=True, help='Comma-separated categories')
    parser.add_argument('--states', required=True, help='Comma-separated state codes')
    parser.add_argument('--pages', type=int, default=1, help='Pages per category-state pair')

    args = parser.parse_args()

    # Parse arguments
    categories = [c.strip() for c in args.categories.split(',')]
    states = [s.strip() for s in args.states.split(',')]

    print(f"Starting YP Crawler")
    print(f"Categories: {categories}")
    print(f"States: {states}")
    print(f"Pages per pair: {args.pages}")
    print("-" * 60)

    # Run crawler
    total_found = 0
    total_new = 0
    total_updated = 0

    for batch in crawl_all_states(categories, states, args.pages):
        # Check for error
        if batch.get('error'):
            print(f"ERROR: {batch['error']}", file=sys.stderr)
            continue

        # Get results
        results = batch.get('results', [])
        if not results:
            continue

        # Save to database
        inserted, skipped, updated = upsert_discovered(results)

        total_found += len(results)
        total_new += inserted
        total_updated += updated

        # Print progress
        category = batch.get('category', '')
        state = batch.get('state', '')
        print(f"✓ {category} × {state}: Found {len(results)}, New {inserted}, Updated {updated}")

    print("-" * 60)
    print(f"Crawl Complete!")
    print(f"Total Found: {total_found}")
    print(f"Total New: {total_new}")
    print(f"Total Updated: {total_updated}")

    return 0


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
