#!/usr/bin/env python3
"""
HomeAdvisor ZIP code-based crawling (Phase 1 of pipeline - saves to staging).

This module implements ZIP code-based scraping for HomeAdvisor:
- Crawls using ZIP codes from city_registry database
- Prioritizes by population tier (A/B/C)
- Reduces redundancy and improves targeting
- Saves discoveries to ha_staging table for Phase 2 processing
"""
from __future__ import annotations
from typing import Generator
import psycopg2
from runner.logging_setup import get_logger
from db.save_to_staging import save_to_staging
from scrape_ha.ha_client import build_search_url, fetch_url, parse_list_page

logger = get_logger("ha_crawl")

# Database connection
DB_USER = "scraper_user"
DB_PASSWORD = "ScraperPass123"
DB_HOST = "localhost"
DB_NAME = "scraper"

CATEGORIES_HA = [
    "power washing",
    "window cleaning services",
    "deck staining or painting",
    "fence painting or staining",
]

# Pages to crawl per tier (based on population)
TIER_PAGES = {
    'A': 3,  # Major cities (100k+): 3 pages
    'B': 2,  # Medium cities (25k-100k): 2 pages
    'C': 1,  # Small cities (<25k): 1 page
}


def get_cities_from_db(states: list[str] = None, tiers: list[str] = None, limit: int = None):
    """
    Fetch cities from city_registry database.

    Args:
        states: List of state codes to filter (e.g., ['AL', 'TX'])
        tiers: List of tiers to filter (e.g., ['A', 'B'])
        limit: Maximum number of cities to return

    Returns:
        List of dicts with keys: city, state_id, primary_zip, tier
    """
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

    try:
        cur = conn.cursor()

        # Build query with filters
        query = """
            SELECT city, state_id, primary_zip, tier, population
            FROM city_registry
            WHERE 1=1
        """
        params = []

        if states:
            query += " AND state_id = ANY(%s)"
            params.append(states)

        if tiers:
            query += " AND tier = ANY(%s)"
            params.append(tiers)

        # Order by tier (A first), then population descending
        query += " ORDER BY tier ASC, population DESC NULLS LAST"

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        cur.execute(query, params)

        cities = []
        for row in cur.fetchall():
            cities.append({
                'city': row[0],
                'state_id': row[1],
                'primary_zip': row[2],
                'tier': row[3],
                'population': row[4],
            })

        cur.close()
        return cities

    finally:
        conn.close()


def crawl_category_zip(category: str, zip_code: str, city: str, state: str, max_pages: int = 3) -> list[dict]:
    """
    Crawl HomeAdvisor for a specific category in a specific ZIP code.

    Args:
        category: Service category (e.g., "power washing")
        zip_code: ZIP code to search (e.g., "35218")
        city: City name (for logging only)
        state: State code (for logging only)
        max_pages: Maximum number of pages to crawl

    Returns:
        List of business dicts ready for staging table
    """
    location = f"{city}, {state} ({zip_code})"
    logger.info(f"[HA Phase 1] Crawl: '{category}' in {location} (max {max_pages} pages)")
    results: list[dict] = []
    seen_profile_urls = set()

    for page in range(1, max_pages + 1):
        search_url = build_search_url(category, page=page, zip_code=zip_code)
        html = fetch_url(search_url)

        if not html:
            logger.info(f"[HA Phase 1] No HTML for {search_url}, stopping")
            break

        cards = parse_list_page(html)
        if not cards:
            logger.info(f"[HA Phase 1] No cards on page {page}, stopping")
            break

        new_this_page = 0
        for card in cards:
            profile_url = card.get("profile_url")
            if not profile_url:
                logger.debug(f"[HA Phase 1] Skip (no profile URL): {card.get('name')}")
                continue

            # Skip duplicates
            if profile_url in seen_profile_urls:
                logger.debug(f"[HA Phase 1] Duplicate profile URL: {profile_url}")
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

        logger.info(f"[HA Phase 1] Page {page}: extracted {new_this_page}/{len(cards)} businesses")
        if new_this_page == 0:
            break

    logger.info(f"[HA Phase 1] Total extracted for {category}/{location}: {len(results)} businesses")
    return results


def crawl_zips(
    categories: list[str] = None,
    states: list[str] = None,
    tiers: list[str] = None,
    max_cities: int = None,
    save_to_db: bool = True
) -> Generator[dict, None, None]:
    """
    Crawl HomeAdvisor using ZIP code-based approach.

    This generator yields batches of businesses discovered from ZIP code-category combinations.
    Each batch is saved to ha_staging table for Phase 2 processing.

    Args:
        categories: List of service categories (defaults to CATEGORIES_HA)
        states: List of state codes to crawl (defaults to all states)
        tiers: List of tiers to crawl (defaults to all tiers: A, B, C)
        max_cities: Maximum number of cities to crawl (defaults to unlimited)
        save_to_db: If True, save to staging table; if False, just return results

    Yields:
        Dict batches with keys: category, city, state, zip_code, results, count, error (optional)
    """
    if categories is None:
        categories = CATEGORIES_HA

    if tiers is None:
        tiers = ['A', 'B', 'C']

    # Fetch cities from database
    logger.info(f"Fetching cities from database (states={states}, tiers={tiers}, limit={max_cities})")
    cities = get_cities_from_db(states=states, tiers=tiers, limit=max_cities)

    if not cities:
        logger.warning("No cities found in database matching criteria")
        return

    logger.info(f"Found {len(cities)} cities to crawl")

    # Calculate total combinations
    total_combinations = len(cities) * len(categories)

    i = 0
    for city_data in cities:
        city = city_data['city']
        state = city_data['state_id']
        zip_code = city_data['primary_zip']
        tier = city_data['tier']
        max_pages = TIER_PAGES.get(tier, 1)

        for category in categories:
            i += 1
            logger.info(
                f"[HA Phase 1] ({i}/{total_combinations}) "
                f"{category} in {city}, {state} (ZIP: {zip_code}, Tier: {tier})"
            )

            try:
                results = crawl_category_zip(
                    category, zip_code, city, state, max_pages=max_pages
                )

                if save_to_db and results:
                    # Save batch to staging table
                    inserted, skipped = save_to_staging(results)
                    logger.info(
                        f"[HA Phase 1] Saved batch: {category}/{city}/{state}, "
                        f"{inserted} new, {skipped} duplicates"
                    )

                # Yield batch
                yield {
                    "category": category,
                    "city": city,
                    "state": state,
                    "zip_code": zip_code,
                    "tier": tier,
                    "results": results,
                    "count": len(results),
                }

            except Exception as e:
                logger.error(
                    f"[HA Phase 1] Error for {category}/{city}/{state}: {e}",
                    exc_info=True
                )
                # Yield error batch
                yield {
                    "category": category,
                    "city": city,
                    "state": state,
                    "zip_code": zip_code,
                    "error": str(e),
                    "results": [],
                    "count": 0,
                }


def main():
    """CLI entry point for ZIP code-based crawler."""
    import argparse

    parser = argparse.ArgumentParser(description="HomeAdvisor ZIP Code-Based Crawler (Phase 1)")
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
        "--tiers",
        nargs="+",
        choices=['A', 'B', 'C'],
        help="City tiers to crawl (A=major, B=medium, C=small). Defaults to all tiers."
    )
    parser.add_argument(
        "--max-cities",
        type=int,
        help="Maximum number of cities to crawl (defaults to unlimited)"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("HomeAdvisor ZIP Code-Based Crawler Starting (Phase 1)")
    logger.info(f"States: {args.states or 'ALL'}")
    logger.info(f"Categories: {args.categories or 'ALL'}")
    logger.info(f"Tiers: {args.tiers or 'ALL'}")
    logger.info(f"Max cities: {args.max_cities or 'UNLIMITED'}")
    logger.info("=" * 60)

    total_discovered = 0
    total_batches = 0

    for batch in crawl_zips(
        categories=args.categories,
        states=args.states,
        tiers=args.tiers,
        max_cities=args.max_cities
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
                f"(ZIP: {batch['zip_code']}, Tier: {batch['tier']}) "
                f"discovered {batch['count']} businesses"
            )

    logger.info("=" * 60)
    logger.info("Crawl Complete")
    logger.info(f"Total batches: {total_batches}")
    logger.info(f"Total businesses discovered: {total_discovered}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
