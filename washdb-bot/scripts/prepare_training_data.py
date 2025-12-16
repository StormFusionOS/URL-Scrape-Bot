#!/usr/bin/env python3
"""
Prepare Training Data for Verification LLM Fine-tuning

This script prepares training data in formats suitable for:
1. Ollama fine-tuning (JSONL with prompt/response pairs)
2. OpenAI-style fine-tuning (JSONL with messages)
3. Raw CSV for manual review

Usage:
    # From Claude-annotated CSV (after you get Claude to annotate the data):
    python scripts/prepare_training_data.py --input annotated_data.csv --output training_data.jsonl

    # Generate sample format for Claude annotation:
    python scripts/prepare_training_data.py --generate-template --limit 500

    # Convert existing standardized data to training format:
    python scripts/prepare_training_data.py --from-db --limit 1000
"""

import os
import sys
import json
import csv
import argparse
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text


# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data" / "training"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_engine():
    return create_engine(os.getenv('DATABASE_URL'))


def generate_template_for_claude(limit: int = 500):
    """
    Generate a CSV template for Claude to annotate with business names.

    This creates a file you can give to Claude with the prompt:
    "For each row, extract the business name from the title and provide reasoning."
    """
    engine = get_engine()

    with engine.connect() as conn:
        # Get companies with domains that haven't been standardized
        result = conn.execute(text('''
            SELECT id, name, domain
            FROM companies
            WHERE domain IS NOT NULL
            AND domain != ''
            AND verified = TRUE
            ORDER BY RANDOM()
            LIMIT :limit
        '''), {'limit': limit})

        companies = [dict(row._mapping) for row in result]

    output_file = DATA_DIR / f"for_claude_annotation_{datetime.now():%Y%m%d_%H%M%S}.csv"

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'id', 'domain', 'url', 'title', 'yp_name',
            'extracted_name', 'reasoning', 'confidence'
        ])
        writer.writeheader()

        for company in companies:
            writer.writerow({
                'id': company['id'],
                'domain': company['domain'],
                'url': f"https://{company['domain']}",
                'title': '',  # To be filled by fetching or Claude
                'yp_name': company['name'],
                'extracted_name': '',  # Claude fills this
                'reasoning': '',  # Claude fills this
                'confidence': ''  # Claude fills this
            })

    print(f"Generated template: {output_file}")
    print(f"Contains {len(companies)} companies")
    print()
    print("Next steps:")
    print("1. Fetch titles for these URLs (or have Claude fetch them)")
    print("2. Give the CSV to Claude with this prompt:")
    print()
    print('   "For each row in this CSV, look at the website title and extract')
    print('   the business name. Fill in extracted_name, reasoning, and confidence.')
    print('   Return the completed CSV."')

    return output_file


def convert_annotated_csv_to_training(input_file: str, output_file: str = None):
    """
    Convert Claude-annotated CSV to training JSONL format.

    Expected CSV columns: title, domain, extracted_name
    """
    if output_file is None:
        output_file = DATA_DIR / f"training_data_{datetime.now():%Y%m%d_%H%M%S}.jsonl"

    training_samples = []

    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get('title', '').strip()
            domain = row.get('domain', '').strip()
            extracted_name = row.get('extracted_name', '').strip()

            if not title or not extracted_name:
                continue

            # Create training sample
            sample = {
                "prompt": f'Title: "{title}"\nDomain: {domain}\nExtract the business name:',
                "completion": extracted_name
            }
            training_samples.append(sample)

    # Write JSONL
    with open(output_file, 'w', encoding='utf-8') as f:
        for sample in training_samples:
            f.write(json.dumps(sample) + '\n')

    print(f"Created training file: {output_file}")
    print(f"Total samples: {len(training_samples)}")

    return output_file


def convert_db_standardized_to_training(limit: int = 1000):
    """
    Convert already-standardized database entries to training format.

    Uses entries where standardized_name was set by LLM with high confidence.
    """
    engine = get_engine()

    with engine.connect() as conn:
        # Get successfully standardized entries
        result = conn.execute(text('''
            SELECT
                name as yp_name,
                domain,
                standardized_name,
                standardized_name_source,
                standardized_name_confidence
            FROM companies
            WHERE standardized_name IS NOT NULL
            AND standardized_name != name
            AND standardized_name_confidence >= 0.85
            AND domain IS NOT NULL
            ORDER BY standardized_at DESC
            LIMIT :limit
        '''), {'limit': limit})

        rows = [dict(row._mapping) for row in result]

    if not rows:
        print("No standardized entries found in database")
        return None

    output_file = DATA_DIR / f"db_training_data_{datetime.now():%Y%m%d_%H%M%S}.jsonl"

    training_samples = []
    for row in rows:
        # Note: We don't have the actual title, so we create a synthetic prompt
        # This is less ideal than having actual titles
        sample = {
            "prompt": f'Domain: {row["domain"]}\nYellowPages name: "{row["yp_name"]}"\nExtract the correct business name:',
            "completion": row["standardized_name"],
            "metadata": {
                "source": row["standardized_name_source"],
                "confidence": float(row["standardized_name_confidence"]) if row["standardized_name_confidence"] else 0
            }
        }
        training_samples.append(sample)

    with open(output_file, 'w', encoding='utf-8') as f:
        for sample in training_samples:
            f.write(json.dumps(sample) + '\n')

    print(f"Created training file: {output_file}")
    print(f"Total samples: {len(training_samples)}")

    return output_file


def create_openai_format(input_jsonl: str, output_file: str = None):
    """
    Convert simple prompt/completion JSONL to OpenAI fine-tuning format.
    """
    if output_file is None:
        output_file = str(input_jsonl).replace('.jsonl', '_openai.jsonl')

    system_message = """You are a business name extraction specialist. Extract the complete business name from the given website title. Return ONLY the business name, or NONE if no clear business name exists."""

    samples = []
    with open(input_jsonl, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)

            openai_sample = {
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": data["prompt"]},
                    {"role": "assistant", "content": data["completion"]}
                ]
            }
            samples.append(openai_sample)

    with open(output_file, 'w', encoding='utf-8') as f:
        for sample in samples:
            f.write(json.dumps(sample) + '\n')

    print(f"Created OpenAI format: {output_file}")
    print(f"Total samples: {len(samples)}")

    return output_file


def main():
    parser = argparse.ArgumentParser(description='Prepare training data for Verification LLM')
    parser.add_argument('--generate-template', action='store_true',
                       help='Generate CSV template for Claude annotation')
    parser.add_argument('--from-db', action='store_true',
                       help='Generate training data from existing DB standardizations')
    parser.add_argument('--input', type=str,
                       help='Input CSV file (Claude-annotated)')
    parser.add_argument('--output', type=str,
                       help='Output file path')
    parser.add_argument('--limit', type=int, default=500,
                       help='Number of samples to generate')
    parser.add_argument('--openai-format', type=str,
                       help='Convert JSONL to OpenAI fine-tuning format')

    args = parser.parse_args()

    if args.generate_template:
        generate_template_for_claude(args.limit)
    elif args.from_db:
        convert_db_standardized_to_training(args.limit)
    elif args.input:
        convert_annotated_csv_to_training(args.input, args.output)
    elif args.openai_format:
        create_openai_format(args.openai_format, args.output)
    else:
        parser.print_help()
        print()
        print("Examples:")
        print("  # Generate template for Claude to annotate:")
        print("  python scripts/prepare_training_data.py --generate-template --limit 500")
        print()
        print("  # Convert Claude-annotated CSV to training format:")
        print("  python scripts/prepare_training_data.py --input annotated.csv")
        print()
        print("  # Use existing DB data for training:")
        print("  python scripts/prepare_training_data.py --from-db --limit 1000")


if __name__ == '__main__':
    main()
