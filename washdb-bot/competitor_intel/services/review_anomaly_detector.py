"""
Review Anomaly Detector

Detects suspicious patterns in competitor reviews:
- Same-day review spikes
- Burst patterns (unusual velocity)
- Generic/templated reviews
- New reviewer clusters
- Rating distribution anomalies
"""

import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from sqlalchemy import text

from competitor_intel.config import ANOMALY_THRESHOLDS
from db.database_manager import create_session

logger = logging.getLogger(__name__)


@dataclass
class ReviewAnomaly:
    """Represents a detected review anomaly."""
    anomaly_type: str
    severity: str  # low, medium, high, critical
    description: str
    evidence: Dict = field(default_factory=dict)
    affected_reviews: List[int] = field(default_factory=list)
    detected_at: datetime = field(default_factory=datetime.now)


@dataclass
class AnomalyReport:
    """Complete anomaly report for a competitor."""
    competitor_id: int
    total_reviews_analyzed: int
    suspicious_count: int
    suspicious_pct: float
    anomalies: List[ReviewAnomaly] = field(default_factory=list)
    solicitation_campaigns: List[Dict] = field(default_factory=list)


class ReviewAnomalyDetector:
    """
    Detects suspicious patterns in competitor reviews.

    Analyzes:
    - Temporal patterns (spikes, bursts)
    - Content patterns (generic text, templates)
    - Reviewer patterns (new accounts, clusters)
    - Rating distributions
    """

    def __init__(self):
        self.spike_threshold = ANOMALY_THRESHOLDS.get("spike_threshold", 5)
        self.burst_multiplier = ANOMALY_THRESHOLDS.get("burst_multiplier", 3.0)
        self.template_similarity = ANOMALY_THRESHOLDS.get("template_similarity", 0.85)
        self.new_reviewer_pct = ANOMALY_THRESHOLDS.get("new_reviewer_pct", 0.5)

        logger.info("ReviewAnomalyDetector initialized")

    def analyze_competitor(self, competitor_id: int, source: str = None) -> AnomalyReport:
        """
        Analyze all reviews for a competitor for anomalies.

        Args:
            competitor_id: The competitor to analyze
            source: Optional filter by source (google, yelp, etc.)

        Returns:
            AnomalyReport with detected anomalies
        """
        # Fetch reviews from database
        reviews = self._fetch_reviews(competitor_id, source)

        if not reviews:
            return AnomalyReport(
                competitor_id=competitor_id,
                total_reviews_analyzed=0,
                suspicious_count=0,
                suspicious_pct=0.0,
            )

        anomalies = []

        # Check for various anomaly types
        anomalies.extend(self._detect_same_day_spikes(reviews))
        anomalies.extend(self._detect_burst_patterns(reviews))
        anomalies.extend(self._detect_generic_reviews(reviews))
        anomalies.extend(self._detect_new_reviewer_clusters(reviews))
        anomalies.extend(self._detect_rating_anomalies(reviews))

        # Count suspicious reviews
        suspicious_ids = set()
        for anomaly in anomalies:
            suspicious_ids.update(anomaly.affected_reviews)

        # Detect solicitation campaigns (date ranges with unusual activity)
        campaigns = self._detect_solicitation_campaigns(reviews, anomalies)

        return AnomalyReport(
            competitor_id=competitor_id,
            total_reviews_analyzed=len(reviews),
            suspicious_count=len(suspicious_ids),
            suspicious_pct=round(len(suspicious_ids) / len(reviews) * 100, 1) if reviews else 0.0,
            anomalies=anomalies,
            solicitation_campaigns=campaigns,
        )

    def _fetch_reviews(self, competitor_id: int, source: str = None) -> List[Dict]:
        """Fetch reviews from database."""
        session = create_session()
        try:
            query = """
                SELECT id, source, rating, review_text, review_date,
                       reviewer_display, reviewer_review_count, is_suspicious
                FROM competitor_reviews
                WHERE competitor_id = :competitor_id
            """
            params = {"competitor_id": competitor_id}

            if source:
                query += " AND source = :source"
                params["source"] = source

            query += " ORDER BY review_date DESC"

            result = session.execute(text(query), params).fetchall()
            return [
                {
                    "id": r[0],
                    "source": r[1],
                    "rating": r[2],
                    "review_text": r[3],
                    "review_date": r[4],
                    "reviewer_display": r[5],
                    "reviewer_review_count": r[6],
                    "is_suspicious": r[7],
                }
                for r in result
            ]
        finally:
            session.close()

    def _detect_same_day_spikes(self, reviews: List[Dict]) -> List[ReviewAnomaly]:
        """Detect days with unusually high review counts."""
        anomalies = []

        # Group by date
        reviews_by_date = defaultdict(list)
        for r in reviews:
            if r["review_date"]:
                reviews_by_date[r["review_date"]].append(r)

        # Find spike days
        for date, day_reviews in reviews_by_date.items():
            if len(day_reviews) >= self.spike_threshold:
                # Check if they're all 5-star
                all_five_star = all(r["rating"] == 5 for r in day_reviews)

                severity = "high" if all_five_star else "medium"
                description = f"{len(day_reviews)} reviews on {date}"
                if all_five_star:
                    description += " (all 5-star)"

                anomalies.append(ReviewAnomaly(
                    anomaly_type="same_day_spike",
                    severity=severity,
                    description=description,
                    evidence={
                        "date": str(date),
                        "count": len(day_reviews),
                        "all_five_star": all_five_star,
                    },
                    affected_reviews=[r["id"] for r in day_reviews],
                ))

        return anomalies

    def _detect_burst_patterns(self, reviews: List[Dict]) -> List[ReviewAnomaly]:
        """Detect unusual spikes in review velocity."""
        anomalies = []

        if len(reviews) < 10:
            return anomalies

        # Calculate rolling 7-day counts
        reviews_with_dates = [r for r in reviews if r["review_date"]]
        if not reviews_with_dates:
            return anomalies

        reviews_with_dates.sort(key=lambda x: x["review_date"])

        # Get average velocity
        if len(reviews_with_dates) < 2:
            return anomalies

        date_range = (reviews_with_dates[-1]["review_date"] - reviews_with_dates[0]["review_date"]).days
        if date_range <= 0:
            return anomalies

        avg_per_week = len(reviews_with_dates) / (date_range / 7)

        # Check 7-day windows for bursts
        for i, review in enumerate(reviews_with_dates):
            window_start = review["review_date"]
            window_end = window_start + timedelta(days=7)

            window_reviews = [
                r for r in reviews_with_dates
                if window_start <= r["review_date"] <= window_end
            ]

            if len(window_reviews) >= avg_per_week * self.burst_multiplier:
                anomalies.append(ReviewAnomaly(
                    anomaly_type="burst_pattern",
                    severity="medium",
                    description=f"Burst of {len(window_reviews)} reviews in 7 days (avg: {avg_per_week:.1f}/week)",
                    evidence={
                        "window_start": str(window_start),
                        "window_end": str(window_end),
                        "count": len(window_reviews),
                        "avg_per_week": round(avg_per_week, 2),
                    },
                    affected_reviews=[r["id"] for r in window_reviews],
                ))
                break  # Only report first burst to avoid duplicates

        return anomalies

    def _detect_generic_reviews(self, reviews: List[Dict]) -> List[ReviewAnomaly]:
        """Detect very short or generic review text."""
        anomalies = []
        generic_reviews = []

        # Patterns for generic reviews
        generic_patterns = [
            r'^great\.?$',
            r'^excellent\.?$',
            r'^good job\.?$',
            r'^recommend\.?$',
            r'^highly recommend\.?$',
            r'^5 stars?\.?$',
            r'^a{2,}\s*$',  # Just "aaa" or similar
        ]

        import re
        combined_pattern = re.compile('|'.join(generic_patterns), re.IGNORECASE)

        for r in reviews:
            text = (r.get("review_text") or "").strip()

            # Check for very short reviews
            if len(text) < 15:
                generic_reviews.append(r)
                continue

            # Check for generic patterns
            if combined_pattern.match(text):
                generic_reviews.append(r)

        if len(generic_reviews) >= 3:
            anomalies.append(ReviewAnomaly(
                anomaly_type="generic_text",
                severity="low",
                description=f"{len(generic_reviews)} very short or generic reviews",
                evidence={
                    "count": len(generic_reviews),
                    "examples": [r.get("review_text", "")[:50] for r in generic_reviews[:3]],
                },
                affected_reviews=[r["id"] for r in generic_reviews],
            ))

        return anomalies

    def _detect_new_reviewer_clusters(self, reviews: List[Dict]) -> List[ReviewAnomaly]:
        """Detect high percentage of reviews from accounts with only 1 review."""
        anomalies = []

        # Count reviews from new accounts
        new_reviewer_reviews = [
            r for r in reviews
            if r.get("reviewer_review_count") is not None and r["reviewer_review_count"] <= 1
        ]

        if len(reviews) < 5:
            return anomalies

        pct_new = len(new_reviewer_reviews) / len(reviews)

        if pct_new >= self.new_reviewer_pct:
            anomalies.append(ReviewAnomaly(
                anomaly_type="new_reviewer_cluster",
                severity="medium",
                description=f"{pct_new:.0%} of reviews from accounts with only 1 review",
                evidence={
                    "count": len(new_reviewer_reviews),
                    "total": len(reviews),
                    "percentage": round(pct_new * 100, 1),
                },
                affected_reviews=[r["id"] for r in new_reviewer_reviews],
            ))

        return anomalies

    def _detect_rating_anomalies(self, reviews: List[Dict]) -> List[ReviewAnomaly]:
        """Detect unnatural rating distributions."""
        anomalies = []

        if len(reviews) < 10:
            return anomalies

        # Count ratings
        rating_counts = defaultdict(int)
        for r in reviews:
            if r.get("rating"):
                rating_counts[r["rating"]] += 1

        total = sum(rating_counts.values())
        if total == 0:
            return anomalies

        # Check for all 5-star reviews
        pct_five_star = rating_counts[5] / total

        if pct_five_star >= 0.95 and total >= 20:
            anomalies.append(ReviewAnomaly(
                anomaly_type="rating_distribution_anomaly",
                severity="high",
                description=f"{pct_five_star:.0%} of reviews are 5-star (suspicious)",
                evidence={
                    "distribution": dict(rating_counts),
                    "pct_five_star": round(pct_five_star * 100, 1),
                    "total": total,
                },
                affected_reviews=[r["id"] for r in reviews if r.get("rating") == 5],
            ))

        # Check for missing middle ratings (only 1s and 5s)
        middle_ratings = sum(rating_counts[r] for r in [2, 3, 4])
        if total >= 20 and middle_ratings == 0 and rating_counts[1] > 0 and rating_counts[5] > 0:
            anomalies.append(ReviewAnomaly(
                anomaly_type="rating_distribution_anomaly",
                severity="medium",
                description="No reviews with 2-4 stars (polarized distribution)",
                evidence={
                    "distribution": dict(rating_counts),
                },
                affected_reviews=[],
            ))

        return anomalies

    def _detect_solicitation_campaigns(
        self, reviews: List[Dict], anomalies: List[ReviewAnomaly]
    ) -> List[Dict]:
        """Identify potential solicitation campaigns based on anomaly clusters."""
        campaigns = []

        # Find date ranges with multiple anomalies
        spike_dates = []
        for a in anomalies:
            if a.anomaly_type in ["same_day_spike", "burst_pattern"]:
                if "date" in a.evidence:
                    spike_dates.append(a.evidence["date"])
                elif "window_start" in a.evidence:
                    spike_dates.append(a.evidence["window_start"])

        # Group nearby dates into campaigns
        if spike_dates:
            spike_dates = sorted(set(spike_dates))
            for date_str in spike_dates:
                campaigns.append({
                    "start_date": date_str,
                    "description": "Potential review solicitation campaign detected",
                    "confidence": "medium",
                })

        return campaigns

    def mark_suspicious_reviews(self, competitor_id: int, review_ids: List[int], reason: str):
        """Mark specific reviews as suspicious in the database."""
        if not review_ids:
            return

        session = create_session()
        try:
            session.execute(text("""
                UPDATE competitor_reviews
                SET is_suspicious = true,
                    suspicious_reason = :reason
                WHERE id = ANY(:ids)
            """), {
                "ids": review_ids,
                "reason": reason,
            })
            session.commit()
            logger.info(f"Marked {len(review_ids)} reviews as suspicious for competitor {competitor_id}")
        except Exception as e:
            logger.error(f"Failed to mark suspicious reviews: {e}")
            session.rollback()
        finally:
            session.close()


def detect_review_anomalies(competitor_id: int, source: str = None) -> AnomalyReport:
    """
    Convenience function to detect anomalies for a competitor.

    Args:
        competitor_id: The competitor to analyze
        source: Optional filter by source

    Returns:
        AnomalyReport
    """
    detector = ReviewAnomalyDetector()
    return detector.analyze_competitor(competitor_id, source)
