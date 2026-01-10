#!/usr/bin/env python3
"""
Batch re-verification using the unified LLM.

Runs the unified-washdb model on all companies
in the database and updates their llm_verified flag.

Features:
- Processes companies in batches with progress tracking
- Stores results in a new column (llm_verified) to preserve old data
- Resumable (tracks processed IDs)
- Progress logging with ETA
- Saves full classification to parse_metadata

Usage:
    python scripts/batch_reverify_with_trained_llm.py [--batch-size 100] [--limit 1000]
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/batch_reverify.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BatchReverifier:
    """Batch re-verification using trained LLM."""

    SYSTEM_PROMPT = """You are verifying if a business offers exterior cleaning services.

Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet/truck washing, Wood restoration/deck cleaning.

Based on the company name and website content, determine if this is a legitimate service provider.

Respond with ONLY a JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": [], "reasoning": "brief explanation"}"""

    def __init__(self, batch_size: int = 100, limit: int = None):
        self.batch_size = batch_size
        self.limit = limit
        self.engine = create_engine(os.getenv('DATABASE_URL'))

        # Ollama settings
        self.ollama_url = "http://localhost:11434/api/generate"
        self.model = os.getenv("OLLAMA_MODEL", "unified-washdb-v2")

        # Progress tracking
        self.processed = 0
        self.successes = 0
        self.failures = 0
        self.start_time = None

        # Results file for resumability
        self.progress_file = "logs/batch_reverify_progress.json"

    def ensure_column_exists(self):
        """Ensure llm_verified column exists."""
        with self.engine.connect() as conn:
            conn.execute(text('''
                ALTER TABLE companies
                ADD COLUMN IF NOT EXISTS llm_verified BOOLEAN DEFAULT NULL
            '''))
            conn.execute(text('''
                ALTER TABLE companies
                ADD COLUMN IF NOT EXISTS llm_verified_at TIMESTAMP DEFAULT NULL
            '''))
            conn.execute(text('''
                ALTER TABLE companies
                ADD COLUMN IF NOT EXISTS llm_confidence NUMERIC(3,2) DEFAULT NULL
            '''))
            conn.commit()
            logger.info("Ensured llm_verified, llm_verified_at, llm_confidence columns exist")

    def get_companies_to_process(self, offset: int = 0) -> list:
        """Get batch of companies to process."""
        with self.engine.connect() as conn:
            # Get companies that haven't been llm_verified yet
            # Prioritize those with parse_metadata (more content to analyze)
            query = text('''
                SELECT id, name, website, phone, services, parse_metadata
                FROM companies
                WHERE llm_verified IS NULL
                AND website IS NOT NULL
                ORDER BY
                    CASE WHEN parse_metadata IS NOT NULL THEN 0 ELSE 1 END,
                    id
                LIMIT :limit OFFSET :offset
            ''')

            result = conn.execute(query, {'limit': self.batch_size, 'offset': offset})

            companies = []
            for row in result:
                companies.append({
                    'id': row[0],
                    'name': row[1],
                    'website': row[2],
                    'phone': row[3],
                    'services': row[4],
                    'parse_metadata': row[5]
                })

            return companies

    def get_remaining_count(self) -> int:
        """Get count of companies not yet processed."""
        with self.engine.connect() as conn:
            result = conn.execute(text('''
                SELECT COUNT(*) FROM companies
                WHERE llm_verified IS NULL AND website IS NOT NULL
            '''))
            return result.scalar()

    def build_prompt(self, company: dict) -> str:
        """Build prompt for the trained model."""
        meta = company.get('parse_metadata') or {}

        # Extract content from metadata
        title = meta.get('title', '')
        services_text = meta.get('services', '') or company.get('services', '') or ''
        about_text = meta.get('about', '') or ''
        homepage_text = meta.get('homepage_text', '') or ''

        # Truncate to reasonable lengths
        homepage_text = homepage_text[:800]
        services_text = services_text[:500]
        about_text = about_text[:300]

        prompt = f"Company: {company['name']}\n"
        prompt += f"Website: {company['website']}\n"

        if company.get('phone'):
            prompt += f"Phone: {company['phone']}\n"

        if title:
            prompt += f"Page title: {title}\n"

        if homepage_text:
            prompt += f"\nHomepage excerpt:\n{homepage_text}\n"

        if services_text:
            prompt += f"\nServices:\n{services_text}\n"
        elif about_text:
            prompt += f"\nAbout:\n{about_text}\n"

        prompt += "\nDoes this company provide exterior cleaning services? Assess if legitimate."

        return prompt

    def classify_company(self, company: dict) -> dict:
        """Classify a single company using the trained model."""
        prompt = self.build_prompt(company)
        full_prompt = f"<s>[INST] {self.SYSTEM_PROMPT}\n\n{prompt} [/INST]"

        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 250,
            }
        }

        try:
            response = requests.post(self.ollama_url, json=payload, timeout=45)
            response.raise_for_status()
            result = response.json()
            response_text = result.get("response", "").strip()

            # Parse JSON from response using robust extraction
            parsed = self._extract_json(response_text)

            if parsed:
                return {
                    'success': True,
                    'legitimate': parsed.get('legitimate', False),
                    'confidence': float(parsed.get('confidence', 0.5)),
                    'services': parsed.get('services', []),
                    'reasoning': str(parsed.get('reasoning', ''))[:200],
                    'raw': response_text[:200]
                }
            else:
                # Fallback: try to infer from text
                fallback = self._fallback_parse(response_text)
                if fallback:
                    return fallback
                return {
                    'success': False,
                    'error': 'No valid JSON in response',
                    'raw': response_text[:200]
                }

        except requests.Timeout:
            return {'success': False, 'error': 'timeout'}
        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'JSON parse error: {e}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _extract_json(self, text: str) -> dict:
        """Extract first valid JSON object from text with robust parsing."""
        import re

        # Clean up common artifacts
        text = text.replace('<|im_start|>', ' ').replace('<|im_end|>', ' ')
        text = re.sub(r'\s+', ' ', text)

        # Try to find JSON with balanced braces
        brace_count = 0
        json_start = -1

        for i, char in enumerate(text):
            if char == '{':
                if brace_count == 0:
                    json_start = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and json_start >= 0:
                    json_str = text[json_start:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        # Try to fix common issues
                        json_str = self._fix_json(json_str)
                        try:
                            return json.loads(json_str)
                        except:
                            json_start = -1  # Reset and try next

        return None

    def _fix_json(self, json_str: str) -> str:
        """Fix common JSON issues."""
        import re
        # Fix unquoted true/false
        json_str = re.sub(r':\s*true\b', ': true', json_str)
        json_str = re.sub(r':\s*false\b', ': false', json_str)
        # Fix trailing commas
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        return json_str

    def _fallback_parse(self, text: str) -> dict:
        """Fallback parsing when JSON extraction fails."""
        text_lower = text.lower()

        # Dead website / error page patterns (memorized from training data)
        dead_site_phrases = [
            'website is no longer available',
            'domain has expired',
            'page not found',
            'this site is under construction',
            'coming soon',
            'placeholder',
            'contact your customer service',
            'webstarts.com',
            'yext knowledge tags',
            'this message will not appear',
            'link to the website',
            'appears to be a website link',
            'actual business name is not provided'
        ]
        if any(phrase in text_lower for phrase in dead_site_phrases):
            return {
                'success': True,
                'legitimate': False,
                'confidence': 0.4,
                'services': [],
                'reasoning': 'Dead or unavailable website',
                'raw': text[:200]
            }

        # Negative indicators
        if any(phrase in text_lower for phrase in [
            'not a valid', 'not legitimate', 'does not provide',
            'not an exterior', 'no evidence', 'not offer',
            'not a business', 'no information', 'insufficient data'
        ]):
            return {
                'success': True,
                'legitimate': False,
                'confidence': 0.5,
                'services': [],
                'reasoning': 'Inferred from text: negative indicators found',
                'raw': text[:200]
            }

        # Positive indicators
        if any(phrase in text_lower for phrase in [
            'legitimate', 'provides pressure', 'offers exterior',
            'pressure washing service', 'cleaning service',
            'power wash', 'window clean', 'soft wash'
        ]) and 'not' not in text_lower[:100]:
            return {
                'success': True,
                'legitimate': True,
                'confidence': 0.6,
                'services': [],
                'reasoning': 'Inferred from text: positive indicators found',
                'raw': text[:200]
            }

        # Catch-all for unparseable responses
        if len(text.strip()) > 0:
            return {
                'success': True,
                'legitimate': False,
                'confidence': 0.3,
                'services': [],
                'reasoning': 'Unable to parse model response',
                'raw': text[:200]
            }

        return None

    def update_company(self, company_id: int, result: dict):
        """Update company with classification result."""
        with self.engine.connect() as conn:
            if result['success']:
                # Update llm_verified and related fields
                classification_data = json.dumps({
                    'llm_classification': {
                        'legitimate': result['legitimate'],
                        'confidence': result['confidence'],
                        'services': result['services'],
                        'reasoning': result['reasoning'][:200] if result.get('reasoning') else '',
                        'model': self.model,
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
                # Mark as processed with null (error)
                error_data = json.dumps({
                    'llm_classification_error': {
                        'error': result.get('error', 'unknown'),
                        'attempted_at': datetime.now().isoformat()
                    }
                })
                conn.execute(text("""
                    UPDATE companies
                    SET llm_verified_at = :verified_at,
                        parse_metadata = COALESCE(parse_metadata, '{}'::jsonb) || (:error)::jsonb
                    WHERE id = :id
                """), {
                    'id': company_id,
                    'verified_at': datetime.now(),
                    'error': error_data
                })
            conn.commit()

    def save_progress(self):
        """Save progress for resumability."""
        progress = {
            'processed': self.processed,
            'successes': self.successes,
            'failures': self.failures,
            'last_updated': datetime.now().isoformat()
        }

        os.makedirs('logs', exist_ok=True)
        with open(self.progress_file, 'w') as f:
            json.dump(progress, f, indent=2)

    def load_progress(self) -> dict:
        """Load previous progress if exists."""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {'processed': 0, 'successes': 0, 'failures': 0}

    def run(self):
        """Run the batch re-verification."""
        self.ensure_column_exists()

        # Get total count
        remaining = self.get_remaining_count()
        total_to_process = min(remaining, self.limit) if self.limit else remaining

        logger.info(f"Starting batch re-verification")
        logger.info(f"Model: {self.model}")
        logger.info(f"Companies to process: {total_to_process:,}")
        logger.info(f"Batch size: {self.batch_size}")

        self.start_time = time.time()
        batch_num = 0

        while True:
            # Get next batch
            companies = self.get_companies_to_process()

            if not companies:
                logger.info("No more companies to process")
                break

            if self.limit and self.processed >= self.limit:
                logger.info(f"Reached limit of {self.limit} companies")
                break

            batch_num += 1
            batch_start = time.time()

            for company in companies:
                if self.limit and self.processed >= self.limit:
                    break

                # Classify
                result = self.classify_company(company)

                # Update database
                self.update_company(company['id'], result)

                # Track progress
                self.processed += 1
                if result['success']:
                    self.successes += 1
                else:
                    self.failures += 1

                # Log every 10 companies
                if self.processed % 10 == 0:
                    elapsed = time.time() - self.start_time
                    rate = self.processed / elapsed if elapsed > 0 else 0
                    remaining_count = total_to_process - self.processed
                    eta_seconds = remaining_count / rate if rate > 0 else 0
                    eta = str(timedelta(seconds=int(eta_seconds)))

                    logger.info(
                        f"Progress: {self.processed:,}/{total_to_process:,} "
                        f"({100*self.processed/total_to_process:.1f}%) | "
                        f"Rate: {rate:.1f}/sec | "
                        f"Success: {100*self.successes/self.processed:.1f}% | "
                        f"ETA: {eta}"
                    )

            # Save progress after each batch
            self.save_progress()

            batch_elapsed = time.time() - batch_start
            logger.info(f"Batch {batch_num} complete ({len(companies)} companies in {batch_elapsed:.1f}s)")

        # Final summary
        elapsed = time.time() - self.start_time
        logger.info("=" * 60)
        logger.info("BATCH RE-VERIFICATION COMPLETE")
        logger.info(f"Total processed: {self.processed:,}")
        logger.info(f"Successes: {self.successes:,} ({100*self.successes/self.processed:.1f}%)")
        logger.info(f"Failures: {self.failures:,}")
        logger.info(f"Time: {timedelta(seconds=int(elapsed))}")
        logger.info(f"Rate: {self.processed/elapsed:.1f} companies/sec")
        logger.info("=" * 60)

        # Show distribution
        self.show_results_distribution()

    def show_results_distribution(self):
        """Show the distribution of llm_verified results."""
        with self.engine.connect() as conn:
            result = conn.execute(text('''
                SELECT
                    llm_verified,
                    COUNT(*) as count,
                    AVG(llm_confidence) as avg_confidence
                FROM companies
                WHERE llm_verified IS NOT NULL
                GROUP BY llm_verified
                ORDER BY llm_verified
            '''))

            logger.info("\nLLM Verification Results Distribution:")
            for row in result:
                verified, count, avg_conf = row
                logger.info(f"  llm_verified={verified}: {count:,} (avg confidence: {avg_conf:.2f})")


def main():
    parser = argparse.ArgumentParser(description='Batch re-verify companies with trained LLM')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for processing')
    parser.add_argument('--limit', type=int, default=None, help='Limit total companies to process')

    args = parser.parse_args()

    # Check Ollama is running
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m['name'] for m in resp.json().get('models', [])]
        expected_model = os.getenv("OLLAMA_MODEL", "unified-washdb-v2")
        if not any(expected_model in m for m in models):
            logger.error(f"Model {expected_model} not found in Ollama. Available: {models}")
            sys.exit(1)
        logger.info(f"Ollama ready with model: {expected_model}")
    except Exception as e:
        logger.error(f"Cannot connect to Ollama: {e}")
        sys.exit(1)

    reverifier = BatchReverifier(
        batch_size=args.batch_size,
        limit=args.limit
    )

    reverifier.run()


if __name__ == "__main__":
    main()
