#!/usr/bin/env python3
"""
Reset Verification Status
==========================
Sets all companies to active=false so they need re-verification.

Usage: python reset_verification.py [--dry-run]
"""

import sys
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

def main():
    dry_run = '--dry-run' in sys.argv

    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL not found in .env")
        return 1

    engine = create_engine(db_url)

    print("=" * 70)
    print("RESET VERIFICATION STATUS")
    print("=" * 70)
    print(f"Database: {db_url.split('@')[1] if '@' in db_url else 'washbot_db'}")
    print(f"Timestamp: {datetime.now()}")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will modify data)'}")
    print("=" * 70)
    print()

    with engine.connect() as conn:
        # Get current status
        result = conn.execute(text('''
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN active = true THEN 1 END) as currently_active,
                COUNT(CASE WHEN active = false THEN 1 END) as currently_inactive
            FROM companies
        '''))

        row = result.fetchone()
        total = row[0]
        active = row[1]
        inactive = row[2]

        print("CURRENT STATUS:")
        print(f"  Total companies: {total:,}")
        print(f"  Currently verified (active=true): {active:,}")
        print(f"  Currently need verification (active=false): {inactive:,}")
        print()

        if not dry_run:
            # Perform the reset
            print("RESETTING ALL COMPANIES...")
            result = conn.execute(text('''
                UPDATE companies
                SET active = false
                WHERE active = true
            '''))
            conn.commit()

            affected = result.rowcount
            print(f"  ✓ Updated {affected:,} companies to active=false")
            print()

            # Verify the change
            result = conn.execute(text('''
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN active = true THEN 1 END) as now_active,
                    COUNT(CASE WHEN active = false THEN 1 END) as now_inactive
                FROM companies
            '''))

            row = result.fetchone()
            print("NEW STATUS:")
            print(f"  Total companies: {row[0]:,}")
            print(f"  Verified (active=true): {row[1]:,}")
            print(f"  Need verification (active=false): {row[2]:,}")
            print()
            print("=" * 70)
            print("✓ RESET COMPLETE")
            print("=" * 70)
        else:
            print(f"DRY RUN: Would update {active:,} companies to active=false")
            print()
            print("To actually perform the reset, run:")
            print("  python reset_verification.py")
            print("=" * 70)

    return 0

if __name__ == '__main__':
    sys.exit(main())
