#!/usr/bin/env python3
"""
Continuous LLM Verification & Standardization Service

Runs 24/7 using the unified-washdb-v2 model for:
1. Business verification (is this a legitimate exterior cleaning service?)
2. Name standardization (extract/clean the official business name)

Features:
- Heartbeat monitoring
- Processes all unverified/unstandardized companies
- Waits for new companies when queue is empty
- Automatic retry on failures
- Progress logging

Usage:
    python scripts/llm_verification_service.py

Or as systemd service:
    sudo systemctl start llm-verification
"""

import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
import requests

# Setup logging
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Clear existing handlers to avoid duplicates
logging.root.handlers = []
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'llm_verification_service.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LLMVerificationService:
    """Continuous LLM verification and standardization service."""

    VERIFICATION_PROMPT = """You are a business verification assistant for exterior cleaning services. Respond with JSON only.

Target services: Pressure washing, Power washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet washing, Deck cleaning, Wood restoration.

Respond with: {"legitimate": true/false, "confidence": 0.0-1.0, "services": {}, "reasoning": "brief"}"""

    STANDARDIZATION_PROMPT = """Extract the official business name from the provided data.

Rules:
- Extract actual business name, not taglines or slogans
- Keep legal suffixes (LLC, Inc, Corp) if part of the brand
- Use proper Title Case capitalization
- Remove location suffixes unless part of official name
- If uncertain, return the input name unchanged

Respond with ONLY the business name, nothing else."""

    def __init__(self):
        self.engine = create_engine(os.getenv('DATABASE_URL'))
        self.ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.model = os.getenv('OLLAMA_MODEL', 'unified-washdb-v2')

        # Service state
        self.running = True
        self.paused = False

        # Stats
        self.stats = {
            'verified': 0,
            'standardized': 0,
            'verify_success': 0,
            'standard_success': 0,
            'failures': 0
        }
        self.start_time = datetime.now()
        self.last_heartbeat = datetime.now()

        # Config
        self.batch_size = int(os.getenv('LLM_BATCH_SIZE', '50'))
        self.poll_interval = int(os.getenv('LLM_POLL_INTERVAL', '60'))
        self.heartbeat_interval = 30
        self.request_timeout = 60

        # Heartbeat file
        self.heartbeat_file = LOG_DIR / 'llm_verification_heartbeat.json'

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle graceful shutdown."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def write_heartbeat(self, status: str = "running", message: str = ""):
        """Write heartbeat file for monitoring."""
        self.last_heartbeat = datetime.now()
        total = self.stats['verified'] + self.stats['standardized']
        successes = self.stats['verify_success'] + self.stats['standard_success']

        heartbeat = {
            "status": status,
            "message": message,
            "timestamp": self.last_heartbeat.isoformat(),
            "uptime_seconds": (self.last_heartbeat - self.start_time).total_seconds(),
            "stats": {
                "verified": self.stats['verified'],
                "standardized": self.stats['standardized'],
                "total_processed": total,
                "successes": successes,
                "failures": self.stats['failures'],
                "success_rate": f"{100*successes/max(1,total):.1f}%"
            },
            "model": self.model,
            "pid": os.getpid()
        }

        try:
            with open(self.heartbeat_file, 'w') as f:
                json.dump(heartbeat, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write heartbeat: {e}")

    def ensure_columns_exist(self):
        """Ensure required columns exist in database."""
        with self.engine.connect() as conn:
            # Verification columns
            conn.execute(text('ALTER TABLE companies ADD COLUMN IF NOT EXISTS llm_verified BOOLEAN DEFAULT NULL'))
            conn.execute(text('ALTER TABLE companies ADD COLUMN IF NOT EXISTS llm_verified_at TIMESTAMP DEFAULT NULL'))
            conn.execute(text('ALTER TABLE companies ADD COLUMN IF NOT EXISTS llm_confidence NUMERIC(3,2) DEFAULT NULL'))
            conn.execute(text('ALTER TABLE companies ADD COLUMN IF NOT EXISTS llm_services JSONB DEFAULT NULL'))
            conn.commit()
        logger.info("Database columns verified")

    def check_ollama(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m['name'] for m in resp.json().get('models', [])]
                if any(self.model in m for m in models):
                    return True
                logger.error(f"Model {self.model} not found. Available: {models}")
                return False
        except Exception as e:
            logger.error(f"Ollama not reachable: {e}")
        return False

    def call_llm(self, system_prompt: str, prompt: str) -> str:
        """Make a request to the LLM."""
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "system": system_prompt,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=self.request_timeout
            )
            if resp.status_code == 200:
                return resp.json().get('response', '')
        except Exception as e:
            logger.debug(f"LLM call failed: {e}")
        return None

    # ===================== VERIFICATION =====================

    def get_pending_verification(self) -> list:
        """Get companies needing verification."""
        with self.engine.connect() as conn:
            result = conn.execute(text('''
                SELECT id, name, website, domain,
                       parse_metadata->>'title' as title,
                       LEFT(parse_metadata->>'meta_description', 200) as meta,
                       LEFT(parse_metadata->>'homepage_text', 500) as content
                FROM companies
                WHERE llm_verified IS NULL
                  AND name IS NOT NULL
                  AND (website IS NOT NULL OR domain IS NOT NULL)
                ORDER BY CASE WHEN parse_metadata IS NOT NULL THEN 0 ELSE 1 END, created_at DESC
                LIMIT :limit
            '''), {'limit': self.batch_size})
            return [dict(row._mapping) for row in result]

    def verify_company(self, company: dict) -> dict:
        """Verify a single company."""
        name = company.get('name', 'Unknown')
        website = company.get('website') or company.get('domain', '')

        prompt_parts = [f"Company: {name}"]
        if website:
            prompt_parts.append(f"Website: {website}")
        if company.get('title'):
            prompt_parts.append(f"Page Title: {company['title']}")
        if company.get('meta'):
            prompt_parts.append(f"Description: {company['meta']}")
        if company.get('content'):
            prompt_parts.append(f"Content: {company['content'][:400]}")
        prompt_parts.append("\nIs this a legitimate exterior cleaning service provider?")

        response = self.call_llm(self.VERIFICATION_PROMPT, "\n".join(prompt_parts))

        if response:
            try:
                data = json.loads(response)
                return {
                    "success": True,
                    "legitimate": data.get('legitimate', False),
                    "confidence": data.get('confidence', 0.5),
                    "services": data.get('services', {})
                }
            except json.JSONDecodeError:
                # Try regex fallback
                legit_match = re.search(r'"legitimate":\s*(true|false)', response, re.I)
                conf_match = re.search(r'"confidence":\s*([0-9.]+)', response)
                if legit_match:
                    return {
                        "success": True,
                        "legitimate": legit_match.group(1).lower() == 'true',
                        "confidence": float(conf_match.group(1)) if conf_match else 0.5,
                        "services": {}
                    }
        return {"success": False}

    def update_verification(self, company_id: int, result: dict):
        """Update company with verification result."""
        with self.engine.connect() as conn:
            if result.get('success'):
                conn.execute(text('''
                    UPDATE companies
                    SET llm_verified = :legitimate,
                        llm_verified_at = NOW(),
                        llm_confidence = :confidence,
                        llm_services = :services
                    WHERE id = :id
                '''), {
                    'id': company_id,
                    'legitimate': result.get('legitimate'),
                    'confidence': result.get('confidence'),
                    'services': json.dumps(result.get('services', {}))
                })
            conn.commit()

    # ===================== STANDARDIZATION =====================

    def get_pending_standardization(self) -> list:
        """Get companies needing name standardization."""
        with self.engine.connect() as conn:
            result = conn.execute(text('''
                SELECT id, name, website,
                       parse_metadata->>'title' as title,
                       parse_metadata->>'og_site_name' as og_name,
                       parse_metadata->>'business_name' as extracted_name
                FROM companies
                WHERE (standardized_name IS NULL OR standardized_name = '')
                  AND name IS NOT NULL
                  AND llm_verified = true
                ORDER BY created_at DESC
                LIMIT :limit
            '''), {'limit': self.batch_size})
            return [dict(row._mapping) for row in result]

    def clean_standardized_name(self, name: str, original: str) -> str:
        """Clean and validate standardized name."""
        if not name:
            return None

        # Strip whitespace and quotes
        name = name.strip().strip('"').strip("'").strip()

        # Fix apostrophe capitalization: "'S" -> "'s", "'T" -> "'t", etc.
        name = re.sub(r"'([A-Z])(?=[a-z]|\s|$)", lambda m: "'" + m.group(1).lower(), name)

        # Remove common garbage patterns
        garbage_patterns = [
            r'\(noun\)',
            r'http[s]?://',
            r'\.com',
            r'\.net',
            r'\.org',
            r'www\.',
            r'- Wikipedia',
            r'\r\n|\r|\n',
        ]
        for pattern in garbage_patterns:
            if re.search(pattern, name, re.IGNORECASE):
                return None

        # Reject if too different from original (likely hallucination)
        # For short names (<=5 chars), be stricter about length increase
        if len(original) <= 5:
            if len(name) > len(original) * 3:
                return None
        elif len(name) > len(original) * 2:
            return None

        # Reject very short results for longer originals
        if len(name) < 3:
            return None

        # Reject if it's just a domain
        if name.lower().endswith(('.com', '.net', '.org', '.co')):
            return None

        return name

    def standardize_name(self, company: dict) -> dict:
        """Standardize company name."""
        original_name = company.get('name', '')

        # Skip very short or garbage input names
        if len(original_name) < 2 or original_name.isdigit():
            return {"success": False}

        prompt_parts = [f"Current name: {original_name}"]
        if company.get('title'):
            prompt_parts.append(f"Page title: {company['title']}")
        if company.get('og_name'):
            prompt_parts.append(f"Site name: {company['og_name']}")
        if company.get('extracted_name'):
            prompt_parts.append(f"Extracted name: {company['extracted_name']}")
        prompt_parts.append("\nWhat is the official business name?")

        response = self.call_llm(self.STANDARDIZATION_PROMPT, "\n".join(prompt_parts))

        if response:
            std_name = self.clean_standardized_name(response, original_name)
            if std_name and len(std_name) <= 200:
                return {"success": True, "standardized_name": std_name}

        return {"success": False}

    def update_standardization(self, company_id: int, result: dict):
        """Update company with standardized name."""
        with self.engine.connect() as conn:
            if result.get('success'):
                conn.execute(text('''
                    UPDATE companies
                    SET standardized_name = :name,
                        standardized_name_source = 'llm-v2',
                        standardized_at = NOW()
                    WHERE id = :id
                '''), {
                    'id': company_id,
                    'name': result.get('standardized_name')
                })
            conn.commit()

    # ===================== MAIN LOOP =====================

    def process_batch(self) -> int:
        """Process verification and standardization batches."""
        processed = 0

        # Process verification
        companies = self.get_pending_verification()
        for company in companies:
            if not self.running:
                break
            result = self.verify_company(company)
            self.update_verification(company['id'], result)
            self.stats['verified'] += 1
            if result.get('success'):
                self.stats['verify_success'] += 1
            else:
                self.stats['failures'] += 1
            processed += 1

            if (datetime.now() - self.last_heartbeat).seconds >= self.heartbeat_interval:
                self.write_heartbeat("running", f"Verifying companies")

        # Process standardization
        companies = self.get_pending_standardization()
        for company in companies:
            if not self.running:
                break
            result = self.standardize_name(company)
            self.update_standardization(company['id'], result)
            self.stats['standardized'] += 1
            if result.get('success'):
                self.stats['standard_success'] += 1
            else:
                self.stats['failures'] += 1
            processed += 1

            if (datetime.now() - self.last_heartbeat).seconds >= self.heartbeat_interval:
                self.write_heartbeat("running", f"Standardizing names")

        return processed

    def get_queue_sizes(self) -> dict:
        """Get pending counts for both tasks."""
        with self.engine.connect() as conn:
            verify = conn.execute(text('''
                SELECT COUNT(*) FROM companies
                WHERE llm_verified IS NULL AND name IS NOT NULL
                  AND (website IS NOT NULL OR domain IS NOT NULL)
            ''')).scalar()

            standard = conn.execute(text('''
                SELECT COUNT(*) FROM companies
                WHERE (standardized_name IS NULL OR standardized_name = '')
                  AND name IS NOT NULL AND llm_verified = true
            ''')).scalar()

            return {'verification': verify, 'standardization': standard}

    def run(self):
        """Main service loop."""
        logger.info("=" * 60)
        logger.info("LLM Verification & Standardization Service Starting")
        logger.info(f"Model: {self.model}")
        logger.info(f"Batch size: {self.batch_size}")
        logger.info(f"Poll interval: {self.poll_interval}s")
        logger.info("=" * 60)

        self.ensure_columns_exist()

        if not self.check_ollama():
            logger.error("Ollama check failed. Exiting.")
            self.write_heartbeat("error", "Ollama not available")
            sys.exit(1)

        queues = self.get_queue_sizes()
        logger.info(f"Pending verification: {queues['verification']}")
        logger.info(f"Pending standardization: {queues['standardization']}")

        self.write_heartbeat("running", "Starting")

        while self.running:
            try:
                processed = self.process_batch()

                if processed > 0:
                    total = self.stats['verified'] + self.stats['standardized']
                    logger.info(f"Batch complete | Verified: {self.stats['verified']} | Standardized: {self.stats['standardized']} | Total: {total}")
                    self.write_heartbeat("running", f"Processed {total} total")
                else:
                    queues = self.get_queue_sizes()
                    total_pending = queues['verification'] + queues['standardization']

                    if total_pending == 0:
                        logger.info(f"Queues empty. Waiting {self.poll_interval}s...")
                        self.write_heartbeat("idle", "Waiting for new companies")

                        wait_until = datetime.now() + timedelta(seconds=self.poll_interval)
                        while datetime.now() < wait_until and self.running:
                            time.sleep(min(self.heartbeat_interval, self.poll_interval))
                            self.write_heartbeat("idle", "Waiting for new companies")
                    else:
                        time.sleep(5)

            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                self.write_heartbeat("error", str(e))
                time.sleep(10)

        logger.info("=" * 60)
        logger.info("Service Stopped")
        logger.info(f"Verified: {self.stats['verified']}")
        logger.info(f"Standardized: {self.stats['standardized']}")
        logger.info("=" * 60)
        self.write_heartbeat("stopped", "Graceful shutdown")


def main():
    service = LLMVerificationService()
    service.run()


if __name__ == "__main__":
    main()
