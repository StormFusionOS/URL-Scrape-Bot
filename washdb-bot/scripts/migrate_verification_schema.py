#!/usr/bin/env python3
"""
Migrate verification schema to standardized format.

New Schema:
- active: boolean - website is online/reachable (true/false)
- verified: boolean - company is a legitimate target service provider (true/false)
- verification_type: varchar - how it was verified ('llm', 'claude', 'manual', null)

Migration Logic:
1. Add new columns: verified, verification_type
2. Migrate data:
   - If claude_verified=true AND verification.status='passed' -> verified=true, verification_type='claude'
   - If claude_verified=true AND verification.status='failed' -> verified=false, verification_type='claude'
   - If verification.status='passed' (not claude) -> verified=true, verification_type='llm'
   - If verification.status='failed' (not claude) -> verified=false, verification_type='llm'
3. Reset 'active' to true for all (will be updated by website health checks)
4. Update SEO worker queries to use 'verified' instead of parse_metadata

Usage:
    python scripts/migrate_verification_schema.py [--dry-run]
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import create_session
from sqlalchemy import text


def check_current_state(session):
    """Check current verification data state."""
    print("=" * 70)
    print("CURRENT STATE ANALYSIS")
    print("=" * 70)

    # Count by verification combinations
    result = session.execute(text('''
        SELECT
            claude_verified,
            CASE
                WHEN parse_metadata @> '{"verification": {"status": "passed"}}'::jsonb THEN 'passed'
                WHEN parse_metadata @> '{"verification": {"status": "failed"}}'::jsonb THEN 'failed'
                ELSE 'none'
            END as pm_status,
            active,
            COUNT(*) as count
        FROM companies
        GROUP BY 1, 2, 3
        ORDER BY 4 DESC
    '''))

    print("\nCurrent state (claude_verified, parse_metadata.status, active):")
    total = 0
    for row in result:
        print(f"  claude={row[0]}, pm_status={row[1]}, active={row[2]}: {row[3]:,}")
        total += row[3]
    print(f"\nTotal companies: {total:,}")

    return total


def add_new_columns(session, dry_run=False):
    """Add verified and verification_type columns."""
    print("\n" + "=" * 70)
    print("STEP 1: ADD NEW COLUMNS")
    print("=" * 70)

    # Check if columns exist
    result = session.execute(text('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'companies' AND column_name IN ('verified', 'verification_type')
    '''))
    existing = [row[0] for row in result]

    if 'verified' in existing and 'verification_type' in existing:
        print("Columns already exist, skipping...")
        return

    if dry_run:
        print("[DRY RUN] Would add columns: verified (boolean), verification_type (varchar)")
        return

    # Add columns
    if 'verified' not in existing:
        print("Adding column: verified (boolean, default null)")
        session.execute(text('ALTER TABLE companies ADD COLUMN verified BOOLEAN DEFAULT NULL'))

    if 'verification_type' not in existing:
        print("Adding column: verification_type (varchar, default null)")
        session.execute(text('ALTER TABLE companies ADD COLUMN verification_type VARCHAR(20) DEFAULT NULL'))

    session.commit()
    print("Columns added successfully")


def migrate_verification_data(session, dry_run=False):
    """Migrate existing verification data to new schema."""
    print("\n" + "=" * 70)
    print("STEP 2: MIGRATE VERIFICATION DATA")
    print("=" * 70)

    migrations = [
        # Claude verified + passed -> verified=true, type='claude'
        {
            'name': 'Claude verified + passed',
            'condition': "claude_verified = true AND parse_metadata @> '{\"verification\": {\"status\": \"passed\"}}'::jsonb",
            'verified': True,
            'verification_type': 'claude'
        },
        # Claude verified + failed -> verified=false, type='claude'
        {
            'name': 'Claude verified + failed',
            'condition': "claude_verified = true AND parse_metadata @> '{\"verification\": {\"status\": \"failed\"}}'::jsonb",
            'verified': False,
            'verification_type': 'claude'
        },
        # LLM passed (not claude) -> verified=true, type='llm'
        {
            'name': 'LLM passed (not claude)',
            'condition': "claude_verified = false AND parse_metadata @> '{\"verification\": {\"status\": \"passed\"}}'::jsonb",
            'verified': True,
            'verification_type': 'llm'
        },
        # LLM failed (not claude) -> verified=false, type='llm'
        {
            'name': 'LLM failed (not claude)',
            'condition': "claude_verified = false AND parse_metadata @> '{\"verification\": {\"status\": \"failed\"}}'::jsonb",
            'verified': False,
            'verification_type': 'llm'
        },
    ]

    for migration in migrations:
        # Count affected rows
        result = session.execute(text(f'''
            SELECT COUNT(*) FROM companies WHERE {migration['condition']}
        '''))
        count = result.scalar()

        print(f"\n{migration['name']}: {count:,} companies")
        print(f"  -> verified={migration['verified']}, verification_type='{migration['verification_type']}'")

        if dry_run:
            print(f"  [DRY RUN] Would update {count:,} rows")
            continue

        if count > 0:
            session.execute(text(f'''
                UPDATE companies
                SET verified = :verified, verification_type = :vtype
                WHERE {migration['condition']}
            '''), {'verified': migration['verified'], 'vtype': migration['verification_type']})
            print(f"  Updated {count:,} rows")

    if not dry_run:
        session.commit()


def reset_active_flag(session, dry_run=False):
    """Reset active flag to true (will be updated by health checks)."""
    print("\n" + "=" * 70)
    print("STEP 3: RESET ACTIVE FLAG")
    print("=" * 70)

    # Count currently inactive
    result = session.execute(text('SELECT COUNT(*) FROM companies WHERE active = false'))
    inactive_count = result.scalar()

    print(f"Currently inactive companies: {inactive_count:,}")
    print("Setting all to active=true (website health checks will update later)")

    if dry_run:
        print(f"[DRY RUN] Would set {inactive_count:,} companies to active=true")
        return

    session.execute(text('UPDATE companies SET active = true WHERE active = false'))
    session.commit()
    print(f"Updated {inactive_count:,} companies to active=true")


def create_index(session, dry_run=False):
    """Create index on verified column for SEO queries."""
    print("\n" + "=" * 70)
    print("STEP 4: CREATE INDEX")
    print("=" * 70)

    # Check if index exists
    result = session.execute(text('''
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'companies' AND indexname = 'idx_companies_verified'
    '''))
    if result.fetchone():
        print("Index already exists, skipping...")
        return

    if dry_run:
        print("[DRY RUN] Would create index: idx_companies_verified")
        return

    print("Creating index on verified column...")
    session.execute(text('CREATE INDEX idx_companies_verified ON companies (verified) WHERE verified = true'))
    session.commit()
    print("Index created successfully")


def verify_migration(session):
    """Verify migration results."""
    print("\n" + "=" * 70)
    print("VERIFICATION RESULTS")
    print("=" * 70)

    # Count by new schema
    result = session.execute(text('''
        SELECT
            verified,
            verification_type,
            COUNT(*) as count
        FROM companies
        GROUP BY 1, 2
        ORDER BY 3 DESC
    '''))

    print("\nNew schema distribution (verified, verification_type):")
    for row in result:
        print(f"  verified={row[0]}, type={row[1]}: {row[2]:,}")

    # Count SEO-eligible companies
    result = session.execute(text('''
        SELECT COUNT(*) FROM companies
        WHERE verified = true AND website IS NOT NULL
    '''))
    seo_eligible = result.scalar()
    print(f"\nSEO-eligible companies (verified=true, has website): {seo_eligible:,}")


def main():
    parser = argparse.ArgumentParser(description='Migrate verification schema')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without modifying database')
    args = parser.parse_args()

    print("=" * 70)
    print("VERIFICATION SCHEMA MIGRATION")
    print("=" * 70)
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")

    with create_session() as session:
        # Check current state
        check_current_state(session)

        # Run migration steps
        add_new_columns(session, args.dry_run)
        migrate_verification_data(session, args.dry_run)
        reset_active_flag(session, args.dry_run)
        create_index(session, args.dry_run)

        # Verify results
        if not args.dry_run:
            verify_migration(session)

    print("\n" + "=" * 70)
    print("MIGRATION COMPLETE" if not args.dry_run else "DRY RUN COMPLETE")
    print("=" * 70)

    if not args.dry_run:
        print("\nNext steps:")
        print("1. Update db/models.py to add 'verified' and 'verification_type' columns")
        print("2. Update SEO workers to use 'verified = true' instead of parse_metadata queries")
        print("3. Update verification workers to set 'verified' and 'verification_type'")


if __name__ == '__main__':
    main()
