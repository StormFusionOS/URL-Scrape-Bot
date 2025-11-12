#!/usr/bin/env python3
"""
HomeAdvisor crawling orchestration (mirrors scrape_yp.yp_crawl).
"""
from __future__ import annotations
from typing import Generator, List, Dict, Optional
from urllib.parse import urlparse

from runner.logging_setup import get_logger
from db.models import canonicalize_url, domain_from_url
from scrape_ha.ha_client import (
    build_search_url, fetch_url, parse_list_page, parse_profile_for_company, HA_BASE
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
    logger.info(f"[HA] Crawl: '{category}' in {state} (max {max_pages} pages)")
    results: list[dict] = []
    seen_domains = set()
    seen_websites = set()

    for page in range(1, max_pages + 1):
        search_url = build_search_url(category, state, page)
        html = fetch_url(search_url)
        if not html:
            logger.info(f"[HA] No HTML for {search_url}, stopping page loop")
            break

        cards = parse_list_page(html)
        if not cards:
            logger.info(f"[HA] No cards on page {page}, stopping")
            break

        new_this_page = 0
        for card in cards:
            profile_url = card.get("profile_url")
            if not profile_url:
                continue
            profile_html = fetch_url(profile_url, delay=0)  # small/no extra delay ok
            if not profile_html:
                continue
            info = parse_profile_for_company(profile_html)

            # Must have external website to keep consistent with your DB logic
            website = info.get("website")
            if not website:
                logger.debug(f"[HA] Skip (no external site): {card.get('name')}")
                continue

            try:
                website = canonicalize_url(website)
                domain = domain_from_url(website)
            except Exception as e:
                logger.debug(f"[HA] Bad URL '{website}': {e}")
                continue

            if domain in seen_domains or website in seen_websites:
                logger.debug(f"[HA] Duplicate domain/site: {domain}")
                continue

            seen_domains.add(domain); seen_websites.add(website)

            results.append({
                "name": info.get("name") or card.get("name"),
                "website": website,
                "domain": domain,
                "phone": info.get("phone"),
                "address": info.get("address"),
                "rating_ha": (float(info.get("rating_ha")) if info.get("rating_ha") else None),
                "reviews_ha": (int(info.get("reviews_ha")) if info.get("reviews_ha") else None),
                "source": "HA",
                "profile_url": profile_url,
            })
            new_this_page += 1

        logger.info(f"[HA] Page {page}: kept {new_this_page}/{len(cards)}")
        if new_this_page == 0:
            break

    return results

def crawl_all_states(categories: list[str] = None,
                     states: list[str] = None,
                     limit_per_state: int = 3) -> Generator[dict, None, None]:
    """
    Crawl all state-category combinations and yield batches.

    Yields dicts with keys: category, state, results, count (matching YP format)
    """
    if categories is None:
        categories = CATEGORIES_HA
    if states is None:
        states = STATES

    total = len(categories) * len(states)
    i = 0
    for state in states:
        for cat in categories:
            i += 1
            logger.info(f"[HA] ({i}/{total}) {cat} in {state}")
            try:
                results = crawl_category_state(cat, state, max_pages=limit_per_state)
                # Yield batch in same format as YP crawler
                batch = {
                    "category": cat,
                    "state": state,
                    "results": results,
                    "count": len(results),
                }
                logger.info(f"[HA] Yielding batch: {cat} in {state}, {len(results)} results")
                yield batch
            except Exception as e:
                logger.error(f"[HA] Error for {cat}/{state}: {e}", exc_info=True)
                # Yield error batch
                yield {
                    "category": cat,
                    "state": state,
                    "error": str(e),
                    "results": [],
                    "count": 0,
                }
