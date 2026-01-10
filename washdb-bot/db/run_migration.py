#!/usr/bin/env python3
"""
Run database migrations.

Usage:
    python db/run_migration.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from runner.logging_setup import get_logger

# Load environment
load_dotenv()

# Initialize logger
logger = get_logger("run_migration")


def run_migration(migration_file: str):
    """
    Run a single migration SQL file.

    Args:
        migration_file: Path to SQL migration file

    Returns:
        True if successful, False otherwise
    """
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        logger.error("DATABASE_URL not set in environment")
        return False

    # Read migration SQL
    migration_path = Path(migration_file)
    if not migration_path.exists():
        logger.error(f"Migration file not found: {migration_file}")
        return False

    with open(migration_path, 'r') as f:
        sql = f.read()

    # Connect and run migration
    engine = create_engine(database_url, echo=False)

    try:
        with engine.connect() as conn:
            # Execute migration
            logger.info(f"Running migration: {migration_path.name}")
            conn.execute(text(sql))
            conn.commit()

            logger.info(f"Migration completed successfully: {migration_path.name}")
            return True

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


def main():
    """Run all pending migrations."""
    logger.info("=" * 60)
    logger.info("Database Migration Runner")
    logger.info("=" * 60)

    # Get migrations directory
    migrations_dir = Path(__file__).parent / "migrations"

    if not migrations_dir.exists():
        logger.error(f"Migrations directory not found: {migrations_dir}")
        return

    # Get all .sql files sorted by name
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        logger.info("No migration files found")
        return

    logger.info(f"Found {len(migration_files)} migration(s)")
    logger.info("")

    # Run each migration
    success_count = 0
    failed_count = 0

    for migration_file in migration_files:
        if run_migration(migration_file):
            success_count += 1
        else:
            failed_count += 1
            logger.error(f"Stopping due to failed migration: {migration_file.name}")
            break

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Migration Summary")
    logger.info(f"  Successful: {success_count}")
    logger.info(f"  Failed:     {failed_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
