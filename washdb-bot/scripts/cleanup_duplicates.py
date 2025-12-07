#!/usr/bin/env python3
"""
Post-processing cleanup job for Yellow Pages data.

This script performs:
- Fuzzy duplicate detection and marking
- Data quality validation
- Phone number deduplication
- Domain deduplication
- Statistics and reporting

Usage:
    python scripts/cleanup_duplicates.py [options]

Options:
    --dry-run           Preview changes without modifying database
    --batch-size N      Process N records per batch (default: 1000)
    --name-threshold F  Name similarity threshold 0-1 (default: 0.85)
    --strict            Require multiple field matches for duplicate detection
    --source SOURCE     Only process companies from this source (e.g., 'YP')
    --report-only       Only generate report, don't mark duplicates
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, select, func, and_, or_
from sqlalchemy.orm import sessionmaker, Session
from db.models import Company, Base
from scrape_yp.yp_dedup import (
    DuplicateDetector,
    fuzzy_match_business_name,
    are_same_business,
    extract_domain
)
from db.utils import get_db_url

# Constants
DEFAULT_BATCH_SIZE = 1000
DEFAULT_NAME_THRESHOLD = 0.85


def setup_database() -> Session:
    """
    Setup database connection and return session.

    Returns:
        SQLAlchemy session
    """
    db_url = get_db_url()
    engine = create_engine(db_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def validate_company_data(company: Company) -> Tuple[bool, List[str]]:
    """
    Validate company data quality.

    Args:
        company: Company object to validate

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    # Check for required fields
    if not company.name or not company.name.strip():
        issues.append("Missing business name")

    if not company.website:
        issues.append("Missing website")

    if not company.phone:
        issues.append("Missing phone number")

    # Check for suspicious data
    if company.name and len(company.name) < 3:
        issues.append("Business name too short")

    if company.phone and len(company.phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')) < 10:
        issues.append("Invalid phone number format")

    # Check for placeholder/test data
    if company.name:
        name_lower = company.name.lower()
        if any(test in name_lower for test in ['test', 'sample', 'example', 'placeholder']):
            issues.append("Possible test/placeholder data")

    is_valid = len(issues) == 0
    return is_valid, issues


def find_duplicates_in_batch(
    companies: List[Company],
    detector: DuplicateDetector,
    session: Session
) -> Tuple[int, List[Dict]]:
    """
    Find duplicates in a batch of companies.

    Args:
        companies: List of Company objects
        detector: DuplicateDetector instance
        session: Database session

    Returns:
        Tuple of (duplicate_count, list_of_duplicate_info)
    """
    duplicate_count = 0
    duplicate_info = []

    for company in companies:
        # Convert to dict for dedup detector
        company_dict = {
            'id': company.id,
            'name': company.name,
            'phone': company.phone,
            'website': company.website,
            'address': company.address,
        }

        # Check for duplicate
        is_dup, matching, reason, confidence = detector.check_and_add(company_dict)

        if is_dup:
            duplicate_count += 1
            duplicate_info.append({
                'company_id': company.id,
                'company_name': company.name,
                'duplicate_of_id': matching.get('id'),
                'duplicate_of_name': matching.get('name'),
                'reason': reason,
                'confidence': confidence
            })

    return duplicate_count, duplicate_info


def mark_duplicates(
    session: Session,
    duplicate_info: List[Dict],
    dry_run: bool = False
) -> int:
    """
    Mark duplicates in the database by setting active=False.

    Args:
        session: Database session
        duplicate_info: List of duplicate information dicts
        dry_run: If True, don't actually modify database

    Returns:
        Number of records marked as duplicates
    """
    marked_count = 0

    for dup in duplicate_info:
        company_id = dup['company_id']

        if not dry_run:
            # Mark as inactive
            company = session.query(Company).filter(Company.id == company_id).first()
            if company:
                company.active = False
                company.last_updated = datetime.now(timezone.utc)
                marked_count += 1
        else:
            marked_count += 1

    if not dry_run:
        session.commit()

    return marked_count


def generate_report(
    total_processed: int,
    total_duplicates: int,
    total_invalid: int,
    duplicate_info: List[Dict],
    invalid_info: List[Dict],
    detector_stats: Dict,
    elapsed_seconds: float
) -> str:
    """
    Generate a cleanup report.

    Args:
        total_processed: Total companies processed
        total_duplicates: Total duplicates found
        total_invalid: Total invalid records found
        duplicate_info: List of duplicate details
        invalid_info: List of invalid record details
        detector_stats: Statistics from DuplicateDetector
        elapsed_seconds: Time taken

    Returns:
        Formatted report string
    """
    report = []
    report.append("=" * 80)
    report.append("CLEANUP JOB REPORT")
    report.append("=" * 80)
    report.append(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Processing Time: {elapsed_seconds:.2f} seconds")
    report.append("")

    report.append("SUMMARY:")
    report.append(f"  Total Companies Processed: {total_processed:,}")
    report.append(f"  Duplicates Found: {total_duplicates:,} ({total_duplicates/total_processed*100:.1f}%)")
    report.append(f"  Invalid Records: {total_invalid:,} ({total_invalid/total_processed*100:.1f}%)")
    report.append(f"  Unique Companies: {total_processed - total_duplicates:,}")
    report.append("")

    report.append("DEDUPLICATION STATS:")
    report.append(f"  Phone Index Size: {detector_stats.get('phone_index_size', 0):,}")
    report.append(f"  Domain Index Size: {detector_stats.get('domain_index_size', 0):,}")
    report.append(f"  Duplicate Rate: {detector_stats.get('duplicate_rate', 0):.1f}%")
    report.append("")

    # Top duplicates
    if duplicate_info:
        report.append("TOP 10 DUPLICATES:")
        for i, dup in enumerate(duplicate_info[:10], 1):
            report.append(f"  {i}. {dup['company_name']} (ID: {dup['company_id']})")
            report.append(f"     → Duplicate of: {dup['duplicate_of_name']} (ID: {dup['duplicate_of_id']})")
            report.append(f"     → Reason: {dup['reason']}")
            report.append(f"     → Confidence: {dup['confidence']:.1f}%")
            report.append("")

    # Invalid records sample
    if invalid_info:
        report.append("INVALID RECORDS (Sample of 10):")
        for i, inv in enumerate(invalid_info[:10], 1):
            report.append(f"  {i}. {inv['company_name']} (ID: {inv['company_id']})")
            report.append(f"     Issues: {', '.join(inv['issues'])}")
            report.append("")

    report.append("=" * 80)

    return "\n".join(report)


def main():
    """Main cleanup function."""
    parser = argparse.ArgumentParser(
        description="Post-processing cleanup job for Yellow Pages data"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying database"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Process N records per batch (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument(
        "--name-threshold",
        type=float,
        default=DEFAULT_NAME_THRESHOLD,
        help=f"Name similarity threshold 0-1 (default: {DEFAULT_NAME_THRESHOLD})"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require multiple field matches for duplicate detection"
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Only process companies from this source (e.g., 'YP')"
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Only generate report, don't mark duplicates"
    )

    args = parser.parse_args()

    print("=" * 80)
    print("YELLOW PAGES DATA CLEANUP JOB")
    print("=" * 80)
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Batch Size: {args.batch_size}")
    print(f"Name Threshold: {args.name_threshold}")
    print(f"Strict Mode: {args.strict}")
    print(f"Source Filter: {args.source or 'All'}")
    print(f"Report Only: {args.report_only}")
    print("=" * 80)
    print()

    # Setup database
    print("Connecting to database...")
    session = setup_database()

    # Initialize duplicate detector
    detector = DuplicateDetector(
        name_threshold=args.name_threshold,
        strict=args.strict
    )

    # Query companies
    query = session.query(Company).filter(Company.active == True)
    if args.source:
        query = query.filter(Company.source == args.source)

    total_count = query.count()
    print(f"Found {total_count:,} active companies to process")
    print()

    # Process in batches
    total_processed = 0
    total_duplicates = 0
    total_invalid = 0
    all_duplicate_info = []
    all_invalid_info = []

    start_time = datetime.now()

    print("Processing batches...")
    offset = 0
    while offset < total_count:
        # Fetch batch
        batch = query.limit(args.batch_size).offset(offset).all()
        if not batch:
            break

        # Find duplicates
        dup_count, dup_info = find_duplicates_in_batch(batch, detector, session)
        all_duplicate_info.extend(dup_info)
        total_duplicates += dup_count

        # Validate data quality
        for company in batch:
            is_valid, issues = validate_company_data(company)
            if not is_valid:
                total_invalid += 1
                all_invalid_info.append({
                    'company_id': company.id,
                    'company_name': company.name,
                    'issues': issues
                })

        total_processed += len(batch)
        offset += args.batch_size

        # Progress update
        progress = (total_processed / total_count * 100)
        print(f"  Processed: {total_processed:,}/{total_count:,} ({progress:.1f}%) | Duplicates: {total_duplicates:,} | Invalid: {total_invalid:,}")

    print()

    # Mark duplicates if not dry-run or report-only
    if not args.dry_run and not args.report_only and all_duplicate_info:
        print(f"Marking {len(all_duplicate_info)} duplicates as inactive...")
        marked_count = mark_duplicates(session, all_duplicate_info, dry_run=False)
        print(f"Marked {marked_count:,} records as inactive")
        print()
    elif args.dry_run:
        print(f"DRY RUN: Would mark {len(all_duplicate_info)} duplicates as inactive")
        print()

    # Generate report
    elapsed_seconds = (datetime.now() - start_time).total_seconds()
    detector_stats = detector.get_stats()

    report = generate_report(
        total_processed=total_processed,
        total_duplicates=total_duplicates,
        total_invalid=total_invalid,
        duplicate_info=all_duplicate_info,
        invalid_info=all_invalid_info,
        detector_stats=detector_stats,
        elapsed_seconds=elapsed_seconds
    )

    # Print report
    print(report)

    # Save report to file
    report_dir = Path(__file__).parent.parent / "logs"
    report_dir.mkdir(exist_ok=True)
    report_file = report_dir / f"cleanup_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    with open(report_file, 'w') as f:
        f.write(report)

    print(f"\nReport saved to: {report_file}")

    # Close session
    session.close()

    print("\nCleanup job completed!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
