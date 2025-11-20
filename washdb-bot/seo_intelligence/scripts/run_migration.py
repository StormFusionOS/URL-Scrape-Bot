#!/usr/bin/env python3
"""
Database migration runner for SEO Intelligence tables.

Applies the 005_add_seo_intelligence_tables.sql migration.

Usage:
    python run_migration.py [--database-url URL]

Or set DATABASE_URL environment variable:
    export DATABASE_URL="postgresql://user:pass@localhost/dbname"
    python run_migration.py
"""
import argparse
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def run_migration(database_url: str, migration_file: str):
    """
    Run SQL migration file.

    Args:
        database_url: PostgreSQL connection URL
        migration_file: Path to .sql file
    """
    try:
        logger.info(f"Connecting to database...")
        engine = create_engine(database_url)

        # Read migration SQL
        logger.info(f"Reading migration file: {migration_file}")
        with open(migration_file, 'r') as f:
            sql = f.read()

        # Execute migration
        logger.info("Executing migration...")
        with engine.connect() as conn:
            # Split by semicolon and execute each statement
            statements = [s.strip() for s in sql.split(';') if s.strip()]

            for i, statement in enumerate(statements, 1):
                try:
                    conn.execute(text(statement))
                    logger.debug(f"Executed statement {i}/{len(statements)}")
                except Exception as e:
                    logger.error(f"Error executing statement {i}: {e}")
                    logger.error(f"Statement: {statement[:100]}...")
                    raise

            conn.commit()

        logger.info("Migration completed successfully!")
        logger.info("\nCreated tables:")
        logger.info("  - search_queries")
        logger.info("  - serp_snapshots")
        logger.info("  - serp_results")
        logger.info("  - competitors")
        logger.info("  - competitor_pages")
        logger.info("  - backlinks")
        logger.info("  - referring_domains")
        logger.info("  - citations")
        logger.info("  - page_audits")
        logger.info("  - audit_issues")
        logger.info("  - task_logs")
        logger.info("  - change_log")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Run SEO Intelligence database migration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--database-url',
        type=str,
        default=None,
        help='Database URL (defaults to DATABASE_URL env var)'
    )

    parser.add_argument(
        '--migration-file',
        type=str,
        default=None,
        help='Path to migration file (defaults to 005_add_seo_intelligence_tables.sql)'
    )

    args = parser.parse_args()

    # Get database URL
    database_url = args.database_url or os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL not provided. Set via --database-url or environment variable.")
        sys.exit(1)

    # Get migration file
    if args.migration_file:
        migration_file = args.migration_file
    else:
        # Default to the SEO intelligence migration
        script_dir = Path(__file__).parent
        migration_file = script_dir.parent.parent / 'db' / 'migrations' / '005_add_seo_intelligence_tables.sql'

    if not Path(migration_file).exists():
        logger.error(f"Migration file not found: {migration_file}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("SEO Intelligence Database Migration")
    logger.info("=" * 60)
    logger.info(f"Database: {database_url.split('@')[-1] if '@' in database_url else 'configured'}")
    logger.info(f"Migration: {Path(migration_file).name}")
    logger.info("=" * 60)

    run_migration(database_url, str(migration_file))


if __name__ == '__main__':
    main()
