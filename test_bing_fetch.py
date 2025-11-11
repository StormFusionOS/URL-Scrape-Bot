#!/usr/bin/env python3
"""
Quick test script to diagnose Bing fetching issues.
"""

import sys
from scrape_bing.bing_client import fetch_bing_search_page, parse_bing_results, build_bing_query
from scrape_bing.bing_config import USE_API, BING_API_KEY

# Test query
category = "pressure washing"
location = "AL"
page = 1

print("=" * 70)
print("BING FETCH TEST")
print("=" * 70)
print(f"Category: {category}")
print(f"Location: {location}")
print(f"Page: {page}")
print(f"Mode: {'API' if USE_API else 'HTML'}")
if USE_API:
    print(f"API Key present: {bool(BING_API_KEY)}")
print("=" * 70)
print()

# Build query
query = build_bing_query(category, location, page)
print(f"Query: {query}")
print()

# Fetch page
print("Fetching...")
try:
    payload = fetch_bing_search_page(query, page=page)
    print(f"Fetch successful!")

    # Determine mode from payload type
    if isinstance(payload, str):
        mode = 'html'
        print(f"Mode: HTML")
        print(f"HTML length: {len(payload)} bytes")
        print()
        print("First 1000 characters of HTML:")
        print("-" * 70)
        print(payload[:1000])
        print("-" * 70)
        print()

        # Save full HTML for inspection
        with open('/opt/ai-seo/state/url-scrape-bot/bing_test.html', 'w') as f:
            f.write(payload)
        print("Full HTML saved to: /opt/ai-seo/state/url-scrape-bot/bing_test.html")
    else:
        mode = 'api'
        print(f"Mode: API")
        print(f"JSON payload: {payload}")

    print()
    print("Parsing results...")
    results = parse_bing_results(payload, mode=mode)
    print(f"Found {len(results)} results")

    if results:
        print()
        print("First result:")
        print("-" * 70)
        for key, value in results[0].items():
            print(f"  {key}: {value}")
        print("-" * 70)
    else:
        print("No results parsed!")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 70)
print("TEST COMPLETE")
print("=" * 70)
