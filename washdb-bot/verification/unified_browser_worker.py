#!/usr/bin/env python3
"""
Unified Browser Worker - Single browser session for verification AND standardization.

This worker uses the SEO browser infrastructure (warmed sessions, stealth, escalation)
to extract comprehensive content and run both verification and standardization in a
single visit per company.

Features:
- Uses EnterpriseBrowserPool for warmed browser sessions
- Automatic Camoufox escalation on CAPTCHA/blocks
- Human behavior simulation
- ChatML prompt format for unified-washdb model
- Comprehensive content extraction for maximum LLM accuracy
- Combined verification + standardization in one session
"""

# Fix for Playwright sync API in asyncio contexts - MUST be before any Playwright imports
import nest_asyncio
nest_asyncio.apply()

import os
import sys
import time
import json
import random
import signal
import logging
import threading
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from queue import Queue, Empty

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=False)

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from runner.logging_setup import get_logger

# Browser pool imports
from seo_intelligence.drivers.browser_pool import get_browser_pool
from seo_intelligence.drivers.human_behavior import simulate_reading_selenium
from seo_intelligence.drivers.pool_models import SessionLease

# Local imports
from verification.browser_content_extractor import (
    BrowserExtractedContent,
    extract_browser_content,
    get_json_ld_name,
)
from verification.unified_llm import get_unified_llm

logger = get_logger("unified_browser_worker")

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')
WORKER_ID = int(os.getenv('UNIFIED_WORKER_ID', '1'))
BATCH_SIZE = int(os.getenv('UNIFIED_BATCH_SIZE', '50'))
LEASE_DURATION = int(os.getenv('UNIFIED_BROWSER_LEASE_DURATION', '120'))
PREFETCH_SIZE = int(os.getenv('UNIFIED_BROWSER_PREFETCH_SIZE', '3'))
POLL_INTERVAL = int(os.getenv('UNIFIED_POLL_INTERVAL', '30'))
HEARTBEAT_INTERVAL = 30

# Rate limiting
MIN_DELAY_BETWEEN_REQUESTS = 3.0
MAX_DELAY_BETWEEN_REQUESTS = 6.0

# Directory domains - these are citation sources, not direct business websites
# We skip browser verification but track them for SEO modules
DIRECTORY_DOMAINS = {
    'localsearch.com',
    'yellowpages.com',
    'yelp.com',
    'manta.com',
    'bbb.org',
    'angieslist.com',
    'homeadvisor.com',
    'thumbtack.com',
    'houzz.com',
    'porch.com',
    'nextdoor.com',
    'facebook.com',
    'linkedin.com',
    'google.com/maps',
    'mapquest.com',
    'superpages.com',
    'dexknows.com',
    'citysearch.com',
    'merchantcircle.com',
    'brownbook.net',
    'hotfrog.com',
    'chamberofcommerce.com',
    'spoke.com',
    'judysbook.com',
    'kudzu.com',
    'local.com',
    'yellowbot.com',
    'showmelocal.com',
    'cylex.us.com',
    'elocal.com',
    'yasabe.com',
    'bizhwy.com',
    'salespider.com',
    'expressbusinessdirectory.com',
    'tuugo.us',
    'fyple.com',
    'golocal247.com',
    'lacartes.com',
    'n49.com',
    '2findlocal.com',
    'opendi.us',
    'callupcontact.com',
    'getfave.com',
    'ebusinesspages.com',
    'agreatertown.com',
}


def is_directory_url(url: str) -> Optional[str]:
    """Check if URL is a directory/citation source. Returns directory domain or None."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace('www.', '')

        # Check for exact matches or subdomains
        for dir_domain in DIRECTORY_DOMAINS:
            if domain == dir_domain or domain.endswith('.' + dir_domain):
                return dir_domain

        # Check for common directory patterns in subdomain
        if '.localsearch.com' in domain:
            return 'localsearch.com'

        return None
    except Exception:
        return None


@dataclass
class PrefetchedCompany:
    """Company with prefetched browser content."""
    company: Dict
    content: Optional[BrowserExtractedContent] = None
    error: Optional[str] = None


class UnifiedBrowserWorker:
    """
    Unified browser worker for verification + standardization.

    Uses the SEO browser pool for warmed sessions and Camoufox fallback.
    Extracts comprehensive content and runs both LLM tasks in one session.
    """

    def __init__(self, worker_id: int = 1):
        """Initialize unified browser worker."""
        self.worker_id = worker_id
        self.engine = create_engine(
            DATABASE_URL,
            poolclass=QueuePool,
            pool_size=2,
            max_overflow=3,
            pool_pre_ping=True,
        )

        # Browser pool
        self.pool = get_browser_pool()

        # LLM
        self.llm = get_unified_llm()

        # Prefetch buffer
        self._prefetch_buffer: Queue = Queue(maxsize=PREFETCH_SIZE)
        self._prefetch_thread: Optional[threading.Thread] = None

        # Statistics
        self.stats = {
            'processed': 0,
            'verified_true': 0,
            'verified_false': 0,
            'standardized': 0,
            'errors': 0,
            'blocks': 0,
        }

        # Shutdown flag
        self._shutdown = threading.Event()

        logger.info(f"UnifiedBrowserWorker {worker_id} initialized")

    def start(self):
        """Start the worker."""
        logger.info(f"Starting UnifiedBrowserWorker {self.worker_id}")

        # Start prefetch thread
        self._prefetch_thread = threading.Thread(
            target=self._prefetch_loop,
            name=f"Prefetch-{self.worker_id}",
            daemon=True,
        )
        self._prefetch_thread.start()

        # Main processing loop
        self._main_loop()

    def stop(self):
        """Stop the worker gracefully."""
        logger.info(f"Stopping UnifiedBrowserWorker {self.worker_id}")
        self._shutdown.set()

    def _main_loop(self):
        """Main processing loop."""
        while not self._shutdown.is_set():
            try:
                # Get prefetched company
                try:
                    prefetched = self._prefetch_buffer.get(timeout=5)
                except Empty:
                    continue

                if prefetched.error:
                    # Check if this is a directory/citation source
                    if prefetched.error.startswith('DIRECTORY:'):
                        directory_domain = prefetched.error.split(':', 1)[1]
                        self._mark_as_citation(prefetched.company, directory_domain)
                        logger.info(f"Marked {prefetched.company.get('name')} as citation source ({directory_domain})")
                    else:
                        logger.warning(f"Prefetch error for {prefetched.company.get('name')}: {prefetched.error}")
                        self._mark_failed(prefetched.company, prefetched.error)
                    continue

                # Process company
                self._process_company(prefetched)

                # Rate limiting
                delay = random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)
                time.sleep(delay)

            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(5)

    def _prefetch_loop(self):
        """Background prefetch loop - acquires browser and extracts content."""
        while not self._shutdown.is_set():
            try:
                # Wait if buffer is full
                if self._prefetch_buffer.full():
                    time.sleep(0.5)
                    continue

                # Get next company
                company = self._acquire_next_company()
                if not company:
                    time.sleep(POLL_INTERVAL)
                    continue

                # Extract content with browser
                content, error = self._extract_with_browser(company)

                prefetched = PrefetchedCompany(
                    company=company,
                    content=content,
                    error=error,
                )

                self._prefetch_buffer.put(prefetched)

            except Exception as e:
                logger.error(f"Prefetch loop error: {e}")
                time.sleep(5)

    def _acquire_next_company(self) -> Optional[Dict]:
        """Acquire next company to process from database."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                UPDATE companies
                SET processing_started_at = NOW(),
                    processing_worker_id = :worker_id
                WHERE id = (
                    SELECT id FROM companies
                    WHERE llm_verified IS NULL
                    AND website IS NOT NULL
                    AND website != ''
                    AND (processing_started_at IS NULL
                         OR processing_started_at < NOW() - INTERVAL '30 minutes')
                    ORDER BY
                        CASE WHEN parse_metadata IS NOT NULL
                             AND parse_metadata::text != '{}' THEN 0 ELSE 1 END,
                        created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, name, website, phone, address
            """), {'worker_id': self.worker_id})

            row = result.fetchone()
            conn.commit()

            if row:
                return {
                    'id': row[0],
                    'name': row[1],
                    'website': row[2],
                    'phone': row[3],
                    'address': row[4],
                }
            return None

    def _extract_with_browser(
        self,
        company: Dict
    ) -> Tuple[Optional[BrowserExtractedContent], Optional[str]]:
        """Extract content using browser pool."""
        website = company.get('website', '')
        if not website:
            return None, "No website"

        # Check if this is a directory/citation source
        directory_domain = is_directory_url(website)
        if directory_domain:
            # Return special marker for directory URLs - these are valuable for SEO
            # but not valid for direct business verification
            return None, f"DIRECTORY:{directory_domain}"

        # Parse domain
        try:
            parsed = urlparse(website)
            domain = parsed.netloc.replace('www.', '')
        except Exception:
            return None, "Invalid URL"

        # Acquire browser session
        lease = self.pool.acquire_session(
            target_domain=domain,
            requester=f"unified_worker_{self.worker_id}",
            timeout_seconds=60,
            lease_duration_seconds=LEASE_DURATION,
        )

        if not lease:
            # Try Camoufox fallback
            return self._extract_with_camoufox(company)

        try:
            driver = self.pool.get_driver(lease)
            if not driver:
                self.pool.release_session(lease, dirty=True, dirty_reason="No driver")
                return self._extract_with_camoufox(company)

            # Navigate
            try:
                driver.get(website)
            except Exception as e:
                self.pool.release_session(lease, dirty=True, dirty_reason=str(e))
                return None, f"Navigation failed: {e}"

            # Wait for JS-heavy sites to render (Wix, Squarespace, React, etc.)
            time.sleep(random.uniform(7, 10))

            # Simulate reading behavior
            try:
                simulate_reading_selenium(driver, min_time=4, max_time=6)
            except Exception:
                pass

            # Dismiss popups
            self._dismiss_popups(driver)

            # Check for blocks
            if self._detect_block(driver):
                self.pool.release_session(lease, dirty=True, detected_captcha=True)
                self.stats['blocks'] += 1
                return self._extract_with_camoufox(company)

            # Extract content
            content = extract_browser_content(driver, website, browser_type="selenium_uc")

            # Release session
            self.pool.release_session(lease, dirty=False)

            return content, None

        except Exception as e:
            logger.error(f"Browser extraction error: {e}")
            try:
                self.pool.release_session(lease, dirty=True, dirty_reason=str(e))
            except Exception:
                pass
            return None, str(e)

    def _extract_with_camoufox(
        self,
        company: Dict
    ) -> Tuple[Optional[BrowserExtractedContent], Optional[str]]:
        """Fallback extraction with Camoufox."""
        try:
            from seo_intelligence.drivers.camoufox_drivers import CamoufoxDriver

            website = company.get('website', '')

            with CamoufoxDriver() as driver:
                driver.get(website)
                time.sleep(random.uniform(7, 10))  # Wait for JS to render

                if self._detect_block(driver):
                    return None, "Blocked by Camoufox"

                content = extract_browser_content(driver, website, browser_type="camoufox")
                return content, None

        except Exception as e:
            logger.error(f"Camoufox extraction error: {e}")
            return None, str(e)

    def _dismiss_popups(self, driver: Any):
        """Try to dismiss cookie/popup dialogs."""
        selectors = [
            'button[id*="accept"]',
            'button[class*="accept"]',
            'button[class*="consent"]',
            '[aria-label*="Accept"]',
        ]

        for selector in selectors:
            try:
                elements = driver.find_elements("css selector", selector)
                for elem in elements:
                    if elem.is_displayed() and elem.is_enabled():
                        text = elem.text.lower()
                        if any(w in text for w in ['accept', 'agree', 'ok', 'got it']):
                            elem.click()
                            time.sleep(0.3)
                            return
            except Exception:
                continue

    def _detect_block(self, driver: Any) -> bool:
        """Detect CAPTCHA or blocking page."""
        try:
            title = driver.title.lower() if driver.title else ""
            indicators = ['captcha', 'robot check', 'are you human', 'access denied', 'blocked']
            return any(ind in title for ind in indicators)
        except Exception:
            return False

    def _process_company(self, prefetched: PrefetchedCompany):
        """Process company with verification and standardization."""
        company = prefetched.company
        content = prefetched.content

        if not content or not content.success:
            self._mark_failed(company, content.error if content else "No content")
            return

        # Run verification
        verify_result = self.llm.verify_company_rich(
            company_name=company['name'],
            website=company['website'],
            phone=company.get('phone') or '',
            title=content.title or '',
            meta_description=content.meta_description or '',
            h1_text=content.h1_text or '',
            og_site_name=content.og_site_name or '',
            json_ld=content.json_ld,
            services_text=content.services_text or '',
            about_text=content.about_text or '',
            homepage_text=content.homepage_text or '',
            address=content.address or '',
            emails=content.emails,
        )

        if not verify_result:
            self._mark_failed(company, "Verification LLM failed")
            return

        legitimate = verify_result.get('legitimate', False)

        # Run standardization if legitimate
        std_result = None
        if legitimate:
            std_result = self.llm.standardize_name_rich(
                current_name=company['name'],
                website=company['website'],
                page_title=content.title or '',
                meta_description=content.meta_description or '',
                og_site_name=content.og_site_name or '',
                json_ld=content.json_ld,
                h1_text=content.h1_text or '',
                copyright_text=content.copyright_text or '',
            )

        # Update database
        self._update_company(company, verify_result, std_result, content)

        # Update stats
        self.stats['processed'] += 1
        if legitimate:
            self.stats['verified_true'] += 1
            if std_result and std_result.get('success'):
                self.stats['standardized'] += 1
        else:
            self.stats['verified_false'] += 1

        logger.info(
            f"Processed {company['name'][:30]}: "
            f"legitimate={legitimate}, confidence={verify_result.get('confidence', 0):.2f}"
        )

    def _update_company(
        self,
        company: Dict,
        verify_result: Dict,
        std_result: Optional[Dict],
        content: BrowserExtractedContent
    ):
        """Update company in database."""
        with self.engine.connect() as conn:
            # Build verification metadata
            verification_data = {
                'status': 'passed' if verify_result.get('legitimate') else 'failed',
                'score': verify_result.get('confidence', 0.0),
                'legitimate': verify_result.get('legitimate', False),
                'services': verify_result.get('services', []),
                'reasoning': verify_result.get('reasoning', ''),
                'browser_type': content.browser_type,
                'content_depth': content.content_depth,
                'word_count': content.word_count,
                'extraction_method': 'unified_browser',
                'verified_at': datetime.now(timezone.utc).isoformat(),
            }

            # Update query
            update_fields = {
                'company_id': company['id'],
                'llm_verified': verify_result.get('legitimate', False),
                'verification_data': json.dumps(verification_data),
            }

            if std_result and std_result.get('success'):
                update_fields['standardized_name'] = std_result.get('name')
                update_fields['standardized_name_source'] = f"unified_browser_{std_result.get('source', 'llm')}"
                update_fields['standardized_name_confidence'] = std_result.get('confidence', 0.0)

            conn.execute(text("""
                UPDATE companies SET
                    llm_verified = :llm_verified,
                    parse_metadata = COALESCE(parse_metadata, '{}'::jsonb) ||
                        jsonb_build_object('verification', CAST(:verification_data AS JSONB)),
                    processing_started_at = NULL,
                    processing_worker_id = NULL
                WHERE id = :company_id
            """), update_fields)

            if std_result and std_result.get('success'):
                conn.execute(text("""
                    UPDATE companies SET
                        standardized_name = :standardized_name,
                        standardized_name_source = :standardized_name_source,
                        standardized_name_confidence = :standardized_name_confidence
                    WHERE id = :company_id
                """), update_fields)

            conn.commit()

    def _mark_failed(self, company: Dict, error: str):
        """Mark company as failed."""
        self.stats['errors'] += 1
        error_msg = str(error)[:200]
        with self.engine.connect() as conn:
            conn.execute(text("""
                UPDATE companies SET
                    parse_metadata = COALESCE(parse_metadata, '{}'::jsonb) ||
                        jsonb_build_object('unified_error', CAST(:error AS TEXT)),
                    processing_started_at = NULL,
                    processing_worker_id = NULL
                WHERE id = :company_id
            """), {'company_id': company['id'], 'error': error_msg})
            conn.commit()

    def _mark_as_citation(self, company: Dict, directory_domain: str):
        """
        Mark company as having a directory/citation URL instead of direct website.

        This is NOT an error - directory listings are valuable for SEO modules:
        - Citation tracking (NAP consistency)
        - Backlink analysis
        - Local SEO signals

        We mark llm_verified=false (not a direct business website) and also
        insert into the citations table for SEO module use.
        """
        listing_url = company.get('website', '')
        citation_data = {
            'type': 'citation_source',
            'directory': directory_domain,
            'url': listing_url,
            'detected_at': datetime.now(timezone.utc).isoformat(),
            'use_for_seo': True,
        }

        with self.engine.connect() as conn:
            # Update companies table
            conn.execute(text("""
                UPDATE companies SET
                    llm_verified = false,
                    parse_metadata = COALESCE(parse_metadata, '{}'::jsonb) ||
                        jsonb_build_object('citation_source', CAST(:citation_data AS JSONB)),
                    processing_started_at = NULL,
                    processing_worker_id = NULL
                WHERE id = :company_id
            """), {
                'company_id': company['id'],
                'citation_data': json.dumps(citation_data)
            })

            # Also insert into citations table for SEO modules
            conn.execute(text("""
                INSERT INTO citations (
                    directory_name,
                    directory_url,
                    listing_url,
                    business_name,
                    address,
                    phone,
                    discovered_at,
                    metadata
                ) VALUES (
                    :directory_name,
                    :directory_url,
                    :listing_url,
                    :business_name,
                    :address,
                    :phone,
                    NOW(),
                    :metadata
                )
                ON CONFLICT (directory_name, listing_url) DO UPDATE SET
                    last_verified_at = NOW(),
                    business_name = EXCLUDED.business_name
            """), {
                'directory_name': directory_domain,
                'directory_url': f'https://{directory_domain}',
                'listing_url': listing_url,
                'business_name': company.get('name', ''),
                'address': company.get('address', ''),
                'phone': company.get('phone', ''),
                'metadata': json.dumps({
                    'source': 'unified_browser_worker',
                    'company_id': company['id'],
                })
            })

            conn.commit()


def main():
    """Main entry point."""
    worker_id = int(os.getenv('UNIFIED_WORKER_ID', '1'))
    worker = UnifiedBrowserWorker(worker_id=worker_id)

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        worker.stop()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        worker.start()
    except KeyboardInterrupt:
        worker.stop()
    finally:
        logger.info(f"Worker stats: {worker.stats}")


if __name__ == '__main__':
    main()
