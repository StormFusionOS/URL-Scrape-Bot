#!/usr/bin/env python3
"""
Update company details from websites.

This module provides:
- Updating individual companies by scraping their websites
- Batch updating companies based on criteria
- Enriching existing records with fresh data
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, or_, and_

from db.models import Company
from db.save_discoveries import create_session, normalize_phone, normalize_email
from runner.logging_setup import get_logger
from scrape_site.site_scraper import scrape_website


# Initialize logger
logger = get_logger("update_details")


def update_company_details(website: str) -> dict:
    """
    Update a single company's details by scraping its website.

    Args:
        website: Canonical website URL

    Returns:
        Dict with summary:
        - updated: bool - Whether the company was updated
        - fields_updated: list - List of field names that were updated
        - error: str - Error message if any
    """
    logger.info(f"Updating company details for {website}")

    summary = {
        "updated": False,
        "fields_updated": [],
        "error": None,
    }

    session = create_session()

    try:
        # Fetch company by website
        stmt = select(Company).where(Company.website == website)
        company = session.execute(stmt).scalar_one_or_none()

        if not company:
            error_msg = f"Company not found with website: {website}"
            logger.warning(error_msg)
            summary["error"] = error_msg
            return summary

        logger.debug(f"Found company: {company.name} (ID: {company.id})")

        # Scrape website
        try:
            site_data = scrape_website(website)
        except Exception as e:
            error_msg = f"Error scraping website: {e}"
            logger.error(error_msg, exc_info=True)
            summary["error"] = error_msg
            return summary

        # Update fields with new data (only if non-null)
        updated_fields = []

        # Name
        if site_data.get("name") and site_data["name"] != company.name:
            company.name = site_data["name"]
            updated_fields.append("name")

        # Phone
        if site_data.get("phones"):
            new_phone = normalize_phone(site_data["phones"][0])
            if new_phone and new_phone != company.phone:
                company.phone = new_phone
                updated_fields.append("phone")

        # Email
        if site_data.get("emails"):
            new_email = normalize_email(site_data["emails"][0])
            if new_email and new_email != company.email:
                company.email = new_email
                updated_fields.append("email")

        # Services
        if site_data.get("services") and site_data["services"] != company.services:
            company.services = site_data["services"]
            updated_fields.append("services")

        # Service Area
        if site_data.get("service_area") and site_data["service_area"] != company.service_area:
            company.service_area = site_data["service_area"]
            updated_fields.append("service_area")

        # Address
        if site_data.get("address") and site_data["address"] != company.address:
            company.address = site_data["address"]
            updated_fields.append("address")

        # Update timestamp if any fields were updated
        if updated_fields:
            company.last_updated = datetime.utcnow()
            session.commit()

            logger.info(f"Updated {company.name}: {', '.join(updated_fields)}")
            summary["updated"] = True
            summary["fields_updated"] = updated_fields
        else:
            logger.debug(f"No new data for {company.name}")
            summary["updated"] = False

    except Exception as e:
        session.rollback()
        error_msg = f"Database error: {e}"
        logger.error(error_msg, exc_info=True)
        summary["error"] = error_msg

    finally:
        session.close()

    return summary


def update_batch(
    limit: int = 100,
    stale_days: int = 30,
    only_missing_email: bool = False,
) -> dict:
    """
    Batch update companies by scraping their websites.

    Selects companies that:
    - Have never been updated (last_updated IS NULL), OR
    - Were last updated more than stale_days ago, OR
    - Are missing email (if only_missing_email=True)

    Args:
        limit: Maximum number of companies to update (default: 100)
        stale_days: Consider companies stale after this many days (default: 30)
        only_missing_email: Only update companies missing email (default: False)

    Returns:
        Dict with summary:
        - total_processed: int - Total companies processed
        - updated: int - Number successfully updated
        - skipped: int - Number skipped (no updates needed)
        - errors: int - Number of errors
        - fields_updated: dict - Count of each field type updated
    """
    logger.info("=" * 60)
    logger.info("Starting batch update")
    logger.info(f"  Limit: {limit}")
    logger.info(f"  Stale days: {stale_days}")
    logger.info(f"  Only missing email: {only_missing_email}")
    logger.info("=" * 60)

    summary = {
        "total_processed": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "fields_updated": {},
    }

    session = create_session()

    try:
        # Build query
        stale_date = datetime.utcnow() - timedelta(days=stale_days)

        # Base condition: has website
        conditions = [Company.website.isnot(None)]

        if only_missing_email:
            # Only companies missing email
            conditions.append(Company.email.is_(None))
        else:
            # Companies that are stale or never updated
            conditions.append(
                or_(
                    Company.last_updated.is_(None),
                    Company.last_updated < stale_date,
                )
            )

        stmt = (
            select(Company)
            .where(and_(*conditions))
            .limit(limit)
            .order_by(Company.last_updated.asc().nullsfirst())
        )

        companies = session.execute(stmt).scalars().all()

        logger.info(f"Found {len(companies)} companies to update")

        # Process each company
        for i, company in enumerate(companies, 1):
            logger.info(f"[{i}/{len(companies)}] Processing: {company.name} ({company.website})")

            try:
                # Update company details
                result = update_company_details(company.website)

                summary["total_processed"] += 1

                if result.get("error"):
                    summary["errors"] += 1
                    logger.warning(f"  ✗ Error: {result['error']}")

                elif result.get("updated"):
                    summary["updated"] += 1

                    # Track which fields were updated
                    for field in result.get("fields_updated", []):
                        summary["fields_updated"][field] = summary["fields_updated"].get(field, 0) + 1

                    logger.info(f"  ✓ Updated: {', '.join(result['fields_updated'])}")

                else:
                    summary["skipped"] += 1
                    logger.info(f"  - No updates needed")

            except Exception as e:
                summary["errors"] += 1
                logger.error(f"  ✗ Unexpected error: {e}", exc_info=True)
                continue

        # Print summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("Batch Update Summary")
        logger.info("=" * 60)
        logger.info(f"Total processed: {summary['total_processed']}")
        logger.info(f"Updated:         {summary['updated']}")
        logger.info(f"Skipped:         {summary['skipped']}")
        logger.info(f"Errors:          {summary['errors']}")

        if summary["fields_updated"]:
            logger.info("")
            logger.info("Fields updated:")
            for field, count in sorted(summary["fields_updated"].items()):
                logger.info(f"  {field}: {count}")

        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Batch update failed: {e}", exc_info=True)
        summary["errors"] += 1

    finally:
        session.close()

    return summary


def main():
    """Demo: Update batch of companies."""
    logger.info("=" * 60)
    logger.info("Update Details Demo")
    logger.info("=" * 60)
    logger.info("")

    # Demo 1: Update single company
    logger.info("Demo 1: Update single company")
    logger.info("")

    # This would need a real website from the database
    # result = update_company_details("https://example.com")
    # logger.info(f"Result: {result}")

    logger.info("(Skipped - requires existing database record)")
    logger.info("")

    # Demo 2: Batch update
    logger.info("Demo 2: Batch update companies")
    logger.info("")

    # Update up to 10 companies, focusing on those missing email
    summary = update_batch(
        limit=10,
        stale_days=30,
        only_missing_email=True,
    )

    logger.info("")
    logger.info("Batch update complete!")


if __name__ == "__main__":
    main()
