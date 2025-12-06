#!/usr/bin/env python3
"""
Complete training pipeline for verification system.

This orchestrates:
1. Export human-labeled data
2. Train ML classifier
3. Evaluate model performance
4. Deploy updated model

Usage:
    python scripts/training_pipeline.py [--min-samples 100] [--test-size 0.2]
"""

import sys
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager
from sqlalchemy import text
import subprocess


def check_labeled_data(db: DatabaseManager):
    """Check how much labeled data is available."""

    with db.get_session() as session:
        # Total labels
        result = session.execute(text("""
            SELECT COUNT(*)
            FROM companies
            WHERE parse_metadata->'verification'->>'human_label' IS NOT NULL
        """))
        total_labels = result.scalar()

        # By label type
        result = session.execute(text("""
            SELECT
                parse_metadata->'verification'->>'human_label' as label,
                COUNT(*) as count
            FROM companies
            WHERE parse_metadata->'verification'->>'human_label' IS NOT NULL
            GROUP BY parse_metadata->'verification'->>'human_label'
            ORDER BY count DESC
        """))
        label_distribution = result.fetchall()

    return total_labels, label_distribution


def export_training_data(output_file: str):
    """Export all human-labeled data for training."""

    print("\n" + "=" * 70)
    print("STEP 1: Exporting Training Data")
    print("=" * 70)

    result = subprocess.run(
        ['./venv/bin/python', 'scripts/export_training_data.py', output_file],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"❌ Export failed: {result.stderr}")
        return False

    print(result.stdout)
    return True


def train_classifier(binary_mode: bool = True):
    """Train the ML classifier."""

    print("\n" + "=" * 70)
    print("STEP 2: Training ML Classifier")
    print("=" * 70)

    cmd = ['./venv/bin/python', 'scripts/train_verification_classifier.py']
    if binary_mode:
        cmd.append('--binary')

    # Automatically answer 'y' to confirmation prompt
    result = subprocess.run(
        cmd,
        input='y\n',
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"❌ Training failed: {result.stderr}")
        return False

    print(result.stdout)
    return True


def evaluate_model():
    """Evaluate the trained model performance."""

    print("\n" + "=" * 70)
    print("STEP 3: Evaluating Model")
    print("=" * 70)

    # This will show the evaluation metrics from the training script
    # The training script already outputs precision, recall, F1, etc.
    print("✓ Evaluation metrics shown in training output above")

    return True


def main(min_samples: int = 100, test_size: float = 0.2):
    """Run the complete training pipeline."""

    db = DatabaseManager()

    print("=" * 70)
    print("VERIFICATION TRAINING PIPELINE")
    print("=" * 70)

    # Check labeled data
    print("\nChecking labeled data...")
    total_labels, distribution = check_labeled_data(db)

    print(f"\nTotal human labels: {total_labels}")
    print("\nLabel distribution:")
    for label, count in distribution:
        print(f"  {label}: {count}")

    if total_labels < min_samples:
        print(f"\n❌ ERROR: Not enough labeled data!")
        print(f"   Need at least {min_samples} samples, have {total_labels}")
        print(f"\nNext steps:")
        print(f"1. Export more companies for labeling:")
        print(f"   ./venv/bin/python scripts/export_for_review.py --limit 200")
        print(f"2. Label them and import:")
        print(f"   ./venv/bin/python scripts/import_reviewed_labels.py <csv_file>")
        print(f"3. Run this pipeline again")
        return False

    # Export training data
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    training_file = f"data/training_data_{timestamp}.csv"

    if not export_training_data(training_file):
        return False

    # Train classifier
    if not train_classifier(binary_mode=True):
        return False

    # Evaluate
    if not evaluate_model():
        return False

    print("\n" + "=" * 70)
    print("✓ TRAINING PIPELINE COMPLETE")
    print("=" * 70)
    print("\nThe ML classifier has been updated.")
    print("\nNext steps:")
    print("1. Review model metrics above")
    print("2. If accuracy is good (>90%), restart verification workers")
    print("3. If accuracy is poor, label more data and retrain")
    print("\nTo restart verification:")
    print("  systemctl restart washdb-verification-orchestrator")
    print("  systemctl restart washdb-verification-worker@{1..5}")

    return True


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run training pipeline')
    parser.add_argument('--min-samples', type=int, default=100,
                       help='Minimum number of labeled samples required')
    parser.add_argument('--test-size', type=float, default=0.2,
                       help='Fraction of data to use for testing (0.0-1.0)')

    args = parser.parse_args()

    success = main(args.min_samples, args.test_size)
    sys.exit(0 if success else 1)
