"""
Keyword Opportunity Analyzer Service

Combines volume and difficulty estimates to identify ranking opportunities.
Prioritizes keywords based on potential ROI (high volume, low difficulty).

Opportunity Score = Volume Score * (1 - Difficulty Score / 100)

Features:
- Quick win identification (high volume, low difficulty)
- Keyword prioritization by opportunity score
- Current ranking position integration
- Intent classification (informational, transactional, navigational)
- Topic clustering for content strategy

Usage:
    from seo_intelligence.services.opportunity_analyzer import OpportunityAnalyzer

    analyzer = OpportunityAnalyzer()
    opportunities = analyzer.analyze_keywords(keyword_data)

    # Get prioritized quick wins
    quick_wins = analyzer.get_quick_wins(opportunities)
"""

import re
import json
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from runner.logging_setup import get_logger
from seo_intelligence.services.volume_estimator import (
    VolumeEstimator, VolumeEstimate, VolumeCategory, get_volume_estimator
)
from seo_intelligence.services.difficulty_calculator import (
    DifficultyCalculator, DifficultyResult, DifficultyLevel, get_difficulty_calculator
)


class SearchIntent(Enum):
    """Search intent classification."""
    INFORMATIONAL = "INFORMATIONAL"  # Looking for information
    NAVIGATIONAL = "NAVIGATIONAL"    # Looking for specific site
    TRANSACTIONAL = "TRANSACTIONAL"  # Ready to buy/convert
    COMMERCIAL = "COMMERCIAL"         # Researching before purchase
    LOCAL = "LOCAL"                   # Local search intent


class OpportunityTier(Enum):
    """Opportunity tier classification."""
    QUICK_WIN = "QUICK_WIN"          # High opportunity, prioritize immediately
    HIGH_VALUE = "HIGH_VALUE"         # Good opportunity, include in strategy
    MODERATE = "MODERATE"             # Worth targeting with good content
    LONG_TERM = "LONG_TERM"           # Requires investment, long-term goal
    LOW_PRIORITY = "LOW_PRIORITY"     # Not worth pursuing currently


@dataclass
class KeywordOpportunity:
    """Keyword opportunity analysis result."""
    keyword: str
    opportunity_score: float  # 0-100 (higher = better opportunity)
    tier: OpportunityTier
    volume_estimate: VolumeEstimate
    difficulty_result: DifficultyResult
    intent: SearchIntent
    current_position: Optional[int] = None  # Current ranking if known
    position_gap: Optional[int] = None  # Positions to gain
    estimated_traffic: int = 0  # Estimated monthly traffic if ranking
    priority_rank: int = 0  # Overall priority (1 = highest)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    analyzed_at: datetime = field(default_factory=datetime.now)


class OpportunityAnalyzer:
    """
    Analyzes keyword opportunities by combining volume and difficulty.

    Higher opportunity score = higher volume + lower difficulty.
    """

    # Opportunity tier thresholds
    TIER_THRESHOLDS = {
        75: OpportunityTier.QUICK_WIN,
        55: OpportunityTier.HIGH_VALUE,
        35: OpportunityTier.MODERATE,
        15: OpportunityTier.LONG_TERM,
        0: OpportunityTier.LOW_PRIORITY,
    }

    # CTR by position (estimated click-through rates)
    POSITION_CTR = {
        1: 0.285,   # 28.5% CTR for position 1
        2: 0.157,   # 15.7%
        3: 0.110,   # 11.0%
        4: 0.080,   # 8.0%
        5: 0.072,   # 7.2%
        6: 0.051,   # 5.1%
        7: 0.044,   # 4.4%
        8: 0.038,   # 3.8%
        9: 0.034,   # 3.4%
        10: 0.031,  # 3.1%
    }

    # Intent indicator keywords
    INTENT_INDICATORS = {
        SearchIntent.TRANSACTIONAL: [
            "buy", "purchase", "order", "price", "cost", "cheap",
            "deal", "discount", "coupon", "sale", "shop", "store",
            "best price", "for sale", "free shipping",
        ],
        SearchIntent.COMMERCIAL: [
            "best", "top", "review", "reviews", "comparison", "vs",
            "versus", "alternative", "alternatives", "compare",
            "which", "recommendation", "rated",
        ],
        SearchIntent.INFORMATIONAL: [
            "what is", "what are", "how to", "how do", "why",
            "when", "where", "who", "guide", "tutorial", "learn",
            "tips", "ideas", "examples", "definition",
        ],
        SearchIntent.NAVIGATIONAL: [
            "login", "sign in", "website", "official", "portal",
            "account", "contact", "support", "customer service",
        ],
        SearchIntent.LOCAL: [
            "near me", "nearby", "in", "local", "closest",
            "directions", "hours", "open now", "address",
        ],
    }

    def __init__(self):
        """Initialize opportunity analyzer."""
        self.logger = get_logger("opportunity_analyzer")
        self.volume_estimator = get_volume_estimator()
        self.difficulty_calculator = get_difficulty_calculator()

    def _classify_intent(self, keyword: str) -> SearchIntent:
        """
        Classify search intent for a keyword.

        Args:
            keyword: Keyword to classify

        Returns:
            SearchIntent: Classified intent
        """
        keyword_lower = keyword.lower()

        # Check each intent type
        for intent, indicators in self.INTENT_INDICATORS.items():
            for indicator in indicators:
                if indicator in keyword_lower:
                    return intent

        # Default to informational
        return SearchIntent.INFORMATIONAL

    def _calculate_opportunity_score(
        self,
        volume: VolumeEstimate,
        difficulty: DifficultyResult,
        current_position: Optional[int] = None,
    ) -> float:
        """
        Calculate opportunity score from volume and difficulty.

        Formula: opportunity = volume_score * (1 - difficulty / 100) * position_bonus

        Args:
            volume: Volume estimate
            difficulty: Difficulty result
            current_position: Current ranking position if known

        Returns:
            float: Opportunity score (0-100)
        """
        # Base opportunity: high volume + low difficulty
        base_score = volume.volume_score * (1 - difficulty.difficulty_score / 100)

        # Position bonus: if already ranking, easier to improve
        position_bonus = 1.0
        if current_position is not None:
            if current_position <= 10:
                position_bonus = 1.3  # Already on page 1
            elif current_position <= 20:
                position_bonus = 1.2  # Page 2
            elif current_position <= 50:
                position_bonus = 1.1  # Top 50

        opportunity_score = base_score * position_bonus

        return min(100, max(0, opportunity_score))

    def _estimate_traffic_potential(
        self,
        volume: VolumeEstimate,
        target_position: int = 3,
    ) -> int:
        """
        Estimate monthly traffic if ranking at target position.

        Args:
            volume: Volume estimate
            target_position: Target ranking position

        Returns:
            int: Estimated monthly traffic
        """
        # Use midpoint of volume range
        monthly_volume = (
            volume.estimated_monthly_min + volume.estimated_monthly_max
        ) // 2

        # Apply CTR for target position
        ctr = self.POSITION_CTR.get(target_position, 0.02)

        return int(monthly_volume * ctr)

    def _get_tier(self, opportunity_score: float) -> OpportunityTier:
        """
        Get opportunity tier from score.

        Args:
            opportunity_score: Opportunity score (0-100)

        Returns:
            OpportunityTier: Tier classification
        """
        for threshold, tier in sorted(self.TIER_THRESHOLDS.items(), reverse=True):
            if opportunity_score >= threshold:
                return tier

        return OpportunityTier.LOW_PRIORITY

    def _generate_opportunity_recommendations(
        self,
        opportunity: KeywordOpportunity,
    ) -> List[str]:
        """
        Generate actionable recommendations for the opportunity.

        Args:
            opportunity: KeywordOpportunity to analyze

        Returns:
            list: Recommendations
        """
        recommendations = []
        tier = opportunity.tier
        intent = opportunity.intent

        # Tier-specific recommendations
        if tier == OpportunityTier.QUICK_WIN:
            recommendations.append(
                "HIGH PRIORITY: Create optimized content within 2 weeks"
            )
            recommendations.append(
                "Expected results within 1-3 months with quality content"
            )

        elif tier == OpportunityTier.HIGH_VALUE:
            recommendations.append(
                "Strong opportunity - include in content calendar"
            )
            recommendations.append(
                "Create comprehensive, authoritative content"
            )

        elif tier == OpportunityTier.MODERATE:
            recommendations.append(
                "Worth targeting with well-optimized content"
            )
            recommendations.append(
                "Consider as part of topical authority building"
            )

        elif tier == OpportunityTier.LONG_TERM:
            recommendations.append(
                "Long-term target - requires domain authority building"
            )
            recommendations.append(
                "Focus on related easier keywords first"
            )

        else:
            recommendations.append(
                "Low priority - focus resources elsewhere"
            )

        # Intent-specific recommendations
        if intent == SearchIntent.TRANSACTIONAL:
            recommendations.append(
                "High-converting intent - optimize for conversions"
            )
            recommendations.append(
                "Include clear CTAs and trust signals"
            )

        elif intent == SearchIntent.COMMERCIAL:
            recommendations.append(
                "Comparison/review intent - create detailed comparisons"
            )
            recommendations.append(
                "Include pros/cons and clear recommendations"
            )

        elif intent == SearchIntent.INFORMATIONAL:
            recommendations.append(
                "Informational intent - focus on comprehensive coverage"
            )
            recommendations.append(
                "Add FAQ schema and structured content"
            )

        elif intent == SearchIntent.LOCAL:
            recommendations.append(
                "Local intent - optimize Google Business Profile"
            )
            recommendations.append(
                "Include location-specific content and NAP data"
            )

        # Position-specific recommendations
        if opportunity.current_position:
            if opportunity.current_position <= 10:
                recommendations.append(
                    f"Currently position {opportunity.current_position} - optimize to reach top 3"
                )
            elif opportunity.current_position <= 20:
                recommendations.append(
                    f"Position {opportunity.current_position} - build links to reach page 1"
                )

        return recommendations

    def analyze_keyword(
        self,
        keyword: str,
        serp_data: Dict[str, Any],
        organic_results: List[Dict[str, Any]],
        current_position: Optional[int] = None,
    ) -> KeywordOpportunity:
        """
        Analyze opportunity for a single keyword.

        Args:
            keyword: Target keyword
            serp_data: SERP features data
            organic_results: Organic search results
            current_position: Current ranking if known

        Returns:
            KeywordOpportunity: Analysis result
        """
        # Estimate volume
        volume = self.volume_estimator.estimate_volume(serp_data, keyword)

        # Calculate difficulty
        difficulty = self.difficulty_calculator.calculate_difficulty(
            keyword, serp_data, organic_results
        )

        # Classify intent
        intent = self._classify_intent(keyword)

        # Calculate opportunity score
        opportunity_score = self._calculate_opportunity_score(
            volume, difficulty, current_position
        )

        # Determine tier
        tier = self._get_tier(opportunity_score)

        # Estimate traffic potential
        estimated_traffic = self._estimate_traffic_potential(volume)

        # Calculate position gap
        position_gap = None
        if current_position:
            position_gap = max(0, current_position - 3)  # Gap to top 3

        # Create opportunity object
        opportunity = KeywordOpportunity(
            keyword=keyword,
            opportunity_score=round(opportunity_score, 2),
            tier=tier,
            volume_estimate=volume,
            difficulty_result=difficulty,
            intent=intent,
            current_position=current_position,
            position_gap=position_gap,
            estimated_traffic=estimated_traffic,
            metadata={
                "volume_category": volume.category.value,
                "difficulty_level": difficulty.level.value,
                "time_to_rank": difficulty.estimated_time_to_rank,
            }
        )

        # Generate recommendations
        opportunity.recommendations = self._generate_opportunity_recommendations(
            opportunity
        )

        self.logger.debug(
            f"Opportunity for '{keyword}': {opportunity_score:.1f} ({tier.value})"
        )

        return opportunity

    def analyze_keywords(
        self,
        keywords_data: List[Tuple[str, Dict, List[Dict], Optional[int]]],
    ) -> List[KeywordOpportunity]:
        """
        Analyze opportunities for multiple keywords.

        Args:
            keywords_data: List of (keyword, serp_data, organic_results, position) tuples

        Returns:
            list: KeywordOpportunity objects sorted by opportunity score
        """
        opportunities = []

        for data in keywords_data:
            keyword, serp_data, organic_results = data[:3]
            position = data[3] if len(data) > 3 else None

            opportunity = self.analyze_keyword(
                keyword, serp_data, organic_results, position
            )
            opportunities.append(opportunity)

        # Sort by opportunity score descending
        opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)

        # Assign priority ranks
        for i, opp in enumerate(opportunities):
            opp.priority_rank = i + 1

        return opportunities

    def get_quick_wins(
        self,
        opportunities: List[KeywordOpportunity],
        limit: int = 10,
    ) -> List[KeywordOpportunity]:
        """
        Get top quick win opportunities.

        Quick wins: high volume, low difficulty, easy to rank.

        Args:
            opportunities: List of analyzed opportunities
            limit: Maximum number to return

        Returns:
            list: Top quick win opportunities
        """
        quick_wins = [
            opp for opp in opportunities
            if opp.tier in (OpportunityTier.QUICK_WIN, OpportunityTier.HIGH_VALUE)
        ]

        return quick_wins[:limit]

    def get_by_intent(
        self,
        opportunities: List[KeywordOpportunity],
        intent: SearchIntent,
    ) -> List[KeywordOpportunity]:
        """
        Filter opportunities by search intent.

        Args:
            opportunities: List of opportunities
            intent: Desired intent type

        Returns:
            list: Filtered opportunities
        """
        return [opp for opp in opportunities if opp.intent == intent]

    def get_by_difficulty(
        self,
        opportunities: List[KeywordOpportunity],
        max_difficulty: DifficultyLevel = DifficultyLevel.MODERATE,
    ) -> List[KeywordOpportunity]:
        """
        Filter opportunities by maximum difficulty.

        Args:
            opportunities: List of opportunities
            max_difficulty: Maximum difficulty level

        Returns:
            list: Filtered opportunities
        """
        difficulty_order = [
            DifficultyLevel.VERY_EASY,
            DifficultyLevel.EASY,
            DifficultyLevel.MODERATE,
            DifficultyLevel.HARD,
            DifficultyLevel.VERY_HARD,
        ]

        max_index = difficulty_order.index(max_difficulty)

        return [
            opp for opp in opportunities
            if difficulty_order.index(opp.difficulty_result.level) <= max_index
        ]

    def save_opportunities(
        self,
        opportunities: List[KeywordOpportunity],
        competitor_id: Optional[int] = None,
    ):
        """
        Save opportunities to database.

        Args:
            opportunities: List of opportunities to save
            competitor_id: Optional competitor association
        """
        if not opportunities:
            return

        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv
        import os

        load_dotenv()
        db_url = os.getenv("DATABASE_URL")

        if not db_url:
            self.logger.warning("DATABASE_URL not set, skipping save")
            return

        engine = create_engine(db_url)

        insert_sql = text("""
            INSERT INTO keyword_metrics (
                keyword, search_volume_estimate, difficulty_score,
                opportunity_score, intent, current_position,
                competitor_id, metadata, created_at
            ) VALUES (
                :keyword, :volume, :difficulty,
                :opportunity, :intent, :position,
                :competitor_id, :metadata, :created_at
            )
            ON CONFLICT (keyword) DO UPDATE SET
                search_volume_estimate = EXCLUDED.search_volume_estimate,
                difficulty_score = EXCLUDED.difficulty_score,
                opportunity_score = EXCLUDED.opportunity_score,
                current_position = EXCLUDED.current_position,
                updated_at = NOW()
        """)

        with engine.connect() as conn:
            for opp in opportunities:
                try:
                    conn.execute(insert_sql, {
                        "keyword": opp.keyword,
                        "volume": (
                            opp.volume_estimate.estimated_monthly_min +
                            opp.volume_estimate.estimated_monthly_max
                        ) // 2,
                        "difficulty": opp.difficulty_result.difficulty_score,
                        "opportunity": opp.opportunity_score,
                        "intent": opp.intent.value,
                        "position": opp.current_position,
                        "competitor_id": competitor_id,
                        "metadata": json.dumps(opp.metadata),
                        "created_at": opp.analyzed_at,
                    })
                except Exception as e:
                    self.logger.debug(f"Error saving opportunity: {e}")

            conn.commit()

        self.logger.info(f"Saved {len(opportunities)} opportunities to database")

    def generate_report(
        self,
        opportunities: List[KeywordOpportunity],
    ) -> Dict[str, Any]:
        """
        Generate summary report of opportunities.

        Args:
            opportunities: Analyzed opportunities

        Returns:
            dict: Summary report
        """
        if not opportunities:
            return {"error": "No opportunities to report"}

        # Count by tier
        tier_counts = {}
        for tier in OpportunityTier:
            tier_counts[tier.value] = len([
                o for o in opportunities if o.tier == tier
            ])

        # Count by intent
        intent_counts = {}
        for intent in SearchIntent:
            intent_counts[intent.value] = len([
                o for o in opportunities if o.intent == intent
            ])

        # Top opportunities
        top_10 = opportunities[:10]

        # Calculate totals
        total_traffic = sum(o.estimated_traffic for o in opportunities)
        avg_difficulty = sum(
            o.difficulty_result.difficulty_score for o in opportunities
        ) / len(opportunities)

        return {
            "total_keywords": len(opportunities),
            "tier_distribution": tier_counts,
            "intent_distribution": intent_counts,
            "quick_wins_count": tier_counts.get(OpportunityTier.QUICK_WIN.value, 0),
            "total_potential_traffic": total_traffic,
            "average_difficulty": round(avg_difficulty, 2),
            "top_opportunities": [
                {
                    "keyword": o.keyword,
                    "score": o.opportunity_score,
                    "tier": o.tier.value,
                    "volume": f"{o.volume_estimate.estimated_monthly_min:,}-{o.volume_estimate.estimated_monthly_max:,}",
                    "difficulty": o.difficulty_result.difficulty_score,
                    "intent": o.intent.value,
                }
                for o in top_10
            ],
        }


# Module-level singleton
_opportunity_analyzer_instance = None


def get_opportunity_analyzer() -> OpportunityAnalyzer:
    """Get or create the singleton OpportunityAnalyzer instance."""
    global _opportunity_analyzer_instance

    if _opportunity_analyzer_instance is None:
        _opportunity_analyzer_instance = OpportunityAnalyzer()

    return _opportunity_analyzer_instance
