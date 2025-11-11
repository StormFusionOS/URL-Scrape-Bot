#!/usr/bin/env python3
"""
Database migration script to add HomeAdvisor columns.

Creates:
- rating_ha column (Float)
- reviews_ha column (Integer)
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_database_url():
    """Get database URL from environment."""
    return os.getenv('DATABASE_URL', 'postgresql+psycopg://scraper_user:ScraperPass123@localhost:5432/scraper')


def run_migration():
    """Run the migration to add HomeAdvisor columns."""
    database_url = get_database_url()

    print("=" * 70)
    print("HomeAdvisor Columns Migration")
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
    print("Adding HomeAdvisor columns to companies table...")
    print()

    try:
        # Add HomeAdvisor rating columns
        with engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE companies
                ADD COLUMN IF NOT EXISTS rating_ha DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS reviews_ha INTEGER
            """))

        print("✓ Added column: rating_ha (DOUBLE PRECISION)")
        print("✓ Added column: reviews_ha (INTEGER)")

        print()
        print("=" * 70)
        print("Migration completed successfully!")
        print("=" * 70)

        # Show table info
        with engine.connect() as conn:
            # Check if columns exist
            result = conn.execute(text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'companies'
                AND column_name IN ('rating_ha', 'reviews_ha')
                ORDER BY column_name
            """))
            print()
            print("New columns in companies table:")
            for row in result:
                print(f"  - {row[0]}: {row[1]}")

        return True

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
