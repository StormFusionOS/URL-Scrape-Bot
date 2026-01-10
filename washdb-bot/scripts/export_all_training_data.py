#!/usr/bin/env python3
"""
Export ALL available training data from database, including failures.
Creates comprehensive training dataset for fine-tuning.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import get_db_manager
from sqlalchemy import text

OUTPUT_DIR = Path("data/comprehensive_training")
OUTPUT_DIR.mkdir(exist_ok=True)

def get_verification_prompt(company_data):
    """Generate verification training example."""
    system = """You are a business verification assistant. Your task is to determine if a company is a legitimate service provider that offers exterior building and property cleaning services.

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
- reason: Brief explanation"""

    user = f"""Company: {company_data['name']}
Website: {company_data.get('website', 'N/A')}
Domain: {company_data.get('domain', 'N/A')}
Phone: {company_data.get('phone', 'N/A')}
Address: {company_data.get('address', 'N/A')}
Services: {company_data.get('services', 'N/A')}

Is this a legitimate exterior cleaning service provider?"""

    # Determine the response based on verification result
    verified = company_data.get('verified')
    verification_type = company_data.get('verification_type', '')
    
    if verified is True:
        response = json.dumps({
            "legitimate": True,
            "confidence": 0.85,
            "reason": f"Verified as legitimate exterior cleaning provider via {verification_type}"
        })
    elif verified is False:
        if verification_type == 'excluded_service':
            reason = "Not an exterior cleaning service - excluded service type"
        elif verification_type == 'fetch_failed':
            reason = "Could not verify - website fetch failed"
        else:
            reason = f"Not a legitimate exterior cleaning provider - {verification_type}"
        response = json.dumps({
            "legitimate": False,
            "confidence": 0.85,
            "reason": reason
        })
    else:
        # Unknown/null - use as negative example
        response = json.dumps({
            "legitimate": False,
            "confidence": 0.5,
            "reason": "Insufficient evidence to verify as exterior cleaning provider"
        })
    
    return {
        "text": f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{response}<|im_end|>"
    }

def get_standardization_prompt(company_data):
    """Generate standardization training example."""
    system = """You are a business name standardization assistant. Extract and standardize the official business name from the provided website information.

Rules:
- Extract the actual business name, not page titles or taglines
- Remove legal suffixes (LLC, Inc, Corp) unless they're part of the brand identity
- Preserve proper capitalization and spacing
- If the business name is already correct, return it unchanged

Respond with ONLY the standardized business name, nothing else."""

    original_name = company_data.get('name', '')
    domain = company_data.get('domain', '')
    website = company_data.get('website', '')
    standardized = company_data.get('standardized_name', original_name)
    
    user = f"""Extract business name:
Original: {original_name}
Domain: {domain}
Website: {website}"""

    return {
        "text": f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{standardized}<|im_end|>"
    }

def main():
    print("=" * 60)
    print("COMPREHENSIVE TRAINING DATA EXPORT")
    print("=" * 60)
    
    db = get_db_manager()
    
    verification_examples = []
    standardization_examples = []
    
    # Export ALL verification data (including failures)
    print("\n1. Exporting verification data...")
    with db.get_session() as session:
        result = session.execute(text("""
            SELECT id, name, website, domain, phone, address, services,
                   verified, verification_type, parse_metadata
            FROM companies
            WHERE verification_type IS NOT NULL
            ORDER BY id
        """))
        
        for row in result:
            company_data = {
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'domain': row[3],
                'phone': row[4],
                'address': row[5],
                'services': row[6],
                'verified': row[7],
                'verification_type': row[8],
            }
            example = get_verification_prompt(company_data)
            verification_examples.append(example)
    
    print(f"   Verification examples: {len(verification_examples):,}")
    
    # Export ALL standardization data
    print("\n2. Exporting standardization data...")
    with db.get_session() as session:
        result = session.execute(text("""
            SELECT id, name, website, domain, standardized_name, standardized_name_source
            FROM companies
            WHERE standardized_name IS NOT NULL
            ORDER BY id
        """))
        
        for row in result:
            company_data = {
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'domain': row[3],
                'standardized_name': row[4],
                'standardized_name_source': row[5],
            }
            # Only include if standardized name is different or meaningful
            if company_data['standardized_name'] and len(company_data['standardized_name']) > 1:
                example = get_standardization_prompt(company_data)
                standardization_examples.append(example)
    
    print(f"   Standardization examples: {len(standardization_examples):,}")
    
    # Combine all examples
    all_examples = verification_examples + standardization_examples
    print(f"\n3. Total examples: {len(all_examples):,}")
    
    # Shuffle for training
    import random
    random.seed(42)
    random.shuffle(all_examples)
    
    # Split into train/val (90/10)
    split_idx = int(len(all_examples) * 0.9)
    train_examples = all_examples[:split_idx]
    val_examples = all_examples[split_idx:]
    
    # Write files
    train_file = OUTPUT_DIR / "comprehensive_train.jsonl"
    val_file = OUTPUT_DIR / "comprehensive_val.jsonl"
    
    print(f"\n4. Writing files...")
    with open(train_file, 'w') as f:
        for ex in train_examples:
            f.write(json.dumps(ex) + '\n')
    
    with open(val_file, 'w') as f:
        for ex in val_examples:
            f.write(json.dumps(ex) + '\n')
    
    # Stats
    stats = {
        "created_at": datetime.now().isoformat(),
        "total_examples": len(all_examples),
        "train_examples": len(train_examples),
        "val_examples": len(val_examples),
        "verification_count": len(verification_examples),
        "standardization_count": len(standardization_examples),
        "train_file_mb": os.path.getsize(train_file) / 1024 / 1024,
        "val_file_mb": os.path.getsize(val_file) / 1024 / 1024,
    }
    
    with open(OUTPUT_DIR / "stats.json", 'w') as f:
        json.dump(stats, f, indent=2)
    
    print(f"\n" + "=" * 60)
    print("EXPORT COMPLETE")
    print("=" * 60)
    print(f"  Training examples: {stats['train_examples']:,}")
    print(f"  Validation examples: {stats['val_examples']:,}")
    print(f"  Train file: {stats['train_file_mb']:.1f} MB")
    print(f"  Val file: {stats['val_file_mb']:.1f} MB")
    print(f"\nFiles saved to: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
