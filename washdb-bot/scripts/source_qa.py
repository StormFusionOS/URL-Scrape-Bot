#!/usr/bin/env python3
"""
Business Source Quality Assurance Script

Analyzes NAP (Name-Address-Phone) consistency across multiple business sources.

Features:
- Joins Company ↔ BusinessSource tables
- Computes per-field agreement & conflict counts
- Identifies companies with NAP conflicts
- Finds companies with only 1 weak source
- Generates CSV reports for review

Usage:
    python scripts/source_qa.py --output reports/nap_conflicts.csv
    python scripts/source_qa.py --weak-sources --min-score 50
    python scripts/source_qa.py --all-companies
"""

import os
import sys
import csv
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from difflib import SequenceMatcher

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from db.models import Company, BusinessSource
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("source_qa")


def normalize_for_comparison(text: Optional[str]) -> str:
    """Normalize text for fuzzy comparison."""
    if not text:
        return ""
    return text.lower().strip()


def fuzzy_match(text1: Optional[str], text2: Optional[str], threshold: float = 0.85) -> bool:
    """
    Check if two strings are similar using SequenceMatcher.

    Args:
        text1: First string
        text2: Second string
        threshold: Similarity threshold (0-1)

    Returns:
        True if similarity >= threshold
    """
    if not text1 or not text2:
        return False

    norm1 = normalize_for_comparison(text1)
    norm2 = normalize_for_comparison(text2)

    if norm1 == norm2:
        return True

    similarity = SequenceMatcher(None, norm1, norm2).ratio()
    return similarity >= threshold


def analyze_company_sources(company: Company, sources: List[BusinessSource]) -> Dict[str, Any]:
    """
    Analyze NAP consistency for a company across its sources.

    Args:
        company: Company record
        sources: List of BusinessSource records for this company

    Returns:
        Dict with consistency analysis
    """
    if not sources:
        return {
            'company_id': company.id,
            'company_name': company.name,
            'source_count': 0,
            'has_conflict': False,
            'conflicts': {},
            'agreement': {},
            'weak_source': True,
            'quality_scores': []
        }

    # Collect unique values for each field
    names = [s.name for s in sources if s.name]
    phones = [s.phone for s in sources if s.phone]
    streets = [s.street for s in sources if s.street]
    cities = [s.city for s in sources if s.city]
    states = [s.state for s in sources if s.state]
    zip_codes = [s.zip_code for s in sources if s.zip_code]

    # Count unique values (exact match)
    unique_names = len(set(normalize_for_comparison(n) for n in names))
    unique_phones = len(set(normalize_for_comparison(p) for p in phones))
    unique_streets = len(set(normalize_for_comparison(s) for s in streets))
    unique_cities = len(set(normalize_for_comparison(c) for c in cities))
    unique_states = len(set(normalize_for_comparison(s) for s in states))
    unique_zips = len(set(normalize_for_comparison(z) for z in zip_codes))

    # Detect conflicts (more than 1 unique value)
    has_conflict = (
        unique_names > 1 or
        unique_phones > 1 or
        unique_streets > 1 or
        unique_cities > 1 or
        unique_states > 1 or
        unique_zips > 1
    )

    conflicts = {}
    if unique_names > 1:
        conflicts['name'] = list(set(names))
    if unique_phones > 1:
        conflicts['phone'] = list(set(phones))
    if unique_streets > 1:
        conflicts['street'] = list(set(streets))
    if unique_cities > 1:
        conflicts['city'] = list(set(cities))
    if unique_states > 1:
        conflicts['state'] = list(set(states))
    if unique_zips > 1:
        conflicts['zip_code'] = list(set(zip_codes))

    # Calculate agreement (sources with matching data)
    agreement = {}
    if len(sources) > 1:
        # Name agreement
        if names:
            reference_name = names[0]
            agreement_count = sum(1 for n in names if fuzzy_match(n, reference_name))
            agreement['name'] = f"{agreement_count}/{len(names)}"

        # Phone agreement (exact)
        if phones:
            reference_phone = normalize_for_comparison(phones[0])
            agreement_count = sum(1 for p in phones if normalize_for_comparison(p) == reference_phone)
            agreement['phone'] = f"{agreement_count}/{len(phones)}"

        # Street agreement
        if streets:
            reference_street = streets[0]
            agreement_count = sum(1 for s in streets if fuzzy_match(s, reference_street))
            agreement['street'] = f"{agreement_count}/{len(streets)}"

        # City agreement
        if cities:
            reference_city = normalize_for_comparison(cities[0])
            agreement_count = sum(1 for c in cities if normalize_for_comparison(c) == reference_city)
            agreement['city'] = f"{agreement_count}/{len(cities)}"

    # Quality scores
    quality_scores = [s.data_quality_score for s in sources if s.data_quality_score is not None]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

    # Weak source detection (only 1 source with low quality)
    weak_source = len(sources) == 1 and avg_quality < 70

    # Source breakdown
    source_breakdown = {}
    for source in sources:
        source_type = source.source_type
        if source_type not in source_breakdown:
            source_breakdown[source_type] = {
                'count': 0,
                'avg_quality': 0,
                'verified': False
            }
        source_breakdown[source_type]['count'] += 1
        source_breakdown[source_type]['verified'] = source_breakdown[source_type]['verified'] or source.is_verified

    # Calculate average quality per source type
    for source_type in source_breakdown:
        type_sources = [s for s in sources if s.source_type == source_type]
        type_scores = [s.data_quality_score for s in type_sources if s.data_quality_score]
        if type_scores:
            source_breakdown[source_type]['avg_quality'] = sum(type_scores) / len(type_scores)

    return {
        'company_id': company.id,
        'company_name': company.name,
        'company_domain': company.domain,
        'source_count': len(sources),
        'has_conflict': has_conflict,
        'conflicts': conflicts,
        'agreement': agreement,
        'weak_source': weak_source,
        'quality_scores': quality_scores,
        'avg_quality': avg_quality,
        'source_breakdown': source_breakdown,
        'sources': [{'type': s.source_type, 'quality': s.data_quality_score} for s in sources]
    }


def generate_csv_report(
    analyses: List[Dict[str, Any]],
    output_path: str,
    mode: str = 'conflicts'
) -> None:
    """
    Generate CSV report from analyses.

    Args:
        analyses: List of company analysis dicts
        output_path: Path to output CSV file
        mode: 'conflicts', 'weak', or 'all'
    """
    # Ensure output directory exists
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'company_id', 'company_name', 'company_domain', 'source_count',
            'has_conflict', 'conflict_fields', 'name_agreement', 'phone_agreement',
            'street_agreement', 'city_agreement', 'avg_quality', 'weak_source',
            'source_types', 'source_details'
        ]

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for analysis in analyses:
            # Skip based on mode
            if mode == 'conflicts' and not analysis['has_conflict']:
                continue
            if mode == 'weak' and not analysis['weak_source']:
                continue

            # Format conflict fields
            conflict_fields = ', '.join(analysis['conflicts'].keys()) if analysis['conflicts'] else 'None'

            # Format source types
            source_types = ', '.join(
                f"{stype} ({data['count']})"
                for stype, data in analysis['source_breakdown'].items()
            )

            # Format source details
            source_details = '; '.join(
                f"{s['type']}:{s['quality'] or 'N/A'}"
                for s in analysis['sources']
            )

            writer.writerow({
                'company_id': analysis['company_id'],
                'company_name': analysis['company_name'],
                'company_domain': analysis['company_domain'],
                'source_count': analysis['source_count'],
                'has_conflict': analysis['has_conflict'],
                'conflict_fields': conflict_fields,
                'name_agreement': analysis['agreement'].get('name', 'N/A'),
                'phone_agreement': analysis['agreement'].get('phone', 'N/A'),
                'street_agreement': analysis['agreement'].get('street', 'N/A'),
                'city_agreement': analysis['agreement'].get('city', 'N/A'),
                'avg_quality': f"{analysis['avg_quality']:.1f}",
                'weak_source': analysis['weak_source'],
                'source_types': source_types,
                'source_details': source_details
            })

    logger.info(f"CSV report written to: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze NAP consistency across business sources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate report of companies with NAP conflicts
  python scripts/source_qa.py --output reports/nap_conflicts.csv

  # Find companies with only 1 weak source (quality < 70)
  python scripts/source_qa.py --weak-sources --min-score 70 --output reports/weak_sources.csv

  # Generate report for all companies
  python scripts/source_qa.py --all-companies --output reports/all_sources.csv

  # Limit to specific number of companies
  python scripts/source_qa.py --limit 100 --output reports/sample.csv
        """
    )

    parser.add_argument(
        '--output', '-o',
        type=str,
        default=f"reports/source_qa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        help="Output CSV file path (default: reports/source_qa_TIMESTAMP.csv)"
    )

    parser.add_argument(
        '--weak-sources',
        action='store_true',
        help="Only show companies with 1 weak source (low quality)"
    )

    parser.add_argument(
        '--all-companies',
        action='store_true',
        help="Show all companies (default: only conflicts)"
    )

    parser.add_argument(
        '--min-score',
        type=int,
        default=70,
        help="Minimum quality score threshold for weak source detection (default: 70)"
    )

    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help="Limit number of companies to analyze"
    )

    args = parser.parse_args()

    # Determine mode
    if args.all_companies:
        mode = 'all'
    elif args.weak_sources:
        mode = 'weak'
    else:
        mode = 'conflicts'

    logger.info("=" * 80)
    logger.info("Business Source Quality Assurance")
    logger.info("=" * 80)
    logger.info(f"Mode: {mode}")
    logger.info(f"Output: {args.output}")
    logger.info("")

    # Connect to database
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set in environment")
        return 1

    engine = create_engine(database_url, echo=False)

    with Session(engine) as session:
        # Query companies with their sources
        query = (
            select(Company)
            .order_by(Company.id)
        )

        if args.limit:
            query = query.limit(args.limit)

        companies = session.execute(query).scalars().all()

        logger.info(f"Analyzing {len(companies)} companies...")
        logger.info("")

        analyses = []
        conflict_count = 0
        weak_source_count = 0

        for company in companies:
            # Get all sources for this company
            sources_query = select(BusinessSource).where(BusinessSource.company_id == company.id)
            sources = session.execute(sources_query).scalars().all()

            analysis = analyze_company_sources(company, sources)
            analyses.append(analysis)

            if analysis['has_conflict']:
                conflict_count += 1
            if analysis['weak_source']:
                weak_source_count += 1

        logger.info("=" * 80)
        logger.info("Analysis Summary")
        logger.info("=" * 80)
        logger.info(f"Total companies analyzed: {len(companies)}")
        logger.info(f"Companies with NAP conflicts: {conflict_count}")
        logger.info(f"Companies with weak sources: {weak_source_count}")
        logger.info("")

        # Generate CSV report
        generate_csv_report(analyses, args.output, mode=mode)

        logger.info("=" * 80)
        logger.info("QA Complete")
        logger.info("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
