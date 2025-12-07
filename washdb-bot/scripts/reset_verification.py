#!/usr/bin/env python3
"""
Reset verification data while preserving human labels.

This script will:
1. Back up all verification data to a JSON file
2. Clear all verification results (status, scores, etc.)
3. Preserve human_label field for training

Usage:
    python scripts/reset_verification.py [--backup-file backup.json] [--confirm]
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from sqlalchemy import text

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager


def backup_verification_data(db: DatabaseManager, backup_file: str):
    """Backup all verification data to JSON file."""

    with db.get_session() as session:
        result = session.execute(text("""
            SELECT
                id,
                name,
                website,
                parse_metadata->'verification' as verification
            FROM companies
            WHERE parse_metadata->'verification' IS NOT NULL
        """))

        companies = result.fetchall()

        backup_data = []
        for company in companies:
            backup_data.append({
                'id': company[0],
                'name': company[1],
                'website': company[2],
                'verification': company[3]
            })

    # Save to file
    backup_path = Path(backup_file)
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, indent=2, default=str)

    print(f"✓ Backed up {len(backup_data)} verification records to: {backup_path}")
    return len(backup_data)


def reset_verification(db: DatabaseManager, preserve_labels: bool = True):
    """Reset verification data while optionally preserving human labels."""

    with db.get_session() as session:
        # Get stats before reset
        result = session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN parse_metadata->'verification'->>'human_label' IS NOT NULL THEN 1 END) as with_labels
            FROM companies
            WHERE parse_metadata->'verification' IS NOT NULL
        """))
        stats = result.fetchone()

        print(f"\nCurrent stats:")
        print(f"  Total verified: {stats[0]}")
        print(f"  With human labels: {stats[1]}")

        if preserve_labels:
            # Clear verification data but keep human_label
            query = text("""
                UPDATE companies
                SET parse_metadata =
                    CASE
                        WHEN parse_metadata->'verification'->>'human_label' IS NOT NULL THEN
                            -- Keep only the verification object with human_label
                            jsonb_set(
                                parse_metadata - 'verification',
                                '{verification}',
                                jsonb_build_object('human_label', parse_metadata->'verification'->>'human_label')
                            )
                        ELSE
                            -- Remove verification entirely
                            parse_metadata - 'verification'
                    END
                WHERE parse_metadata->'verification' IS NOT NULL
            """)

            result = session.execute(query)
            session.commit()

            print(f"\n✓ Reset verification data for {result.rowcount} companies")
            print(f"✓ Preserved {stats[1]} human labels")
        else:
            # Clear all verification data including labels
            query = text("""
                UPDATE companies
                SET parse_metadata = parse_metadata - 'verification'
                WHERE parse_metadata->'verification' IS NOT NULL
            """)

            result = session.execute(query)
            session.commit()

            print(f"\n✓ Cleared all verification data for {result.rowcount} companies")

        # Show stats after reset
        result = session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN parse_metadata->'verification'->>'human_label' IS NOT NULL THEN 1 END) as with_labels
            FROM companies
            WHERE parse_metadata->'verification' IS NOT NULL
        """))
        stats_after = result.fetchone()

        print(f"\nAfter reset:")
        print(f"  With verification data: {stats_after[0]}")
        print(f"  With human labels: {stats_after[1]}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Reset verification data')
    parser.add_argument('--backup-file',
                       default=f'data/backups/verification_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json',
                       help='Backup file path')
    parser.add_argument('--confirm', action='store_true',
                       help='Confirm reset without prompting')
    parser.add_argument('--no-preserve-labels', action='store_true',
                       help='Also clear human labels (NOT RECOMMENDED)')

    args = parser.parse_args()

    db = DatabaseManager()

    # Backup first
    print("=" * 70)
    print("STEP 1: Backing up verification data")
    print("=" * 70)
    backup_count = backup_verification_data(db, args.backup_file)

    # Confirm reset
    print("\n" + "=" * 70)
    print("STEP 2: Reset verification data")
    print("=" * 70)

    if not args.confirm:
        print("\nThis will reset all verification results.")
        if args.no_preserve_labels:
            print("WARNING: This will also DELETE all human labels!")
        else:
            print("Human labels will be PRESERVED for training.")

        response = input("\nAre you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)

    # Reset
    reset_verification(db, preserve_labels=not args.no_preserve_labels)

    print("\n" + "=" * 70)
    print("RESET COMPLETE")
    print("=" * 70)
    print(f"\nBackup saved to: {args.backup_file}")
    print("\nNext steps:")
    print("1. Restart verification workers")
    print("2. Monitor verification progress")
    print("3. Label more companies for training")
    print("4. Train ML model with improved dataset")
