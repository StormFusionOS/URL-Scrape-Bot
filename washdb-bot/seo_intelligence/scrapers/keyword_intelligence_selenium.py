"""
Keyword Intelligence Orchestrator (SeleniumBase Version)

Integrates all keyword intelligence components with SeleniumBase drivers:
- Autocomplete scraper for keyword discovery
- SERP scraper for SERP feature analysis
- Volume estimator for search volume
- Difficulty calculator for competition analysis
- Opportunity analyzer for prioritization

Provides unified keyword research workflow without external APIs.

Usage:
    from seo_intelligence.scrapers.keyword_intelligence_selenium import KeywordIntelligenceSelenium

    ki = KeywordIntelligenceSelenium()

    # Full keyword analysis
    analysis = ki.analyze_keyword("car wash near me")

    # Discover and analyze keywords
    opportunities = ki.discover_opportunities(
        seed_keywords=["car wash", "auto detailing"],
        max_keywords=50
    )

    # Get quick wins
    quick_wins = ki.get_quick_wins(opportunities)
"""

import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from runner.logging_setup import get_logger
from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper
from seo_intelligence.scrapers.autocomplete_scraper_selenium import (
    AutocompleteScraperSelenium, AutocompleteSuggestion, get_autocomplete_scraper_selenium
)
from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium, get_serp_scraper_selenium
from seo_intelligence.services import (
    get_volume_estimator,
    get_difficulty_calculator,
    get_opportunity_analyzer,
    VolumeEstimate,
    DifficultyResult,
    KeywordOpportunity,
    OpportunityTier,
    SearchIntent,
)


@dataclass
class KeywordAnalysis:
    """Complete keyword analysis result."""
    keyword: str
    volume: VolumeEstimate
    difficulty: DifficultyResult
    opportunity: KeywordOpportunity
    serp_features: Dict[str, Any]
    autocomplete_position: Optional[int] = None
    related_keywords: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "keyword": self.keyword,
            "volume": {
                "score": self.volume.volume_score,
                "category": self.volume.category.value,
                "estimated_monthly": f"{self.volume.estimated_monthly_min:,}-{self.volume.estimated_monthly_max:,}",
            },
            "difficulty": {
                "score": self.difficulty.difficulty_score,
                "level": self.difficulty.level.value,
                "time_to_rank": self.difficulty.estimated_time_to_rank,
            },
            "opportunity": {
                "score": self.opportunity.opportunity_score,
                "tier": self.opportunity.tier.value,
                "intent": self.opportunity.intent.value,
                "estimated_traffic": self.opportunity.estimated_traffic,
            },
            "serp_features": self.serp_features,
            "recommendations": self.opportunity.recommendations,
            "related_keywords": self.related_keywords[:10],
            "questions": self.questions[:5],
            "analyzed_at": self.analyzed_at.isoformat(),
        }


class KeywordIntelligenceSelenium(BaseSeleniumScraper):
    """
    Unified keyword intelligence orchestrator using SeleniumBase.

    Combines all keyword research capabilities into a single interface.
    """

    def __init__(
        self,
        tier: str = "D",  # Conservative for Google
        country: str = "us",
        language: str = "en",
        headless: bool = False,  # Headed mode works better against Google detection
        use_proxy: bool = True,  # Use residential proxies by default
    ):
        """
        Initialize keyword intelligence.

        Args:
            tier: Rate limit tier
            country: Country code for localized results
            language: Language code
            headless: Run browser in headless mode
            use_proxy: Use proxy pool
        """
        super().__init__(
            name="keyword_intelligence_selenium",
            tier=tier,
            headless=headless,
            use_proxy=use_proxy,
            max_retries=3,
            page_timeout=30000,
        )

        self.country = country
        self.language = language
        self.logger = get_logger("keyword_intelligence_selenium")

        # Configure GoogleCoordinator with our headless/proxy settings BEFORE creating scrapers
        # This ensures the shared browser session uses our settings
        from seo_intelligence.services import get_google_coordinator
        get_google_coordinator(headless=headless, use_proxy=use_proxy)

        # Initialize components (SeleniumBase versions)
        # These will use the GoogleCoordinator's shared browser with our settings
        self.autocomplete_scraper = get_autocomplete_scraper_selenium()
        self.serp_scraper = get_serp_scraper_selenium()
        self.volume_estimator = get_volume_estimator()
        self.difficulty_calculator = get_difficulty_calculator()
        self.opportunity_analyzer = get_opportunity_analyzer()

        # Statistics
        self.ki_stats = {
            "keywords_analyzed": 0,
            "opportunities_found": 0,
            "quick_wins": 0,
        }

    def _extract_serp_features(
        self,
        serp_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Extract SERP features for analysis.

        Args:
            serp_data: Raw SERP data

        Returns:
            dict: Normalized SERP features
        """
        return {
            "has_ads": serp_data.get("has_ads", False),
            "ad_count": serp_data.get("ad_count", 0),
            "has_shopping": serp_data.get("has_shopping", False),
            "has_featured_snippet": serp_data.get("has_featured_snippet", False),
            "has_people_also_ask": serp_data.get("has_paa", False),
            "paa_count": len(serp_data.get("paa_questions", [])),
            "has_knowledge_panel": serp_data.get("has_knowledge_panel", False),
            "has_local_pack": serp_data.get("has_local_pack", False),
            "has_video_results": serp_data.get("has_video", False),
            "has_image_pack": serp_data.get("has_images", False),
            "total_results": serp_data.get("total_results", 0),
            "related_searches": serp_data.get("related_searches", []),
            "organic_results": serp_data.get("organic_results", []),
        }

    def analyze_keyword(
        self,
        keyword: str,
        include_related: bool = True,
        include_questions: bool = True,
    ) -> KeywordAnalysis:
        """
        Perform complete analysis on a single keyword.

        Args:
            keyword: Keyword to analyze
            include_related: Include related keyword suggestions
            include_questions: Include question-based keywords

        Returns:
            KeywordAnalysis: Complete analysis
        """
        keyword = keyword.strip().lower()
        self.logger.info(f"Analyzing keyword: {keyword}")

        # 1. Get SERP data (using SeleniumBase SERP scraper)
        serp_result = self.serp_scraper.scrape_serp(
            keyword,
            country=self.country,
            language=self.language,
        )

        serp_features = self._extract_serp_features(serp_result or {})
        organic_results = serp_features.get("organic_results", [])

        # 2. Estimate volume
        volume = self.volume_estimator.estimate_volume(serp_features, keyword)

        # 3. Calculate difficulty
        difficulty = self.difficulty_calculator.calculate_difficulty(
            keyword, serp_features, organic_results
        )

        # 4. Analyze opportunity
        opportunity = self.opportunity_analyzer.analyze_keyword(
            keyword, serp_features, organic_results
        )

        # 5. Get related keywords (optional, using SeleniumBase autocomplete)
        related_keywords = []
        if include_related:
            suggestions = self.autocomplete_scraper.get_suggestions(keyword)
            related_keywords = [s.keyword for s in suggestions[:10]]

        # 6. Get questions (optional)
        questions = []
        if include_questions:
            question_suggestions = self.autocomplete_scraper.get_related_questions(keyword)
            questions = [s.keyword for s in question_suggestions[:5]]

        # Create analysis result
        analysis = KeywordAnalysis(
            keyword=keyword,
            volume=volume,
            difficulty=difficulty,
            opportunity=opportunity,
            serp_features=serp_features,
            related_keywords=related_keywords,
            questions=questions,
        )

        self.ki_stats["keywords_analyzed"] += 1

        self.logger.info(
            f"Analysis complete for '{keyword}': "
            f"Volume={volume.category.value}, "
            f"Difficulty={difficulty.level.value}, "
            f"Opportunity={opportunity.tier.value}"
        )

        return analysis

    def discover_opportunities(
        self,
        seed_keywords: List[str],
        max_keywords: int = 50,
        expand_seeds: bool = True,
        min_opportunity_score: float = 20.0,
    ) -> List[KeywordOpportunity]:
        """
        Discover and analyze keyword opportunities from seed keywords.

        Args:
            seed_keywords: Starting keywords
            max_keywords: Maximum keywords to analyze
            expand_seeds: Whether to expand seeds with autocomplete
            min_opportunity_score: Minimum score to include

        Returns:
            list: Prioritized KeywordOpportunity objects
        """
        self.logger.info(
            f"Discovering opportunities from {len(seed_keywords)} seeds "
            f"(max={max_keywords}, expand={expand_seeds})"
        )

        # 1. Collect keywords to analyze
        keywords_to_analyze = set(k.lower().strip() for k in seed_keywords)

        if expand_seeds:
            for seed in seed_keywords:
                suggestions = self.autocomplete_scraper.expand_keyword(
                    seed,
                    include_alphabet=True,
                    include_questions=True,
                    include_modifiers=True,
                    max_expansions=20,  # Limit per seed
                )

                for suggestion in suggestions:
                    keywords_to_analyze.add(suggestion.keyword)

                    if len(keywords_to_analyze) >= max_keywords:
                        break

                if len(keywords_to_analyze) >= max_keywords:
                    break

        # Convert to list and limit
        keywords_list = list(keywords_to_analyze)[:max_keywords]

        self.logger.info(f"Analyzing {len(keywords_list)} keywords...")

        # 2. Analyze each keyword
        opportunities = []

        for keyword in keywords_list:
            try:
                analysis = self.analyze_keyword(
                    keyword,
                    include_related=False,  # Skip to speed up
                    include_questions=False,
                )

                if analysis.opportunity.opportunity_score >= min_opportunity_score:
                    opportunities.append(analysis.opportunity)
                    self.ki_stats["opportunities_found"] += 1

            except Exception as e:
                self.logger.warning(f"Failed to analyze '{keyword}': {e}")
                continue

        # 3. Sort by opportunity score
        opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)

        # 4. Assign priority ranks
        for i, opp in enumerate(opportunities):
            opp.priority_rank = i + 1

        self.logger.info(
            f"Found {len(opportunities)} opportunities above threshold"
        )

        return opportunities

    def get_quick_wins(
        self,
        opportunities: List[KeywordOpportunity],
        limit: int = 10,
    ) -> List[KeywordOpportunity]:
        """
        Get top quick win opportunities.

        Args:
            opportunities: List of analyzed opportunities
            limit: Maximum to return

        Returns:
            list: Top quick wins
        """
        quick_wins = [
            opp for opp in opportunities
            if opp.tier in (OpportunityTier.QUICK_WIN, OpportunityTier.HIGH_VALUE)
        ]

        result = quick_wins[:limit]
        self.ki_stats["quick_wins"] = len(result)

        return result

    def get_by_intent(
        self,
        opportunities: List[KeywordOpportunity],
        intent: SearchIntent,
    ) -> List[KeywordOpportunity]:
        """
        Filter opportunities by search intent.

        Args:
            opportunities: List of opportunities
            intent: Desired intent

        Returns:
            list: Filtered opportunities
        """
        return [opp for opp in opportunities if opp.intent == intent]

    def generate_content_strategy(
        self,
        opportunities: List[KeywordOpportunity],
        max_topics: int = 10,
    ) -> Dict[str, Any]:
        """
        Generate content strategy from opportunities.

        Groups keywords by intent and priority.

        Args:
            opportunities: Analyzed opportunities
            max_topics: Maximum topics to include

        Returns:
            dict: Content strategy plan
        """
        if not opportunities:
            return {"error": "No opportunities to analyze"}

        # Group by intent
        intent_groups = {}
        for intent in SearchIntent:
            intent_opps = self.get_by_intent(opportunities, intent)
            if intent_opps:
                intent_groups[intent.value] = [
                    {
                        "keyword": o.keyword,
                        "score": o.opportunity_score,
                        "tier": o.tier.value,
                        "traffic": o.estimated_traffic,
                    }
                    for o in intent_opps[:5]
                ]

        # Get quick wins
        quick_wins = self.get_quick_wins(opportunities, limit=5)

        # Calculate totals
        total_traffic = sum(o.estimated_traffic for o in opportunities)

        return {
            "summary": {
                "total_keywords": len(opportunities),
                "total_potential_traffic": total_traffic,
                "quick_wins_count": len(quick_wins),
            },
            "quick_wins": [
                {
                    "keyword": o.keyword,
                    "score": o.opportunity_score,
                    "difficulty": o.difficulty_result.difficulty_score,
                    "time_to_rank": o.difficulty_result.estimated_time_to_rank,
                }
                for o in quick_wins
            ],
            "by_intent": intent_groups,
            "recommendations": [
                "Start with quick wins for early traffic gains",
                "Create pillar content for high-volume keywords",
                "Build topical authority with related content clusters",
                "Prioritize transactional keywords for conversions",
            ],
        }

    def save_analysis(
        self,
        opportunities: List[KeywordOpportunity],
        competitor_id: Optional[int] = None,
    ):
        """
        Save opportunities to database.

        Args:
            opportunities: Opportunities to save
            competitor_id: Optional competitor association
        """
        self.opportunity_analyzer.save_opportunities(opportunities, competitor_id)

    def run(
        self,
        seed_keywords: List[str],
        max_keywords: int = 50,
        expand: bool = True,
        save_to_db: bool = True,
        competitor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run full keyword intelligence workflow.

        Args:
            seed_keywords: Starting keywords
            max_keywords: Maximum keywords to analyze
            expand: Whether to expand with autocomplete
            save_to_db: Whether to save results
            competitor_id: Optional competitor ID

        Returns:
            dict: Complete analysis results
        """
        # Discover opportunities
        opportunities = self.discover_opportunities(
            seed_keywords=seed_keywords,
            max_keywords=max_keywords,
            expand_seeds=expand,
        )

        # Generate strategy
        strategy = self.generate_content_strategy(opportunities)

        # Save to database
        if save_to_db:
            self.save_analysis(opportunities, competitor_id)

        # Generate report
        report = self.opportunity_analyzer.generate_report(opportunities)

        return {
            "opportunities": [
                {
                    "keyword": o.keyword,
                    "opportunity_score": o.opportunity_score,
                    "tier": o.tier.value,
                    "volume_category": o.volume_estimate.category.value,
                    "difficulty_level": o.difficulty_result.level.value,
                    "intent": o.intent.value,
                    "estimated_traffic": o.estimated_traffic,
                    "time_to_rank": o.difficulty_result.estimated_time_to_rank,
                }
                for o in opportunities[:20]  # Top 20
            ],
            "strategy": strategy,
            "report": report,
            "stats": self.ki_stats,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics."""
        base_stats = super().get_stats()
        return {**base_stats, **self.ki_stats}


# Module-level singleton
_keyword_intelligence_selenium_instance = None


def get_keyword_intelligence_selenium() -> KeywordIntelligenceSelenium:
    """Get or create the singleton KeywordIntelligenceSelenium instance."""
    global _keyword_intelligence_selenium_instance

    if _keyword_intelligence_selenium_instance is None:
        _keyword_intelligence_selenium_instance = KeywordIntelligenceSelenium()

    return _keyword_intelligence_selenium_instance
