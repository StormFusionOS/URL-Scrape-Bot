#!/usr/bin/env python3
"""
Lightweight Domain Health Checker

Runs DNS lookups to pre-filter dead domains before browser fetches.
This eliminates ~23% of standardization failures from ERR_NAME_NOT_RESOLVED.

Run as a background service or periodically via cron.
"""

import os
import sys
import socket
import time
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Setup
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/domain_checker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
BATCH_SIZE = 500
CHECK_THREADS = 20
DNS_TIMEOUT = 5  # seconds
RECHECK_INTERVAL_DAYS = 7  # Recheck domains after this many days


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    if not url:
        return None
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split('/')[0]
    except Exception:
        return None


def check_domain_dns(domain: str) -> tuple:
    """
    Check if domain resolves via DNS.
    Returns (domain, is_alive, error_message)
    """
    if not domain:
        return (domain, False, 'empty_domain')

    try:
        socket.setdefaulttimeout(DNS_TIMEOUT)
        socket.gethostbyname(domain)
        return (domain, True, None)
    except socket.gaierror as e:
        return (domain, False, f'dns_failed: {e}')
    except socket.timeout:
        return (domain, False, 'dns_timeout')
    except Exception as e:
        return (domain, False, f'error: {e}')


def get_companies_to_check(engine, limit: int = BATCH_SIZE) -> list:
    """
    Get companies that need domain health checking.
    Prioritizes:
    1. Never checked (domain_status = 'unknown')
    2. Checked but stale (last_domain_check > RECHECK_INTERVAL_DAYS ago)
    """
    recheck_cutoff = datetime.now() - timedelta(days=RECHECK_INTERVAL_DAYS)

    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT id, website, domain
            FROM companies
            WHERE website IS NOT NULL
              AND standardized_name IS NULL
              AND (verified = true OR llm_verified = true)
              AND (
                  domain_status = 'unknown'
                  OR domain_status IS NULL
                  OR (last_domain_check IS NULL)
                  OR (last_domain_check < :recheck_cutoff AND domain_status != 'dead')
              )
            ORDER BY
                CASE WHEN domain_status = 'unknown' OR domain_status IS NULL THEN 0 ELSE 1 END,
                last_domain_check NULLS FIRST
            LIMIT :limit
        '''), {'limit': limit, 'recheck_cutoff': recheck_cutoff})

        companies = []
        for row in result:
            domain = row[2] or extract_domain(row[1])
            companies.append({
                'id': row[0],
                'website': row[1],
                'domain': domain
            })
        return companies


def update_domain_status(engine, company_id: int, status: str, error: str = None):
    """Update company's domain status."""
    with engine.connect() as conn:
        conn.execute(text('''
            UPDATE companies
            SET domain_status = :status,
                last_domain_check = NOW()
            WHERE id = :id
        '''), {'id': company_id, 'status': status})
        conn.commit()


def batch_update_domain_status(engine, updates: list):
    """Batch update domain statuses for efficiency."""
    with engine.connect() as conn:
        for company_id, status in updates:
            conn.execute(text('''
                UPDATE companies
                SET domain_status = :status,
                    last_domain_check = NOW()
                WHERE id = :id
            '''), {'id': company_id, 'status': status})
        conn.commit()


def check_domains_batch(companies: list) -> dict:
    """
    Check multiple domains in parallel using thread pool.
    Returns dict mapping company_id to (is_alive, error)
    """
    results = {}

    # Group by domain to avoid duplicate lookups
    domain_to_companies = {}
    for company in companies:
        domain = company['domain']
        if domain:
            if domain not in domain_to_companies:
                domain_to_companies[domain] = []
            domain_to_companies[domain].append(company['id'])

    # Check unique domains in parallel
    domain_results = {}
    with ThreadPoolExecutor(max_workers=CHECK_THREADS) as executor:
        futures = {
            executor.submit(check_domain_dns, domain): domain
            for domain in domain_to_companies.keys()
        }

        for future in as_completed(futures):
            domain = futures[future]
            try:
                _, is_alive, error = future.result()
                domain_results[domain] = (is_alive, error)
            except Exception as e:
                domain_results[domain] = (False, str(e))

    # Map results back to company IDs
    for domain, company_ids in domain_to_companies.items():
        is_alive, error = domain_results.get(domain, (False, 'unknown'))
        for company_id in company_ids:
            results[company_id] = (is_alive, error)

    # Handle companies with no domain
    for company in companies:
        if not company['domain']:
            results[company['id']] = (False, 'no_domain')

    return results


def run_domain_checker(engine, single_pass: bool = False, batch_size: int = None):
    """
    Main domain checking loop.

    Args:
        engine: SQLAlchemy engine
        single_pass: If True, run once and exit. If False, run continuously.
        batch_size: Number of companies to check per batch
    """
    if batch_size is None:
        batch_size = BATCH_SIZE

    logger.info("=" * 60)
    logger.info("DOMAIN HEALTH CHECKER STARTING")
    logger.info("=" * 60)
    logger.info(f"Batch size: {batch_size}")
    logger.info(f"Check threads: {CHECK_THREADS}")
    logger.info(f"DNS timeout: {DNS_TIMEOUT}s")
    logger.info(f"Recheck interval: {RECHECK_INTERVAL_DAYS} days")

    total_checked = 0
    total_alive = 0
    total_dead = 0

    while True:
        companies = get_companies_to_check(engine, limit=batch_size)

        if not companies:
            if single_pass:
                logger.info("No more companies to check. Exiting.")
                break
            logger.info("No companies to check. Sleeping 5 minutes...")
            time.sleep(300)
            continue

        logger.info(f"Checking {len(companies)} domains...")

        # Check domains in parallel
        results = check_domains_batch(companies)

        # Prepare batch updates
        updates = []
        batch_alive = 0
        batch_dead = 0

        for company_id, (is_alive, error) in results.items():
            if is_alive:
                status = 'alive'
                batch_alive += 1
            else:
                status = 'dead'
                batch_dead += 1
                logger.debug(f"Dead domain for company {company_id}: {error}")

            updates.append((company_id, status))

        # Batch update database
        batch_update_domain_status(engine, updates)

        total_checked += len(companies)
        total_alive += batch_alive
        total_dead += batch_dead

        logger.info(f"Batch complete: {batch_alive} alive, {batch_dead} dead")
        logger.info(f"Total: {total_checked} checked, {total_alive} alive ({total_alive/total_checked*100:.1f}%), {total_dead} dead ({total_dead/total_checked*100:.1f}%)")

        if single_pass:
            continue  # Keep going until queue empty

        # Brief pause between batches
        time.sleep(1)

    logger.info("=" * 60)
    logger.info("DOMAIN HEALTH CHECKER COMPLETE")
    logger.info(f"Total checked: {total_checked}")
    logger.info(f"Alive: {total_alive} ({total_alive/max(total_checked,1)*100:.1f}%)")
    logger.info(f"Dead: {total_dead} ({total_dead/max(total_checked,1)*100:.1f}%)")
    logger.info("=" * 60)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Domain Health Checker')
    parser.add_argument('--single-pass', action='store_true',
                       help='Run once through queue and exit')
    parser.add_argument('--batch-size', type=int, default=500,
                       help='Batch size (default: 500)')
    args = parser.parse_args()

    engine = create_engine(os.getenv('DATABASE_URL'))

    try:
        run_domain_checker(engine, single_pass=args.single_pass, batch_size=args.batch_size)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
