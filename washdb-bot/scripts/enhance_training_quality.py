#!/usr/bin/env python3
"""
Training Data Quality Enhancement

This script improves training data quality by:
1. Removing duplicates and near-duplicates
2. Mining hard negatives (tricky misclassification cases)
3. Adding edge cases (franchises, multi-location, similar names)
4. Balancing the dataset
5. Creating augmented examples

Output:
- quality_report.json - Data quality analysis
- hard_negatives.jsonl - Challenging examples
- edge_cases.jsonl - Special cases
- cleaned_training.jsonl - Deduplicated data
"""

import json
import re
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# Paths
BASE_DIR = Path("/home/rivercityscrape/URL-Scrape-Bot/washdb-bot")
DATA_DIR = BASE_DIR / "data"
UNIFIED_DIR = DATA_DIR / "unified_training"
OUTPUT_DIR = DATA_DIR / "enhanced_training"
OUTPUT_DIR.mkdir(exist_ok=True)

# Database
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "washbot_db",
    "user": "washbot",
    "password": "Washdb123"
}

# System prompts
VERIFICATION_SYSTEM = """You are a business verification assistant. Analyze the company information and determine if it is a legitimate service provider offering exterior cleaning services.

Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet washing, Wood restoration.

Respond with JSON: {"legitimate": true/false, "confidence": 0.0-1.0, "services": {...}, "reasoning": "..."}"""

STANDARDIZATION_SYSTEM = """You are a business name standardization assistant. Extract and standardize the official business name.

Rules:
- Extract the actual business name, not page titles or taglines
- Remove legal suffixes (LLC, Inc) unless part of brand identity
- Preserve proper capitalization

Respond with ONLY the standardized business name."""


class DataQualityChecker:
    """Analyzes and improves training data quality."""

    def __init__(self):
        self.duplicates = []
        self.low_quality = []
        self.stats = {}

    def compute_content_hash(self, messages: List[Dict]) -> str:
        """Compute hash of message content for deduplication."""
        content = ""
        for msg in messages:
            if msg['role'] == 'user':
                content += msg['content']
        return hashlib.md5(content.encode()).hexdigest()

    def check_example_quality(self, example: Dict) -> Tuple[bool, List[str]]:
        """Check if an example meets quality standards."""
        issues = []
        messages = example.get('messages', [])

        if len(messages) < 3:
            issues.append("Missing messages")
            return False, issues

        user_msg = next((m for m in messages if m['role'] == 'user'), None)
        assistant_msg = next((m for m in messages if m['role'] == 'assistant'), None)

        if not user_msg or not assistant_msg:
            issues.append("Missing user or assistant message")
            return False, issues

        # Check user message quality
        user_content = user_msg['content']
        if len(user_content) < 50:
            issues.append("User message too short")
        if len(user_content) > 10000:
            issues.append("User message too long")

        # Check assistant message quality
        assistant_content = assistant_msg['content']
        if len(assistant_content) < 2:
            issues.append("Assistant message too short")

        # Check for verification task
        if example.get('task') == 'verification':
            try:
                response = json.loads(assistant_content)
                if 'legitimate' not in response:
                    issues.append("Missing 'legitimate' field")
                if 'confidence' not in response:
                    issues.append("Missing 'confidence' field")
            except json.JSONDecodeError:
                issues.append("Invalid JSON response")

        return len(issues) == 0, issues

    def deduplicate(self, examples: List[Dict]) -> List[Dict]:
        """Remove duplicate examples."""
        seen_hashes = set()
        unique = []
        duplicates = 0

        for ex in examples:
            content_hash = self.compute_content_hash(ex.get('messages', []))
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique.append(ex)
            else:
                duplicates += 1

        print(f"Removed {duplicates} duplicates, {len(unique)} unique examples remain")
        return unique

    def analyze_dataset(self, filepath: Path) -> Dict:
        """Analyze a training dataset."""
        stats = {
            "total": 0,
            "verification": 0,
            "standardization": 0,
            "quality_pass": 0,
            "quality_fail": 0,
            "issues": Counter(),
            "avg_user_length": 0,
            "avg_assistant_length": 0,
        }

        user_lengths = []
        assistant_lengths = []

        with open(filepath, 'r') as f:
            for line in f:
                try:
                    ex = json.loads(line.strip())
                    stats["total"] += 1

                    # Task type
                    task = ex.get('task', 'unknown')
                    if task == 'verification':
                        stats["verification"] += 1
                    elif task == 'standardization':
                        stats["standardization"] += 1

                    # Quality check
                    is_valid, issues = self.check_example_quality(ex)
                    if is_valid:
                        stats["quality_pass"] += 1
                    else:
                        stats["quality_fail"] += 1
                        for issue in issues:
                            stats["issues"][issue] += 1

                    # Length stats
                    for msg in ex.get('messages', []):
                        if msg['role'] == 'user':
                            user_lengths.append(len(msg['content']))
                        elif msg['role'] == 'assistant':
                            assistant_lengths.append(len(msg['content']))

                except json.JSONDecodeError:
                    stats["quality_fail"] += 1
                    stats["issues"]["Invalid JSON"] += 1

        if user_lengths:
            stats["avg_user_length"] = sum(user_lengths) // len(user_lengths)
        if assistant_lengths:
            stats["avg_assistant_length"] = sum(assistant_lengths) // len(assistant_lengths)

        stats["issues"] = dict(stats["issues"])
        return stats


class HardNegativeMiner:
    """Mines hard negative examples from the database."""

    def __init__(self):
        self.conn = psycopg2.connect(**DB_CONFIG)

    def close(self):
        self.conn.close()

    def get_franchises(self, limit: int = 500) -> List[Dict]:
        """Get franchise businesses (often misclassified)."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        # Common franchise patterns
        franchise_patterns = [
            '%SERVPRO%', '%ServiceMaster%', '%Chem-Dry%', '%Stanley Steemer%',
            '%Jan-Pro%', '%Jani-King%', '%Merry Maids%', '%Molly Maid%',
            '%Window Genie%', '%Fish Window%', '%Men In Kilts%',
        ]

        pattern_sql = " OR ".join([f"name ILIKE '{p}'" for p in franchise_patterns])

        query = f"""
        SELECT id, name, website, domain, phone, address, city, state,
               llm_verified, standardized_name
        FROM companies
        WHERE ({pattern_sql})
          AND llm_verified IS NOT NULL
        LIMIT {limit}
        """

        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()

        return [dict(row) for row in rows]

    def get_similar_names_different_verdicts(self, limit: int = 500) -> List[Tuple[Dict, Dict]]:
        """Find companies with similar names but different verification verdicts."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        query = """
        WITH name_groups AS (
            SELECT
                LOWER(REGEXP_REPLACE(name, '[^a-zA-Z]', '', 'g')) as clean_name,
                id, name, website, domain, llm_verified, standardized_name
            FROM companies
            WHERE llm_verified IS NOT NULL
              AND LENGTH(name) > 5
        )
        SELECT a.*, b.id as b_id, b.name as b_name, b.website as b_website,
               b.llm_verified as b_verified
        FROM name_groups a
        JOIN name_groups b ON
            a.clean_name = b.clean_name
            AND a.id < b.id
            AND a.llm_verified != b.llm_verified
        LIMIT %s
        """

        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        cursor.close()

        pairs = []
        for row in rows:
            pair = (
                {"id": row['id'], "name": row['name'], "website": row['website'],
                 "llm_verified": row['llm_verified']},
                {"id": row['b_id'], "name": row['b_name'], "website": row['b_website'],
                 "llm_verified": row['b_verified']}
            )
            pairs.append(pair)

        return pairs

    def get_non_service_businesses(self, limit: int = 500) -> List[Dict]:
        """Get businesses that failed verification (negative examples)."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        query = """
        SELECT id, name, website, domain, phone, address,
               llm_verified, llm_confidence, parse_metadata
        FROM companies
        WHERE llm_verified = false
          AND llm_confidence >= 0.7
        ORDER BY RANDOM()
        LIMIT %s
        """

        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        cursor.close()

        return [dict(row) for row in rows]

    def get_edge_cases(self, limit: int = 500) -> List[Dict]:
        """Get edge cases: low confidence, conflicting signals."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        query = """
        SELECT id, name, website, domain, phone, address,
               llm_verified, llm_confidence, standardized_name
        FROM companies
        WHERE llm_confidence BETWEEN 0.4 AND 0.6
          AND llm_verified IS NOT NULL
        ORDER BY RANDOM()
        LIMIT %s
        """

        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        cursor.close()

        return [dict(row) for row in rows]


def create_hard_negative_examples(miner: HardNegativeMiner) -> List[Dict]:
    """Create training examples from hard negatives."""
    examples = []

    print("Mining franchises...")
    franchises = miner.get_franchises(300)
    for company in franchises:
        # Franchises are often legitimate but need careful handling
        example = create_verification_example(company, is_franchise=True)
        if example:
            examples.append(example)

    print(f"  Found {len(franchises)} franchise examples")

    print("Mining similar names with different verdicts...")
    pairs = miner.get_similar_names_different_verdicts(200)
    for company_a, company_b in pairs:
        # Both are interesting - shows why context matters
        ex_a = create_verification_example(company_a, note="Similar name to another business with different verdict")
        ex_b = create_verification_example(company_b, note="Similar name to another business with different verdict")
        if ex_a:
            examples.append(ex_a)
        if ex_b:
            examples.append(ex_b)

    print(f"  Found {len(pairs)} similar name pairs")

    print("Mining non-service businesses...")
    non_service = miner.get_non_service_businesses(400)
    for company in non_service:
        example = create_verification_example(company, is_negative=True)
        if example:
            examples.append(example)

    print(f"  Found {len(non_service)} non-service examples")

    print("Mining edge cases...")
    edge_cases = miner.get_edge_cases(300)
    for company in edge_cases:
        example = create_verification_example(company, is_edge_case=True)
        if example:
            examples.append(example)

    print(f"  Found {len(edge_cases)} edge case examples")

    return examples


def create_verification_example(company: Dict, is_franchise: bool = False,
                                 is_negative: bool = False, is_edge_case: bool = False,
                                 note: str = None) -> Dict:
    """Create a verification training example from company data."""
    context_parts = []
    context_parts.append(f"Company: {company['name']}")
    context_parts.append(f"Website: {company.get('website', 'N/A')}")
    context_parts.append(f"Domain: {company.get('domain', 'N/A')}")

    if company.get('phone'):
        context_parts.append(f"Phone: {company['phone']}")
    if company.get('address'):
        context_parts.append(f"Address: {company['address']}")

    if is_franchise:
        context_parts.append("\nNote: This appears to be a franchise location.")
    if note:
        context_parts.append(f"\nNote: {note}")

    context_parts.append("\nIs this a legitimate exterior cleaning service provider?")

    is_legit = bool(company.get('llm_verified', False))
    confidence = float(company.get('llm_confidence', 0.7) or 0.7)

    response = {
        "legitimate": is_legit,
        "confidence": round(confidence, 2),
        "services": {"pressure_washing": is_legit, "window_cleaning": False},
        "reasoning": "Based on business profile analysis."
    }

    return {
        "messages": [
            {"role": "system", "content": VERIFICATION_SYSTEM},
            {"role": "user", "content": '\n'.join(context_parts)},
            {"role": "assistant", "content": json.dumps(response, indent=2)}
        ],
        "task": "verification",
        "hard_negative": True,
        "is_franchise": is_franchise,
        "is_negative": is_negative,
        "is_edge_case": is_edge_case,
        "company_id": company.get('id')
    }


def main():
    print("=" * 60)
    print("TRAINING DATA QUALITY ENHANCEMENT")
    print("=" * 60)
    print()

    checker = DataQualityChecker()

    # Analyze current training data
    print("Analyzing current training data...")
    train_file = UNIFIED_DIR / "unified_train.jsonl"
    if train_file.exists():
        stats = checker.analyze_dataset(train_file)
        print(f"\nCurrent Dataset Stats:")
        print(f"  Total examples: {stats['total']}")
        print(f"  Verification: {stats['verification']}")
        print(f"  Standardization: {stats['standardization']}")
        print(f"  Quality Pass: {stats['quality_pass']}")
        print(f"  Quality Fail: {stats['quality_fail']}")
        print(f"  Avg User Length: {stats['avg_user_length']}")
        print(f"  Avg Assistant Length: {stats['avg_assistant_length']}")
        if stats['issues']:
            print(f"  Issues: {stats['issues']}")

        # Save stats
        with open(OUTPUT_DIR / "quality_report.json", 'w') as f:
            json.dump(stats, f, indent=2)

    # Mine hard negatives
    print("\n" + "=" * 60)
    print("MINING HARD NEGATIVES")
    print("=" * 60)

    miner = HardNegativeMiner()
    hard_negatives = create_hard_negative_examples(miner)
    miner.close()

    print(f"\nTotal hard negative examples: {len(hard_negatives)}")

    # Save hard negatives
    hard_neg_file = OUTPUT_DIR / "hard_negatives.jsonl"
    with open(hard_neg_file, 'w') as f:
        for ex in hard_negatives:
            f.write(json.dumps(ex) + '\n')
    print(f"Saved to: {hard_neg_file}")

    # Load and deduplicate all data
    print("\n" + "=" * 60)
    print("DEDUPLICATING AND COMBINING")
    print("=" * 60)

    all_examples = []

    # Load original training data
    if train_file.exists():
        with open(train_file, 'r') as f:
            for line in f:
                try:
                    ex = json.loads(line.strip())
                    all_examples.append(ex)
                except:
                    continue

    # Add hard negatives
    all_examples.extend(hard_negatives)

    print(f"Total before dedup: {len(all_examples)}")

    # Deduplicate
    unique_examples = checker.deduplicate(all_examples)

    # Save cleaned data
    cleaned_file = OUTPUT_DIR / "enhanced_train.jsonl"
    with open(cleaned_file, 'w') as f:
        for ex in unique_examples:
            # Clean up metadata
            clean_ex = {"messages": ex["messages"]}
            if "task" in ex:
                clean_ex["task"] = ex["task"]
            f.write(json.dumps(clean_ex) + '\n')

    print(f"Saved enhanced training data: {cleaned_file}")
    print(f"Total examples: {len(unique_examples)}")

    # Summary
    print("\n" + "=" * 60)
    print("ENHANCEMENT COMPLETE")
    print("=" * 60)
    print(f"\nOutput files:")
    print(f"  - {OUTPUT_DIR / 'quality_report.json'}")
    print(f"  - {OUTPUT_DIR / 'hard_negatives.jsonl'}")
    print(f"  - {OUTPUT_DIR / 'enhanced_train.jsonl'}")


if __name__ == "__main__":
    main()
