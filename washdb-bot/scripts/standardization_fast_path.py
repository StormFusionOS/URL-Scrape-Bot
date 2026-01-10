#!/usr/bin/env python3
"""
Fast-Path Standardization Service - No Browser Required

This script handles companies that don't need browser visits:
1. Dead domains (domain_status = 'dead')
2. Highly blocked domains (block_count >= 3)
3. Simple names that just need basic cleanup

Uses regex_fallback_standardize() which:
- Converts to title case
- Removes legal suffixes (LLC, Inc, etc.)
- Preserves acronyms

This can process hundreds of companies per minute since there's no
browser overhead or delays.
"""

import os
import sys
import re
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('fast_path_standardization')

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://washbot:Washdb123@127.0.0.1:5432/washbot_db')

# Processing settings
BATCH_SIZE = 500  # Process many at once since no browser
SLEEP_BETWEEN_BATCHES = 1.0  # Very short delay


def regex_fallback_standardize(original_name: str) -> Tuple[str, float]:
    """
    Simple regex-based standardization.

    Returns (standardized_name, confidence)
    """
    if not original_name or len(original_name) < 2:
        return original_name, 0.0

    name = original_name.strip()

    # Remove legal suffixes (case insensitive)
    legal_suffixes = [
        r'\s*,?\s*LLC\.?$',
        r'\s*,?\s*L\.L\.C\.?$',
        r'\s*,?\s*Inc\.?$',
        r'\s*,?\s*Incorporated$',
        r'\s*,?\s*Corp\.?$',
        r'\s*,?\s*Corporation$',
        r'\s*,?\s*Co\.?$',
        r'\s*,?\s*Company$',
        r'\s*,?\s*Ltd\.?$',
        r'\s*,?\s*Limited$',
        r'\s*,?\s*P\.?C\.?$',
        r'\s*,?\s*PLLC\.?$',
    ]
    for suffix in legal_suffixes:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)

    # Clean up extra whitespace
    name = ' '.join(name.split())

    # Convert to title case, but preserve acronyms and handle apostrophes
    words = name.split()
    result_words = []
    for word in words:
        # Keep acronyms as-is (all caps, 2-4 chars)
        if word.isupper() and 2 <= len(word) <= 4:
            result_words.append(word)
        # Keep words with mixed case (like McDonald's)
        elif any(c.isupper() for c in word[1:]):
            result_words.append(word)
        else:
            # Handle words with apostrophes
            if "'" in word:
                parts = word.split("'")
                word = "'".join(p.title() if len(p) > 1 else p.lower() for p in parts)
                result_words.append(word)
            else:
                result_words.append(word.title())

    name = ' '.join(result_words)

    # Clean up common punctuation issues
    name = re.sub(r'\s+([,.])', r'\1', name)
    name = re.sub(r'([,.])\s*$', '', name)

    return name.strip(), 0.6


def get_fast_path_companies(engine, limit: int = BATCH_SIZE) -> list:
    """
    Get companies that can be processed without browser visits.

    Includes:
    - Dead domains
    - Highly blocked domains (block_count >= 3)
    """
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT id, name, website, domain_status, block_count
            FROM companies
            WHERE standardized_name IS NULL
              AND (verified = true OR llm_verified = true)
              AND website IS NOT NULL
              AND name IS NOT NULL
              AND LENGTH(name) > 2
              AND (
                -- Dead domains
                domain_status = 'dead'
                -- Or highly blocked domains
                OR block_count >= 3
              )
            ORDER BY id
            LIMIT :limit
        '''), {'limit': limit})

        companies = [
            {
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'domain_status': row[3],
                'block_count': row[4],
            }
            for row in result
        ]

        return companies


def save_standardized_name(engine, company_id: int, standardized_name: str, confidence: float, source: str):
    """Save the standardized name to database."""
    with engine.connect() as conn:
        conn.execute(text('''
            UPDATE companies
            SET standardized_name = :name,
                standardized_name_confidence = :confidence,
                standardized_name_source = :source,
                standardization_status = 'completed',
                standardized_at = NOW(),
                last_updated = NOW()
            WHERE id = :id
        '''), {
            'id': company_id,
            'name': standardized_name,
            'confidence': confidence,
            'source': source,
        })
        conn.commit()


def process_batch(engine, companies: list) -> Tuple[int, int]:
    """
    Process a batch of companies with regex standardization.

    Returns (success_count, skip_count)
    """
    success_count = 0
    skip_count = 0

    for company in companies:
        try:
            original_name = company['name']

            # Apply regex standardization
            standardized_name, confidence = regex_fallback_standardize(original_name)

            # Skip if no change and name is very short
            if standardized_name == original_name and len(original_name) < 5:
                skip_count += 1
                continue

            # Determine source based on reason
            if company['domain_status'] == 'dead':
                source = 'fast_path_dead_domain'
            elif company['block_count'] and company['block_count'] >= 3:
                source = 'fast_path_blocked_domain'
            else:
                source = 'fast_path_regex'

            # Save to database
            save_standardized_name(
                engine,
                company['id'],
                standardized_name,
                confidence,
                source
            )

            success_count += 1

            if success_count % 100 == 0:
                logger.info(f"Processed {success_count} companies...")

        except Exception as e:
            logger.error(f"Error processing company {company['id']}: {e}")
            continue

    return success_count, skip_count


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("FAST-PATH STANDARDIZATION SERVICE")
    logger.info("=" * 60)
    logger.info("Processing dead/blocked domains with regex-only standardization")
    logger.info(f"Batch size: {BATCH_SIZE}")
    logger.info("=" * 60)

    # Create database engine
    engine = create_engine(DATABASE_URL)

    # Get initial count
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT COUNT(*) FROM companies
            WHERE standardized_name IS NULL
              AND (verified = true OR llm_verified = true)
              AND (domain_status = 'dead' OR block_count >= 3)
        '''))
        total_pending = result.fetchone()[0]

    logger.info(f"Total companies for fast-path processing: {total_pending}")

    total_processed = 0
    total_skipped = 0
    start_time = time.time()

    while True:
        # Get batch of companies
        companies = get_fast_path_companies(engine, BATCH_SIZE)

        if not companies:
            logger.info("No more companies for fast-path processing")
            break

        # Check if we're making progress
        if len(companies) > 0 and all(c.get('processed', False) for c in companies):
            logger.info("All remaining companies already processed, exiting")
            break

        # Process batch
        success, skipped = process_batch(engine, companies)
        total_processed += success
        total_skipped += skipped

        elapsed = time.time() - start_time
        rate = total_processed / elapsed if elapsed > 0 else 0

        logger.info(
            f"Batch complete: {success} processed, {skipped} skipped | "
            f"Total: {total_processed}/{total_pending} | "
            f"Rate: {rate:.1f}/sec"
        )

        # Brief pause between batches
        time.sleep(SLEEP_BETWEEN_BATCHES)

    # Final summary
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("FAST-PATH STANDARDIZATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total processed: {total_processed}")
    logger.info(f"Total skipped: {total_skipped}")
    logger.info(f"Time elapsed: {elapsed:.1f} seconds")
    logger.info(f"Average rate: {total_processed / elapsed:.1f} companies/second")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
