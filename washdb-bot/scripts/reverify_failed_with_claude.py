#!/usr/bin/env python3
"""
Re-verify "failed" status companies using Claude API.

Many companies were marked as "failed" by the initial ML model (Ollama).
Claude is more accurate and may find some are actually valid pressure washing/cleaning businesses.

This script:
1. Finds companies with status = "failed" that haven't been verified by Claude
2. Re-verifies them using Claude API
3. Tracks API costs and stops when budget is reached
4. Updates both parse_metadata AND claude_verified field

Usage:
    python scripts/reverify_failed_with_claude.py --budget 50 --batch-size 100 [--include-inactive]
"""

import sys
import os
import time
import argparse
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
import json

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager
from scrape_site.claude_verifier import ClaudeVerifier


class FailedCompanyReverifier:
    """Re-verify failed companies using Claude API."""

    # Claude pricing (Haiku 3)
    PRICE_INPUT = 0.25 / 1_000_000   # $0.25 per million input tokens
    PRICE_OUTPUT = 1.25 / 1_000_000  # $1.25 per million output tokens

    def __init__(self, budget: float, min_reserve: float = 0.0, include_inactive: bool = False):
        """Initialize reverifier."""
        self.budget = budget
        self.min_reserve = min_reserve
        self.include_inactive = include_inactive
        self.db = DatabaseManager()
        self.verifier = ClaudeVerifier()

        self.total_cost = 0.0
        self.total_verified = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.status_changes = {'passed': 0, 'failed': 0, 'unknown': 0}

        print(f"Initialized Failed Company Reverifier")
        print(f"Budget: ${budget:.2f}")
        print(f"Reserve: ${min_reserve:.2f}")
        print(f"Available: ${budget - min_reserve:.2f}")
        print(f"Include inactive: {include_inactive}")

    def get_failed_companies(self, limit: int = 100):
        """Get companies marked as failed (verified=false) but not yet verified by Claude."""

        with self.db.get_session() as session:
            # Use standardized schema: verified=false means failed
            # Only get LLM-verified companies that need Claude re-verification
            query = text(f"""
                SELECT
                    c.id,
                    c.name,
                    c.website,
                    c.parse_metadata
                FROM companies c
                WHERE c.verified = false
                AND c.verification_type = 'llm'
                AND c.claude_verified = FALSE
                ORDER BY c.id
                LIMIT :limit
            """)

            result = session.execute(query, {'limit': limit})
            companies = result.fetchall()
            return companies

    def reverify_company(self, company_id: int, name: str, parse_metadata: dict):
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

                # Update database (both parse_metadata AND claude_verified)
                self._update_company(company_id, result, new_status)

                # Estimate cost
                estimated_input = 2000
                estimated_output = 300
                cost = (estimated_input * self.PRICE_INPUT) + (estimated_output * self.PRICE_OUTPUT)

                self.total_cost += cost
                self.total_input_tokens += estimated_input
                self.total_output_tokens += estimated_output
                self.total_verified += 1
                self.status_changes[new_status] = self.status_changes.get(new_status, 0) + 1

                status_emoji = "✓" if new_status == "passed" else ("✗" if new_status == "failed" else "?")
                old_status = "failed"
                change_indicator = " [CHANGED]" if new_status != old_status else ""

                print(f"  {status_emoji} ID {company_id}: {name[:40]} → {new_status}{change_indicator} (${cost:.4f})")

                return True

            except Exception as e:
                error_msg = str(e)
                # Check for rate limit errors
                if 'rate' in error_msg.lower() or '429' in error_msg:
                    retry_delay = (attempt + 1) * 10
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
            # Must have at least one relevant service
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
                    return 'unknown'
            else:
                return 'failed'
        else:
            return 'failed'

    def _update_company(self, company_id: int, result: dict, new_status: str):
        """Update company with Claude's assessment using standardized schema."""

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
            }

            # Save Claude's assessment as human_label for ML training
            human_label = 'pass' if new_status == 'passed' else 'fail'

            # Determine verified boolean from status
            verified_value = True if new_status == 'passed' else False

            # Update using standardized schema: verified, verification_type
            query_sql = f"""
                UPDATE companies
                SET
                    parse_metadata = jsonb_set(
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
                    claude_verified = TRUE,
                    claude_verified_at = NOW(),
                    verified = {str(verified_value).lower()},
                    verification_type = 'claude'
                WHERE id = {company_id}
            """

            session.execute(text(query_sql))
            session.commit()

    def run(self, batch_size: int = 100):
        """Run the reverification process."""

        print()
        print("=" * 80)
        print("Failed Company Reverification with Claude")
        print("=" * 80)
        print()

        total_processed = 0
        total_success = 0
        batch_num = 0

        while True:
            # Check budget
            remaining_budget = self.budget - self.total_cost - self.min_reserve
            if remaining_budget <= 0:
                print()
                print(f"Budget limit reached. Total cost: ${self.total_cost:.2f}")
                break

            # Get next batch
            companies = self.get_failed_companies(limit=batch_size)

            if not companies:
                print()
                print("No more failed companies to process!")
                break

            batch_num += 1
            print()
            print(f"Batch {batch_num}: Processing {len(companies)} companies...")
            print("-" * 80)

            # Process each company
            for company in companies:
                company_id, name, website, parse_metadata = company

                # Check budget before each company
                remaining_budget = self.budget - self.total_cost - self.min_reserve
                if remaining_budget <= 0:
                    print()
                    print(f"Budget limit reached during batch")
                    break

                success = self.reverify_company(company_id, name, parse_metadata or {})

                total_processed += 1
                if success:
                    total_success += 1

                # Small delay to avoid rate limits
                time.sleep(0.1)

            # Show batch summary
            print()
            print(f"Batch {batch_num} complete:")
            print(f"  Processed: {total_processed}")
            print(f"  Successful: {total_success}")
            print(f"  Total cost so far: ${self.total_cost:.2f}")
            print(f"  Status changes - Passed: {self.status_changes['passed']}, Failed: {self.status_changes['failed']}, Unknown: {self.status_changes['unknown']}")

        # Final summary
        print()
        print("=" * 80)
        print("Reverification Complete")
        print("=" * 80)
        print(f"Total companies processed: {total_processed}")
        print(f"Successful verifications: {total_success}")
        print(f"Total cost: ${self.total_cost:.2f}")
        print()
        print("Status Changes from 'failed' to:")
        print(f"  Passed: {self.status_changes['passed']} (Claude found these ARE valid businesses)")
        print(f"  Failed: {self.status_changes['failed']} (Confirmed not businesses)")
        print(f"  Unknown: {self.status_changes['unknown']} (Uncertain)")
        print()


def main():
    parser = argparse.ArgumentParser(description='Re-verify failed companies with Claude API')
    parser.add_argument('--budget', type=float, required=True, help='Budget in dollars')
    parser.add_argument('--min-reserve', type=float, default=0.0, help='Minimum reserve to maintain')
    parser.add_argument('--batch-size', type=int, default=100, help='Companies per batch')
    parser.add_argument('--include-inactive', action='store_true', help='Include inactive companies')
    args = parser.parse_args()

    reverifier = FailedCompanyReverifier(
        budget=args.budget,
        min_reserve=args.min_reserve,
        include_inactive=args.include_inactive
    )
    reverifier.run(batch_size=args.batch_size)


if __name__ == '__main__':
    main()
