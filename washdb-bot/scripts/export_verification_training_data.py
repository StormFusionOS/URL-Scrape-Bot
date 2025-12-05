#!/usr/bin/env python3
"""
Export verification training data for model training and analysis.

Exports companies with human labels to JSONL format for:
- Training supervised classifiers
- Analyzing misclassifications
- Refining LLM prompts

Usage:
    python scripts/export_verification_training_data.py [--output FILE]

Options:
    --output FILE    Output file path (default: data/verification_training.jsonl)
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger

load_dotenv()

logger = get_logger("export_training_data")


def get_labeled_companies(session):
    """
    Get all companies with human labels.

    Returns:
        List of company dicts with verification data
    """
    query = text("""
        SELECT
            id,
            name,
            website,
            domain,
            source,
            rating_yp,
            rating_google,
            reviews_yp,
            reviews_google,
            parse_metadata
        FROM companies
        WHERE parse_metadata->'verification'->>'human_label' IS NOT NULL
        ORDER BY parse_metadata->'verification'->>'reviewed_at' DESC
    """)

    result = session.execute(query)

    companies = []
    for row in result:
        companies.append({
            'id': row.id,
            'name': row.name,
            'website': row.website,
            'domain': row.domain,
            'source': row.source,
            'rating_yp': row.rating_yp,
            'rating_google': row.rating_google,
            'reviews_yp': row.reviews_yp,
            'reviews_google': row.reviews_google,
            'parse_metadata': row.parse_metadata or {}
        })

    return companies


def extract_features(company: dict) -> dict:
    """
    Extract features from company data for ML training.

    Args:
        company: Company dict with parse_metadata

    Returns:
        Dict of extracted features
    """
    verification = company['parse_metadata'].get('verification', {})
    yp_filter = company['parse_metadata'].get('yp_filter', {})
    google_filter = company['parse_metadata'].get('google_filter', {})

    # Calculate review score (log-scaled)
    reviews_total = (company.get('reviews_google') or 0) + (company.get('reviews_yp') or 0)
    review_score = min(math.log1p(reviews_total) / 5.0, 1.0)

    # Extract LLM classification features
    llm_class = verification.get('llm_classification', {})

    features = {
        # Verification scores
        'web_score': verification.get('score', 0.0),
        'combined_score': verification.get('combined_score', 0.0),
        'rule_score': verification.get('rule_score', 0.0),
        'llm_score': verification.get('llm_score', 0.0),

        # LLM outputs
        'is_legitimate': verification.get('is_legitimate', False),
        'llm_type': llm_class.get('type', 0),
        'llm_confidence': llm_class.get('confidence', 0.0),
        'pressure_washing': llm_class.get('pressure_washing', False),
        'window_cleaning': llm_class.get('window_cleaning', False),
        'wood_restoration': llm_class.get('wood_restoration', False),
        'scope': llm_class.get('scope', 0),

        # Red flags and quality
        'red_flags_count': len(verification.get('red_flags', [])),
        'quality_signals_count': len(verification.get('quality_signals', [])),

        # Tier
        'tier': verification.get('tier', 'E'),

        # Contact info
        'has_phone': verification.get('has_phone', False),
        'has_email': verification.get('has_email', False),
        'has_address': verification.get('has_address', False),

        # Language analysis
        'provider_phrase_count': verification.get('provider_phrase_count', 0),
        'informational_phrase_count': verification.get('informational_phrase_count', 0),
        'cta_phrase_count': verification.get('cta_phrase_count', 0),

        # Site structure
        'has_service_nav': verification.get('has_service_nav', False),
        'has_local_business_schema': verification.get('has_local_business_schema', False),

        # Discovery signals
        'yp_confidence': yp_filter.get('confidence', 0.0),
        'google_confidence': google_filter.get('confidence', 0.0),

        # Reviews
        'rating_google': company.get('rating_google') or 0.0,
        'rating_yp': company.get('rating_yp') or 0.0,
        'reviews_google': company.get('reviews_google') or 0,
        'reviews_yp': company.get('reviews_yp') or 0,
        'review_score': review_score,

        # Metadata
        'deep_scraped': verification.get('deep_scraped', False),
        'source': company.get('source', ''),
    }

    return features


def export_to_jsonl(companies: list, output_path: str):
    """
    Export companies to JSONL format.

    Args:
        companies: List of company dicts
        output_path: Output file path
    """
    # Ensure output directory exists
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        for company in companies:
            verification = company['parse_metadata'].get('verification', {})

            record = {
                'id': company['id'],
                'url': company['website'],
                'domain': company['domain'],
                'name': company['name'],
                'features': extract_features(company),
                'label': verification.get('human_label'),
                'human_notes': verification.get('human_notes', ''),
                'model_status': verification.get('status'),
                'model_score': verification.get('score', 0.0),
                'red_flags': verification.get('red_flags', []),
                'quality_signals': verification.get('quality_signals', []),
            }

            f.write(json.dumps(record) + '\n')


def analyze_labels(companies: list):
    """
    Print analysis of labeled data.

    Args:
        companies: List of company dicts
    """
    label_counts = {}
    model_vs_human = {'correct': 0, 'incorrect': 0}

    for company in companies:
        verification = company['parse_metadata'].get('verification', {})
        human_label = verification.get('human_label')
        model_status = verification.get('status')

        # Count labels
        label_counts[human_label] = label_counts.get(human_label, 0) + 1

        # Compare model vs human
        # Model "passed" should match human "provider"
        # Model "failed" should match human non-provider types
        if human_label == 'provider':
            if model_status == 'passed':
                model_vs_human['correct'] += 1
            else:
                model_vs_human['incorrect'] += 1
        else:  # non_provider, directory, agency, blog, franchise
            if model_status in ('failed', 'unknown'):
                model_vs_human['correct'] += 1
            else:
                model_vs_human['incorrect'] += 1

    print("\n" + "=" * 50)
    print("  TRAINING DATA ANALYSIS")
    print("=" * 50)

    print("\n  Label Distribution:")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        pct = count / len(companies) * 100
        print(f"    {label:15} {count:5} ({pct:.1f}%)")

    print(f"\n  Total Samples: {len(companies)}")

    total = model_vs_human['correct'] + model_vs_human['incorrect']
    if total > 0:
        accuracy = model_vs_human['correct'] / total * 100
        print(f"\n  Model vs Human Agreement:")
        print(f"    Correct:   {model_vs_human['correct']}")
        print(f"    Incorrect: {model_vs_human['incorrect']}")
        print(f"    Accuracy:  {accuracy:.1f}%")


def main():
    parser = argparse.ArgumentParser(description='Export verification training data')
    parser.add_argument('--output', default='data/verification_training.jsonl',
                       help='Output file path')

    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  EXPORT VERIFICATION TRAINING DATA")
    print("=" * 50)

    # Connect to database
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Get labeled companies
        print("\n  Fetching labeled companies...")
        companies = get_labeled_companies(session)

        if not companies:
            print("  No labeled companies found. Run review_verification_queue.py first.")
            return 1

        print(f"  Found {len(companies)} labeled companies")

        # Export to JSONL
        print(f"\n  Exporting to: {args.output}")
        export_to_jsonl(companies, args.output)
        print(f"  ✓ Exported {len(companies)} records")

        # Print analysis
        analyze_labels(companies)

        return 0

    except Exception as e:
        logger.error(f"Export failed: {e}")
        return 1

    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
