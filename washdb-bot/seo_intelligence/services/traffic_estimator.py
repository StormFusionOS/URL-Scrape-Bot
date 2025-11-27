"""
Traffic Estimator Service

Estimates organic search traffic for domains and pages:
- Click-through rate (CTR) modeling by position
- Traffic estimation from keyword rankings
- Domain traffic aggregation
- Traffic value calculation

No external APIs - uses position-based CTR models and keyword data.

Usage:
    from seo_intelligence.services.traffic_estimator import get_traffic_estimator

    estimator = get_traffic_estimator()

    # Estimate traffic for a keyword/position
    traffic = estimator.estimate_keyword_traffic(
        keyword="car wash near me",
        position=3,
        volume_estimate=5000
    )

    # Estimate domain traffic
    domain_traffic = estimator.estimate_domain_traffic(
        keyword_rankings=[{"keyword": "...", "position": 3, "volume": 5000}]
    )
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from runner.logging_setup import get_logger
from db.database_manager import get_db_manager


class TrafficQuality(Enum):
    """Traffic quality tier."""
    HIGH_INTENT = "high_intent"
    MEDIUM_INTENT = "medium_intent"
    LOW_INTENT = "low_intent"
    BRANDED = "branded"


class DeviceType(Enum):
    """Device type for CTR adjustment."""
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"


@dataclass
class KeywordTraffic:
    """Traffic estimate for a single keyword."""
    keyword: str
    position: int
    search_volume: int
    ctr: float
    estimated_clicks: int
    traffic_value: float  # Estimated $ value
    quality: TrafficQuality
    device_split: Dict[str, float] = field(default_factory=dict)


@dataclass
class DomainTraffic:
    """Aggregated traffic estimate for a domain."""
    domain: str
    total_keywords: int
    keywords_top_3: int
    keywords_top_10: int
    keywords_top_20: int
    estimated_monthly_traffic: int
    estimated_traffic_value: float
    traffic_by_quality: Dict[str, int] = field(default_factory=dict)
    top_keywords: List[KeywordTraffic] = field(default_factory=list)
    estimated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "total_keywords": self.total_keywords,
            "keywords_top_3": self.keywords_top_3,
            "keywords_top_10": self.keywords_top_10,
            "keywords_top_20": self.keywords_top_20,
            "estimated_monthly_traffic": self.estimated_monthly_traffic,
            "estimated_traffic_value": self.estimated_traffic_value,
            "traffic_by_quality": self.traffic_by_quality,
            "top_keywords": [
                {
                    "keyword": k.keyword,
                    "position": k.position,
                    "volume": k.search_volume,
                    "clicks": k.estimated_clicks,
                }
                for k in self.top_keywords[:10]
            ],
            "estimated_at": self.estimated_at.isoformat(),
        }


# CTR curves by position (based on industry studies)
# Desktop CTR (Google organic results)
DESKTOP_CTR = {
    1: 0.319,   # 31.9%
    2: 0.158,   # 15.8%
    3: 0.107,   # 10.7%
    4: 0.078,   # 7.8%
    5: 0.058,   # 5.8%
    6: 0.043,   # 4.3%
    7: 0.033,   # 3.3%
    8: 0.026,   # 2.6%
    9: 0.021,   # 2.1%
    10: 0.017,  # 1.7%
    # Page 2
    11: 0.010,
    12: 0.009,
    13: 0.008,
    14: 0.007,
    15: 0.006,
    16: 0.005,
    17: 0.005,
    18: 0.004,
    19: 0.004,
    20: 0.003,
}

# Mobile CTR (slightly different distribution)
MOBILE_CTR = {
    1: 0.287,   # 28.7%
    2: 0.144,   # 14.4%
    3: 0.098,   # 9.8%
    4: 0.072,   # 7.2%
    5: 0.054,   # 5.4%
    6: 0.041,   # 4.1%
    7: 0.032,   # 3.2%
    8: 0.025,   # 2.5%
    9: 0.020,   # 2.0%
    10: 0.016,  # 1.6%
    # Beyond page 1
    11: 0.008,
    12: 0.007,
    13: 0.006,
    14: 0.005,
    15: 0.005,
    16: 0.004,
    17: 0.004,
    18: 0.003,
    19: 0.003,
    20: 0.002,
}

# SERP feature impact on CTR (multipliers)
SERP_FEATURE_CTR_IMPACT = {
    "featured_snippet": 0.85,  # Reduces organic CTR
    "knowledge_panel": 0.90,
    "local_pack": 0.80,
    "shopping_ads": 0.85,
    "paid_ads_top": 0.75,
    "video_results": 0.95,
    "images": 0.95,
    "people_also_ask": 0.90,
}

# Traffic value per click (estimated CPC by intent)
TRAFFIC_VALUE_PER_CLICK = {
    TrafficQuality.HIGH_INTENT: 2.50,
    TrafficQuality.MEDIUM_INTENT: 1.00,
    TrafficQuality.LOW_INTENT: 0.30,
    TrafficQuality.BRANDED: 0.50,
}

# Intent indicators
HIGH_INTENT_KEYWORDS = [
    "buy", "purchase", "order", "price", "cost", "cheap",
    "best", "top", "review", "vs", "compare", "near me",
    "quote", "hire", "service", "booking", "appointment",
]

LOW_INTENT_KEYWORDS = [
    "what is", "how to", "why", "when", "where", "who",
    "definition", "meaning", "tutorial", "guide", "learn",
    "free", "diy", "tips", "ideas",
]

BRANDED_INDICATORS = [
    ".com", ".net", ".org", "login", "sign in", "account",
]


class TrafficEstimator:
    """
    Estimates organic search traffic.

    Uses position-based CTR models to estimate traffic from
    keyword ranking data without external APIs.
    """

    def __init__(
        self,
        desktop_share: float = 0.55,  # 55% desktop
        mobile_share: float = 0.42,   # 42% mobile
        tablet_share: float = 0.03,   # 3% tablet
    ):
        """
        Initialize the traffic estimator.

        Args:
            desktop_share: Desktop traffic share (0-1)
            mobile_share: Mobile traffic share (0-1)
            tablet_share: Tablet traffic share (0-1)
        """
        self.logger = get_logger("traffic_estimator")
        self.db = get_db_manager()

        # Device distribution
        self.device_share = {
            DeviceType.DESKTOP: desktop_share,
            DeviceType.MOBILE: mobile_share,
            DeviceType.TABLET: tablet_share,
        }

        self.logger.info(
            f"TrafficEstimator initialized "
            f"(desktop={desktop_share:.0%}, mobile={mobile_share:.0%})"
        )

    def _get_ctr(
        self,
        position: int,
        device: DeviceType = DeviceType.DESKTOP,
    ) -> float:
        """
        Get CTR for a position.

        Args:
            position: SERP position (1-based)
            device: Device type

        Returns:
            float: Click-through rate (0-1)
        """
        if position < 1:
            return 0.0

        ctr_table = DESKTOP_CTR if device == DeviceType.DESKTOP else MOBILE_CTR

        if position <= 20:
            return ctr_table.get(position, 0.003)
        elif position <= 50:
            # Exponential decay beyond position 20
            return 0.003 * (0.8 ** (position - 20))
        else:
            return 0.0001

    def _get_blended_ctr(self, position: int) -> float:
        """
        Get blended CTR across all devices.

        Args:
            position: SERP position

        Returns:
            float: Blended CTR
        """
        ctr = 0.0
        ctr += self._get_ctr(position, DeviceType.DESKTOP) * self.device_share[DeviceType.DESKTOP]
        ctr += self._get_ctr(position, DeviceType.MOBILE) * self.device_share[DeviceType.MOBILE]
        ctr += self._get_ctr(position, DeviceType.MOBILE) * self.device_share[DeviceType.TABLET]  # Use mobile CTR for tablet

        return ctr

    def _adjust_ctr_for_serp(
        self,
        base_ctr: float,
        serp_features: Optional[Dict[str, bool]] = None,
    ) -> float:
        """
        Adjust CTR based on SERP features.

        Args:
            base_ctr: Base CTR
            serp_features: Dict of SERP features present

        Returns:
            float: Adjusted CTR
        """
        if not serp_features:
            return base_ctr

        adjusted_ctr = base_ctr

        for feature, present in serp_features.items():
            if present and feature in SERP_FEATURE_CTR_IMPACT:
                adjusted_ctr *= SERP_FEATURE_CTR_IMPACT[feature]

        return adjusted_ctr

    def _classify_traffic_quality(self, keyword: str) -> TrafficQuality:
        """
        Classify keyword traffic quality by intent.

        Args:
            keyword: Search keyword

        Returns:
            TrafficQuality: Quality tier
        """
        keyword_lower = keyword.lower()

        # Check for branded
        if any(ind in keyword_lower for ind in BRANDED_INDICATORS):
            return TrafficQuality.BRANDED

        # Check for high intent
        if any(ind in keyword_lower for ind in HIGH_INTENT_KEYWORDS):
            return TrafficQuality.HIGH_INTENT

        # Check for low intent
        if any(ind in keyword_lower for ind in LOW_INTENT_KEYWORDS):
            return TrafficQuality.LOW_INTENT

        return TrafficQuality.MEDIUM_INTENT

    def estimate_keyword_traffic(
        self,
        keyword: str,
        position: int,
        search_volume: int,
        serp_features: Optional[Dict[str, bool]] = None,
    ) -> KeywordTraffic:
        """
        Estimate traffic for a single keyword.

        Args:
            keyword: Search keyword
            position: Current ranking position
            search_volume: Monthly search volume
            serp_features: SERP features present

        Returns:
            KeywordTraffic: Traffic estimate
        """
        # Get base CTR
        base_ctr = self._get_blended_ctr(position)

        # Adjust for SERP features
        ctr = self._adjust_ctr_for_serp(base_ctr, serp_features)

        # Calculate clicks
        estimated_clicks = int(search_volume * ctr)

        # Classify quality
        quality = self._classify_traffic_quality(keyword)

        # Calculate traffic value
        value_per_click = TRAFFIC_VALUE_PER_CLICK.get(quality, 0.50)
        traffic_value = estimated_clicks * value_per_click

        # Device split
        device_split = {
            "desktop": int(estimated_clicks * self.device_share[DeviceType.DESKTOP]),
            "mobile": int(estimated_clicks * self.device_share[DeviceType.MOBILE]),
            "tablet": int(estimated_clicks * self.device_share[DeviceType.TABLET]),
        }

        return KeywordTraffic(
            keyword=keyword,
            position=position,
            search_volume=search_volume,
            ctr=round(ctr, 4),
            estimated_clicks=estimated_clicks,
            traffic_value=round(traffic_value, 2),
            quality=quality,
            device_split=device_split,
        )

    def estimate_domain_traffic(
        self,
        domain: str,
        keyword_rankings: List[Dict[str, Any]],
    ) -> DomainTraffic:
        """
        Estimate total domain traffic from keyword rankings.

        Args:
            domain: Domain name
            keyword_rankings: List of {keyword, position, volume, serp_features?}

        Returns:
            DomainTraffic: Aggregated traffic estimate
        """
        self.logger.info(
            f"Estimating traffic for {domain} "
            f"({len(keyword_rankings)} keywords)"
        )

        keyword_traffic = []
        total_traffic = 0
        total_value = 0.0

        traffic_by_quality = {
            TrafficQuality.HIGH_INTENT.value: 0,
            TrafficQuality.MEDIUM_INTENT.value: 0,
            TrafficQuality.LOW_INTENT.value: 0,
            TrafficQuality.BRANDED.value: 0,
        }

        keywords_top_3 = 0
        keywords_top_10 = 0
        keywords_top_20 = 0

        for ranking in keyword_rankings:
            keyword = ranking.get("keyword", "")
            position = ranking.get("position", 100)
            volume = ranking.get("volume", 0)
            serp_features = ranking.get("serp_features")

            if not keyword or position > 100:
                continue

            # Count position distributions
            if position <= 3:
                keywords_top_3 += 1
            if position <= 10:
                keywords_top_10 += 1
            if position <= 20:
                keywords_top_20 += 1

            # Estimate traffic
            kw_traffic = self.estimate_keyword_traffic(
                keyword=keyword,
                position=position,
                search_volume=volume,
                serp_features=serp_features,
            )

            keyword_traffic.append(kw_traffic)
            total_traffic += kw_traffic.estimated_clicks
            total_value += kw_traffic.traffic_value
            traffic_by_quality[kw_traffic.quality.value] += kw_traffic.estimated_clicks

        # Sort by traffic
        keyword_traffic.sort(key=lambda x: x.estimated_clicks, reverse=True)

        result = DomainTraffic(
            domain=domain,
            total_keywords=len(keyword_rankings),
            keywords_top_3=keywords_top_3,
            keywords_top_10=keywords_top_10,
            keywords_top_20=keywords_top_20,
            estimated_monthly_traffic=total_traffic,
            estimated_traffic_value=round(total_value, 2),
            traffic_by_quality=traffic_by_quality,
            top_keywords=keyword_traffic[:20],
        )

        self.logger.info(
            f"Traffic estimate complete: {total_traffic:,} monthly clicks, "
            f"${total_value:,.2f} value"
        )

        return result

    def compare_domains(
        self,
        domain_rankings: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Compare traffic across multiple domains.

        Args:
            domain_rankings: Dict of domain -> keyword_rankings

        Returns:
            dict: Comparison results
        """
        estimates = {}

        for domain, rankings in domain_rankings.items():
            estimates[domain] = self.estimate_domain_traffic(domain, rankings)

        # Sort by traffic
        sorted_domains = sorted(
            estimates.items(),
            key=lambda x: x[1].estimated_monthly_traffic,
            reverse=True,
        )

        # Calculate market share
        total_market_traffic = sum(e.estimated_monthly_traffic for e in estimates.values())

        return {
            "domains_analyzed": len(estimates),
            "total_market_traffic": total_market_traffic,
            "rankings": [
                {
                    "rank": i + 1,
                    "domain": domain,
                    "traffic": est.estimated_monthly_traffic,
                    "value": est.estimated_traffic_value,
                    "market_share": round(
                        est.estimated_monthly_traffic / max(1, total_market_traffic) * 100, 1
                    ),
                    "top_10_keywords": est.keywords_top_10,
                }
                for i, (domain, est) in enumerate(sorted_domains)
            ],
            "leader": sorted_domains[0][0] if sorted_domains else None,
        }

    def estimate_traffic_opportunity(
        self,
        current_position: int,
        target_position: int,
        search_volume: int,
        serp_features: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """
        Estimate traffic gain from ranking improvement.

        Args:
            current_position: Current ranking
            target_position: Target ranking
            search_volume: Monthly search volume
            serp_features: SERP features

        Returns:
            dict: Traffic opportunity analysis
        """
        if target_position >= current_position:
            return {"error": "Target must be better than current position"}

        # Current traffic
        current_ctr = self._adjust_ctr_for_serp(
            self._get_blended_ctr(current_position),
            serp_features,
        )
        current_traffic = int(search_volume * current_ctr)

        # Target traffic
        target_ctr = self._adjust_ctr_for_serp(
            self._get_blended_ctr(target_position),
            serp_features,
        )
        target_traffic = int(search_volume * target_ctr)

        # Calculate gain
        traffic_gain = target_traffic - current_traffic
        percent_gain = (traffic_gain / max(1, current_traffic)) * 100

        return {
            "current": {
                "position": current_position,
                "ctr": round(current_ctr, 4),
                "monthly_traffic": current_traffic,
            },
            "target": {
                "position": target_position,
                "ctr": round(target_ctr, 4),
                "monthly_traffic": target_traffic,
            },
            "opportunity": {
                "traffic_gain": traffic_gain,
                "percent_gain": round(percent_gain, 1),
                "yearly_traffic_gain": traffic_gain * 12,
            },
        }

    def estimate_from_volume_estimate(
        self,
        keyword: str,
        position: int,
        volume_score: float,
    ) -> KeywordTraffic:
        """
        Estimate traffic using our volume score (0-100).

        Converts volume score to estimated monthly searches.

        Args:
            keyword: Search keyword
            position: Ranking position
            volume_score: Volume score from VolumeEstimator (0-100)

        Returns:
            KeywordTraffic: Traffic estimate
        """
        # Convert volume score to estimated monthly searches
        # Score 0-20: 0-100 searches
        # Score 20-40: 100-1000 searches
        # Score 40-60: 1000-5000 searches
        # Score 60-80: 5000-20000 searches
        # Score 80-100: 20000-100000+ searches

        if volume_score < 20:
            estimated_volume = int(volume_score * 5)
        elif volume_score < 40:
            estimated_volume = int(100 + (volume_score - 20) * 45)
        elif volume_score < 60:
            estimated_volume = int(1000 + (volume_score - 40) * 200)
        elif volume_score < 80:
            estimated_volume = int(5000 + (volume_score - 60) * 750)
        else:
            estimated_volume = int(20000 + (volume_score - 80) * 4000)

        return self.estimate_keyword_traffic(
            keyword=keyword,
            position=position,
            search_volume=estimated_volume,
        )

    def save_estimate(
        self,
        estimate: DomainTraffic,
        competitor_id: Optional[int] = None,
    ):
        """
        Save traffic estimate to database.

        Args:
            estimate: Domain traffic estimate
            competitor_id: Optional competitor association
        """
        try:
            conn = self.db.engine.connect()

            query = """
                INSERT INTO domain_traffic_estimates (
                    domain, competitor_id, total_keywords,
                    keywords_top_3, keywords_top_10, keywords_top_20,
                    estimated_monthly_traffic, estimated_traffic_value,
                    high_intent_traffic, medium_intent_traffic,
                    low_intent_traffic, branded_traffic, estimated_at
                ) VALUES (
                    %(domain)s, %(competitor_id)s, %(total_keywords)s,
                    %(keywords_top_3)s, %(keywords_top_10)s, %(keywords_top_20)s,
                    %(estimated_monthly_traffic)s, %(estimated_traffic_value)s,
                    %(high_intent)s, %(medium_intent)s,
                    %(low_intent)s, %(branded)s, %(estimated_at)s
                )
                ON CONFLICT (domain) DO UPDATE SET
                    total_keywords = EXCLUDED.total_keywords,
                    estimated_monthly_traffic = EXCLUDED.estimated_monthly_traffic,
                    estimated_traffic_value = EXCLUDED.estimated_traffic_value,
                    estimated_at = EXCLUDED.estimated_at
            """

            conn.execute(query, {
                "domain": estimate.domain,
                "competitor_id": competitor_id,
                "total_keywords": estimate.total_keywords,
                "keywords_top_3": estimate.keywords_top_3,
                "keywords_top_10": estimate.keywords_top_10,
                "keywords_top_20": estimate.keywords_top_20,
                "estimated_monthly_traffic": estimate.estimated_monthly_traffic,
                "estimated_traffic_value": estimate.estimated_traffic_value,
                "high_intent": estimate.traffic_by_quality.get(TrafficQuality.HIGH_INTENT.value, 0),
                "medium_intent": estimate.traffic_by_quality.get(TrafficQuality.MEDIUM_INTENT.value, 0),
                "low_intent": estimate.traffic_by_quality.get(TrafficQuality.LOW_INTENT.value, 0),
                "branded": estimate.traffic_by_quality.get(TrafficQuality.BRANDED.value, 0),
                "estimated_at": estimate.estimated_at,
            })

            conn.close()
            self.logger.debug(f"Saved traffic estimate for {estimate.domain}")

        except Exception as e:
            self.logger.warning(f"Failed to save traffic estimate: {e}")


# Module-level singleton
_traffic_estimator_instance = None


def get_traffic_estimator() -> TrafficEstimator:
    """Get or create the singleton TrafficEstimator instance."""
    global _traffic_estimator_instance

    if _traffic_estimator_instance is None:
        _traffic_estimator_instance = TrafficEstimator()

    return _traffic_estimator_instance
