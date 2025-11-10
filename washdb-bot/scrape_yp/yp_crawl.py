#!/usr/bin/env python3
"""
Yellow Pages crawling orchestration for washdb-bot.

This module provides:
- Multi-page crawling for category/location combinations
- Batch processing across states and categories
- De-duplication by domain/website
- Data normalization
"""

from typing import Generator

from db.models import canonicalize_url, domain_from_url
from runner.logging_setup import get_logger
from scrape_yp.yp_client import fetch_yp_search_page, parse_yp_results


# Initialize logger
logger = get_logger("yp_crawl")

# Default categories to crawl - using broader terms that return consistent results
CATEGORIES = [
    "pressure washing",
    "power washing",
    "soft washing",
    "window cleaning",
    "gutter cleaning",
    "roof cleaning",
    "deck cleaning",
    "concrete cleaning",
    "house cleaning exterior",
    "driveway cleaning",
]

# US States (2-letter codes)
STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


def crawl_category_location(
    category: str,
    location: str,
    max_pages: int = 50,
) -> list[dict]:
    """
    Crawl Yellow Pages for a specific category and location across multiple pages.

    Args:
        category: Search category (e.g., "pressure washing")
        location: Geographic location (e.g., "Texas" or "TX")
        max_pages: Maximum number of pages to crawl (default: 50)

    Returns:
        List of de-duplicated business dicts with normalized URLs and domains
    """
    logger.info(f"Starting crawl: category='{category}', location='{location}', max_pages={max_pages}")

    all_results = []
    seen_domains = set()
    seen_websites = set()

    for page in range(1, max_pages + 1):
        logger.info(f"Crawling page {page}/{max_pages}...")

        try:
            # Fetch page HTML
            html = fetch_yp_search_page(category, location, page)

            # Parse results
            results = parse_yp_results(html)

            # Check if we got any results
            if not results:
                logger.info(f"No results found on page {page}. Ending crawl.")
                break

            logger.info(f"Parsed {len(results)} results from page {page}")

            # Process each result
            new_results = 0
            for result in results:
                # Add source
                result["source"] = "YP"

                # Normalize and add domain if website exists
                if result.get("website"):
                    try:
                        # Canonicalize URL
                        canonical = canonicalize_url(result["website"])
                        result["website"] = canonical

                        # Extract domain
                        result["domain"] = domain_from_url(canonical)

                        # Check for duplicates
                        if result["domain"] in seen_domains:
                            logger.debug(f"Skipping duplicate domain: {result['domain']}")
                            continue

                        if result["website"] in seen_websites:
                            logger.debug(f"Skipping duplicate website: {result['website']}")
                            continue

                        # Mark as seen
                        seen_domains.add(result["domain"])
                        seen_websites.add(result["website"])

                    except Exception as e:
                        logger.warning(f"Failed to normalize URL '{result['website']}': {e}")
                        # Skip results with invalid URLs
                        continue
                else:
                    # No website - skip or handle differently
                    # For now, we'll skip businesses without websites
                    logger.debug(f"Skipping business without website: {result.get('name')}")
                    continue

                # Add to results
                all_results.append(result)
                new_results += 1

            logger.info(f"Added {new_results} new unique results from page {page}")

            # If no new results were added, we might be at the end
            if new_results == 0:
                logger.info("No new unique results found. Ending crawl.")
                break

            # Check for pagination indicators in HTML
            # If page structure indicates we're at the end, break
            if is_last_page(html):
                logger.info("Detected last page. Ending crawl.")
                break

        except Exception as e:
            logger.error(f"Error crawling page {page}: {e}")
            # Continue to next page on error
            continue

    logger.info(
        f"Crawl complete: category='{category}', location='{location}', "
        f"pages={page}, total_results={len(all_results)}"
    )

    return all_results


def is_last_page(html: str) -> bool:
    """
    Check if the current page is the last page of results.

    Args:
        html: HTML content from Yellow Pages

    Returns:
        True if this appears to be the last page
    """
    # Simple heuristic: check if "next" button/link is disabled or missing
    # This is a basic check - may need refinement based on actual YP HTML structure
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    # Look for disabled next button
    next_disabled = soup.select_one("a.next.disabled") or soup.select_one("button.next[disabled]")
    if next_disabled:
        return True

    # Look for active next link
    next_link = soup.select_one("a.next:not(.disabled)") or soup.select_one("a[rel='next']")
    if not next_link:
        # No next link found - might be last page
        return True

    return False


def crawl_all_states(
    categories: list[str] = None,
    states: list[str] = None,
    limit_per_state: int = 3,
) -> Generator[dict, None, None]:
    """
    Crawl all state-category combinations and yield batches.

    This generator yields batches of results for each state-category combination,
    allowing for incremental processing and database insertion.

    Args:
        categories: List of categories to crawl (default: CATEGORIES)
        states: List of state codes to crawl (default: STATES)
        limit_per_state: Maximum pages per state-category combination (default: 3)

    Yields:
        Dict with keys:
        - category: Category name
        - state: State code
        - results: List of business dicts
        - count: Number of results
    """
    if categories is None:
        categories = CATEGORIES

    if states is None:
        states = STATES

    logger.info(
        f"Starting crawl_all_states: "
        f"{len(categories)} categories × {len(states)} states × {limit_per_state} pages/each"
    )
    logger.info(f"Categories: {', '.join(categories)}")
    logger.info(f"States: {', '.join(states)}")

    total_combinations = len(categories) * len(states)
    current = 0

    import time
    import random

    for state in states:
        for category in categories:
            current += 1
            logger.info(
                f"[{current}/{total_combinations}] Processing: {category} in {state}"
            )

            try:
                # Crawl this combination
                results = crawl_category_location(
                    category=category,
                    location=state,
                    max_pages=limit_per_state,
                )

                # Yield batch
                batch = {
                    "category": category,
                    "state": state,
                    "results": results,
                    "count": len(results),
                }

                logger.info(
                    f"Yielding batch: {category} in {state} - {len(results)} results"
                )

                yield batch

            except Exception as e:
                logger.error(
                    f"Error processing {category} in {state}: {e}",
                    exc_info=True,
                )
                # Yield empty batch on error
                yield {
                    "category": category,
                    "state": state,
                    "results": [],
                    "count": 0,
                    "error": str(e),
                }

        # Add cooldown period after each state (all categories for one state)
        # This gives Yellow Pages time to "forget" about us
        if state != states[-1]:  # Don't sleep after last state
            cooldown = random.uniform(15, 25)  # 15-25 second cooldown
            logger.info(f"Cooldown period: sleeping {cooldown:.1f}s before next state...")
            time.sleep(cooldown)


def main():
    """Demo: Crawl a single category-location combination."""
    logger.info("=" * 60)
    logger.info("Yellow Pages Crawler Demo")
    logger.info("=" * 60)

    # Demo: Crawl one category in one state
    category = "pressure washing"
    location = "TX"
    max_pages = 3

    logger.info(f"Crawling: {category} in {location} (max {max_pages} pages)")
    logger.info("")

    results = crawl_category_location(category, location, max_pages)

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Crawl Results: {len(results)} unique businesses")
    logger.info("=" * 60)
    logger.info("")

    # Display first few results
    for i, result in enumerate(results[:5], 1):
        logger.info(f"{i}. {result['name']}")
        logger.info(f"   Domain: {result['domain']}")
        logger.info(f"   Website: {result['website']}")
        if result.get("phone"):
            logger.info(f"   Phone: {result['phone']}")
        if result.get("address"):
            logger.info(f"   Address: {result['address']}")
        logger.info("")

    if len(results) > 5:
        logger.info(f"... and {len(results) - 5} more results")

    logger.info("")
    logger.info("Demo: Crawling multiple state-category combinations")
    logger.info("")

    # Demo: Crawl multiple combinations
    demo_categories = ["pressure washing", "window cleaning"]
    demo_states = ["TX", "CA"]

    batch_count = 0
    total_results = 0

    for batch in crawl_all_states(
        categories=demo_categories,
        states=demo_states,
        limit_per_state=2,  # Just 2 pages for demo
    ):
        batch_count += 1
        total_results += batch["count"]
        logger.info(
            f"Batch {batch_count}: {batch['category']} in {batch['state']} - "
            f"{batch['count']} results"
        )

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"All batches complete: {batch_count} batches, {total_results} total results")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
