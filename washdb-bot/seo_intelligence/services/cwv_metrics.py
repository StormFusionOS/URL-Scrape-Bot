"""
Core Web Vitals Metrics Service

Defines thresholds and scoring for Core Web Vitals measurements.

Metrics tracked:
- LCP (Largest Contentful Paint): Measures loading performance
- CLS (Cumulative Layout Shift): Measures visual stability
- FID (First Input Delay): Measures interactivity (simulated via click)
- FCP (First Contentful Paint): First paint with content
- TTI (Time to Interactive): When page becomes interactive
- TTFB (Time to First Byte): Server response time

Thresholds based on Google's Core Web Vitals guidelines:
https://web.dev/vitals/

Usage:
    from seo_intelligence.services.cwv_metrics import CWVMetricsService

    service = CWVMetricsService()
    lcp_rating = service.rate_lcp(2500)  # "GOOD"
    cwv_score = service.calculate_cwv_score(lcp_ms=2500, cls=0.05, fid_ms=50)
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
from enum import Enum


class CWVRating(Enum):
    """Core Web Vitals rating levels."""
    GOOD = "GOOD"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    POOR = "POOR"


@dataclass
class CWVThresholds:
    """Thresholds for a single CWV metric."""
    good_max: float  # Up to this value is GOOD
    needs_improvement_max: float  # Up to this value is NEEDS_IMPROVEMENT, above is POOR
    unit: str  # ms, score, etc.


# Google's official Core Web Vitals thresholds
# Source: https://web.dev/vitals/
CWV_THRESHOLDS = {
    "lcp": CWVThresholds(
        good_max=2500,  # 2.5s
        needs_improvement_max=4000,  # 4.0s
        unit="ms"
    ),
    "cls": CWVThresholds(
        good_max=0.1,
        needs_improvement_max=0.25,
        unit="score"
    ),
    "fid": CWVThresholds(
        good_max=100,  # 100ms
        needs_improvement_max=300,  # 300ms
        unit="ms"
    ),
    # Additional performance metrics
    "fcp": CWVThresholds(
        good_max=1800,  # 1.8s
        needs_improvement_max=3000,  # 3.0s
        unit="ms"
    ),
    "tti": CWVThresholds(
        good_max=3800,  # 3.8s
        needs_improvement_max=7300,  # 7.3s
        unit="ms"
    ),
    "ttfb": CWVThresholds(
        good_max=800,  # 800ms
        needs_improvement_max=1800,  # 1.8s
        unit="ms"
    ),
}


class CWVMetricsService:
    """
    Service for rating and scoring Core Web Vitals measurements.

    Provides:
    - Individual metric rating (GOOD, NEEDS_IMPROVEMENT, POOR)
    - Composite CWV score (0-100)
    - Issue detection and recommendations
    """

    def __init__(self):
        """Initialize CWV metrics service."""
        self.thresholds = CWV_THRESHOLDS

    def rate_metric(self, metric_name: str, value: float) -> CWVRating:
        """
        Rate a single metric value.

        Args:
            metric_name: Metric name (lcp, cls, fid, fcp, tti, ttfb)
            value: Measured value

        Returns:
            CWVRating: GOOD, NEEDS_IMPROVEMENT, or POOR
        """
        if metric_name not in self.thresholds:
            raise ValueError(f"Unknown metric: {metric_name}")

        threshold = self.thresholds[metric_name]

        if value <= threshold.good_max:
            return CWVRating.GOOD
        elif value <= threshold.needs_improvement_max:
            return CWVRating.NEEDS_IMPROVEMENT
        else:
            return CWVRating.POOR

    def rate_lcp(self, lcp_ms: float) -> CWVRating:
        """Rate Largest Contentful Paint."""
        return self.rate_metric("lcp", lcp_ms)

    def rate_cls(self, cls_value: float) -> CWVRating:
        """Rate Cumulative Layout Shift."""
        return self.rate_metric("cls", cls_value)

    def rate_fid(self, fid_ms: float) -> CWVRating:
        """Rate First Input Delay."""
        return self.rate_metric("fid", fid_ms)

    def rate_fcp(self, fcp_ms: float) -> CWVRating:
        """Rate First Contentful Paint."""
        return self.rate_metric("fcp", fcp_ms)

    def rate_tti(self, tti_ms: float) -> CWVRating:
        """Rate Time to Interactive."""
        return self.rate_metric("tti", tti_ms)

    def rate_ttfb(self, ttfb_ms: float) -> CWVRating:
        """Rate Time to First Byte."""
        return self.rate_metric("ttfb", ttfb_ms)

    def calculate_metric_score(self, metric_name: str, value: float) -> float:
        """
        Calculate a 0-100 score for a single metric.

        Score mapping:
        - GOOD range: 70-100
        - NEEDS_IMPROVEMENT range: 40-69
        - POOR range: 0-39

        Args:
            metric_name: Metric name
            value: Measured value

        Returns:
            float: Score from 0-100
        """
        if metric_name not in self.thresholds:
            raise ValueError(f"Unknown metric: {metric_name}")

        threshold = self.thresholds[metric_name]

        # GOOD: Map 0 -> 100, good_max -> 70
        if value <= threshold.good_max:
            score = 100 - (value / threshold.good_max) * 30
            return max(70, min(100, score))

        # NEEDS_IMPROVEMENT: Map good_max -> 70, needs_improvement_max -> 40
        elif value <= threshold.needs_improvement_max:
            range_size = threshold.needs_improvement_max - threshold.good_max
            progress = (value - threshold.good_max) / range_size
            score = 70 - progress * 30
            return max(40, min(69, score))

        # POOR: Map needs_improvement_max -> 40, 2x needs_improvement_max -> 0
        else:
            range_size = threshold.needs_improvement_max  # Same size as poor threshold
            progress = (value - threshold.needs_improvement_max) / range_size
            score = 40 - progress * 40
            return max(0, min(39, score))

    def calculate_cwv_score(
        self,
        lcp_ms: Optional[float] = None,
        cls_value: Optional[float] = None,
        fid_ms: Optional[float] = None,
        fcp_ms: Optional[float] = None,
        tti_ms: Optional[float] = None,
        ttfb_ms: Optional[float] = None,
    ) -> float:
        """
        Calculate composite Core Web Vitals score (0-100).

        Weights:
        - LCP: 35% (loading performance)
        - CLS: 25% (visual stability)
        - FID: 25% (interactivity)
        - FCP: 5% (bonus metric)
        - TTI: 5% (bonus metric)
        - TTFB: 5% (bonus metric)

        Args:
            lcp_ms: Largest Contentful Paint in milliseconds
            cls_value: Cumulative Layout Shift score
            fid_ms: First Input Delay in milliseconds
            fcp_ms: First Contentful Paint in milliseconds (optional)
            tti_ms: Time to Interactive in milliseconds (optional)
            ttfb_ms: Time to First Byte in milliseconds (optional)

        Returns:
            float: Composite score from 0-100
        """
        # Core metrics (must have at least LCP or CLS)
        scores = []
        weights = []

        # Primary CWV metrics (85% weight)
        if lcp_ms is not None:
            scores.append(self.calculate_metric_score("lcp", lcp_ms))
            weights.append(0.35)

        if cls_value is not None:
            scores.append(self.calculate_metric_score("cls", cls_value))
            weights.append(0.25)

        if fid_ms is not None:
            scores.append(self.calculate_metric_score("fid", fid_ms))
            weights.append(0.25)

        # Secondary metrics (15% weight, optional)
        if fcp_ms is not None:
            scores.append(self.calculate_metric_score("fcp", fcp_ms))
            weights.append(0.05)

        if tti_ms is not None:
            scores.append(self.calculate_metric_score("tti", tti_ms))
            weights.append(0.05)

        if ttfb_ms is not None:
            scores.append(self.calculate_metric_score("ttfb", ttfb_ms))
            weights.append(0.05)

        if not scores:
            return 0.0

        # Normalize weights to sum to 1.0
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]

        # Calculate weighted average
        weighted_score = sum(s * w for s, w in zip(scores, normalized_weights))

        return round(weighted_score, 2)

    def get_cwv_assessment(
        self,
        lcp_ms: Optional[float] = None,
        cls_value: Optional[float] = None,
        fid_ms: Optional[float] = None,
    ) -> Tuple[str, Dict[str, CWVRating]]:
        """
        Get overall CWV assessment (PASSED, NEEDS_IMPROVEMENT, FAILED).

        Per Google's guidelines:
        - PASSED: All three metrics are GOOD
        - FAILED: Any metric is POOR
        - NEEDS_IMPROVEMENT: Otherwise

        Args:
            lcp_ms: Largest Contentful Paint
            cls_value: Cumulative Layout Shift
            fid_ms: First Input Delay

        Returns:
            Tuple of (assessment, {metric: rating})
        """
        ratings = {}

        if lcp_ms is not None:
            ratings["lcp"] = self.rate_lcp(lcp_ms)

        if cls_value is not None:
            ratings["cls"] = self.rate_cls(cls_value)

        if fid_ms is not None:
            ratings["fid"] = self.rate_fid(fid_ms)

        if not ratings:
            return "UNKNOWN", ratings

        # Check for any POOR ratings -> FAILED
        if any(r == CWVRating.POOR for r in ratings.values()):
            return "FAILED", ratings

        # Check if all are GOOD -> PASSED
        if all(r == CWVRating.GOOD for r in ratings.values()):
            return "PASSED", ratings

        # Otherwise -> NEEDS_IMPROVEMENT
        return "NEEDS_IMPROVEMENT", ratings

    def generate_issues(
        self,
        lcp_ms: Optional[float] = None,
        cls_value: Optional[float] = None,
        fid_ms: Optional[float] = None,
        fcp_ms: Optional[float] = None,
        tti_ms: Optional[float] = None,
        ttfb_ms: Optional[float] = None,
        lcp_element: Optional[str] = None,
    ) -> list:
        """
        Generate audit issues for CWV problems.

        Args:
            lcp_ms: Largest Contentful Paint
            cls_value: Cumulative Layout Shift
            fid_ms: First Input Delay
            fcp_ms: First Contentful Paint
            tti_ms: Time to Interactive
            ttfb_ms: Time to First Byte
            lcp_element: CSS selector of LCP element

        Returns:
            List of issue dicts for audit_issues table
        """
        issues = []

        # LCP issues
        if lcp_ms is not None:
            rating = self.rate_lcp(lcp_ms)
            if rating != CWVRating.GOOD:
                severity = "critical" if rating == CWVRating.POOR else "warning"
                issues.append({
                    "severity": severity,
                    "category": "performance",
                    "issue_type": "slow_lcp",
                    "description": f"Largest Contentful Paint is {lcp_ms:.0f}ms ({rating.value}). Target: <2500ms.",
                    "element": lcp_element,
                    "recommendation": (
                        "Optimize LCP by: 1) Preloading critical resources, "
                        "2) Optimizing images (compression, modern formats), "
                        "3) Reducing server response time, "
                        "4) Using efficient caching"
                    ),
                    "metadata": {"lcp_ms": lcp_ms, "rating": rating.value}
                })

        # CLS issues
        if cls_value is not None:
            rating = self.rate_cls(cls_value)
            if rating != CWVRating.GOOD:
                severity = "critical" if rating == CWVRating.POOR else "warning"
                issues.append({
                    "severity": severity,
                    "category": "performance",
                    "issue_type": "high_cls",
                    "description": f"Cumulative Layout Shift is {cls_value:.3f} ({rating.value}). Target: <0.1.",
                    "element": None,
                    "recommendation": (
                        "Reduce CLS by: 1) Setting explicit dimensions on images/videos, "
                        "2) Reserving space for ads/embeds, "
                        "3) Avoiding DOM insertions above existing content, "
                        "4) Using CSS transforms instead of layout-triggering properties"
                    ),
                    "metadata": {"cls_value": cls_value, "rating": rating.value}
                })

        # FID issues
        if fid_ms is not None:
            rating = self.rate_fid(fid_ms)
            if rating != CWVRating.GOOD:
                severity = "critical" if rating == CWVRating.POOR else "warning"
                issues.append({
                    "severity": severity,
                    "category": "performance",
                    "issue_type": "slow_fid",
                    "description": f"First Input Delay is {fid_ms:.0f}ms ({rating.value}). Target: <100ms.",
                    "element": None,
                    "recommendation": (
                        "Improve FID by: 1) Breaking up long JavaScript tasks, "
                        "2) Using web workers for heavy processing, "
                        "3) Reducing third-party script impact, "
                        "4) Implementing code splitting"
                    ),
                    "metadata": {"fid_ms": fid_ms, "rating": rating.value}
                })

        # TTFB issues (impacts all other metrics)
        if ttfb_ms is not None:
            rating = self.rate_ttfb(ttfb_ms)
            if rating != CWVRating.GOOD:
                severity = "warning" if rating == CWVRating.NEEDS_IMPROVEMENT else "critical"
                issues.append({
                    "severity": severity,
                    "category": "performance",
                    "issue_type": "slow_ttfb",
                    "description": f"Time to First Byte is {ttfb_ms:.0f}ms ({rating.value}). Target: <800ms.",
                    "element": None,
                    "recommendation": (
                        "Reduce TTFB by: 1) Optimizing server processing, "
                        "2) Using CDN for static content, "
                        "3) Implementing effective caching, "
                        "4) Reducing redirects"
                    ),
                    "metadata": {"ttfb_ms": ttfb_ms, "rating": rating.value}
                })

        # TTI issues
        if tti_ms is not None:
            rating = self.rate_tti(tti_ms)
            if rating != CWVRating.GOOD:
                severity = "warning" if rating == CWVRating.NEEDS_IMPROVEMENT else "critical"
                issues.append({
                    "severity": severity,
                    "category": "performance",
                    "issue_type": "slow_tti",
                    "description": f"Time to Interactive is {tti_ms:.0f}ms ({rating.value}). Target: <3800ms.",
                    "element": None,
                    "recommendation": (
                        "Improve TTI by: 1) Minimizing main-thread work, "
                        "2) Reducing JavaScript execution time, "
                        "3) Keeping request counts low, "
                        "4) Minimizing transfer sizes"
                    ),
                    "metadata": {"tti_ms": tti_ms, "rating": rating.value}
                })

        return issues


# Module-level singleton
_cwv_metrics_service_instance = None


def get_cwv_metrics_service() -> CWVMetricsService:
    """Get or create the singleton CWVMetricsService instance."""
    global _cwv_metrics_service_instance

    if _cwv_metrics_service_instance is None:
        _cwv_metrics_service_instance = CWVMetricsService()

    return _cwv_metrics_service_instance
