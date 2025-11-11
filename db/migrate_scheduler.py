#!/usr/bin/env python3
"""
Database migration script to add scheduler tables.

Creates:
- scheduled_jobs table
- job_execution_logs table
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from db.models import Base, ScheduledJob, JobExecutionLog

# Load environment variables
load_dotenv()

def get_database_url():
    """Get database URL from environment."""
    return os.getenv('DATABASE_URL', 'postgresql+psycopg://scraper_user:ScraperPass123@localhost:5432/scraper')

def run_migration():
    """Run the migration to create scheduler tables."""
    database_url = get_database_url()

    print("=" * 70)
    print("Scheduler Tables Migration")
    print("=" * 70)
    print(f"Database URL: {database_url.split('@')[1] if '@' in database_url else database_url}")
    print()

    # Create engine
    engine = create_engine(database_url)

    # Test connection
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✓ Database connection successful")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False

    print()
    print("Creating scheduler tables...")
    print()

    try:
        # Create only the scheduler tables
        ScheduledJob.__table__.create(engine, checkfirst=True)
        print("✓ Created table: scheduled_jobs")

        JobExecutionLog.__table__.create(engine, checkfirst=True)
        print("✓ Created table: job_execution_logs")

        print()
        print("=" * 70)
        print("Migration completed successfully!")
        print("=" * 70)

        # Show table info
        with engine.connect() as conn:
            # Count scheduled_jobs
            result = conn.execute(text("SELECT COUNT(*) FROM scheduled_jobs"))
            job_count = result.scalar()
            print(f"Scheduled jobs: {job_count}")

            # Count job_execution_logs
            result = conn.execute(text("SELECT COUNT(*) FROM job_execution_logs"))
            log_count = result.scalar()
            print(f"Execution logs: {log_count}")

        return True

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
