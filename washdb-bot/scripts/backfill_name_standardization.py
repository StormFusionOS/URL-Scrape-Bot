#!/usr/bin/env python3
"""
Backfill Name Standardization

Process existing verified companies to:
1. Parse city/state from address
2. Calculate name quality scores
3. Generate standardized_name via domain inference for poor-quality names

Usage:
    ./venv/bin/python scripts/backfill_name_standardization.py [--batch-size 500] [--limit 1000]
"""

import os
import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scrape_yp.name_standardizer import (
    score_name_quality,
    standardize_name,
    parse_location_from_address,
    needs_standardization,
)


def backfill_companies(batch_size: int = 500, limit: int = None, dry_run: bool = False):
    """
    Backfill name standardization fields for existing companies.

    Args:
        batch_size: Number of companies to process per batch
        limit: Maximum total companies to process (None = all)
        dry_run: If True, don't commit changes
    """
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    engine = create_engine(DATABASE_URL)

    # Get count of companies needing processing
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM companies
            WHERE verified = TRUE
            AND (name_quality_score IS NULL OR name_quality_score = 50)
        """))
        total_count = result.fetchone()[0]

    print(f"Found {total_count:,} verified companies to process")
    if limit:
        print(f"Limited to {limit:,} companies")
        total_count = min(total_count, limit)

    processed = 0
    updated = 0
    standardized = 0
    offset = 0

    while processed < total_count:
        current_batch_size = min(batch_size, total_count - processed)

        with engine.connect() as conn:
            # Fetch batch of companies
            result = conn.execute(text("""
                SELECT id, name, address, domain
                FROM companies
                WHERE verified = TRUE
                AND (name_quality_score IS NULL OR name_quality_score = 50)
                ORDER BY id
                LIMIT :limit OFFSET :offset
            """), {'limit': current_batch_size, 'offset': offset})

            rows = result.fetchall()
            if not rows:
                break

            for row in rows:
                company_id = row[0]
                name = row[1]
                address = row[2]
                domain = row[3]

                # Calculate name quality score
                quality_score = score_name_quality(name) if name else 0
                name_flag = needs_standardization(name) if name else True

                # Parse location from address
                location = parse_location_from_address(address) if address else {}
                city = location.get("city")
                state = location.get("state")
                zip_code = location.get("zip_code")
                loc_source = "address_parse" if (city or state or zip_code) else None

                # Attempt to standardize name if needed
                std_name = None
                std_source = None
                std_confidence = None
                if name_flag and name:
                    std_name, std_source, std_confidence = standardize_name(
                        original_name=name,
                        city=city,
                        state=state,
                        domain=domain
                    )
                    # Only keep if different from original
                    if std_name == name:
                        std_name = None
                        std_source = None
                        std_confidence = None
                    else:
                        standardized += 1

                # Update company
                if not dry_run:
                    conn.execute(text("""
                        UPDATE companies
                        SET name_quality_score = :quality_score,
                            name_length_flag = :name_flag,
                            city = COALESCE(city, :city),
                            state = COALESCE(state, :state),
                            zip_code = COALESCE(zip_code, :zip_code),
                            location_source = COALESCE(location_source, :loc_source),
                            standardized_name = COALESCE(standardized_name, :std_name),
                            standardized_name_source = COALESCE(standardized_name_source, :std_source),
                            standardized_name_confidence = COALESCE(standardized_name_confidence, :std_confidence)
                        WHERE id = :id
                    """), {
                        'id': company_id,
                        'quality_score': quality_score,
                        'name_flag': name_flag,
                        'city': city,
                        'state': state,
                        'zip_code': zip_code,
                        'loc_source': loc_source,
                        'std_name': std_name,
                        'std_source': std_source,
                        'std_confidence': std_confidence,
                    })

                updated += 1
                processed += 1

            if not dry_run:
                conn.commit()

        # Progress update
        pct = (processed / total_count * 100) if total_count > 0 else 0
        print(f"\rProcessed {processed:,}/{total_count:,} ({pct:.1f}%) - "
              f"Updated: {updated:,}, Standardized: {standardized:,}", end="")

        offset += current_batch_size

    print()  # Newline after progress
    print()
    print("=" * 60)
    print("Backfill Complete!")
    print("=" * 60)
    print(f"  Total processed: {processed:,}")
    print(f"  Companies updated: {updated:,}")
    print(f"  Names standardized: {standardized:,}")
    if dry_run:
        print()
        print("  (DRY RUN - no changes committed)")


def show_preview():
    """Show a preview of companies that would be standardized."""
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    engine = create_engine(DATABASE_URL)

    print("=" * 80)
    print("Preview: Companies with poor names that would be standardized")
    print("=" * 80)
    print()

    with engine.connect() as conn:
        # Find companies with short names
        result = conn.execute(text("""
            SELECT id, name, domain, address
            FROM companies
            WHERE verified = TRUE
            AND LENGTH(name) < 10
            AND standardized_name IS NULL
            ORDER BY LENGTH(name), name
            LIMIT 20
        """))
        rows = result.fetchall()

    for row in rows:
        company_id = row[0]
        name = row[1]
        domain = row[2]
        address = row[3]

        # Parse location
        location = parse_location_from_address(address) if address else {}
        city = location.get("city")
        state = location.get("state")

        # Get quality score
        quality = score_name_quality(name)

        # Try to standardize
        std_name, source, conf = standardize_name(
            original_name=name,
            city=city,
            state=state,
            domain=domain
        )

        if std_name != name:
            print(f"ID {company_id}: \"{name}\" (score: {quality})")
            print(f"  Domain: {domain}")
            print(f"  Location: {city}, {state}")
            print(f"  -> \"{std_name}\" (source: {source}, conf: {conf:.2f})")
            print()

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Backfill name standardization fields for existing companies'
    )
    parser.add_argument('--batch-size', '-b', type=int, default=500,
                        help='Number of companies to process per batch (default: 500)')
    parser.add_argument('--limit', '-l', type=int, default=None,
                        help='Maximum total companies to process (default: all)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Preview changes without committing')
    parser.add_argument('--preview', '-p', action='store_true',
                        help='Show preview of companies that would be standardized')
    args = parser.parse_args()

    if args.preview:
        show_preview()
    else:
        backfill_companies(
            batch_size=args.batch_size,
            limit=args.limit,
            dry_run=args.dry_run
        )


if __name__ == '__main__':
    main()
