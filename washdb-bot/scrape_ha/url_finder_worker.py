#!/usr/bin/env python3
"""
URL Finder Worker - Phase 2 of HomeAdvisor Pipeline

Continuous background worker that processes businesses from ha_staging table,
searches DuckDuckGo for external websites, and moves them to main companies table.

Architecture:
- Polls ha_staging table every 30 seconds
- Waits for minimum batch size (10 businesses) before starting
- Processes one business at a time with DuckDuckGo search
- Implements exponential backoff for retries (1h, 4h, 16h)
- Deduplicates by domain when inserting into main companies table
- Deletes from staging after successful processing or max retries
"""
from __future__ import annotations
import asyncio
import random
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser
from sqlalchemy import select, func, and_

from db.models import Company, HAStaging, canonicalize_url, domain_from_url
from db.save_discoveries import create_session, normalize_phone, normalize_email
from scrape_ha.url_finder import (
    extract_city_state_from_address,
    build_search_query,
    search_duckduckgo,
    score_url_match,
    MIN_SEARCH_DELAY,
    MAX_SEARCH_DELAY,
    USER_AGENTS,
)
from runner.logging_setup import get_logger

logger = get_logger("url_finder_worker")

# Worker configuration
POLL_INTERVAL_SECONDS = 30  # Poll staging table every 30 seconds
MIN_BATCH_SIZE = 10  # Wait for at least 10 businesses before starting
MAX_RETRY_COUNT = 3  # Give up after 3 failed attempts
RETRY_DELAYS = [1, 4, 16]  # Exponential backoff in hours (2^0, 2^2, 2^4)

# Shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


async def find_business_url(page: Page, staging: HAStaging) -> Optional[str]:
    """
    Search for external website URL for a business from staging table.

    Args:
        page: Playwright page instance
        staging: HAStaging record from database

    Returns:
        External website URL or None if not found
    """
    logger.info(f"[Find URL] {staging.name}")

    # Build search query
    query = build_search_query(staging.name, staging.address)

    # Search DuckDuckGo
    results = await search_duckduckgo(page, query)

    if not results:
        logger.warning(f"[Find URL] No results for {staging.name}")
        return None

    # Extract city/state for scoring
    city, state = extract_city_state_from_address(staging.address)

    # Score all results
    scored_results = []
    for result in results:
        score = score_url_match(result["url"], staging.name, city, state)
        if score > 0.0:
            scored_results.append({
                "url": result["url"],
                "score": score,
                "title": result["title"],
            })

    # Sort by score (highest first)
    scored_results.sort(key=lambda x: x["score"], reverse=True)

    if scored_results:
        best_match = scored_results[0]
        logger.info(
            f"[Find URL] Best match: {best_match['url']} "
            f"(score: {best_match['score']:.2f})"
        )
        return best_match["url"]

    logger.warning(f"[Find URL] No good matches for {staging.name}")
    return None


def upsert_to_companies_by_domain(staging: HAStaging, website: str) -> bool:
    """
    Insert or update company in main companies table, deduplicating by domain.

    Args:
        staging: HAStaging record with business info
        website: External website URL found

    Returns:
        True if successful, False otherwise
    """
    session = create_session()

    try:
        # Canonicalize and extract domain
        canonical_website = canonicalize_url(website)
        domain = domain_from_url(canonical_website)

        # Check if domain already exists in companies table
        stmt = select(Company).where(Company.domain == domain)
        existing = session.execute(stmt).scalar_one_or_none()

        if existing:
            # Update existing record with new data from staging
            logger.info(f"[Dedup] Domain {domain} exists, updating existing record")

            updated_fields = []

            if staging.name:
                existing.name = staging.name
                updated_fields.append("name")

            if staging.phone:
                normalized_phone = normalize_phone(staging.phone)
                if normalized_phone:
                    existing.phone = normalized_phone
                    updated_fields.append("phone")

            if staging.address:
                existing.address = staging.address
                updated_fields.append("address")

            if staging.rating_ha is not None:
                existing.rating_ha = staging.rating_ha
                updated_fields.append("rating_ha")

            if staging.reviews_ha is not None:
                existing.reviews_ha = staging.reviews_ha
                updated_fields.append("reviews_ha")

            # Always set active=True and source
            existing.active = True
            existing.source = "HA"

            session.commit()

            if updated_fields:
                logger.info(f"[Update] {domain}: {', '.join(updated_fields)}")
            else:
                logger.info(f"[Update] {domain}: no new data")

        else:
            # Insert new record
            logger.info(f"[Insert] New domain: {domain}")

            normalized_phone = normalize_phone(staging.phone)

            new_company = Company(
                name=staging.name,
                website=canonical_website,
                domain=domain,
                phone=normalized_phone,
                email=None,
                address=staging.address,
                services=None,
                service_area=None,
                source="HA",
                rating_ha=staging.rating_ha,
                reviews_ha=staging.reviews_ha,
                active=True,
            )

            session.add(new_company)
            session.commit()

            logger.info(f"[Insert] Created new company: {domain}")

        return True

    except Exception as e:
        logger.error(f"Error upserting to companies table: {e}", exc_info=True)
        session.rollback()
        return False

    finally:
        session.close()


def update_staging_retry(staging_id: int, error_message: str):
    """
    Update staging record with retry information.

    Increments retry_count and sets next_retry_at using exponential backoff.

    Args:
        staging_id: ID of staging record
        error_message: Error message to store
    """
    session = create_session()

    try:
        stmt = select(HAStaging).where(HAStaging.id == staging_id)
        staging = session.execute(stmt).scalar_one_or_none()

        if not staging:
            logger.warning(f"Staging record {staging_id} not found for retry update")
            return

        # Increment retry count
        staging.retry_count += 1

        # Set next retry time using exponential backoff
        if staging.retry_count < MAX_RETRY_COUNT:
            hours_delay = RETRY_DELAYS[staging.retry_count - 1]
            staging.next_retry_at = datetime.now() + timedelta(hours=hours_delay)
            logger.info(
                f"[Retry] {staging.name}: retry {staging.retry_count}/{MAX_RETRY_COUNT} "
                f"scheduled in {hours_delay}h"
            )
        else:
            logger.warning(
                f"[Failed] {staging.name}: max retries ({MAX_RETRY_COUNT}) reached"
            )

        # Store error message
        staging.last_error = error_message[:500]  # Truncate long errors

        session.commit()

    except Exception as e:
        logger.error(f"Error updating retry info: {e}", exc_info=True)
        session.rollback()

    finally:
        session.close()


def delete_from_staging(staging_id: int):
    """
    Delete staging record after successful processing or max retries.

    Args:
        staging_id: ID of staging record to delete
    """
    session = create_session()

    try:
        stmt = select(HAStaging).where(HAStaging.id == staging_id)
        staging = session.execute(stmt).scalar_one_or_none()

        if staging:
            session.delete(staging)
            session.commit()
            logger.debug(f"[Cleanup] Deleted staging record: {staging.name}")
        else:
            logger.warning(f"Staging record {staging_id} not found for deletion")

    except Exception as e:
        logger.error(f"Error deleting staging record: {e}", exc_info=True)
        session.rollback()

    finally:
        session.close()


def get_pending_staging_records(limit: int = 1) -> list[HAStaging]:
    """
    Get pending staging records ready for processing.

    Returns records where:
    - processed = False
    - retry_count < MAX_RETRY_COUNT
    - next_retry_at is NULL or in the past

    Args:
        limit: Maximum number of records to return

    Returns:
        List of HAStaging records
    """
    session = create_session()

    try:
        now = datetime.now()

        stmt = (
            select(HAStaging)
            .where(
                and_(
                    HAStaging.processed == False,
                    HAStaging.retry_count < MAX_RETRY_COUNT,
                    (HAStaging.next_retry_at.is_(None) | (HAStaging.next_retry_at <= now))
                )
            )
            .order_by(HAStaging.created_at.asc())
            .limit(limit)
        )

        results = session.execute(stmt).scalars().all()
        return list(results)

    finally:
        session.close()


def get_staging_queue_size() -> int:
    """
    Get count of pending staging records ready for processing.

    Returns:
        Number of pending records
    """
    session = create_session()

    try:
        now = datetime.now()

        stmt = (
            select(func.count(HAStaging.id))
            .where(
                and_(
                    HAStaging.processed == False,
                    HAStaging.retry_count < MAX_RETRY_COUNT,
                    (HAStaging.next_retry_at.is_(None) | (HAStaging.next_retry_at <= now))
                )
            )
        )

        count = session.execute(stmt).scalar()
        return count or 0

    finally:
        session.close()


async def process_one_staging_record(page: Page, staging: HAStaging) -> bool:
    """
    Process a single staging record: find URL, upsert to companies, cleanup.

    Args:
        page: Playwright page instance
        staging: HAStaging record to process

    Returns:
        True if successful, False if failed (will retry later)
    """
    logger.info(f"[Process] {staging.name} (ID: {staging.id}, retry: {staging.retry_count})")

    try:
        # Find external URL
        external_url = await find_business_url(page, staging)

        if not external_url:
            # No URL found - schedule retry
            error_msg = "No external website URL found"
            logger.warning(f"[Process] {staging.name}: {error_msg}")
            update_staging_retry(staging.id, error_msg)
            return False

        # Upsert to companies table (dedup by domain)
        success = upsert_to_companies_by_domain(staging, external_url)

        if success:
            # Successfully processed - delete from staging
            logger.info(f"[Success] {staging.name}: processed and saved to companies table")
            delete_from_staging(staging.id)
            return True
        else:
            # Failed to save - schedule retry
            error_msg = "Failed to save to companies table"
            logger.error(f"[Process] {staging.name}: {error_msg}")
            update_staging_retry(staging.id, error_msg)
            return False

    except Exception as e:
        # Unexpected error - schedule retry
        error_msg = f"Processing error: {str(e)}"
        logger.error(f"[Process] {staging.name}: {error_msg}", exc_info=True)
        update_staging_retry(staging.id, error_msg)
        return False


async def worker_loop():
    """
    Main worker loop: continuously poll staging table and process records.

    Workflow:
    1. Check queue size
    2. If < MIN_BATCH_SIZE, wait
    3. If >= MIN_BATCH_SIZE, process one record at a time
    4. Sleep between polls
    """
    global shutdown_requested

    logger.info("=" * 60)
    logger.info("URL Finder Worker - Phase 2 Pipeline")
    logger.info("=" * 60)
    logger.info(f"Configuration:")
    logger.info(f"  Poll interval: {POLL_INTERVAL_SECONDS}s")
    logger.info(f"  Min batch size: {MIN_BATCH_SIZE}")
    logger.info(f"  Max retries: {MAX_RETRY_COUNT}")
    logger.info(f"  Retry delays: {RETRY_DELAYS} hours")
    logger.info(f"  Search delay: {MIN_SEARCH_DELAY}-{MAX_SEARCH_DELAY}s")
    logger.info("=" * 60)

    poll_count = 0

    async with async_playwright() as p:
        # Launch browser (reuse for entire worker session)
        browser = await p.chromium.launch(headless=True)

        try:
            # Random user agent
            user_agent = random.choice(USER_AGENTS)
            context = await browser.new_context(user_agent=user_agent)
            page = await context.new_page()

            while not shutdown_requested:
                poll_count += 1

                try:
                    # Get queue size
                    queue_size = get_staging_queue_size()

                    logger.info(f"[Poll {poll_count}] Queue size: {queue_size} pending")

                    if queue_size < MIN_BATCH_SIZE:
                        logger.info(
                            f"[Wait] Queue size ({queue_size}) below minimum ({MIN_BATCH_SIZE}), "
                            f"waiting {POLL_INTERVAL_SECONDS}s..."
                        )
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue

                    # Get one record to process
                    records = get_pending_staging_records(limit=1)

                    if not records:
                        logger.info(f"[Wait] No records ready for processing, waiting {POLL_INTERVAL_SECONDS}s...")
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue

                    # Process the record
                    staging = records[0]
                    success = await process_one_staging_record(page, staging)

                    if success:
                        logger.info(f"[Done] Successfully processed {staging.name}")
                    else:
                        logger.warning(f"[Done] Failed to process {staging.name} (will retry later)")

                    # Random delay between searches (rate limiting)
                    delay = random.uniform(MIN_SEARCH_DELAY, MAX_SEARCH_DELAY)
                    logger.debug(f"[Sleep] {delay:.1f}s before next search")
                    await asyncio.sleep(delay)

                except Exception as e:
                    logger.error(f"Error in worker loop: {e}", exc_info=True)
                    logger.info(f"[Recover] Waiting {POLL_INTERVAL_SECONDS}s before retry...")
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

        finally:
            await page.close()
            await context.close()
            await browser.close()

    logger.info("=" * 60)
    logger.info("Worker shutdown complete")
    logger.info("=" * 60)


def main():
    """CLI entry point."""
    logger.info("Starting URL Finder Worker...")

    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
