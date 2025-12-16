#!/usr/bin/env python3
"""
Export BALANCED fine-tuning data for verification LLM.

The key issue with previous training: 99.9% of data was "legitimate: true"
This script creates balanced training data with both TRUE and FALSE cases.

Strategy:
1. Export companies with verified=TRUE (legitimate businesses)
2. Export companies with verified=FALSE (failed verifications)
3. Balance the dataset to ~50/50 or configurable ratio

Usage:
    python scripts/export_balanced_finetuning_data.py --limit 10000 --ratio 0.5
"""

import json
import sys
import argparse
import random
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import create_session
from sqlalchemy import text


DATA_DIR = Path(__file__).parent.parent / "data"
FINETUNE_DIR = DATA_DIR / "finetuning"


SYSTEM_PROMPT = """You are a business verification assistant. Your task is to determine if a company is a legitimate service provider that offers exterior building and property cleaning services.

Target services include:
- Pressure washing / power washing
- Window cleaning
- Soft washing
- Roof cleaning
- Gutter cleaning
- Solar panel cleaning
- Fleet/truck washing
- Wood restoration / deck cleaning

Analyze the company information and respond with a JSON object containing:
- legitimate: true/false - Is this a legitimate service provider?
- confidence: 0.0-1.0 - How confident are you?
- services: object with service types detected
- quality_signals: list of positive indicators
- red_flags: list of concerns or issues"""


def build_user_prompt(company: dict) -> str:
    """Build the user prompt from company data."""
    parts = [f"Company: {company['name']}"]

    if company.get('website'):
        parts.append(f"Website: {company['website']}")

    if company.get('phone'):
        parts.append(f"Phone: {company['phone']}")

    if company.get('address'):
        parts.append(f"Address: {company['address']}")

    if company.get('service_area'):
        parts.append(f"Service Area: {company['service_area']}")

    verification = company.get('verification', {})

    if verification.get('quality_signals'):
        signals = verification['quality_signals']
        if isinstance(signals, list):
            parts.append(f"Quality signals: {', '.join(signals)}")

    if verification.get('red_flags'):
        flags = verification['red_flags']
        if isinstance(flags, list):
            parts.append(f"Red flags: {', '.join(flags)}")

    if verification.get('positive_signals'):
        pos = verification['positive_signals']
        if isinstance(pos, list):
            parts.append(f"Positive signals: {', '.join(pos[:5])}")  # Limit to 5

    if verification.get('negative_signals'):
        neg = verification['negative_signals']
        if isinstance(neg, list):
            parts.append(f"Negative signals: {', '.join(neg[:5])}")  # Limit to 5

    parts.append("\nIs this a legitimate service provider? Provide your assessment.")

    return "\n".join(parts)


def build_assistant_response_true(company: dict) -> str:
    """Build TRUE response from company with claude_assessment."""
    verification = company.get('verification', {})
    claude = verification.get('claude_assessment', {})

    response = {
        "legitimate": True,
        "confidence": claude.get('claude_confidence', 0.85),
        "type": claude.get('claude_type', 1),
        "scope": claude.get('claude_scope', 2),
        "services": claude.get('claude_services', {
            "pressure_washing": True,
            "window_cleaning": False,
            "wood_restoration": False
        }),
        "quality_signals": claude.get('claude_quality_signals', [
            "Offers target services",
            "Contact information present"
        ])[:3],
        "red_flags": claude.get('claude_red_flags', [])[:2]
    }
    return json.dumps(response, indent=2)


def build_assistant_response_false(company: dict) -> str:
    """Build FALSE response from failed verification company."""
    verification = company.get('verification', {})
    llm_class = verification.get('llm_classification', {})

    # Determine reason for failure
    red_flags = verification.get('red_flags', [])
    if not red_flags:
        red_flags = llm_class.get('red_flags', [])
    if not red_flags:
        # Default red flags based on common failure reasons
        reason = verification.get('reason', '')
        if 'fetch' in reason.lower():
            red_flags = ['Website unreachable']
        elif 'directory' in reason.lower():
            red_flags = ['Directory or listing site, not actual service provider']
        elif 'franchise' in reason.lower():
            red_flags = ['Franchise sales page, not local service provider']
        else:
            red_flags = ['Does not provide target cleaning services']

    response = {
        "legitimate": False,
        "confidence": llm_class.get('confidence', 0.7),
        "type": llm_class.get('type', verification.get('tier_code', 4)),
        "scope": llm_class.get('scope', 0),
        "services": {
            "pressure_washing": llm_class.get('pressure_washing', False),
            "window_cleaning": llm_class.get('window_cleaning', False),
            "wood_restoration": llm_class.get('wood_restoration', False)
        },
        "quality_signals": verification.get('quality_signals', [])[:2],
        "red_flags": red_flags[:3]
    }
    return json.dumps(response, indent=2)


def fetch_legitimate_companies(session, limit: int) -> list:
    """Fetch verified=TRUE companies with claude_assessment."""
    query = text("""
        SELECT
            id, name, website, phone, address, service_area,
            parse_metadata->'verification' as verification
        FROM companies
        WHERE verified = TRUE
        AND parse_metadata->'verification'->'claude_assessment'->>'claude_legitimate' = 'true'
        ORDER BY RANDOM()
        LIMIT :limit
    """)

    result = session.execute(query, {'limit': limit})
    companies = []

    for row in result:
        companies.append({
            'id': row[0],
            'name': row[1],
            'website': row[2],
            'phone': row[3],
            'address': row[4],
            'service_area': row[5],
            'verification': row[6] or {},
            'label': True
        })

    return companies


def fetch_failed_companies(session, limit: int) -> list:
    """Fetch verified=FALSE companies with verification data."""
    query = text("""
        SELECT
            id, name, website, phone, address, service_area,
            parse_metadata->'verification' as verification
        FROM companies
        WHERE verified = FALSE
        AND parse_metadata->'verification'->>'status' = 'failed'
        ORDER BY RANDOM()
        LIMIT :limit
    """)

    result = session.execute(query, {'limit': limit})
    companies = []

    for row in result:
        companies.append({
            'id': row[0],
            'name': row[1],
            'website': row[2],
            'phone': row[3],
            'address': row[4],
            'service_area': row[5],
            'verification': row[6] or {},
            'label': False
        })

    return companies


def create_training_sample(company: dict) -> dict:
    """Create a training sample from a company."""
    user_content = build_user_prompt(company)

    if company['label']:
        assistant_content = build_assistant_response_true(company)
    else:
        assistant_content = build_assistant_response_false(company)

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content}
        ]
    }


def export_jsonl(samples: list, output_path: Path):
    """Export samples to JSONL file."""
    with open(output_path, 'w') as f:
        for sample in samples:
            f.write(json.dumps(sample) + "\n")
    print(f"Exported {len(samples)} samples to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Export balanced fine-tuning data')
    parser.add_argument(
        '--limit',
        type=int,
        default=10000,
        help='Total samples to export (default: 10000)'
    )
    parser.add_argument(
        '--ratio',
        type=float,
        default=0.5,
        help='Ratio of FALSE cases (default: 0.5 = 50/50 balance)'
    )
    parser.add_argument(
        '--split',
        type=float,
        default=0.9,
        help='Train/val split (default: 0.9)'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("BALANCED FINE-TUNING DATA EXPORT")
    print("=" * 60)

    FINETUNE_DIR.mkdir(parents=True, exist_ok=True)

    # Calculate how many of each
    false_count = int(args.limit * args.ratio)
    true_count = args.limit - false_count

    print(f"\nTarget: {true_count} TRUE + {false_count} FALSE = {args.limit} total")
    print(f"Ratio: {100*(1-args.ratio):.0f}% TRUE / {100*args.ratio:.0f}% FALSE")

    with create_session() as session:
        # Fetch TRUE cases
        print(f"\nFetching up to {true_count} legitimate companies...")
        true_companies = fetch_legitimate_companies(session, true_count)
        print(f"  Found: {len(true_companies)}")

        # Fetch FALSE cases
        print(f"Fetching up to {false_count} failed verification companies...")
        false_companies = fetch_failed_companies(session, false_count)
        print(f"  Found: {len(false_companies)}")

    if not true_companies or not false_companies:
        print("\nERROR: Not enough data!")
        sys.exit(1)

    # Create training samples
    print("\nCreating training samples...")
    all_samples = []

    for company in true_companies:
        sample = create_training_sample(company)
        all_samples.append(sample)

    for company in false_companies:
        sample = create_training_sample(company)
        all_samples.append(sample)

    # Shuffle
    random.shuffle(all_samples)

    # Count labels in final data
    true_labels = sum(1 for s in all_samples if '"legitimate": true' in s['messages'][2]['content'])
    false_labels = sum(1 for s in all_samples if '"legitimate": false' in s['messages'][2]['content'])

    print(f"\nFinal distribution: {true_labels} TRUE ({100*true_labels/len(all_samples):.1f}%) / {false_labels} FALSE ({100*false_labels/len(all_samples):.1f}%)")

    # Split into train/val
    split_idx = int(len(all_samples) * args.split)
    train_samples = all_samples[:split_idx]
    val_samples = all_samples[split_idx:]

    print(f"Split: {len(train_samples)} train / {len(val_samples)} validation")

    # Export
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    train_path = FINETUNE_DIR / f"balanced_train_{timestamp}.jsonl"
    val_path = FINETUNE_DIR / f"balanced_val_{timestamp}.jsonl"
    combined_path = FINETUNE_DIR / f"balanced_all_{timestamp}.jsonl"

    export_jsonl(train_samples, train_path)
    export_jsonl(val_samples, val_path)
    export_jsonl(all_samples, combined_path)

    print("\n" + "=" * 60)
    print("EXPORT COMPLETE")
    print("=" * 60)
    print(f"\nFiles created:")
    print(f"  Train: {train_path}")
    print(f"  Val:   {val_path}")
    print(f"  All:   {combined_path}")
    print(f"\nTo train with balanced data:")
    print(f"  python scripts/finetune_mistral.py --data {combined_path}")


if __name__ == '__main__':
    main()
