#!/usr/bin/env python3
"""
Import reviewed labels from CSV and update database.
This will:
1. Import the human labels
2. Update the status from 'unknown' to 'verified' (removing from review queue)

Usage:
    python scripts/import_reviewed_labels.py data/companies_for_review_unknown.csv
"""

import sys
import csv
from pathlib import Path
from sqlalchemy import text

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager


def import_reviewed_labels(csv_file: str):
    """Import reviewed labels from CSV and update database."""

    db = DatabaseManager()

    # Read CSV
    labels_to_import = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            company_id = int(row['ID'])

            # Get the label
            label = row.get('Label (provider/non_provider)', '').strip().lower()

            if label in ['provider', 'non_provider']:
                labels_to_import.append((company_id, label))

    print(f"Found {len(labels_to_import)} labels to import")

    if not labels_to_import:
        print("No valid labels found in CSV")
        return

    # Import labels into database
    with db.get_session() as session:
        for company_id, label in labels_to_import:
            # Update the human_label and change status from 'unknown' to 'verified'
            # This removes it from the review queue
            query = text(f"""
                UPDATE companies
                SET parse_metadata =
                    CASE
                        WHEN parse_metadata IS NULL THEN
                            '{{"verification": {{"human_label": "{label}", "status": "verified"}}}}'::jsonb
                        WHEN parse_metadata->'verification' IS NULL THEN
                            parse_metadata || '{{"verification": {{"human_label": "{label}", "status": "verified"}}}}'::jsonb
                        ELSE
                            jsonb_set(
                                jsonb_set(
                                    parse_metadata,
                                    '{{verification,human_label}}',
                                    '"{label}"'::jsonb
                                ),
                                '{{verification,status}}',
                                '"verified"'::jsonb
                            )
                    END
                WHERE id = :company_id
            """)

            session.execute(query, {'company_id': company_id})

        session.commit()

    print(f"✓ Imported {len(labels_to_import)} labels into database")
    print(f"✓ Updated status from 'unknown' to 'verified' (removed from review queue)")

    # Show label distribution
    from collections import Counter
    label_counts = Counter(label for _, label in labels_to_import)
    print("\nLabel distribution:")
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count}")

    # Show updated stats
    with db.get_session() as session:
        # Check remaining unknown
        result = session.execute(text("""
            SELECT COUNT(*)
            FROM companies
            WHERE parse_metadata->'verification'->>'status' = 'unknown'
            AND parse_metadata->'verification'->>'human_label' IS NULL
        """))
        remaining = result.scalar()

        # Check total verified
        result = session.execute(text("""
            SELECT COUNT(*)
            FROM companies
            WHERE parse_metadata->'verification'->>'status' = 'verified'
        """))
        verified = result.scalar()

        # Check total with human labels
        result = session.execute(text("""
            SELECT COUNT(*)
            FROM companies
            WHERE parse_metadata->'verification'->>'human_label' IS NOT NULL
        """))
        total_labeled = result.scalar()

        print(f"\nDatabase stats:")
        print(f"  Remaining in review queue (unknown): {remaining}")
        print(f"  Total verified: {verified}")
        print(f"  Total with human labels: {total_labeled}")

    print("\nNext steps:")
    print("1. Run: ./venv/bin/python scripts/train_verification_classifier.py --binary")
    print("2. Or use the GUI 'Train Classifier' button in the Verification page")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_reviewed_labels.py <csv_file>")
        sys.exit(1)

    csv_file = sys.argv[1]

    if not Path(csv_file).exists():
        print(f"Error: File not found: {csv_file}")
        sys.exit(1)

    import_reviewed_labels(csv_file)
