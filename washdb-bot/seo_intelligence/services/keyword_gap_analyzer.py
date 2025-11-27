"""
Keyword Gap Analyzer Service

Identifies keyword opportunities by comparing your ranking keywords
with competitors. Finds keywords competitors rank for but you don't.

Analysis Methods:
- Keyword presence comparison
- Position gap analysis
- Opportunity scoring
- Intent-based filtering

Usage:
    from seo_intelligence.services.keyword_gap_analyzer import KeywordGapAnalyzer

    analyzer = KeywordGapAnalyzer()
    gaps = analyzer.analyze_keyword_gaps(
        your_keywords=your_rankings,
        competitor_keywords=competitor_rankings
    )

Results stored in keyword_gaps database table.
"""

import json
from collections import Counter, defaultdict
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from runner.logging_setup import get_logger


class GapCategory(Enum):
    """Categories of keyword gaps."""
    MISSING = "MISSING"               # You don't rank at all
    UNDERPERFORMING = "UNDERPERFORMING"  # You rank but poorly vs competitors
    DECLINING = "DECLINING"           # Your rankings are dropping
    OPPORTUNITY = "OPPORTUNITY"       # New opportunity emerging


class KeywordPriority(Enum):
    """Keyword gap priority levels."""
    CRITICAL = "CRITICAL"     # Must target
    HIGH = "HIGH"             # Should target
    MEDIUM = "MEDIUM"         # Consider targeting
    LOW = "LOW"               # If resources allow


@dataclass
class KeywordRanking:
    """Represents a keyword ranking."""
    keyword: str
    position: Optional[int]  # None = not ranking
    url: Optional[str] = None
    search_volume: Optional[int] = None
    difficulty: Optional[float] = None
    intent: Optional[str] = None


@dataclass
class KeywordGap:
    """Represents a keyword gap opportunity."""
    keyword: str
    category: GapCategory
    priority: KeywordPriority
    your_position: Optional[int]  # None if not ranking
    avg_competitor_position: float
    best_competitor_position: int
    competitor_count: int  # How many competitors rank
    competitors_ranking: List[Tuple[str, int]]  # (competitor, position)
    opportunity_score: float  # 0-100
    estimated_volume: Optional[int] = None
    estimated_difficulty: Optional[float] = None
    search_intent: Optional[str] = None
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    identified_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "keyword": self.keyword,
            "category": self.category.value,
            "priority": self.priority.value,
            "your_position": self.your_position,
            "avg_competitor_position": round(self.avg_competitor_position, 1),
            "best_competitor_position": self.best_competitor_position,
            "competitor_count": self.competitor_count,
            "opportunity_score": self.opportunity_score,
            "estimated_volume": self.estimated_volume,
            "search_intent": self.search_intent,
            "recommendations": self.recommendations,
        }


class KeywordGapAnalyzer:
    """
    Analyzes keyword gaps between you and competitors.

    Identifies keywords where competitors outperform you or
    where you're missing entirely.
    """

    # Intent indicators
    INTENT_INDICATORS = {
        "transactional": [
            "buy", "purchase", "order", "price", "cost", "cheap",
            "deal", "discount", "coupon", "sale", "shop", "store",
        ],
        "commercial": [
            "best", "top", "review", "reviews", "comparison", "vs",
            "versus", "alternative", "compare", "rated",
        ],
        "informational": [
            "what is", "what are", "how to", "how do", "why",
            "when", "where", "who", "guide", "tutorial", "learn",
        ],
        "navigational": [
            "login", "sign in", "website", "official", "portal",
        ],
        "local": [
            "near me", "nearby", "local", "closest", "directions",
        ],
    }

    def __init__(self):
        """Initialize keyword gap analyzer."""
        self.logger = get_logger("keyword_gap_analyzer")

    def _classify_intent(self, keyword: str) -> str:
        """
        Classify search intent for a keyword.

        Args:
            keyword: Keyword to classify

        Returns:
            str: Intent classification
        """
        keyword_lower = keyword.lower()

        for intent, indicators in self.INTENT_INDICATORS.items():
            for indicator in indicators:
                if indicator in keyword_lower:
                    return intent

        return "informational"  # Default

    def _calculate_opportunity_score(
        self,
        your_position: Optional[int],
        avg_competitor_position: float,
        competitor_count: int,
        total_competitors: int,
        estimated_volume: Optional[int],
    ) -> float:
        """
        Calculate opportunity score for a keyword gap.

        Higher score = better opportunity.

        Args:
            your_position: Your current position (None if not ranking)
            avg_competitor_position: Average competitor position
            competitor_count: Number of competitors ranking
            total_competitors: Total competitors analyzed
            estimated_volume: Estimated search volume

        Returns:
            float: Opportunity score (0-100)
        """
        score = 0

        # Position opportunity (higher if you're not ranking or poorly)
        if your_position is None:
            score += 40  # Big opportunity if not ranking
        elif your_position > 10:
            score += 30  # Good opportunity if off page 1
        elif your_position > 3:
            score += 15  # Some opportunity if not top 3

        # Competitor coverage (more competitors = validated keyword)
        coverage_ratio = competitor_count / max(1, total_competitors)
        score += coverage_ratio * 25

        # Competitor position (easier if competitors rank lower)
        if avg_competitor_position <= 5:
            score += 10  # Competitive but validated
        elif avg_competitor_position <= 10:
            score += 20  # Good positions achievable
        else:
            score += 25  # Less competitive

        # Volume bonus
        if estimated_volume:
            if estimated_volume >= 1000:
                score += 15
            elif estimated_volume >= 100:
                score += 10
            elif estimated_volume >= 10:
                score += 5

        return min(100, score)

    def _determine_category(
        self,
        your_position: Optional[int],
        avg_competitor_position: float,
    ) -> GapCategory:
        """
        Determine gap category based on positions.

        Args:
            your_position: Your position
            avg_competitor_position: Average competitor position

        Returns:
            GapCategory: Gap categorization
        """
        if your_position is None:
            return GapCategory.MISSING

        if your_position > avg_competitor_position + 10:
            return GapCategory.UNDERPERFORMING

        return GapCategory.OPPORTUNITY

    def _determine_priority(
        self,
        opportunity_score: float,
        category: GapCategory,
        competitor_count: int,
        total_competitors: int,
    ) -> KeywordPriority:
        """
        Determine targeting priority for a keyword gap.

        Args:
            opportunity_score: Calculated opportunity score
            category: Gap category
            competitor_count: Number of competitors ranking
            total_competitors: Total competitors

        Returns:
            KeywordPriority: Priority level
        """
        # Coverage ratio
        coverage = competitor_count / max(1, total_competitors)

        # High priority if missing and competitors all rank
        if category == GapCategory.MISSING and coverage >= 0.8:
            return KeywordPriority.CRITICAL

        # Score-based prioritization
        if opportunity_score >= 70:
            return KeywordPriority.CRITICAL if coverage >= 0.5 else KeywordPriority.HIGH
        elif opportunity_score >= 50:
            return KeywordPriority.HIGH if coverage >= 0.5 else KeywordPriority.MEDIUM
        elif opportunity_score >= 30:
            return KeywordPriority.MEDIUM
        return KeywordPriority.LOW

    def _generate_recommendations(
        self,
        gap: KeywordGap,
    ) -> List[str]:
        """
        Generate recommendations for addressing a keyword gap.

        Args:
            gap: Keyword gap to analyze

        Returns:
            list: Recommendations
        """
        recommendations = []

        if gap.category == GapCategory.MISSING:
            recommendations.append(
                f"Create dedicated content targeting '{gap.keyword}'"
            )
            if gap.best_competitor_position <= 3:
                recommendations.append(
                    "Analyze top-ranking competitor content for format and depth"
                )

        elif gap.category == GapCategory.UNDERPERFORMING:
            recommendations.append(
                f"Optimize existing content for '{gap.keyword}'"
            )
            recommendations.append(
                "Add more comprehensive coverage and internal links"
            )

        # Intent-specific recommendations
        if gap.search_intent == "transactional":
            recommendations.append(
                "Include clear CTAs and conversion elements"
            )
        elif gap.search_intent == "informational":
            recommendations.append(
                "Create comprehensive guide with FAQ schema"
            )
        elif gap.search_intent == "local":
            recommendations.append(
                "Optimize Google Business Profile and local landing pages"
            )

        # Competition-based recommendations
        if gap.competitor_count >= 3:
            recommendations.append(
                f"{gap.competitor_count} competitors rank - validated keyword worth targeting"
            )

        if gap.avg_competitor_position > 10:
            recommendations.append(
                "Lower competition - good opportunity for quick ranking"
            )

        return recommendations

    def analyze_keyword_gaps(
        self,
        your_keywords: Dict[str, KeywordRanking],
        competitor_keywords: Dict[str, Dict[str, KeywordRanking]],
        min_competitor_coverage: int = 1,
    ) -> List[KeywordGap]:
        """
        Analyze keyword gaps between you and competitors.

        Args:
            your_keywords: Dict of keyword -> your ranking
            competitor_keywords: Dict of competitor -> {keyword -> ranking}
            min_competitor_coverage: Minimum competitors needed for gap

        Returns:
            list: KeywordGap opportunities
        """
        self.logger.info(
            f"Analyzing gaps: {len(your_keywords)} your keywords vs "
            f"{len(competitor_keywords)} competitors"
        )

        gaps = []
        total_competitors = len(competitor_keywords)

        # Collect all competitor keywords
        all_competitor_keywords = set()
        keyword_rankings = defaultdict(list)  # keyword -> [(competitor, position)]

        for competitor, rankings in competitor_keywords.items():
            for keyword, ranking in rankings.items():
                all_competitor_keywords.add(keyword)
                if ranking.position is not None:
                    keyword_rankings[keyword].append(
                        (competitor, ranking.position)
                    )

        # Analyze each competitor keyword
        for keyword in all_competitor_keywords:
            comp_rankings = keyword_rankings.get(keyword, [])

            if len(comp_rankings) < min_competitor_coverage:
                continue

            # Get your ranking
            your_ranking = your_keywords.get(keyword)
            your_position = your_ranking.position if your_ranking else None

            # Calculate competitor metrics
            positions = [pos for _, pos in comp_rankings]
            avg_position = sum(positions) / len(positions)
            best_position = min(positions)

            # Determine if this is a gap
            is_gap = (
                your_position is None or  # Not ranking
                your_position > avg_position + 5  # Significantly behind
            )

            if not is_gap:
                continue

            # Get volume/difficulty from any ranking that has it
            estimated_volume = None
            estimated_difficulty = None

            for comp, rankings in competitor_keywords.items():
                if keyword in rankings:
                    if rankings[keyword].search_volume:
                        estimated_volume = rankings[keyword].search_volume
                    if rankings[keyword].difficulty:
                        estimated_difficulty = rankings[keyword].difficulty
                    break

            # Calculate opportunity score
            opportunity_score = self._calculate_opportunity_score(
                your_position, avg_position, len(comp_rankings),
                total_competitors, estimated_volume
            )

            # Determine category and priority
            category = self._determine_category(your_position, avg_position)
            priority = self._determine_priority(
                opportunity_score, category, len(comp_rankings), total_competitors
            )

            # Classify intent
            intent = self._classify_intent(keyword)

            gap = KeywordGap(
                keyword=keyword,
                category=category,
                priority=priority,
                your_position=your_position,
                avg_competitor_position=avg_position,
                best_competitor_position=best_position,
                competitor_count=len(comp_rankings),
                competitors_ranking=comp_rankings,
                opportunity_score=round(opportunity_score, 2),
                estimated_volume=estimated_volume,
                estimated_difficulty=estimated_difficulty,
                search_intent=intent,
            )

            # Generate recommendations
            gap.recommendations = self._generate_recommendations(gap)

            gaps.append(gap)

        # Sort by opportunity score
        gaps.sort(key=lambda x: x.opportunity_score, reverse=True)

        self.logger.info(f"Found {len(gaps)} keyword gaps")

        return gaps

    def analyze_from_simple_lists(
        self,
        your_keywords: List[str],
        competitor_keywords: Dict[str, List[str]],
    ) -> List[KeywordGap]:
        """
        Simplified gap analysis from keyword lists (no positions).

        Args:
            your_keywords: Your keywords
            competitor_keywords: Dict of competitor -> keywords

        Returns:
            list: KeywordGap opportunities
        """
        # Convert to KeywordRanking format
        your_rankings = {
            kw: KeywordRanking(keyword=kw, position=1)  # Assume ranking
            for kw in your_keywords
        }

        comp_rankings = {}
        for comp, keywords in competitor_keywords.items():
            comp_rankings[comp] = {
                kw: KeywordRanking(keyword=kw, position=5)  # Assume top 5
                for kw in keywords
            }

        return self.analyze_keyword_gaps(your_rankings, comp_rankings)

    def get_missing_keywords(
        self,
        gaps: List[KeywordGap],
    ) -> List[KeywordGap]:
        """
        Get keywords you don't rank for at all.

        Args:
            gaps: All gaps

        Returns:
            list: Missing keyword gaps
        """
        return [g for g in gaps if g.category == GapCategory.MISSING]

    def get_by_intent(
        self,
        gaps: List[KeywordGap],
        intent: str,
    ) -> List[KeywordGap]:
        """
        Filter gaps by search intent.

        Args:
            gaps: All gaps
            intent: Desired intent

        Returns:
            list: Filtered gaps
        """
        return [g for g in gaps if g.search_intent == intent]

    def get_quick_wins(
        self,
        gaps: List[KeywordGap],
        limit: int = 20,
    ) -> List[KeywordGap]:
        """
        Get easiest keyword wins.

        Prioritizes low competition + high opportunity.

        Args:
            gaps: All gaps
            limit: Maximum to return

        Returns:
            list: Quick win gaps
        """
        # Filter for achievable targets
        achievable = [
            g for g in gaps
            if (g.avg_competitor_position > 5 or  # Lower competition
                g.priority in (KeywordPriority.CRITICAL, KeywordPriority.HIGH))
        ]

        return achievable[:limit]

    def generate_targeting_plan(
        self,
        gaps: List[KeywordGap],
        max_items: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Generate keyword targeting plan.

        Args:
            gaps: Gaps to plan
            max_items: Maximum plan items

        Returns:
            list: Targeting plan
        """
        # Group by priority
        by_priority = defaultdict(list)
        for gap in gaps:
            by_priority[gap.priority.value].append(gap)

        plan = []
        added = 0

        # Add in priority order
        for priority in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            for gap in by_priority[priority]:
                if added >= max_items:
                    break

                item = {
                    "keyword": gap.keyword,
                    "priority": gap.priority.value,
                    "category": gap.category.value,
                    "opportunity_score": gap.opportunity_score,
                    "your_position": gap.your_position or "Not ranking",
                    "competitor_avg_position": round(gap.avg_competitor_position, 1),
                    "competitors_ranking": gap.competitor_count,
                    "intent": gap.search_intent,
                    "action": "",
                    "recommendations": gap.recommendations,
                }

                # Set action based on category
                if gap.category == GapCategory.MISSING:
                    item["action"] = "Create new content"
                else:
                    item["action"] = "Optimize existing content"

                plan.append(item)
                added += 1

        return plan

    def save_gaps(
        self,
        gaps: List[KeywordGap],
        competitor_id: Optional[int] = None,
    ):
        """
        Save keyword gaps to database.

        Args:
            gaps: Gaps to save
            competitor_id: Optional competitor association
        """
        if not gaps:
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
            INSERT INTO keyword_gaps (
                keyword, category, priority, opportunity_score,
                your_position, avg_competitor_position, competitor_count,
                estimated_volume, search_intent, recommendations,
                competitor_id, metadata, created_at
            ) VALUES (
                :keyword, :category, :priority, :score,
                :your_pos, :avg_comp_pos, :comp_count,
                :volume, :intent, :recommendations,
                :competitor_id, :metadata, :created_at
            )
            ON CONFLICT (keyword) DO UPDATE SET
                opportunity_score = GREATEST(keyword_gaps.opportunity_score, EXCLUDED.opportunity_score),
                your_position = EXCLUDED.your_position,
                avg_competitor_position = EXCLUDED.avg_competitor_position,
                updated_at = NOW()
        """)

        with engine.connect() as conn:
            for gap in gaps:
                try:
                    conn.execute(insert_sql, {
                        "keyword": gap.keyword,
                        "category": gap.category.value,
                        "priority": gap.priority.value,
                        "score": gap.opportunity_score,
                        "your_pos": gap.your_position,
                        "avg_comp_pos": gap.avg_competitor_position,
                        "comp_count": gap.competitor_count,
                        "volume": gap.estimated_volume,
                        "intent": gap.search_intent,
                        "recommendations": json.dumps(gap.recommendations),
                        "competitor_id": competitor_id,
                        "metadata": json.dumps(gap.metadata),
                        "created_at": gap.identified_at,
                    })
                except Exception as e:
                    self.logger.debug(f"Error saving gap: {e}")

            conn.commit()

        self.logger.info(f"Saved {len(gaps)} keyword gaps to database")


# Module-level singleton
_keyword_gap_analyzer_instance = None


def get_keyword_gap_analyzer() -> KeywordGapAnalyzer:
    """Get or create the singleton KeywordGapAnalyzer instance."""
    global _keyword_gap_analyzer_instance

    if _keyword_gap_analyzer_instance is None:
        _keyword_gap_analyzer_instance = KeywordGapAnalyzer()

    return _keyword_gap_analyzer_instance
