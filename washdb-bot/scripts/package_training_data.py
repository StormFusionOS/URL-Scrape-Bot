#!/usr/bin/env python3
"""
Package Training Data for RunPod

Combines all training data sources into final training package:
1. Original unified training data
2. Enhanced data with hard negatives
3. Validation split
4. Creates ChatML format for Mistral fine-tuning

Output:
- final_train.jsonl - Training data (ChatML format)
- final_val.jsonl - Validation data (ChatML format)
- package_stats.json - Statistics
"""

import json
import random
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# Paths
BASE_DIR = Path("/home/rivercityscrape/URL-Scrape-Bot/washdb-bot")
DATA_DIR = BASE_DIR / "data"
UNIFIED_DIR = DATA_DIR / "unified_training"
ENHANCED_DIR = DATA_DIR / "enhanced_training"
FINAL_DIR = DATA_DIR / "final_training"
FINAL_DIR.mkdir(exist_ok=True)


def load_jsonl(filepath: Path) -> List[Dict]:
    """Load JSONL file."""
    examples = []
    if filepath.exists():
        with open(filepath, 'r') as f:
            for line in f:
                try:
                    examples.append(json.loads(line.strip()))
                except:
                    continue
    return examples


def to_chatml(example: Dict) -> str:
    """Convert example to ChatML format."""
    messages = example.get('messages', [])
    text_parts = []

    for msg in messages:
        role = msg.get('role', '')
        content = msg.get('content', '')

        if role == "system":
            text_parts.append(f"<|im_start|>system\n{content}<|im_end|>")
        elif role == "user":
            text_parts.append(f"<|im_start|>user\n{content}<|im_end|>")
        elif role == "assistant":
            text_parts.append(f"<|im_start|>assistant\n{content}<|im_end|>")

    return "\n".join(text_parts)


def main():
    print("=" * 60)
    print("PACKAGING FINAL TRAINING DATA")
    print("=" * 60)
    print()

    all_examples = []

    # Load enhanced training data (includes hard negatives)
    print("Loading enhanced training data...")
    enhanced_file = ENHANCED_DIR / "enhanced_train.jsonl"
    if enhanced_file.exists():
        enhanced = load_jsonl(enhanced_file)
        print(f"  Loaded {len(enhanced)} enhanced examples")
        all_examples.extend(enhanced)
    else:
        # Fall back to original unified data
        print("  Enhanced data not found, loading original...")
        unified_file = UNIFIED_DIR / "unified_train.jsonl"
        unified = load_jsonl(unified_file)
        print(f"  Loaded {len(unified)} unified examples")
        all_examples.extend(unified)

    # Load original validation data
    print("Loading validation data...")
    val_file = UNIFIED_DIR / "unified_val.jsonl"
    val_examples = load_jsonl(val_file)
    print(f"  Loaded {len(val_examples)} validation examples")

    # Shuffle training data
    print("\nShuffling and preparing data...")
    random.seed(42)
    random.shuffle(all_examples)

    # Count tasks
    verif_count = sum(1 for ex in all_examples if ex.get('task') == 'verification' or 'legitimate' in str(ex))
    std_count = len(all_examples) - verif_count

    print(f"  Training: {len(all_examples)} total")
    print(f"    - Verification: ~{verif_count}")
    print(f"    - Standardization: ~{std_count}")
    print(f"  Validation: {len(val_examples)} total")

    # Convert to ChatML and save
    print("\nSaving in ChatML format...")

    # Training data
    train_output = FINAL_DIR / "final_train.jsonl"
    with open(train_output, 'w') as f:
        for ex in all_examples:
            chatml = to_chatml(ex)
            if chatml:  # Skip empty
                f.write(json.dumps({"text": chatml}) + '\n')
    print(f"  Saved: {train_output}")

    # Validation data
    val_output = FINAL_DIR / "final_val.jsonl"
    with open(val_output, 'w') as f:
        for ex in val_examples:
            chatml = to_chatml(ex)
            if chatml:
                f.write(json.dumps({"text": chatml}) + '\n')
    print(f"  Saved: {val_output}")

    # Also save in messages format (for compatibility)
    train_msg = FINAL_DIR / "final_train_messages.jsonl"
    with open(train_msg, 'w') as f:
        for ex in all_examples:
            f.write(json.dumps({"messages": ex.get("messages", [])}) + '\n')

    val_msg = FINAL_DIR / "final_val_messages.jsonl"
    with open(val_msg, 'w') as f:
        for ex in val_examples:
            f.write(json.dumps({"messages": ex.get("messages", [])}) + '\n')

    # Save stats
    stats = {
        "created_at": datetime.now().isoformat(),
        "training_examples": len(all_examples),
        "validation_examples": len(val_examples),
        "total_examples": len(all_examples) + len(val_examples),
        "estimated_verification": verif_count,
        "estimated_standardization": std_count,
        "files": {
            "train_chatml": str(train_output),
            "val_chatml": str(val_output),
            "train_messages": str(train_msg),
            "val_messages": str(val_msg),
        }
    }

    stats_file = FINAL_DIR / "package_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)

    # Print file sizes
    print("\nFile sizes:")
    for f in FINAL_DIR.glob("*.jsonl"):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name}: {size_mb:.1f} MB")

    print("\n" + "=" * 60)
    print("PACKAGING COMPLETE")
    print("=" * 60)
    print(f"\nTotal training examples: {stats['training_examples']}")
    print(f"Total validation examples: {stats['validation_examples']}")
    print(f"\nOutput directory: {FINAL_DIR}")
    print("\nReady for RunPod training!")
    print("Upload these files to RunPod:")
    print(f"  - {train_output.name}")
    print(f"  - {val_output.name}")


if __name__ == "__main__":
    main()
