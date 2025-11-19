"""
City slug normalization for Yellow Pages URLs.

This module generates YP-compatible city-state slugs from city names.

Example URLs:
- https://www.yellowpages.com/los-angeles-ca/window-cleaning
- https://www.yellowpages.com/saint-louis-mo/pressure-washing
- https://www.yellowpages.com/fort-worth-tx/gutter-cleaning
"""

import re
from typing import Dict


# Common abbreviations at the start of city names
CITY_ABBREVIATIONS: Dict[str, str] = {
    "st": "saint",
    "st.": "saint",
    "ft": "fort",
    "ft.": "fort",
    "mt": "mount",
    "mt.": "mount",
}


def generate_city_slug(city: str, state_id: str) -> str:
    """
    Generate a YP-compatible city-state slug.

    Rules:
    1. Convert to lowercase
    2. Remove periods
    3. Normalize common abbreviations at the start (St. → saint, Ft. → fort, Mt. → mount)
    4. Replace spaces and punctuation with hyphens
    5. Collapse multiple hyphens to one
    6. Remove leading/trailing hyphens
    7. Append -{state_id} in lowercase

    Args:
        city: City name (e.g., "Los Angeles", "St. Louis", "Fort Worth")
        state_id: 2-letter state code (e.g., "CA", "MO", "TX")

    Returns:
        YP-compatible slug (e.g., "los-angeles-ca", "saint-louis-mo", "fort-worth-tx")

    Examples:
        >>> generate_city_slug("Los Angeles", "CA")
        'los-angeles-ca'
        >>> generate_city_slug("St. Louis", "MO")
        'saint-louis-mo'
        >>> generate_city_slug("Fort Worth", "TX")
        'fort-worth-tx'
        >>> generate_city_slug("O'Fallon", "IL")
        'o-fallon-il'
        >>> generate_city_slug("Winston-Salem", "NC")
        'winston-salem-nc'
    """
    # Step 1: Convert to lowercase
    slug = city.lower().strip()

    # Step 2: Remove periods
    slug = slug.replace(".", "")

    # Step 3: Normalize abbreviations at the start of the name
    parts = slug.split()
    if parts and parts[0] in CITY_ABBREVIATIONS:
        parts[0] = CITY_ABBREVIATIONS[parts[0]]
        slug = " ".join(parts)

    # Step 4: Replace spaces and punctuation with hyphens
    # Keep alphanumeric and hyphens, replace everything else with hyphen
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)

    # Step 5: Collapse multiple hyphens to one
    slug = re.sub(r"-+", "-", slug)

    # Step 6: Remove leading/trailing hyphens
    slug = slug.strip("-")

    # Step 7: Append state code in lowercase
    state_slug = state_id.lower().strip()
    full_slug = f"{slug}-{state_slug}"

    return full_slug


def generate_yp_geo(city: str, state_id: str) -> str:
    """
    Generate YP fallback search geo format: "City, ST"

    This format is used in YP search URLs as the geo_location_terms parameter.

    Args:
        city: City name
        state_id: 2-letter state code

    Returns:
        Geo string in format "City, ST"

    Examples:
        >>> generate_yp_geo("Los Angeles", "CA")
        'Los Angeles, CA'
        >>> generate_yp_geo("St. Louis", "MO")
        'St. Louis, MO'
    """
    return f"{city.strip()}, {state_id.upper().strip()}"


def calculate_population_tier(population: int, percentile_90: int, percentile_50: int) -> int:
    """
    Calculate population tier for page limit.

    Tiers:
    - Tier 1 (High): Top 10% by population → max_pages=20
    - Tier 2 (Medium): Next 40% → max_pages=15
    - Tier 3 (Low): Bottom 50% → max_pages=10

    Args:
        population: City population
        percentile_90: Population at 90th percentile (top 10% threshold)
        percentile_50: Population at 50th percentile (median)

    Returns:
        Tier number (1=high priority, 2=medium, 3=low)

    Examples:
        >>> calculate_population_tier(1000000, 100000, 10000)  # Large city
        1
        >>> calculate_population_tier(50000, 100000, 10000)    # Medium city
        2
        >>> calculate_population_tier(5000, 100000, 10000)     # Small city
        3
    """
    if population >= percentile_90:
        return 1  # Top 10% - high priority
    elif population >= percentile_50:
        return 2  # Next 40% - medium priority
    else:
        return 3  # Bottom 50% - low priority


def tier_to_max_pages(tier: int) -> int:
    """
    Convert tier number to max_pages for scraping.

    Args:
        tier: Tier number (1-3)

    Returns:
        Maximum pages to scrape

    Examples:
        >>> tier_to_max_pages(1)
        20
        >>> tier_to_max_pages(2)
        15
        >>> tier_to_max_pages(3)
        10
    """
    tier_pages = {
        1: 20,  # High priority - 20 pages (2000 results max)
        2: 15,  # Medium priority - 15 pages (1500 results max)
        3: 10,  # Low priority - 10 pages (1000 results max)
    }
    return tier_pages.get(tier, 10)  # Default to 10 pages if unknown tier


# Test the functions if run directly
if __name__ == "__main__":
    import doctest
    doctest.testmod()

    # Additional manual tests
    test_cases = [
        ("Los Angeles", "CA", "los-angeles-ca"),
        ("St. Louis", "MO", "saint-louis-mo"),
        ("Fort Worth", "TX", "fort-worth-tx"),
        ("Mt. Vernon", "NY", "mount-vernon-ny"),
        ("O'Fallon", "IL", "o-fallon-il"),
        ("Winston-Salem", "NC", "winston-salem-nc"),
        ("New York", "NY", "new-york-ny"),
        ("Washington", "DC", "washington-dc"),
    ]

    print("City Slug Tests:")
    print("-" * 60)
    for city, state, expected in test_cases:
        result = generate_city_slug(city, state)
        status = "✓" if result == expected else "✗"
        print(f"{status} {city:20s} {state:3s} → {result:30s} (expected: {expected})")

    print("\n" + "=" * 60)
    print("YP Geo Tests:")
    print("-" * 60)
    for city, state, _ in test_cases[:3]:
        result = generate_yp_geo(city, state)
        print(f"{city:20s} {state:3s} → {result}")
