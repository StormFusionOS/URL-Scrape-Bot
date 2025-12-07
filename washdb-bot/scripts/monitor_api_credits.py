#!/usr/bin/env python3
"""
Monitor Claude API credit usage and stop workers when depleted.

This script:
1. Tracks API calls and estimated costs
2. Monitors remaining credits
3. Automatically stops verification workers when credits are low
4. Provides usage statistics

Usage:
    python scripts/monitor_api_credits.py --budget 50 --min-reserve 5
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime
import anthropic
from dotenv import load_dotenv

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment
load_dotenv()

from db.database_manager import DatabaseManager
from sqlalchemy import text
import subprocess


class CreditMonitor:
    """Monitor API credit usage."""

    # Claude API pricing (as of 2024)
    # Sonnet 3.5: $3 per million input tokens, $15 per million output tokens
    PRICING = {
        'claude-3-haiku-20240307': {
            'input': 0.25 / 1_000_000,   # $0.25 per million tokens
            'output': 1.25 / 1_000_000,  # $1.25 per million tokens
        },
        'claude-3-5-sonnet-20240620': {
            'input': 3.0 / 1_000_000,   # $3 per million tokens
            'output': 15.0 / 1_000_000,  # $15 per million tokens
        },
        'claude-3-5-sonnet-20241022': {
            'input': 3.0 / 1_000_000,   # $3 per million tokens
            'output': 15.0 / 1_000_000,  # $15 per million tokens
        }
    }

    def __init__(self, budget: float, min_reserve: float = 5.0):
        """
        Initialize credit monitor.

        Args:
            budget: Total budget in USD
            min_reserve: Minimum reserve to keep (stop before hitting zero)
        """
        self.budget = budget
        self.min_reserve = min_reserve
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self.model = os.getenv('CLAUDE_MODEL', 'claude-3-haiku-20240307')

        if not self.api_key or self.api_key == 'your-api-key-here':
            raise ValueError("ANTHROPIC_API_KEY not set in .env")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.db = DatabaseManager()

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.api_calls = 0

    def get_verification_stats(self):
        """Get verification progress from database."""

        with self.db.get_session() as session:
            result = session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE parse_metadata->'verification'->>'status' = 'passed') as passed,
                    COUNT(*) FILTER (WHERE parse_metadata->'verification'->>'status' = 'failed') as failed,
                    COUNT(*) FILTER (WHERE parse_metadata->'verification'->>'status' = 'unknown') as unknown,
                    COUNT(*) FILTER (WHERE parse_metadata->'verification'->>'status' = 'in_progress') as in_progress,
                    COUNT(*) FILTER (WHERE parse_metadata->'verification' IS NULL) as unverified
                FROM companies
                WHERE parse_metadata->>'filter_reason' = 'accepted'
            """))

            stats = result.fetchone()
            return {
                'passed': stats[0] or 0,
                'failed': stats[1] or 0,
                'unknown': stats[2] or 0,
                'in_progress': stats[3] or 0,
                'unverified': stats[4] or 0,
            }

    def estimate_usage(self):
        """Estimate token usage from recent verifications."""

        with self.db.get_session() as session:
            # Get recent verifications with LLM data
            result = session.execute(text("""
                SELECT
                    parse_metadata->'verification'->>'llm_details' as llm_details
                FROM companies
                WHERE (parse_metadata->'verification'->>'verified_at')::timestamp > NOW() - INTERVAL '1 hour'
                AND parse_metadata->'verification'->>'llm_details' IS NOT NULL
                LIMIT 100
            """))

            verifications = result.fetchall()

            if not verifications:
                return 0, 0, 0

            # Estimate tokens per verification
            # Average: ~2000 input tokens (HTML content) + ~200 output tokens (analysis)
            avg_input = 2000
            avg_output = 200

            total_verifications = len(verifications)
            total_input = total_verifications * avg_input
            total_output = total_verifications * avg_output

            # Calculate cost
            pricing = self.PRICING.get(self.model, self.PRICING['claude-3-5-sonnet-20241022'])
            cost = (total_input * pricing['input']) + (total_output * pricing['output'])

            return total_input, total_output, cost

    def calculate_remaining_verifications(self):
        """Calculate how many more verifications we can do with remaining budget."""

        remaining_budget = self.budget - self.total_cost - self.min_reserve

        if remaining_budget <= 0:
            return 0

        # Estimate cost per verification
        pricing = self.PRICING.get(self.model, self.PRICING['claude-3-5-sonnet-20241022'])
        cost_per_verification = (2000 * pricing['input']) + (200 * pricing['output'])

        return int(remaining_budget / cost_per_verification)

    def stop_workers(self):
        """Stop all verification workers."""

        print("\n" + "=" * 70)
        print("STOPPING VERIFICATION WORKERS")
        print("=" * 70)

        try:
            # Kill all verification worker processes
            result = subprocess.run(
                ['pkill', '-f', 'run_verification_workers.py'],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                print("✓ Stopped all verification workers")
                return True
            elif result.returncode == 1:
                print("✓ No workers were running")
                return True
            else:
                print(f"❌ Error stopping workers: {result.stderr}")
                return False

        except Exception as e:
            print(f"❌ Error stopping workers: {e}")
            return False

    def print_status(self, stats):
        """Print current status."""

        os.system('clear')

        print("=" * 70)
        print("CLAUDE API CREDIT MONITOR")
        print("=" * 70)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        print("BUDGET:")
        print(f"  Total Budget:      ${self.budget:.2f}")
        print(f"  Spent So Far:      ${self.total_cost:.2f}")
        print(f"  Remaining:         ${self.budget - self.total_cost:.2f}")
        print(f"  Min Reserve:       ${self.min_reserve:.2f}")
        print(f"  Available to Spend: ${max(0, self.budget - self.total_cost - self.min_reserve):.2f}")
        print()

        print("TOKEN USAGE:")
        print(f"  Input Tokens:  {self.total_input_tokens:,}")
        print(f"  Output Tokens: {self.total_output_tokens:,}")
        print(f"  Total Tokens:  {self.total_input_tokens + self.total_output_tokens:,}")
        print()

        print("VERIFICATION PROGRESS:")
        print(f"  ✓ Passed:       {stats['passed']:,}")
        print(f"  ✗ Failed:       {stats['failed']:,}")
        print(f"  ? Unknown:      {stats['unknown']:,}")
        print(f"  ⟳ In Progress:  {stats['in_progress']:,}")
        print(f"  ○ Unverified:   {stats['unverified']:,}")
        print()

        remaining_verifications = self.calculate_remaining_verifications()
        print(f"ESTIMATED REMAINING VERIFICATIONS: ~{remaining_verifications:,}")
        print()

        # Progress bar
        progress = (self.total_cost / self.budget) * 100 if self.budget > 0 else 0
        bar_length = 50
        filled = int(bar_length * progress / 100)
        bar = '█' * filled + '░' * (bar_length - filled)
        print(f"BUDGET USAGE: [{bar}] {progress:.1f}%")
        print()

        print("=" * 70)
        print("Press Ctrl+C to stop monitoring and halt workers")
        print("=" * 70)

    def monitor(self, check_interval: int = 30):
        """
        Monitor credit usage continuously.

        Args:
            check_interval: Seconds between checks
        """

        print("Starting credit monitor...")
        print(f"Budget: ${self.budget:.2f}")
        print(f"Min Reserve: ${self.min_reserve:.2f}")
        print(f"Check Interval: {check_interval}s")
        print()

        try:
            while True:
                # Get current stats
                stats = self.get_verification_stats()

                # Estimate usage
                input_tokens, output_tokens, cost = self.estimate_usage()

                if input_tokens > 0:
                    self.total_input_tokens += input_tokens
                    self.total_output_tokens += output_tokens
                    self.total_cost += cost

                # Print status
                self.print_status(stats)

                # Check if budget exhausted
                remaining_budget = self.budget - self.total_cost - self.min_reserve

                if remaining_budget <= 0:
                    print("\n" + "!" * 70)
                    print("BUDGET LIMIT REACHED!")
                    print("!" * 70)
                    print(f"\nSpent: ${self.total_cost:.2f}")
                    print(f"Budget: ${self.budget:.2f}")
                    print(f"Reserve: ${self.min_reserve:.2f}")
                    print()

                    self.stop_workers()

                    print("\nFinal Statistics:")
                    print(f"  Total Verifications: {stats['passed'] + stats['failed'] + stats['unknown']:,}")
                    print(f"  Passed: {stats['passed']:,}")
                    print(f"  Failed: {stats['failed']:,}")
                    print(f"  Unknown: {stats['unknown']:,}")
                    print(f"\nTotal Cost: ${self.total_cost:.2f}")
                    print(f"Cost per Verification: ${self.total_cost / max(1, stats['passed'] + stats['failed'] + stats['unknown']):.4f}")

                    break

                # Wait before next check
                time.sleep(check_interval)

        except KeyboardInterrupt:
            print("\n\nMonitoring interrupted by user")
            response = input("\nDo you want to stop the workers? (yes/no): ")
            if response.lower() == 'yes':
                self.stop_workers()
            else:
                print("Workers still running. Monitor stopped.")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Monitor API credit usage')
    parser.add_argument('--budget', type=float, default=50.0,
                       help='Total budget in USD (default: 50)')
    parser.add_argument('--min-reserve', type=float, default=5.0,
                       help='Minimum reserve to keep (default: 5)')
    parser.add_argument('--check-interval', type=int, default=30,
                       help='Seconds between checks (default: 30)')

    args = parser.parse_args()

    monitor = CreditMonitor(budget=args.budget, min_reserve=args.min_reserve)
    monitor.monitor(check_interval=args.check_interval)
