#!/usr/bin/env python3
"""
HomeAdvisor Pipeline Statistics and Monitoring

Provides real-time monitoring and statistics for the two-phase pipeline:
- Phase 1 (Discovery): Staging table population
- Phase 2 (URL Finder): Processing and company table updates

Usage:
    # Show current stats
    python scrape_ha/pipeline_stats.py

    # Watch stats in real-time (refreshes every 10 seconds)
    python scrape_ha/pipeline_stats.py --watch

    # Show detailed breakdown
    python scrape_ha/pipeline_stats.py --detailed
"""
import argparse
import time
from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import select, func, and_

from db.models import Company, HAStaging
from db.save_discoveries import create_session
from runner.logging_setup import get_logger

logger = get_logger("pipeline_stats")


def get_staging_stats() -> Dict:
    """
    Get detailed statistics about the staging table.

    Returns:
        Dict with staging table metrics
    """
    session = create_session()

    try:
        now = datetime.now()

        # Total records
        total = session.query(func.count(HAStaging.id)).scalar() or 0

        # Pending (ready to process now)
        pending = session.query(func.count(HAStaging.id)).filter(
            and_(
                HAStaging.processed == False,
                HAStaging.retry_count < 3,
                (HAStaging.next_retry_at.is_(None) | (HAStaging.next_retry_at <= now))
            )
        ).scalar() or 0

        # Waiting for retry (in future)
        waiting_retry = session.query(func.count(HAStaging.id)).filter(
            and_(
                HAStaging.processed == False,
                HAStaging.retry_count > 0,
                HAStaging.retry_count < 3,
                HAStaging.next_retry_at > now
            )
        ).scalar() or 0

        # Failed (max retries reached)
        failed = session.query(func.count(HAStaging.id)).filter(
            HAStaging.retry_count >= 3
        ).scalar() or 0

        # Retry count breakdown
        retry_0 = session.query(func.count(HAStaging.id)).filter(
            HAStaging.retry_count == 0,
            HAStaging.processed == False
        ).scalar() or 0

        retry_1 = session.query(func.count(HAStaging.id)).filter(
            HAStaging.retry_count == 1
        ).scalar() or 0

        retry_2 = session.query(func.count(HAStaging.id)).filter(
            HAStaging.retry_count == 2
        ).scalar() or 0

        # Recent additions (last hour)
        one_hour_ago = now - timedelta(hours=1)
        recent = session.query(func.count(HAStaging.id)).filter(
            HAStaging.created_at >= one_hour_ago
        ).scalar() or 0

        return {
            "total": total,
            "pending": pending,
            "waiting_retry": waiting_retry,
            "failed": failed,
            "retry_0": retry_0,
            "retry_1": retry_1,
            "retry_2": retry_2,
            "recent_1h": recent,
        }

    finally:
        session.close()


def get_companies_stats() -> Dict:
    """
    Get statistics about the companies table (main production table).

    Returns:
        Dict with companies table metrics
    """
    session = create_session()

    try:
        # Total companies
        total = session.query(func.count(Company.id)).scalar() or 0

        # Active companies
        active = session.query(func.count(Company.id)).filter(
            Company.active == True
        ).scalar() or 0

        # HomeAdvisor sourced companies
        ha_companies = session.query(func.count(Company.id)).filter(
            Company.source == "HA"
        ).scalar() or 0

        # Companies with HA ratings
        ha_rated = session.query(func.count(Company.id)).filter(
            Company.rating_ha.isnot(None)
        ).scalar() or 0

        # Recent additions (last hour)
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent = session.query(func.count(Company.id)).filter(
            Company.created_at >= one_hour_ago
        ).scalar() or 0

        # Recent from HA (last hour)
        recent_ha = session.query(func.count(Company.id)).filter(
            Company.created_at >= one_hour_ago,
            Company.source == "HA"
        ).scalar() or 0

        return {
            "total": total,
            "active": active,
            "ha_companies": ha_companies,
            "ha_rated": ha_rated,
            "recent_1h": recent,
            "recent_ha_1h": recent_ha,
        }

    finally:
        session.close()


def print_stats(detailed: bool = False):
    """
    Print pipeline statistics to console.

    Args:
        detailed: If True, show detailed breakdown
    """
    print("=" * 70)
    print(f"HomeAdvisor Pipeline Statistics - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    # Staging table stats
    staging = get_staging_stats()

    print("STAGING TABLE (Phase 1 → Phase 2 Queue)")
    print("-" * 70)
    print(f"  Total Records:        {staging['total']:,}")
    print(f"  Ready to Process:     {staging['pending']:,}  (can process now)")
    print(f"  Waiting for Retry:    {staging['waiting_retry']:,}  (scheduled for later)")
    print(f"  Failed (max retries): {staging['failed']:,}  (gave up)")
    print(f"  Added (last hour):    {staging['recent_1h']:,}")

    if detailed:
        print()
        print("  Retry Breakdown:")
        print(f"    0 retries (new):    {staging['retry_0']:,}")
        print(f"    1 retry:            {staging['retry_1']:,}")
        print(f"    2 retries:          {staging['retry_2']:,}")
        print(f"    3+ retries (fail):  {staging['failed']:,}")

    print()

    # Companies table stats
    companies = get_companies_stats()

    print("COMPANIES TABLE (Production)")
    print("-" * 70)
    print(f"  Total Companies:      {companies['total']:,}")
    print(f"  Active Companies:     {companies['active']:,}")
    print(f"  From HomeAdvisor:     {companies['ha_companies']:,}")
    print(f"  With HA Ratings:      {companies['ha_rated']:,}")
    print(f"  Added (last hour):    {companies['recent_1h']:,}")
    print(f"  From HA (last hour):  {companies['recent_ha_1h']:,}")

    print()

    # Pipeline health
    print("PIPELINE HEALTH")
    print("-" * 70)

    if staging['pending'] == 0 and staging['total'] == 0:
        health = "IDLE - No businesses in queue"
    elif staging['pending'] >= 10:
        health = "ACTIVE - Phase 2 is processing"
    elif staging['pending'] > 0:
        health = f"WAITING - Need {10 - staging['pending']} more to start Phase 2"
    else:
        health = "WAITING - All items in retry queue"

    print(f"  Status: {health}")

    # Calculate success rate
    if staging['total'] > 0:
        processed = staging['total'] - staging['pending'] - staging['waiting_retry']
        if processed > 0:
            success_rate = ((processed - staging['failed']) / processed) * 100
            print(f"  Success Rate: {success_rate:.1f}%  ({processed - staging['failed']}/{processed} succeeded)")

    print()
    print("=" * 70)


def watch_stats(interval: int = 10, detailed: bool = False):
    """
    Watch stats in real-time, refreshing periodically.

    Args:
        interval: Refresh interval in seconds
        detailed: If True, show detailed breakdown
    """
    import os

    try:
        while True:
            # Clear screen (cross-platform)
            os.system('clear' if os.name == 'posix' else 'cls')

            # Print stats
            print_stats(detailed=detailed)

            print(f"Refreshing every {interval} seconds... (Press Ctrl+C to stop)")
            print()

            # Wait for next refresh
            time.sleep(interval)

    except KeyboardInterrupt:
        print()
        print("Stopped watching.")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="HomeAdvisor Pipeline Statistics and Monitoring"
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch stats in real-time (refreshes every 10 seconds)"
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Refresh interval for --watch mode (default: 10 seconds)"
    )

    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed breakdown"
    )

    args = parser.parse_args()

    try:
        if args.watch:
            watch_stats(interval=args.interval, detailed=args.detailed)
        else:
            print_stats(detailed=args.detailed)

    except Exception as e:
        logger.error(f"Stats failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
