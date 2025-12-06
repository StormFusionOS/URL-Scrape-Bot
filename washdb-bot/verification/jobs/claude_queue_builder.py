#!/usr/bin/env python3
"""
Claude Queue Builder - Scheduled Job

Runs nightly (2 AM) to populate claude_review_queue with borderline companies.

Priority scoring:
- 10: Very close to boundary (scores 0.48-0.52)
- 50: Borderline (scores 0.45-0.47 or 0.53-0.55)
- 100: Further from boundary

Only queues companies that:
- Are active
- Have status = 'unknown' (needs_review)
- Have borderline scores (0.45-0.55)
- Have NOT been reviewed by Claude yet
- Are NOT already in queue

Usage:
    python verification/jobs/claude_queue_builder.py [--limit 1000] [--dry-run]
"""

import sys
import os
import logging
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from db.database_manager import DatabaseManager
from verification.config_verifier import (
    CLAUDE_REVIEW_SCORE_MIN,
    CLAUDE_REVIEW_SCORE_MAX
)

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def queue_borderline_companies(limit: int = 1000, dry_run: bool = False) -> dict:
    """
    Query companies with needs_review status and borderline scores.
    Add them to claude_review_queue with priority scoring.

    Args:
        limit: Maximum number of companies to queue
        dry_run: If True, only show what would be queued (no insert)

    Returns:
        Dictionary with stats
    """
    db_manager = DatabaseManager()

    # Build query
    query = """
        WITH candidates AS (
            SELECT
                c.id as company_id,
                c.name,
                c.website,
                (c.parse_metadata->'verification'->>'final_score')::decimal as score,
                -- Priority calculation: closer to 0.50 = higher priority (lower number)
                CASE
                    WHEN ABS((c.parse_metadata->'verification'->>'final_score')::decimal - 0.50) < 0.02
                        THEN 10  -- Very close to boundary (0.48-0.52)
                    WHEN ABS((c.parse_metadata->'verification'->>'final_score')::decimal - 0.50) < 0.04
                        THEN 50  -- Borderline (0.46-0.48 or 0.52-0.54)
                    ELSE 100     -- Further from boundary
                END as priority
            FROM companies c
            WHERE c.active = true
              -- Status is 'unknown' (needs_review)
              AND c.parse_metadata->'verification'->>'status' = 'unknown'
              -- Borderline score
              AND (c.parse_metadata->'verification'->>'final_score')::decimal
                  BETWEEN %(score_min)s AND %(score_max)s
              -- NOT yet reviewed by Claude
              AND (
                  c.parse_metadata->'verification'->'claude_review' IS NULL
                  OR (c.parse_metadata->'verification'->'claude_review'->>'reviewed')::boolean IS NOT TRUE
              )
              -- NOT already in queue (pending or processing)
              AND NOT EXISTS (
                  SELECT 1 FROM claude_review_queue q
                  WHERE q.company_id = c.id
                    AND q.status IN ('pending', 'processing')
              )
            ORDER BY priority ASC, c.id ASC
            LIMIT %(limit)s
        )
        SELECT
            company_id,
            name,
            website,
            score,
            priority
        FROM candidates
    """

    with db_manager.get_session() as session:
        result = session.execute(text(query), {
            'score_min': CLAUDE_REVIEW_SCORE_MIN,
            'score_max': CLAUDE_REVIEW_SCORE_MAX,
            'limit': limit
        })
        candidates = result.fetchall()

    if not candidates:
        logger.info("No borderline companies found to queue")
        return {
            'queued': 0,
            'priority_10': 0,
            'priority_50': 0,
            'priority_100': 0
        }

    logger.info(f"Found {len(candidates)} borderline companies")

    # Count by priority
    priority_counts = {10: 0, 50: 0, 100: 0}
    for candidate in candidates:
        priority = candidate[4]
        priority_counts[priority] = priority_counts.get(priority, 0) + 1

    logger.info(f"Priority breakdown: P10={priority_counts[10]}, P50={priority_counts[50]}, P100={priority_counts[100]}")

    if dry_run:
        logger.info("DRY RUN - Would queue:")
        for i, (company_id, name, website, score, priority) in enumerate(candidates[:10], 1):
            logger.info(f"  {i}. [{priority}] {name} (score: {score:.3f})")
        if len(candidates) > 10:
            logger.info(f"  ... and {len(candidates) - 10} more")

        return {
            'queued': 0,
            'would_queue': len(candidates),
            'priority_10': priority_counts[10],
            'priority_50': priority_counts[50],
            'priority_100': priority_counts[100],
            'dry_run': True
        }

    # Insert into queue
    insert_query = """
        INSERT INTO claude_review_queue (company_id, priority, score)
        VALUES (%(company_id)s, %(priority)s, %(score)s)
        ON CONFLICT (company_id, status)
        WHERE status IN ('pending', 'processing')
        DO NOTHING
    """

    inserted_count = 0
    with db_manager.get_session() as session:
                for company_id, name, website, score, priority in candidates:
            try:
                result = session.execute(text(
                    insert_query,
                    {
                        'company_id': company_id,
                        'priority': priority,
                        'score': float(score))
                    }
                )
                inserted_count += 1
            except Exception as e:
                logger.error(f"Failed to queue company {company_id}: {e}")

        # commit handled by context manager

    logger.info(f"✓ Queued {inserted_count} companies for Claude review")

    return {
        'queued': inserted_count,
        'priority_10': priority_counts[10],
        'priority_50': priority_counts[50],
        'priority_100': priority_counts[100]
    }


def get_queue_stats() -> dict:
    """Get current queue statistics."""
    db_manager = DatabaseManager()

    query = """
        SELECT
            status,
            COUNT(*) as count,
            AVG(priority) as avg_priority
        FROM claude_review_queue
        GROUP BY status
        ORDER BY status
    """

    with db_manager.get_session() as session:
                result = session.execute(text(query))
        rows = result.fetchall()

    stats = {}
    for status, count, avg_priority in rows:
        stats[status] = {
            'count': count,
            'avg_priority': round(float(avg_priority), 1) if avg_priority else 0
        }

    return stats


def cleanup_old_completed() -> int:
    """
    Clean up old completed queue entries (older than 7 days).

    Returns:
        Number of rows deleted
    """
    db_manager = DatabaseManager()

    delete_query = """
        DELETE FROM claude_review_queue
        WHERE status = 'completed'
          AND processed_at < NOW() - INTERVAL '7 days'
    """

    with db_manager.get_session() as session:
                result = session.execute(text(delete_query))
        deleted_count = result.rowcount
        # commit handled by context manager

    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old completed queue entries")

    return deleted_count


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Queue borderline companies for Claude review')
    parser.add_argument('--limit', type=int, default=1000, help='Max companies to queue')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be queued without inserting')
    parser.add_argument('--cleanup', action='store_true', help='Clean up old completed entries')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("CLAUDE QUEUE BUILDER")
    logger.info("=" * 70)

    # Show current queue stats
    logger.info("\nCurrent queue state:")
    stats = get_queue_stats()
    if stats:
        for status, data in stats.items():
            logger.info(f"  {status}: {data['count']} (avg priority: {data['avg_priority']})")
    else:
        logger.info("  Queue is empty")

    # Cleanup old entries
    if args.cleanup:
        logger.info("\nCleaning up old completed entries...")
        deleted = cleanup_old_completed()

    # Queue new companies
    logger.info(f"\nQueuing borderline companies (limit: {args.limit})...")
    result = queue_borderline_companies(limit=args.limit, dry_run=args.dry_run)

    logger.info("\n" + "=" * 70)
    logger.info("RESULTS")
    logger.info("=" * 70)
    for key, value in result.items():
        logger.info(f"  {key}: {value}")

    # Show updated queue stats
    if not args.dry_run:
        logger.info("\nUpdated queue state:")
        stats = get_queue_stats()
        for status, data in stats.items():
            logger.info(f"  {status}: {data['count']} (avg priority: {data['avg_priority']})")

    logger.info("\n✓ Queue builder completed")


if __name__ == "__main__":
    main()
