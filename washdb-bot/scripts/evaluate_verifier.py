#!/usr/bin/env python3
"""
Offline evaluation harness for the verification pipeline.

Runs the full verification pipeline on labeled data and computes metrics:
- Precision, recall, F1 for provider vs non-provider
- Confusion matrix
- Percentage of items landing in needs_review

Usage:
    python scripts/evaluate_verifier.py [--input FILE] [--from-db]

Options:
    --input FILE    Input JSONL file with labeled data
    --from-db       Load labeled data directly from database
    --dry-run       Don't re-run verification, just compute metrics from stored results
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger
from scrape_site.site_scraper import fetch_page
from scrape_site.site_parse import parse_site_content
from scrape_site.service_verifier import create_verifier
from db.verify_company_urls import calculate_combined_score
from verification.config_verifier import (
    COMBINED_HIGH_THRESHOLD,
    COMBINED_LOW_THRESHOLD,
    RED_FLAG_AUTO_REJECT_COUNT,
)

load_dotenv()

logger = get_logger("evaluate_verifier")


def load_from_jsonl(input_path: str) -> list:
    """Load labeled data from JSONL file."""
    records = []
    with open(input_path, 'r') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def load_from_db(session) -> list:
    """Load labeled data directly from database."""
    query = text("""
        SELECT
            id, name, website, domain, phone, email,
            services, service_area, address, source,
            rating_yp, rating_google, reviews_yp, reviews_google,
            parse_metadata, active
        FROM companies
        WHERE parse_metadata->'verification'->>'human_label' IS NOT NULL
        ORDER BY parse_metadata->'verification'->>'reviewed_at' DESC
    """)

    result = session.execute(query)

    records = []
    for row in result:
        verification = (row.parse_metadata or {}).get('verification', {})
        records.append({
            'id': row.id,
            'name': row.name,
            'url': row.website,
            'domain': row.domain,
            'label': verification.get('human_label'),
            'company_data': {
                'id': row.id,
                'name': row.name,
                'website': row.website,
                'domain': row.domain,
                'phone': row.phone,
                'email': row.email,
                'services': row.services,
                'service_area': row.service_area,
                'address': row.address,
                'source': row.source,
                'rating_yp': row.rating_yp,
                'rating_google': row.rating_google,
                'reviews_yp': row.reviews_yp,
                'reviews_google': row.reviews_google,
                'parse_metadata': row.parse_metadata or {},
                'active': row.active,
            },
            # Also include stored verification result for dry-run
            'stored_verification': verification,
        })

    return records


def run_verification_pipeline(company_data: dict, verifier) -> dict:
    """
    Run the full verification pipeline on a company.

    Args:
        company_data: Company dict
        verifier: ServiceVerifier instance

    Returns:
        Dict with verification result and timing
    """
    start_time = time.time()

    website = company_data.get('website')
    if not website:
        return {
            'status': 'failed',
            'score': 0.0,
            'reason': 'No website',
            'elapsed_ms': 0
        }

    try:
        # Fetch and parse website
        html = fetch_page(website, delay=1.0)
        if not html:
            return {
                'status': 'failed',
                'score': 0.0,
                'reason': 'Failed to fetch',
                'elapsed_ms': int((time.time() - start_time) * 1000)
            }

        metadata = parse_site_content(html, website)

        # Run verification
        verification_result = verifier.verify_company(
            company_data=company_data,
            website_html=html,
            website_metadata=metadata
        )

        # Calculate combined score
        combined_score = calculate_combined_score(company_data, verification_result)

        # Apply triage logic
        svc_status = verification_result.get('status', 'unknown')
        is_legitimate = verification_result.get('is_legitimate', False)
        red_flags = verification_result.get('red_flags', []) or []

        needs_review = False

        if (combined_score >= COMBINED_HIGH_THRESHOLD and
            is_legitimate and
            svc_status == 'passed' and
            len(red_flags) == 0):
            final_status = 'passed'
        elif (combined_score <= COMBINED_LOW_THRESHOLD or
              (not is_legitimate and len(red_flags) >= RED_FLAG_AUTO_REJECT_COUNT)):
            final_status = 'failed'
        else:
            final_status = 'unknown'
            needs_review = True

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            'status': final_status,
            'score': verification_result.get('score', 0.0),
            'combined_score': combined_score,
            'needs_review': needs_review,
            'is_legitimate': is_legitimate,
            'red_flags': red_flags,
            'tier': verification_result.get('tier', 'E'),
            'elapsed_ms': elapsed_ms,
        }

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            'status': 'error',
            'score': 0.0,
            'reason': str(e),
            'elapsed_ms': elapsed_ms
        }


def compute_metrics(records: list, predictions: list) -> dict:
    """
    Compute evaluation metrics.

    Args:
        records: List of labeled records
        predictions: List of prediction dicts

    Returns:
        Dict of metrics
    """
    # Map human labels to binary (provider vs non-provider)
    def is_provider(label):
        return label == 'provider'

    # Confusion matrix counts
    tp = fp = tn = fn = 0

    # Per-label confusion
    label_confusion = defaultdict(lambda: defaultdict(int))

    # Needs review tracking
    needs_review_count = 0
    needs_review_correct = 0

    for record, pred in zip(records, predictions):
        human_label = record['label']
        pred_status = pred['status']
        needs_review = pred.get('needs_review', False)

        # Binary classification metrics
        human_positive = is_provider(human_label)
        pred_positive = pred_status == 'passed'

        if human_positive and pred_positive:
            tp += 1
        elif human_positive and not pred_positive:
            fn += 1
        elif not human_positive and pred_positive:
            fp += 1
        else:
            tn += 1

        # Per-label confusion
        pred_label = 'provider' if pred_positive else 'non_provider'
        label_confusion[human_label][pred_label] += 1

        # Needs review tracking
        if needs_review:
            needs_review_count += 1
            # Consider needs_review "correct" if the human label was ambiguous
            if human_label in ('directory', 'agency', 'blog', 'franchise'):
                needs_review_correct += 1

    # Calculate metrics
    total = len(records)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    accuracy = (tp + tn) / total if total > 0 else 0

    return {
        'total': total,
        'true_positives': tp,
        'false_positives': fp,
        'true_negatives': tn,
        'false_negatives': fn,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'accuracy': accuracy,
        'needs_review_count': needs_review_count,
        'needs_review_rate': needs_review_count / total if total > 0 else 0,
        'label_confusion': dict(label_confusion),
    }


def print_report(metrics: dict, records: list, predictions: list):
    """Print evaluation report."""
    print("\n" + "=" * 60)
    print("  VERIFICATION PIPELINE EVALUATION REPORT")
    print("=" * 60)

    print(f"\n  Total Samples: {metrics['total']}")

    print("\n  --- Binary Classification (Provider vs Non-Provider) ---")
    print(f"  Precision:  {metrics['precision']:.3f}")
    print(f"  Recall:     {metrics['recall']:.3f}")
    print(f"  F1 Score:   {metrics['f1']:.3f}")
    print(f"  Accuracy:   {metrics['accuracy']:.3f}")

    print("\n  --- Confusion Matrix ---")
    print(f"  True Positives (correct providers):   {metrics['true_positives']}")
    print(f"  False Positives (wrong providers):    {metrics['false_positives']}")
    print(f"  True Negatives (correct rejects):     {metrics['true_negatives']}")
    print(f"  False Negatives (missed providers):   {metrics['false_negatives']}")

    print("\n  --- Needs Review ---")
    print(f"  Items in needs_review: {metrics['needs_review_count']}")
    print(f"  Needs review rate:     {metrics['needs_review_rate']:.1%}")

    print("\n  --- Per-Label Breakdown ---")
    for human_label, pred_counts in sorted(metrics['label_confusion'].items()):
        total_for_label = sum(pred_counts.values())
        print(f"\n  Human Label: {human_label} ({total_for_label} samples)")
        for pred_label, count in sorted(pred_counts.items()):
            pct = count / total_for_label * 100 if total_for_label > 0 else 0
            print(f"    → Predicted {pred_label}: {count} ({pct:.1f}%)")

    # Show some misclassified examples
    print("\n  --- Sample Misclassifications ---")
    misclassified = []
    for record, pred in zip(records, predictions):
        human_is_provider = record['label'] == 'provider'
        pred_is_provider = pred['status'] == 'passed'
        if human_is_provider != pred_is_provider:
            misclassified.append((record, pred))

    for record, pred in misclassified[:5]:
        print(f"\n  Company: {record.get('name', record.get('url', 'N/A'))}")
        print(f"    Human: {record['label']}")
        print(f"    Model: {pred['status']} (score={pred['score']:.2f})")
        if pred.get('red_flags'):
            print(f"    Flags: {', '.join(pred['red_flags'][:3])}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Evaluate verification pipeline')
    parser.add_argument('--input', help='Input JSONL file with labeled data')
    parser.add_argument('--from-db', action='store_true', help='Load from database')
    parser.add_argument('--dry-run', action='store_true',
                       help='Use stored results, don\'t re-run verification')
    parser.add_argument('--limit', type=int, help='Limit number of samples')

    args = parser.parse_args()

    if not args.input and not args.from_db:
        print("Error: Must specify --input FILE or --from-db")
        return 1

    print("\n" + "=" * 60)
    print("  VERIFIER EVALUATION")
    print("=" * 60)

    # Load data
    if args.from_db:
        print("\n  Loading labeled data from database...")
        engine = create_engine(os.getenv('DATABASE_URL'))
        Session = sessionmaker(bind=engine)
        session = Session()
        records = load_from_db(session)
        session.close()
    else:
        print(f"\n  Loading labeled data from: {args.input}")
        records = load_from_jsonl(args.input)

    if args.limit:
        records = records[:args.limit]

    print(f"  Loaded {len(records)} labeled records")

    if not records:
        print("  No data to evaluate!")
        return 1

    # Get predictions
    predictions = []

    if args.dry_run:
        print("\n  Using stored verification results (dry-run mode)")
        for record in records:
            stored = record.get('stored_verification', {})
            predictions.append({
                'status': stored.get('status', 'unknown'),
                'score': stored.get('score', 0.0),
                'combined_score': stored.get('combined_score', 0.0),
                'needs_review': stored.get('needs_review', False),
                'is_legitimate': stored.get('is_legitimate', False),
                'red_flags': stored.get('red_flags', []),
                'tier': stored.get('tier', 'E'),
            })
    else:
        print("\n  Running verification pipeline on each sample...")
        verifier = create_verifier()

        for i, record in enumerate(records, 1):
            company_data = record.get('company_data', {
                'name': record.get('name', ''),
                'website': record['url'],
                'domain': record.get('domain', ''),
                'parse_metadata': {}
            })

            print(f"  [{i}/{len(records)}] {company_data.get('name', record['url'])[:40]}...",
                  end='', flush=True)

            pred = run_verification_pipeline(company_data, verifier)
            predictions.append(pred)

            print(f" → {pred['status']} ({pred['elapsed_ms']}ms)")

            # Rate limiting
            if i < len(records):
                time.sleep(1.0)

    # Compute metrics
    print("\n  Computing metrics...")
    metrics = compute_metrics(records, predictions)

    # Print report
    print_report(metrics, records, predictions)

    # Save report
    report_path = 'logs/eval/evaluation_report.json'
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)

    report = {
        'timestamp': datetime.now().isoformat(),
        'total_samples': metrics['total'],
        'metrics': {
            'precision': metrics['precision'],
            'recall': metrics['recall'],
            'f1': metrics['f1'],
            'accuracy': metrics['accuracy'],
            'needs_review_rate': metrics['needs_review_rate'],
        },
        'confusion': {
            'tp': metrics['true_positives'],
            'fp': metrics['false_positives'],
            'tn': metrics['true_negatives'],
            'fn': metrics['false_negatives'],
        },
        'label_breakdown': metrics['label_confusion'],
    }

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n  Report saved to: {report_path}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
