"""
ML Classifier for Verification

This module loads the trained classifier and provides prediction functions
for use in the verification worker.

The classifier is loaded lazily on first use and cached for the process lifetime.
"""

import logging
from pathlib import Path
from typing import Optional, Any

import joblib

logger = logging.getLogger(__name__)

# Model file path
MODEL_PATH = Path(__file__).parent.parent / "models" / "verification_classifier.joblib"

# Cached model bundle
_model_bundle: Optional[dict] = None
_load_attempted: bool = False


def load_model_bundle() -> Optional[dict]:
    """
    Load the model bundle (vectorizer + model + metrics).

    Returns None if no model file exists or loading fails.
    The result is cached for the process lifetime.
    """
    global _model_bundle, _load_attempted

    if _load_attempted:
        return _model_bundle

    _load_attempted = True

    if not MODEL_PATH.exists():
        logger.info(f"No ML classifier found at {MODEL_PATH} - using combined_score only")
        return None

    try:
        _model_bundle = joblib.load(MODEL_PATH)
        logger.info(f"Loaded ML classifier from {MODEL_PATH}")

        # Log model info
        metrics = _model_bundle.get('metrics', {})
        logger.info(f"  Model type: {metrics.get('model_type', 'unknown')}")
        logger.info(f"  Trained at: {metrics.get('trained_at', 'unknown')}")
        logger.info(f"  Training samples: {metrics.get('n_train', 'unknown')}")
        logger.info(f"  Classes: {metrics.get('classes', [])}")

        return _model_bundle

    except Exception as e:
        logger.error(f"Failed to load ML classifier: {e}")
        _model_bundle = None
        return None


def reload_model():
    """
    Force reload of the model (e.g., after retraining).
    """
    global _model_bundle, _load_attempted
    _model_bundle = None
    _load_attempted = False
    return load_model_bundle()


def build_features(company: Any, verification_result: dict, combined_score: float) -> dict:
    """
    Build a feature dictionary from company data and verification results.

    This should match the features used during training (see export_verification_training_data.py).

    Args:
        company: Company ORM object with parse_metadata
        verification_result: Dict with score, is_legitimate, red_flags, tier, etc.
        combined_score: The combined score from calculate_combined_score()

    Returns:
        Dict of features suitable for the vectorizer
    """
    v = verification_result or {}
    pm = getattr(company, 'parse_metadata', None) or {}

    # Get nested metadata
    yp_filter = pm.get('yp_filter', {}) or {}
    google_filter = pm.get('google_filter', {}) or {}
    website_pm = pm.get('website', {}) or {}

    # Red flags processing
    red_flags = v.get('red_flags') or []
    red_flags_set = set(rf.lower() if isinstance(rf, str) else str(rf).lower() for rf in red_flags)

    # Tier mapping
    tier_map = {'A': 3, 'B': 2, 'C': 1, 'D': 0}

    features = {
        # Verification scores
        'score': float(v.get('score', 0.0) or 0.0),
        'combined_score': float(combined_score or 0.0),
        'is_legitimate': 1.0 if v.get('is_legitimate') else 0.0,
        'tier': tier_map.get(v.get('tier'), 0),

        # Red flags
        'red_flags_count': len(red_flags),
        'has_directory_flag': 1.0 if any('directory' in rf for rf in red_flags_set) else 0.0,
        'has_agency_flag': 1.0 if any('agency' in rf or 'lead_gen' in rf for rf in red_flags_set) else 0.0,
        'has_blog_flag': 1.0 if any('blog' in rf or 'informational' in rf for rf in red_flags_set) else 0.0,
        'has_franchise_flag': 1.0 if any('franchise' in rf or 'national' in rf for rf in red_flags_set) else 0.0,

        # YP filter confidence
        'yp_confidence': float(yp_filter.get('confidence', 0.0) or 0.0),

        # Google filter confidence
        'google_confidence': float(google_filter.get('confidence', 0.0) or 0.0),

        # Ratings
        'rating_google': float(google_filter.get('rating', 0.0) or 0.0),
        'reviews_google': float(google_filter.get('reviews', 0) or 0),
        'rating_yp': float(yp_filter.get('rating', 0.0) or 0.0),
        'reviews_yp': float(yp_filter.get('reviews', 0) or 0),

        # Website features
        'has_phone': 1.0 if website_pm.get('has_phone') else 0.0,
        'has_email': 1.0 if website_pm.get('has_email') else 0.0,
        'has_address': 1.0 if website_pm.get('has_address') else 0.0,
        'homepage_text_length': float(website_pm.get('homepage_text_length', 0) or 0),
        'services_text_length': float(website_pm.get('services_text_length', 0) or 0),
    }

    return features


def predict_provider_prob(features: dict) -> Optional[float]:
    """
    Predict the probability that a company is a legitimate provider.

    Args:
        features: Feature dict from build_features()

    Returns:
        Float probability (0-1) that this is a provider, or None if no model is loaded.
    """
    bundle = load_model_bundle()
    if not bundle:
        return None

    vec = bundle.get('vectorizer')
    clf = bundle.get('model')

    if not vec or not clf:
        return None

    try:
        # Transform features
        X_vec = vec.transform([features])

        # Get probability
        proba = clf.predict_proba(X_vec)[0]

        # Find the 'provider' class index
        classes = list(clf.classes_)
        if 'provider' in classes:
            provider_idx = classes.index('provider')
            return float(proba[provider_idx])
        else:
            # Binary model might have 'other' vs 'provider'
            # Return 1 - other_prob if provider not found
            logger.warning(f"'provider' class not found in {classes}")
            return None

    except Exception as e:
        logger.error(f"ML prediction failed: {e}")
        return None


def get_model_info() -> Optional[dict]:
    """
    Get information about the loaded model.

    Returns:
        Dict with model metrics, or None if no model loaded.
    """
    bundle = load_model_bundle()
    if not bundle:
        return None

    return bundle.get('metrics', {})


def compute_final_score(combined_score: float, ml_prob: Optional[float], ml_weight: float = 0.5) -> float:
    """
    Compute final score by fusing combined_score with ML probability.

    Args:
        combined_score: Score from calculate_combined_score()
        ml_prob: Probability from predict_provider_prob(), or None
        ml_weight: Weight for ML probability (0-1). Default 0.5 means 50/50 blend.

    Returns:
        Final score (0-1)
    """
    if ml_prob is None:
        return combined_score

    # Weighted average
    return (1 - ml_weight) * combined_score + ml_weight * ml_prob
