#!/usr/bin/env python3
"""
Clean training data by removing garbage examples.
"""

import json
import os
from pathlib import Path

INPUT_DIR = Path("data/full_reasoning_training")
OUTPUT_DIR = Path("data/cleaned_training")
OUTPUT_DIR.mkdir(exist_ok=True)

# Garbage patterns to filter out
GARBAGE_RESPONSES = [
    "Forbidden<|im_end|>",
    "Not Found<|im_end|>",
    "Access Denied<|im_end|>",
    "403 Forbidden<|im_end|>",
    "404 Not Found<|im_end|>",
    "Error<|im_end|>",
    "Blocked<|im_end|>",
    "None<|im_end|>",
    "null<|im_end|>",
    "N/A<|im_end|>",
]

# Patterns indicating low-quality standardization (response too short or garbage)
def is_garbage_standardization(text):
    """Check if standardization example is garbage."""
    if "standardization assistant" not in text:
        return False

    # Extract assistant response
    try:
        assistant_part = text.split("<|im_start|>assistant\n")[-1]
        response = assistant_part.split("<|im_end|>")[0].strip()

        # Too short (less than 2 chars)
        if len(response) < 2:
            return True

        # Known garbage responses
        garbage_names = ["forbidden", "not found", "access denied", "error", "none", "null", "n/a", "blocked"]
        if response.lower() in garbage_names:
            return True

        return False
    except:
        return False

def is_low_quality_verification(text):
    """Check if verification example has very low quality."""
    if "verification assistant" not in text:
        return False

    try:
        assistant_part = text.split("<|im_start|>assistant\n")[-1]
        response = assistant_part.split("<|im_end|>")[0].strip()

        # Try to parse JSON
        data = json.loads(response)

        # Low confidence + legitimate is contradictory training signal
        if data.get("legitimate") == True and data.get("confidence", 1.0) < 0.3:
            return True

        # Empty or very short reasoning
        reasoning = data.get("reasoning", "")
        if len(reasoning) < 10:
            return True

        return False
    except:
        return False

def clean_file(input_path, output_path):
    """Clean a single JSONL file."""
    kept = 0
    removed_garbage = 0
    removed_low_quality = 0

    with open(input_path, 'r') as fin, open(output_path, 'w') as fout:
        for line in fin:
            try:
                data = json.loads(line.strip())
                text = data.get("text", "")

                # Check for garbage responses
                is_garbage = any(g in text for g in GARBAGE_RESPONSES)
                if is_garbage:
                    removed_garbage += 1
                    continue

                # Check for garbage standardization
                if is_garbage_standardization(text):
                    removed_garbage += 1
                    continue

                # Check for low quality verification
                if is_low_quality_verification(text):
                    removed_low_quality += 1
                    continue

                # Keep this example
                fout.write(line)
                kept += 1

            except Exception as e:
                removed_garbage += 1
                continue

    return kept, removed_garbage, removed_low_quality

def main():
    print("=" * 60)
    print("CLEANING TRAINING DATA")
    print("=" * 60)

    total_kept = 0
    total_garbage = 0
    total_low_quality = 0

    for filename in ["train.jsonl", "val.jsonl"]:
        input_path = INPUT_DIR / filename
        output_path = OUTPUT_DIR / filename

        if not input_path.exists():
            print(f"Skipping {filename} - not found")
            continue

        print(f"\nProcessing {filename}...")
        kept, garbage, low_quality = clean_file(input_path, output_path)

        total_kept += kept
        total_garbage += garbage
        total_low_quality += low_quality

        print(f"  Kept: {kept:,}")
        print(f"  Removed (garbage): {garbage:,}")
        print(f"  Removed (low quality): {low_quality:,}")

    # Copy stats and update
    stats = {
        "original_train": 183199,
        "original_val": 20356,
        "cleaned_total": total_kept,
        "removed_garbage": total_garbage,
        "removed_low_quality": total_low_quality,
    }

    with open(OUTPUT_DIR / "stats.json", 'w') as f:
        json.dump(stats, f, indent=2)

    print("\n" + "=" * 60)
    print("CLEANING COMPLETE")
    print("=" * 60)
    print(f"Total kept: {total_kept:,}")
    print(f"Total removed: {total_garbage + total_low_quality:,}")
    print(f"  - Garbage responses: {total_garbage:,}")
    print(f"  - Low quality: {total_low_quality:,}")
    print(f"\nOutput: {OUTPUT_DIR}")

    # Show file sizes
    for f in OUTPUT_DIR.glob("*.jsonl"):
        size_mb = os.path.getsize(f) / 1024 / 1024
        print(f"  {f.name}: {size_mb:.1f} MB")

if __name__ == "__main__":
    main()
