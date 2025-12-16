#!/usr/bin/env python3
"""
Prepare standardization training data for RunPod fine-tuning.
Combines:
1. 1,000 heavy annotated samples (with reasoning)
2. 14k+ Claude standardization pairs from database
"""

import json
import os
import random
from pathlib import Path
from datetime import datetime

# Paths
DATA_DIR = Path(__file__).parent.parent / 'data'
TRAINING_DIR = DATA_DIR / 'training'
STANDARDIZATION_DIR = DATA_DIR / 'standardization'
OUTPUT_DIR = Path('/home/rivercityscrape/runpod-standardization')

# System prompt for standardization
SYSTEM_PROMPT = """You are a business name standardization assistant. Your task is to clean and standardize company names.

Rules for standardization:
1. Remove legal suffixes: LLC, Inc, Inc., Corp, Corporation, Ltd, Limited, Co, Company, LP, LLP
2. Fix capitalization: Use proper title case (e.g., "ABC CLEANING" -> "ABC Cleaning")
3. Keep location indicators if part of the brand (e.g., "Austin Pressure Washing")
4. Remove trailing punctuation
5. Preserve abbreviations that are part of the brand (e.g., "A&B Services" stays as is)
6. Remove redundant words like "The" at the start unless it's part of the official brand

Output ONLY the standardized name, nothing else."""


def load_annotated_samples():
    """Load the 1,000 heavy annotated samples with reasoning."""
    annotated_file = TRAINING_DIR / 'claude_annotated_training_20251208_173534.jsonl'

    samples = []
    if annotated_file.exists():
        with open(annotated_file) as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    # Extract name from prompt
                    prompt = data.get('prompt', '')
                    if 'YellowPages Name:' in prompt:
                        # Parse: YellowPages Name: "Company Name"\nDomain: example.com
                        import re
                        match = re.search(r'YellowPages Name: "([^"]+)"', prompt)
                        if match:
                            original_name = match.group(1)
                            standardized_name = data.get('completion', '').strip()

                            # Get metadata
                            meta = data.get('metadata', {})
                            reasoning = meta.get('reasoning', '')
                            label = meta.get('label', '')

                            if original_name and standardized_name:
                                samples.append({
                                    'original': original_name,
                                    'standardized': standardized_name,
                                    'reasoning': reasoning,
                                    'label': label,
                                    'source': 'annotated',
                                    'weight': 3  # Higher weight for annotated samples
                                })
                except Exception as e:
                    continue

    print(f"Loaded {len(samples)} annotated samples")
    return samples


def load_standardization_pairs():
    """Load Claude standardization pairs from JSONL files."""
    samples = []

    for jsonl_file in STANDARDIZATION_DIR.glob('*.jsonl'):
        with open(jsonl_file) as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    original = data.get('original_name', '') or data.get('name', '')
                    standardized = data.get('standardized_name', '') or data.get('standardized', '')

                    if original and standardized and original != standardized:
                        samples.append({
                            'original': original,
                            'standardized': standardized,
                            'reasoning': '',
                            'label': '',
                            'source': 'claude_batch',
                            'weight': 1
                        })
                except Exception as e:
                    continue

    print(f"Loaded {len(samples)} standardization pairs from JSONL files")
    return samples


def load_db_standardization_pairs():
    """Load standardization pairs directly from database."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from sqlalchemy import create_engine, text

        engine = create_engine(os.getenv('DATABASE_URL'))

        samples = []
        with engine.connect() as conn:
            result = conn.execute(text('''
                SELECT name, standardized_name, standardized_name_source
                FROM companies
                WHERE standardized_name IS NOT NULL
                AND name != standardized_name
                AND standardized_name_source = 'claude'
            '''))

            for row in result:
                samples.append({
                    'original': row[0],
                    'standardized': row[1],
                    'reasoning': '',
                    'label': '',
                    'source': 'db_claude',
                    'weight': 1
                })

        print(f"Loaded {len(samples)} standardization pairs from database")
        return samples
    except Exception as e:
        print(f"Error loading from DB: {e}")
        return []


def format_training_sample(sample, include_reasoning=False):
    """Format a sample for Mistral instruction fine-tuning."""
    original = sample['original']
    standardized = sample['standardized']

    if include_reasoning and sample.get('reasoning'):
        # Include reasoning in the response for high-quality samples
        user_content = f"Standardize this business name: {original}"
        assistant_content = standardized
    else:
        user_content = f"Standardize this business name: {original}"
        assistant_content = standardized

    # Mistral Instruct format
    formatted = f"<s>[INST] {SYSTEM_PROMPT}\n\n{user_content} [/INST] {assistant_content}</s>"

    return {
        'text': formatted,
        'original': original,
        'standardized': standardized
    }


def create_training_dataset():
    """Create the combined training dataset."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load all data sources
    annotated = load_annotated_samples()
    jsonl_pairs = load_standardization_pairs()
    db_pairs = load_db_standardization_pairs()

    # Combine and deduplicate
    all_samples = []
    seen = set()

    # Add annotated samples first (highest priority)
    for sample in annotated:
        key = (sample['original'].lower(), sample['standardized'].lower())
        if key not in seen:
            seen.add(key)
            all_samples.append(sample)

    # Add JSONL pairs
    for sample in jsonl_pairs:
        key = (sample['original'].lower(), sample['standardized'].lower())
        if key not in seen:
            seen.add(key)
            all_samples.append(sample)

    # Add DB pairs
    for sample in db_pairs:
        key = (sample['original'].lower(), sample['standardized'].lower())
        if key not in seen:
            seen.add(key)
            all_samples.append(sample)

    print(f"\nTotal unique samples: {len(all_samples)}")
    print(f"  - Annotated (high quality): {sum(1 for s in all_samples if s['source'] == 'annotated')}")
    print(f"  - JSONL pairs: {sum(1 for s in all_samples if s['source'] == 'claude_batch')}")
    print(f"  - DB pairs: {sum(1 for s in all_samples if s['source'] == 'db_claude')}")

    # Expand samples based on weight (oversample high-quality)
    weighted_samples = []
    for sample in all_samples:
        for _ in range(sample.get('weight', 1)):
            weighted_samples.append(sample)

    # Shuffle
    random.shuffle(weighted_samples)

    # Format for training
    training_data = []
    for sample in weighted_samples:
        formatted = format_training_sample(sample)
        training_data.append(formatted)

    # Split into train/val (95/5)
    split_idx = int(len(training_data) * 0.95)
    train_data = training_data[:split_idx]
    val_data = training_data[split_idx:]

    # Save training data
    train_file = OUTPUT_DIR / 'standardization_train.jsonl'
    with open(train_file, 'w') as f:
        for item in train_data:
            f.write(json.dumps({'text': item['text']}) + '\n')

    # Save validation data
    val_file = OUTPUT_DIR / 'standardization_val.jsonl'
    with open(val_file, 'w') as f:
        for item in val_data:
            f.write(json.dumps({'text': item['text']}) + '\n')

    # Save raw pairs for reference
    pairs_file = OUTPUT_DIR / 'standardization_pairs.json'
    with open(pairs_file, 'w') as f:
        json.dump([{'original': s['original'], 'standardized': s['standardized']}
                   for s in all_samples], f, indent=2)

    print(f"\nSaved training data:")
    print(f"  - Train: {train_file} ({len(train_data)} samples)")
    print(f"  - Val: {val_file} ({len(val_data)} samples)")
    print(f"  - Pairs: {pairs_file}")

    # Create training config for RunPod
    config = {
        'model_name': 'unsloth/mistral-7b-v0.3-bnb-4bit',
        'output_name': 'standardization-mistral',
        'train_file': str(train_file),
        'val_file': str(val_file),
        'epochs': 3,
        'batch_size': 4,
        'learning_rate': 2e-4,
        'lora_r': 16,
        'lora_alpha': 16,
        'max_seq_length': 512,
        'total_samples': len(all_samples),
        'weighted_samples': len(weighted_samples),
        'created_at': datetime.now().isoformat()
    }

    config_file = OUTPUT_DIR / 'training_config.json'
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"  - Config: {config_file}")

    return OUTPUT_DIR


if __name__ == '__main__':
    output_dir = create_training_dataset()
    print(f"\n=== Training data ready in {output_dir} ===")
    print("\nTo train on RunPod:")
    print("1. Upload this directory to RunPod")
    print("2. Run the training script with these files")
