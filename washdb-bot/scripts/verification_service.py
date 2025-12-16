#!/usr/bin/env python3
"""
Continuous LLM Verification Service

A long-running service that:
1. Continuously monitors for unverified companies
2. Maintains a heartbeat file for tracking state
3. Auto-resumes from where it left off on restart
4. Sleeps when no work available, wakes up to check for new companies
"""

import os
import sys
import json
import logging
import requests
import time
import signal
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# Setup logging - only to stdout (systemd will capture via StandardOutput)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Config
OLLAMA_URL = 'http://localhost:11434/api/generate'
MODEL = 'verification-mistral-proper'
NUM_WORKERS = 4
BATCH_SIZE = 500
PROGRESS_INTERVAL = 100
HEARTBEAT_FILE = 'data/verification_heartbeat.json'
HEARTBEAT_INTERVAL = 30  # seconds
POLL_INTERVAL = 60  # seconds to wait when no work found
MAX_RETRIES = 3

SYSTEM_PROMPT = '''You are verifying if a business offers exterior cleaning services.
Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet/truck washing, Wood restoration/deck cleaning.
Based on the company name and website content, determine if this is a legitimate service provider.
Respond with ONLY a JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": [], "reasoning": "brief explanation"}'''


class VerificationService:
    def __init__(self, num_workers: int = 4):
        self.engine = create_engine(os.getenv('DATABASE_URL'))
        self.lock = Lock()
        self.shutdown_event = Event()
        self.num_workers = num_workers

        # Stats (reset each session, but cumulative saved to heartbeat)
        self.session_processed = 0
        self.session_success = 0
        self.session_failed = 0
        self.session_verified_true = 0
        self.session_verified_false = 0
        self.session_start = None

        # Cumulative stats (loaded from heartbeat)
        self.total_processed = 0
        self.total_verified_true = 0
        self.total_verified_false = 0
        self.total_errors = 0

        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)

        # Load previous state
        self.load_heartbeat()

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_event.set()

    def load_heartbeat(self):
        """Load previous state from heartbeat file."""
        try:
            if os.path.exists(HEARTBEAT_FILE):
                with open(HEARTBEAT_FILE, 'r') as f:
                    data = json.load(f)
                    self.total_processed = data.get('total_processed', 0)
                    self.total_verified_true = data.get('total_verified_true', 0)
                    self.total_verified_false = data.get('total_verified_false', 0)
                    self.total_errors = data.get('total_errors', 0)
                    logger.info(f"Loaded heartbeat: {self.total_processed:,} total processed")
        except Exception as e:
            logger.warning(f"Could not load heartbeat: {e}")

    def save_heartbeat(self):
        """Save current state to heartbeat file."""
        try:
            data = {
                'last_updated': datetime.now().isoformat(),
                'status': 'running',
                'total_processed': self.total_processed,
                'total_verified_true': self.total_verified_true,
                'total_verified_false': self.total_verified_false,
                'total_errors': self.total_errors,
                'session_processed': self.session_processed,
                'session_start': self.session_start.isoformat() if self.session_start else None,
                'model': MODEL,
                'workers': self.num_workers,
            }

            # Get current queue size
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM companies WHERE llm_verified IS NULL
                """))
                data['pending_count'] = result.scalar()

            with open(HEARTBEAT_FILE, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Could not save heartbeat: {e}")

    def get_unprocessed_companies(self, limit: int) -> list:
        """Get companies that haven't been LLM verified yet."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, name, website, phone, services, parse_metadata
                FROM companies
                WHERE llm_verified IS NULL
                AND (website IS NOT NULL OR services IS NOT NULL OR name IS NOT NULL)
                ORDER BY id
                LIMIT :limit
            """), {'limit': limit})

            companies = []
            for row in result:
                companies.append({
                    'id': row[0],
                    'name': row[1],
                    'website': row[2],
                    'phone': row[3],
                    'services': row[4],
                    'parse_metadata': row[5] or {}
                })
            return companies

    def classify_company(self, company: dict) -> dict:
        """Send company to Ollama for classification."""
        meta = company.get('parse_metadata', {}) or {}

        title = meta.get('title', '')
        services_text = meta.get('services', '') or company.get('services', '') or ''
        about_text = meta.get('about', '') or ''
        homepage_text = (meta.get('homepage_text', '') or '')[:500]

        content = f"""Company: {company['name'] or 'Unknown'}
Website: {company['website'] or 'N/A'}
Title: {title or 'N/A'}
Services: {services_text[:300] if services_text else 'N/A'}
About: {about_text[:200] if about_text else 'N/A'}"""

        prompt = f'<s>[INST] {SYSTEM_PROMPT}\n\n{content} [/INST]'

        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.post(OLLAMA_URL, json={
                    'model': MODEL,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.1,
                        'num_predict': 200,
                    }
                }, timeout=60)

                response_text = resp.json().get('response', '')

                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    parsed = json.loads(response_text[json_start:json_end])
                    return {
                        'success': True,
                        'legitimate': parsed.get('legitimate', False),
                        'confidence': parsed.get('confidence', 0.5),
                        'services': parsed.get('services', []),
                        'reasoning': parsed.get('reasoning', '')[:200]
                    }
                else:
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(1)
                        continue
                    return {'success': False, 'error': 'No JSON in response'}

            except json.JSONDecodeError as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
                    continue
                return {'success': False, 'error': f'JSON parse error: {str(e)[:50]}'}
            except requests.Timeout:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2)
                    continue
                return {'success': False, 'error': 'Timeout'}
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
                    continue
                return {'success': False, 'error': str(e)[:50]}

        return {'success': False, 'error': 'Max retries exceeded'}

    def update_company(self, company_id: int, result: dict):
        """Update company with classification result."""
        with self.engine.connect() as conn:
            if result['success']:
                classification_data = json.dumps({
                    'llm_classification': {
                        'legitimate': result['legitimate'],
                        'confidence': result['confidence'],
                        'services': result['services'],
                        'reasoning': result['reasoning'],
                        'model': MODEL,
                        'verified_at': datetime.now().isoformat()
                    }
                })
                conn.execute(text("""
                    UPDATE companies
                    SET llm_verified = :verified,
                        llm_verified_at = :verified_at,
                        llm_confidence = :confidence,
                        parse_metadata = COALESCE(parse_metadata, '{}'::jsonb) || (:classification)::jsonb
                    WHERE id = :id
                """), {
                    'id': company_id,
                    'verified': result['legitimate'],
                    'verified_at': datetime.now(),
                    'confidence': result['confidence'],
                    'classification': classification_data
                })
            else:
                conn.execute(text("""
                    UPDATE companies
                    SET llm_verified = false,
                        llm_verified_at = :verified_at,
                        llm_confidence = 0
                    WHERE id = :id
                """), {
                    'id': company_id,
                    'verified_at': datetime.now()
                })
            conn.commit()

    def process_company(self, company: dict) -> tuple:
        """Process a single company (called by worker threads)."""
        if self.shutdown_event.is_set():
            return company['id'], False

        result = self.classify_company(company)
        self.update_company(company['id'], result)

        with self.lock:
            self.session_processed += 1
            self.total_processed += 1

            if result['success']:
                self.session_success += 1
                if result['legitimate']:
                    self.session_verified_true += 1
                    self.total_verified_true += 1
                else:
                    self.session_verified_false += 1
                    self.total_verified_false += 1
            else:
                self.session_failed += 1
                self.total_errors += 1

            if self.session_processed % PROGRESS_INTERVAL == 0:
                elapsed = time.time() - self.session_start.timestamp()
                rate = self.session_processed / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Session: {self.session_processed:,} | "
                    f"Total: {self.total_processed:,} | "
                    f"Rate: {rate:.1f}/sec | "
                    f"True: {self.session_verified_true:,} False: {self.session_verified_false:,} | "
                    f"Errors: {self.session_failed:,}"
                )
                self.save_heartbeat()

        return company['id'], result['success']

    def wait_for_ollama(self):
        """Wait for Ollama to be ready with the model."""
        logger.info(f"Waiting for Ollama with model {MODEL}...")
        while not self.shutdown_event.is_set():
            try:
                resp = requests.get('http://localhost:11434/api/tags', timeout=5)
                models = [m['name'] for m in resp.json().get('models', [])]
                if MODEL in models or f'{MODEL}:latest' in models:
                    logger.info(f"Ollama ready with model: {MODEL}")
                    return True
            except Exception as e:
                logger.debug(f"Ollama not ready: {e}")

            logger.info("Waiting for Ollama... (retrying in 10s)")
            self.shutdown_event.wait(10)

        return False

    def run(self):
        """Main service loop."""
        logger.info("=" * 60)
        logger.info("VERIFICATION SERVICE STARTING")
        logger.info(f"Workers: {self.num_workers}")
        logger.info(f"Model: {MODEL}")
        logger.info(f"Previous total: {self.total_processed:,} companies")
        logger.info("=" * 60)

        if not self.wait_for_ollama():
            logger.error("Ollama not available, shutting down")
            return

        self.session_start = datetime.now()
        last_heartbeat = time.time()

        while not self.shutdown_event.is_set():
            # Fetch next batch
            companies = self.get_unprocessed_companies(BATCH_SIZE)

            if not companies:
                logger.info(f"No unverified companies found, sleeping {POLL_INTERVAL}s...")
                self.save_heartbeat()
                self.shutdown_event.wait(POLL_INTERVAL)
                continue

            logger.info(f"Processing batch of {len(companies)} companies...")

            # Process with thread pool
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                futures = {
                    executor.submit(self.process_company, company): company
                    for company in companies
                }

                for future in as_completed(futures):
                    if self.shutdown_event.is_set():
                        break
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Worker error: {e}")

                    # Periodic heartbeat
                    if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
                        self.save_heartbeat()
                        last_heartbeat = time.time()

        # Final summary
        self.save_heartbeat()
        elapsed = (datetime.now() - self.session_start).total_seconds()
        rate = self.session_processed / elapsed if elapsed > 0 else 0

        logger.info("=" * 60)
        logger.info("VERIFICATION SERVICE STOPPED")
        logger.info(f"Session processed: {self.session_processed:,}")
        logger.info(f"Session rate: {rate:.1f}/sec")
        logger.info(f"Total all-time: {self.total_processed:,}")
        logger.info("=" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Continuous LLM verification service')
    parser.add_argument('--workers', type=int, default=4, help='Number of concurrent workers')
    args = parser.parse_args()

    service = VerificationService(num_workers=args.workers)
    service.run()


if __name__ == '__main__':
    main()
