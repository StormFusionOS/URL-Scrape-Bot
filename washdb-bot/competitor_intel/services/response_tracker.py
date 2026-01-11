"""
Response Tracker for Competitor Reviews

Tracks owner responses to reviews:
- Response rate calculation
- Response time analysis
- Template response detection
- Response quality scoring
"""

import re
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from sqlalchemy import text

from competitor_intel.config import REVIEW_SCRAPE_CONFIG
from db.database_manager import create_session

logger = logging.getLogger(__name__)


@dataclass
class OwnerResponse:
    """Owner response to a review."""
    review_id: int
    response_text: str
    response_date: Optional[datetime] = None
    response_time_days: Optional[int] = None
    is_template: bool = False
    template_group: Optional[str] = None


@dataclass
class ResponseMetrics:
    """Aggregated response metrics for a competitor."""
    competitor_id: int
    total_reviews: int
    reviews_with_response: int
    response_rate: float
    response_rate_positive: float
    response_rate_negative: float
    avg_response_time_days: Optional[float] = None
    template_usage_pct: float = 0.0
    template_count: int = 0
    unique_templates: int = 0


class ResponseTracker:
    """
    Analyzes owner responses to competitor reviews.

    Features:
    - Response rate by rating category
    - Response time tracking
    - Template detection using similarity hashing
    - Response quality scoring
    """

    def __init__(self):
        self.similarity_threshold = 0.85
        self.min_response_length = 20

        logger.info("ResponseTracker initialized")

    def analyze_responses(self, competitor_id: int, source: str = None) -> ResponseMetrics:
        """
        Analyze all responses for a competitor.

        Args:
            competitor_id: The competitor to analyze
            source: Optional filter by source (google, yelp, etc.)

        Returns:
            ResponseMetrics with calculated metrics
        """
        reviews = self._fetch_reviews_with_responses(competitor_id, source)

        if not reviews:
            return ResponseMetrics(
                competitor_id=competitor_id,
                total_reviews=0,
                reviews_with_response=0,
                response_rate=0.0,
                response_rate_positive=0.0,
                response_rate_negative=0.0,
            )

        # Calculate response rates
        total = len(reviews)
        with_response = [r for r in reviews if r.get("owner_response")]
        positive_reviews = [r for r in reviews if r.get("rating", 0) >= 4]
        negative_reviews = [r for r in reviews if r.get("rating", 0) <= 2]
        positive_with_response = [r for r in positive_reviews if r.get("owner_response")]
        negative_with_response = [r for r in negative_reviews if r.get("owner_response")]

        response_rate = len(with_response) / total if total > 0 else 0.0
        response_rate_positive = (
            len(positive_with_response) / len(positive_reviews)
            if positive_reviews else 0.0
        )
        response_rate_negative = (
            len(negative_with_response) / len(negative_reviews)
            if negative_reviews else 0.0
        )

        # Calculate average response time
        response_times = []
        for r in with_response:
            if r.get("review_date") and r.get("response_date"):
                days = (r["response_date"] - r["review_date"]).days
                if days >= 0:
                    response_times.append(days)

        avg_response_time = (
            sum(response_times) / len(response_times)
            if response_times else None
        )

        # Detect templates
        response_texts = [r.get("owner_response", "") for r in with_response]
        templates = self._detect_templates(response_texts)
        template_count = sum(1 for r in with_response if self._is_templated(r.get("owner_response", ""), templates))

        return ResponseMetrics(
            competitor_id=competitor_id,
            total_reviews=total,
            reviews_with_response=len(with_response),
            response_rate=round(response_rate * 100, 1),
            response_rate_positive=round(response_rate_positive * 100, 1),
            response_rate_negative=round(response_rate_negative * 100, 1),
            avg_response_time_days=round(avg_response_time, 1) if avg_response_time else None,
            template_usage_pct=round(template_count / len(with_response) * 100, 1) if with_response else 0.0,
            template_count=template_count,
            unique_templates=len(templates),
        )

    def _fetch_reviews_with_responses(self, competitor_id: int, source: str = None) -> List[Dict]:
        """Fetch reviews with response data from database."""
        session = create_session()
        try:
            query = """
                SELECT id, source, rating, review_text, review_date,
                       owner_response_text, owner_response_date
                FROM competitor_reviews
                WHERE competitor_id = :competitor_id
            """
            params = {"competitor_id": competitor_id}

            if source:
                query += " AND source = :source"
                params["source"] = source

            result = session.execute(text(query), params).fetchall()
            return [
                {
                    "id": r[0],
                    "source": r[1],
                    "rating": r[2],
                    "review_text": r[3],
                    "review_date": r[4],
                    "owner_response": r[5],
                    "response_date": r[6],
                }
                for r in result
            ]
        finally:
            session.close()

    def _detect_templates(self, responses: List[str]) -> List[str]:
        """
        Detect template responses using similarity grouping.

        Returns:
            List of template fingerprints
        """
        if not responses:
            return []

        templates = []
        template_groups = defaultdict(list)

        for response in responses:
            if not response or len(response) < self.min_response_length:
                continue

            # Create normalized fingerprint
            fingerprint = self._create_fingerprint(response)

            # Check against existing templates
            matched = False
            for template_fp in templates:
                if self._fingerprint_similarity(fingerprint, template_fp) >= self.similarity_threshold:
                    template_groups[template_fp].append(response)
                    matched = True
                    break

            if not matched:
                templates.append(fingerprint)
                template_groups[fingerprint].append(response)

        # Only return templates that appear 3+ times
        return [fp for fp, group in template_groups.items() if len(group) >= 3]

    def _create_fingerprint(self, text: str) -> str:
        """Create a normalized fingerprint for template detection."""
        # Normalize: lowercase, remove names/numbers, collapse whitespace
        normalized = text.lower()

        # Remove common variable parts
        normalized = re.sub(r'\b(hi|hello|dear|thanks?|thank you)\s+\w+\b', 'GREETING', normalized)
        normalized = re.sub(r'\b\d+\b', 'NUM', normalized)
        normalized = re.sub(r'\b\w+@\w+\.\w+\b', 'EMAIL', normalized)
        normalized = re.sub(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', 'PHONE', normalized)

        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        # Create hash
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def _fingerprint_similarity(self, fp1: str, fp2: str) -> float:
        """Compare fingerprints for similarity."""
        # Simple character-level similarity
        if fp1 == fp2:
            return 1.0

        matches = sum(c1 == c2 for c1, c2 in zip(fp1, fp2))
        return matches / max(len(fp1), len(fp2))

    def _is_templated(self, response: str, templates: List[str]) -> bool:
        """Check if a response matches any template."""
        if not response or len(response) < self.min_response_length:
            return False

        fingerprint = self._create_fingerprint(response)
        for template_fp in templates:
            if self._fingerprint_similarity(fingerprint, template_fp) >= self.similarity_threshold:
                return True
        return False

    def identify_response_patterns(self, competitor_id: int) -> Dict:
        """
        Identify patterns in owner responses.

        Returns:
            Dict with pattern analysis
        """
        reviews = self._fetch_reviews_with_responses(competitor_id)
        with_response = [r for r in reviews if r.get("owner_response")]

        if not with_response:
            return {"patterns_found": False}

        # Analyze response patterns
        response_lengths = [len(r["owner_response"]) for r in with_response]
        avg_length = sum(response_lengths) / len(response_lengths)

        # Check response consistency by rating
        by_rating = defaultdict(list)
        for r in with_response:
            rating = r.get("rating", 0)
            by_rating[rating].append(r["owner_response"])

        # Calculate response rate by rating bucket
        rating_response_rates = {}
        for rating in [1, 2, 3, 4, 5]:
            rating_reviews = [r for r in reviews if r.get("rating") == rating]
            rating_with_response = [r for r in rating_reviews if r.get("owner_response")]
            if rating_reviews:
                rating_response_rates[rating] = round(
                    len(rating_with_response) / len(rating_reviews) * 100, 1
                )

        # Detect common phrases
        common_phrases = self._find_common_phrases([r["owner_response"] for r in with_response])

        return {
            "patterns_found": True,
            "total_responses": len(with_response),
            "avg_response_length": round(avg_length),
            "response_rate_by_rating": rating_response_rates,
            "common_phrases": common_phrases[:10],
            "prioritizes_negative": rating_response_rates.get(1, 0) > rating_response_rates.get(5, 0),
        }

    def _find_common_phrases(self, responses: List[str], min_count: int = 3) -> List[Tuple[str, int]]:
        """Find commonly used phrases in responses."""
        phrase_counts = defaultdict(int)

        for response in responses:
            if not response:
                continue

            # Extract 3-5 word phrases
            words = response.lower().split()
            for n in [3, 4, 5]:
                for i in range(len(words) - n + 1):
                    phrase = ' '.join(words[i:i+n])
                    phrase_counts[phrase] += 1

        # Filter and sort
        common = [(phrase, count) for phrase, count in phrase_counts.items() if count >= min_count]
        return sorted(common, key=lambda x: x[1], reverse=True)

    def save_metrics(self, metrics: ResponseMetrics):
        """Save response metrics to database."""
        session = create_session()
        try:
            # Update competitor_review_stats table
            session.execute(text("""
                INSERT INTO competitor_review_stats (
                    competitor_id, total_reviews, reviews_with_response,
                    response_rate, response_rate_positive, response_rate_negative,
                    avg_response_time_days, template_usage_pct
                ) VALUES (
                    :competitor_id, :total_reviews, :reviews_with_response,
                    :response_rate, :response_rate_positive, :response_rate_negative,
                    :avg_response_time_days, :template_usage_pct
                )
                ON CONFLICT (competitor_id) DO UPDATE SET
                    total_reviews = EXCLUDED.total_reviews,
                    reviews_with_response = EXCLUDED.reviews_with_response,
                    response_rate = EXCLUDED.response_rate,
                    response_rate_positive = EXCLUDED.response_rate_positive,
                    response_rate_negative = EXCLUDED.response_rate_negative,
                    avg_response_time_days = EXCLUDED.avg_response_time_days,
                    template_usage_pct = EXCLUDED.template_usage_pct,
                    updated_at = NOW()
            """), {
                "competitor_id": metrics.competitor_id,
                "total_reviews": metrics.total_reviews,
                "reviews_with_response": metrics.reviews_with_response,
                "response_rate": metrics.response_rate,
                "response_rate_positive": metrics.response_rate_positive,
                "response_rate_negative": metrics.response_rate_negative,
                "avg_response_time_days": metrics.avg_response_time_days,
                "template_usage_pct": metrics.template_usage_pct,
            })
            session.commit()
            logger.info(f"Saved response metrics for competitor {metrics.competitor_id}")
        except Exception as e:
            logger.error(f"Failed to save response metrics: {e}")
            session.rollback()
        finally:
            session.close()


def analyze_owner_responses(competitor_id: int, source: str = None) -> ResponseMetrics:
    """
    Convenience function to analyze owner responses.

    Args:
        competitor_id: The competitor to analyze
        source: Optional source filter

    Returns:
        ResponseMetrics
    """
    tracker = ResponseTracker()
    return tracker.analyze_responses(competitor_id, source)
