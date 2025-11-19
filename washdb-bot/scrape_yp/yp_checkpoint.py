#!/usr/bin/env python3
"""
Yellow Pages checkpoint and recovery system.

This module provides checkpoint and recovery functionality for the YP crawler:
- Orphaned target recovery (targets stuck in 'in_progress')
- Progress checkpointing (save/load crawl progress)
- Overall progress reporting

Usage:
    # Recover orphaned targets
    from scrape_yp.yp_checkpoint import recover_orphaned_targets
    count = recover_orphaned_targets(session, timeout_minutes=60)

    # Save progress checkpoint
    from scrape_yp.yp_checkpoint import save_progress_checkpoint
    save_progress_checkpoint('logs/yp_progress.json', stats)

    # Load progress checkpoint
    from scrape_yp.yp_checkpoint import load_progress_checkpoint
    prev_stats = load_progress_checkpoint('logs/yp_progress.json')
"""

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from db.models import YPTarget
from runner.logging_setup import get_logger

logger = get_logger("yp_checkpoint")


def recover_orphaned_targets(
    session,
    timeout_minutes: int = 60,
    state_ids: Optional[list[str]] = None
) -> dict:
    """
    Recover targets that have been stuck in 'IN_PROGRESS' status.

    A target is considered orphaned if:
    - Status is 'IN_PROGRESS'
    - heartbeat_at is older than timeout_minutes (or NULL)

    This heartbeat-based approach ensures we only recover targets from
    crashed/killed workers, not actively running ones.

    These targets are reset to 'PLANNED' status so they can be retried.

    Args:
        session: SQLAlchemy session
        timeout_minutes: Minutes after which a target is considered orphaned (default: 60)
        state_ids: Optional list of state codes to limit recovery (e.g., ['RI', 'CA'])

    Returns:
        Dict with keys:
        - recovered: Number of targets recovered
        - targets: List of recovered target dicts (id, city, state, category, claimed_by, heartbeat_at)
    """
    logger.info(f"Searching for orphaned targets (heartbeat timeout={timeout_minutes} minutes)...")

    # Calculate threshold timestamp
    threshold = datetime.utcnow() - timedelta(minutes=timeout_minutes)

    # Build query - use heartbeat_at for orphan detection
    query = session.query(YPTarget).filter(
        YPTarget.status == 'IN_PROGRESS'
    ).filter(
        # Orphaned if: heartbeat is NULL OR heartbeat is stale
        (YPTarget.heartbeat_at == None) | (YPTarget.heartbeat_at < threshold)
    )

    if state_ids:
        query = query.filter(YPTarget.state_id.in_(state_ids))

    # Find orphaned targets
    orphaned = query.all()

    if not orphaned:
        logger.info("No orphaned targets found")
        return {'recovered': 0, 'targets': []}

    logger.warning(f"Found {len(orphaned)} orphaned targets")

    # Reset targets to 'PLANNED'
    recovered_targets = []
    for target in orphaned:
        old_note = target.note or ""
        old_status = target.status

        # Track recovery details
        recovery_info = f"worker={target.claimed_by or 'unknown'}, heartbeat={target.heartbeat_at or 'never'}"

        target.status = 'PLANNED'
        target.note = f"auto_recovered_from_{old_status}_attempts={target.attempts}_page={target.page_current}/{target.page_target}_{recovery_info} | {old_note}"

        # Clear worker claim (will be re-claimed by new worker)
        target.claimed_by = None
        target.claimed_at = None

        recovered_targets.append({
            'id': target.id,
            'city': target.city,
            'state': target.state_id,
            'category': target.category_label,
            'attempts': target.attempts,
            'page_current': target.page_current,
            'page_target': target.page_target,
            'claimed_by': target.claimed_by,
            'heartbeat_at': target.heartbeat_at.isoformat() if target.heartbeat_at else None,
        })

        logger.info(
            f"  Recovered: {target.city}, {target.state_id} - {target.category_label} "
            f"(attempts={target.attempts}, page={target.page_current}/{target.page_target}, "
            f"claimed_by={target.claimed_by}, heartbeat={target.heartbeat_at})"
        )

    session.commit()

    logger.info(f"Successfully recovered {len(orphaned)} orphaned targets")

    return {
        'recovered': len(orphaned),
        'targets': recovered_targets,
    }


def get_overall_progress(session, state_ids: Optional[list[str]] = None) -> dict:
    """
    Get overall crawl progress statistics.

    Args:
        session: SQLAlchemy session
        state_ids: Optional list of state codes to filter (e.g., ['RI', 'CA'])

    Returns:
        Dict with keys:
        - total: Total number of targets
        - planned: Number of planned targets
        - in_progress: Number of in-progress targets
        - done: Number of completed targets
        - failed: Number of failed targets
        - parked: Number of parked targets
        - progress_pct: Percentage complete (done / total * 100)
    """
    # Base query
    query = session.query(YPTarget)

    if state_ids:
        query = query.filter(YPTarget.state_id.in_(state_ids))

    # Count by status
    total = query.count()
    planned = query.filter(YPTarget.status == 'PLANNED').count()
    in_progress = query.filter(YPTarget.status == 'IN_PROGRESS').count()
    done = query.filter(YPTarget.status == 'DONE').count()
    failed = query.filter(YPTarget.status == 'FAILED').count()
    stuck = query.filter(YPTarget.status == 'STUCK').count()
    parked = query.filter(YPTarget.status == 'PARKED').count()

    # Calculate progress percentage
    progress_pct = (done / total * 100) if total > 0 else 0

    return {
        'total': total,
        'planned': planned,
        'in_progress': in_progress,
        'done': done,
        'failed': failed,
        'stuck': stuck,
        'parked': parked,
        'progress_pct': progress_pct,
    }


def save_progress_checkpoint(checkpoint_file: str, stats: dict, state_ids: Optional[list[str]] = None) -> None:
    """
    Save progress checkpoint to JSON file (atomic write).

    Args:
        checkpoint_file: Path to checkpoint file (e.g., 'logs/yp_progress.json')
        stats: Dict with progress statistics
        state_ids: Optional list of states being crawled
    """
    # Ensure directory exists
    checkpoint_path = Path(checkpoint_file)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare checkpoint data
    checkpoint_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'state_ids': state_ids or [],
        'stats': stats,
    }

    # Atomic write: write to temp file, then rename
    temp_fd, temp_path = tempfile.mkstemp(
        dir=checkpoint_path.parent,
        prefix='.checkpoint_',
        suffix='.tmp'
    )

    try:
        with os.fdopen(temp_fd, 'w') as f:
            json.dump(checkpoint_data, f, indent=2)

        # Atomic rename
        os.rename(temp_path, checkpoint_file)

        logger.debug(f"Saved checkpoint to {checkpoint_file}")

    except Exception as e:
        logger.error(f"Failed to save checkpoint: {e}")
        # Clean up temp file if it still exists
        try:
            os.unlink(temp_path)
        except Exception:
            pass
        raise


def load_progress_checkpoint(checkpoint_file: str) -> Optional[dict]:
    """
    Load progress checkpoint from JSON file.

    Args:
        checkpoint_file: Path to checkpoint file (e.g., 'logs/yp_progress.json')

    Returns:
        Dict with checkpoint data, or None if file doesn't exist
    """
    checkpoint_path = Path(checkpoint_file)

    if not checkpoint_path.exists():
        logger.debug(f"No checkpoint file found at {checkpoint_file}")
        return None

    try:
        with open(checkpoint_file, 'r') as f:
            checkpoint_data = json.load(f)

        logger.info(f"Loaded checkpoint from {checkpoint_file}")
        logger.info(f"  Checkpoint timestamp: {checkpoint_data.get('timestamp')}")
        logger.info(f"  States: {', '.join(checkpoint_data.get('state_ids', [])) or 'ALL'}")

        if 'stats' in checkpoint_data:
            stats = checkpoint_data['stats']
            logger.info(f"  Progress: {stats.get('done', 0)}/{stats.get('total', 0)} targets complete "
                       f"({stats.get('progress_pct', 0):.1f}%)")

        return checkpoint_data

    except Exception as e:
        logger.error(f"Failed to load checkpoint: {e}")
        return None


def reset_failed_targets(session, state_ids: Optional[list[str]] = None, max_attempts: Optional[int] = None) -> dict:
    """
    Reset failed targets to 'PLANNED' status for retry.

    Args:
        session: SQLAlchemy session
        state_ids: Optional list of state codes to limit reset
        max_attempts: Only reset targets with attempts <= max_attempts

    Returns:
        Dict with keys:
        - reset: Number of targets reset
        - targets: List of reset target dicts
    """
    logger.info("Resetting failed targets to 'PLANNED' status...")

    # Build query
    query = session.query(YPTarget).filter(YPTarget.status == 'FAILED')

    if state_ids:
        query = query.filter(YPTarget.state_id.in_(state_ids))

    if max_attempts is not None:
        query = query.filter(YPTarget.attempts <= max_attempts)

    # Find failed targets
    failed_targets = query.all()

    if not failed_targets:
        logger.info("No failed targets found")
        return {'reset': 0, 'targets': []}

    logger.info(f"Found {len(failed_targets)} failed targets to reset")

    # Reset targets
    reset_targets = []
    for target in failed_targets:
        old_note = target.note or ""
        target.status = 'PLANNED'
        target.note = f"reset_from_FAILED_{target.attempts}_attempts | {old_note}"
        target.claimed_by = None  # Clear worker claim
        target.claimed_at = None

        reset_targets.append({
            'id': target.id,
            'city': target.city,
            'state': target.state_id,
            'category': target.category_label,
            'attempts': target.attempts,
        })

    session.commit()

    logger.info(f"Successfully reset {len(failed_targets)} failed targets")

    return {
        'reset': len(failed_targets),
        'targets': reset_targets,
    }


def print_progress_summary(session, state_ids: Optional[list[str]] = None) -> None:
    """
    Print a formatted progress summary to console.

    Args:
        session: SQLAlchemy session
        state_ids: Optional list of state codes to filter
    """
    progress = get_overall_progress(session, state_ids=state_ids)

    print()
    print("=" * 60)
    print("YELLOW PAGES CRAWLER PROGRESS")
    print("=" * 60)
    print(f"States: {', '.join(state_ids) if state_ids else 'ALL'}")
    print()
    print(f"Total targets:        {progress['total']:>6}")
    print(f"Completed (done):     {progress['done']:>6}  ({progress['done']/progress['total']*100:>5.1f}%)" if progress['total'] > 0 else "")
    print(f"In progress:          {progress['in_progress']:>6}")
    print(f"Planned (remaining):  {progress['planned']:>6}")
    print(f"Failed:               {progress['failed']:>6}")
    print(f"Parked:               {progress['parked']:>6}")
    print()
    print(f"Overall progress:     {progress['progress_pct']:.1f}%")
    print("=" * 60)
    print()


if __name__ == "__main__":
    """CLI for checkpoint management."""
    import argparse
    import sys
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    parser = argparse.ArgumentParser(description="Yellow Pages Checkpoint Management")
    parser.add_argument('--recover', action='store_true', help="Recover orphaned targets")
    parser.add_argument('--reset-failed', action='store_true', help="Reset failed targets to planned")
    parser.add_argument('--progress', action='store_true', help="Show progress summary")
    parser.add_argument('--timeout', type=int, default=60, help="Orphan timeout in minutes (default: 60)")
    parser.add_argument('--states', nargs='+', help="Filter by state codes (e.g., RI CA TX)")
    parser.add_argument('--max-attempts', type=int, help="Only reset targets with attempts <= this value")

    args = parser.parse_args()

    # Database connection
    DB_USER = "scraper_user"
    DB_PASSWORD = "ScraperPass123"
    DB_HOST = "localhost"
    DB_NAME = "scraper"

    engine = create_engine(f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        if args.recover:
            result = recover_orphaned_targets(session, timeout_minutes=args.timeout, state_ids=args.states)
            print(f"\nRecovered {result['recovered']} orphaned targets")

        if args.reset_failed:
            result = reset_failed_targets(session, state_ids=args.states, max_attempts=args.max_attempts)
            print(f"\nReset {result['reset']} failed targets")

        if args.progress:
            print_progress_summary(session, state_ids=args.states)

        if not (args.recover or args.reset_failed or args.progress):
            parser.print_help()
            sys.exit(1)

    finally:
        session.close()
