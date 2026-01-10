#!/usr/bin/env python3
"""
Create Final Combined Dataset for Training

Combines:
1. Existing enhanced training data (27,008 examples)
2. New enriched examples with website content (30,838 examples)

Deduplicates and creates proper train/val splits.
"""

import json
import hashlib
import random
from pathlib import Path
from typing import Dict, List, Set

BASE_DIR = Path("/home/rivercityscrape/URL-Scrape-Bot/washdb-bot")
DATA_DIR = BASE_DIR / "data"

# Input files
EXISTING_TRAIN = DATA_DIR / "final_training" / "final_train.jsonl"
EXISTING_VAL = DATA_DIR / "final_training" / "final_val.jsonl"
ENRICHED = DATA_DIR / "enriched_training" / "enriched_examples_fast.jsonl"

# Output directory
OUTPUT_DIR = DATA_DIR / "combined_training"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_jsonl(filepath: Path) -> List[Dict]:
    """Load JSONL file."""
    examples = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    examples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return examples


def get_content_hash(example: Dict) -> str:
    """Create hash of example content for deduplication."""
    messages = example.get('messages', [])
    if len(messages) >= 2:
        # Hash user message (the actual content)
        user_content = messages[1].get('content', '')[:500]
        return hashlib.md5(user_content.encode()).hexdigest()
    return hashlib.md5(json.dumps(example).encode()).hexdigest()


def extract_company_info(example: Dict) -> str:
    """Extract company identifier from example."""
    messages = example.get('messages', [])
    if len(messages) >= 2:
        user_content = messages[1].get('content', '')
        # Try to extract company name
        for line in user_content.split('\n'):
            if line.startswith('Company:') or line.startswith('Original Name:'):
                return line.split(':', 1)[1].strip()[:100]
    return ""


def main():
    print("=" * 60)
    print("CREATING FINAL COMBINED DATASET")
    print("=" * 60)

    # Load all data sources
    print("\n1. Loading existing training data...")
    existing_train = load_jsonl(EXISTING_TRAIN)
    existing_val = load_jsonl(EXISTING_VAL)
    print(f"   Existing train: {len(existing_train):,}")
    print(f"   Existing val: {len(existing_val):,}")

    print("\n2. Loading enriched examples...")
    enriched = load_jsonl(ENRICHED)
    print(f"   Enriched examples: {len(enriched):,}")

    # Combine all examples
    all_examples = existing_train + existing_val + enriched
    print(f"\n3. Total before deduplication: {len(all_examples):,}")

    # Deduplicate using content hash
    print("\n4. Deduplicating...")
    seen_hashes: Set[str] = set()
    unique_examples = []

    # Prioritize enriched examples (they have website content)
    # Process enriched first, then existing
    for example in enriched:
        content_hash = get_content_hash(example)
        if content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            unique_examples.append(example)

    enriched_count = len(unique_examples)

    for example in existing_train + existing_val:
        content_hash = get_content_hash(example)
        if content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            unique_examples.append(example)

    print(f"   Unique examples: {len(unique_examples):,}")
    print(f"   Duplicates removed: {len(all_examples) - len(unique_examples):,}")
    print(f"   Enriched (prioritized): {enriched_count:,}")
    print(f"   Existing (non-duplicated): {len(unique_examples) - enriched_count:,}")

    # Shuffle for training
    random.seed(42)
    random.shuffle(unique_examples)

    # Count by task type
    task_counts = {}
    for ex in unique_examples:
        task = ex.get('task', 'unknown')
        task_counts[task] = task_counts.get(task, 0) + 1

    print("\n5. Task distribution:")
    for task, count in sorted(task_counts.items()):
        print(f"   {task}: {count:,} ({100*count/len(unique_examples):.1f}%)")

    # Split into train/val (90/10)
    split_idx = int(len(unique_examples) * 0.9)
    train_examples = unique_examples[:split_idx]
    val_examples = unique_examples[split_idx:]

    print(f"\n6. Train/Val split:")
    print(f"   Train: {len(train_examples):,}")
    print(f"   Val: {len(val_examples):,}")

    # Save combined dataset
    print("\n7. Saving combined dataset...")

    train_file = OUTPUT_DIR / "combined_train.jsonl"
    val_file = OUTPUT_DIR / "combined_val.jsonl"

    with open(train_file, 'w') as f:
        for example in train_examples:
            f.write(json.dumps(example) + '\n')

    with open(val_file, 'w') as f:
        for example in val_examples:
            f.write(json.dumps(example) + '\n')

    # Calculate sizes
    train_size = train_file.stat().st_size / (1024 * 1024)
    val_size = val_file.stat().st_size / (1024 * 1024)

    print(f"   {train_file.name}: {train_size:.1f} MB")
    print(f"   {val_file.name}: {val_size:.1f} MB")

    # Save stats
    stats = {
        "total_examples": len(unique_examples),
        "train_examples": len(train_examples),
        "val_examples": len(val_examples),
        "task_distribution": task_counts,
        "sources": {
            "existing_train": len(existing_train),
            "existing_val": len(existing_val),
            "enriched": len(enriched),
            "duplicates_removed": len(all_examples) - len(unique_examples)
        },
        "file_sizes_mb": {
            "train": round(train_size, 2),
            "val": round(val_size, 2)
        }
    }

    with open(OUTPUT_DIR / "combined_stats.json", 'w') as f:
        json.dump(stats, f, indent=2)

    print("\n" + "=" * 60)
    print("FINAL DATASET READY!")
    print("=" * 60)
    print(f"\nTotal training examples: {len(train_examples):,}")
    print(f"Total validation examples: {len(val_examples):,}")
    print(f"\nFiles created in: {OUTPUT_DIR}")
    print("\nReady for RunPod training!")


if __name__ == "__main__":
    main()
