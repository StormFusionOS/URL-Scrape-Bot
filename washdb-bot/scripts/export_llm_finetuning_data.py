#!/usr/bin/env python3
"""
Export Claude-verified data for LLM fine-tuning.

This script exports companies verified by Claude API into formats suitable for
fine-tuning local LLMs like Mistral via Ollama.

Supported formats:
- JSONL (OpenAI/Ollama format): {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
- Alpaca format: {"instruction": ..., "input": ..., "output": ...}

Usage:
    python scripts/export_llm_finetuning_data.py [--format jsonl|alpaca] [--limit N]
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import create_session
from sqlalchemy import text


# Output paths
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

    # Include verification signals if available
    verification = company.get('verification', {})

    if verification.get('quality_signals'):
        parts.append(f"Quality signals: {', '.join(verification['quality_signals'])}")

    if verification.get('red_flags'):
        parts.append(f"Red flags: {', '.join(verification['red_flags'])}")

    if verification.get('positive_signals'):
        parts.append(f"Positive signals: {', '.join(verification['positive_signals'])}")

    if verification.get('negative_signals'):
        parts.append(f"Negative signals: {', '.join(verification['negative_signals'])}")

    parts.append("\nIs this a legitimate service provider? Provide your assessment.")

    return "\n".join(parts)


def build_assistant_response(claude_assessment: dict) -> str:
    """Build the assistant response from Claude's assessment."""
    response = {
        "legitimate": claude_assessment.get('claude_legitimate', False),
        "confidence": claude_assessment.get('claude_confidence', 0.5),
        "type": claude_assessment.get('claude_type', 0),
        "scope": claude_assessment.get('claude_scope', 0),
        "services": claude_assessment.get('claude_services', {}),
        "quality_signals": claude_assessment.get('claude_quality_signals', []),
        "red_flags": claude_assessment.get('claude_red_flags', [])
    }
    return json.dumps(response, indent=2)


def export_jsonl_format(companies: list, output_path: Path):
    """Export in JSONL format for OpenAI/Ollama fine-tuning."""
    with open(output_path, 'w') as f:
        for company in companies:
            claude_assessment = company['verification'].get('claude_assessment', {})
            if not claude_assessment:
                continue

            record = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(company)},
                    {"role": "assistant", "content": build_assistant_response(claude_assessment)}
                ]
            }
            f.write(json.dumps(record) + "\n")

    print(f"Exported JSONL format to: {output_path}")


def export_alpaca_format(companies: list, output_path: Path):
    """Export in Alpaca format for fine-tuning."""
    with open(output_path, 'w') as f:
        for company in companies:
            claude_assessment = company['verification'].get('claude_assessment', {})
            if not claude_assessment:
                continue

            record = {
                "instruction": SYSTEM_PROMPT,
                "input": build_user_prompt(company),
                "output": build_assistant_response(claude_assessment)
            }
            f.write(json.dumps(record) + "\n")

    print(f"Exported Alpaca format to: {output_path}")


def fetch_claude_verified_companies(limit: int = None) -> list:
    """Fetch companies that have been verified by Claude."""
    with create_session() as session:
        limit_clause = f"LIMIT {limit}" if limit else ""

        query = text(f"""
            SELECT
                id,
                name,
                website,
                phone,
                address,
                service_area,
                parse_metadata->'verification' as verification
            FROM companies
            WHERE parse_metadata->'verification'->'claude_assessment'->>'claude_legitimate' IS NOT NULL
            ORDER BY RANDOM()
            {limit_clause}
        """)

        result = session.execute(query)
        companies = []

        for row in result:
            companies.append({
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'phone': row[3],
                'address': row[4],
                'service_area': row[5],
                'verification': row[6] or {}
            })

        return companies


def main():
    parser = argparse.ArgumentParser(description='Export Claude-verified data for LLM fine-tuning')
    parser.add_argument(
        '--format',
        choices=['jsonl', 'alpaca', 'both'],
        default='both',
        help='Output format (default: both)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of records to export'
    )
    parser.add_argument(
        '--split',
        type=float,
        default=0.9,
        help='Train/validation split ratio (default: 0.9)'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("LLM FINE-TUNING DATA EXPORT")
    print("=" * 60)

    # Create output directory
    FINETUNE_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch data
    print(f"\nFetching Claude-verified companies...")
    companies = fetch_claude_verified_companies(limit=args.limit)
    print(f"Found {len(companies):,} companies with Claude verification")

    if not companies:
        print("No data to export!")
        sys.exit(1)

    # Split into train/validation
    split_idx = int(len(companies) * args.split)
    train_companies = companies[:split_idx]
    val_companies = companies[split_idx:]

    print(f"\nSplit: {len(train_companies):,} training, {len(val_companies):,} validation")

    # Count legitimate vs not
    legit_count = sum(1 for c in companies if c['verification'].get('claude_assessment', {}).get('claude_legitimate', False))
    print(f"Class distribution: {legit_count:,} legitimate, {len(companies) - legit_count:,} not legitimate")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Export in requested formats
    if args.format in ('jsonl', 'both'):
        # Training set
        train_path = FINETUNE_DIR / f"train_verification_{timestamp}.jsonl"
        export_jsonl_format(train_companies, train_path)

        # Validation set
        val_path = FINETUNE_DIR / f"val_verification_{timestamp}.jsonl"
        export_jsonl_format(val_companies, val_path)

    if args.format in ('alpaca', 'both'):
        # Training set
        train_path = FINETUNE_DIR / f"train_verification_alpaca_{timestamp}.jsonl"
        export_alpaca_format(train_companies, train_path)

        # Validation set
        val_path = FINETUNE_DIR / f"val_verification_alpaca_{timestamp}.jsonl"
        export_alpaca_format(val_companies, val_path)

    # Also create a combined file for easy use
    combined_path = FINETUNE_DIR / f"verification_finetuning_{timestamp}.jsonl"
    export_jsonl_format(companies, combined_path)

    print("\n" + "=" * 60)
    print("EXPORT COMPLETE")
    print("=" * 60)
    print(f"\nFiles created in: {FINETUNE_DIR}")
    print(f"\nTo fine-tune Mistral with Ollama, use:")
    print(f"  ollama create verification-mistral -f Modelfile")
    print(f"\nSee data/finetuning/README.md for detailed instructions.")


if __name__ == '__main__':
    main()
