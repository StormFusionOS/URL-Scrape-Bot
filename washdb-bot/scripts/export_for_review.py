#!/usr/bin/env python3
"""
Export companies that need manual review to CSV.

Usage:
    python scripts/export_for_review.py [output_file] [--limit N]
"""

import sys
import csv
from pathlib import Path
from sqlalchemy import text

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager


def export_for_review(output_file: str = None, limit: int = None, status: str = 'unknown'):
    """Export companies needing review to CSV."""

    if output_file is None:
        output_file = f'data/companies_for_review_{status}.csv'

    db = DatabaseManager()

    # Build query
    query = text(f"""
        SELECT
            id,
            name,
            website,
            source,
            parse_metadata->'verification'->>'status' as current_status,
            parse_metadata->'verification'->>'ml_prediction' as ml_prediction,
            parse_metadata->'verification'->>'ml_confidence' as ml_confidence
        FROM companies
        WHERE parse_metadata->'verification'->>'status' = :status
        AND parse_metadata->'verification'->>'human_label' IS NULL
        ORDER BY id
        {f'LIMIT {limit}' if limit else ''}
    """)

    with db.get_session() as session:
        result = session.execute(query, {'status': status})
        companies = result.fetchall()

    if not companies:
        print(f"No companies with status '{status}' found for review")
        return

    # Write to CSV
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'ID',
            'Company Name',
            'Website',
            'Source',
            'Current Status',
            'ML Prediction',
            'ML Confidence',
            'Label (provider/non_provider)'
        ])

        for company in companies:
            writer.writerow([
                company[0],  # id
                company[1],  # company_name
                company[2],  # website
                company[3],  # source
                company[4],  # current_status
                company[5],  # ml_prediction
                company[6],  # ml_confidence
                ''          # empty label column for manual entry
            ])

    print(f"✓ Exported {len(companies)} companies to {output_path}")
    print(f"\nStatus breakdown:")
    print(f"  Status: {status}")
    print(f"  Total: {len(companies)}")
    print(f"\nNext steps:")
    print(f"1. Review and label the companies in: {output_path}")
    print(f"2. Fill in the 'Label (provider/non_provider)' column with:")
    print(f"   - 'provider' for service providers")
    print(f"   - 'non_provider' for non-providers")
    print(f"3. Run: ./venv/bin/python scripts/import_reviewed_labels.py {output_path}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Export companies for manual review')
    parser.add_argument('output_file', nargs='?', help='Output CSV file path')
    parser.add_argument('--limit', type=int, help='Limit number of companies to export')
    parser.add_argument('--status', default='unknown',
                       help='Status to export (default: unknown)')

    args = parser.parse_args()

    export_for_review(args.output_file, args.limit, args.status)
