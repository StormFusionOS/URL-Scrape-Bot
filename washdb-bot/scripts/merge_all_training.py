#!/usr/bin/env python3
"""
Merge ALL training sources into one comprehensive dataset.
Deduplicates and combines all available training data.
"""

import json
import os
import sys
import hashlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

OUTPUT_DIR = Path("data/final_comprehensive")
OUTPUT_DIR.mkdir(exist_ok=True)

def get_text_hash(text):
    """Get hash of text for deduplication."""
    return hashlib.md5(text.encode()).hexdigest()

def load_jsonl(filepath):
    """Load JSONL file."""
    examples = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    examples.append(data)
                except:
                    pass
    except Exception as e:
        print(f"  Warning: Could not load {filepath}: {e}")
    return examples

def main():
    print("=" * 60)
    print("MERGE ALL TRAINING SOURCES")
    print("=" * 60)
    
    data_dir = Path("data")
    
    # All training source files
    source_files = [
        # Database export (comprehensive)
        data_dir / "comprehensive_training/comprehensive_train.jsonl",
        
        # Previous combined/enriched data (may have richer Claude responses)
        data_dir / "combined_training/combined_train.jsonl",
        data_dir / "enriched_training/enriched_examples_fast.jsonl",
        data_dir / "enhanced_training/enhanced_train.jsonl",
        data_dir / "enhanced_training/hard_negatives.jsonl",
        
        # Finetuning data
        data_dir / "finetuning/verification_finetuning_20251207_093643.jsonl",
        
        # Unified training
        data_dir / "unified_training/unified_train.jsonl",
        
        # Standardization specific
        data_dir / "standardization/claude_standardization_20251209_112408.jsonl",
        
        # Original verification training
        data_dir / "verification_training.jsonl",
    ]
    
    # Validation files
    val_files = [
        data_dir / "comprehensive_training/comprehensive_val.jsonl",
        data_dir / "combined_training/combined_val.jsonl",
        data_dir / "unified_training/unified_val.jsonl",
    ]
    
    all_examples = []
    seen_hashes = set()
    source_counts = {}
    
    print("\nLoading training sources...")
    for filepath in source_files:
        if filepath.exists():
            examples = load_jsonl(filepath)
            added = 0
            for ex in examples:
                text = ex.get('text', '')
                if not text:
                    continue
                h = get_text_hash(text)
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    all_examples.append(ex)
                    added += 1
            source_counts[filepath.name] = {'loaded': len(examples), 'added': added}
            print(f"  {filepath.name}: {len(examples):,} loaded, {added:,} unique added")
        else:
            print(f"  {filepath.name}: NOT FOUND")
    
    # Load validation
    val_examples = []
    val_hashes = set()
    
    print("\nLoading validation sources...")
    for filepath in val_files:
        if filepath.exists():
            examples = load_jsonl(filepath)
            added = 0
            for ex in examples:
                text = ex.get('text', '')
                if not text:
                    continue
                h = get_text_hash(text)
                if h not in val_hashes and h not in seen_hashes:  # Not in train either
                    val_hashes.add(h)
                    val_examples.append(ex)
                    added += 1
            print(f"  {filepath.name}: {len(examples):,} loaded, {added:,} unique added")
    
    print(f"\nTotal unique training examples: {len(all_examples):,}")
    print(f"Total unique validation examples: {len(val_examples):,}")
    
    # Shuffle training
    import random
    random.seed(42)
    random.shuffle(all_examples)
    
    # If validation is too small, split some from training
    target_val_ratio = 0.10
    if len(val_examples) < len(all_examples) * target_val_ratio * 0.5:
        print("\nAugmenting validation set from training...")
        split_idx = int(len(all_examples) * (1 - target_val_ratio))
        val_examples = val_examples + all_examples[split_idx:]
        all_examples = all_examples[:split_idx]
        print(f"  New training: {len(all_examples):,}")
        print(f"  New validation: {len(val_examples):,}")
    
    # Write final files
    train_file = OUTPUT_DIR / "train.jsonl"
    val_file = OUTPUT_DIR / "val.jsonl"
    
    print(f"\nWriting files...")
    with open(train_file, 'w') as f:
        for ex in all_examples:
            f.write(json.dumps(ex) + '\n')
    
    with open(val_file, 'w') as f:
        for ex in val_examples:
            f.write(json.dumps(ex) + '\n')
    
    # Stats
    stats = {
        "created_at": datetime.now().isoformat(),
        "total_examples": len(all_examples) + len(val_examples),
        "train_examples": len(all_examples),
        "val_examples": len(val_examples),
        "train_file_mb": os.path.getsize(train_file) / 1024 / 1024,
        "val_file_mb": os.path.getsize(val_file) / 1024 / 1024,
        "sources": {k: v for k, v in source_counts.items()},
        "duplicates_removed": sum(v['loaded'] - v['added'] for v in source_counts.values()),
    }
    
    with open(OUTPUT_DIR / "stats.json", 'w') as f:
        json.dump(stats, f, indent=2)
    
    print(f"\n" + "=" * 60)
    print("FINAL MERGED DATASET")
    print("=" * 60)
    print(f"  Training examples: {stats['train_examples']:,}")
    print(f"  Validation examples: {stats['val_examples']:,}")
    print(f"  Total: {stats['total_examples']:,}")
    print(f"  Train file: {stats['train_file_mb']:.1f} MB")
    print(f"  Val file: {stats['val_file_mb']:.1f} MB")
    print(f"  Duplicates removed: {stats['duplicates_removed']:,}")
    print(f"\nFiles saved to: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
