"""
Save HomeAdvisor businesses to staging table (Phase 1 of pipeline).

This module provides functions for saving businesses discovered from HomeAdvisor
to the ha_staging table, where they wait for URL finding (Phase 2).
"""
import os
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Base, HAStaging
from db.save_discoveries import normalize_phone
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

# Initialize logger
logger = get_logger("save_to_staging")


def create_session() -> Session:
    """
    Create a database session.

    Returns:
        SQLAlchemy Session instance

    Raises:
        RuntimeError: If DATABASE_URL is not set
    """
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL not set in environment")

    engine = create_engine(database_url, echo=False)
    return Session(engine)


def save_to_staging(businesses: list[dict]) -> tuple[int, int]:
    """
    Save HomeAdvisor businesses to staging table.

    Args:
        businesses: List of business dicts with keys:
            - name, address, phone, profile_url, rating_ha, reviews_ha

    Returns:
        Tuple of (inserted_count, skipped_count)

    Raises:
        Exception: If database operation fails
    """
    if not businesses:
        logger.info("No businesses to save to staging")
        return (0, 0)

    logger.info(f"Saving {len(businesses)} businesses to staging table...")

    inserted = 0
    skipped = 0

    session = create_session()

    try:
        for business in businesses:
            try:
                # Ensure profile_url is present (required field)
                if not business.get("profile_url"):
                    logger.warning(f"Skipping business without profile_url: {business.get('name')}")
                    skipped += 1
                    continue

                # Normalize phone
                phone = normalize_phone(business.get("phone"))

                # Create staging record
                staging_record = HAStaging(
                    name=business.get("name"),
                    address=business.get("address"),
                    phone=phone,
                    profile_url=business["profile_url"],
                    rating_ha=business.get("rating_ha"),
                    reviews_ha=business.get("reviews_ha"),
                    processed=False,
                    retry_count=0,
                    next_retry_at=None,
                    last_error=None
                )

                session.add(staging_record)
                logger.debug(f"Added to staging: {business.get('name')}")
                inserted += 1

            except Exception as e:
                # Check if it's a duplicate profile_url (unique constraint violation)
                if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                    logger.debug(
                        f"Duplicate profile_url (already in staging): {business.get('profile_url')}"
                    )
                    skipped += 1
                    # Rollback this transaction and continue
                    session.rollback()
                    continue
                else:
                    logger.error(
                        f"Error saving to staging {business.get('name', 'Unknown')}: {e}"
                    )
                    skipped += 1
                    session.rollback()
                    continue

        # Commit all successful inserts
        session.commit()
        logger.info(
            f"Staging save complete: {inserted} inserted, {skipped} skipped"
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Database error during staging save: {e}", exc_info=True)
        raise

    finally:
        session.close()

    return (inserted, skipped)


def get_staging_stats() -> dict:
    """
    Get statistics about the staging table.

    Returns:
        Dict with keys: total, pending, in_retry, failed (retry_count >= 3)
    """
    session = create_session()

    try:
        from sqlalchemy import func

        total = session.query(func.count(HAStaging.id)).scalar()

        pending = session.query(func.count(HAStaging.id)).filter(
            HAStaging.processed == False,
            HAStaging.retry_count == 0
        ).scalar()

        in_retry = session.query(func.count(HAStaging.id)).filter(
            HAStaging.processed == False,
            HAStaging.retry_count > 0,
            HAStaging.retry_count < 3
        ).scalar()

        failed = session.query(func.count(HAStaging.id)).filter(
            HAStaging.retry_count >= 3
        ).scalar()

        return {
            "total": total or 0,
            "pending": pending or 0,
            "in_retry": in_retry or 0,
            "failed": failed or 0
        }

    finally:
        session.close()


def clear_staging_table():
    """
    Clear all records from staging table (for testing/debugging).

    WARNING: This deletes all records! Use with caution.
    """
    session = create_session()

    try:
        deleted = session.query(HAStaging).delete()
        session.commit()
        logger.info(f"Cleared {deleted} records from staging table")
        return deleted

    finally:
        session.close()


def main():
    """Demo: Save sample businesses to staging."""
    logger.info("=" * 60)
    logger.info("Save to Staging Demo")
    logger.info("=" * 60)
    logger.info("")

    # Sample businesses
    businesses = [
        {
            "name": "ABC Pressure Washing",
            "address": "123 Main St, Austin, TX 78701",
            "phone": "(555) 123-4567",
            "profile_url": "https://www.homeadvisor.com/rated.ABCPressureWashing.12345.html",
            "rating_ha": 4.5,
            "reviews_ha": 42,
        },
        {
            "name": "XYZ Power Wash",
            "address": "456 Oak Ave, Dallas, TX 75201",
            "phone": "555.987.6543",
            "profile_url": "https://www.homeadvisor.com/rated.XYZPowerWash.67890.html",
            "rating_ha": 4.8,
            "reviews_ha": 128,
        },
    ]

    logger.info(f"Saving {len(businesses)} sample businesses to staging...")
    logger.info("")

    try:
        inserted, skipped = save_to_staging(businesses)

        logger.info("")
        logger.info("=" * 60)
        logger.info("Results:")
        logger.info(f"  Inserted: {inserted}")
        logger.info(f"  Skipped:  {skipped}")
        logger.info("=" * 60)

        # Get stats
        logger.info("")
        logger.info("Staging Table Stats:")
        stats = get_staging_stats()
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Demo failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
