#!/usr/bin/env python3
"""
Verification Service V2 - Optimized GPU Utilization

Key improvements:
1. Prefetch queue - fetches next batch while current batch processes
2. Request pipelining - keeps GPU busy with constant request stream
3. Batch request coalescing - sends multiple prompts at once where possible
"""

import os
import sys
import json
import logging
import requests
import time
import signal
import queue
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Config
OLLAMA_URL = 'http://localhost:11434/api/generate'
MODEL = 'verification-mistral-proper'
NUM_WORKERS = 4
BATCH_SIZE = 100  # Smaller batches for faster prefetch cycling
PREFETCH_BATCHES = 2  # Number of batches to keep prefetched
PROGRESS_INTERVAL = 50
HEARTBEAT_FILE = 'data/verification_heartbeat.json'
HEARTBEAT_INTERVAL = 30
POLL_INTERVAL = 60
MAX_RETRIES = 3
REQUEST_TIMEOUT = 45  # Shorter timeout for faster failure detection

SYSTEM_PROMPT = '''You are verifying if a business offers exterior cleaning services.
Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet/truck washing, Wood restoration/deck cleaning.
Based on the company name and website content, determine if this is a legitimate service provider.
Respond with ONLY a JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": [], "reasoning": "brief explanation"}'''


class PrefetchQueue:
    """Background prefetch queue that stages companies ahead of processing."""

    def __init__(self, engine, max_queued: int = 500):
        self.engine = engine
        self.max_queued = max_queued
        self.queue = queue.Queue(maxsize=max_queued)
        self.fetched_ids = set()  # Track IDs already fetched to avoid duplicates
        self.lock = Lock()
        self.running = True
        self.fetch_thread = None
        self.last_id = 0  # Track last fetched ID for pagination

    def start(self):
        """Start background fetch thread."""
        self.fetch_thread = threading.Thread(target=self._fetch_loop, daemon=True)
        self.fetch_thread.start()
        logger.info(f"Prefetch queue started (max: {self.max_queued})")

    def stop(self):
        """Stop background fetch thread."""
        self.running = False
        if self.fetch_thread:
            self.fetch_thread.join(timeout=5)

    def _fetch_loop(self):
        """Background loop that keeps queue filled."""
        while self.running:
            try:
                # Fill queue when below threshold
                if self.queue.qsize() < self.max_queued // 2:
                    companies = self._fetch_batch(BATCH_SIZE)
                    if companies:
                        for company in companies:
                            if not self.running:
                                break
                            try:
                                self.queue.put(company, timeout=1)
                            except queue.Full:
                                break
                    else:
                        # No more companies, wait and check again
                        time.sleep(POLL_INTERVAL)
                else:
                    time.sleep(1)  # Queue is full enough
            except Exception as e:
                logger.error(f"Prefetch error: {e}")
                time.sleep(5)

    def _fetch_batch(self, limit: int) -> list:
        """Fetch a batch of unprocessed companies."""
        with self.lock:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id, name, website, phone, services, parse_metadata
                    FROM companies
                    WHERE llm_verified IS NULL
                    AND id > :last_id
                    AND (website IS NOT NULL OR services IS NOT NULL OR name IS NOT NULL)
                    ORDER BY id
                    LIMIT :limit
                """), {'last_id': self.last_id, 'limit': limit})

                companies = []
                for row in result:
                    company_id = row[0]
                    if company_id not in self.fetched_ids:
                        companies.append({
                            'id': company_id,
                            'name': row[1],
                            'website': row[2],
                            'phone': row[3],
                            'services': row[4],
                            'parse_metadata': row[5] or {}
                        })
                        self.fetched_ids.add(company_id)
                        self.last_id = max(self.last_id, company_id)

                return companies

    def get(self, timeout: float = 5.0):
        """Get next company from queue."""
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_batch(self, size: int, timeout: float = 10.0) -> list:
        """Get a batch of companies from queue."""
        companies = []
        deadline = time.time() + timeout

        while len(companies) < size and time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            company = self.get(timeout=min(1.0, remaining))
            if company:
                companies.append(company)

        return companies

    def mark_processed(self, company_id: int):
        """Mark company as processed (remove from tracking)."""
        with self.lock:
            self.fetched_ids.discard(company_id)

    def qsize(self) -> int:
        """Get current queue size."""
        return self.queue.qsize()


class VerificationServiceV2:
    def __init__(self, num_workers: int = 4):
        self.engine = create_engine(os.getenv('DATABASE_URL'))
        self.lock = Lock()
        self.shutdown_event = Event()
        self.num_workers = num_workers

        # Prefetch queue
        self.prefetch = PrefetchQueue(self.engine, max_queued=BATCH_SIZE * PREFETCH_BATCHES)

        # Stats
        self.session_processed = 0
        self.session_success = 0
        self.session_failed = 0
        self.session_verified_true = 0
        self.session_verified_false = 0
        self.session_start = None

        # Cumulative stats
        self.total_processed = 0
        self.total_verified_true = 0
        self.total_verified_false = 0
        self.total_errors = 0

        # Performance tracking
        self.request_times = []
        self.gpu_busy_since = None

        os.makedirs('data', exist_ok=True)
        self.load_heartbeat()

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown_event.set()
        self.prefetch.stop()

    def load_heartbeat(self):
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
        try:
            # Calculate avg request time
            avg_time = sum(self.request_times[-100:]) / len(self.request_times[-100:]) if self.request_times else 0

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
                'prefetch_queue_size': self.prefetch.qsize(),
                'avg_request_time_ms': int(avg_time * 1000),
            }

            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM companies WHERE llm_verified IS NULL"))
                data['pending_count'] = result.scalar()

            with open(HEARTBEAT_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save heartbeat: {e}")

    def classify_company(self, company: dict) -> dict:
        """Send company to Ollama for classification with timing."""
        meta = company.get('parse_metadata', {}) or {}

        title = meta.get('title', '')
        services_text = meta.get('services', '') or company.get('services', '') or ''
        about_text = meta.get('about', '') or ''

        content = f"""Company: {company['name'] or 'Unknown'}
Website: {company['website'] or 'N/A'}
Title: {title or 'N/A'}
Services: {services_text[:300] if services_text else 'N/A'}
About: {about_text[:200] if about_text else 'N/A'}"""

        prompt = f'<s>[INST] {SYSTEM_PROMPT}\n\n{content} [/INST]'

        start_time = time.time()

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
                }, timeout=REQUEST_TIMEOUT)

                elapsed = time.time() - start_time

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
                        'reasoning': parsed.get('reasoning', '')[:200],
                        'elapsed': elapsed
                    }
                else:
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(0.5)
                        continue
                    return {'success': False, 'error': 'No JSON', 'elapsed': elapsed}

            except json.JSONDecodeError as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(0.5)
                    continue
                return {'success': False, 'error': f'JSON error', 'elapsed': time.time() - start_time}
            except requests.Timeout:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
                    continue
                return {'success': False, 'error': 'Timeout', 'elapsed': time.time() - start_time}
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(0.5)
                    continue
                return {'success': False, 'error': str(e)[:30], 'elapsed': time.time() - start_time}

        return {'success': False, 'error': 'Max retries', 'elapsed': time.time() - start_time}

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
        """Process a single company."""
        if self.shutdown_event.is_set():
            return company['id'], False

        result = self.classify_company(company)
        self.update_company(company['id'], result)

        # Track request time
        if 'elapsed' in result:
            self.request_times.append(result['elapsed'])
            if len(self.request_times) > 1000:
                self.request_times = self.request_times[-500:]

        # Mark as processed in prefetch
        self.prefetch.mark_processed(company['id'])

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
                avg_time = sum(self.request_times[-50:]) / len(self.request_times[-50:]) if self.request_times else 0
                logger.info(
                    f"Session: {self.session_processed:,} | "
                    f"Total: {self.total_processed:,} | "
                    f"Rate: {rate:.1f}/sec | "
                    f"Avg: {avg_time*1000:.0f}ms | "
                    f"Queue: {self.prefetch.qsize()} | "
                    f"True: {self.session_verified_true:,} False: {self.session_verified_false:,}"
                )
                self.save_heartbeat()

        return company['id'], result['success']

    def wait_for_ollama(self):
        """Wait for Ollama to be ready."""
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
        """Main service loop with prefetch."""
        logger.info("=" * 60)
        logger.info("VERIFICATION SERVICE V2 STARTING")
        logger.info(f"Workers: {self.num_workers}")
        logger.info(f"Model: {MODEL}")
        logger.info(f"Prefetch queue size: {BATCH_SIZE * PREFETCH_BATCHES}")
        logger.info(f"Previous total: {self.total_processed:,} companies")
        logger.info("=" * 60)

        if not self.wait_for_ollama():
            logger.error("Ollama not available, shutting down")
            return

        # Start prefetch queue
        self.prefetch.start()

        # Give prefetch time to fill initial queue
        logger.info("Waiting for prefetch queue to fill...")
        time.sleep(3)

        self.session_start = datetime.now()
        last_heartbeat = time.time()
        empty_cycles = 0

        while not self.shutdown_event.is_set():
            # Get batch from prefetch queue
            companies = self.prefetch.get_batch(BATCH_SIZE, timeout=5)

            if not companies:
                empty_cycles += 1
                if empty_cycles >= 3:
                    logger.info(f"No unverified companies, sleeping {POLL_INTERVAL}s...")
                    self.save_heartbeat()
                    self.shutdown_event.wait(POLL_INTERVAL)
                    empty_cycles = 0
                continue

            empty_cycles = 0
            logger.debug(f"Processing batch of {len(companies)} companies (queue: {self.prefetch.qsize()})")

            # Process with thread pool - continuous flow
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

                    if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
                        self.save_heartbeat()
                        last_heartbeat = time.time()

        # Cleanup
        self.prefetch.stop()
        self.save_heartbeat()

        elapsed = (datetime.now() - self.session_start).total_seconds()
        rate = self.session_processed / elapsed if elapsed > 0 else 0

        logger.info("=" * 60)
        logger.info("VERIFICATION SERVICE V2 STOPPED")
        logger.info(f"Session processed: {self.session_processed:,}")
        logger.info(f"Session rate: {rate:.1f}/sec")
        logger.info(f"Total all-time: {self.total_processed:,}")
        logger.info("=" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Optimized LLM verification service')
    parser.add_argument('--workers', type=int, default=4, help='Number of concurrent workers')
    args = parser.parse_args()

    service = VerificationServiceV2(num_workers=args.workers)
    service.run()


if __name__ == '__main__':
    main()
