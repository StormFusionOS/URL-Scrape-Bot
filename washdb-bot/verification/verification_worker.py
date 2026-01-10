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
from scrape_site.site_scraper import fetch_page, scrape_website
from scrape_site.site_parse import parse_site_content
from scrape_site.service_verifier import create_verifier
from db.verify_company_urls import calculate_combined_score
from verification.ml_classifier import (
    build_features,
    predict_provider_prob,
    compute_final_score,
    get_model_info,
)
from scrape_yp.name_standardizer import (
    score_name_quality,
    parse_location_from_address,
    needs_standardization,
)
from verification.config_verifier import (
    MIN_DELAY_SECONDS,
    MAX_DELAY_SECONDS,
    EMPTY_QUEUE_DELAY,
    MAX_EMPTY_QUEUE_DELAY,
    PREFETCH_BUFFER_SIZE,
    COMBINED_HIGH_THRESHOLD,
    COMBINED_LOW_THRESHOLD,
    RED_FLAG_AUTO_REJECT_COUNT,
    LLM_CONFIDENCE_LOW,
    THIN_TEXT_THRESHOLD,
    MAX_DEEP_SCRAPES_PER_HOUR,
)

# Track deep scrapes per hour (reset hourly)
_deep_scrape_count = 0
_deep_scrape_hour = None

load_dotenv()

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
                used_deep_scrape = False

                if website:
                    try:
                        html = fetch_page(website, delay=MIN_DELAY_SECONDS)
                        if html:
                            metadata = parse_site_content(html, website)

                            # === Deep scrape for thin sites ===
                            # Check if site has minimal content
                            services_len = len(metadata.get('services') or '')
                            homepage_len = len(metadata.get('homepage_text') or '')

                            if (services_len < THIN_TEXT_THRESHOLD and
                                homepage_len < THIN_TEXT_THRESHOLD):
                                # This is a thin site - check deep scrape budget
                                global _deep_scrape_count, _deep_scrape_hour
                                current_hour = datetime.now().hour

                                # Reset hourly counter
                                if _deep_scrape_hour != current_hour:
                                    _deep_scrape_count = 0
                                    _deep_scrape_hour = current_hour

                                if _deep_scrape_count < MAX_DEEP_SCRAPES_PER_HOUR:
                                    try:
                                        self.logger.info(
                                            f"Thin site detected ({homepage_len} chars), "
                                            f"running deep scrape for {company['name']}"
                                        )
                                        scraper_result = scrape_website(website)
                                        if scraper_result:
                                            # Merge deep scrape metadata
                                            metadata = scraper_result
                                            metadata['deep_scraped'] = True
                                            used_deep_scrape = True
                                            _deep_scrape_count += 1
                                    except Exception as e:
                                        self.logger.warning(
                                            f"Deep scrape failed for {website}: {e}"
                                        )
                                        # Continue with original metadata
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
                  -- Only pick up companies that are truly unverified
                  AND verified IS NULL
                  AND llm_verified IS NULL
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
              -- Only pick up companies that are truly unverified
              AND verified IS NULL
              AND llm_verified IS NULL
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

        # Include content_metrics from metadata for SEO analysis storage
        if metadata and metadata.get('content_metrics'):
            verification_result['content_metrics'] = metadata['content_metrics']

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

        # Include content_metrics from metadata for SEO analysis storage
        if prefetched.metadata and prefetched.metadata.get('content_metrics'):
            verification_result['content_metrics'] = prefetched.metadata['content_metrics']

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
    company_data: Dict,
    verification_result: Dict,
    combined_score: float,
    worker_id: int,
    logger,
    website_metadata: Optional[Dict] = None
):
    """
    Update company record with verification results using proper triage logic.

    Three-way triage based on combined signals:
    - passed (auto-accept): High final score + LLM legitimate + no red flags
    - failed (auto-reject): Low final score OR multiple red flags + not legitimate
    - needs_review: Ambiguous signals, disagreement, or low confidence

    Also extracts and stores name standardization data for companies with
    short/poor-quality names using the website content that was already scraped.

    Args:
        session: SQLAlchemy session
        company_id: Company ID
        company_data: Company data dict (used for ML feature building)
        verification_result: Verification result dict from service_verifier
        combined_score: Combined score (discovery + website + reviews)
        worker_id: Worker ID for tracking
        logger: Logger instance
        website_metadata: Parsed website content (name, services, about, homepage_text, etc.)
    """
    try:
        # === Extract decision signals ===
        svc_status = verification_result.get('status', 'unknown')  # From service_verifier
        svc_score = verification_result.get('score', 0.0)
        is_legitimate = verification_result.get('is_legitimate', False)
        red_flags = verification_result.get('red_flags', []) or []
        llm_confidence = verification_result.get('llm_classification', {}).get('confidence', 0.0)

        # === ML Classifier Integration ===
        # Build features and get ML probability if model exists
        ml_prob = None
        final_score = combined_score  # Default to combined_score if no model

        try:
            # Create a simple object with parse_metadata for build_features
            class CompanyProxy:
                def __init__(self, data):
                    self.parse_metadata = data.get('parse_metadata', {})

            company_proxy = CompanyProxy(company_data)
            features = build_features(company_proxy, verification_result, combined_score)
            ml_prob = predict_provider_prob(features)

            if ml_prob is not None:
                # Fuse ML probability with combined score
                final_score = compute_final_score(combined_score, ml_prob, ml_weight=0.5)
                logger.debug(f"ML: combined={combined_score:.3f}, ml_prob={ml_prob:.3f}, "
                           f"final={final_score:.3f}")
        except Exception as e:
            logger.warning(f"ML prediction failed, using combined_score: {e}")

        # === Name Standardization ===
        # Extract better name from website content for companies with short/poor-quality names
        name_quality = None
        name_flag = False
        standardized_name = None
        std_name_source = None
        std_name_confidence = None
        city = None
        state = None
        zip_code = None
        location_source = None

        company_name = company_data.get('name', '')
        company_address = company_data.get('address', '')

        try:
            # Calculate name quality score
            if company_name:
                name_quality = score_name_quality(company_name)
                name_flag = needs_standardization(company_name)

            # Parse location from address
            if company_address:
                location = parse_location_from_address(company_address)
                city = location.get('city')
                state = location.get('state')
                zip_code = location.get('zip_code')
                if city or state or zip_code:
                    location_source = 'address_parse'

            # Try to extract better name from website content if name is poor quality
            if name_flag and website_metadata:
                # First try: use name extracted from website by site_parse.py
                website_name = website_metadata.get('name', '')
                if website_name and len(website_name) > len(company_name) + 3:
                    # Website has a longer name - use it
                    standardized_name = website_name.strip()
                    std_name_source = 'website_title'
                    std_name_confidence = 0.85
                    logger.info(f"Name improved from '{company_name}' to '{standardized_name}' (from website)")

                # If website name not better, could also check about section
                if not standardized_name:
                    about_text = website_metadata.get('about', '')
                    if about_text and len(about_text) > 20:
                        # Look for business name patterns in about text
                        # Common pattern: "Welcome to <Business Name>" or "<Business Name> is..."
                        import re
                        patterns = [
                            r'Welcome to ([A-Z][A-Za-z\s&\'-]+(?:LLC|Inc|Co|Services|Wash|Cleaning)?)',
                            r'^([A-Z][A-Za-z\s&\'-]+(?:LLC|Inc|Co|Services|Wash|Cleaning)?)\s+(?:is|has been|provides|offers)',
                        ]
                        for pattern in patterns:
                            match = re.search(pattern, about_text[:500])
                            if match:
                                extracted_name = match.group(1).strip()
                                if len(extracted_name) > len(company_name) + 3 and len(extracted_name) < 80:
                                    standardized_name = extracted_name
                                    std_name_source = 'about_section'
                                    std_name_confidence = 0.70
                                    logger.info(f"Name improved from '{company_name}' to '{standardized_name}' (from about)")
                                    break

        except Exception as e:
            logger.warning(f"Name standardization failed: {e}")

        # === Three-way triage logic (using final_score) ===
        needs_review = False

        # HIGH: Auto-accept conditions
        # - Final score >= threshold (e.g., 0.75)
        # - LLM says legitimate
        # - Service verifier passed
        if (final_score >= COMBINED_HIGH_THRESHOLD and
            is_legitimate and
            svc_status == 'passed'):
            active = True
            final_status = 'passed'
            logger.info(f"ACCEPTED: final_score={final_score:.2f}, legitimate=True, red_flags={len(red_flags)}")

        # LOW: Auto-reject conditions
        # - Final score <= threshold (e.g., 0.35)
        # - OR: Not legitimate + multiple red flags
        # - OR: Service verifier explicitly failed with red flags
        elif (final_score <= COMBINED_LOW_THRESHOLD or
              (not is_legitimate and len(red_flags) >= RED_FLAG_AUTO_REJECT_COUNT) or
              (svc_status == 'failed' and len(red_flags) >= RED_FLAG_AUTO_REJECT_COUNT)):
            active = False
            final_status = 'failed'
            logger.info(f"REJECTED: final_score={final_score:.2f}, legitimate={is_legitimate}, "
                       f"red_flags={len(red_flags)}")

        # MIDDLE: Needs manual review
        # - Score in uncertain range
        # - OR: Heuristics and LLM disagree
        # - OR: LLM confidence is low
        # - OR: Service verifier said unknown
        else:
            active = False  # Don't auto-activate uncertain companies
            final_status = 'unknown'
            needs_review = True
            logger.info(f"NEEDS REVIEW: final_score={final_score:.2f}, legitimate={is_legitimate}, "
                       f"svc_status={svc_status}, red_flags={len(red_flags)}")

        # === Update verification result with triage outcome ===
        verification_result['status'] = final_status
        verification_result['needs_review'] = needs_review
        verification_result['combined_score'] = combined_score
        verification_result['final_score'] = final_score
        if ml_prob is not None:
            verification_result['ml_prob'] = ml_prob
        verification_result['verified_at'] = datetime.now().isoformat()
        verification_result['worker_id'] = worker_id
        verification_result['triage_reason'] = (
            f"final={final_score:.2f}, combined={combined_score:.2f}, "
            f"ml_prob={ml_prob if ml_prob else 'N/A'}, legit={is_legitimate}, "
            f"red_flags={len(red_flags)}, svc={svc_status}"
        )

        # === Store additional metadata we already extract ===
        if website_metadata:
            # Content metrics (SEO signals: word count, headers, content depth)
            if website_metadata.get('content_metrics'):
                verification_result['content_metrics'] = website_metadata['content_metrics']

            # All contacts (not just the first one)
            verification_result['contacts'] = {
                'phones': website_metadata.get('phones', []),
                'emails': website_metadata.get('emails', []),
            }

            # JSON-LD structured data (hours, social links, logo, etc.)
            if website_metadata.get('json_ld'):
                verification_result['schema_org'] = website_metadata['json_ld']

            # Scrape info (track what was scraped)
            verification_result['scrape_info'] = {
                'deep_scraped': website_metadata.get('deep_scraped', False),
                'scraped_at': datetime.now().isoformat()
            }

        # Serialize to JSON
        verification_json = json.dumps(verification_result)

        # Determine verified status for standardized column
        # verified = true if passed, false if failed, null if unknown/needs_review
        # llm_verified is set to mark that LLM verification was attempted
        verified_value = None
        llm_verified_value = None
        provider_status = 'pending'  # Default status
        if final_status == 'passed':
            verified_value = True
            llm_verified_value = True
            provider_status = 'provider'  # Confirmed service provider
        elif final_status == 'failed':
            verified_value = False
            llm_verified_value = False
            provider_status = 'non_provider'  # NOT a service provider
        else:
            # Needs review - set llm_verified to False to prevent re-processing
            llm_verified_value = False
            provider_status = 'unknown'  # Needs review

        # Build the UPDATE query with name standardization fields
        query = text("""
            UPDATE companies
            SET
                parse_metadata = jsonb_set(
                    COALESCE(parse_metadata, '{}'::jsonb),
                    '{verification}',
                    CAST(:verification_json AS jsonb)
                ),
                verified = :verified,
                llm_verified = :llm_verified,
                llm_verified_at = NOW(),
                provider_status = :provider_status,
                verification_type = 'llm',
                name_quality_score = COALESCE(:name_quality, name_quality_score),
                name_length_flag = COALESCE(:name_flag, name_length_flag),
                standardized_name = COALESCE(:std_name, standardized_name),
                standardized_name_source = COALESCE(:std_source, standardized_name_source),
                standardized_name_confidence = COALESCE(:std_confidence, standardized_name_confidence),
                city = COALESCE(:city, city),
                state = COALESCE(:state, state),
                zip_code = COALESCE(:zip_code, zip_code),
                location_source = COALESCE(:loc_source, location_source),
                last_updated = NOW()
            WHERE id = :company_id
        """)

        session.execute(query, {
            'company_id': company_id,
            'verification_json': verification_json,
            'verified': verified_value,
            'llm_verified': llm_verified_value,
            'provider_status': provider_status,
            'name_quality': name_quality,
            'name_flag': name_flag,
            'std_name': standardized_name,
            'std_source': std_name_source,
            'std_confidence': std_name_confidence,
            'city': city,
            'state': state,
            'zip_code': zip_code,
            'loc_source': location_source,
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
    logger.info(f"High threshold (auto-pass): {COMBINED_HIGH_THRESHOLD}")
    logger.info(f"Low threshold (auto-reject): {COMBINED_LOW_THRESHOLD}")
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

    # Log ML classifier info
    ml_info = get_model_info()
    if ml_info:
        logger.info(f"🧠 ML Classifier LOADED: {ml_info.get('model_type', 'unknown')} "
                   f"(trained: {ml_info.get('trained_at', 'unknown')[:10]}, "
                   f"samples: {ml_info.get('n_train', 'unknown')})")
    else:
        logger.info("📊 ML Classifier NOT AVAILABLE - using combined_score only")

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
                website_metadata = None  # Track website metadata for name extraction

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
                    website_metadata = prefetched.metadata  # Save for name extraction
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
                        company,  # Pass company_data for ML feature building
                        verification_result,
                        combined_score,
                        worker_id,
                        logger,
                        website_metadata=website_metadata  # Pass website metadata for name extraction
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
