"""
Bing crawl orchestrator - multi-page discovery with de-duplication.

This module coordinates the high-level discovery workflow across Bing search
results. It handles multi-page crawling, within-batch de-duplication, and
result aggregation for category/location pairs.

Responsibilities:
    - crawl_category_location(): Crawl multiple pages for a single category/location
    - crawl_all_states(): Generator that crawls across all states/categories
    - De-duplication by canonical domain
    - Progress tracking and metrics logging
    - Callback hooks for UI progress updates

Usage:
    from scrape_bing import crawl_category_location, crawl_all_states

    # Crawl a single category/location
    results = crawl_category_location(
        category="pressure washing",
        location="TX",
        max_pages=5
    )

    # Crawl all states (generator for memory efficiency)
    for result in crawl_all_states(
        categories=["pressure washing", "window cleaning"],
        states=["TX", "IL"],
        limit_per_state=3
    ):
        print(result)
"""

import logging
from typing import List, Dict, Any, Optional, Callable, Generator
from datetime import datetime
import time

from scrape_bing.bing_client import (
    fetch_bing_search_page,
    parse_bing_results,
)
from scrape_bing.bing_config import (
    CATEGORIES,
    STATES,
    PAGES_PER_PAIR,
    CRAWL_DELAY_SECONDS,
)
from scrape_bing.query_variants import generate_query_variants

# Configure logging
logger = logging.getLogger(__name__)


# ==============================================================================
# De-duplication Helper
# ==============================================================================

def deduplicate_by_domain(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    De-duplicate results by canonical domain.

    Removes duplicate entries within a batch by keeping only the first
    occurrence of each unique domain.

    Args:
        results: List of discovery dicts with 'domain' field

    Returns:
        De-duplicated list of discovery dicts

    Example:
        >>> results = [
        ...     {'domain': 'example.com', 'name': 'Example Inc'},
        ...     {'domain': 'example.com', 'name': 'Example Co'},  # duplicate
        ...     {'domain': 'other.com', 'name': 'Other Business'},
        ... ]
        >>> deduped = deduplicate_by_domain(results)
        >>> len(deduped)
        2
    """
    logger.debug(f"De-duplicating {len(results)} results by domain")

    seen_domains = set()
    unique_results = []

    for result in results:
        domain = result.get('domain')

        if not domain:
            logger.warning("Result missing domain field, skipping")
            continue

        # Keep first occurrence of each domain
        if domain not in seen_domains:
            seen_domains.add(domain)
            unique_results.append(result)
        else:
            logger.debug(f"Skipping duplicate domain: {domain}")

    duplicates_removed = len(results) - len(unique_results)
    logger.info(f"De-duplication: {len(results)} → {len(unique_results)} results ({duplicates_removed} duplicates removed)")

    return unique_results


# ==============================================================================
# Single Category/Location Crawl
# ==============================================================================

def crawl_category_location(
    category: str,
    location: str,
    max_pages: int = PAGES_PER_PAIR,
    page_callback: Optional[Callable[[int, int, int], None]] = None
) -> List[Dict[str, Any]]:
    """
    Crawl Bing search results for a single category/location pair using multi-variant queries.

    Generates 6 query variants (exact phrase, synonyms, operators) for maximum recall.
    Each variant is paginated to fetch multiple pages, then results are aggregated and de-duplicated.

    Based on Yellow Pages Prompt E implementation:
    - Exact phrase + location (quoted primary)
    - 3 synonym variants (power washing, pressure wash, etc.)
    - 2 operator variants (intitle:, inurl:)
    - Negative keywords applied to all queries
    - Each variant fetches multiple pages (configurable depth)

    Args:
        category: Service category (e.g., "pressure washing")
        location: Geographic location (e.g., "TX", "Peoria IL")
        max_pages: Number of pages to fetch per variant (default: PAGES_PER_PAIR)
        page_callback: Optional callback function called after each variant
                       Signature: callback(variant_num, results_this_variant, total_so_far)

    Returns:
        List of unique discovery dicts with fields:
            - name: Business name
            - website: Canonical URL
            - domain: Extracted domain
            - source: Always 'BING'
            - category: The search category
            - location: The search location
            - discovered_at: ISO timestamp
            - query_pattern: Query variant pattern (exact, synonym, operator_*)

    Example:
        >>> results = crawl_category_location(
        ...     category="pressure washing",
        ...     location="TX"
        ... )
        >>> len(results)  # Typically 5-20 unique businesses
    """
    logger.info(f"Starting multi-variant crawl: category='{category}', location='{location}', max_pages={max_pages}")

    all_results = []

    # Generate query variants (6 variants per category/location)
    variants = generate_query_variants(category, location, variants_per_pair=6)
    logger.info(f"Generated {len(variants)} query variants, {max_pages} pages per variant")

    # Crawl each variant with pagination
    for variant in variants:
        variant_num = variant['variant_index']
        query = variant['query']
        pattern = variant['pattern']
        variant_results = []

        try:
            logger.info(f"Fetching variant {variant_num}/{len(variants)}: pattern='{pattern}', query='{query[:80]}'")

            # Paginate this variant
            for page_num in range(1, max_pages + 1):
                try:
                    logger.debug(f"Variant {variant_num}/{len(variants)}, page {page_num}/{max_pages}")

                    # Fetch this page
                    payload = fetch_bing_search_page(query, page=page_num)

                    # Determine mode based on payload type
                    mode = 'api' if isinstance(payload, dict) else 'html'

                    # Parse results
                    page_results = parse_bing_results(payload, mode=mode)

                    # Add metadata to each result
                    for result in page_results:
                        result['category'] = category
                        result['location'] = location
                        result['query_pattern'] = pattern  # Track which variant found this result

                    # Accumulate variant results
                    variant_results.extend(page_results)

                    logger.debug(f"Variant {variant_num}/{len(variants)}, page {page_num}/{max_pages}: Found {len(page_results)} results")

                    # Apply delay between pages (polite crawling)
                    if page_num < max_pages:
                        delay = CRAWL_DELAY_SECONDS
                        logger.debug(f"Sleeping {delay}s before next page")
                        time.sleep(delay)

                except Exception as e:
                    logger.warning(f"Error fetching variant {variant_num}, page {page_num}: {e}")
                    # Continue to next page instead of failing entire variant
                    continue

            # Accumulate all results
            all_results.extend(variant_results)

            # Call progress callback
            if page_callback:
                page_callback(variant_num, len(variant_results), len(all_results))

            logger.info(f"Variant {variant_num}/{len(variants)} ({pattern}): Found {len(variant_results)} results across {max_pages} pages (total: {len(all_results)})")

        except Exception as e:
            logger.error(f"Error processing variant {variant_num} ({pattern}): {e}", exc_info=True)
            # Continue to next variant instead of failing entire crawl
            continue

    # De-duplicate by domain
    unique_results = deduplicate_by_domain(all_results)

    logger.info(
        f"Multi-variant crawl complete: category='{category}', location='{location}', "
        f"variants={len(variants)}, total_results={len(all_results)}, unique={len(unique_results)}"
    )

    return unique_results


# ==============================================================================
# Multi-State Crawl Generator
# ==============================================================================

def crawl_all_states(
    categories: Optional[List[str]] = None,
    states: Optional[List[str]] = None,
    limit_per_state: Optional[int] = None,
    page_callback: Optional[Callable[[str, str, int, int], None]] = None
) -> Generator[Dict[str, Any], None, None]:
    """
    Generator that crawls all category/state combinations.

    Yields individual discovery results as they are found, enabling
    memory-efficient processing of large-scale crawls.

    Args:
        categories: List of service categories (default: all CATEGORIES)
        states: List of US state codes (default: all STATES)
        limit_per_state: Maximum pages per category/state pair (default: PAGES_PER_PAIR)
        page_callback: Optional callback after each category/state pair
                       Signature: callback(category, state, pair_results, cumulative_total)

    Yields:
        Individual discovery dicts (one per unique business found)

    Example:
        >>> for result in crawl_all_states(
        ...     categories=["pressure washing"],
        ...     states=["TX", "IL"],
        ...     limit_per_state=2
        ... ):
        ...     print(f"Found: {result['name']} in {result['location']}")
    """
    # Use defaults if not provided
    categories = categories or CATEGORIES
    states = states or STATES
    limit_per_state = limit_per_state or PAGES_PER_PAIR

    total_pairs = len(categories) * len(states)
    pair_num = 0
    cumulative_total = 0

    logger.info(
        f"Starting multi-state crawl: "
        f"{len(categories)} categories × {len(states)} states "
        f"({limit_per_state} pages/pair) = {total_pairs} total pairs"
    )

    # Double loop: iterate all category × state combinations
    for cat_idx, category in enumerate(categories, 1):
        for state_idx, state in enumerate(states, 1):
            pair_num += 1

            try:
                logger.info(
                    f"Crawling pair {pair_num}/{total_pairs}: "
                    f"category={category} ({cat_idx}/{len(categories)}), "
                    f"state={state} ({state_idx}/{len(states)})"
                )

                # Crawl this category/state pair
                results = crawl_category_location(
                    category=category,
                    location=state,
                    max_pages=limit_per_state
                )

                pair_count = len(results)
                logger.info(
                    f"Pair {pair_num}/{total_pairs} complete: "
                    f"{category} × {state} → {pair_count} unique results"
                )

                # Yield each result individually (generator pattern)
                for result in results:
                    yield result
                    cumulative_total += 1

                # Call progress callback if provided
                if page_callback:
                    try:
                        page_callback(category, state, pair_count, cumulative_total)
                    except Exception as e:
                        logger.warning(f"Progress callback failed: {e}")

                # Apply delay between pairs (polite crawling)
                if pair_num < total_pairs:
                    logger.debug(f"Sleeping {CRAWL_DELAY_SECONDS}s before next pair")
                    time.sleep(CRAWL_DELAY_SECONDS)

            except Exception as e:
                logger.error(
                    f"Error crawling pair {pair_num}/{total_pairs} "
                    f"({category} × {state}): {e}",
                    exc_info=True
                )
                # Continue to next pair instead of failing entire crawl
                continue

    # Log completion summary
    logger.info(
        f"Multi-state crawl complete: "
        f"{total_pairs} pairs processed, "
        f"{cumulative_total} total unique results yielded"
    )


# ==============================================================================
# Export Constants
# ==============================================================================

# Re-export categories and states for convenience
__all__ = [
    'crawl_category_location',
    'crawl_all_states',
    'deduplicate_by_domain',
    'CATEGORIES',
    'STATES',
]
