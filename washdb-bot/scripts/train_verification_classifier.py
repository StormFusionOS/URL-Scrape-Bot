#!/usr/bin/env python3
"""
Train verification classifier from labeled data.

This script:
1. Loads labeled examples from data/verification_training.jsonl
2. Trains a classifier (LogisticRegression or GradientBoosting)
3. Evaluates on a hold-out set
4. Saves the model to models/verification_classifier.joblib

Usage:
    python scripts/train_verification_classifier.py [--model logistic|gradient]
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score


# Paths
DATA_FILE = Path(__file__).parent.parent / "data" / "verification_training.jsonl"
MODEL_DIR = Path(__file__).parent.parent / "models"
MODEL_FILE = MODEL_DIR / "verification_classifier.joblib"


def load_training_data(filepath: Path) -> tuple[list[dict], list[str]]:
    """Load features and labels from JSONL file."""
    X = []
    y = []

    if not filepath.exists():
        print(f"Error: Training data file not found: {filepath}")
        print("Run scripts/export_verification_training_data.py first to generate training data.")
        sys.exit(1)

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                features = record.get('features', {})
                label = record.get('label')

                if features and label:
                    X.append(features)
                    y.append(label)
            except json.JSONDecodeError as e:
                print(f"Warning: Skipping malformed JSON line: {e}")
                continue

    return X, y


def binarize_labels(labels: list[str]) -> list[str]:
    """
    Convert multi-class labels to binary (provider vs other).

    provider, pass -> provider  (legitimate service providers)
    non_provider, fail, directory, agency, blog, franchise -> other
    """
    binary = []
    for label in labels:
        # Handle both old format (provider/non_provider) and new format (pass/fail)
        if label in ('provider', 'pass'):
            binary.append('provider')
        else:
            binary.append('other')
    return binary


def train_model(X: list[dict], y: list[str], model_type: str = 'logistic') -> tuple:
    """
    Train a classifier on the feature dictionaries.

    Returns (vectorizer, model, metrics_dict)
    """
    # Vectorize features
    vec = DictVectorizer(sparse=False)
    X_vec = vec.fit_transform(X)

    # Handle NaN values by replacing with 0 (missing features default to 0)
    X_vec = np.nan_to_num(X_vec, nan=0.0, posinf=0.0, neginf=0.0)
    nan_count = np.sum(np.isnan(X_vec))
    if nan_count > 0:
        print(f"Warning: Found {nan_count} NaN values, replaced with 0")

    print(f"\nFeature names ({len(vec.feature_names_)}):")
    for name in sorted(vec.feature_names_):
        print(f"  - {name}")

    # Split into train/validation
    X_train, X_val, y_train, y_val = train_test_split(
        X_vec, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None
    )

    print(f"\nTraining set size: {len(X_train)}")
    print(f"Validation set size: {len(X_val)}")
    print(f"Class distribution in training: {dict(zip(*np.unique(y_train, return_counts=True)))}")

    # Choose model
    if model_type == 'gradient':
        clf = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            random_state=42
        )
        print("\nTraining GradientBoostingClassifier...")
    else:
        clf = LogisticRegression(
            max_iter=1000,
            class_weight='balanced',
            random_state=42
        )
        print("\nTraining LogisticRegression...")

    clf.fit(X_train, y_train)

    # Evaluate
    y_pred = clf.predict(X_val)
    y_proba = clf.predict_proba(X_val)

    print("\n" + "="*60)
    print("VALIDATION RESULTS")
    print("="*60)

    accuracy = accuracy_score(y_val, y_pred)
    print(f"\nAccuracy: {accuracy:.3f}")

    print("\nClassification Report:")
    print(classification_report(y_val, y_pred))

    print("\nConfusion Matrix:")
    print(confusion_matrix(y_val, y_pred))

    # Calculate provider-specific metrics
    provider_idx = list(clf.classes_).index('provider') if 'provider' in clf.classes_ else None

    metrics = {
        'accuracy': accuracy,
        'model_type': model_type,
        'n_train': len(X_train),
        'n_val': len(X_val),
        'classes': list(clf.classes_),
        'feature_names': vec.feature_names_,
        'trained_at': datetime.utcnow().isoformat()
    }

    if provider_idx is not None:
        # Provider recall (true positive rate)
        provider_mask = np.array(y_val) == 'provider'
        provider_correct = np.sum((y_pred == 'provider') & provider_mask)
        provider_total = np.sum(provider_mask)
        provider_recall = provider_correct / provider_total if provider_total > 0 else 0

        # Provider precision
        provider_pred_mask = y_pred == 'provider'
        provider_precision = provider_correct / np.sum(provider_pred_mask) if np.sum(provider_pred_mask) > 0 else 0

        metrics['provider_recall'] = provider_recall
        metrics['provider_precision'] = provider_precision

        print(f"\nProvider Recall: {provider_recall:.3f}")
        print(f"Provider Precision: {provider_precision:.3f}")

    return vec, clf, metrics


def save_model(vec: DictVectorizer, clf, metrics: dict, filepath: Path):
    """Save the vectorizer and model to a joblib file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)

    bundle = {
        'vectorizer': vec,
        'model': clf,
        'metrics': metrics
    }

    joblib.dump(bundle, filepath)
    print(f"\nModel saved to: {filepath}")


def main():
    parser = argparse.ArgumentParser(description='Train verification classifier')
    parser.add_argument(
        '--model',
        choices=['logistic', 'gradient'],
        default='logistic',
        help='Model type to train (default: logistic)'
    )
    parser.add_argument(
        '--binary',
        action='store_true',
        help='Train binary classifier (provider vs other) instead of multi-class'
    )
    args = parser.parse_args()

    print("="*60)
    print("VERIFICATION CLASSIFIER TRAINING")
    print("="*60)

    # Load data
    print(f"\nLoading training data from: {DATA_FILE}")
    X, y = load_training_data(DATA_FILE)

    if len(X) == 0:
        print("Error: No training examples found!")
        print("Label some companies using the review queue first.")
        sys.exit(1)

    print(f"Loaded {len(X)} training examples")
    print(f"Label distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    # Optionally binarize labels
    if args.binary:
        print("\nUsing binary labels (provider vs other)")
        y = binarize_labels(y)
        print(f"Binary distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    # Check minimum samples
    min_samples = 10
    if len(X) < min_samples:
        print(f"\nWarning: Only {len(X)} samples. Recommend at least {min_samples} for reliable training.")
        response = input("Continue anyway? [y/N]: ")
        if response.lower() != 'y':
            sys.exit(0)

    # Train
    vec, clf, metrics = train_model(X, y, model_type=args.model)

    # Check quality before saving
    if metrics.get('provider_recall', 1.0) < 0.5:
        print("\nWarning: Provider recall is below 50%. This means many real providers will be rejected.")
        response = input("Save model anyway? [y/N]: ")
        if response.lower() != 'y':
            print("Model not saved.")
            sys.exit(0)

    # Save
    save_model(vec, clf, metrics, MODEL_FILE)

    print("\n" + "="*60)
    print("TRAINING COMPLETE")
    print("="*60)
    print(f"\nModel file: {MODEL_FILE}")
    print("The verification worker will automatically load this model on next run.")


if __name__ == '__main__':
    main()
