#!/usr/bin/env python3
"""
Multi-Worker Standardization Pool

Runs multiple parallel standardization workers, each with its own browser.
Uses PostgreSQL row-level locking to prevent duplicate work.

This significantly speeds up standardization by parallelizing the browser work.

Usage:
    python scripts/standardization_worker_pool.py [--workers N]

Default: 3 workers (safe for typical system resources)
"""

import os
import sys
import time
import signal
import socket
import multiprocessing
import threading
import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=False)

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# Selenium imports
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium_stealth import stealth
from selenium.common.exceptions import TimeoutException, WebDriverException

# Import HeartbeatManager for watchdog integration
try:
    from services.heartbeat_manager import HeartbeatManager
    from db.database_manager import get_db_manager
    HEARTBEAT_MANAGER_AVAILABLE = True
except ImportError:
    HEARTBEAT_MANAGER_AVAILABLE = False

# Configuration
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434/api/generate')
MODEL_NAME = os.getenv('OLLAMA_MODEL', 'unified-washdb-v2')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://washbot:Washdb123@127.0.0.1:5432/washbot_db')
DISPLAY = os.getenv('DISPLAY', ':99')
LOG_DIR = Path(__file__).parent.parent / 'logs'

# Worker settings
DEFAULT_WORKERS = 3
PAGE_TIMEOUT = 15
MIN_DELAY = 1.5  # Seconds between requests (per worker)
MAX_DELAY = 3.0
MAX_ATTEMPTS = 5

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def setup_worker_logger(worker_id: int) -> logging.Logger:
    """Set up logging for a worker."""
    logger = logging.getLogger(f'std_worker_{worker_id}')
    logger.setLevel(logging.INFO)

    # Remove existing handlers
    logger.handlers = []

    # File handler
    log_file = LOG_DIR / f'standardization_worker_{worker_id}.log'
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(f'[W{worker_id}] %(message)s'))
    logger.addHandler(ch)

    return logger


def create_stealth_driver(worker_id: int, logger) -> Optional[Driver]:
    """Create a stealth Selenium browser for this worker."""
    try:
        user_agent = random.choice(USER_AGENTS)

        driver = Driver(
            uc=True,
            headless=False,  # Use Xvfb
            agent=user_agent,
            chromium_arg="--disable-gpu,--no-sandbox,--disable-dev-shm-usage",
        )

        # Apply stealth
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Linux",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        logger.info(f"Browser started successfully")
        return driver
    except Exception as e:
        logger.error(f"Failed to create browser: {e}")
        return None


def regex_fallback_standardize(original_name: str) -> Tuple[str, float]:
    """Simple regex-based standardization for fallback."""
    if not original_name or len(original_name) < 2:
        return original_name, 0.0

    name = original_name.strip()

    # Remove legal suffixes
    legal_suffixes = [
        r'\s*,?\s*LLC\.?$', r'\s*,?\s*L\.L\.C\.?$', r'\s*,?\s*Inc\.?$',
        r'\s*,?\s*Incorporated$', r'\s*,?\s*Corp\.?$', r'\s*,?\s*Corporation$',
        r'\s*,?\s*Co\.?$', r'\s*,?\s*Company$', r'\s*,?\s*Ltd\.?$',
        r'\s*,?\s*Limited$', r'\s*,?\s*P\.?C\.?$', r'\s*,?\s*PLLC\.?$',
    ]
    for suffix in legal_suffixes:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)

    # Clean whitespace
    name = ' '.join(name.split())

    # Convert to title case (preserve acronyms)
    words = name.split()
    result_words = []
    for word in words:
        if word.isupper() and 2 <= len(word) <= 4:
            result_words.append(word)
        elif any(c.isupper() for c in word[1:]):
            result_words.append(word)
        else:
            result_words.append(word.title())

    name = ' '.join(result_words)
    name = re.sub(r'\s+([,.])', r'\1', name)
    name = re.sub(r'([,.])\s*$', '', name)

    return name.strip(), 0.6


def call_llm_for_standardization(original_name: str, page_content: str, logger) -> Optional[Tuple[str, float]]:
    """Call LLM to standardize the business name."""
    import requests

    prompt = f"""Standardize this business name for a directory. Keep the original name but clean it up.

Original name: {original_name}

Website context (for reference only):
{page_content[:500]}

IMPORTANT: Return ONLY the cleaned business name. Do not add any explanation.
Remove legal suffixes like LLC, Inc.
Use proper title case.
Keep the original business name - do not replace it with something from the website.

Standardized name:"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 50}
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json().get('response', '').strip()

            # Block training artifacts
            if 'Proper Business Name' in result or result.count('\n') > 1:
                logger.warning(f"Blocked LLM artifact: {result[:50]}")
                return None

            # Clean up result
            result = result.split('\n')[0].strip()
            if len(result) > 2 and len(result) < 200:
                return result, 0.85

        return None
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        return None


def acquire_company_for_worker(engine, logger) -> Optional[dict]:
    """
    Acquire next company for standardization using row-level locking.

    Uses SELECT FOR UPDATE SKIP LOCKED to prevent duplicate work across workers.
    """
    with engine.connect() as conn:
        try:
            # Start transaction
            result = conn.execute(text('''
                SELECT id, name, website, domain_status, block_count, standardization_attempts
                FROM companies
                WHERE standardized_name IS NULL
                  AND (verified = true OR llm_verified = true)
                  AND website IS NOT NULL
                  AND name IS NOT NULL
                  AND LENGTH(name) > 2
                  AND (domain_status IS NULL OR domain_status != 'dead')
                  AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                  AND (standardization_attempts IS NULL OR standardization_attempts < :max_attempts)
                ORDER BY
                  CASE
                    WHEN (block_count IS NULL OR block_count = 0)
                         AND (domain_status IS NULL OR domain_status = 'alive')
                    THEN 0
                    ELSE 1
                  END,
                  COALESCE(standardization_attempts, 0),
                  id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            '''), {'max_attempts': MAX_ATTEMPTS})

            row = result.fetchone()

            if row:
                company = {
                    'id': row[0],
                    'name': row[1],
                    'website': row[2],
                    'domain_status': row[3],
                    'block_count': row[4] or 0,
                    'attempts': row[5] or 0
                }

                # Mark as in-progress (increment attempts)
                conn.execute(text('''
                    UPDATE companies
                    SET standardization_attempts = COALESCE(standardization_attempts, 0) + 1
                    WHERE id = :id
                '''), {'id': company['id']})

                conn.commit()
                return company

            return None

        except Exception as e:
            logger.error(f"Error acquiring company: {e}")
            conn.rollback()
            return None


def save_standardized_name(engine, company_id: int, std_name: str, confidence: float, source: str, logger):
    """Save standardized name to database."""
    with engine.connect() as conn:
        try:
            conn.execute(text('''
                UPDATE companies
                SET standardized_name = :std_name,
                    standardized_name_source = :source,
                    standardized_name_confidence = :confidence,
                    standardization_status = 'completed',
                    standardized_at = NOW(),
                    last_updated = NOW()
                WHERE id = :id
            '''), {
                'id': company_id,
                'std_name': std_name,
                'source': source,
                'confidence': confidence
            })
            conn.commit()
            logger.info(f"Saved: '{std_name}' (source: {source})")
        except Exception as e:
            logger.error(f"Error saving: {e}")
            conn.rollback()


def mark_company_failed(engine, company_id: int, error: str, logger):
    """Mark company as failed and set retry time."""
    with engine.connect() as conn:
        try:
            conn.execute(text('''
                UPDATE companies
                SET standardization_failures = COALESCE(standardization_failures, 0) + 1,
                    standardization_last_error = :error,
                    next_retry_at = NOW() + INTERVAL '1 hour',
                    last_updated = NOW()
                WHERE id = :id
            '''), {'id': company_id, 'error': error[:500]})
            conn.commit()
        except Exception as e:
            logger.error(f"Error marking failed: {e}")
            conn.rollback()


def fetch_page_content(driver, url: str, logger) -> Optional[str]:
    """Fetch page content using Selenium."""
    try:
        driver.set_page_load_timeout(PAGE_TIMEOUT)
        driver.get(url)
        time.sleep(2)  # Wait for JS

        # Get page content
        title = driver.title or ""

        # Get meta description
        desc = ""
        try:
            meta = driver.find_element(By.CSS_SELECTOR, 'meta[name="description"]')
            desc = meta.get_attribute('content') or ""
        except:
            pass

        # Get main heading
        h1 = ""
        try:
            h1_elem = driver.find_element(By.CSS_SELECTOR, 'h1')
            h1 = h1_elem.text or ""
        except:
            pass

        content = f"Title: {title}\nDescription: {desc}\nH1: {h1}"
        return content

    except TimeoutException:
        logger.warning(f"Timeout loading {url}")
        return None
    except WebDriverException as e:
        logger.warning(f"Browser error for {url}: {str(e)[:100]}")
        return None
    except Exception as e:
        logger.warning(f"Error fetching {url}: {e}")
        return None


def worker_main(worker_id: int, shutdown_event: multiprocessing.Event,
                shared_completed: multiprocessing.Value, shared_failed: multiprocessing.Value):
    """Main function for a single standardization worker."""

    logger = setup_worker_logger(worker_id)
    logger.info("=" * 60)
    logger.info(f"STANDARDIZATION WORKER {worker_id} STARTING")
    logger.info("=" * 60)

    # Set DISPLAY for browser
    os.environ['DISPLAY'] = DISPLAY

    # Create database engine
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=2,
        max_overflow=3,
        pool_recycle=3600
    )

    # Initialize browser
    driver = create_stealth_driver(worker_id, logger)
    if not driver:
        logger.error("Failed to create browser, exiting")
        return

    companies_processed = 0
    consecutive_empty = 0

    try:
        while not shutdown_event.is_set():
            # Acquire next company
            company = acquire_company_for_worker(engine, logger)

            if not company:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    logger.info("No pending companies, sleeping 60s...")
                    time.sleep(60)
                    consecutive_empty = 0
                else:
                    time.sleep(5)
                continue

            consecutive_empty = 0

            try:
                logger.info(f"Processing {company['id']}: {company['name'][:40]}")

                # Fetch page content
                url = company['website']
                if not url.startswith('http'):
                    url = 'https://' + url

                content = fetch_page_content(driver, url, logger)

                if content:
                    # Try LLM standardization
                    llm_result = call_llm_for_standardization(company['name'], content, logger)

                    if llm_result:
                        std_name, confidence = llm_result
                        save_standardized_name(engine, company['id'], std_name, confidence,
                                               'pool_llm', logger)
                    else:
                        # Fallback to regex
                        std_name, confidence = regex_fallback_standardize(company['name'])
                        save_standardized_name(engine, company['id'], std_name, confidence,
                                               'pool_regex_fallback', logger)
                else:
                    # Browser failed, use regex fallback
                    std_name, confidence = regex_fallback_standardize(company['name'])
                    save_standardized_name(engine, company['id'], std_name, confidence,
                                           'pool_browser_failed', logger)

                companies_processed += 1

                # Update shared counter
                with shared_completed.get_lock():
                    shared_completed.value += 1

                # Random delay between requests
                delay = random.uniform(MIN_DELAY, MAX_DELAY)
                time.sleep(delay)

            except Exception as e:
                logger.error(f"Error processing {company['id']}: {e}")
                mark_company_failed(engine, company['id'], str(e), logger)

                with shared_failed.get_lock():
                    shared_failed.value += 1

                # Restart browser on errors
                try:
                    driver.quit()
                except:
                    pass
                time.sleep(5)
                driver = create_stealth_driver(worker_id, logger)
                if not driver:
                    logger.error("Failed to restart browser, exiting")
                    break

    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down...")
    finally:
        logger.info("=" * 60)
        logger.info(f"WORKER {worker_id} FINAL STATS")
        logger.info(f"Companies processed: {companies_processed}")
        logger.info("=" * 60)

        try:
            driver.quit()
        except:
            pass

        engine.dispose()


def main():
    """Start the standardization worker pool."""
    import argparse

    parser = argparse.ArgumentParser(description='Multi-worker standardization pool')
    parser.add_argument('--workers', type=int, default=DEFAULT_WORKERS,
                        help=f'Number of workers (default: {DEFAULT_WORKERS})')
    args = parser.parse_args()

    worker_count = args.workers

    # Setup main logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_DIR / 'standardization_pool.log'),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger('std_pool')

    logger.info("=" * 70)
    logger.info("STANDARDIZATION WORKER POOL")
    logger.info("=" * 70)
    logger.info(f"Workers: {worker_count}")
    logger.info(f"Display: {DISPLAY}")
    logger.info("=" * 70)

    # Create shared counters
    shared_completed = multiprocessing.Value('i', 0)
    shared_failed = multiprocessing.Value('i', 0)
    shutdown_event = multiprocessing.Event()

    # Signal handler
    def signal_handler(signum, frame):
        logger.info(f"\nReceived signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start workers
    processes = []
    for worker_id in range(worker_count):
        logger.info(f"Starting worker {worker_id}...")

        p = multiprocessing.Process(
            target=worker_main,
            args=(worker_id, shutdown_event, shared_completed, shared_failed),
            name=f'std_worker_{worker_id}'
        )
        p.start()
        processes.append(p)
        time.sleep(2)  # Stagger browser starts

    logger.info(f"All {worker_count} workers started")

    # Monitor loop
    start_time = time.time()
    last_completed = 0

    try:
        while any(p.is_alive() for p in processes):
            time.sleep(30)

            with shared_completed.get_lock():
                completed = shared_completed.value
            with shared_failed.get_lock():
                failed = shared_failed.value

            elapsed = time.time() - start_time
            rate = completed / (elapsed / 60) if elapsed > 0 else 0

            new_completed = completed - last_completed
            last_completed = completed

            logger.info(f"Progress: {completed} done (+{new_completed}), {failed} failed | Rate: {rate:.1f}/min")

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt")
        shutdown_event.set()

    # Wait for workers
    logger.info("Waiting for workers to finish...")
    for p in processes:
        p.join(timeout=10)
        if p.is_alive():
            logger.warning(f"Force terminating {p.name}")
            p.terminate()

    with shared_completed.get_lock():
        final_completed = shared_completed.value
    with shared_failed.get_lock():
        final_failed = shared_failed.value

    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info("POOL FINAL STATS")
    logger.info("=" * 70)
    logger.info(f"Total completed: {final_completed}")
    logger.info(f"Total failed: {final_failed}")
    logger.info(f"Time elapsed: {elapsed:.1f} seconds")
    logger.info(f"Average rate: {final_completed / (elapsed / 60):.1f} companies/minute")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
