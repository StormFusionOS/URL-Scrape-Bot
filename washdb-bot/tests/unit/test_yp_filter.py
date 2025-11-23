#!/usr/bin/env python3
"""
Test the YP filter with real parsed data.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from scrape_yp.yp_filter import YPFilter

# Initialize filter
yp_filter = YPFilter()

print("=" * 80)
print("Testing YP Filter")
print("=" * 80)
print()

print("Allowlist categories:", len(yp_filter.allowlist))
for cat in list(yp_filter.allowlist)[:5]:
    print(f"  - '{cat}'")
print()

print("Blocklist categories:", len(yp_filter.blocklist))
for cat in list(yp_filter.blocklist)[:5]:
    print(f"  - '{cat}'")
print()

# Test with real data from the parser test
test_listings = [
    {
        "name": "Lem's-Warwick Window Cleaning",
        "phone": "(401) 942-9451",
        "category_tags": ["Window Cleaning", "House Cleaning"],
        "description": "",
        "services": ""
    },
    {
        "name": "Nu-Way Window Cleaning",
        "phone": "(401) 861-0919",
        "category_tags": ["Window Cleaning"],
        "description": "",
        "services": ""
    },
    {
        "name": "AAA Window Cleaning Supplies",  # Should be rejected (has "Supplies" anti-keyword)
        "phone": "(401) 123-4567",
        "category_tags": ["Window Cleaning", "Pressure Washing Equipment & Services"],
        "description": "",
        "services": ""
    },
]

print("Testing listings:")
print()

for i, listing in enumerate(test_listings, 1):
    print(f"Listing {i}: {listing['name']}")
    print(f"  Tags: {listing['category_tags']}")

    should_include, reason, score = yp_filter.should_include(listing)

    print(f"  Result: {'✅ ACCEPTED' if should_include else '❌ REJECTED'}")
    print(f"  Reason: {reason}")
    print(f"  Score: {score:.1f}")
    print()

# Test filter_listings method (what the crawler actually calls)
print("=" * 80)
print("Testing filter_listings method (what crawler uses):")
print()

filtered_results, filter_stats = yp_filter.filter_listings(
    test_listings,
    min_score=50.0,
    include_sponsored=False
)

print(f"Input: {len(test_listings)} listings")
print(f"Accepted: {filter_stats['accepted']} listings")
print(f"Rejected: {filter_stats['rejected']} listings")
print()

if filtered_results:
    print("Accepted listings:")
    for result in filtered_results:
        print(f"  - {result['name']} (score: {result.get('confidence_score', 0):.1f})")
else:
    print("⚠️  NO LISTINGS ACCEPTED!")
print()
print("=" * 80)
