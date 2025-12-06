#!/usr/bin/env python3
"""
Validate existing verifications by testing random passed/failed companies with Claude.

This helps us:
1. Check if Ollama/Mistral made correct decisions
2. Find disagreements between local LLM and Claude
3. Generate high-quality training data from both correct and incorrect predictions
4. Understand where the local LLM needs improvement

Usage:
    python scripts/validate_with_claude.py --passed-sample 50 --failed-sample 50 --budget 10
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
import json
import random

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager
from scrape_site.claude_verifier import ClaudeVerifier


class ClaudeValidator:
    """Validate existing verifications using Claude API."""

    # Claude pricing (Haiku)
    PRICE_INPUT = 0.25 / 1_000_000
    PRICE_OUTPUT = 1.25 / 1_000_000

    def __init__(self, budget: float):
        """Initialize validator."""
        self.budget = budget
        self.db = DatabaseManager()
        self.verifier = ClaudeVerifier()

        self.total_cost = 0.0
        self.total_validated = 0
        self.agreements = 0
        self.disagreements = 0
        self.disagreement_details = []

    def get_random_verified_companies(self, status: str, limit: int):
        """Get random companies with specific verification status."""

        with self.db.get_session() as session:
            result = session.execute(text("""
                SELECT
                    id,
                    name,
                    website,
                    parse_metadata
                FROM companies
                WHERE parse_metadata->'verification'->>'status' = :status
                AND parse_metadata->'verification'->>'human_label' IS NULL
                ORDER BY RANDOM()
                LIMIT :limit
            """), {'status': status, 'limit': limit})

            companies = result.fetchall()
            return companies

    def validate_company(self, company_id: int, name: str, parse_metadata: dict, expected_status: str):
        """Validate a single company with Claude."""

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

            # Determine Claude's assessment
            claude_status = self._determine_status(result)

            # Compare with expected
            agrees = (claude_status == expected_status)

            if agrees:
                self.agreements += 1
                print(f"  ✓ ID {company_id}: {name[:50]} - AGREES ({expected_status})")
            else:
                self.disagreements += 1
                self.disagreement_details.append({
                    'company_id': company_id,
                    'name': name,
                    'expected': expected_status,
                    'claude_says': claude_status,
                    'confidence': result.get('confidence', 0.5)
                })
                print(f"  ⚠ ID {company_id}: {name[:50]} - DISAGREES (Expected: {expected_status}, Claude: {claude_status})")

            # Save Claude's assessment as training data
            self._save_validation(company_id, result, claude_status, expected_status, agrees)

            # Estimate cost
            estimated_input = 2000
            estimated_output = 300
            cost = (estimated_input * self.PRICE_INPUT) + (estimated_output * self.PRICE_OUTPUT)

            self.total_cost += cost
            self.total_validated += 1

            return True

        except Exception as e:
            print(f"  ❌ ID {company_id}: Error - {e}")
            return False

    def _determine_status(self, result: dict) -> str:
        """Determine status from Claude's classification."""
        if result['type'] == 1 and result['is_legitimate']:
            has_services = any([
                result.get('pressure_washing'),
                result.get('window_cleaning'),
                result.get('wood_restoration')
            ])

            if has_services and result.get('confidence', 0) >= 0.7:
                return 'passed'
            else:
                return 'unknown'
        else:
            return 'failed'

    def _save_validation(self, company_id: int, result: dict, claude_status: str, original_status: str, agrees: bool):
        """Save validation results as training data."""

        with self.db.get_session() as session:
            # Build validation assessment
            validation_assessment = {
                'claude_status': claude_status,
                'original_status': original_status,
                'agrees': agrees,
                'claude_type': result['type'],
                'claude_services': {
                    'pressure_washing': result.get('pressure_washing', False),
                    'window_cleaning': result.get('window_cleaning', False),
                    'wood_restoration': result.get('wood_restoration', False),
                },
                'claude_legitimate': result['is_legitimate'],
                'claude_confidence': result.get('confidence', 0.5),
                'validated_at': datetime.now().isoformat(),
            }

            # If Claude agrees OR has high confidence, save as human_label for training
            if agrees or result.get('confidence', 0) >= 0.8:
                human_label = 'pass' if claude_status == 'passed' else 'fail'

                # Use f-string SQL with escaped quotes
                query_sql = f"""
                    UPDATE companies
                    SET parse_metadata = jsonb_set(
                        jsonb_set(
                            parse_metadata,
                            '{{verification,claude_validation}}',
                            '{json.dumps(validation_assessment).replace("'", "''")}'::jsonb
                        ),
                        '{{verification,human_label}}',
                        '{json.dumps(human_label).replace("'", "''")}'::jsonb
                    )
                    WHERE id = {company_id}
                """
                session.execute(text(query_sql))
            else:
                # Just save validation, don't set as ground truth
                # Use f-string SQL with escaped quotes
                query_sql = f"""
                    UPDATE companies
                    SET parse_metadata = jsonb_set(
                        parse_metadata,
                        '{{verification,claude_validation}}',
                        '{json.dumps(validation_assessment).replace("'", "''")}'::jsonb
                    )
                    WHERE id = {company_id}
                """
                session.execute(text(query_sql))

            session.commit()

    def run(self, passed_sample: int, failed_sample: int):
        """Run validation process."""

        print("\n" + "=" * 70)
        print("CLAUDE VALIDATION - Testing Local LLM Accuracy")
        print("=" * 70)
        print(f"Budget: ${self.budget:.2f}")
        print(f"Sampling: {passed_sample} passed + {failed_sample} failed = {passed_sample + failed_sample} total")
        print()

        # Get random samples
        print("Fetching random samples...")
        passed_companies = self.get_random_verified_companies('passed', passed_sample)
        failed_companies = self.get_random_verified_companies('failed', failed_sample)

        print(f"  Found {len(passed_companies)} passed companies")
        print(f"  Found {len(failed_companies)} failed companies")
        print()

        # Validate passed companies
        print("=" * 70)
        print("VALIDATING 'PASSED' COMPANIES")
        print("=" * 70)
        for company in passed_companies:
            if self.total_cost >= self.budget:
                print("\n⚠ Budget limit reached")
                break

            company_id, name, website, parse_metadata = company
            self.validate_company(company_id, name, parse_metadata, 'passed')
            time.sleep(0.5)  # Rate limiting

        # Validate failed companies
        print("\n" + "=" * 70)
        print("VALIDATING 'FAILED' COMPANIES")
        print("=" * 70)
        for company in failed_companies:
            if self.total_cost >= self.budget:
                print("\n⚠ Budget limit reached")
                break

            company_id, name, website, parse_metadata = company
            self.validate_company(company_id, name, parse_metadata, 'failed')
            time.sleep(0.5)  # Rate limiting

        # Print summary
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)
        print(f"Total validated: {self.total_validated}")
        print(f"Agreements: {self.agreements} ({100*self.agreements/max(1,self.total_validated):.1f}%)")
        print(f"Disagreements: {self.disagreements} ({100*self.disagreements/max(1,self.total_validated):.1f}%)")
        print(f"Total cost: ${self.total_cost:.4f}")
        print()

        if self.disagreement_details:
            print("DISAGREEMENTS (Local LLM may need improvement):")
            print("-" * 70)
            for d in self.disagreement_details[:20]:  # Show first 20
                print(f"  ID {d['company_id']}: {d['name'][:50]}")
                print(f"    Local LLM said: {d['expected']}")
                print(f"    Claude says: {d['claude_says']} (confidence: {d['confidence']:.2f})")
                print()

        print("=" * 70)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Validate verifications with Claude')
    parser.add_argument('--passed-sample', type=int, default=50,
                       help='Number of passed companies to validate (default: 50)')
    parser.add_argument('--failed-sample', type=int, default=50,
                       help='Number of failed companies to validate (default: 50)')
    parser.add_argument('--budget', type=float, default=10.0,
                       help='Budget in USD for validation (default: 10)')

    args = parser.parse_args()

    validator = ClaudeValidator(budget=args.budget)
    validator.run(passed_sample=args.passed_sample, failed_sample=args.failed_sample)
