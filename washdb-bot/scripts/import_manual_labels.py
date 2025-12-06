#!/usr/bin/env python3
"""
Import manual labels from CSV and update database.

Usage:
    python scripts/import_manual_labels.py data/companies_labeled.csv
"""

import sys
import csv
from pathlib import Path
from sqlalchemy import text

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager


def import_labels(csv_file: str):
    """Import labels from CSV and update database."""

    db = DatabaseManager()

    # Read CSV
    labels_to_import = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            company_id = int(row['ID'])

            # Try both column names (with and without parenthetical)
            label = row.get('Label (provider/non_provider)', '').strip().lower()
            if not label:
                label = row.get('Label', '').strip().lower()

            if label in ['provider', 'non_provider', 'directory', 'agency', 'blog', 'franchise']:
                labels_to_import.append((company_id, label))

    print(f"Found {len(labels_to_import)} labels to import")

    if not labels_to_import:
        print("No valid labels found in CSV")
        return

    # Import labels into database
    with db.get_session() as session:
        for company_id, label in labels_to_import:
            # Update the human_label in parse_metadata
            # Handle cases where parse_metadata or verification doesn't exist yet
            query = text(f"""
                UPDATE companies
                SET parse_metadata =
                    CASE
                        WHEN parse_metadata IS NULL THEN
                            '{{"verification": {{"human_label": "{label}"}}}}'::jsonb
                        WHEN parse_metadata->'verification' IS NULL THEN
                            parse_metadata || '{{"verification": {{"human_label": "{label}"}}}}'::jsonb
                        ELSE
                            jsonb_set(
                                parse_metadata,
                                '{{verification,human_label}}',
                                '"{label}"'::jsonb
                            )
                    END
                WHERE id = :company_id
            """)

            session.execute(query, {'company_id': company_id})

        session.commit()

    print(f"✓ Imported {len(labels_to_import)} labels into database")

    # Show label distribution
    from collections import Counter
    label_counts = Counter(label for _, label in labels_to_import)
    print("\nLabel distribution:")
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count}")

    print("\nNext steps:")
    print("1. Run: ./venv/bin/python scripts/train_verification_classifier.py --binary")
    print("2. Or use the GUI 'Train Classifier' button in the Verification page")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_manual_labels.py <csv_file>")
        sys.exit(1)

    csv_file = sys.argv[1]

    if not Path(csv_file).exists():
        print(f"Error: File not found: {csv_file}")
        sys.exit(1)

    import_labels(csv_file)
