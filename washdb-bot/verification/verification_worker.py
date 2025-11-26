#!/usr/bin/env python3
"""
Verification worker process with prefetch buffer.

Uses a background thread to prefetch company websites while the main thread
runs LLM verification, keeping the GPU queue fed continuously.

Architecture:
1. Background prefetch thread acquires companies and fetches HTML
2. Prefetch buffer holds N ready-to-verify companies
3. Main thread pulls from buffer and runs verification
4. GPU stays busy because work is always ready
"""

import os
import sys
import time
import signal
import json
import threading
import queue
from datetime import datetime
from typing import Optional, Dict, Tuple
from pathlib import Path
from dataclasses import dataclass

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
PREFETCH_BUFFER_SIZE = int(os.getenv('VERIFY_PREFETCH_SIZE', '3'))  # Companies to prefetch

# Shutdown flag
shutdown_requested = False


@dataclass
class PrefetchedCompany:
    """A company with its pre-fetched website HTML."""
    company: Dict
    html: Optional[str]
    metadata: Optional[Dict]
    fetch_error: Optional[str] = None


class PrefetchBuffer:
    """
    Buffer that prefetches company websites in background.

    Keeps N companies ready with their HTML already fetched,
    so verification can proceed immediately without waiting for network I/O.
    """

    def __init__(self, worker_id: int, session_factory, logger, buffer_size: int = 3):
        self.worker_id = worker_id
        self.session_factory = session_factory
        self.logger = logger
        self.buffer_size = buffer_size

        self._buffer: queue.Queue[PrefetchedCompany] = queue.Queue(maxsize=buffer_size)
        self._prefetch_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start the prefetch background thread."""
        self._running = True
        self._prefetch_thread = threading.Thread(
            target=self._prefetch_loop,
            name=f"Prefetch-{self.worker_id}",
            daemon=True
        )
        self._prefetch_thread.start()
        self.logger.info(f"Prefetch buffer started (size={self.buffer_size})")

    def stop(self):
        """Stop the prefetch thread."""
        self._running = False
        if self._prefetch_thread:
            self._prefetch_thread.join(timeout=5.0)

    def get(self, timeout: float = 30.0) -> Optional[PrefetchedCompany]:
        """Get next prefetched company (blocks until available)."""
        try:
            return self._buffer.get(timeout=timeout)
        except queue.Empty:
            return None

    def qsize(self) -> int:
        """Current buffer size."""
        return self._buffer.qsize()

    def _prefetch_loop(self):
        """Background loop that continuously prefetches companies."""
        while self._running and not shutdown_requested:
            # Only prefetch if buffer has room
            if self._buffer.full():
                time.sleep(0.1)
                continue

            session = self.session_factory()
            try:
                # Acquire company
                company = self._acquire_company(session)

                if not company:
                    # Queue empty - wait before retrying
                    session.close()
                    time.sleep(5.0)
                    continue

                # Fetch website HTML (this is the slow part)
                website = company.get('website')
                html = None
                metadata = None
                fetch_error = None

                if website:
                    try:
                        html = fetch_page(website, delay=MIN_DELAY_SECONDS)
                        if html:
                            metadata = parse_site_content(html, website)
                        else:
                            fetch_error = "Failed to fetch website"
                    except Exception as e:
                        fetch_error = str(e)
                        self.logger.debug(f"Prefetch error for {company['name']}: {e}")

                # Add to buffer
                prefetched = PrefetchedCompany(
                    company=company,
                    html=html,
                    metadata=metadata,
                    fetch_error=fetch_error
                )

                try:
                    self._buffer.put(prefetched, timeout=5.0)
                    self.logger.debug(f"Prefetched: {company['name']} (buffer: {self._buffer.qsize()})")
                except queue.Full:
                    # Buffer full, mark company as not in_progress
                    self.logger.warning(f"Buffer full, releasing {company['name']}")

            except Exception as e:
                self.logger.error(f"Prefetch loop error: {e}")
                time.sleep(1.0)
            finally:
                session.close()

    def _acquire_company(self, session) -> Optional[Dict]:
        """Acquire a company for verification (same logic as main acquire)."""
        try:
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

            # Mark as in_progress
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
                'worker_id': self.worker_id,
                'started_at': datetime.now().isoformat()
            })
            session.commit()

            return company

        except Exception as e:
            self.logger.error(f"Error acquiring company: {e}")
            session.rollback()
            return None


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
    Verify a single company's website (fetches HTML).

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


def verify_prefetched_company(prefetched: PrefetchedCompany, verifier, logger) -> Optional[Dict]:
    """
    Verify a company using pre-fetched HTML (no network I/O).

    This is the fast path - HTML is already fetched by background thread.

    Args:
        prefetched: PrefetchedCompany with HTML already loaded
        verifier: ServiceVerifier instance
        logger: Logger instance

    Returns:
        Verification result dict or None on error
    """
    company = prefetched.company
    website = company.get('website')

    logger.info(f"Verifying (prefetched): {company['name']} ({website})")

    # Handle fetch errors from prefetch
    if prefetched.fetch_error or not prefetched.html:
        logger.warning(f"Prefetch failed for {website}: {prefetched.fetch_error}")
        return {
            'status': 'failed',
            'score': 0.0,
            'reason': prefetched.fetch_error or 'Failed to fetch website',
            'negative_signals': ['Website unreachable'],
            'positive_signals': [],
            'services_detected': {},
            'tier': 'D'
        }

    try:
        # Run verification with pre-fetched data (this is where LLM is called)
        verification_result = verifier.verify_company(
            company_data=company,
            website_html=prefetched.html,
            website_metadata=prefetched.metadata
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
        # LLM-based verification: trust is_legitimate flag
        is_legitimate = verification_result.get('is_legitimate', False)

        # Determine active flag based on LLM legitimacy check
        if is_legitimate:
            active = True
            verification_result['status'] = 'passed'
            verification_result['needs_review'] = False
            logger.info(f"LLM verified as legitimate")
        else:
            active = False
            verification_result['status'] = 'failed'
            verification_result['needs_review'] = False
            logger.info(f"LLM marked as not legitimate")

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

    When USE_LLM_QUEUE is enabled, uses prefetch buffer to keep GPU busy:
    - Background thread fetches websites into buffer
    - Main thread pulls from buffer and runs verification (LLM)
    - No network I/O wait in main thread = GPU always has work

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
    logger.info(f"Prefetch buffer size: {PREFETCH_BUFFER_SIZE}")
    logger.info("-" * 70)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Connect to database
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)

    # Create verifier with LLM mode (can be controlled via env var)
    use_llm = os.getenv('VERIFY_USE_LLM', 'true').lower() in ['true', '1', 'yes']
    use_llm_queue = os.getenv('USE_LLM_QUEUE', 'true').lower() in ['true', '1', 'yes']
    verifier = create_verifier(use_llm=use_llm)

    if use_llm:
        if use_llm_queue:
            logger.info("🤖 LLM verification ENABLED with GPU Queue + Prefetch (steady GPU)")
        else:
            logger.info("🤖 LLM verification ENABLED (direct mode)")
    else:
        logger.info("📊 Rule-based verification only (LLM disabled)")

    # Setup prefetch buffer if using LLM queue
    prefetch_buffer = None
    if use_llm_queue:
        prefetch_buffer = PrefetchBuffer(
            worker_id=worker_id,
            session_factory=Session,
            logger=logger,
            buffer_size=PREFETCH_BUFFER_SIZE
        )
        prefetch_buffer.start()
        logger.info("📦 Prefetch buffer STARTED")

    # Counters
    processed_count = 0
    success_count = 0
    empty_queue_count = 0
    current_delay = EMPTY_QUEUE_DELAY

    try:
        while not shutdown_requested:
            session = Session()

            try:
                if use_llm_queue and prefetch_buffer:
                    # PREFETCH MODE: Pull from buffer (fast - no network wait)
                    prefetched = prefetch_buffer.get(timeout=10.0)

                    if not prefetched:
                        # Buffer empty - wait for prefetch thread
                        empty_queue_count += 1
                        if empty_queue_count > 5:
                            logger.info(f"Prefetch buffer empty, waiting...")
                            time.sleep(2.0)
                        continue

                    # Reset empty count
                    empty_queue_count = 0

                    # Verify using pre-fetched data (only LLM call, no network)
                    company = prefetched.company
                    verification_result = verify_prefetched_company(prefetched, verifier, logger)

                else:
                    # LEGACY MODE: Fetch and verify sequentially
                    company = acquire_company_for_verification(session, worker_id, logger)

                    if not company:
                        empty_queue_count += 1
                        logger.info(f"Queue empty (count: {empty_queue_count}), sleeping {current_delay}s")
                        time.sleep(current_delay)
                        current_delay = min(current_delay * 1.5, MAX_EMPTY_QUEUE_DELAY)
                        continue

                    empty_queue_count = 0
                    current_delay = EMPTY_QUEUE_DELAY

                    verification_result = verify_company(company, verifier, logger)

                # Update database with results
                if verification_result:
                    combined_score = calculate_combined_score(company, verification_result)

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

                    # Log progress with buffer status
                    buffer_info = f", Buffer={prefetch_buffer.qsize()}" if prefetch_buffer else ""
                    logger.info(
                        f"Progress: Processed={processed_count}, "
                        f"Success={success_count}, "
                        f"Rate={success_count/processed_count*100:.1f}%{buffer_info}"
                    )

                # Minimal delay in prefetch mode (GPU should stay busy)
                if use_llm_queue:
                    pass  # No delay - next item already prefetched
                else:
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
        if prefetch_buffer:
            prefetch_buffer.stop()
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
