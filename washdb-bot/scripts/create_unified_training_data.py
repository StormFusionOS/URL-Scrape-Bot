#!/usr/bin/env python3
"""
Create Unified Training Dataset for Combined Verification + Standardization LLM

This script combines verification and standardization training data into a unified
format suitable for fine-tuning a single Mistral-7B model that can perform both tasks.

Output:
- unified_train.jsonl - Training data
- unified_val.jsonl - Validation data
- training_stats.json - Statistics about the dataset
"""

import json
import os
import random
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor

# Paths
BASE_DIR = Path("/home/rivercityscrape/URL-Scrape-Bot/washdb-bot")
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "unified_training"
OUTPUT_DIR.mkdir(exist_ok=True)

# Database connection
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "washbot_db",
    "user": "washbot",
    "password": "Washdb123"
}

# System prompts for each task
VERIFICATION_SYSTEM_PROMPT = """You are a business verification assistant. Analyze the company information and determine if it is a legitimate service provider offering exterior building and property cleaning services.

Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet washing, Wood restoration.

Respond with ONLY a valid JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": {"pressure_washing": bool, "window_cleaning": bool, "soft_washing": bool, "roof_cleaning": bool, "gutter_cleaning": bool, "solar_panel_cleaning": bool, "fleet_washing": bool, "wood_restoration": bool}, "reasoning": "brief explanation"}"""

STANDARDIZATION_SYSTEM_PROMPT = """You are a business name standardization assistant. Extract and standardize the official business name from the provided website information.

Rules:
- Extract the actual business name, not page titles or taglines
- Remove legal suffixes (LLC, Inc, Corp) unless they're part of the brand identity
- Preserve proper capitalization and spacing
- If the business name is already correct, return it unchanged

Respond with ONLY the standardized business name, nothing else."""

COMBINED_SYSTEM_PROMPT = """You are a business intelligence assistant that performs two tasks:

TASK 1 - VERIFICATION: Determine if a company is a legitimate exterior cleaning service provider.
Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet washing, Wood restoration.

TASK 2 - STANDARDIZATION: Extract and standardize the official business name.

Based on the task specified, respond with the appropriate format:
- For verification: {"legitimate": true/false, "confidence": 0.0-1.0, "services": [...], "reasoning": "..."}
- For standardization: Just the standardized business name"""


def load_verification_data() -> List[Dict]:
    """Load existing verification training data."""
    verification_data = []

    # Load balanced training data (already in messages format)
    balanced_train = DATA_DIR / "finetuning" / "balanced_train_20251209_101213.jsonl"
    balanced_val = DATA_DIR / "finetuning" / "balanced_val_20251209_101213.jsonl"

    for filepath in [balanced_train, balanced_val]:
        if filepath.exists():
            print(f"Loading verification data from {filepath}")
            with open(filepath, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if 'messages' in data:
                            # Mark as verification task
                            data['task'] = 'verification'
                            verification_data.append(data)
                    except json.JSONDecodeError:
                        continue

    print(f"Loaded {len(verification_data)} verification examples")
    return verification_data


def load_standardization_data() -> List[Dict]:
    """Load existing standardization training data and convert to messages format."""
    standardization_data = []

    # Load Claude-annotated standardization data
    std_dir = DATA_DIR / "standardization"
    if std_dir.exists():
        for filepath in std_dir.glob("*.jsonl"):
            print(f"Loading standardization data from {filepath}")
            with open(filepath, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if 'prompt' in data and 'completion' in data:
                            # Convert to messages format
                            messages = {
                                "messages": [
                                    {"role": "system", "content": STANDARDIZATION_SYSTEM_PROMPT},
                                    {"role": "user", "content": data['prompt']},
                                    {"role": "assistant", "content": data['completion']}
                                ],
                                "task": "standardization"
                            }
                            standardization_data.append(messages)
                    except json.JSONDecodeError:
                        continue

    print(f"Loaded {len(standardization_data)} standardization examples")
    return standardization_data


def load_db_examples() -> List[Dict]:
    """Load high-quality examples from database where we have both verification and standardization."""
    examples = []

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get companies that were verified AND standardized with good data
        query = """
        SELECT
            c.id, c.name, c.domain, c.website, c.phone, c.address,
            c.standardized_name, c.llm_verified, c.llm_confidence,
            c.parse_metadata
        FROM companies c
        WHERE c.llm_verified IS NOT NULL
          AND c.standardized_name IS NOT NULL
          AND c.standardized_name != ''
          AND c.standardized_name != c.name
          AND c.llm_confidence >= 0.7
        ORDER BY c.llm_confidence DESC
        LIMIT 5000
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        for row in rows:
            # Create standardization example
            user_content = f"""Extract business name:
Original: {row['name']}
Domain: {row['domain']}
Website: {row['website']}"""

            std_example = {
                "messages": [
                    {"role": "system", "content": STANDARDIZATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": row['standardized_name']}
                ],
                "task": "standardization",
                "source": "database"
            }
            examples.append(std_example)

        cursor.close()
        conn.close()

        print(f"Loaded {len(examples)} examples from database")

    except Exception as e:
        print(f"Error loading from database: {e}")

    return examples


def create_unified_dataset(
    verification_data: List[Dict],
    standardization_data: List[Dict],
    db_examples: List[Dict],
    train_ratio: float = 0.9
) -> tuple:
    """Combine all data into unified training and validation sets."""

    # Combine all data
    all_data = verification_data + standardization_data + db_examples

    # Shuffle
    random.seed(42)
    random.shuffle(all_data)

    # Split
    split_idx = int(len(all_data) * train_ratio)
    train_data = all_data[:split_idx]
    val_data = all_data[split_idx:]

    return train_data, val_data


def save_dataset(data: List[Dict], filepath: Path):
    """Save dataset in JSONL format."""
    with open(filepath, 'w') as f:
        for item in data:
            # Remove metadata fields for training, keep only messages
            output = {"messages": item["messages"]}
            f.write(json.dumps(output) + '\n')
    print(f"Saved {len(data)} examples to {filepath}")


def create_chatml_format(data: List[Dict], filepath: Path):
    """Save in ChatML format for Mistral fine-tuning."""
    with open(filepath, 'w') as f:
        for item in data:
            messages = item["messages"]
            text_parts = []

            for msg in messages:
                role = msg["role"]
                content = msg["content"]

                if role == "system":
                    text_parts.append(f"<|im_start|>system\n{content}<|im_end|>")
                elif role == "user":
                    text_parts.append(f"<|im_start|>user\n{content}<|im_end|>")
                elif role == "assistant":
                    text_parts.append(f"<|im_start|>assistant\n{content}<|im_end|>")

            text = "\n".join(text_parts)
            f.write(json.dumps({"text": text}) + '\n')

    print(f"Saved ChatML format to {filepath}")


def create_alpaca_format(data: List[Dict], filepath: Path):
    """Save in Alpaca format for compatibility with various fine-tuning frameworks."""
    with open(filepath, 'w') as f:
        for item in data:
            messages = item["messages"]

            system = ""
            instruction = ""
            output = ""

            for msg in messages:
                if msg["role"] == "system":
                    system = msg["content"]
                elif msg["role"] == "user":
                    instruction = msg["content"]
                elif msg["role"] == "assistant":
                    output = msg["content"]

            alpaca_item = {
                "instruction": instruction,
                "input": system,
                "output": output
            }
            f.write(json.dumps(alpaca_item) + '\n')

    print(f"Saved Alpaca format to {filepath}")


def generate_stats(train_data: List[Dict], val_data: List[Dict]) -> Dict:
    """Generate statistics about the dataset."""

    train_verification = len([d for d in train_data if d.get('task') == 'verification'])
    train_standardization = len([d for d in train_data if d.get('task') == 'standardization'])
    val_verification = len([d for d in val_data if d.get('task') == 'verification'])
    val_standardization = len([d for d in val_data if d.get('task') == 'standardization'])

    stats = {
        "created_at": datetime.now().isoformat(),
        "total_examples": len(train_data) + len(val_data),
        "training": {
            "total": len(train_data),
            "verification": train_verification,
            "standardization": train_standardization
        },
        "validation": {
            "total": len(val_data),
            "verification": val_verification,
            "standardization": val_standardization
        },
        "task_ratio": {
            "verification": (train_verification + val_verification) / (len(train_data) + len(val_data)),
            "standardization": (train_standardization + val_standardization) / (len(train_data) + len(val_data))
        }
    }

    return stats


def main():
    print("=" * 60)
    print("Creating Unified Training Dataset")
    print("=" * 60)
    print()

    # Load all data sources
    print("Loading verification data...")
    verification_data = load_verification_data()

    print("\nLoading standardization data...")
    standardization_data = load_standardization_data()

    print("\nLoading database examples...")
    db_examples = load_db_examples()

    # Create unified dataset
    print("\nCreating unified dataset...")
    train_data, val_data = create_unified_dataset(
        verification_data, standardization_data, db_examples
    )

    # Save in multiple formats
    print("\nSaving datasets...")

    # OpenAI messages format (primary)
    save_dataset(train_data, OUTPUT_DIR / "unified_train.jsonl")
    save_dataset(val_data, OUTPUT_DIR / "unified_val.jsonl")

    # ChatML format for Mistral
    create_chatml_format(train_data, OUTPUT_DIR / "unified_train_chatml.jsonl")
    create_chatml_format(val_data, OUTPUT_DIR / "unified_val_chatml.jsonl")

    # Alpaca format for compatibility
    create_alpaca_format(train_data, OUTPUT_DIR / "unified_train_alpaca.jsonl")
    create_alpaca_format(val_data, OUTPUT_DIR / "unified_val_alpaca.jsonl")

    # Generate and save stats
    stats = generate_stats(train_data, val_data)
    stats_path = OUTPUT_DIR / "training_stats.json"
    with open(stats_path, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"\nSaved stats to {stats_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("TRAINING DATA SUMMARY")
    print("=" * 60)
    print(f"Total examples: {stats['total_examples']}")
    print(f"\nTraining set: {stats['training']['total']}")
    print(f"  - Verification: {stats['training']['verification']}")
    print(f"  - Standardization: {stats['training']['standardization']}")
    print(f"\nValidation set: {stats['validation']['total']}")
    print(f"  - Verification: {stats['validation']['verification']}")
    print(f"  - Standardization: {stats['validation']['standardization']}")
    print(f"\nOutput directory: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
