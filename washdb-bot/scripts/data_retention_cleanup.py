#!/usr/bin/env python3
"""
Data Retention & Cleanup Script

Manages storage by:
1. Removing old raw_html from serp_snapshots (keep 90 days)
2. Archiving old competitor_pages main_text (keep 90 days of full text)
3. Cleaning up orphaned task_logs (keep 30 days)
4. Vacuuming tables after cleanup

Run via cron or systemd timer:
  0 3 * * * /path/to/venv/bin/python /path/to/scripts/data_retention_cleanup.py

Author: WashDB Bot
"""

import os
import sys
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("data_retention")

# Load environment
load_dotenv()


class DataRetentionManager:
    """Manages data retention policies for WashDB tables."""

    def __init__(self, database_url: str = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set")

        self.engine = create_engine(self.database_url, echo=False)

        # Retention periods (days)
        self.retention_config = {
            "serp_raw_html": 90,          # Keep raw HTML for 90 days
            "competitor_main_text": 90,    # Keep full main_text for 90 days
            "task_logs": 30,               # Keep task logs for 30 days
            "change_log": 180,             # Keep change log for 6 months
        }

    def cleanup_serp_raw_html(self, dry_run: bool = False) -> dict:
        """
        Remove raw_html from old serp_snapshots to save storage.

        The raw HTML is only needed for re-parsing. After 90 days,
        we keep the parsed data but remove the raw HTML.
        """
        cutoff_days = self.retention_config["serp_raw_html"]
        cutoff_date = datetime.now() - timedelta(days=cutoff_days)

        with self.engine.connect() as conn:
            # Count affected rows
            count_result = conn.execute(text("""
                SELECT COUNT(*) FROM serp_snapshots
                WHERE captured_at < :cutoff
                AND raw_html IS NOT NULL
                AND LENGTH(raw_html) > 0
            """), {"cutoff": cutoff_date})
            affected_count = count_result.scalar()

            # Estimate storage savings (avg raw_html is ~200KB)
            estimated_savings_mb = (affected_count * 200) / 1024

            if dry_run:
                logger.info(f"[DRY RUN] Would clear raw_html from {affected_count} serp_snapshots "
                           f"(~{estimated_savings_mb:.1f} MB savings)")
                return {"affected": affected_count, "savings_mb": estimated_savings_mb, "dry_run": True}

            # Clear raw_html but keep the row
            conn.execute(text("""
                UPDATE serp_snapshots
                SET raw_html = NULL
                WHERE captured_at < :cutoff
                AND raw_html IS NOT NULL
            """), {"cutoff": cutoff_date})
            conn.commit()

            logger.info(f"Cleared raw_html from {affected_count} serp_snapshots "
                       f"(~{estimated_savings_mb:.1f} MB savings)")

            return {"affected": affected_count, "savings_mb": estimated_savings_mb, "dry_run": False}

    def cleanup_competitor_main_text(self, dry_run: bool = False) -> dict:
        """
        Truncate main_text in old competitor_pages.

        Keep a summary (first 1000 chars) for context, but remove
        the full text after 90 days to save storage.
        """
        cutoff_days = self.retention_config["competitor_main_text"]
        cutoff_date = datetime.now() - timedelta(days=cutoff_days)

        with self.engine.connect() as conn:
            # Count affected rows
            count_result = conn.execute(text("""
                SELECT COUNT(*) FROM competitor_pages
                WHERE crawled_at < :cutoff
                AND main_text IS NOT NULL
                AND LENGTH(main_text) > 1000
            """), {"cutoff": cutoff_date})
            affected_count = count_result.scalar()

            if dry_run:
                logger.info(f"[DRY RUN] Would truncate main_text in {affected_count} competitor_pages")
                return {"affected": affected_count, "dry_run": True}

            # Truncate to first 1000 chars + note
            conn.execute(text("""
                UPDATE competitor_pages
                SET main_text = LEFT(main_text, 1000) || '... [truncated by retention policy]'
                WHERE crawled_at < :cutoff
                AND main_text IS NOT NULL
                AND LENGTH(main_text) > 1000
            """), {"cutoff": cutoff_date})
            conn.commit()

            logger.info(f"Truncated main_text in {affected_count} competitor_pages")

            return {"affected": affected_count, "dry_run": False}

    def cleanup_task_logs(self, dry_run: bool = False) -> dict:
        """
        Delete old task_logs entries.
        """
        cutoff_days = self.retention_config["task_logs"]
        cutoff_date = datetime.now() - timedelta(days=cutoff_days)

        with self.engine.connect() as conn:
            # Check if table exists
            table_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'task_logs'
                )
            """)).scalar()

            if not table_exists:
                logger.info("task_logs table does not exist, skipping")
                return {"affected": 0, "dry_run": dry_run, "skipped": True}

            # Count affected rows
            count_result = conn.execute(text("""
                SELECT COUNT(*) FROM task_logs
                WHERE started_at < :cutoff
            """), {"cutoff": cutoff_date})
            affected_count = count_result.scalar()

            if dry_run:
                logger.info(f"[DRY RUN] Would delete {affected_count} old task_logs")
                return {"affected": affected_count, "dry_run": True}

            # Delete old logs
            conn.execute(text("""
                DELETE FROM task_logs
                WHERE started_at < :cutoff
            """), {"cutoff": cutoff_date})
            conn.commit()

            logger.info(f"Deleted {affected_count} old task_logs")

            return {"affected": affected_count, "dry_run": False}

    def cleanup_change_log(self, dry_run: bool = False) -> dict:
        """
        Delete old change_log entries (keep 6 months).
        """
        cutoff_days = self.retention_config["change_log"]
        cutoff_date = datetime.now() - timedelta(days=cutoff_days)

        with self.engine.connect() as conn:
            # Check if table exists
            table_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'change_log'
                )
            """)).scalar()

            if not table_exists:
                logger.info("change_log table does not exist, skipping")
                return {"affected": 0, "dry_run": dry_run, "skipped": True}

            # Count affected rows
            count_result = conn.execute(text("""
                SELECT COUNT(*) FROM change_log
                WHERE proposed_at < :cutoff
            """), {"cutoff": cutoff_date})
            affected_count = count_result.scalar()

            if dry_run:
                logger.info(f"[DRY RUN] Would delete {affected_count} old change_log entries")
                return {"affected": affected_count, "dry_run": True}

            # Delete old logs
            conn.execute(text("""
                DELETE FROM change_log
                WHERE proposed_at < :cutoff
            """), {"cutoff": cutoff_date})
            conn.commit()

            logger.info(f"Deleted {affected_count} old change_log entries")

            return {"affected": affected_count, "dry_run": False}

    def vacuum_tables(self) -> None:
        """
        Run VACUUM ANALYZE on affected tables to reclaim space.

        Note: VACUUM cannot run inside a transaction, so we use a direct
        psycopg3 connection instead of SQLAlchemy's connection pool.
        """
        import psycopg
        import re

        tables = ["serp_snapshots", "competitor_pages", "task_logs", "change_log"]

        # Convert SQLAlchemy URL to psycopg3 format
        # postgresql+psycopg://user:pass@host:port/db -> postgresql://user:pass@host:port/db
        db_url = re.sub(r'^postgresql\+\w+://', 'postgresql://', self.database_url)

        try:
            # Use psycopg3 directly with autocommit
            with psycopg.connect(db_url, autocommit=True) as conn:
                with conn.cursor() as cursor:
                    for table in tables:
                        try:
                            cursor.execute(f"VACUUM ANALYZE {table}")
                            logger.info(f"VACUUM ANALYZE completed for {table}")
                        except Exception as e:
                            logger.warning(f"VACUUM failed for {table}: {e}")
        except Exception as e:
            logger.warning(f"Could not run VACUUM (non-critical): {e}")

    def get_table_sizes(self) -> dict:
        """Get current sizes of key tables."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    relname as table_name,
                    pg_size_pretty(pg_total_relation_size(relid)) as total_size,
                    pg_total_relation_size(relid) as size_bytes
                FROM pg_catalog.pg_statio_user_tables
                WHERE relname IN ('serp_snapshots', 'competitor_pages', 'task_logs', 'change_log', 'companies')
                ORDER BY pg_total_relation_size(relid) DESC
            """))

            sizes = {}
            for row in result:
                sizes[row[0]] = {"pretty": row[1], "bytes": row[2]}

            return sizes

    def run_all(self, dry_run: bool = False, vacuum: bool = True) -> dict:
        """
        Run all cleanup tasks.

        Args:
            dry_run: If True, only report what would be done
            vacuum: If True, run VACUUM after cleanup

        Returns:
            Summary of all operations
        """
        logger.info(f"Starting data retention cleanup (dry_run={dry_run})")

        # Get sizes before
        sizes_before = self.get_table_sizes()
        logger.info(f"Table sizes before: {sizes_before}")

        results = {
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
            "serp_raw_html": self.cleanup_serp_raw_html(dry_run),
            "competitor_main_text": self.cleanup_competitor_main_text(dry_run),
            "task_logs": self.cleanup_task_logs(dry_run),
            "change_log": self.cleanup_change_log(dry_run),
        }

        if not dry_run and vacuum:
            logger.info("Running VACUUM ANALYZE...")
            self.vacuum_tables()

        # Get sizes after
        if not dry_run:
            sizes_after = self.get_table_sizes()
            logger.info(f"Table sizes after: {sizes_after}")
            results["sizes_before"] = sizes_before
            results["sizes_after"] = sizes_after

        logger.info(f"Data retention cleanup complete: {results}")
        return results


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="WashDB Data Retention Cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--no-vacuum", action="store_true", help="Skip VACUUM after cleanup")
    parser.add_argument("--sizes-only", action="store_true", help="Only show table sizes")

    args = parser.parse_args()

    try:
        manager = DataRetentionManager()

        if args.sizes_only:
            sizes = manager.get_table_sizes()
            print("\nTable Sizes:")
            for table, info in sizes.items():
                print(f"  {table}: {info['pretty']}")
            return

        results = manager.run_all(
            dry_run=args.dry_run,
            vacuum=not args.no_vacuum
        )

        print(f"\nCleanup {'simulation' if args.dry_run else 'complete'}:")
        print(f"  SERP raw_html cleared: {results['serp_raw_html']['affected']} rows")
        print(f"  Competitor main_text truncated: {results['competitor_main_text']['affected']} rows")
        print(f"  Task logs deleted: {results['task_logs']['affected']} rows")
        print(f"  Change log deleted: {results['change_log']['affected']} rows")

    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
