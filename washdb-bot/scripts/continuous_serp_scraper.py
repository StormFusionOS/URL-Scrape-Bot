#!/usr/bin/env python3
"""
Continuous SERP Scraper for Verified Companies

Runs continuously in a loop, scraping verified company URLs at slow rate (1-2 sites/hour).
After completing all verified URLs, rests for 60 minutes then starts over.

Features:
- Ultra-slow rate limits (30-60 minutes between requests) to avoid detection
- CAPTCHA cooldown: pauses if too many consecutive CAPTCHAs detected
- Auto-resumes on restart (tracks last scraped company)
- Systemd service compatible for auto-restart on reboot
- Comprehensive logging and progress tracking

Usage:
    python scripts/continuous_serp_scraper.py [--dry-run] [--max-consecutive-captchas 3]
"""

import sys
import os
import time
import random
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from db.database_manager import DatabaseManager
from seo_intelligence.scrapers.serp_scraper import SerpScraper
from runner.logging_setup import get_logger

logger = get_logger("continuous_serp_scraper")


class ContinuousSerpScraper:
    """
    Continuous SERP scraper for verified company URLs.

    Runs at ultra-slow rate (1-2 sites/hour) to minimize detection.
    Implements CAPTCHA cooldown and cycle-based operation.
    """

    # Rate limits: 30-60 minutes per site (1-2 sites/hour)
    MIN_DELAY_SECONDS = 1800  # 30 minutes
    MAX_DELAY_SECONDS = 3600  # 60 minutes

    # Cycle rest period: 60 minutes after completing all sites
    CYCLE_REST_SECONDS = 3600  # 60 minutes

    # CAPTCHA cooldown settings
    DEFAULT_MAX_CONSECUTIVE_CAPTCHAS = 3  # Pause after 3 consecutive CAPTCHAs
    CAPTCHA_COOLDOWN_SECONDS = 7200  # 2 hour cooldown

    # Progress tracking file
    PROGRESS_FILE = "/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/.serp_scraper_progress.json"

    def __init__(self, max_consecutive_captchas: int = 3, dry_run: bool = False):
        """Initialize continuous scraper."""
        self.db = DatabaseManager()
        self.scraper = SerpScraper(
            headless=True,  # Hybrid mode
            use_proxy=False,  # Disabled: datacenter proxies get detected
            store_raw_html=True,
            enable_embeddings=True
        )

        self.max_consecutive_captchas = max_consecutive_captchas
        self.dry_run = dry_run

        # Stats tracking
        self.cycle_num = 0
        self.total_scraped = 0
        self.total_captchas = 0
        self.consecutive_captchas = 0
        self.captcha_cooldowns = 0

        # Load progress
        self.last_scraped_id = self._load_progress()

        logger.info(f"Continuous SERP Scraper Initialized")
        logger.info(f"Rate limit: {self.MIN_DELAY_SECONDS//60}-{self.MAX_DELAY_SECONDS//60} minutes per site")
        logger.info(f"Cycle rest: {self.CYCLE_REST_SECONDS//60} minutes")
        logger.info(f"CAPTCHA threshold: {self.max_consecutive_captchas} consecutive")
        logger.info(f"Dry run: {self.dry_run}")
        if self.last_scraped_id:
            logger.info(f"Resuming from company ID: {self.last_scraped_id}")

    def _load_progress(self) -> Optional[int]:
        """Load last scraped company ID from progress file."""
        if not os.path.exists(self.PROGRESS_FILE):
            return None

        try:
            with open(self.PROGRESS_FILE, 'r') as f:
                data = json.load(f)
                return data.get('last_scraped_id')
        except Exception as e:
            logger.warning(f"Failed to load progress: {e}")
            return None

    def _save_progress(self, company_id: int):
        """Save progress to file."""
        try:
            data = {
                'last_scraped_id': company_id,
                'last_updated': datetime.now().isoformat(),
                'cycle_num': self.cycle_num,
                'total_scraped': self.total_scraped,
                'total_captchas': self.total_captchas,
            }

            with open(self.PROGRESS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")

    def _reset_progress(self):
        """Reset progress to start new cycle."""
        self.last_scraped_id = None
        try:
            if os.path.exists(self.PROGRESS_FILE):
                os.remove(self.PROGRESS_FILE)
        except Exception as e:
            logger.warning(f"Failed to reset progress file: {e}")

    def _get_verified_companies(self) -> List[Dict]:
        """
        Get all verified companies with websites.

        Returns companies in order, starting after last_scraped_id if resuming.
        """
        with self.db.get_session() as session:
            # Build query
            query = """
                SELECT
                    c.id,
                    c.name,
                    c.website,
                    c.address
                FROM companies c
                WHERE c.parse_metadata->'verification'->>'status' = 'passed'
                AND c.website IS NOT NULL
                AND c.active = true
            """

            # Add resume clause if needed
            if self.last_scraped_id:
                query += f" AND c.id > {self.last_scraped_id}"

            query += " ORDER BY c.id"

            result = session.execute(text(query))
            companies = []
            for row in result:
                companies.append({
                    'id': row[0],
                    'name': row[1],
                    'website': row[2],
                    'address': row[3],
                })

            return companies

    def _build_search_query(self, company: Dict) -> str:
        """
        Build Google search query for company.

        Query format: "company name" address
        """
        name = company['name']
        address = company.get('address', '')

        # Quote company name for exact match
        query = f'"{name}"'

        # Add location context from address
        if address:
            query += f' {address}'

        return query

    def _detect_captcha(self, snapshot) -> bool:
        """
        Detect if CAPTCHA was encountered.

        Returns True if CAPTCHA detected, False otherwise.
        """
        # If snapshot is None, likely hit CAPTCHA or error
        if snapshot is None:
            return True

        # If very few results, might be CAPTCHA page
        if len(snapshot.results) < 3:
            return True

        return False

    def _handle_captcha(self):
        """Handle CAPTCHA detection with cooldown logic."""
        self.total_captchas += 1
        self.consecutive_captchas += 1

        logger.warning(f"CAPTCHA detected ({self.consecutive_captchas}/{self.max_consecutive_captchas} consecutive)")

        if self.consecutive_captchas >= self.max_consecutive_captchas:
            # Trigger cooldown
            self.captcha_cooldowns += 1
            logger.warning(f"⏸️  CAPTCHA threshold reached! Entering cooldown for {self.CAPTCHA_COOLDOWN_SECONDS//3600} hours")
            logger.warning(f"Cooldown started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.warning(f"Will resume at: {(datetime.now() + timedelta(seconds=self.CAPTCHA_COOLDOWN_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')}")

            # Sleep for cooldown period
            time.sleep(self.CAPTCHA_COOLDOWN_SECONDS)

            # Reset consecutive counter
            self.consecutive_captchas = 0
            logger.info("Cooldown complete. Resuming scraping...")

    def _scrape_company(self, company: Dict) -> bool:
        """
        Scrape SERP for a single company.

        Returns True if successful, False if CAPTCHA or error.
        """
        query = self._build_search_query(company)
        location = company.get('address', '')

        logger.info("="*80)
        logger.info(f"Scraping company {company['id']}: {company['name']}")
        logger.info(f"Query: {query}")
        logger.info(f"Location: {location}")
        logger.info(f"Website: {company['website']}")

        if self.dry_run:
            logger.info("[DRY RUN] Would scrape here")
            return True

        try:
            # Scrape SERP
            snapshot = self.scraper.scrape_query(
                query=query,
                location=location,
                our_domains=[company['website'].replace('http://', '').replace('https://', '').split('/')[0]],
            )

            # Check for CAPTCHA
            if self._detect_captcha(snapshot):
                self._handle_captcha()
                return False

            # Success - reset consecutive CAPTCHA counter
            self.consecutive_captchas = 0

            # Log results
            if snapshot and snapshot.results:
                logger.info(f"✓ Scraped {len(snapshot.results)} results")

                # Check if our domain appears in results
                our_domain = company['website'].replace('http://', '').replace('https://', '').split('/')[0]
                for result in snapshot.results:
                    if our_domain in result.domain:
                        logger.info(f"  ✓ Found at position {result.position}: {result.url}")
            else:
                logger.warning(f"No results returned (may be CAPTCHA)")
                return False

            return True

        except Exception as e:
            logger.error(f"Error scraping company {company['id']}: {e}", exc_info=True)
            return False

    def _random_delay(self):
        """Wait random delay between MIN_DELAY_SECONDS and MAX_DELAY_SECONDS."""
        delay_seconds = random.randint(self.MIN_DELAY_SECONDS, self.MAX_DELAY_SECONDS)
        delay_minutes = delay_seconds / 60

        resume_time = datetime.now() + timedelta(seconds=delay_seconds)

        logger.info(f"⏳ Waiting {delay_minutes:.1f} minutes before next scrape")
        logger.info(f"Next scrape at: {resume_time.strftime('%Y-%m-%d %H:%M:%S')}")

        if not self.dry_run:
            time.sleep(delay_seconds)
        else:
            logger.info("[DRY RUN] Skipping delay")

    def run_cycle(self):
        """Run a single scraping cycle (all verified companies)."""
        self.cycle_num += 1

        logger.info("")
        logger.info("="*80)
        logger.info(f"CYCLE {self.cycle_num} STARTING")
        logger.info("="*80)
        logger.info("")

        # Get companies to scrape
        companies = self._get_verified_companies()

        if not companies:
            logger.info("No companies to scrape (all caught up!)")
            # Reset progress to start from beginning next cycle
            self._reset_progress()
            return

        logger.info(f"Found {len(companies)} companies to scrape")
        if self.last_scraped_id:
            logger.info(f"Resuming from company ID {self.last_scraped_id}")

        cycle_start = datetime.now()
        cycle_scraped = 0
        cycle_failed = 0

        # Scrape each company
        for i, company in enumerate(companies, 1):
            logger.info(f"\nCompany {i}/{len(companies)} (Cycle {self.cycle_num})")

            # Scrape
            success = self._scrape_company(company)

            if success:
                cycle_scraped += 1
                self.total_scraped += 1
            else:
                cycle_failed += 1

            # Save progress
            self._save_progress(company['id'])

            # Delay before next scrape (unless last one)
            if i < len(companies):
                self._random_delay()

        # Cycle complete
        cycle_duration = datetime.now() - cycle_start

        logger.info("")
        logger.info("="*80)
        logger.info(f"CYCLE {self.cycle_num} COMPLETE")
        logger.info("="*80)
        logger.info(f"Duration: {cycle_duration}")
        logger.info(f"Scraped: {cycle_scraped}")
        logger.info(f"Failed: {cycle_failed}")
        logger.info(f"CAPTCHAs this cycle: {self.total_captchas - (getattr(self, '_last_cycle_captchas', 0))}")
        logger.info(f"Total scraped (all cycles): {self.total_scraped}")
        logger.info(f"Total CAPTCHAs (all cycles): {self.total_captchas}")
        logger.info(f"Total cooldowns (all cycles): {self.captcha_cooldowns}")
        logger.info("")

        self._last_cycle_captchas = self.total_captchas

        # Reset progress for next cycle
        self._reset_progress()

    def run(self):
        """Run continuous scraper forever."""
        logger.info("")
        logger.info("="*80)
        logger.info("CONTINUOUS SERP SCRAPER STARTING")
        logger.info("="*80)
        logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("")

        try:
            while True:
                # Run cycle
                self.run_cycle()

                # Rest before next cycle
                logger.info(f"⏸️  Resting for {self.CYCLE_REST_SECONDS//60} minutes before next cycle")
                resume_time = datetime.now() + timedelta(seconds=self.CYCLE_REST_SECONDS)
                logger.info(f"Next cycle starts at: {resume_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info("")

                if not self.dry_run:
                    time.sleep(self.CYCLE_REST_SECONDS)
                else:
                    logger.info("[DRY RUN] Skipping cycle rest")
                    break  # Exit after one cycle in dry run

        except KeyboardInterrupt:
            logger.info("")
            logger.info("Interrupted by user. Shutting down gracefully...")
            logger.info(f"Total scraped: {self.total_scraped}")
            logger.info(f"Total CAPTCHAs: {self.total_captchas}")
            logger.info(f"Total cooldowns: {self.captcha_cooldowns}")
            logger.info("Progress saved. Can resume later.")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            raise


def main():
    parser = argparse.ArgumentParser(description='Continuous SERP scraper for verified companies')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (no actual scraping)')
    parser.add_argument('--max-consecutive-captchas', type=int, default=3, help='Max consecutive CAPTCHAs before cooldown')
    args = parser.parse_args()

    scraper = ContinuousSerpScraper(
        max_consecutive_captchas=args.max_consecutive_captchas,
        dry_run=args.dry_run
    )
    scraper.run()


if __name__ == '__main__':
    main()
