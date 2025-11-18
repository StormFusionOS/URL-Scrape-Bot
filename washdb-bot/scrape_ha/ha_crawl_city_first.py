#!/usr/bin/env python3
"""
HomeAdvisor city-first crawling (Phase 1 of pipeline - saves to staging).

This module implements city-first scraping for HomeAdvisor:
- Crawls major cities instead of entire states
- Reduces redundancy and improves targeting
- Saves discoveries to ha_staging table for Phase 2 processing
"""
from __future__ import annotations
from typing import Generator
from runner.logging_setup import get_logger
from db.save_to_staging import save_to_staging
from scrape_ha.ha_client import build_search_url, fetch_url, parse_list_page

logger = get_logger("ha_crawl_city_first")

CATEGORIES_HA = [
    "power washing",
    "window cleaning services",
    "deck staining or painting",
    "fence painting or staining",
]

# Major US cities by state - targeting population centers
MAJOR_CITIES = {
    "AL": ["Birmingham", "Montgomery", "Mobile", "Huntsville"],
    "AK": ["Anchorage", "Fairbanks", "Juneau"],
    "AZ": ["Phoenix", "Tucson", "Mesa", "Chandler", "Scottsdale"],
    "AR": ["Little Rock", "Fort Smith", "Fayetteville"],
    "CA": ["Los Angeles", "San Diego", "San Jose", "San Francisco", "Fresno",
           "Sacramento", "Long Beach", "Oakland", "Bakersfield", "Anaheim"],
    "CO": ["Denver", "Colorado Springs", "Aurora", "Fort Collins"],
    "CT": ["Bridgeport", "New Haven", "Hartford", "Stamford"],
    "DE": ["Wilmington", "Dover", "Newark"],
    "FL": ["Jacksonville", "Miami", "Tampa", "Orlando", "St. Petersburg",
           "Hialeah", "Tallahassee", "Fort Lauderdale", "Port St. Lucie"],
    "GA": ["Atlanta", "Augusta", "Columbus", "Savannah", "Athens"],
    "HI": ["Honolulu", "Pearl City", "Hilo"],
    "ID": ["Boise", "Meridian", "Nampa"],
    "IL": ["Chicago", "Aurora", "Naperville", "Joliet", "Rockford"],
    "IN": ["Indianapolis", "Fort Wayne", "Evansville", "South Bend"],
    "IA": ["Des Moines", "Cedar Rapids", "Davenport"],
    "KS": ["Wichita", "Overland Park", "Kansas City", "Topeka"],
    "KY": ["Louisville", "Lexington", "Bowling Green"],
    "LA": ["New Orleans", "Baton Rouge", "Shreveport", "Lafayette"],
    "ME": ["Portland", "Lewiston", "Bangor"],
    "MD": ["Baltimore", "Columbia", "Germantown", "Silver Spring"],
    "MA": ["Boston", "Worcester", "Springfield", "Cambridge", "Lowell"],
    "MI": ["Detroit", "Grand Rapids", "Warren", "Sterling Heights", "Ann Arbor"],
    "MN": ["Minneapolis", "St. Paul", "Rochester", "Duluth"],
    "MS": ["Jackson", "Gulfport", "Southaven", "Hattiesburg"],
    "MO": ["Kansas City", "St. Louis", "Springfield", "Columbia"],
    "MT": ["Billings", "Missoula", "Great Falls"],
    "NE": ["Omaha", "Lincoln", "Bellevue"],
    "NV": ["Las Vegas", "Henderson", "Reno", "North Las Vegas"],
    "NH": ["Manchester", "Nashua", "Concord"],
    "NJ": ["Newark", "Jersey City", "Paterson", "Elizabeth", "Edison"],
    "NM": ["Albuquerque", "Las Cruces", "Rio Rancho"],
    "NY": ["New York", "Buffalo", "Rochester", "Yonkers", "Syracuse"],
    "NC": ["Charlotte", "Raleigh", "Greensboro", "Durham", "Winston-Salem"],
    "ND": ["Fargo", "Bismarck", "Grand Forks"],
    "OH": ["Columbus", "Cleveland", "Cincinnati", "Toledo", "Akron"],
    "OK": ["Oklahoma City", "Tulsa", "Norman"],
    "OR": ["Portland", "Salem", "Eugene", "Gresham"],
    "PA": ["Philadelphia", "Pittsburgh", "Allentown", "Erie", "Reading"],
    "RI": ["Providence", "Warwick", "Cranston"],
    "SC": ["Columbia", "Charleston", "North Charleston", "Mount Pleasant"],
    "SD": ["Sioux Falls", "Rapid City", "Aberdeen"],
    "TN": ["Nashville", "Memphis", "Knoxville", "Chattanooga"],
    "TX": ["Houston", "San Antonio", "Dallas", "Austin", "Fort Worth",
           "El Paso", "Arlington", "Corpus Christi", "Plano", "Laredo"],
    "UT": ["Salt Lake City", "West Valley City", "Provo", "West Jordan"],
    "VT": ["Burlington", "South Burlington", "Rutland"],
    "VA": ["Virginia Beach", "Norfolk", "Chesapeake", "Richmond", "Newport News"],
    "WA": ["Seattle", "Spokane", "Tacoma", "Vancouver", "Bellevue"],
    "WV": ["Charleston", "Huntington", "Morgantown"],
    "WI": ["Milwaukee", "Madison", "Green Bay", "Kenosha"],
    "WY": ["Cheyenne", "Casper", "Laramie"],
}


def crawl_category_city(category: str, city: str, state: str, max_pages: int = 3) -> list[dict]:
    """
    Crawl HomeAdvisor for a specific category in a specific city.

    Args:
        category: Service category (e.g., "power washing")
        city: City name (e.g., "Birmingham")
        state: State code (e.g., "AL")
        max_pages: Maximum number of pages to crawl

    Returns:
        List of business dicts ready for staging table
    """
    location = f"{city}, {state}"
    logger.info(f"[HA City-First] Crawl: '{category}' in {location} (max {max_pages} pages)")
    results: list[dict] = []
    seen_profile_urls = set()

    for page in range(1, max_pages + 1):
        search_url = build_search_url(category, state, page, city=city)
        html = fetch_url(search_url)

        if not html:
            logger.info(f"[HA City-First] No HTML for {search_url}, stopping")
            break

        cards = parse_list_page(html)
        if not cards:
            logger.info(f"[HA City-First] No cards on page {page}, stopping")
            break

        new_this_page = 0
        for card in cards:
            profile_url = card.get("profile_url")
            if not profile_url:
                logger.debug(f"[HA City-First] Skip (no profile URL): {card.get('name')}")
                continue

            # Skip duplicates
            if profile_url in seen_profile_urls:
                logger.debug(f"[HA City-First] Duplicate profile URL: {profile_url}")
                continue

            seen_profile_urls.add(profile_url)

            # Prepare data for staging table
            results.append({
                "name": card.get("name"),
                "phone": card.get("phone"),
                "address": card.get("address"),
                "profile_url": profile_url,
                "rating_ha": (float(card.get("rating_ha")) if card.get("rating_ha") else None),
                "reviews_ha": (int(card.get("reviews_ha")) if card.get("reviews_ha") else None),
            })
            new_this_page += 1

        logger.info(f"[HA City-First] Page {page}: extracted {new_this_page}/{len(cards)} businesses")
        if new_this_page == 0:
            break

    logger.info(f"[HA City-First] Total extracted for {category}/{location}: {len(results)} businesses")
    return results


def crawl_cities(
    categories: list[str] = None,
    states: list[str] = None,
    max_pages_per_city: int = 3,
    save_to_db: bool = True
) -> Generator[dict, None, None]:
    """
    Crawl HomeAdvisor using city-first approach.

    This generator yields batches of businesses discovered from city-category combinations.
    Each batch is saved to ha_staging table for Phase 2 processing.

    Args:
        categories: List of service categories (defaults to CATEGORIES_HA)
        states: List of state codes to crawl (defaults to all states in MAJOR_CITIES)
        max_pages_per_city: Number of pages to scrape per city-category pair
        save_to_db: If True, save to staging table; if False, just return results

    Yields:
        Dict batches with keys: category, city, state, results, count, error (optional)
    """
    if categories is None:
        categories = CATEGORIES_HA

    if states is None:
        states = list(MAJOR_CITIES.keys())

    # Filter to only requested states
    target_cities = {
        state: cities
        for state, cities in MAJOR_CITIES.items()
        if state in states
    }

    # Calculate total combinations
    total_combinations = sum(
        len(cities) * len(categories)
        for cities in target_cities.values()
    )

    i = 0
    for state, cities in target_cities.items():
        for city in cities:
            for category in categories:
                i += 1
                logger.info(
                    f"[HA City-First] ({i}/{total_combinations}) "
                    f"{category} in {city}, {state}"
                )

                try:
                    results = crawl_category_city(
                        category, city, state, max_pages=max_pages_per_city
                    )

                    if save_to_db and results:
                        # Save batch to staging table
                        inserted, skipped = save_to_staging(results)
                        logger.info(
                            f"[HA City-First] Saved batch: {category}/{city}/{state}, "
                            f"{inserted} new, {skipped} duplicates"
                        )

                    # Yield batch
                    yield {
                        "category": category,
                        "city": city,
                        "state": state,
                        "results": results,
                        "count": len(results),
                    }

                except Exception as e:
                    logger.error(
                        f"[HA City-First] Error for {category}/{city}/{state}: {e}",
                        exc_info=True
                    )
                    # Yield error batch
                    yield {
                        "category": category,
                        "city": city,
                        "state": state,
                        "error": str(e),
                        "results": [],
                        "count": 0,
                    }


def main():
    """CLI entry point for city-first crawler."""
    import argparse

    parser = argparse.ArgumentParser(description="HomeAdvisor City-First Crawler (Phase 1)")
    parser.add_argument(
        "--states",
        nargs="+",
        help="State codes to crawl (e.g., AL TX CA). Defaults to all states."
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        help="Categories to crawl. Defaults to all HA categories."
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Max pages per city-category pair (default: 3)"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("HomeAdvisor City-First Crawler Starting (Phase 1)")
    logger.info(f"States: {args.states or 'ALL'}")
    logger.info(f"Categories: {args.categories or 'ALL'}")
    logger.info(f"Max pages per city: {args.pages}")
    logger.info("=" * 60)

    total_discovered = 0
    total_batches = 0

    for batch in crawl_cities(
        categories=args.categories,
        states=args.states,
        max_pages_per_city=args.pages
    ):
        total_batches += 1
        total_discovered += batch["count"]

        if "error" in batch:
            logger.warning(
                f"Batch {total_batches}: {batch['category']}/{batch['city']}/{batch['state']} "
                f"FAILED - {batch['error']}"
            )
        else:
            logger.info(
                f"Batch {total_batches}: {batch['category']}/{batch['city']}/{batch['state']} "
                f"discovered {batch['count']} businesses"
            )

    logger.info("=" * 60)
    logger.info("Crawl Complete")
    logger.info(f"Total batches: {total_batches}")
    logger.info(f"Total businesses discovered: {total_discovered}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
