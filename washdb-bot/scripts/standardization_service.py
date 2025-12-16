#!/usr/bin/env python3
"""
Persistent Standardization Service
Runs 24/7 to standardize business names using the local LLM
Processes existing backlog then monitors for new companies
"""

import os
import sys
import json
import time
import logging
import signal
import requests
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# Configuration
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434/api/generate')
MODEL_NAME = os.getenv('STANDARDIZATION_MODEL', 'standardization-mistral7b')
BATCH_SIZE = 100
POLL_INTERVAL = 60  # seconds to wait when no work
HEARTBEAT_INTERVAL = 30
LOG_DIR = Path(__file__).parent.parent / 'logs'
DATA_DIR = Path(__file__).parent.parent / 'data'

# Setup logging
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'standardization_service.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global state
running = True
stats = {
    'total_processed': 0,
    'total_success': 0,
    'total_errors': 0,
    'session_start': datetime.now(timezone.utc).isoformat(),
    'last_batch_time': None,
}


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global running
    logger.info(f"Received signal {signum}, shutting down...")
    running = False


def get_engine():
    """Create database connection"""
    return create_engine(
        os.getenv('DATABASE_URL'),
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


def standardize_name(name: str) -> tuple:
    """Call LLM to standardize a business name"""
    prompt = f"""<s>[INST] You are a business name standardization assistant.

Convert this business name to proper title case format:
- Remove legal suffixes (LLC, Inc, Corp, etc.)
- Remove special characters and symbols (except apostrophes)
- Fix ALL CAPS or all lowercase
- Keep it concise and professional
- IMPORTANT: Keep spaces between words! Do not merge words together.

Input: {name}

Output ONLY the standardized name with proper spacing, nothing else. [/INST]"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.1,
                    'num_predict': 50,
                }
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json().get('response', '').strip()
            # Clean up common LLM artifacts
            result = result.strip('"\'').strip()
            if result and len(result) > 1 and len(result) < 200:
                # Quality check: Reject if spaces were merged (camelCase issue)
                if ' ' in name and ' ' not in result and len(result) > 15:
                    logger.warning(f"Rejected merged output: '{name}' -> '{result}'")
                    return None, 0.0
                return result, 0.85

        return None, 0.0

    except Exception as e:
        logger.error(f"LLM error for '{name}': {e}")
        return None, 0.0


def get_companies_to_standardize(engine, limit: int = BATCH_SIZE) -> list:
    """Get companies needing standardization, prioritizing verified ones"""
    with engine.connect() as conn:
        # First priority: verified companies without standardization
        result = conn.execute(text('''
            SELECT id, name
            FROM companies
            WHERE standardized_name IS NULL
            AND claude_verified = true
            AND name IS NOT NULL
            AND LENGTH(name) > 2
            ORDER BY id
            LIMIT :limit
        '''), {'limit': limit})

        companies = [{'id': row[0], 'name': row[1]} for row in result]

        # If we got enough, return
        if len(companies) >= limit:
            return companies

        # Otherwise, get unverified companies to fill the batch
        remaining = limit - len(companies)
        result = conn.execute(text('''
            SELECT id, name
            FROM companies
            WHERE standardized_name IS NULL
            AND (claude_verified IS NULL OR claude_verified = false)
            AND name IS NOT NULL
            AND LENGTH(name) > 2
            ORDER BY id
            LIMIT :limit
        '''), {'limit': remaining})

        companies.extend([{'id': row[0], 'name': row[1]} for row in result])

        return companies


def update_standardized_name(engine, company_id: int, std_name: str, confidence: float):
    """Update company with standardized name"""
    with engine.connect() as conn:
        conn.execute(text('''
            UPDATE companies
            SET standardized_name = :std_name,
                standardized_name_source = 'llm',
                standardized_name_confidence = :confidence
            WHERE id = :id
        '''), {
            'id': company_id,
            'std_name': std_name,
            'confidence': confidence
        })
        conn.commit()


def write_heartbeat():
    """Write heartbeat file for monitoring"""
    heartbeat = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'status': 'running' if running else 'stopping',
        'model': MODEL_NAME,
        **stats
    }

    heartbeat_file = DATA_DIR / 'standardization_heartbeat.json'
    with open(heartbeat_file, 'w') as f:
        json.dump(heartbeat, f, indent=2)


def get_pending_count(engine) -> int:
    """Get count of companies needing standardization"""
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT COUNT(*) FROM companies
            WHERE standardized_name IS NULL
            AND name IS NOT NULL
            AND LENGTH(name) > 2
        '''))
        return result.scalar()


def process_batch(engine):
    """Process a batch of companies"""
    companies = get_companies_to_standardize(engine)

    if not companies:
        return 0

    batch_success = 0
    batch_errors = 0

    for company in companies:
        if not running:
            break

        try:
            std_name, confidence = standardize_name(company['name'])

            if std_name:
                update_standardized_name(engine, company['id'], std_name, confidence)
                batch_success += 1
                logger.debug(f"Standardized: '{company['name']}' -> '{std_name}'")
            else:
                batch_errors += 1
                logger.warning(f"Failed to standardize: '{company['name']}'")

        except Exception as e:
            batch_errors += 1
            logger.error(f"Error processing {company['id']}: {e}")

    stats['total_processed'] += batch_success + batch_errors
    stats['total_success'] += batch_success
    stats['total_errors'] += batch_errors
    stats['last_batch_time'] = datetime.now(timezone.utc).isoformat()

    return batch_success + batch_errors


def ensure_ollama_model():
    """Ensure the standardization model is available"""
    try:
        response = requests.get('http://localhost:11434/api/tags', timeout=10)
        if response.status_code == 200:
            models = [m['name'] for m in response.json().get('models', [])]
            if MODEL_NAME in models or f'{MODEL_NAME}:latest' in models:
                logger.info(f"Model {MODEL_NAME} is available")
                return True
            else:
                logger.warning(f"Model {MODEL_NAME} not found. Available: {models}")
                return False
    except Exception as e:
        logger.error(f"Cannot connect to Ollama: {e}")
        return False


def main():
    global running

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("=" * 60)
    logger.info("STANDARDIZATION SERVICE STARTING")
    logger.info("=" * 60)
    logger.info(f"Model: {MODEL_NAME}")
    logger.info(f"Batch size: {BATCH_SIZE}")
    logger.info(f"Poll interval: {POLL_INTERVAL}s")

    # Check Ollama model
    if not ensure_ollama_model():
        logger.error("Cannot start without standardization model")
        sys.exit(1)

    engine = get_engine()

    # Get initial pending count
    pending = get_pending_count(engine)
    logger.info(f"Pending companies: {pending:,}")

    last_heartbeat = 0

    while running:
        try:
            # Write heartbeat periodically
            now = time.time()
            if now - last_heartbeat > HEARTBEAT_INTERVAL:
                stats['pending_count'] = get_pending_count(engine)
                write_heartbeat()
                last_heartbeat = now

            # Process a batch
            processed = process_batch(engine)

            if processed > 0:
                logger.info(f"Processed {processed} companies. Total: {stats['total_success']:,} success, {stats['total_errors']:,} errors")
            else:
                # No work available, wait before polling again
                logger.info(f"No pending companies. Waiting {POLL_INTERVAL}s...")
                for _ in range(POLL_INTERVAL):
                    if not running:
                        break
                    time.sleep(1)

        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(10)

    # Final heartbeat
    stats['status'] = 'stopped'
    write_heartbeat()

    logger.info("=" * 60)
    logger.info("STANDARDIZATION SERVICE STOPPED")
    logger.info(f"Total processed: {stats['total_success']:,}")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
