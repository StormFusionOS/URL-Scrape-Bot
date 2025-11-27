"""
Search Volume Estimator Service

Estimates relative search volume using SERP signals without external APIs.
Uses multiple signals to create a composite volume score.

Volume Signals Used:
- SERP features (ads, shopping, featured snippets)
- Number of search results
- Autocomplete suggestion position
- Related searches count
- Domain competition level
- CPC indicators (ad presence)

Usage:
    from seo_intelligence.services.volume_estimator import VolumeEstimator

    estimator = VolumeEstimator()
    volume = estimator.estimate_volume(serp_data)

Volume Categories:
- VERY_HIGH: 10,000+ monthly searches
- HIGH: 1,000-10,000 monthly searches
- MEDIUM: 100-1,000 monthly searches
- LOW: 10-100 monthly searches
- VERY_LOW: <10 monthly searches
"""

import re
import math
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from runner.logging_setup import get_logger


class VolumeCategory(Enum):
    """Search volume categories."""
    VERY_HIGH = "VERY_HIGH"    # 10,000+ monthly
    HIGH = "HIGH"              # 1,000-10,000 monthly
    MEDIUM = "MEDIUM"          # 100-1,000 monthly
    LOW = "LOW"                # 10-100 monthly
    VERY_LOW = "VERY_LOW"      # <10 monthly


@dataclass
class VolumeEstimate:
    """Search volume estimation result."""
    keyword: str
    volume_score: float  # 0-100 composite score
    category: VolumeCategory
    estimated_monthly_min: int
    estimated_monthly_max: int
    confidence: float  # 0-1 confidence in estimate
    signals: Dict[str, Any] = field(default_factory=dict)
    estimated_at: datetime = field(default_factory=datetime.now)


class VolumeEstimator:
    """
    Estimates search volume using SERP signals.

    Uses a weighted scoring system based on observable SERP features.
    Higher scores indicate higher search volume.
    """

    # Volume category thresholds (score -> category)
    CATEGORY_THRESHOLDS = {
        80: VolumeCategory.VERY_HIGH,
        60: VolumeCategory.HIGH,
        40: VolumeCategory.MEDIUM,
        20: VolumeCategory.LOW,
        0: VolumeCategory.VERY_LOW,
    }

    # Estimated volume ranges per category
    VOLUME_RANGES = {
        VolumeCategory.VERY_HIGH: (10000, 100000),
        VolumeCategory.HIGH: (1000, 10000),
        VolumeCategory.MEDIUM: (100, 1000),
        VolumeCategory.LOW: (10, 100),
        VolumeCategory.VERY_LOW: (0, 10),
    }

    # Signal weights (must sum to 1.0)
    SIGNAL_WEIGHTS = {
        "ads_present": 0.15,           # Ads indicate commercial intent & volume
        "ad_count": 0.10,              # More ads = higher volume
        "shopping_present": 0.12,      # Shopping = high commercial volume
        "featured_snippet": 0.08,      # Featured snippet = high volume
        "people_also_ask": 0.08,       # PAA = high volume
        "result_count": 0.12,          # Total results
        "brand_results": 0.10,         # Known brands ranking = volume
        "autocomplete_position": 0.10, # Higher position = more searches
        "related_searches": 0.08,      # Related searches count
        "knowledge_panel": 0.07,       # Knowledge panel = high volume
    }

    # Known high-authority domains (indicates competitive keyword)
    HIGH_AUTHORITY_DOMAINS = {
        "wikipedia.org", "amazon.com", "ebay.com", "facebook.com",
        "twitter.com", "instagram.com", "linkedin.com", "youtube.com",
        "yelp.com", "tripadvisor.com", "nytimes.com", "forbes.com",
        "bbc.com", "cnn.com", "reddit.com", "quora.com",
        "webmd.com", "healthline.com", "mayoclinic.org",
        "homedepot.com", "lowes.com", "walmart.com", "target.com",
    }

    def __init__(self):
        """Initialize volume estimator."""
        self.logger = get_logger("volume_estimator")

    def _score_ads_present(self, serp_data: Dict) -> float:
        """
        Score based on presence of ads.

        Ads indicate advertisers consider the keyword valuable.

        Returns:
            float: 0-100 score
        """
        has_ads = serp_data.get("has_ads", False)
        return 100.0 if has_ads else 0.0

    def _score_ad_count(self, serp_data: Dict) -> float:
        """
        Score based on number of ads.

        More ads = more competition = higher volume keyword.

        Returns:
            float: 0-100 score
        """
        ad_count = serp_data.get("ad_count", 0)

        if ad_count >= 4:
            return 100.0
        elif ad_count == 3:
            return 80.0
        elif ad_count == 2:
            return 60.0
        elif ad_count == 1:
            return 40.0
        return 0.0

    def _score_shopping_present(self, serp_data: Dict) -> float:
        """
        Score based on shopping results presence.

        Shopping results indicate high commercial volume.

        Returns:
            float: 0-100 score
        """
        has_shopping = serp_data.get("has_shopping", False)
        return 100.0 if has_shopping else 0.0

    def _score_featured_snippet(self, serp_data: Dict) -> float:
        """
        Score based on featured snippet presence.

        Google only shows featured snippets for high-volume queries.

        Returns:
            float: 0-100 score
        """
        has_snippet = serp_data.get("has_featured_snippet", False)
        return 100.0 if has_snippet else 30.0  # Base score for no snippet

    def _score_people_also_ask(self, serp_data: Dict) -> float:
        """
        Score based on People Also Ask presence.

        PAA indicates Google has data on related queries = volume.

        Returns:
            float: 0-100 score
        """
        has_paa = serp_data.get("has_people_also_ask", False)
        paa_count = serp_data.get("paa_count", 0)

        if not has_paa:
            return 20.0

        # More PAA questions = higher volume
        if paa_count >= 4:
            return 100.0
        elif paa_count >= 2:
            return 75.0
        return 50.0

    def _score_result_count(self, serp_data: Dict) -> float:
        """
        Score based on total search results.

        More results indicate more content = higher volume keyword.

        Returns:
            float: 0-100 score
        """
        result_count = serp_data.get("total_results", 0)

        if result_count == 0:
            return 0.0

        # Logarithmic scale (billions of results common for popular terms)
        # 10M+ = 100, 1M = 80, 100K = 60, 10K = 40, 1K = 20
        if result_count >= 10_000_000:
            return 100.0
        elif result_count >= 1_000_000:
            return 80.0
        elif result_count >= 100_000:
            return 60.0
        elif result_count >= 10_000:
            return 40.0
        elif result_count >= 1_000:
            return 20.0
        return 10.0

    def _score_brand_results(self, serp_data: Dict) -> float:
        """
        Score based on known brand domains in results.

        High-authority sites ranking indicates competitive keyword.

        Returns:
            float: 0-100 score
        """
        organic_results = serp_data.get("organic_results", [])
        brand_count = 0

        for result in organic_results[:10]:  # Top 10 results
            domain = result.get("domain", "").lower()
            if any(auth in domain for auth in self.HIGH_AUTHORITY_DOMAINS):
                brand_count += 1

        # More brands = higher volume keyword
        if brand_count >= 5:
            return 100.0
        elif brand_count >= 3:
            return 75.0
        elif brand_count >= 1:
            return 50.0
        return 25.0

    def _score_autocomplete_position(self, serp_data: Dict) -> float:
        """
        Score based on autocomplete suggestion position.

        Keywords that appear first in autocomplete have higher volume.

        Returns:
            float: 0-100 score
        """
        position = serp_data.get("autocomplete_position")

        if position is None:
            return 50.0  # Default if no data

        # Position 1 = 100, decreasing by 10 per position
        score = max(0, 100 - (position - 1) * 10)
        return score

    def _score_related_searches(self, serp_data: Dict) -> float:
        """
        Score based on related searches count.

        More related searches = more search variants = higher volume.

        Returns:
            float: 0-100 score
        """
        related = serp_data.get("related_searches", [])
        count = len(related)

        if count >= 8:
            return 100.0
        elif count >= 6:
            return 80.0
        elif count >= 4:
            return 60.0
        elif count >= 2:
            return 40.0
        elif count >= 1:
            return 20.0
        return 0.0

    def _score_knowledge_panel(self, serp_data: Dict) -> float:
        """
        Score based on knowledge panel presence.

        Knowledge panels indicate Google has significant data = volume.

        Returns:
            float: 0-100 score
        """
        has_panel = serp_data.get("has_knowledge_panel", False)
        return 100.0 if has_panel else 30.0

    def estimate_volume(
        self,
        serp_data: Dict[str, Any],
        keyword: str = "",
    ) -> VolumeEstimate:
        """
        Estimate search volume from SERP data.

        Args:
            serp_data: SERP data dictionary with features
            keyword: The keyword being analyzed

        Returns:
            VolumeEstimate: Estimated volume with confidence
        """
        signals = {}
        weighted_scores = []

        # Calculate each signal score
        signal_funcs = {
            "ads_present": self._score_ads_present,
            "ad_count": self._score_ad_count,
            "shopping_present": self._score_shopping_present,
            "featured_snippet": self._score_featured_snippet,
            "people_also_ask": self._score_people_also_ask,
            "result_count": self._score_result_count,
            "brand_results": self._score_brand_results,
            "autocomplete_position": self._score_autocomplete_position,
            "related_searches": self._score_related_searches,
            "knowledge_panel": self._score_knowledge_panel,
        }

        available_signals = 0

        for signal_name, score_func in signal_funcs.items():
            try:
                score = score_func(serp_data)
                weight = self.SIGNAL_WEIGHTS.get(signal_name, 0.1)

                signals[signal_name] = {
                    "score": score,
                    "weight": weight,
                    "weighted": score * weight,
                }

                weighted_scores.append(score * weight)
                available_signals += 1

            except Exception as e:
                self.logger.debug(f"Error calculating {signal_name}: {e}")

        # Calculate composite volume score
        total_weight = sum(self.SIGNAL_WEIGHTS.get(k, 0) for k in signal_funcs.keys())
        volume_score = sum(weighted_scores) / total_weight if total_weight > 0 else 0

        # Determine category
        category = VolumeCategory.VERY_LOW
        for threshold, cat in sorted(self.CATEGORY_THRESHOLDS.items(), reverse=True):
            if volume_score >= threshold:
                category = cat
                break

        # Get volume range
        min_vol, max_vol = self.VOLUME_RANGES.get(category, (0, 10))

        # Calculate confidence based on available signals
        confidence = min(1.0, available_signals / len(signal_funcs))

        estimate = VolumeEstimate(
            keyword=keyword,
            volume_score=round(volume_score, 2),
            category=category,
            estimated_monthly_min=min_vol,
            estimated_monthly_max=max_vol,
            confidence=round(confidence, 2),
            signals=signals,
        )

        self.logger.debug(
            f"Volume estimate for '{keyword}': {volume_score:.1f} ({category.value})"
        )

        return estimate

    def estimate_from_serp_features(
        self,
        keyword: str,
        has_ads: bool = False,
        ad_count: int = 0,
        has_shopping: bool = False,
        has_featured_snippet: bool = False,
        has_people_also_ask: bool = False,
        paa_count: int = 0,
        total_results: int = 0,
        has_knowledge_panel: bool = False,
        organic_results: Optional[List[Dict]] = None,
        related_searches: Optional[List[str]] = None,
        autocomplete_position: Optional[int] = None,
    ) -> VolumeEstimate:
        """
        Convenience method to estimate volume from individual SERP features.

        Args:
            keyword: Target keyword
            has_ads: Whether ads are present
            ad_count: Number of ads
            has_shopping: Whether shopping results present
            has_featured_snippet: Whether featured snippet present
            has_people_also_ask: Whether PAA box present
            paa_count: Number of PAA questions
            total_results: Total search results count
            has_knowledge_panel: Whether knowledge panel present
            organic_results: List of organic results with domains
            related_searches: List of related search terms
            autocomplete_position: Position in autocomplete (1-10)

        Returns:
            VolumeEstimate: Estimated volume
        """
        serp_data = {
            "has_ads": has_ads,
            "ad_count": ad_count,
            "has_shopping": has_shopping,
            "has_featured_snippet": has_featured_snippet,
            "has_people_also_ask": has_people_also_ask,
            "paa_count": paa_count,
            "total_results": total_results,
            "has_knowledge_panel": has_knowledge_panel,
            "organic_results": organic_results or [],
            "related_searches": related_searches or [],
            "autocomplete_position": autocomplete_position,
        }

        return self.estimate_volume(serp_data, keyword)

    def batch_estimate(
        self,
        keywords_serp_data: List[Tuple[str, Dict]],
    ) -> List[VolumeEstimate]:
        """
        Estimate volume for multiple keywords.

        Args:
            keywords_serp_data: List of (keyword, serp_data) tuples

        Returns:
            list: VolumeEstimate objects
        """
        estimates = []

        for keyword, serp_data in keywords_serp_data:
            estimate = self.estimate_volume(serp_data, keyword)
            estimates.append(estimate)

        # Sort by volume score descending
        estimates.sort(key=lambda x: x.volume_score, reverse=True)

        return estimates

    def get_volume_tier(self, estimate: VolumeEstimate) -> str:
        """
        Get human-readable volume tier description.

        Args:
            estimate: VolumeEstimate object

        Returns:
            str: Description like "High volume (1,000-10,000/mo)"
        """
        category = estimate.category.value.replace("_", " ").title()
        min_vol = f"{estimate.estimated_monthly_min:,}"
        max_vol = f"{estimate.estimated_monthly_max:,}"

        return f"{category} ({min_vol}-{max_vol}/mo)"


# Module-level singleton
_volume_estimator_instance = None


def get_volume_estimator() -> VolumeEstimator:
    """Get or create the singleton VolumeEstimator instance."""
    global _volume_estimator_instance

    if _volume_estimator_instance is None:
        _volume_estimator_instance = VolumeEstimator()

    return _volume_estimator_instance
