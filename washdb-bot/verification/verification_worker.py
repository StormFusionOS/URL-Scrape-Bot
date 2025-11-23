#!/usr/bin/env python3
"""
Verification worker process.

Continuously processes unverified companies from the database:
1. Acquires next company with row-level locking
2. Fetches website content
3. Runs verification logic
4. Updates database with results
5. Repeats until shutdown signal
"""

import os
import sys
import time
import signal
import json
from datetime import datetime
from typing import Optional, Dict
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, or_
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger
from scrape_site.site_scraper import fetch_page
from scrape_site.site_parse import parse_site_content
from scrape_site.service_verifier import create_verifier
from db.verify_company_urls import calculate_combined_score

load_dotenv()

# Configuration
MIN_DELAY_SECONDS = float(os.getenv('VERIFY_MIN_DELAY_SECONDS', '2.0'))
MAX_DELAY_SECONDS = float(os.getenv('VERIFY_MAX_DELAY_SECONDS', '5.0'))
EMPTY_QUEUE_DELAY = 60  # Seconds to wait when queue is empty
MAX_EMPTY_QUEUE_DELAY = 300  # Max backoff delay
MIN_SCORE = float(os.getenv('VERIFY_MIN_SCORE', '0.75'))
MAX_SCORE = float(os.getenv('VERIFY_MAX_SCORE', '0.25'))  # Lowered from 0.35

# Shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    shutdown_requested = True


def acquire_company_for_verification(session, worker_id: int, logger) -> Optional[Dict]:
    """
    Acquire next unverified company using row-level locking.

    Uses PostgreSQL's FOR UPDATE SKIP LOCKED to prevent multiple
    workers from processing the same company.

    Args:
        session: SQLAlchemy session
        worker_id: Worker ID for tracking
        logger: Logger instance

    Returns:
        Company dict or None if queue is empty
    """
    try:
        # Query for next unverified company with row-level lock
        query = text("""
            SELECT
                id, name, website, domain, phone, email,
                services, service_area, address, source,
                rating_yp, rating_google, reviews_yp, reviews_google,
                parse_metadata, active, created_at, last_updated
            FROM companies
            WHERE website IS NOT NULL
              AND (
                  parse_metadata->'verification' IS NULL
                  OR parse_metadata->'verification'->>'status' IS NULL
                  OR parse_metadata->'verification'->>'status' = 'in_progress'
              )
            ORDER BY created_at DESC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        """)

        result = session.execute(query)
        row = result.fetchone()

        if not row:
            return None

        # Convert to dict
        company = {
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
        }

        # Mark as in_progress immediately to prevent other workers from claiming
        mark_query = text("""
            UPDATE companies
            SET parse_metadata = jsonb_set(
                COALESCE(parse_metadata, '{}'::jsonb),
                '{verification}',
                jsonb_build_object(
                    'status', 'in_progress'::text,
                    'worker_id', CAST(:worker_id AS integer),
                    'started_at', CAST(:started_at AS text)
                )
            )
            WHERE id = :company_id
        """)

        session.execute(mark_query, {
            'company_id': company['id'],
            'worker_id': worker_id,
            'started_at': datetime.now().isoformat()
        })
        session.commit()

        logger.info(f"Acquired company {company['id']}: {company['name']}")
        return company

    except Exception as e:
        logger.error(f"Error acquiring company: {e}")
        session.rollback()
        return None


def verify_company(company: Dict, verifier, logger) -> Optional[Dict]:
    """
    Verify a single company's website.

    Args:
        company: Company data dict
        verifier: ServiceVerifier instance
        logger: Logger instance

    Returns:
        Verification result dict or None on error
    """
    website = company.get('website')
    if not website:
        return None

    logger.info(f"Verifying: {company['name']} ({website})")

    try:
        # Fetch homepage
        html = fetch_page(website, delay=MIN_DELAY_SECONDS)
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


def update_company_verification(
    session,
    company_id: int,
    verification_result: Dict,
    combined_score: float,
    worker_id: int,
    logger
):
    """
    Update company record with verification results.

    Args:
        session: SQLAlchemy session
        company_id: Company ID
        verification_result: Verification result dict
        combined_score: Combined score (discovery + website + reviews)
        worker_id: Worker ID for tracking
        logger: Logger instance
    """
    try:
        # Determine active flag based on combined score
        if combined_score >= MIN_SCORE:
            active = True
            verification_result['status'] = 'passed'
            verification_result['needs_review'] = False
        elif combined_score <= MAX_SCORE:
            active = False
            verification_result['status'] = 'failed'
            verification_result['needs_review'] = False
        else:
            # Keep current active status, but flag for review
            active = None  # Don't change
            verification_result['status'] = 'unknown'
            verification_result['needs_review'] = True

        # Add metadata
        verification_result['combined_score'] = combined_score
        verification_result['verified_at'] = datetime.now().isoformat()
        verification_result['worker_id'] = worker_id

        # Serialize to JSON
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
        logger.info(f"Updated company {company_id} with verification results")

    except Exception as e:
        logger.error(f"Error updating company {company_id}: {e}")
        session.rollback()


def run_worker(worker_id: int, config: Dict):
    """
    Main worker function - runs continuously until shutdown.

    Args:
        worker_id: Worker ID (0-4 for 5 workers)
        config: Configuration dict
    """
    # Setup logger
    logger = get_logger(f"verify_worker_{worker_id}")

    logger.info("=" * 70)
    logger.info(f"VERIFICATION WORKER {worker_id} STARTED")
    logger.info("=" * 70)
    logger.info(f"Min delay: {MIN_DELAY_SECONDS}s")
    logger.info(f"Max delay: {MAX_DELAY_SECONDS}s")
    logger.info(f"Min score (auto-pass): {MIN_SCORE}")
    logger.info(f"Max score (auto-reject): {MAX_SCORE}")
    logger.info("-" * 70)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Connect to database
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)

    # Create verifier with LLM mode (can be controlled via env var)
    use_llm = os.getenv('VERIFY_USE_LLM', 'true').lower() in ['true', '1', 'yes']
    verifier = create_verifier(use_llm=use_llm)

    if use_llm:
        logger.info("🤖 LLM-enhanced verification ENABLED (Llama 3.2 3B)")
    else:
        logger.info("📊 Rule-based verification only (LLM disabled)")

    # Counters
    processed_count = 0
    success_count = 0
    empty_queue_count = 0
    current_delay = EMPTY_QUEUE_DELAY

    try:
        while not shutdown_requested:
            session = Session()

            try:
                # Acquire next company
                company = acquire_company_for_verification(session, worker_id, logger)

                if not company:
                    # Queue is empty
                    empty_queue_count += 1
                    logger.info(f"Queue empty (count: {empty_queue_count}), sleeping {current_delay}s")
                    time.sleep(current_delay)

                    # Exponential backoff
                    current_delay = min(current_delay * 1.5, MAX_EMPTY_QUEUE_DELAY)
                    continue

                # Reset empty queue tracking
                empty_queue_count = 0
                current_delay = EMPTY_QUEUE_DELAY

                # Verify company
                verification_result = verify_company(company, verifier, logger)

                if verification_result:
                    # Calculate combined score
                    combined_score = calculate_combined_score(company, verification_result)

                    # Update database
                    update_company_verification(
                        session,
                        company['id'],
                        verification_result,
                        combined_score,
                        worker_id,
                        logger
                    )

                    processed_count += 1
                    if verification_result['status'] in ['passed', 'unknown']:
                        success_count += 1

                    logger.info(
                        f"Progress: Processed={processed_count}, "
                        f"Success={success_count}, "
                        f"Rate={success_count/processed_count*100:.1f}%"
                    )

                # Rate limiting
                delay = MIN_DELAY_SECONDS + (MAX_DELAY_SECONDS - MIN_DELAY_SECONDS) * 0.5
                time.sleep(delay)

            finally:
                session.close()

        logger.info("=" * 70)
        logger.info(f"WORKER {worker_id} SHUTTING DOWN (graceful)")
        logger.info(f"Total processed: {processed_count}")
        logger.info(f"Success count: {success_count}")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"Worker {worker_id} failed: {e}")
        raise

    finally:
        engine.dispose()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Verification worker process')
    parser.add_argument('--worker-id', type=int, required=True, help='Worker ID')
    parser.add_argument('--config', type=str, help='Config file path (optional)')

    args = parser.parse_args()

    config = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = json.load(f)

    run_worker(args.worker_id, config)
