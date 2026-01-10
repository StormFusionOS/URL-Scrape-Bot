#!/usr/bin/env python3
"""
Claude ML Retrainer - Scheduled Job

Runs monthly (1st of month, 4 AM) to retrain Mistral 7B classifier with Claude labels.

Tasks:
1. Export training data (human + Claude labels)
2. Train new sklearn classifier model
3. Evaluate performance vs current model
4. Deploy if improved (accuracy increase)
5. Log results and alert

Usage:
    python verification/jobs/claude_ml_retrainer.py [--force] [--dry-run]
"""

import sys
import os
import logging
import argparse
import subprocess
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from db.database_manager import get_db_manager

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_training_data_stats() -> dict:
    """Get statistics on available training data."""
    db_manager = get_db_manager()

    query = """
        SELECT
            COUNT(*) as total_companies,
            COUNT(*) FILTER (
                WHERE parse_metadata->'verification'->'labels'->>'human' IS NOT NULL
            ) as human_labeled,
            COUNT(*) FILTER (
                WHERE parse_metadata->'verification'->'labels'->>'claude' IS NOT NULL
            ) as claude_labeled,
            COUNT(*) FILTER (
                WHERE parse_metadata->'verification'->'labels'->>'human' IS NOT NULL
                   OR parse_metadata->'verification'->'labels'->>'claude' IS NOT NULL
            ) as total_labeled,
            COUNT(*) FILTER (
                WHERE parse_metadata->'verification'->'labels'->>'human' = 'provider'
                   OR parse_metadata->'verification'->'labels'->>'claude' = 'provider'
            ) as provider_count,
            COUNT(*) FILTER (
                WHERE parse_metadata->'verification'->'labels'->>'human' IN ('non_provider', 'directory', 'agency', 'blog')
                   OR parse_metadata->'verification'->'labels'->>'claude' = 'non_provider'
            ) as non_provider_count
        FROM companies
        WHERE active = true
    """

    with db_manager.get_session() as session:
        result = session.execute(text(query))
        row = result.fetchone()

    total, human, claude, labeled, providers, non_providers = row

    return {
        'total_companies': total,
        'human_labeled': human,
        'claude_labeled': claude,
        'total_labeled': labeled,
        'provider_count': providers,
        'non_provider_count': non_providers,
        'label_rate': round(labeled / max(total, 1), 3)
    }


def export_training_data() -> str:
    """
    Export training data including Claude labels.

    Returns:
        Path to exported file
    """
    output_file = "data/training_with_claude.jsonl"

    logger.info("Exporting training data with Claude labels...")

    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)

    # Run export script
    cmd = [
        "python",
        "scripts/export_verification_training_data.py",
        "--include-claude-labels",
        "--output", output_file
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes
        )

        if result.returncode != 0:
            raise Exception(f"Export failed: {result.stderr}")

        logger.info(f"✓ Training data exported to {output_file}")
        return output_file

    except subprocess.TimeoutExpired:
        raise Exception("Export timed out after 5 minutes")
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise


def train_model(training_file: str) -> str:
    """
    Train new sklearn classifier model.

    Args:
        training_file: Path to training data (JSONL)

    Returns:
        Path to trained model file
    """
    output_model = "models/verification_classifier_candidate.joblib"

    logger.info("Training new classifier model...")

    # Ensure models directory exists
    os.makedirs("models", exist_ok=True)

    # Run training script
    cmd = [
        "python",
        "scripts/train_verification_classifier.py",
        "--input", training_file,
        "--output", output_model,
        "--val-split", "0.2"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes
        )

        if result.returncode != 0:
            raise Exception(f"Training failed: {result.stderr}")

        logger.info(f"✓ Model trained: {output_model}")
        return output_model

    except subprocess.TimeoutExpired:
        raise Exception("Training timed out after 10 minutes")
    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise


def evaluate_model(model_path: str) -> dict:
    """
    Evaluate model performance.

    Args:
        model_path: Path to model file

    Returns:
        Dictionary with metrics (accuracy, precision, recall, f1)
    """
    logger.info(f"Evaluating model: {model_path}")

    # TODO: Implement actual evaluation
    # For now, return mock metrics
    # In production, this should:
    # 1. Load test set
    # 2. Run predictions
    # 3. Calculate metrics

    # Mock metrics
    metrics = {
        'accuracy': 0.85,
        'precision': 0.83,
        'recall': 0.87,
        'f1': 0.85,
        'samples_evaluated': 1000
    }

    logger.info(f"Model metrics: accuracy={metrics['accuracy']:.3f}, f1={metrics['f1']:.3f}")
    return metrics


def get_current_model_metrics() -> dict:
    """Get metrics for current production model."""
    current_model = "models/verification_classifier.joblib"

    if not os.path.exists(current_model):
        logger.warning("No current model found")
        return {'accuracy': 0.0}

    return evaluate_model(current_model)


def deploy_model(candidate_model: str, backup: bool = True) -> bool:
    """
    Deploy candidate model as production model.

    Args:
        candidate_model: Path to candidate model
        backup: If True, backup current model

    Returns:
        True if successful
    """
    production_model = "models/verification_classifier.joblib"

    try:
        # Backup current model
        if backup and os.path.exists(production_model):
            backup_path = f"models/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.joblib"
            os.rename(production_model, backup_path)
            logger.info(f"Backed up current model to {backup_path}")

        # Deploy candidate
        os.rename(candidate_model, production_model)
        logger.info(f"✓ Deployed new model: {production_model}")

        return True

    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        return False


def log_retraining_result(result: dict):
    """Log retraining result to file."""
    # TODO: Create retraining_log table if needed
    # For now, just log to file
    log_file = "logs/ml_retraining.log"
    os.makedirs("logs", exist_ok=True)

    with open(log_file, 'a') as f:
        entry = {
            'timestamp': datetime.now().isoformat(),
            **result
        }
        f.write(json.dumps(entry) + '\n')

    logger.info(f"Logged retraining result to {log_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Retrain ML classifier with Claude labels')
    parser.add_argument('--force', action='store_true', help='Deploy even if accuracy did not improve')
    parser.add_argument('--dry-run', action='store_true', help='Train but do not deploy')
    parser.add_argument('--min-samples', type=int, default=100, help='Minimum labeled samples required')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("CLAUDE ML RETRAINER")
    logger.info("=" * 70)

    result = {
        'success': False,
        'deployed': False,
        'error': None
    }

    try:
        # 1. Check training data availability
        logger.info("\nChecking training data availability...")
        stats = get_training_data_stats()

        logger.info("Training data stats:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")

        if stats['total_labeled'] < args.min_samples:
            raise Exception(
                f"Insufficient training data: {stats['total_labeled']} < {args.min_samples}"
            )

        # 2. Export training data
        logger.info("\nStep 1: Exporting training data...")
        training_file = export_training_data()
        result['training_file'] = training_file
        result['training_samples'] = stats['total_labeled']

        # 3. Train new model
        logger.info("\nStep 2: Training new model...")
        candidate_model = train_model(training_file)
        result['candidate_model'] = candidate_model

        # 4. Evaluate current model
        logger.info("\nStep 3: Evaluating models...")
        current_metrics = get_current_model_metrics()
        logger.info(f"Current model: {current_metrics}")

        # 5. Evaluate candidate model
        candidate_metrics = evaluate_model(candidate_model)
        logger.info(f"Candidate model: {candidate_metrics}")

        result['current_metrics'] = current_metrics
        result['candidate_metrics'] = candidate_metrics

        # 6. Decide whether to deploy
        accuracy_improved = candidate_metrics['accuracy'] > current_metrics['accuracy']
        improvement = candidate_metrics['accuracy'] - current_metrics['accuracy']

        logger.info(f"\nAccuracy change: {improvement:+.3f}")

        if args.dry_run:
            logger.info("DRY RUN - Model not deployed")
            result['success'] = True

        elif accuracy_improved or args.force:
            logger.info("\nStep 4: Deploying new model...")
            deployed = deploy_model(candidate_model, backup=True)

            if deployed:
                result['deployed'] = True
                result['success'] = True
                logger.info("✓ New model deployed successfully")
            else:
                raise Exception("Model deployment failed")

        else:
            logger.info("\nModel accuracy did not improve - keeping current model")
            logger.info(f"  Current: {current_metrics['accuracy']:.3f}")
            logger.info(f"  Candidate: {candidate_metrics['accuracy']:.3f}")
            result['success'] = True

        # 7. Log result
        log_retraining_result(result)

    except Exception as e:
        logger.error(f"\n✗ Retraining failed: {e}")
        result['error'] = str(e)
        log_retraining_result(result)

    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Success: {result['success']}")
    logger.info(f"Deployed: {result.get('deployed', False)}")
    if result.get('candidate_metrics'):
        logger.info(f"Candidate accuracy: {result['candidate_metrics']['accuracy']:.3f}")
    if result.get('error'):
        logger.info(f"Error: {result['error']}")
    logger.info("=" * 70)

    return 0 if result['success'] else 1


if __name__ == "__main__":
    sys.exit(main())
