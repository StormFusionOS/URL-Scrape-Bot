#!/usr/bin/env python3
"""
Export training data with FULL Claude reasoning from parse_metadata.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import get_db_manager
from sqlalchemy import text

OUTPUT_DIR = Path("data/full_reasoning_training")
OUTPUT_DIR.mkdir(exist_ok=True)

def build_verification_example(company):
    """Build verification example with full reasoning."""
    
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
- services: object with service types detected
- quality_signals: list of positive indicators found
- red_flags: list of concerns or issues found
- reasoning: detailed explanation of your decision"""

    # Build user prompt with available signals
    metadata = company.get('parse_metadata') or {}
    verification = metadata.get('verification', {})
    
    user_parts = [
        f"Company: {company.get('name', 'Unknown')}",
        f"Website: {company.get('website', 'N/A')}",
        f"Domain: {company.get('domain', 'N/A')}",
    ]
    
    if company.get('phone'):
        user_parts.append(f"Phone: {company['phone']}")
    if company.get('address'):
        user_parts.append(f"Address: {company['address']}")
    if company.get('services'):
        user_parts.append(f"Services listed: {company['services']}")
    
    # Add signals from metadata if available
    quality_signals = verification.get('quality_signals', [])
    red_flags = verification.get('red_flags', [])
    
    if quality_signals:
        user_parts.append(f"Quality signals detected: {', '.join(quality_signals[:5])}")
    if red_flags:
        user_parts.append(f"Red flags detected: {', '.join(red_flags[:5])}")
    
    user_parts.append("\nIs this a legitimate exterior cleaning service provider? Provide your detailed assessment.")
    user = "\n".join(user_parts)
    
    # Build response with full reasoning
    is_legit = company.get('verified', False)
    confidence = verification.get('final_score', 0.5) if verification else 0.5
    confidence = min(max(confidence, 0.1), 0.99)  # Clamp to valid range
    
    # Extract services from metadata
    services = {}
    llm_details = verification.get('llm_details', {})
    if llm_details.get('service_score', 0) > 0:
        services['pressure_washing'] = True
    if 'window' in str(company.get('services', '')).lower():
        services['window_cleaning'] = True
    if 'gutter' in str(company.get('services', '')).lower():
        services['gutter_cleaning'] = True
    if 'roof' in str(company.get('services', '')).lower():
        services['roof_cleaning'] = True
    if 'soft' in str(company.get('services', '')).lower():
        services['soft_washing'] = True
    
    # Build reasoning
    reason = verification.get('reason', '')
    if not reason:
        if is_legit:
            reason = "Company appears to be a legitimate exterior cleaning service provider based on available information."
        else:
            reason = "Company does not appear to be a legitimate exterior cleaning service provider."
    
    response = {
        "legitimate": is_legit,
        "confidence": round(confidence, 2),
        "services": services if services else {"detected": False},
        "quality_signals": quality_signals[:5] if quality_signals else ["No specific quality signals identified"],
        "red_flags": red_flags[:5] if red_flags else ["No significant red flags identified"],
        "reasoning": reason
    }
    
    return {
        "text": f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{json.dumps(response, indent=2)}<|im_end|>"
    }

def build_standardization_example(company):
    """Build standardization example."""
    
    system = """You are a business name standardization assistant. Extract and standardize the official business name from the provided website information.

Rules:
- Extract the actual business name, not page titles or taglines
- Remove legal suffixes (LLC, Inc, Corp) unless they're part of the brand identity
- Preserve proper capitalization and spacing
- If the business name is already correct, return it unchanged

Respond with ONLY the standardized business name, nothing else."""

    user = f"""Extract business name:
Original: {company.get('name', '')}
Domain: {company.get('domain', '')}
Website: {company.get('website', '')}"""

    standardized = company.get('standardized_name', company.get('name', ''))
    
    return {
        "text": f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{standardized}<|im_end|>"
    }

def main():
    print("=" * 60)
    print("EXPORT WITH FULL REASONING")
    print("=" * 60)
    
    db = get_db_manager()
    
    verification_examples = []
    standardization_examples = []
    
    # Export verification with reasoning
    print("\n1. Exporting verification data with reasoning...")
    with db.get_session() as session:
        result = session.execute(text("""
            SELECT id, name, website, domain, phone, address, services,
                   verified, verification_type, parse_metadata
            FROM companies
            WHERE verification_type IS NOT NULL
            ORDER BY id
        """))
        
        for row in result:
            company = {
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'domain': row[3],
                'phone': row[4],
                'address': row[5],
                'services': row[6],
                'verified': row[7],
                'verification_type': row[8],
                'parse_metadata': row[9] if row[9] else {},
            }
            example = build_verification_example(company)
            verification_examples.append(example)
    
    print(f"   Verification examples: {len(verification_examples):,}")
    
    # Count rich vs simple
    rich = sum(1 for ex in verification_examples if 'quality_signals' in ex['text'] and len(ex['text']) > 1500)
    print(f"   With rich reasoning: {rich:,}")
    
    # Export standardization
    print("\n2. Exporting standardization data...")
    with db.get_session() as session:
        result = session.execute(text("""
            SELECT id, name, website, domain, standardized_name
            FROM companies
            WHERE standardized_name IS NOT NULL AND standardized_name != ''
            ORDER BY id
        """))
        
        for row in result:
            company = {
                'id': row[0],
                'name': row[1],
                'website': row[2],
                'domain': row[3],
                'standardized_name': row[4],
            }
            example = build_standardization_example(company)
            standardization_examples.append(example)
    
    print(f"   Standardization examples: {len(standardization_examples):,}")
    
    # Combine
    all_examples = verification_examples + standardization_examples
    print(f"\n3. Total examples: {len(all_examples):,}")
    
    # Shuffle
    import random
    random.seed(42)
    random.shuffle(all_examples)
    
    # Split
    split_idx = int(len(all_examples) * 0.9)
    train = all_examples[:split_idx]
    val = all_examples[split_idx:]
    
    # Write
    print(f"\n4. Writing files...")
    train_file = OUTPUT_DIR / "train.jsonl"
    val_file = OUTPUT_DIR / "val.jsonl"
    
    with open(train_file, 'w') as f:
        for ex in train:
            f.write(json.dumps(ex) + '\n')
    
    with open(val_file, 'w') as f:
        for ex in val:
            f.write(json.dumps(ex) + '\n')
    
    stats = {
        "created_at": datetime.now().isoformat(),
        "train_examples": len(train),
        "val_examples": len(val),
        "total": len(all_examples),
        "verification_count": len(verification_examples),
        "standardization_count": len(standardization_examples),
        "train_mb": os.path.getsize(train_file) / 1024 / 1024,
        "val_mb": os.path.getsize(val_file) / 1024 / 1024,
    }
    
    with open(OUTPUT_DIR / "stats.json", 'w') as f:
        json.dump(stats, f, indent=2)
    
    print(f"\n" + "=" * 60)
    print("EXPORT COMPLETE")
    print("=" * 60)
    print(f"  Training: {stats['train_examples']:,} ({stats['train_mb']:.1f} MB)")
    print(f"  Validation: {stats['val_examples']:,} ({stats['val_mb']:.1f} MB)")
    print(f"\nFiles: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
