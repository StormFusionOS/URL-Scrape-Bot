#!/usr/bin/env python3
"""
Claude API Batch Verification - Aligned with Local LLM Format

This script uses Claude API to verify companies using the EXACT same prompt
format as the local unified-washdb LLM. This ensures Claude's outputs can be
used directly as training data for the local LLM.

The local LLM uses:
- System prompt defining target services and JSON output format
- User prompt with structured company data
- Response: {"legitimate": bool, "confidence": float, "services": [], "reasoning": str}

Usage:
    python scripts/claude_batch_verify.py [--limit N] [--dry-run]
"""

import os
import sys
import json
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import anthropic
from sqlalchemy import create_engine, text

# Configuration
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-3-haiku-20240307')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://washbot:Washdb123@127.0.0.1:5432/washbot_db')

# Rate limiting - Haiku can handle more
REQUESTS_PER_MINUTE = 60
DELAY_BETWEEN_REQUESTS = 60.0 / REQUESTS_PER_MINUTE

# Content limits (same as local LLM)
LLM_SERVICES_TEXT_LIMIT = 2000
LLM_ABOUT_TEXT_LIMIT = 2000
LLM_HOMEPAGE_TEXT_LIMIT = 4000

# ============================================================================
# EXACT SAME SYSTEM PROMPT AS LOCAL LLM (unified_llm.py lines 48-54)
# ============================================================================
SYSTEM_PROMPT = """You are a business verification assistant. Analyze the company information and determine if this is a legitimate service provider offering exterior cleaning services.

Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet/truck washing, Wood restoration.

Respond with ONLY a valid JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": [], "reasoning": "brief explanation"}"""

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/claude_batch_verify.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('claude_batch_verify')


def build_verification_prompt(
    company_name: str,
    website: str,
    phone: str = "",
    title: str = "",
    services_text: str = "",
    about_text: str = "",
    homepage_text: str = ""
) -> str:
    """
    Build verification prompt - EXACT SAME FORMAT as local LLM.
    (Matches unified_llm.py _build_verification_prompt method)
    """
    homepage_text = (homepage_text or "")[:LLM_HOMEPAGE_TEXT_LIMIT]
    services_text = (services_text or "")[:LLM_SERVICES_TEXT_LIMIT]
    about_text = (about_text or "")[:LLM_ABOUT_TEXT_LIMIT]

    prompt = f"Company: {company_name}\n"
    prompt += f"Website: {website}\n"

    if phone:
        prompt += f"Phone: {phone}\n"
    if title:
        prompt += f"Page title: {title}\n"
    if homepage_text:
        prompt += f"\nHomepage excerpt:\n{homepage_text}\n"
    if services_text:
        prompt += f"\nServices page excerpt:\n{services_text}\n"
    elif about_text:
        prompt += f"\nAbout page excerpt:\n{about_text}\n"

    prompt += "\nIs this a legitimate exterior cleaning service provider?"
    return prompt


def parse_claude_response(response_text: str) -> Optional[Dict]:
    """Parse Claude's JSON response - expect same format as local LLM."""
    try:
        text = response_text.strip()

        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        parsed = json.loads(text)

        # Validate expected fields
        if 'legitimate' not in parsed:
            logger.warning("Missing 'legitimate' field in response")
            return None

        # Normalize the response to match local LLM format exactly
        return {
            'legitimate': bool(parsed.get('legitimate', False)),
            'confidence': float(parsed.get('confidence', 0.5)),
            'services': parsed.get('services', []),
            'reasoning': str(parsed.get('reasoning', ''))
        }

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON: {e}")
        return None


def get_companies_needing_review(engine, limit: int = None) -> List[Dict]:
    """Fetch companies needing review with same data as local LLM uses."""
    with engine.connect() as conn:
        query = """
            SELECT
                id,
                name,
                website,
                phone,
                parse_metadata->>'title' as page_title,
                parse_metadata->>'services' as services_text,
                parse_metadata->>'about' as about_text,
                parse_metadata->'homepage_text' as homepage_text
            FROM companies
            WHERE verified IS NULL
              AND llm_verified = false
              AND website IS NOT NULL
            ORDER BY id
        """
        if limit:
            query += f" LIMIT {limit}"

        result = conn.execute(text(query))

        companies = []
        for row in result:
            # Extract homepage_text (may be JSON or string)
            homepage_text = ""
            if row[7]:
                try:
                    if isinstance(row[7], str):
                        homepage_text = json.loads(row[7]) if row[7].startswith('{') else row[7]
                    else:
                        homepage_text = str(row[7])
                except:
                    homepage_text = str(row[7])[:LLM_HOMEPAGE_TEXT_LIMIT]

            companies.append({
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'phone': row[3] or "",
                'title': row[4] or "",
                'services_text': row[5] or "",
                'about_text': row[6] or "",
                'homepage_text': homepage_text if isinstance(homepage_text, str) else ""
            })

        return companies


def update_company_with_claude_result(
    engine,
    company_id: int,
    claude_result: Dict,
    raw_response: str,
    user_prompt: str
):
    """
    Update company with Claude's verification and store training data.

    Training data stored in same format as local LLM output for easy fine-tuning.
    """
    with engine.connect() as conn:
        is_legitimate = claude_result.get('legitimate', False)
        confidence = claude_result.get('confidence', 0.0)
        services = claude_result.get('services', [])
        reasoning = claude_result.get('reasoning', '')

        # Training data - matches local LLM input/output format exactly
        training_data = {
            # Timestamp and metadata
            'verified_at': datetime.now().isoformat(),
            'model': CLAUDE_MODEL,
            'model_type': 'claude_api',

            # The prompt that was sent (for training input)
            'system_prompt': SYSTEM_PROMPT,
            'user_prompt': user_prompt,

            # The response (for training output) - EXACT same format as local LLM
            'response': {
                'legitimate': is_legitimate,
                'confidence': confidence,
                'services': services,
                'reasoning': reasoning
            },

            # Raw response for debugging
            'raw_response': raw_response
        }

        conn.execute(text("""
            UPDATE companies
            SET
                verified = :verified,
                llm_verified = :llm_verified,
                claude_verified = true,
                claude_verified_at = NOW(),
                verification_type = 'claude',
                provider_status = :provider_status,
                parse_metadata = jsonb_set(
                    COALESCE(parse_metadata, '{}'::jsonb),
                    '{claude_training_data}',
                    CAST(:training_data AS jsonb)
                ),
                last_updated = NOW()
            WHERE id = :company_id
        """), {
            'company_id': company_id,
            'verified': is_legitimate,
            'llm_verified': is_legitimate,
            'provider_status': 'provider' if is_legitimate else 'non_provider',
            'training_data': json.dumps(training_data)
        })
        conn.commit()


def verify_company_with_claude(client: anthropic.Anthropic, company: Dict) -> tuple:
    """
    Call Claude API using EXACT same prompt format as local LLM.

    Returns: (parsed_result, raw_response, user_prompt)
    """
    # Build prompt exactly like local LLM does
    user_prompt = build_verification_prompt(
        company_name=company['name'],
        website=company['website'],
        phone=company['phone'],
        title=company['title'],
        services_text=company['services_text'],
        about_text=company['about_text'],
        homepage_text=company['homepage_text']
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        raw_response = response.content[0].text
        parsed = parse_claude_response(raw_response)

        return parsed, raw_response, user_prompt

    except anthropic.RateLimitError:
        logger.warning("Rate limited, waiting 60 seconds...")
        time.sleep(60)
        return None, "", user_prompt
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return None, str(e), user_prompt


def export_training_data(engine, output_file: str = "data/claude_training_data.jsonl"):
    """Export Claude verification results in JSONL format for LLM fine-tuning."""
    Path(output_file).parent.mkdir(exist_ok=True)

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                parse_metadata->'claude_training_data'->>'system_prompt' as system_prompt,
                parse_metadata->'claude_training_data'->>'user_prompt' as user_prompt,
                parse_metadata->'claude_training_data'->'response' as response
            FROM companies
            WHERE claude_verified = true
              AND parse_metadata->'claude_training_data' IS NOT NULL
        """))

        count = 0
        with open(output_file, 'w') as f:
            for row in result:
                if row[0] and row[1] and row[2]:
                    training_example = {
                        "system": row[0],
                        "prompt": row[1],
                        "response": json.dumps(row[2]) if isinstance(row[2], dict) else row[2]
                    }
                    f.write(json.dumps(training_example) + "\n")
                    count += 1

        logger.info(f"Exported {count} training examples to {output_file}")
        return count


def main():
    parser = argparse.ArgumentParser(description='Claude API batch verification (aligned with local LLM)')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of companies')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--export-only', action='store_true', help='Only export existing training data')
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    engine = create_engine(DATABASE_URL)

    # Export-only mode
    if args.export_only:
        export_training_data(engine)
        return

    logger.info("=" * 70)
    logger.info("CLAUDE API BATCH VERIFICATION")
    logger.info("(Aligned with local LLM format for training data)")
    logger.info("=" * 70)
    logger.info(f"Model: {CLAUDE_MODEL}")
    logger.info(f"Rate limit: {REQUESTS_PER_MINUTE}/min")
    logger.info(f"Limit: {args.limit or 'All'}")
    logger.info("=" * 70)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Get companies
    logger.info("Fetching companies needing review...")
    companies = get_companies_needing_review(engine, args.limit)
    logger.info(f"Found {len(companies)} companies to verify")

    if args.dry_run:
        logger.info("DRY RUN - showing first 3 prompts:")
        for c in companies[:3]:
            prompt = build_verification_prompt(
                c['name'], c['website'], c['phone'], c['title'],
                c['services_text'], c['about_text'], c['homepage_text']
            )
            logger.info(f"\n--- Company {c['id']}: {c['name']} ---")
            logger.info(f"Prompt:\n{prompt[:500]}...")
        return

    # Process companies
    verified = 0
    accepted = 0
    rejected = 0
    errors = 0
    start_time = time.time()

    for i, company in enumerate(companies):
        try:
            logger.info(f"[{i+1}/{len(companies)}] {company['name'][:40]}...")

            result, raw_response, user_prompt = verify_company_with_claude(client, company)

            if result:
                update_company_with_claude_result(
                    engine, company['id'], result, raw_response, user_prompt
                )

                verified += 1
                if result.get('legitimate'):
                    accepted += 1
                    logger.info(f"  ✓ ACCEPTED ({result['confidence']:.2f}): {result['reasoning'][:50]}")
                else:
                    rejected += 1
                    logger.info(f"  ✗ REJECTED ({result['confidence']:.2f}): {result['reasoning'][:50]}")
            else:
                errors += 1
                logger.warning(f"  ! ERROR: Failed to get valid response")

            time.sleep(DELAY_BETWEEN_REQUESTS)

            # Progress every 100
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                rate = verified / (elapsed / 60)
                logger.info(f"Progress: {verified} done ({accepted} acc, {rejected} rej) | {rate:.1f}/min")

        except KeyboardInterrupt:
            logger.info("Interrupted")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            errors += 1

    # Summary
    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info("COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Verified: {verified} ({accepted} accepted, {rejected} rejected)")
    logger.info(f"Errors: {errors}")
    logger.info(f"Time: {elapsed/60:.1f} min | Rate: {verified/(elapsed/60) if elapsed > 60 else 0:.1f}/min")
    logger.info("=" * 70)

    # Export training data
    if verified > 0:
        logger.info("Exporting training data...")
        export_training_data(engine)


if __name__ == "__main__":
    main()
