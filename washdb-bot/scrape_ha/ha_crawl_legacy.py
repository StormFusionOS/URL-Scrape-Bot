#!/usr/bin/env python3
"""
HomeAdvisor crawling orchestration (Phase 1 of pipeline - saves to staging).
"""
from __future__ import annotations
from typing import Generator, List, Dict, Optional
from urllib.parse import urlparse

from runner.logging_setup import get_logger
from db.models import canonicalize_url, domain_from_url
from db.save_to_staging import save_to_staging, get_staging_stats
from scrape_ha.ha_client import (
    build_search_url, fetch_url, parse_list_page, HA_BASE
)

logger = get_logger("ha_crawl")

CATEGORIES_HA = [
    "power washing",
    "window cleaning services",
    "deck staining or painting",
    "fence painting or staining",
]

# US States list (previously imported from YP scraper)
STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

def crawl_category_state(category: str, state: str, max_pages: int = 3) -> list[dict]:
    """
    Crawl HomeAdvisor list pages and extract basic business info for staging.

    PIPELINE Phase 1: Extracts only name, address, phone, ratings from list pages.
    Data is saved to ha_staging table where Phase 2 (URL finder) will process it.
    """
    logger.info(f"[HA Phase 1] Crawl: '{category}' in {state} (max {max_pages} pages)")
    results: list[dict] = []
    seen_profile_urls = set()

    for page in range(1, max_pages + 1):
        search_url = build_search_url(category, state, page)
        html = fetch_url(search_url)
        if not html:
            logger.info(f"[HA Phase 1] No HTML for {search_url}, stopping page loop")
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

            # Prepare data for staging table (no website/domain needed yet)
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

    logger.info(f"[HA Phase 1] Total extracted for {category}/{state}: {len(results)} businesses")
    return results

def crawl_all_states(categories: list[str] = None,
                     states: list[str] = None,
                     limit_per_state: int = 3,
                     save_to_db: bool = True) -> Generator[dict, None, None]:
    """
    Crawl all state-category combinations and yield batches.

    PIPELINE Phase 1: Discovers businesses and saves to ha_staging table.
    Phase 2 (URL finder worker) will process items from the queue.

    Args:
        categories: List of service categories to search
        states: List of US state codes to search
        limit_per_state: Number of pages to scrape per category/state pair
        save_to_db: If True, save to staging table; if False, return results

    Yields:
        Dict batches with keys: category, state, results, count, error (optional)
    """
    if categories is None:
        categories = CATEGORIES_HA
    if states is None:
        states = STATES

    total_pairs = len(categories) * len(states)

    i = 0
    for state in states:
        for cat in categories:
            i += 1
            logger.info(f"[HA Phase 1] ({i}/{total_pairs}) {cat} in {state}")
            try:
                results = crawl_category_state(cat, state, max_pages=limit_per_state)

                if save_to_db and results:
                    # Save batch to staging table
                    inserted, skipped = save_to_staging(results)
                    logger.info(
                        f"[HA Phase 1] Saved batch: {cat}/{state}, "
                        f"{inserted} new, {skipped} duplicates"
                    )

                # Yield batch
                yield {
                    "category": cat,
                    "state": state,
                    "results": results,
                    "count": len(results),
                }

            except Exception as e:
                logger.error(f"[HA Phase 1] Error for {cat}/{state}: {e}", exc_info=True)
                # Yield error batch
                yield {
                    "category": cat,
                    "state": state,
                    "error": str(e),
                    "results": [],
                    "count": 0,
                }
