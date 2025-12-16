#!/usr/bin/env python3
"""
Parallel Batch Re-verification with Trained LLM

Uses multiple concurrent workers to speed up processing.
Ollama can handle concurrent requests - each request queues at the model level.
"""

import os
import sys
import json
import logging
import requests
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# Setup logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/batch_reverify_parallel.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Config
OLLAMA_URL = 'http://localhost:11434/api/generate'
MODEL = 'verification-mistral-proper'
NUM_WORKERS = 4  # Concurrent workers
BATCH_SIZE = 500  # Companies to fetch per batch
PROGRESS_INTERVAL = 100  # Log progress every N completions

SYSTEM_PROMPT = '''You are verifying if a business offers exterior cleaning services.
Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet/truck washing, Wood restoration/deck cleaning.
Based on the company name and website content, determine if this is a legitimate service provider.
Respond with ONLY a JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": [], "reasoning": "brief explanation"}'''


class ParallelBatchVerifier:
    def __init__(self, num_workers: int = 4):
        self.engine = create_engine(os.getenv('DATABASE_URL'))
        self.lock = Lock()
        self.processed = 0
        self.success = 0
        self.failed = 0
        self.verified_true = 0
        self.verified_false = 0
        self.start_time = None
        self.num_workers = num_workers

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

        # Build content from available data
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

            # Parse JSON from response
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
                return {'success': False, 'error': 'No JSON in response'}

        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'JSON parse error: {str(e)[:50]}'}
        except requests.Timeout:
            return {'success': False, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'error': str(e)[:50]}

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
                # Mark as processed but with error
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
        result = self.classify_company(company)
        self.update_company(company['id'], result)

        with self.lock:
            self.processed += 1
            if result['success']:
                self.success += 1
                if result['legitimate']:
                    self.verified_true += 1
                else:
                    self.verified_false += 1
            else:
                self.failed += 1

            # Log progress periodically
            if self.processed % PROGRESS_INTERVAL == 0:
                elapsed = time.time() - self.start_time
                rate = self.processed / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: {self.processed:,} | "
                    f"Rate: {rate:.1f}/sec | "
                    f"Verified: {self.verified_true:,} true, {self.verified_false:,} false | "
                    f"Errors: {self.failed:,}"
                )

        return company['id'], result['success']

    def run(self, total_limit: int = None):
        """Run parallel batch verification."""
        logger.info(f"Starting parallel batch verification with {self.num_workers} workers")
        logger.info(f"Model: {MODEL}")

        self.start_time = time.time()

        while True:
            # Fetch next batch
            companies = self.get_unprocessed_companies(BATCH_SIZE)

            if not companies:
                logger.info("No more companies to process")
                break

            logger.info(f"Processing batch of {len(companies)} companies...")

            # Process with thread pool
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                futures = {
                    executor.submit(self.process_company, company): company
                    for company in companies
                }

                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Worker error: {e}")

            # Check if we've hit the limit
            if total_limit and self.processed >= total_limit:
                logger.info(f"Reached limit of {total_limit}")
                break

        # Final summary
        elapsed = time.time() - self.start_time
        rate = self.processed / elapsed if elapsed > 0 else 0

        logger.info("=" * 60)
        logger.info("BATCH VERIFICATION COMPLETE")
        logger.info(f"Total processed: {self.processed:,}")
        logger.info(f"Verified True: {self.verified_true:,}")
        logger.info(f"Verified False: {self.verified_false:,}")
        logger.info(f"Errors: {self.failed:,}")
        logger.info(f"Total time: {elapsed/60:.1f} minutes")
        logger.info(f"Average rate: {rate:.1f}/sec")
        logger.info("=" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Parallel batch LLM verification')
    parser.add_argument('--limit', type=int, default=None, help='Maximum companies to process')
    parser.add_argument('--workers', type=int, default=4, help='Number of concurrent workers')
    args = parser.parse_args()

    num_workers = args.workers

    # Check Ollama is ready
    try:
        resp = requests.get('http://localhost:11434/api/tags', timeout=5)
        models = [m['name'] for m in resp.json().get('models', [])]
        if MODEL not in models and f'{MODEL}:latest' not in models:
            logger.error(f"Model {MODEL} not found in Ollama. Available: {models}")
            sys.exit(1)
        logger.info(f"Ollama ready with model: {MODEL}")
    except Exception as e:
        logger.error(f"Cannot connect to Ollama: {e}")
        sys.exit(1)

    verifier = ParallelBatchVerifier(num_workers=num_workers)
    verifier.run(total_limit=args.limit)


if __name__ == '__main__':
    main()
