#!/usr/bin/env python3
"""
Re-verify rejected companies with "washing" in URL using Claude API.

This script:
1. Finds companies with verification status = "failed" AND URL contains "washing"
2. Re-verifies them using Claude API (more accurate than local LLM)
3. Updates the database with Claude's assessment
4. Tracks API costs and stops when budget is reached

These companies were likely incorrectly rejected and deserve a second look.

Usage:
    python scripts/reverify_washing_urls.py --budget 10 --batch-size 50
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
import json

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager
from scrape_site.claude_verifier import ClaudeVerifier


class WashingURLReverifier:
    """Re-verify rejected companies with 'washing' in URL using Claude API."""

    # Claude pricing (Haiku 3)
    PRICE_INPUT = 0.25 / 1_000_000   # $0.25 per million input tokens
    PRICE_OUTPUT = 1.25 / 1_000_000  # $1.25 per million output tokens

    def __init__(self, budget: float, min_reserve: float = 0.0):
        """Initialize reverifier."""
        self.budget = budget
        self.min_reserve = min_reserve
        self.db = DatabaseManager()
        self.verifier = ClaudeVerifier()

        self.total_cost = 0.0
        self.total_verified = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_flipped = 0  # Changed from failed to passed

        print(f"Initialized Washing URL reverifier")
        print(f"Budget: ${budget:.2f}")
        print(f"Reserve: ${min_reserve:.2f}")
        print(f"Available: ${budget - min_reserve:.2f}")

    def get_washing_url_companies(self, limit: int = 50):
        """Get rejected companies with 'washing' in URL using standardized schema."""

        with self.db.get_session() as session:
            # Use standardized schema: verified=false means failed
            result = session.execute(text("""
                SELECT
                    id,
                    name,
                    website,
                    parse_metadata
                FROM companies
                WHERE verified = false
                AND (
                    website ILIKE '%washing%'
                    OR website ILIKE '%wash%'
                    OR name ILIKE '%washing%'
                    OR name ILIKE '%power wash%'
                    OR name ILIKE '%pressure wash%'
                )
                AND parse_metadata->'verification'->>'human_label' IS NULL
                ORDER BY id
                LIMIT :limit
            """), {'limit': limit})

            companies = result.fetchall()
            return companies

    def reverify_company(self, company_id: int, name: str, website: str, parse_metadata: dict):
        """Re-verify a single company using Claude API with retry logic."""

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Extract text from parse_metadata
                services_text = parse_metadata.get('services_text', '')
                about_text = parse_metadata.get('about_text', '')
                homepage_text = parse_metadata.get('homepage_text', '')

                # Call Claude verifier
                result = self.verifier.classify_company(
                    company_name=name,
                    services_text=services_text,
                    about_text=about_text,
                    homepage_text=homepage_text,
                    deep_verify=True
                )

                if not result:
                    print(f"  ❌ ID {company_id}: Claude API error")
                    return False

                # Determine new status based on Claude's assessment
                new_status = self._determine_status(result)

                # Check if we're flipping from failed to passed
                is_flipped = (new_status == "passed")

                # Update database
                self._update_company(company_id, result, new_status)

                # Estimate cost
                estimated_input = 2000
                estimated_output = 300
                cost = (estimated_input * self.PRICE_INPUT) + (estimated_output * self.PRICE_OUTPUT)

                self.total_cost += cost
                self.total_input_tokens += estimated_input
                self.total_output_tokens += estimated_output
                self.total_verified += 1

                if is_flipped:
                    self.total_flipped += 1

                status_emoji = "✓" if new_status == "passed" else ("✗" if new_status == "failed" else "?")
                flip_indicator = " [FLIPPED!]" if is_flipped else ""
                print(f"  {status_emoji} ID {company_id}: {name[:40]} → {new_status}{flip_indicator} (${cost:.4f})")
                print(f"     URL: {website[:60]}")

                return True

            except Exception as e:
                error_msg = str(e)
                # Check for rate limit errors
                if 'rate' in error_msg.lower() or '429' in error_msg:
                    retry_delay = (attempt + 1) * 10  # 10s, 20s, 30s
                    print(f"  ⏳ ID {company_id}: Rate limit hit, waiting {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"  ❌ ID {company_id}: Error - {e}")
                    return False

        print(f"  ❌ ID {company_id}: Failed after {max_retries} retries")
        return False

    def _determine_status(self, result: dict) -> str:
        """Determine status from Claude's classification."""

        # Type 1 = service provider
        if result['type'] == 1 and result['is_legitimate']:
            # Must have at least one service
            has_services = any([
                result.get('pressure_washing'),
                result.get('window_cleaning'),
                result.get('wood_restoration')
            ])

            if has_services:
                # Check confidence
                if result.get('confidence', 0) >= 0.7:
                    return 'passed'
                else:
                    return 'unknown'  # Still uncertain
            else:
                return 'failed'
        else:
            return 'failed'

    def _update_company(self, company_id: int, result: dict, new_status: str):
        """Update company with Claude's assessment and save as training data."""

        with self.db.get_session() as session:
            # Build Claude assessment details
            claude_assessment = {
                'claude_type': result['type'],
                'claude_services': {
                    'pressure_washing': result.get('pressure_washing', False),
                    'window_cleaning': result.get('window_cleaning', False),
                    'wood_restoration': result.get('wood_restoration', False),
                },
                'claude_scope': result['scope'],
                'claude_legitimate': result['is_legitimate'],
                'claude_confidence': result.get('confidence', 0.5),
                'claude_quality_signals': result.get('quality_signals', []),
                'claude_red_flags': result.get('red_flags', []),
                'claude_verified_at': datetime.now().isoformat(),
                'reverified_from_washing_url': True,  # Mark this special case
            }

            # IMPORTANT: Save Claude's assessment as human_label for ML training
            human_label = 'pass' if new_status == 'passed' else 'fail'

            # Determine verified boolean from status
            verified_value = True if new_status == 'passed' else False

            # Update using standardized schema: verified, verification_type
            query_sql = f"""
                UPDATE companies
                SET parse_metadata = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            parse_metadata,
                            '{{verification,status}}',
                            '{json.dumps(new_status).replace("'", "''")}'::jsonb
                        ),
                        '{{verification,claude_assessment}}',
                        '{json.dumps(claude_assessment).replace("'", "''")}'::jsonb
                    ),
                    '{{verification,human_label}}',
                    '{json.dumps(human_label).replace("'", "''")}'::jsonb
                ),
                verified = {str(verified_value).lower()},
                verification_type = 'claude'
                WHERE id = {company_id}
            """

            session.execute(text(query_sql))
            session.commit()

    def run(self, batch_size: int = 50):
        """Run the reverification process."""

        print("\n" + "=" * 70)
        print("WASHING URL RE-VERIFICATION")
        print("=" * 70)
        print("Re-verifying rejected companies with 'washing' in URL/name")
        print()

        # Get total count first using standardized schema
        with self.db.get_session() as session:
            result = session.execute(text("""
                SELECT COUNT(*)
                FROM companies
                WHERE verified = false
                AND (
                    website ILIKE '%washing%'
                    OR website ILIKE '%wash%'
                    OR name ILIKE '%washing%'
                    OR name ILIKE '%power wash%'
                    OR name ILIKE '%pressure wash%'
                )
                AND parse_metadata->'verification'->>'human_label' IS NULL
            """))
            total_candidates = result.scalar()
            print(f"Found {total_candidates} rejected companies with 'washing' in URL/name")
            print()

        while True:
            # Check budget
            remaining = self.budget - self.total_cost - self.min_reserve
            if remaining <= 0:
                print("\n" + "!" * 70)
                print("BUDGET LIMIT REACHED")
                print("!" * 70)
                break

            # Get next batch
            companies = self.get_washing_url_companies(limit=batch_size)

            if not companies:
                print(f"\n✅ All washing URL companies re-verified!")
                break

            print(f"\n--- Batch of {len(companies)} companies ---")
            print(f"Budget remaining: ${remaining:.2f}")
            print(f"Total spent so far: ${self.total_cost:.2f}")
            print(f"Flipped to PASSED: {self.total_flipped}")
            print()

            # Process batch
            for company in companies:
                company_id, name, website, parse_metadata = company

                # Check budget before each verification
                remaining = self.budget - self.total_cost - self.min_reserve
                if remaining <= 0.02:  # Stop if less than 2 cents left
                    print(f"\n⚠ Budget limit approaching, stopping...")
                    break

                self.reverify_company(company_id, name, website, parse_metadata)

                # Delay to avoid rate limits
                time.sleep(2.0)

            # Check if we should continue
            if remaining <= 0.02:
                break

        # Final summary
        print("\n" + "=" * 70)
        print("FINAL SUMMARY")
        print("=" * 70)
        print(f"Total verified: {self.total_verified}")
        print(f"Flipped from FAILED → PASSED: {self.total_flipped}")
        print(f"Total cost: ${self.total_cost:.2f}")
        print(f"Average cost: ${self.total_cost / max(1, self.total_verified):.4f} per verification")
        print(f"Input tokens: {self.total_input_tokens:,}")
        print(f"Output tokens: {self.total_output_tokens:,}")
        print()

        # Check remaining
        with self.db.get_session() as session:
            result = session.execute(text("""
                SELECT COUNT(*)
                FROM companies
                WHERE parse_metadata->'verification'->>'status' = 'failed'
                AND (
                    website ILIKE '%washing%'
                    OR website ILIKE '%wash%'
                    OR name ILIKE '%washing%'
                    OR name ILIKE '%power wash%'
                    OR name ILIKE '%pressure wash%'
                )
                AND parse_metadata->'verification'->>'human_label' IS NULL
            """))
            remaining_washing = result.scalar()

            print(f"Remaining washing URL companies (rejected): {remaining_washing}")

        print("=" * 70)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Re-verify rejected washing URL companies with Claude')
    parser.add_argument('--budget', type=float, default=10.0,
                       help='Total budget in USD (default: 10)')
    parser.add_argument('--min-reserve', type=float, default=0.0,
                       help='Minimum reserve to keep (default: 0)')
    parser.add_argument('--batch-size', type=int, default=50,
                       help='Companies per batch (default: 50)')

    args = parser.parse_args()

    reverifier = WashingURLReverifier(budget=args.budget, min_reserve=args.min_reserve)
    reverifier.run(batch_size=args.batch_size)
