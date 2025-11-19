#!/usr/bin/env python3
"""
Generate YP crawl targets from categories and query terms.

This module:
- Loads categories from the allowlist
- Expands to state and city-level search URLs
- Generates query-based search URLs
- Outputs: yp_city_pages.json and yp_targets.ndjson
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Set
from urllib.parse import quote_plus


# Common US states
STATES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
]

# Major cities per state (top 3-5 cities for coverage)
MAJOR_CITIES = {
    'AL': ['Birmingham', 'Montgomery', 'Mobile', 'Huntsville'],
    'AK': ['Anchorage', 'Fairbanks', 'Juneau'],
    'AZ': ['Phoenix', 'Tucson', 'Mesa', 'Chandler', 'Scottsdale'],
    'AR': ['Little Rock', 'Fort Smith', 'Fayetteville', 'Springdale'],
    'CA': ['Los Angeles', 'San Diego', 'San Jose', 'San Francisco', 'Fresno', 'Sacramento', 'Long Beach', 'Oakland'],
    'CO': ['Denver', 'Colorado Springs', 'Aurora', 'Fort Collins'],
    'CT': ['Bridgeport', 'New Haven', 'Hartford', 'Stamford'],
    'DE': ['Wilmington', 'Dover', 'Newark'],
    'FL': ['Jacksonville', 'Miami', 'Tampa', 'Orlando', 'St Petersburg', 'Fort Lauderdale'],
    'GA': ['Atlanta', 'Columbus', 'Augusta', 'Savannah', 'Athens'],
    'HI': ['Honolulu', 'Pearl City', 'Hilo'],
    'ID': ['Boise', 'Meridian', 'Nampa', 'Idaho Falls'],
    'IL': ['Chicago', 'Aurora', 'Naperville', 'Joliet', 'Rockford'],
    'IN': ['Indianapolis', 'Fort Wayne', 'Evansville', 'South Bend'],
    'IA': ['Des Moines', 'Cedar Rapids', 'Davenport', 'Sioux City'],
    'KS': ['Wichita', 'Overland Park', 'Kansas City', 'Topeka'],
    'KY': ['Louisville', 'Lexington', 'Bowling Green', 'Owensboro'],
    'LA': ['New Orleans', 'Baton Rouge', 'Shreveport', 'Lafayette'],
    'ME': ['Portland', 'Lewiston', 'Bangor'],
    'MD': ['Baltimore', 'Columbia', 'Germantown', 'Silver Spring'],
    'MA': ['Boston', 'Worcester', 'Springfield', 'Cambridge', 'Lowell'],
    'MI': ['Detroit', 'Grand Rapids', 'Warren', 'Sterling Heights', 'Ann Arbor'],
    'MN': ['Minneapolis', 'St Paul', 'Rochester', 'Duluth'],
    'MS': ['Jackson', 'Gulfport', 'Southaven', 'Hattiesburg'],
    'MO': ['Kansas City', 'St Louis', 'Springfield', 'Columbia'],
    'MT': ['Billings', 'Missoula', 'Great Falls', 'Bozeman'],
    'NE': ['Omaha', 'Lincoln', 'Bellevue', 'Grand Island'],
    'NV': ['Las Vegas', 'Henderson', 'Reno', 'North Las Vegas'],
    'NH': ['Manchester', 'Nashua', 'Concord', 'Derry'],
    'NJ': ['Newark', 'Jersey City', 'Paterson', 'Elizabeth', 'Edison'],
    'NM': ['Albuquerque', 'Las Cruces', 'Rio Rancho', 'Santa Fe'],
    'NY': ['New York', 'Buffalo', 'Rochester', 'Yonkers', 'Syracuse', 'Albany'],
    'NC': ['Charlotte', 'Raleigh', 'Greensboro', 'Durham', 'Winston-Salem'],
    'ND': ['Fargo', 'Bismarck', 'Grand Forks', 'Minot'],
    'OH': ['Columbus', 'Cleveland', 'Cincinnati', 'Toledo', 'Akron'],
    'OK': ['Oklahoma City', 'Tulsa', 'Norman', 'Broken Arrow'],
    'OR': ['Portland', 'Eugene', 'Salem', 'Gresham', 'Hillsboro'],
    'PA': ['Philadelphia', 'Pittsburgh', 'Allentown', 'Erie', 'Reading'],
    'RI': ['Providence', 'Warwick', 'Cranston', 'Pawtucket'],
    'SC': ['Columbia', 'Charleston', 'North Charleston', 'Mount Pleasant'],
    'SD': ['Sioux Falls', 'Rapid City', 'Aberdeen', 'Brookings'],
    'TN': ['Nashville', 'Memphis', 'Knoxville', 'Chattanooga', 'Clarksville'],
    'TX': ['Houston', 'San Antonio', 'Dallas', 'Austin', 'Fort Worth', 'El Paso', 'Arlington', 'Corpus Christi'],
    'UT': ['Salt Lake City', 'West Valley City', 'Provo', 'West Jordan'],
    'VT': ['Burlington', 'Essex', 'South Burlington', 'Rutland'],
    'VA': ['Virginia Beach', 'Norfolk', 'Chesapeake', 'Richmond', 'Newport News'],
    'WA': ['Seattle', 'Spokane', 'Tacoma', 'Vancouver', 'Bellevue'],
    'WV': ['Charleston', 'Huntington', 'Morgantown', 'Parkersburg'],
    'WI': ['Milwaukee', 'Madison', 'Green Bay', 'Kenosha'],
    'WY': ['Cheyenne', 'Casper', 'Laramie', 'Gillette']
}


def load_allowlist(file_path: str) -> List[str]:
    """Load category allowlist from file."""
    path = Path(file_path)
    if not path.exists():
        print(f"Warning: {file_path} not found")
        return []

    with open(path, 'r', encoding='utf-8') as f:
        categories = [line.strip() for line in f if line.strip()]

    print(f"✓ Loaded {len(categories)} categories from allowlist")
    return categories


def load_query_terms(file_path: str) -> List[str]:
    """Load query terms from file."""
    path = Path(file_path)
    if not path.exists():
        print(f"Warning: {file_path} not found")
        return []

    with open(path, 'r', encoding='utf-8') as f:
        terms = [line.strip() for line in f if line.strip()]

    print(f"✓ Loaded {len(terms)} query terms")
    return terms


def generate_city_urls(
    categories: List[str],
    states: List[str] = None,
    cities_per_state: int = 5
) -> Dict[str, List[str]]:
    """
    Generate city-level search URLs for each category.

    Args:
        categories: List of category names
        states: List of state codes (default: all US states)
        cities_per_state: Max cities per state (default: 5)

    Returns:
        Dict mapping category to list of city search URLs
    """
    if states is None:
        states = STATES

    city_pages = {}

    for category in categories:
        urls = []

        for state in states:
            # Get cities for this state
            cities = MAJOR_CITIES.get(state, [])[:cities_per_state]

            for city in cities:
                # YP search URL format: search?search_terms=...&geo_location_terms=City,ST
                location = f"{city}, {state}"
                url = (
                    f"https://www.yellowpages.com/search?"
                    f"search_terms={quote_plus(category)}&"
                    f"geo_location_terms={quote_plus(location)}"
                )
                urls.append(url)

        city_pages[category] = urls
        print(f"  {category}: {len(urls)} city URLs")

    return city_pages


def generate_query_urls(
    query_terms: List[str],
    states: List[str] = None,
    cities_per_state: int = 5
) -> Dict[str, List[str]]:
    """
    Generate city-level search URLs for query terms (non-category searches).

    Args:
        query_terms: List of search terms
        states: List of state codes
        cities_per_state: Max cities per state

    Returns:
        Dict mapping query term to list of search URLs
    """
    if states is None:
        states = STATES

    query_pages = {}

    for term in query_terms:
        urls = []

        for state in states:
            cities = MAJOR_CITIES.get(state, [])[:cities_per_state]

            for city in cities:
                location = f"{city}, {state}"
                url = (
                    f"https://www.yellowpages.com/search?"
                    f"search_terms={quote_plus(term)}&"
                    f"geo_location_terms={quote_plus(location)}"
                )
                urls.append(url)

        query_pages[term] = urls
        print(f"  {term} (query): {len(urls)} city URLs")

    return query_pages


def write_targets_ndjson(
    city_pages: Dict[str, List[str]],
    output_file: str
) -> int:
    """
    Write targets to NDJSON format for crawling.

    Args:
        city_pages: Dict mapping category/term to list of URLs
        output_file: Output file path

    Returns:
        Number of targets written
    """
    path = Path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Deduplicate URLs
    seen_urls: Set[str] = set()
    count = 0

    with open(path, 'w', encoding='utf-8') as f:
        for category, urls in city_pages.items():
            for url in urls:
                if url not in seen_urls:
                    seen_urls.add(url)
                    record = {
                        'category': category,
                        'url': url
                    }
                    f.write(json.dumps(record) + '\n')
                    count += 1

    duplicate_count = sum(len(urls) for urls in city_pages.values()) - count
    dup_pct = (duplicate_count / (count + duplicate_count) * 100) if count > 0 else 0

    print(f"\n✓ Wrote {count} unique targets to {output_file}")
    print(f"  Duplicates removed: {duplicate_count} ({dup_pct:.1f}%)")

    return count


def seed_yp_targets(
    allowlist_file: str = 'data/yp_category_allowlist.txt',
    query_file: str = 'data/yp_query_terms.txt',
    states: List[str] = None,
    cities_per_state: int = 5,
    output_dir: str = 'data'
) -> Dict[str, any]:
    """
    Main seeding function - generate all YP crawl targets.

    Args:
        allowlist_file: Path to category allowlist
        query_file: Path to query terms
        states: List of state codes (default: all)
        cities_per_state: Max cities per state
        output_dir: Output directory

    Returns:
        Dict with statistics
    """
    print("=" * 70)
    print("Yellow Pages Target Seeder")
    print("=" * 70)
    print()

    # Load input files
    categories = load_allowlist(allowlist_file)
    query_terms = load_query_terms(query_file)

    if not categories and not query_terms:
        print("ERROR: No categories or query terms found")
        return {'error': 'No input data'}

    print()
    print("Generating city URLs...")
    print("-" * 70)

    # Generate URLs for categories
    city_pages = {}
    if categories:
        print("\nCategories:")
        category_pages = generate_city_urls(categories, states, cities_per_state)
        city_pages.update(category_pages)

    # Generate URLs for query terms
    if query_terms:
        print("\nQuery Terms:")
        query_pages = generate_query_urls(query_terms, states, cities_per_state)
        # Mark query terms with suffix
        query_pages_marked = {f"{k} (query)": v for k, v in query_pages.items()}
        city_pages.update(query_pages_marked)

    # Save city pages JSON
    city_pages_file = os.path.join(output_dir, 'yp_city_pages.json')
    with open(city_pages_file, 'w', encoding='utf-8') as f:
        json.dump(city_pages, f, indent=2)
    print(f"\n✓ Saved city pages to: {city_pages_file}")

    # Write targets NDJSON
    targets_file = os.path.join(output_dir, 'yp_targets.ndjson')
    target_count = write_targets_ndjson(city_pages, targets_file)

    # Statistics
    total_urls = sum(len(urls) for urls in city_pages.items())

    stats = {
        'categories': len(categories),
        'query_terms': len(query_terms),
        'total_search_types': len(city_pages),
        'unique_targets': target_count,
        'output_files': {
            'city_pages': city_pages_file,
            'targets': targets_file
        }
    }

    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Categories: {stats['categories']}")
    print(f"Query terms: {stats['query_terms']}")
    print(f"Total search types: {stats['total_search_types']}")
    print(f"Unique targets generated: {stats['unique_targets']}")
    print("=" * 70)

    return stats


if __name__ == '__main__':
    # Run seeder with defaults
    seed_yp_targets()
