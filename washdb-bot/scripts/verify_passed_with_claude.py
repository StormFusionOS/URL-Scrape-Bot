#!/usr/bin/env python3
"""
Verify passed companies with Claude API to catch false positives.

This script:
1. Takes all companies marked as 'passed' that haven't been Claude-verified
2. Sends them to Claude API for verification
3. Specifically checks if they offer TARGET services:
   - Pressure washing / power washing / soft washing
   - Window cleaning (residential/commercial)
   - Wood restoration (deck staining, fence staining, log home restoration)
4. Updates parse_metadata with Claude's assessment

Usage:
    python scripts/verify_passed_with_claude.py [--budget 10.00] [--batch-size 100]
"""

import sys
import json
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import create_session
from sqlalchemy import text
from scrape_site.claude_verifier import ClaudeVerifier

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/claude_verify_passed.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Target services we care about
TARGET_SERVICES = """
You are verifying if this company provides EXTERIOR CLEANING AND RESTORATION services.

TARGET SERVICES (mark as target_service=true if they offer ANY of these):
1. PRESSURE WASHING / POWER WASHING / SOFT WASHING
   - House washing, driveway cleaning, sidewalk cleaning
   - Commercial building washing, parking lot cleaning
   - Fleet/truck washing (only if they do external washing)

2. WINDOW CLEANING
   - Residential window cleaning
   - Commercial window cleaning
   - High-rise window cleaning

3. WOOD RESTORATION / STAINING
   - Deck cleaning and staining
   - Fence cleaning and staining
   - Pergola/gazebo restoration
   - Log home restoration and staining
   - Wood siding restoration

NOT TARGET SERVICES (mark as target_service=false):
- Car washes (automated or hand car wash businesses)
- Laundromats / dry cleaners
- Interior cleaning only (maid services, carpet cleaning)
- General contractors without specific exterior cleaning
- Equipment sales/rental only
- Directories or listing sites
- Franchise corporate pages (not local operators)
"""


def get_companies_to_verify(limit: int = None) -> list:
    """Get verified companies that haven't been Claude-verified for target services."""
    with create_session() as session:
        limit_clause = f"LIMIT {limit}" if limit else ""

        # Use new standardized schema: verified=true, verification_type='llm'
        # We want to verify LLM-verified companies with Claude for target service check
        query = text(f"""
            SELECT
                id,
                name,
                website,
                phone,
                address,
                services,
                parse_metadata->'verification' as verification
            FROM companies
            WHERE verified = true
              AND verification_type = 'llm'
              AND parse_metadata->'verification'->'claude_assessment'->>'claude_legitimate' IS NULL
            ORDER BY id
            {limit_clause}
        """)

        result = session.execute(query)
        companies = []

        for row in result:
            companies.append({
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'phone': row[3],
                'address': row[4],
                'services': row[5],
                'verification': row[6] or {}
            })

        return companies


def update_company_verification(company_id: int, claude_assessment: dict):
    """Update company with Claude assessment using standardized schema."""
    with create_session() as session:
        # Get current parse_metadata
        query = text("SELECT parse_metadata FROM companies WHERE id = :id")
        result = session.execute(query, {'id': company_id}).fetchone()

        if result:
            metadata = result[0] or {}
            if 'verification' not in metadata:
                metadata['verification'] = {}

            metadata['verification']['claude_assessment'] = claude_assessment

            # Determine new verified status based on Claude's assessment
            verified_value = None
            if claude_assessment.get('claude_legitimate') == False:
                metadata['verification']['status'] = 'failed'
                metadata['verification']['reason'] = 'Claude API: Not a legitimate service provider'
                verified_value = False

            # Add target_service flag
            metadata['verification']['target_service'] = claude_assessment.get('target_service', False)

            # Update using standardized schema
            update_query = text("""
                UPDATE companies
                SET parse_metadata = :metadata,
                    claude_verified = true,
                    claude_verified_at = NOW(),
                    verification_type = 'claude',
                    verified = COALESCE(:verified_value, verified)
                WHERE id = :id
            """)
            session.execute(update_query, {
                'id': company_id,
                'metadata': json.dumps(metadata),
                'verified_value': verified_value
            })
            session.commit()


def verify_company_with_claude(verifier: ClaudeVerifier, company: dict) -> dict:
    """Verify a single company with Claude API."""
    # Build context for Claude
    context = f"""
Company Name: {company['name']}
Website: {company.get('website', 'N/A')}
Phone: {company.get('phone', 'N/A')}
Address: {company.get('address', 'N/A')}
Services Listed: {company.get('services', 'N/A')}
"""

    # Add any existing verification signals
    verification = company.get('verification', {})
    if verification.get('quality_signals'):
        context += f"\nQuality Signals: {', '.join(verification['quality_signals'])}"
    if verification.get('positive_signals'):
        context += f"\nPositive Signals: {', '.join(verification['positive_signals'][:5])}"
    if verification.get('red_flags'):
        context += f"\nRed Flags: {', '.join(verification['red_flags'])}"

    prompt = f"""{TARGET_SERVICES}

COMPANY TO VERIFY:
{context}

Respond with JSON only:
{{
    "legitimate": true/false,
    "target_service": true/false,
    "confidence": 0.0-1.0,
    "services_detected": {{
        "pressure_washing": true/false,
        "window_cleaning": true/false,
        "wood_restoration": true/false
    }},
    "reason": "brief explanation"
}}
"""

    try:
        result = verifier.verify(prompt)

        # Parse response
        if isinstance(result, dict):
            return {
                'claude_legitimate': result.get('legitimate', False),
                'target_service': result.get('target_service', False),
                'claude_confidence': result.get('confidence', 0.5),
                'claude_services': result.get('services_detected', {}),
                'claude_reason': result.get('reason', ''),
                'claude_verified_at': datetime.now(timezone.utc).isoformat()
            }
        else:
            # Try to parse JSON from string response
            import re
            json_match = re.search(r'\{.*\}', str(result), re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                return {
                    'claude_legitimate': parsed.get('legitimate', False),
                    'target_service': parsed.get('target_service', False),
                    'claude_confidence': parsed.get('confidence', 0.5),
                    'claude_services': parsed.get('services_detected', {}),
                    'claude_reason': parsed.get('reason', ''),
                    'claude_verified_at': datetime.now(timezone.utc).isoformat()
                }
    except Exception as e:
        logger.error(f"Error verifying company {company['id']}: {e}")

    return {
        'claude_legitimate': None,
        'target_service': None,
        'claude_confidence': 0,
        'claude_error': str(e) if 'e' in dir() else 'Unknown error',
        'claude_verified_at': datetime.now(timezone.utc).isoformat()
    }


def main():
    parser = argparse.ArgumentParser(description='Verify passed companies with Claude API')
    parser.add_argument('--budget', type=float, default=10.0, help='Maximum budget in dollars')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for processing')
    parser.add_argument('--limit', type=int, default=None, help='Limit total companies to process')
    args = parser.parse_args()

    print("=" * 70)
    print("CLAUDE API VERIFICATION OF PASSED COMPANIES")
    print("=" * 70)
    print(f"\nBudget: ${args.budget:.2f}")
    print(f"Cost per verification: ~$0.0009")
    print(f"Max verifications: ~{int(args.budget / 0.0009):,}")

    # Initialize Claude verifier
    verifier = ClaudeVerifier()

    # Get companies to verify
    companies = get_companies_to_verify(limit=args.limit)
    logger.info(f"Found {len(companies):,} passed companies to verify")

    if not companies:
        print("\nNo companies need verification!")
        return

    # Process in batches
    total_cost = 0.0
    cost_per_call = 0.0009

    stats = {
        'processed': 0,
        'legitimate_target': 0,      # Legitimate AND offers target services
        'legitimate_non_target': 0,  # Legitimate but doesn't offer target services
        'not_legitimate': 0,         # Not a legitimate business
        'errors': 0
    }

    print(f"\nProcessing {len(companies):,} companies...")
    print("-" * 70)

    for i, company in enumerate(companies):
        # Check budget
        if total_cost >= args.budget:
            logger.info(f"Budget limit (${args.budget}) reached")
            break

        # Verify with Claude
        assessment = verify_company_with_claude(verifier, company)
        total_cost += cost_per_call
        stats['processed'] += 1

        # Update database
        update_company_verification(company['id'], assessment)

        # Track stats
        if assessment.get('claude_legitimate') is None:
            stats['errors'] += 1
            symbol = '?'
        elif assessment.get('claude_legitimate') == False:
            stats['not_legitimate'] += 1
            symbol = '✗'
        elif assessment.get('target_service') == True:
            stats['legitimate_target'] += 1
            symbol = '★'
        else:
            stats['legitimate_non_target'] += 1
            symbol = '○'

        # Log progress
        target_str = "TARGET" if assessment.get('target_service') else "non-target"
        logger.info(f"{symbol} ID {company['id']}: {company['name'][:40]} → {target_str} (${cost_per_call})")

        # Progress update every batch
        if (i + 1) % args.batch_size == 0:
            print(f"\nBatch {(i+1)//args.batch_size} complete:")
            print(f"  Processed: {stats['processed']}")
            print(f"  Target services: {stats['legitimate_target']}")
            print(f"  Non-target: {stats['legitimate_non_target']}")
            print(f"  Not legitimate: {stats['not_legitimate']}")
            print(f"  Total cost: ${total_cost:.2f}")

        # Small delay to avoid rate limiting
        time.sleep(0.1)

    # Final summary
    print("\n" + "=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)
    print(f"\nTotal processed: {stats['processed']:,}")
    print(f"Total cost: ${total_cost:.2f}")
    print(f"\nResults:")
    print(f"  ★ Target service providers: {stats['legitimate_target']:,}")
    print(f"  ○ Legitimate but non-target: {stats['legitimate_non_target']:,}")
    print(f"  ✗ Not legitimate (false positives caught): {stats['not_legitimate']:,}")
    print(f"  ? Errors: {stats['errors']:,}")

    if stats['not_legitimate'] > 0:
        false_positive_rate = stats['not_legitimate'] / stats['processed'] * 100
        print(f"\nFalse positive rate: {false_positive_rate:.1f}%")


if __name__ == '__main__':
    main()
