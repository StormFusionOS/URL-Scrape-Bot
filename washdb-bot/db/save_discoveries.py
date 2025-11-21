"""
Database save operations for discovered companies.

This module provides:
- Upserting discovered companies to the database
- Data normalization (phone, email)
- Conflict resolution on canonical website URLs
"""

import os
import re
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Base, Company, BusinessSource, canonicalize_url, domain_from_url
from runner.logging_setup import get_logger


# Load environment
load_dotenv()

# Initialize logger
logger = get_logger("save_discoveries")


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """
    Normalize phone number by removing non-digit characters.

    Args:
        phone: Raw phone number string

    Returns:
        Normalized phone string with digits, spaces, and common separators,
        or None if invalid

    Examples:
        >>> normalize_phone("(555) 123-4567")
        '555-123-4567'
        >>> normalize_phone("555.123.4567 ext. 123")
        '555-123-4567 ext. 123'
    """
    if not phone:
        return None

    # Remove leading/trailing whitespace
    phone = phone.strip()

    if not phone:
        return None

    # Extract digits
    digits = re.sub(r'[^\d]', '', phone)

    # Require at least 10 digits (US phone number)
    if len(digits) < 10:
        return None

    # Format as XXX-XXX-XXXX (for 10 digits)
    if len(digits) == 10:
        formatted = f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    elif len(digits) == 11 and digits[0] == '1':
        # US number with country code
        formatted = f"{digits[1:4]}-{digits[4:7]}-{digits[7:11]}"
    else:
        # Just use the digits as-is for international or other formats
        formatted = digits

    # Check for extension
    ext_match = re.search(r'(?:ext|extension|x)[:\s]*(\d+)', phone, re.IGNORECASE)
    if ext_match:
        formatted += f" ext. {ext_match.group(1)}"

    return formatted


def normalize_email(email: Optional[str]) -> Optional[str]:
    """
    Normalize email address by converting to lowercase and stripping whitespace.

    Args:
        email: Raw email string

    Returns:
        Normalized email string or None if invalid

    Examples:
        >>> normalize_email("  John.Doe@Example.COM  ")
        'john.doe@example.com'
    """
    if not email:
        return None

    email = email.strip().lower()

    # Basic email validation
    if not re.match(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$', email):
        return None

    return email


def calculate_data_quality_score(
    name: Optional[str],
    phone: Optional[str],
    street: Optional[str],
    city: Optional[str],
    state: Optional[str],
    zip_code: Optional[str],
    website: Optional[str],
    is_verified: bool,
    rating_count: Optional[int]
) -> int:
    """
    Calculate data quality score (0-100) based on completeness and verification.

    Scoring:
    - Base NAP completeness: 60 points max (name=15, phone=15, street=10, city=10, state=5, zip=5)
    - Additional data: 20 points max (website=10, rating_count=10)
    - Verification bonus: 20 points

    Args:
        name: Business name
        phone: Phone number
        street: Street address
        city: City
        state: State
        zip_code: ZIP code
        website: Website URL
        is_verified: Whether listing is owner-verified
        rating_count: Number of reviews

    Returns:
        Quality score from 0-100
    """
    score = 0

    # Base NAP completeness (60 points max)
    if name and len(name) > 0:
        score += 15
    if phone and len(phone) > 0:
        score += 15
    if street and len(street) > 0:
        score += 10
    if city and len(city) > 0:
        score += 10
    if state and len(state) > 0:
        score += 5
    if zip_code and len(zip_code) > 0:
        score += 5

    # Additional data (20 points max)
    if website and len(website) > 0:
        score += 10
    if rating_count is not None and rating_count > 0:
        score += 10

    # Verification bonus (20 points)
    if is_verified:
        score += 20

    return score


def parse_address_components(address: Optional[str]) -> dict:
    """
    Parse address string into components (street, city, state, zip).

    This is a basic implementation that handles common US address formats.
    For production, consider using a library like usaddress or geopy.

    Args:
        address: Full address string (e.g., "123 Main St, Austin, TX 78701")

    Returns:
        Dict with keys: street, city, state, zip_code
    """
    if not address:
        return {"street": None, "city": None, "state": None, "zip_code": None}

    # Simple regex-based parsing for US addresses
    # Format: "Street, City, ST ZIP"
    components = {"street": None, "city": None, "state": None, "zip_code": None}

    # Split by comma
    parts = [p.strip() for p in address.split(",")]

    if len(parts) >= 1:
        components["street"] = parts[0]

    if len(parts) >= 2:
        components["city"] = parts[1]

    if len(parts) >= 3:
        # Last part should be "ST ZIP"
        last_part = parts[2].strip()
        # Extract state (2-letter code) and ZIP
        match = re.match(r'^([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$', last_part)
        if match:
            components["state"] = match.group(1)
            components["zip_code"] = match.group(2)
        else:
            # Try other formats
            tokens = last_part.split()
            if len(tokens) >= 2:
                components["state"] = tokens[0]
                components["zip_code"] = tokens[1]
            elif len(tokens) == 1:
                # Could be just state or just zip
                if tokens[0].isdigit():
                    components["zip_code"] = tokens[0]
                else:
                    components["state"] = tokens[0]

    return components


def create_business_source_from_yp(
    session: Session,
    company_id: int,
    company_data: dict,
    phone_normalized: Optional[str]
) -> None:
    """
    Create a BusinessSource record from YP scraper data.

    Args:
        session: Database session
        company_id: ID of the Company record
        company_data: Dict with YP data (name, address, phone, website, ratings, etc.)
        phone_normalized: Normalized phone number
    """
    # Parse address into components
    address_components = parse_address_components(company_data.get("address"))

    # Extract rating data
    rating_value = company_data.get("rating_yp")
    rating_count = company_data.get("reviews_yp")

    # Calculate quality score
    quality_score = calculate_data_quality_score(
        name=company_data.get("name"),
        phone=phone_normalized,
        street=address_components["street"],
        city=address_components["city"],
        state=address_components["state"],
        zip_code=address_components["zip_code"],
        website=company_data.get("website"),
        is_verified=False,  # YP doesn't provide verification status
        rating_count=rating_count
    )

    # Determine confidence level based on quality score
    if quality_score >= 80:
        confidence = "high"
    elif quality_score >= 50:
        confidence = "medium"
    else:
        confidence = "low"

    # Build metadata from parse_metadata and other fields
    metadata = {}
    if company_data.get("profile_url"):
        metadata["profile_url"] = company_data["profile_url"]
    if company_data.get("category_tags"):
        metadata["category_tags"] = company_data["category_tags"]
    if company_data.get("is_sponsored") is not None:
        metadata["is_sponsored"] = company_data["is_sponsored"]
    if company_data.get("filter_score") is not None:
        metadata["filter_score"] = company_data["filter_score"]
    if company_data.get("filter_reason"):
        metadata["filter_reason"] = company_data["filter_reason"]
    if company_data.get("source_page_url"):
        metadata["source_page_url"] = company_data["source_page_url"]
    if company_data.get("services"):
        metadata["services"] = company_data["services"]
    if company_data.get("service_area"):
        metadata["service_area"] = company_data["service_area"]

    # Check if BusinessSource already exists for this company + source_type
    existing_bs = session.execute(
        select(BusinessSource).where(
            BusinessSource.company_id == company_id,
            BusinessSource.source_type == "yp"
        )
    ).scalar_one_or_none()

    if existing_bs:
        # Update existing BusinessSource
        existing_bs.source_name = "Yellow Pages"
        existing_bs.profile_url = company_data.get("profile_url")
        existing_bs.name = company_data.get("name")
        existing_bs.phone = company_data.get("phone")
        existing_bs.phone_e164 = None  # TODO: Implement E.164 normalization
        existing_bs.address_raw = company_data.get("address")
        existing_bs.street = address_components["street"]
        existing_bs.city = address_components["city"]
        existing_bs.state = address_components["state"]
        existing_bs.zip_code = address_components["zip_code"]
        existing_bs.website = company_data.get("website")
        existing_bs.categories = company_data.get("category_tags")  # PostgreSQL ARRAY
        existing_bs.rating_value = rating_value
        existing_bs.rating_count = rating_count
        existing_bs.is_verified = False
        existing_bs.listing_status = "found"
        existing_bs.data_quality_score = quality_score
        existing_bs.confidence_level = confidence
        existing_bs.metadata = metadata if metadata else None

        logger.debug(f"Updated BusinessSource for company_id={company_id}, source=yp")
    else:
        # Create new BusinessSource record
        business_source = BusinessSource(
            company_id=company_id,
            source_type="yp",
            source_name="Yellow Pages",
            source_url="https://www.yellowpages.com",
            profile_url=company_data.get("profile_url"),
            name=company_data.get("name"),
            phone=company_data.get("phone"),
            phone_e164=None,  # TODO: Implement E.164 normalization using phonenumbers library
            address_raw=company_data.get("address"),
            street=address_components["street"],
            city=address_components["city"],
            state=address_components["state"],
            zip_code=address_components["zip_code"],
            website=company_data.get("website"),
            categories=company_data.get("category_tags"),  # PostgreSQL ARRAY
            rating_value=rating_value,
            rating_count=rating_count,
            is_verified=False,  # YP doesn't provide verification status
            listing_status="found",
            data_quality_score=quality_score,
            confidence_level=confidence,
            metadata=metadata if metadata else None
        )

        session.add(business_source)
        logger.debug(f"Created BusinessSource for company_id={company_id}, source=yp, quality={quality_score}")


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


def upsert_discovered(companies: list[dict]) -> tuple[int, int, int]:
    """
    Upsert discovered companies to the database.

    For each company:
    - If website doesn't exist: INSERT new record
    - If website exists: UPDATE existing record (only non-null fields)
    - Always set active=True

    Args:
        companies: List of company dicts with keys:
            - name, website, domain, phone, email, address, services,
              service_area, source, rating_yp, reviews_yp, etc.

    Returns:
        Tuple of (inserted_count, skipped_count, updated_count)

    Raises:
        Exception: If database operation fails
    """
    if not companies:
        logger.info("No companies to upsert")
        return (0, 0, 0)

    logger.info(f"Upserting {len(companies)} companies...")

    inserted = 0
    updated = 0
    skipped = 0

    session = create_session()

    try:
        for company_data in companies:
            try:
                # Ensure website is canonical and domain is present
                if not company_data.get("website"):
                    logger.warning(f"Skipping company without website: {company_data.get('name')}")
                    skipped += 1
                    continue

                # Normalize URL and domain
                canonical_website = canonicalize_url(company_data["website"])
                domain = domain_from_url(canonical_website)

                # Normalize phone and email
                phone = normalize_phone(company_data.get("phone"))
                email = normalize_email(company_data.get("email"))

                # Build parse_metadata JSON for traceability
                parse_metadata = {}
                if company_data.get("profile_url"):
                    parse_metadata["profile_url"] = company_data["profile_url"]
                if company_data.get("category_tags"):
                    parse_metadata["category_tags"] = company_data["category_tags"]
                if company_data.get("is_sponsored") is not None:
                    parse_metadata["is_sponsored"] = company_data["is_sponsored"]
                if company_data.get("filter_score") is not None:
                    parse_metadata["filter_score"] = company_data["filter_score"]
                if company_data.get("filter_reason"):
                    parse_metadata["filter_reason"] = company_data["filter_reason"]
                if company_data.get("source_page_url"):
                    parse_metadata["source_page_url"] = company_data["source_page_url"]

                # Check if company already exists by canonical website
                stmt = select(Company).where(Company.website == canonical_website)
                existing = session.execute(stmt).scalar_one_or_none()

                if existing:
                    # Update existing record (only non-null fields)
                    updated_fields = []

                    if company_data.get("name"):
                        existing.name = company_data["name"]
                        updated_fields.append("name")

                    if phone:
                        existing.phone = phone
                        updated_fields.append("phone")

                    if email:
                        existing.email = email
                        updated_fields.append("email")

                    if company_data.get("address"):
                        existing.address = company_data["address"]
                        updated_fields.append("address")

                    if company_data.get("services"):
                        existing.services = company_data["services"]
                        updated_fields.append("services")

                    if company_data.get("service_area"):
                        existing.service_area = company_data["service_area"]
                        updated_fields.append("service_area")

                    if company_data.get("source"):
                        existing.source = company_data["source"]
                        updated_fields.append("source")

                    if company_data.get("rating_yp") is not None:
                        existing.rating_yp = company_data["rating_yp"]
                        updated_fields.append("rating_yp")

                    if company_data.get("reviews_yp") is not None:
                        existing.reviews_yp = company_data["reviews_yp"]
                        updated_fields.append("reviews_yp")

                    if company_data.get("rating_google") is not None:
                        existing.rating_google = company_data["rating_google"]
                        updated_fields.append("rating_google")

                    if company_data.get("reviews_google") is not None:
                        existing.reviews_google = company_data["reviews_google"]
                        updated_fields.append("reviews_google")

                    # Update parse_metadata (merge with existing if present)
                    if parse_metadata:
                        if existing.parse_metadata:
                            # Merge: new metadata takes precedence
                            existing.parse_metadata = {**existing.parse_metadata, **parse_metadata}
                        else:
                            existing.parse_metadata = parse_metadata
                        updated_fields.append("parse_metadata")

                    # Always set active=True
                    existing.active = True

                    if updated_fields:
                        logger.debug(
                            f"Updated {existing.domain}: {', '.join(updated_fields)}"
                        )
                        updated += 1
                    else:
                        logger.debug(f"No new data for {existing.domain}, skipping update")
                        skipped += 1

                    # Create/update BusinessSource record for YP data
                    if company_data.get("source") == "YP":
                        try:
                            create_business_source_from_yp(
                                session=session,
                                company_id=existing.id,
                                company_data=company_data,
                                phone_normalized=phone
                            )
                        except Exception as bs_error:
                            logger.warning(
                                f"Failed to create BusinessSource for {existing.domain}: {bs_error}"
                            )

                else:
                    # Insert new record
                    new_company = Company(
                        name=company_data.get("name"),
                        website=canonical_website,
                        domain=domain,
                        phone=phone,
                        email=email,
                        address=company_data.get("address"),
                        services=company_data.get("services"),
                        service_area=company_data.get("service_area"),
                        source=company_data.get("source"),
                        rating_yp=company_data.get("rating_yp"),
                        reviews_yp=company_data.get("reviews_yp"),
                        rating_google=company_data.get("rating_google"),
                        reviews_google=company_data.get("reviews_google"),
                        parse_metadata=parse_metadata if parse_metadata else None,
                        active=True,
                    )

                    session.add(new_company)
                    session.flush()  # Flush to get the new_company.id
                    logger.debug(f"Inserted new company: {domain}")
                    inserted += 1

                    # Create BusinessSource record for YP data
                    if company_data.get("source") == "YP":
                        try:
                            create_business_source_from_yp(
                                session=session,
                                company_id=new_company.id,
                                company_data=company_data,
                                phone_normalized=phone
                            )
                        except Exception as bs_error:
                            logger.warning(
                                f"Failed to create BusinessSource for {domain}: {bs_error}"
                            )

            except Exception as e:
                logger.error(
                    f"Error processing company {company_data.get('name', 'Unknown')}: {e}"
                )
                skipped += 1
                continue

        # Commit all changes
        session.commit()
        logger.info(
            f"Upsert complete: {inserted} inserted, {updated} updated, {skipped} skipped"
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Database error during upsert: {e}", exc_info=True)
        raise

    finally:
        session.close()

    return (inserted, skipped, updated)


def main():
    """Demo: Upsert sample companies."""
    logger.info("=" * 60)
    logger.info("Save Discoveries Demo")
    logger.info("=" * 60)
    logger.info("")

    # Sample companies
    companies = [
        {
            "name": "ABC Pressure Washing",
            "website": "https://www.abc-washing.com",
            "phone": "(555) 123-4567",
            "email": "Info@ABC-Washing.com",
            "address": "123 Main St, Austin, TX 78701",
            "source": "YP",
            "rating_yp": 4.5,
            "reviews_yp": 42,
        },
        {
            "name": "XYZ Power Wash",
            "website": "http://xyzpowerwash.com/",
            "phone": "555.987.6543 ext. 12",
            "address": "456 Oak Ave, Dallas, TX 75201",
            "source": "YP",
            "rating_yp": 4.8,
            "reviews_yp": 128,
        },
        {
            "name": "ABC Pressure Washing (Updated)",
            "website": "https://www.abc-washing.com",  # Same as first (will update)
            "phone": "(555) 123-4567",
            "rating_yp": 4.7,  # Updated rating
            "reviews_yp": 50,  # Updated review count
            "source": "YP",
        },
    ]

    logger.info(f"Upserting {len(companies)} sample companies...")
    logger.info("")

    try:
        inserted, skipped, updated = upsert_discovered(companies)

        logger.info("")
        logger.info("=" * 60)
        logger.info("Results:")
        logger.info(f"  Inserted: {inserted}")
        logger.info(f"  Updated:  {updated}")
        logger.info(f"  Skipped:  {skipped}")
        logger.info("=" * 60)

        # Query and display results
        logger.info("")
        logger.info("Companies in database:")
        logger.info("")

        session = create_session()
        try:
            stmt = select(Company).order_by(Company.id)
            results = session.execute(stmt).scalars().all()

            for company in results:
                logger.info(f"  {company.id}. {company.name}")
                logger.info(f"     Domain: {company.domain}")
                logger.info(f"     Website: {company.website}")
                if company.phone:
                    logger.info(f"     Phone: {company.phone}")
                if company.rating_yp:
                    logger.info(
                        f"     Rating: {company.rating_yp} ({company.reviews_yp} reviews)"
                    )
                logger.info(f"     Active: {company.active}")
                logger.info("")

        finally:
            session.close()

    except Exception as e:
        logger.error(f"Demo failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
