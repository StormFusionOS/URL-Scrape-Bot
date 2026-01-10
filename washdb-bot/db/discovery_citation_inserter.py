"""
Discovery Citation Inserter - Save no-website directory listings.

This module handles inserting business listings from directories (Google Maps, YP, Yelp)
that don't have websites, saving them as "discovery citations" that can be used for:
- NAP (Name, Address, Phone) validation
- Citation completeness tracking
- Matching to existing companies in the database

Usage:
    from db.discovery_citation_inserter import save_discovery_citation

    # Save a no-website listing from Google Maps
    save_discovery_citation(
        source='google_maps',
        business_data={
            'name': 'ABC Cleaning',
            'phone': '401-555-1234',
            'address': '123 Main St, Providence, RI 02903',
            'place_id': 'ChIJ...',
            'rating': 4.5,
            'reviews_count': 42,
            ...
        },
        session=db_session
    )
"""

import re
from datetime import datetime
from typing import Optional, Dict

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import DiscoveryCitation, Company
from runner.logging_setup import get_logger

logger = get_logger("discovery_citation_inserter")


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """
    Normalize phone number to digits only for matching.

    Args:
        phone: Phone number in any format

    Returns:
        10-digit phone string or None
    """
    if not phone:
        return None

    # Extract digits only
    digits = re.sub(r'\D', '', phone)

    # Handle US numbers
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]

    # Return 10-digit number or None
    return digits if len(digits) == 10 else None


def try_match_to_company(
    business_data: Dict,
    session: Session
) -> Optional[tuple[int, float, str]]:
    """
    Try to match a discovery citation to an existing company.

    Matching priority:
    1. Phone number (highest confidence)
    2. Address match (medium confidence)
    3. Name fuzzy match (lower confidence) - future improvement

    Args:
        business_data: Business information dictionary
        session: SQLAlchemy session

    Returns:
        Tuple of (company_id, confidence, method) or None if no match
    """
    # Try phone match first
    phone = normalize_phone(business_data.get('phone'))
    if phone:
        # Search by normalized phone
        company = (
            session.query(Company)
            .filter(Company.phone.isnot(None))
            .all()
        )
        for c in company:
            normalized = normalize_phone(c.phone)
            if normalized == phone:
                logger.debug(f"Phone match found: {business_data.get('name')} -> Company {c.id}")
                return (c.id, 0.95, 'phone')

    # Could add address matching here in future
    # Could add fuzzy name matching here in future

    return None


def save_discovery_citation(
    source: str,
    business_data: Dict,
    session: Session,
    try_match: bool = True
) -> Optional[int]:
    """
    Save a no-website business listing as a discovery citation.

    Args:
        source: Directory source ('google_maps', 'yellowpages', 'yelp')
        business_data: Business information dictionary with keys:
            - name (required)
            - phone
            - address
            - city, state, zip
            - place_id (Google)
            - profile_url
            - category
            - rating
            - reviews_count
            - hours
            - price_range
        session: SQLAlchemy session
        try_match: Whether to try matching to existing companies

    Returns:
        DiscoveryCitation ID if saved, None on error
    """
    try:
        name = business_data.get('name')
        if not name:
            logger.warning("Cannot save citation without name")
            return None

        # Check for duplicate by place_id or phone
        place_id = business_data.get('place_id')
        phone = business_data.get('phone')

        if place_id:
            existing = (
                session.query(DiscoveryCitation)
                .filter(
                    DiscoveryCitation.source == source,
                    DiscoveryCitation.place_id == place_id
                )
                .first()
            )
            if existing:
                logger.debug(f"Citation already exists: {name} (place_id={place_id})")
                return existing.id

        # Try to match to existing company
        match_result = None
        if try_match:
            match_result = try_match_to_company(business_data, session)

        # Create citation record
        citation = DiscoveryCitation(
            source=source,
            business_name=name,
            phone=phone,
            address=business_data.get('address'),
            city=business_data.get('city'),
            state=business_data.get('state'),
            zip=business_data.get('zip_code') or business_data.get('zip'),
            place_id=place_id,
            profile_url=business_data.get('profile_url') or business_data.get('url'),
            category=business_data.get('category'),
            rating=business_data.get('rating'),
            reviews_count=business_data.get('reviews_count'),
            hours=business_data.get('hours'),
            price_range=business_data.get('price_range'),
        )

        # Add match info if found
        if match_result:
            citation.matched_company_id = match_result[0]
            citation.match_confidence = match_result[1]
            citation.match_method = match_result[2]
            citation.matched_at = datetime.utcnow()
            logger.info(f"Matched citation '{name}' to company {match_result[0]} via {match_result[2]}")

        session.add(citation)
        session.commit()

        logger.debug(f"Saved discovery citation: {name} (ID: {citation.id}, matched: {match_result is not None})")
        return citation.id

    except Exception as e:
        logger.error(f"Failed to save discovery citation: {e}")
        session.rollback()
        return None


def backfill_citation_matches(session: Session, limit: int = 100) -> int:
    """
    Attempt to match unmatched citations to companies.

    Runs periodically to match newly added citations to companies
    that may have been added after the citation was discovered.

    Args:
        session: SQLAlchemy session
        limit: Maximum citations to process

    Returns:
        Number of citations matched
    """
    matched_count = 0

    try:
        # Get unmatched citations
        unmatched = (
            session.query(DiscoveryCitation)
            .filter(DiscoveryCitation.matched_company_id.is_(None))
            .limit(limit)
            .all()
        )

        for citation in unmatched:
            business_data = {
                'name': citation.business_name,
                'phone': citation.phone,
                'address': citation.address,
                'city': citation.city,
                'state': citation.state,
            }

            match_result = try_match_to_company(business_data, session)
            if match_result:
                citation.matched_company_id = match_result[0]
                citation.match_confidence = match_result[1]
                citation.match_method = match_result[2]
                citation.matched_at = datetime.utcnow()
                matched_count += 1

        if matched_count > 0:
            session.commit()
            logger.info(f"Backfill matched {matched_count} citations to companies")

    except Exception as e:
        logger.error(f"Error during citation backfill: {e}")
        session.rollback()

    return matched_count
