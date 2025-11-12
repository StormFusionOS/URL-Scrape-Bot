#!/usr/bin/env python3
"""
Quick test to see what the YP parser is actually extracting.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from scrape_yp.yp_parser_enhanced import parse_yp_results_enhanced
from scrape_yp.yp_crawl_city_first import fetch_city_category_page

# Test URL for Providence, RI - Window Cleaning
test_url = "https://www.yellowpages.com/providence-ri/window-cleaning"

print("=" * 80)
print("Testing Yellow Pages Parser")
print("=" * 80)
print(f"URL: {test_url}")
print()

try:
    # Fetch the page
    print("Fetching page...")
    html = fetch_city_category_page(test_url, page=1, use_playwright=True)

    print(f"HTML length: {len(html)} characters")
    print()

    # Parse results
    print("Parsing results...")
    results = parse_yp_results_enhanced(html)

    print(f"Found {len(results)} listings")
    print()

    # Show first 3 results with details
    for i, result in enumerate(results[:3], 1):
        print(f"Listing {i}:")
        print(f"  Name: {result.get('name', 'N/A')}")
        print(f"  Phone: {result.get('phone', 'N/A')}")
        print(f"  Website: {result.get('website', 'N/A')}")
        print(f"  Category Tags: {result.get('category_tags', [])}")
        print(f"  Address: {result.get('address', 'N/A')}")
        print()

    # Summary
    print("=" * 80)
    print("Summary:")
    print(f"  Total listings: {len(results)}")
    print(f"  Listings with category tags: {sum(1 for r in results if r.get('category_tags'))}")
    print(f"  Listings with website: {sum(1 for r in results if r.get('website'))}")
    print()

    # Show all unique category tags found
    all_tags = set()
    for result in results:
        all_tags.update(result.get('category_tags', []))

    print(f"  Unique category tags found: {len(all_tags)}")
    if all_tags:
        print("  Tags:")
        for tag in sorted(all_tags):
            print(f"    - {tag}")
    else:
        print("  ⚠️  NO CATEGORY TAGS EXTRACTED!")
    print("=" * 80)

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
