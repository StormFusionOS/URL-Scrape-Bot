#!/usr/bin/env python3
"""
Migration: Add Claude verification tracking fields to companies table.

This migration:
1. Adds claude_verified boolean field
2. Adds claude_verified_at timestamp field
3. Creates index for fast lookups
4. Backfills data from parse_metadata JSONB
5. Shows before/after statistics

Usage:
    python scripts/migrate_add_claude_verification_tracking.py [--dry-run]
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
import argparse

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager


class ClaudeVerificationMigration:
    """Migration to add Claude verification tracking."""

    def __init__(self, dry_run: bool = False):
        self.db = DatabaseManager()
        self.dry_run = dry_run

        if dry_run:
            print("=" * 80)
            print("DRY RUN MODE - No changes will be made")
            print("=" * 80)
            print()

    def show_current_stats(self):
        """Show current verification statistics."""
        print("=" * 80)
        print("Current State (Before Migration)")
        print("=" * 80)

        with self.db.get_session() as session:
            # Check if columns already exist
            result = session.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'companies'
                AND column_name IN ('claude_verified', 'claude_verified_at')
            """))
            existing_cols = [row[0] for row in result]

            if existing_cols:
                print(f"⚠️  WARNING: Columns already exist: {', '.join(existing_cols)}")
                print("This migration may have already been run.")
                return False

            # Count companies with Claude verification in JSONB
            result = session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE parse_metadata->'verification'->'claude_assessment' IS NOT NULL) as has_claude,
                    COUNT(*) FILTER (WHERE parse_metadata->'verification'->>'status' IS NOT NULL) as has_status,
                    COUNT(*) as total
                FROM companies
            """))
            row = result.fetchone()

            print(f"Total companies: {row[2]:,}")
            print(f"Companies with Claude assessment: {row[0]:,}")
            print(f"Companies with verification status: {row[1]:,}")
            print()

            # Show verification status breakdown
            result = session.execute(text("""
                SELECT
                    parse_metadata->'verification'->>'status' as status,
                    COUNT(*) as count
                FROM companies
                WHERE parse_metadata->'verification'->>'status' IS NOT NULL
                GROUP BY parse_metadata->'verification'->>'status'
                ORDER BY count DESC
            """))

            print("Verification Status Breakdown:")
            for row in result:
                print(f"  {row[0]:20s} {row[1]:,}")
            print()

            return True

    def add_columns(self):
        """Add claude_verified and claude_verified_at columns."""
        print("=" * 80)
        print("Step 1: Adding Columns")
        print("=" * 80)

        with self.db.get_session() as session:
            # Add claude_verified column
            print("Adding claude_verified column (BOOLEAN, default FALSE)...")
            if not self.dry_run:
                session.execute(text("""
                    ALTER TABLE companies
                    ADD COLUMN IF NOT EXISTS claude_verified BOOLEAN DEFAULT FALSE
                """))
                session.commit()
            print("✓ claude_verified column added")

            # Add claude_verified_at column
            print("Adding claude_verified_at column (TIMESTAMP)...")
            if not self.dry_run:
                session.execute(text("""
                    ALTER TABLE companies
                    ADD COLUMN IF NOT EXISTS claude_verified_at TIMESTAMP
                """))
                session.commit()
            print("✓ claude_verified_at column added")
            print()

    def create_index(self):
        """Create index for fast lookups."""
        print("=" * 80)
        print("Step 2: Creating Index")
        print("=" * 80)

        print("Creating partial index on claude_verified = FALSE...")
        with self.db.get_session() as session:
            if not self.dry_run:
                # Drop index if exists (for re-running migration)
                session.execute(text("""
                    DROP INDEX IF EXISTS idx_companies_claude_verified
                """))

                # Create partial index for unverified companies
                session.execute(text("""
                    CREATE INDEX idx_companies_claude_verified
                    ON companies(claude_verified)
                    WHERE claude_verified = FALSE
                """))
                session.commit()
            print("✓ Index created: idx_companies_claude_verified")
            print()

    def backfill_data(self):
        """Backfill data from parse_metadata."""
        print("=" * 80)
        print("Step 3: Backfilling Data")
        print("=" * 80)

        with self.db.get_session() as session:
            # Count companies to backfill
            result = session.execute(text("""
                SELECT COUNT(*)
                FROM companies
                WHERE parse_metadata->'verification'->'claude_assessment' IS NOT NULL
            """))
            total_to_backfill = result.fetchone()[0]

            print(f"Companies to backfill: {total_to_backfill:,}")
            print()

            if total_to_backfill == 0:
                print("No companies to backfill.")
                return

            print("Updating companies with Claude verification data...")
            if not self.dry_run:
                # Update claude_verified = TRUE for companies with Claude assessment
                result = session.execute(text("""
                    UPDATE companies
                    SET
                        claude_verified = TRUE,
                        claude_verified_at = COALESCE(
                            (parse_metadata->'verification'->'claude_assessment'->>'claude_verified_at')::timestamp,
                            NOW()
                        )
                    WHERE parse_metadata->'verification'->'claude_assessment' IS NOT NULL
                    AND (claude_verified IS NULL OR claude_verified = FALSE)
                """))
                updated_count = result.rowcount
                session.commit()

                print(f"✓ Updated {updated_count:,} companies")
            else:
                print(f"[DRY RUN] Would update {total_to_backfill:,} companies")
            print()

    def show_final_stats(self):
        """Show final statistics after migration."""
        print("=" * 80)
        print("Final State (After Migration)")
        print("=" * 80)

        with self.db.get_session() as session:
            # Count verified companies
            result = session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE claude_verified = TRUE) as verified,
                    COUNT(*) FILTER (WHERE claude_verified = FALSE) as unverified,
                    COUNT(*) as total
                FROM companies
            """))
            row = result.fetchone()

            print(f"Total companies: {row[2]:,}")
            print(f"Claude verified: {row[0]:,} ({row[0]/row[2]*100:.1f}%)")
            print(f"Not verified: {row[1]:,} ({row[1]/row[2]*100:.1f}%)")
            print()

            # Count active companies needing verification
            result = session.execute(text("""
                SELECT COUNT(*)
                FROM companies
                WHERE active = TRUE
                AND claude_verified = FALSE
            """))
            active_unverified = result.fetchone()[0]

            print(f"Active companies needing verification: {active_unverified:,}")
            print()

            # Check index exists
            result = session.execute(text("""
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'companies'
                AND indexname = 'idx_companies_claude_verified'
            """))
            index_exists = result.fetchone() is not None

            if index_exists:
                print("✓ Index exists: idx_companies_claude_verified")
            else:
                print("⚠️  Index NOT found: idx_companies_claude_verified")
            print()

    def run(self):
        """Run the migration."""
        print()
        print("=" * 80)
        print("Claude Verification Tracking Migration")
        print("=" * 80)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        # Show current state
        can_proceed = self.show_current_stats()

        if not can_proceed:
            print()
            print("=" * 80)
            print("Migration aborted - columns already exist")
            print("=" * 80)
            return False

        # Confirm if not dry run
        if not self.dry_run:
            response = input("\nProceed with migration? (yes/no): ")
            if response.lower() != 'yes':
                print("Migration cancelled.")
                return False

        # Run migration steps
        self.add_columns()
        self.create_index()
        self.backfill_data()

        # Show final stats
        if not self.dry_run:
            self.show_final_stats()

        print()
        print("=" * 80)
        print("Migration Complete!")
        print("=" * 80)
        print(f"Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        if not self.dry_run:
            print("Next steps:")
            print("1. Update verification scripts to set claude_verified = TRUE after verification")
            print("2. Query unverified companies with: WHERE claude_verified = FALSE")
            print("3. Monitor verification progress with: SELECT COUNT(*) FROM companies WHERE claude_verified = TRUE")

        return True


def main():
    parser = argparse.ArgumentParser(description='Add Claude verification tracking to companies table')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()

    migration = ClaudeVerificationMigration(dry_run=args.dry_run)
    success = migration.run()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
