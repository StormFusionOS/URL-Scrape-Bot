#!/usr/bin/env python3
"""
Claude Prompt Optimizer - Scheduled Job

Runs weekly (Sunday 3 AM) to optimize prompts based on performance.

Tasks:
1. Analyze last week's Claude performance
2. Identify misclassifications (where human corrected Claude)
3. Select new few-shot examples (include errors + diverse cases)
4. Create new prompt version in database
5. Deploy new version (mark as active)

Usage:
    python verification/jobs/claude_prompt_optimizer.py [--days 7] [--dry-run]
"""

import sys
import os
import logging
import argparse
import json
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from db.database_manager import DatabaseManager
from verification.few_shot_selector import FewShotSelector
from verification.config_verifier import (
    CLAUDE_NUM_FEW_SHOT_EXAMPLES,
    CLAUDE_NUM_PROVIDER_EXAMPLES,
    CLAUDE_NUM_NON_PROVIDER_EXAMPLES,
    CLAUDE_NUM_TRICKY_EXAMPLES
)

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_prompt_performance(days: int = 7) -> dict:
    """
    Analyze Claude's performance over the last N days.

    Returns:
        Dictionary with performance metrics
    """
    db_manager = DatabaseManager()

    query = """
        SELECT
            prompt_version,
            COUNT(*) as total_reviews,
            AVG(confidence) as avg_confidence,
            COUNT(*) FILTER (WHERE decision = 'approve') as approvals,
            COUNT(*) FILTER (WHERE decision = 'deny') as denials,
            COUNT(*) FILTER (WHERE decision = 'unclear') as unclear,
            COUNT(*) FILTER (WHERE human_reviewed = true) as human_reviewed,
            COUNT(*) FILTER (
                WHERE human_reviewed = true
                AND decision != human_decision
            ) as misclassifications,
            AVG(api_latency_ms) as avg_latency_ms,
            SUM(cost_estimate) as total_cost,
            AVG(CASE WHEN cached_tokens > 0 THEN 1.0 ELSE 0.0 END) as cache_hit_rate
        FROM claude_review_audit
        WHERE reviewed_at >= NOW() - INTERVAL '%(days)s days'
        GROUP BY prompt_version
        ORDER BY prompt_version DESC
    """

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, {'days': days})
        rows = cursor.fetchall()

    if not rows:
        logger.warning(f"No reviews found in last {days} days")
        return {}

    results = {}
    for row in rows:
        (version, total, avg_conf, approvals, denials, unclear,
         human_reviewed, misclass, avg_lat, cost, cache_rate) = row

        accuracy = None
        if human_reviewed > 0:
            accuracy = 1.0 - (misclass / human_reviewed)

        results[version] = {
            'total_reviews': total,
            'avg_confidence': round(float(avg_conf), 3),
            'approval_rate': round(approvals / total, 3),
            'denial_rate': round(denials / total, 3),
            'unclear_rate': round(unclear / total, 3),
            'human_reviewed': human_reviewed,
            'misclassifications': misclass,
            'accuracy': round(accuracy, 3) if accuracy else None,
            'avg_latency_ms': int(avg_lat),
            'total_cost': round(float(cost), 4),
            'cache_hit_rate': round(float(cache_rate), 3)
        }

    return results


def get_misclassifications(limit: int = 20) -> list:
    """
    Get cases where Claude was wrong (human corrected).

    Returns:
        List of company IDs with misclassifications
    """
    db_manager = DatabaseManager()

    query = """
        SELECT
            company_id,
            decision as claude_decision,
            human_decision,
            confidence,
            reasoning
        FROM claude_review_audit
        WHERE human_reviewed = true
          AND decision != human_decision
        ORDER BY reviewed_at DESC
        LIMIT %(limit)s
    """

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, {'limit': limit})
        rows = cursor.fetchall()

    misclassifications = []
    for company_id, claude_dec, human_dec, confidence, reasoning in rows:
        misclassifications.append({
            'company_id': company_id,
            'claude_decision': claude_dec,
            'human_decision': human_dec,
            'confidence': float(confidence),
            'reasoning': reasoning
        })

    logger.info(f"Found {len(misclassifications)} misclassifications")
    return misclassifications


def create_optimized_examples(misclassifications: list) -> list:
    """
    Create optimized few-shot examples.

    Strategy:
    - Include 2 recent misclassifications (learning examples)
    - Include 3 clear provider examples (diverse)
    - Include 3 clear non-provider examples (diverse)
    """
    selector = FewShotSelector()

    # Get clear examples
    examples = selector.select_examples(
        n_provider=CLAUDE_NUM_PROVIDER_EXAMPLES,
        n_non_provider=CLAUDE_NUM_NON_PROVIDER_EXAMPLES,
        n_tricky=CLAUDE_NUM_TRICKY_EXAMPLES
    )

    logger.info(f"Selected {len(examples)} optimized examples")
    return examples


def get_current_prompt_text() -> str:
    """Get the current active prompt text."""
    db_manager = DatabaseManager()

    query = """
        SELECT prompt_text
        FROM claude_prompt_versions
        WHERE is_active = true
        LIMIT 1
    """

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        row = cursor.fetchone()

    if row:
        return row[0]

    # Return default if no active prompt
    return """You are a business verification specialist. Your task is to determine if a company is a legitimate service provider (e.g., pressure washing, window cleaning) or a non-provider (directory, equipment seller, training course, blog, lead generation agency).

## Context
You have access to:
- Automated verification signals (scores, ML predictions, red flags)
- Website content (services, about, homepage text)
- Business info (name, contact, location)

## Decision Criteria
APPROVE (legitimate provider) if:
- Offers direct services to customers (residential or commercial)
- Has clear contact info (phone, address, or service area)
- No red flags indicating directory/agency/franchise

DENY (non-provider) if:
- Directory or listing site
- Equipment sales only
- Training courses only
- Lead generation agency
- Blog or information-only site
- Franchise directory

UNCLEAR if:
- Insufficient information
- Conflicting signals
- Legitimate provider BUT also sells equipment/training

## Output Format
Respond with JSON:
{
  "decision": "approve" | "deny" | "unclear",
  "confidence": 0.85,  // 0.0-1.0
  "reasoning": "Brief explanation of decision (2-3 sentences)",
  "primary_services": ["pressure washing", "window cleaning"],
  "red_flags": ["franchise"] | [],
  "is_provider": true | false
}"""


def get_next_version_number() -> str:
    """Get next version number."""
    db_manager = DatabaseManager()

    query = """
        SELECT version
        FROM claude_prompt_versions
        ORDER BY deployed_at DESC
        LIMIT 1
    """

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        row = cursor.fetchone()

    if not row:
        return 'v1.1'

    current = row[0]
    # Parse version (e.g., 'v1.0' -> 'v1.1')
    if current.startswith('v'):
        parts = current[1:].split('.')
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return f'v{major}.{minor + 1}'

    return 'v1.1'


def deploy_prompt_version(
    version: str,
    prompt_text: str,
    examples: list,
    notes: str,
    dry_run: bool = False
) -> bool:
    """
    Deploy new prompt version.

    Args:
        version: Version string (e.g., 'v1.1')
        prompt_text: System prompt text
        examples: Few-shot examples
        notes: Deployment notes
        dry_run: If True, don't actually deploy

    Returns:
        True if successful
    """
    if dry_run:
        logger.info(f"DRY RUN - Would deploy version {version} with {len(examples)} examples")
        return True

    db_manager = DatabaseManager()

    try:
        with db_manager.get_connection() as conn:
                        # Deactivate current version
            result = conn.execute(text("""
                UPDATE claude_prompt_versions
                SET is_active = false,
                    deprecated_at = NOW())
                WHERE is_active = true
            """)

            # Insert new version
            result = conn.execute(text("""
                INSERT INTO claude_prompt_versions (
                    version,
                    prompt_text,
                    few_shot_examples,
                    deployed_at,
                    is_active,
                    notes
                )) VALUES (
                    %(version)s,
                    %(prompt_text)s,
                    %(examples)s,
                    NOW(),
                    true,
                    %(notes)s
                )
            """, {
                'version': version,
                'prompt_text': prompt_text,
                'examples': json.dumps(examples),
                'notes': notes
            })

            # commit handled by context manager

        logger.info(f"✓ Deployed prompt version {version}")
        return True

    except Exception as e:
        logger.error(f"Failed to deploy prompt version: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Optimize Claude prompts based on performance')
    parser.add_argument('--days', type=int, default=7, help='Days of data to analyze')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without deploying')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("CLAUDE PROMPT OPTIMIZER")
    logger.info("=" * 70)

    # 1. Analyze performance
    logger.info(f"\nAnalyzing performance (last {args.days} days)...")
    performance = analyze_prompt_performance(days=args.days)

    if performance:
        for version, metrics in performance.items():
            logger.info(f"\n{version}:")
            for key, value in metrics.items():
                logger.info(f"  {key}: {value}")
    else:
        logger.warning("No performance data available yet")

    # 2. Get misclassifications
    logger.info("\nIdentifying misclassifications...")
    misclassifications = get_misclassifications(limit=20)

    if misclassifications:
        logger.info("Recent misclassifications:")
        for i, error in enumerate(misclassifications[:5], 1):
            logger.info(
                f"  {i}. Company {error['company_id']}: "
                f"Claude={error['claude_decision']} vs Human={error['human_decision']} "
                f"(confidence: {error['confidence']:.2f})"
            )
        if len(misclassifications) > 5:
            logger.info(f"  ... and {len(misclassifications) - 5} more")

    # 3. Create optimized examples
    logger.info("\nSelecting optimized few-shot examples...")
    examples = create_optimized_examples(misclassifications)

    logger.info(f"Selected {len(examples)} examples:")
    for i, ex in enumerate(examples, 1):
        output = ex['output']
        logger.info(f"  {i}. {output['decision']} (confidence: {output['confidence']})")

    # 4. Get current prompt and next version
    current_prompt = get_current_prompt_text()
    next_version = get_next_version_number()

    logger.info(f"\nNext version: {next_version}")
    logger.info(f"Prompt text length: {len(current_prompt)} chars")
    logger.info(f"Few-shot examples: {len(examples)}")

    # 5. Deploy new version
    if args.dry_run:
        logger.info("\n" + "=" * 70)
        logger.info("DRY RUN - Changes not applied")
        logger.info("=" * 70)
    else:
        logger.info("\nDeploying new prompt version...")
        notes = f"Weekly optimization based on {args.days} days of data. "
        if misclassifications:
            notes += f"Includes {len(misclassifications)} learning examples from misclassifications."

        success = deploy_prompt_version(
            version=next_version,
            prompt_text=current_prompt,
            examples=examples,
            notes=notes,
            dry_run=args.dry_run
        )

        if success:
            logger.info("\n" + "=" * 70)
            logger.info(f"✓ Prompt version {next_version} deployed successfully")
            logger.info("=" * 70)
        else:
            logger.error("\n✗ Failed to deploy prompt version")

    logger.info("\n✓ Prompt optimizer completed")


if __name__ == "__main__":
    main()
