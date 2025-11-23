#!/usr/bin/env python3
"""
Batch verification job for company URLs.

This script:
1. Fetches companies from the database that need verification
2. Scrapes their websites to get content
3. Runs service verification logic
4. Stores results in parse_metadata['verification']
5. Updates active flag based on combined score

Usage:
    python db/verify_company_urls.py [--max-companies N] [--force-reverify]

Options:
    --max-companies N       Limit number of companies to verify (default: all)
    --force-reverify        Re-verify companies even if already verified
    --min-score SCORE       Minimum score threshold for auto-accept (default: 0.75)
    --max-score SCORE       Maximum score threshold for auto-reject (default: 0.35)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger
from scrape_site.site_scraper import fetch_page, discover_internal_links, scrape_website
from scrape_site.site_parse import parse_site_content
from scrape_site.service_verifier import create_verifier

load_dotenv()

logger = get_logger("batch_verification")


def get_companies_to_verify(
    session,
    max_companies: Optional[int] = None,
    force_reverify: bool = False
) -> List[Dict]:
    """
    Get companies that need verification.

    Args:
        session: SQLAlchemy session
        max_companies: Maximum companies to fetch
        force_reverify: If True, include already verified companies

    Returns:
        List of company dicts
    """
    logger.info("Fetching companies for verification...")

    # Build query
    query = """
    SELECT
        id,
        name,
        website,
        domain,
        phone,
        email,
        services,
        service_area,
        address,
        source,
        rating_yp,
        rating_google,
        reviews_yp,
        reviews_google,
        parse_metadata,
        active,
        created_at,
        last_updated
    FROM companies
    WHERE website IS NOT NULL
    """

    # Only select unverified companies unless force_reverify
    if not force_reverify:
        query += " AND (parse_metadata->'verification' IS NULL OR parse_metadata->'verification'->>'status' IS NULL)"

    query += " ORDER BY created_at DESC"

    if max_companies:
        query += f" LIMIT {max_companies}"

    result = session.execute(text(query))

    companies = []
    for row in result:
        companies.append({
            'id': row.id,
            'name': row.name,
            'website': row.website,
            'domain': row.domain,
            'phone': row.phone,
            'email': row.email,
            'services': row.services,
            'service_area': row.service_area,
            'address': row.address,
            'source': row.source,
            'rating_yp': row.rating_yp,
            'rating_google': row.rating_google,
            'reviews_yp': row.reviews_yp,
            'reviews_google': row.reviews_google,
            'parse_metadata': row.parse_metadata or {},
            'active': row.active,
            'created_at': row.created_at,
            'last_updated': row.last_updated
        })

    logger.info(f"Found {len(companies)} companies to verify")
    return companies


def verify_company_website(company: Dict, verifier) -> Optional[Dict]:
    """
    Verify a single company's website.

    Args:
        company: Company data dict
        verifier: ServiceVerifier instance

    Returns:
        Verification result dict or None on error
    """
    website = company.get('website')
    if not website:
        return None

    logger.info(f"Verifying: {company['name']} ({website})")

    try:
        # Fetch homepage
        html = fetch_page(website, delay=2.0)
        if not html:
            logger.warning(f"Failed to fetch website: {website}")
            return {
                'status': 'failed',
                'score': 0.0,
                'reason': 'Failed to fetch website',
                'negative_signals': ['Website unreachable'],
                'positive_signals': [],
                'services_detected': {},
                'tier': 'D'
            }

        # Parse website content
        metadata = parse_site_content(html, website)

        # Discover internal pages (optional - for deeper analysis)
        # For now, just use homepage content

        # Run verification
        verification_result = verifier.verify_company(
            company_data=company,
            website_html=html,
            website_metadata=metadata
        )

        logger.info(
            f"Verified {company['name']}: "
            f"Status={verification_result['status']}, "
            f"Score={verification_result['score']:.2f}, "
            f"Tier={verification_result['tier']}"
        )

        return verification_result

    except Exception as e:
        logger.error(f"Error verifying {company['name']}: {e}")
        return {
            'status': 'failed',
            'score': 0.0,
            'reason': f'Verification error: {str(e)}',
            'negative_signals': [f'Error: {str(e)}'],
            'positive_signals': [],
            'services_detected': {},
            'tier': 'D'
        }


def calculate_combined_score(company: Dict, verification_result: Dict) -> float:
    """
    Calculate combined score using discovery signals + website verification.

    Formula (when discovery score available):
        combined_score = 0.4 * discovery_conf + 0.4 * web_conf + 0.2 * review_score

    Formula (when no discovery score):
        combined_score = 0.7 * web_conf + 0.3 * review_score
    """
    parse_metadata = company.get('parse_metadata', {})

    # Get discovery filter confidences
    google_conf = parse_metadata.get('google_filter', {}).get('confidence', 0.0)
    yp_conf = parse_metadata.get('yp_filter', {}).get('confidence', 0.0)

    # Website verification score
    web_conf = verification_result.get('score', 0.0)

    # Review count (log-scaled)
    import math
    reviews_total = (company.get('reviews_google', 0) or 0) + (company.get('reviews_yp', 0) or 0)
    review_score = min(math.log1p(reviews_total) / 5.0, 1.0)  # Normalize to 0-1

    # Weighted combination
    # Use whichever discovery signal is available (prefer Google > YP)
    discovery_conf = google_conf if google_conf > 0 else yp_conf

    if discovery_conf > 0:
        # Standard formula: discovery + website + reviews
        combined_score = (
            0.4 * discovery_conf +
            0.4 * web_conf +
            0.2 * review_score
        )
    else:
        # No discovery score available, rely more heavily on website verification
        combined_score = (
            0.7 * web_conf +
            0.3 * review_score
        )

    return combined_score


def update_company_verification(
    session,
    company_id: int,
    verification_result: Dict,
    combined_score: float,
    min_score: float = 0.75,
    max_score: float = 0.35
):
    """
    Update company record with verification results.

    Args:
        session: SQLAlchemy session
        company_id: Company ID
        verification_result: Verification result dict
        combined_score: Combined score (discovery + website + reviews)
        min_score: Minimum score for auto-accept
        max_score: Maximum score for auto-reject
    """
    # Determine active flag based on combined score
    if combined_score >= min_score:
        active = True
        verification_result['status'] = 'passed'
        verification_result['needs_review'] = False
    elif combined_score <= max_score:
        active = False
        verification_result['status'] = 'failed'
        verification_result['needs_review'] = False
    else:
        # Keep current active status, but flag for review
        active = None  # Don't change
        verification_result['status'] = 'unknown'
        verification_result['needs_review'] = True

    # Add combined score to result
    verification_result['combined_score'] = combined_score
    verification_result['verified_at'] = datetime.now().isoformat()

    # Build update query
    # Properly serialize verification result to JSON
    verification_json = json.dumps(verification_result)

    if active is not None:
        query = text("""
        UPDATE companies
        SET
            parse_metadata = jsonb_set(
                COALESCE(parse_metadata, '{}'::jsonb),
                '{verification}',
                CAST(:verification_json AS jsonb)
            ),
            active = :active,
            last_updated = NOW()
        WHERE id = :company_id
        """)

        session.execute(query, {
            'company_id': company_id,
            'verification_json': verification_json,
            'active': active
        })
    else:
        # Don't update active flag
        query = text("""
        UPDATE companies
        SET
            parse_metadata = jsonb_set(
                COALESCE(parse_metadata, '{}'::jsonb),
                '{verification}',
                CAST(:verification_json AS jsonb)
            ),
            last_updated = NOW()
        WHERE id = :company_id
        """)

        session.execute(query, {
            'company_id': company_id,
            'verification_json': verification_json
        })

    session.commit()


def main():
    """Main batch verification job."""
    parser = argparse.ArgumentParser(description='Batch verification job for company URLs')
    parser.add_argument('--max-companies', type=int, default=None, help='Maximum companies to verify')
    parser.add_argument('--force-reverify', action='store_true', help='Re-verify already verified companies')
    parser.add_argument('--min-score', type=float, default=0.75, help='Min score for auto-accept (default: 0.75)')
    parser.add_argument('--max-score', type=float, default=0.35, help='Max score for auto-reject (default: 0.35)')

    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("BATCH VERIFICATION JOB STARTED")
    logger.info("=" * 70)
    logger.info(f"Max companies: {args.max_companies or 'all'}")
    logger.info(f"Force reverify: {args.force_reverify}")
    logger.info(f"Min score (auto-accept): {args.min_score}")
    logger.info(f"Max score (auto-reject): {args.max_score}")
    logger.info("-" * 70)

    # Connect to database
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create verifier
    verifier = create_verifier()

    try:
        # Get companies to verify
        companies = get_companies_to_verify(
            session,
            max_companies=args.max_companies,
            force_reverify=args.force_reverify
        )

        if not companies:
            logger.info("No companies to verify. Exiting.")
            return 0

        # Verify each company
        total = len(companies)
        passed_count = 0
        failed_count = 0
        unknown_count = 0
        error_count = 0

        for i, company in enumerate(companies, 1):
            logger.info(f"[{i}/{total}] Processing: {company['name']}")

            # Verify
            verification_result = verify_company_website(company, verifier)

            if verification_result:
                # Calculate combined score
                combined_score = calculate_combined_score(company, verification_result)

                # Update database
                update_company_verification(
                    session,
                    company['id'],
                    verification_result,
                    combined_score,
                    min_score=args.min_score,
                    max_score=args.max_score
                )

                # Track stats
                status = verification_result['status']
                if status == 'passed':
                    passed_count += 1
                elif status == 'failed':
                    failed_count += 1
                elif status == 'unknown':
                    unknown_count += 1
            else:
                error_count += 1

            # Rate limiting (polite crawling)
            if i < total:
                time.sleep(2.0)

        # Summary
        logger.info("=" * 70)
        logger.info("BATCH VERIFICATION JOB COMPLETED")
        logger.info("=" * 70)
        logger.info(f"Total processed: {total}")
        logger.info(f"Passed: {passed_count} ({passed_count/total*100:.1f}%)")
        logger.info(f"Failed: {failed_count} ({failed_count/total*100:.1f}%)")
        logger.info(f"Unknown (needs review): {unknown_count} ({unknown_count/total*100:.1f}%)")
        logger.info(f"Errors: {error_count}")
        logger.info("=" * 70)

        return 0

    except Exception as e:
        logger.error(f"Batch verification job failed: {e}")
        return 1

    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
