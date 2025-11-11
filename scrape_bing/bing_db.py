"""
Database integration for Bing discoveries.

This module provides convenience functions for saving Bing discovery results
to the database, wrapping the existing db.save_discoveries module.

Usage:
    from scrape_bing.bing_db import save_bing_discoveries

    results = crawl_category_location("pressure washing", "TX")
    stats = save_bing_discoveries(results)
    print(f"Saved: {stats['inserted']} inserted, {stats['updated']} updated")
"""

import logging
from typing import List, Dict, Any

from db.save_discoveries import upsert_discovered
from db.models import canonicalize_url, domain_from_url


# Configure logging
logger = logging.getLogger(__name__)


def save_bing_discoveries(
    results: List[Dict[str, Any]],
    batch_size: int = 100
) -> Dict[str, int]:
    """
    Save Bing discovery results to the database.

    Wraps the existing upsert_discovered() function with Bing-specific
    preprocessing and logging. Handles large result sets by processing
    in batches.

    Args:
        results: List of discovery dicts from Bing crawl with fields:
            - name: Business name
            - website: Canonical URL
            - domain: Extracted domain
            - source: Always 'BING'
            - category: Search category (optional, not saved to DB)
            - location: Search location (optional, not saved to DB)
            - snippet: Raw snippet (optional, not saved to DB)
            - discovered_at: ISO timestamp (optional, not saved to DB)
        batch_size: Number of records to process per batch (default: 100)

    Returns:
        Dict with stats:
            - inserted: Number of new records inserted
            - updated: Number of existing records updated
            - skipped: Number of records skipped (errors or no changes)
            - total: Total records processed

    Example:
        >>> results = crawl_category_location("pressure washing", "TX")
        >>> stats = save_bing_discoveries(results)
        >>> print(f"Inserted: {stats['inserted']}, Updated: {stats['updated']}")
    """
    if not results:
        logger.warning("No results to save")
        return {"inserted": 0, "updated": 0, "skipped": 0, "total": 0}

    logger.info(f"Saving {len(results)} Bing discoveries to database...")

    # Validate and preprocess results
    valid_results = []

    for result in results:
        try:
            # Ensure required fields are present
            if not result.get("website"):
                logger.warning(f"Skipping result without website: {result.get('name')}")
                continue

            if not result.get("name"):
                logger.warning(f"Skipping result without name: {result.get('website')}")
                continue

            # Ensure source is set to BING
            result["source"] = "BING"

            # Ensure website is canonical and domain is present
            result["website"] = canonicalize_url(result["website"])
            result["domain"] = domain_from_url(result["website"])

            # Build company dict with only DB-relevant fields
            company_dict = {
                "name": result.get("name"),
                "website": result["website"],
                "domain": result["domain"],
                "source": "BING",
                # Phone and email are null at discovery time
                # (will be enriched by site scraper later)
                "phone": result.get("phone"),
                "email": result.get("email"),
                "address": result.get("address"),
                "services": result.get("services"),
                "service_area": result.get("service_area"),
            }

            valid_results.append(company_dict)

        except Exception as e:
            logger.error(
                f"Error preprocessing result {result.get('name', 'Unknown')}: {e}"
            )
            continue

    if not valid_results:
        logger.warning("No valid results to save after preprocessing")
        return {"inserted": 0, "updated": 0, "skipped": 0, "total": len(results)}

    logger.info(f"Preprocessed {len(valid_results)} valid results")

    # Process in batches
    total_inserted = 0
    total_updated = 0
    total_skipped = 0

    for i in range(0, len(valid_results), batch_size):
        batch = valid_results[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(valid_results) + batch_size - 1) // batch_size

        logger.info(
            f"Processing batch {batch_num}/{total_batches} "
            f"({len(batch)} records)"
        )

        try:
            inserted, skipped, updated = upsert_discovered(batch)

            total_inserted += inserted
            total_updated += updated
            total_skipped += skipped

            logger.info(
                f"Batch {batch_num} complete: "
                f"{inserted} inserted, {updated} updated, {skipped} skipped"
            )

        except Exception as e:
            logger.error(f"Error saving batch {batch_num}: {e}", exc_info=True)
            total_skipped += len(batch)
            continue

    # Final summary
    logger.info(
        f"Save complete: {len(results)} total → "
        f"{total_inserted} inserted, {total_updated} updated, {total_skipped} skipped"
    )

    return {
        "inserted": total_inserted,
        "updated": total_updated,
        "skipped": total_skipped,
        "total": len(results),
    }


def save_bing_crawl_results(
    category: str,
    location: str,
    results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Save Bing crawl results with category/location context.

    Convenience wrapper that adds metadata logging for a specific
    category/location crawl before saving to the database.

    Args:
        category: Service category that was crawled
        location: Geographic location that was crawled
        results: Discovery results from crawl

    Returns:
        Dict with stats:
            - category: The category crawled
            - location: The location crawled
            - found: Number of results found in crawl
            - inserted: Number of new records inserted
            - updated: Number of existing records updated
            - skipped: Number of records skipped

    Example:
        >>> results = crawl_category_location("pressure washing", "TX", max_pages=3)
        >>> stats = save_bing_crawl_results("pressure washing", "TX", results)
        >>> print(f"{stats['category']} in {stats['location']}: {stats['inserted']} new")
    """
    logger.info(
        f"Saving Bing crawl results: category='{category}', "
        f"location='{location}', found={len(results)}"
    )

    save_stats = save_bing_discoveries(results)

    return {
        "category": category,
        "location": location,
        "found": len(results),
        "inserted": save_stats["inserted"],
        "updated": save_stats["updated"],
        "skipped": save_stats["skipped"],
    }


# ==============================================================================
# Export Functions
# ==============================================================================

__all__ = [
    "save_bing_discoveries",
    "save_bing_crawl_results",
]
