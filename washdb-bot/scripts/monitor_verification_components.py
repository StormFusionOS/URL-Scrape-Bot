#!/usr/bin/env python3
"""
Monitor Verification Component Performance

Tracks how rules, ML classifier, and LLM scores contribute to final decisions.
Goal: Identify when we can remove rules-based scoring and rely purely on LLM.

Usage:
    python scripts/monitor_verification_components.py --interval 300 --samples 100
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
from collections import defaultdict

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager


class VerificationMonitor:
    """Monitor verification component performance."""

    def __init__(self, sample_size: int = 100):
        self.db = DatabaseManager()
        self.sample_size = sample_size

    def get_recent_verifications(self):
        """Get recently verified companies with component scores."""

        with self.db.get_session() as session:
            result = session.execute(text("""
                SELECT
                    id,
                    name,
                    parse_metadata->'verification'->>'status' as status,
                    (parse_metadata->'verification'->>'rule_score')::float as rule_score,
                    (parse_metadata->'verification'->>'llm_score')::float as llm_score,
                    (parse_metadata->'verification'->>'web_score')::float as web_score,
                    (parse_metadata->'verification'->>'combined_score')::float as combined_score,
                    (parse_metadata->'verification'->>'llm_confidence')::float as llm_confidence,
                    (parse_metadata->'verification'->>'llm_type')::int as llm_type,
                    parse_metadata->'verification'->>'human_label' as human_label
                FROM companies
                WHERE parse_metadata->'verification' IS NOT NULL
                AND parse_metadata->'verification'->>'status' IN ('passed', 'failed', 'unknown')
                ORDER BY id DESC
                LIMIT :limit
            """), {'limit': self.sample_size})

            return result.fetchall()

    def analyze_component_agreement(self, verifications):
        """Analyze agreement between rules, ML, and LLM."""

        stats = {
            'total': len(verifications),
            'by_status': defaultdict(int),
            'score_ranges': {
                'rule': {'high': 0, 'medium': 0, 'low': 0},
                'llm': {'high': 0, 'medium': 0, 'low': 0},
                'combined': {'high': 0, 'medium': 0, 'low': 0},
            },
            'component_agreement': {
                'all_agree_pass': 0,      # Rules, LLM, and final all say pass
                'all_agree_fail': 0,      # Rules, LLM, and final all say fail
                'llm_overrides_rules': 0, # LLM contradicts rules but wins
                'rules_override_llm': 0,  # Rules contradict LLM but win
                'uncertain': 0,           # Unknown status
            },
            'llm_confidence_distribution': {
                'high_confidence': 0,     # >= 0.8
                'medium_confidence': 0,   # 0.5 - 0.8
                'low_confidence': 0,      # < 0.5
            },
            'human_label_agreement': {
                'correct_pass': 0,
                'correct_fail': 0,
                'incorrect_pass': 0,
                'incorrect_fail': 0,
                'no_label': 0,
            }
        }

        for v in verifications:
            v_id, name, status, rule_score, llm_score, web_score, combined_score, llm_conf, llm_type, human_label = v

            # Status distribution
            stats['by_status'][status] += 1

            # Score ranges
            if rule_score is not None:
                if rule_score >= 70: stats['score_ranges']['rule']['high'] += 1
                elif rule_score >= 40: stats['score_ranges']['rule']['medium'] += 1
                else: stats['score_ranges']['rule']['low'] += 1

            if llm_score is not None:
                if llm_score >= 70: stats['score_ranges']['llm']['high'] += 1
                elif llm_score >= 40: stats['score_ranges']['llm']['medium'] += 1
                else: stats['score_ranges']['llm']['low'] += 1

            if combined_score is not None:
                if combined_score >= 70: stats['score_ranges']['combined']['high'] += 1
                elif combined_score >= 40: stats['score_ranges']['combined']['medium'] += 1
                else: stats['score_ranges']['combined']['low'] += 1

            # Component agreement analysis
            if status == 'unknown':
                stats['component_agreement']['uncertain'] += 1
            elif status == 'passed':
                # Both agree on pass
                if rule_score and llm_score and rule_score >= 60 and llm_score >= 60:
                    stats['component_agreement']['all_agree_pass'] += 1
                # LLM says pass but rules say fail (LLM override)
                elif rule_score and llm_score and rule_score < 40 and llm_score >= 60:
                    stats['component_agreement']['llm_overrides_rules'] += 1
            elif status == 'failed':
                # Both agree on fail
                if rule_score and llm_score and rule_score < 40 and llm_score < 40:
                    stats['component_agreement']['all_agree_fail'] += 1
                # Rules say fail but LLM says pass (rules override)
                elif rule_score and llm_score and rule_score < 40 and llm_score >= 60:
                    stats['component_agreement']['rules_override_llm'] += 1

            # LLM confidence distribution
            if llm_conf is not None:
                if llm_conf >= 0.8:
                    stats['llm_confidence_distribution']['high_confidence'] += 1
                elif llm_conf >= 0.5:
                    stats['llm_confidence_distribution']['medium_confidence'] += 1
                else:
                    stats['llm_confidence_distribution']['low_confidence'] += 1

            # Human label agreement (if available)
            if human_label is not None:
                if human_label == 'pass' and status == 'passed':
                    stats['human_label_agreement']['correct_pass'] += 1
                elif human_label == 'fail' and status == 'failed':
                    stats['human_label_agreement']['correct_fail'] += 1
                elif human_label == 'pass' and status == 'failed':
                    stats['human_label_agreement']['incorrect_fail'] += 1
                elif human_label == 'fail' and status == 'passed':
                    stats['human_label_agreement']['incorrect_pass'] += 1
            else:
                stats['human_label_agreement']['no_label'] += 1

        return stats

    def print_report(self, stats):
        """Print analysis report."""

        total = stats['total']

        print("\n" + "=" * 70)
        print("VERIFICATION COMPONENT ANALYSIS")
        print("=" * 70)
        print(f"Sample Size: {total} recent verifications")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print()

        # Status distribution
        print("STATUS DISTRIBUTION")
        print("-" * 70)
        for status, count in stats['by_status'].items():
            pct = (count / total * 100) if total > 0 else 0
            print(f"  {status:>10}: {count:>5} ({pct:>5.1f}%)")
        print()

        # Score ranges
        print("SCORE COMPONENT RANGES")
        print("-" * 70)
        for component in ['rule', 'llm', 'combined']:
            ranges = stats['score_ranges'][component]
            print(f"  {component.upper()} Score:")
            print(f"    High (≥70):   {ranges['high']:>5} ({ranges['high']/total*100:>5.1f}%)")
            print(f"    Medium (40-70): {ranges['medium']:>5} ({ranges['medium']/total*100:>5.1f}%)")
            print(f"    Low (<40):    {ranges['low']:>5} ({ranges['low']/total*100:>5.1f}%)")
        print()

        # Component agreement
        print("COMPONENT AGREEMENT ANALYSIS")
        print("-" * 70)
        agree = stats['component_agreement']
        print(f"  All Agree (Pass):     {agree['all_agree_pass']:>5} ({agree['all_agree_pass']/total*100:>5.1f}%)")
        print(f"  All Agree (Fail):     {agree['all_agree_fail']:>5} ({agree['all_agree_fail']/total*100:>5.1f}%)")
        print(f"  LLM Overrides Rules:  {agree['llm_overrides_rules']:>5} ({agree['llm_overrides_rules']/total*100:>5.1f}%)")
        print(f"  Rules Override LLM:   {agree['rules_override_llm']:>5} ({agree['rules_override_llm']/total*100:>5.1f}%)")
        print(f"  Uncertain (Unknown):  {agree['uncertain']:>5} ({agree['uncertain']/total*100:>5.1f}%)")
        print()

        # LLM confidence
        print("LLM CONFIDENCE DISTRIBUTION")
        print("-" * 70)
        conf = stats['llm_confidence_distribution']
        print(f"  High (≥0.8):   {conf['high_confidence']:>5} ({conf['high_confidence']/total*100:>5.1f}%)")
        print(f"  Medium (0.5-0.8): {conf['medium_confidence']:>5} ({conf['medium_confidence']/total*100:>5.1f}%)")
        print(f"  Low (<0.5):    {conf['low_confidence']:>5} ({conf['low_confidence']/total*100:>5.1f}%)")
        print()

        # Human label agreement
        print("ACCURACY VS HUMAN LABELS (Claude)")
        print("-" * 70)
        ha = stats['human_label_agreement']
        labeled = ha['correct_pass'] + ha['correct_fail'] + ha['incorrect_pass'] + ha['incorrect_fail']
        if labeled > 0:
            accuracy = (ha['correct_pass'] + ha['correct_fail']) / labeled * 100
            print(f"  Correct (Pass):   {ha['correct_pass']:>5} ({ha['correct_pass']/labeled*100:>5.1f}%)")
            print(f"  Correct (Fail):   {ha['correct_fail']:>5} ({ha['correct_fail']/labeled*100:>5.1f}%)")
            print(f"  Incorrect (Pass): {ha['incorrect_pass']:>5} ({ha['incorrect_pass']/labeled*100:>5.1f}%)")
            print(f"  Incorrect (Fail): {ha['incorrect_fail']:>5} ({ha['incorrect_fail']/labeled*100:>5.1f}%)")
            print(f"  No Label:         {ha['no_label']:>5}")
            print(f"\n  OVERALL ACCURACY: {accuracy:>5.1f}%")
        else:
            print("  No human-labeled data in sample")
        print()

        # Recommendations
        print("RECOMMENDATIONS")
        print("-" * 70)

        # Calculate LLM reliability
        llm_high_conf = conf['high_confidence'] / total * 100 if total > 0 else 0
        uncertain_rate = agree['uncertain'] / total * 100 if total > 0 else 0

        if llm_high_conf >= 95 and uncertain_rate <= 0.1:
            print("  ✓ LLM is HIGHLY RELIABLE (95%+ high confidence, <0.1% uncertain)")
            print("  → READY to phase out rules-based scoring")
            print("  → Consider switching to LLM-only verification")
        elif llm_high_conf >= 85 and uncertain_rate <= 0.5:
            print("  ✓ LLM is RELIABLE (85%+ high confidence, <0.5% uncertain)")
            print("  → Continue Claude training for 1-2 more weeks")
            print("  → Rules can be phased out soon")
        elif llm_high_conf >= 70 and uncertain_rate <= 1.0:
            print("  ⚠ LLM is IMPROVING (70%+ high confidence, <1% uncertain)")
            print("  → Continue Claude training for 2-4 more weeks")
            print("  → Keep rules-based scoring for now")
        else:
            print("  ⚠ LLM needs MORE TRAINING")
            print(f"  → Current high confidence: {llm_high_conf:.1f}% (target: 85%+)")
            print(f"  → Current uncertain rate: {uncertain_rate:.1f}% (target: <0.5%)")
            print("  → Continue aggressive Claude labeling")

        print("=" * 70)

    def monitor_continuous(self, interval: int = 300):
        """Continuously monitor and report."""

        print(f"Starting continuous monitoring (interval: {interval}s)")
        print("Press Ctrl+C to stop")

        try:
            while True:
                verifications = self.get_recent_verifications()
                stats = self.analyze_component_agreement(verifications)
                self.print_report(stats)

                print(f"\nNext update in {interval} seconds...")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Monitor verification component performance')
    parser.add_argument('--interval', type=int, default=300,
                       help='Update interval in seconds (default: 300)')
    parser.add_argument('--samples', type=int, default=100,
                       help='Number of recent verifications to analyze (default: 100)')
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit (no continuous monitoring)')

    args = parser.parse_args()

    monitor = VerificationMonitor(sample_size=args.samples)

    if args.once:
        verifications = monitor.get_recent_verifications()
        stats = monitor.analyze_component_agreement(verifications)
        monitor.print_report(stats)
    else:
        monitor.monitor_continuous(interval=args.interval)
