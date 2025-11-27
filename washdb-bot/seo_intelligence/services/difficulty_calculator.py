"""
Keyword Difficulty Calculator Service

Calculates keyword difficulty based on SERP analysis without external APIs.
Analyzes competition strength using observable signals.

Difficulty Factors:
- Domain authority indicators (known brands, domain age signals)
- SERP feature saturation (reduces organic opportunity)
- Content depth of ranking pages
- Backlink profile indicators
- Title/content optimization level

Usage:
    from seo_intelligence.services.difficulty_calculator import DifficultyCalculator

    calc = DifficultyCalculator()
    difficulty = calc.calculate_difficulty(serp_data, organic_results)

Difficulty Scale (0-100):
- 0-20: Very Easy (weak competition, quick wins)
- 21-40: Easy (achievable with good content)
- 41-60: Moderate (requires strong content + some backlinks)
- 61-80: Hard (requires authority + many backlinks)
- 81-100: Very Hard (dominated by major brands)
"""

import re
import math
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from urllib.parse import urlparse

from runner.logging_setup import get_logger


class DifficultyLevel(Enum):
    """Keyword difficulty levels."""
    VERY_EASY = "VERY_EASY"    # 0-20
    EASY = "EASY"              # 21-40
    MODERATE = "MODERATE"      # 41-60
    HARD = "HARD"              # 61-80
    VERY_HARD = "VERY_HARD"    # 81-100


@dataclass
class DifficultyResult:
    """Keyword difficulty calculation result."""
    keyword: str
    difficulty_score: float  # 0-100
    level: DifficultyLevel
    factors: Dict[str, float]  # Individual factor scores
    recommendations: List[str]
    estimated_time_to_rank: str  # "1-3 months", "3-6 months", etc.
    confidence: float  # 0-1
    calculated_at: datetime = field(default_factory=datetime.now)


class DifficultyCalculator:
    """
    Calculates keyword difficulty from SERP analysis.

    Uses multiple competition signals to estimate how hard
    it would be to rank for a keyword.
    """

    # Difficulty level thresholds
    LEVEL_THRESHOLDS = {
        80: DifficultyLevel.VERY_HARD,
        60: DifficultyLevel.HARD,
        40: DifficultyLevel.MODERATE,
        20: DifficultyLevel.EASY,
        0: DifficultyLevel.VERY_EASY,
    }

    # Time to rank estimates per difficulty level
    TIME_TO_RANK = {
        DifficultyLevel.VERY_EASY: "1-3 months",
        DifficultyLevel.EASY: "3-6 months",
        DifficultyLevel.MODERATE: "6-12 months",
        DifficultyLevel.HARD: "12-18 months",
        DifficultyLevel.VERY_HARD: "18+ months",
    }

    # Factor weights (must sum to 1.0)
    FACTOR_WEIGHTS = {
        "domain_authority": 0.30,       # Strength of ranking domains
        "content_depth": 0.20,          # Word count, comprehensiveness
        "serp_features": 0.15,          # SERP feature saturation
        "title_optimization": 0.15,     # Keyword in titles
        "backlink_indicators": 0.15,    # Backlink signals
        "content_freshness": 0.05,      # Age of content
    }

    # Known high-authority domains with estimated DA scores
    DOMAIN_AUTHORITY_TIERS = {
        # Tier 1: DA 90+ (Major brands, news)
        "wikipedia.org": 95, "amazon.com": 96, "facebook.com": 96,
        "youtube.com": 98, "twitter.com": 94, "instagram.com": 93,
        "linkedin.com": 98, "apple.com": 97, "microsoft.com": 97,
        "google.com": 98, "nytimes.com": 95, "bbc.com": 95,
        "cnn.com": 94, "forbes.com": 94, "theguardian.com": 94,
        "washingtonpost.com": 93, "reddit.com": 91, "quora.com": 93,

        # Tier 2: DA 70-89 (Major sites, established brands)
        "yelp.com": 93, "tripadvisor.com": 90, "imdb.com": 92,
        "healthline.com": 89, "webmd.com": 92, "mayoclinic.org": 89,
        "indeed.com": 91, "glassdoor.com": 89, "zillow.com": 90,
        "etsy.com": 87, "shopify.com": 86, "wix.com": 85,
        "medium.com": 95, "wordpress.com": 92, "blogspot.com": 90,
        "github.com": 96, "stackoverflow.com": 93,

        # Tier 3: DA 50-69 (Established sites)
        "homedepot.com": 85, "lowes.com": 83, "walmart.com": 92,
        "target.com": 88, "bestbuy.com": 85, "costco.com": 82,
    }

    # TLD authority modifiers
    TLD_MODIFIERS = {
        ".gov": 15,   # Government sites
        ".edu": 12,   # Educational institutions
        ".org": 5,    # Organizations (slight boost)
        ".com": 0,    # Standard
        ".net": 0,    # Standard
        ".io": -2,    # Newer TLD
        ".co": -3,    # Newer TLD
    }

    def __init__(self):
        """Initialize difficulty calculator."""
        self.logger = get_logger("difficulty_calculator")

    def _estimate_domain_authority(self, domain: str) -> float:
        """
        Estimate domain authority from known domains or heuristics.

        Args:
            domain: Domain to analyze

        Returns:
            float: Estimated DA (0-100)
        """
        domain = domain.lower().strip()

        # Remove www prefix
        if domain.startswith("www."):
            domain = domain[4:]

        # Check known domains
        if domain in self.DOMAIN_AUTHORITY_TIERS:
            return self.DOMAIN_AUTHORITY_TIERS[domain]

        # Check if subdomain of known domain
        for known_domain, da in self.DOMAIN_AUTHORITY_TIERS.items():
            if domain.endswith(f".{known_domain}"):
                return da * 0.7  # Subdomains get 70% of parent DA

        # Apply TLD modifiers
        base_da = 30  # Unknown domain baseline

        for tld, modifier in self.TLD_MODIFIERS.items():
            if domain.endswith(tld):
                base_da += modifier
                break

        # Domain length heuristic (shorter domains often more established)
        domain_parts = domain.split(".")
        if len(domain_parts) >= 2:
            name_length = len(domain_parts[-2])
            if name_length <= 5:
                base_da += 10  # Short domains
            elif name_length <= 10:
                base_da += 5

        return min(100, max(0, base_da))

    def _calculate_domain_authority_score(
        self,
        organic_results: List[Dict],
    ) -> float:
        """
        Calculate difficulty based on ranking domains' authority.

        Args:
            organic_results: List of organic search results

        Returns:
            float: 0-100 difficulty contribution
        """
        if not organic_results:
            return 30.0  # Default

        das = []
        for result in organic_results[:10]:
            domain = result.get("domain", "")
            if domain:
                da = self._estimate_domain_authority(domain)
                das.append(da)

        if not das:
            return 30.0

        # Use weighted average (top positions matter more)
        weighted_sum = 0
        weight_total = 0

        for i, da in enumerate(das):
            position_weight = 1.0 / (i + 1)  # Position 1 = 1.0, Position 10 = 0.1
            weighted_sum += da * position_weight
            weight_total += position_weight

        avg_da = weighted_sum / weight_total if weight_total > 0 else 0

        return avg_da

    def _calculate_content_depth_score(
        self,
        organic_results: List[Dict],
    ) -> float:
        """
        Calculate difficulty based on content depth of ranking pages.

        Args:
            organic_results: Results with content metrics

        Returns:
            float: 0-100 difficulty contribution
        """
        word_counts = []
        has_schema = 0
        has_images = 0

        for result in organic_results[:10]:
            # Word count
            wc = result.get("word_count", 0)
            if wc > 0:
                word_counts.append(wc)

            # Rich content signals
            if result.get("has_schema", False):
                has_schema += 1
            if result.get("has_images", False) or result.get("image_count", 0) > 0:
                has_images += 1

        # Calculate word count difficulty
        if word_counts:
            avg_words = sum(word_counts) / len(word_counts)

            # Higher word count = more competitive
            if avg_words >= 3000:
                word_score = 90
            elif avg_words >= 2000:
                word_score = 70
            elif avg_words >= 1500:
                word_score = 55
            elif avg_words >= 1000:
                word_score = 40
            elif avg_words >= 500:
                word_score = 25
            else:
                word_score = 15
        else:
            word_score = 40  # Default

        # Adjust for rich content presence
        rich_content_bonus = 0
        if has_schema >= 5:
            rich_content_bonus += 10
        if has_images >= 5:
            rich_content_bonus += 5

        return min(100, word_score + rich_content_bonus)

    def _calculate_serp_feature_score(
        self,
        serp_data: Dict,
    ) -> float:
        """
        Calculate difficulty based on SERP feature saturation.

        More SERP features = less organic real estate = harder.

        Args:
            serp_data: SERP features data

        Returns:
            float: 0-100 difficulty contribution
        """
        difficulty = 0

        # Each SERP feature reduces organic visibility
        if serp_data.get("has_ads", False):
            difficulty += 15
            ad_count = serp_data.get("ad_count", 0)
            difficulty += min(15, ad_count * 5)  # Up to 15 more

        if serp_data.get("has_shopping", False):
            difficulty += 15

        if serp_data.get("has_featured_snippet", False):
            difficulty += 10  # Takes position 0

        if serp_data.get("has_knowledge_panel", False):
            difficulty += 10

        if serp_data.get("has_people_also_ask", False):
            difficulty += 5

        if serp_data.get("has_local_pack", False):
            difficulty += 10

        if serp_data.get("has_video_results", False):
            difficulty += 5

        if serp_data.get("has_image_pack", False):
            difficulty += 5

        return min(100, difficulty)

    def _calculate_title_optimization_score(
        self,
        keyword: str,
        organic_results: List[Dict],
    ) -> float:
        """
        Calculate difficulty based on title optimization.

        If competitors have keyword in titles, harder to outrank.

        Args:
            keyword: Target keyword
            organic_results: Results with titles

        Returns:
            float: 0-100 difficulty contribution
        """
        if not keyword or not organic_results:
            return 30.0

        keyword_lower = keyword.lower()
        keyword_words = set(keyword_lower.split())

        exact_match_count = 0
        partial_match_count = 0

        for result in organic_results[:10]:
            title = result.get("title", "").lower()

            # Check for exact keyword match in title
            if keyword_lower in title:
                exact_match_count += 1
            elif all(word in title for word in keyword_words):
                partial_match_count += 1

        # More optimized titles = higher difficulty
        total_optimized = exact_match_count + (partial_match_count * 0.5)

        if total_optimized >= 8:
            return 90
        elif total_optimized >= 6:
            return 70
        elif total_optimized >= 4:
            return 50
        elif total_optimized >= 2:
            return 30
        return 15

    def _calculate_backlink_indicator_score(
        self,
        organic_results: List[Dict],
    ) -> float:
        """
        Calculate difficulty based on backlink indicators.

        Uses observable signals since we don't have backlink API.

        Args:
            organic_results: Results with backlink indicators

        Returns:
            float: 0-100 difficulty contribution
        """
        # Without API, use proxy signals:
        # - Social shares (if available)
        # - Domain authority (correlates with backlinks)
        # - Age indicators

        das = []
        for result in organic_results[:10]:
            domain = result.get("domain", "")
            if domain:
                da = self._estimate_domain_authority(domain)
                das.append(da)

        if not das:
            return 40.0

        avg_da = sum(das) / len(das)

        # High DA = high backlinks = high difficulty
        return avg_da

    def _calculate_freshness_score(
        self,
        organic_results: List[Dict],
    ) -> float:
        """
        Calculate difficulty based on content freshness.

        Fresher content = more active competition = harder.

        Args:
            organic_results: Results with date information

        Returns:
            float: 0-100 difficulty contribution
        """
        fresh_count = 0
        dated_count = 0

        current_year = datetime.now().year

        for result in organic_results[:10]:
            # Check for date in snippet or metadata
            date_str = result.get("date", "") or result.get("published_date", "")
            snippet = result.get("snippet", "")

            # Look for year patterns
            years_found = re.findall(r'\b(20\d{2})\b', f"{date_str} {snippet}")

            if years_found:
                latest_year = max(int(y) for y in years_found)
                if latest_year >= current_year - 1:
                    fresh_count += 1
                else:
                    dated_count += 1

        total_dated = fresh_count + dated_count

        if total_dated == 0:
            return 40.0  # No data

        freshness_ratio = fresh_count / total_dated

        # More fresh content = more active competition
        if freshness_ratio >= 0.8:
            return 80
        elif freshness_ratio >= 0.6:
            return 60
        elif freshness_ratio >= 0.4:
            return 40
        elif freshness_ratio >= 0.2:
            return 25
        return 15

    def _generate_recommendations(
        self,
        difficulty: DifficultyResult,
        factors: Dict[str, float],
        keyword: str,
    ) -> List[str]:
        """
        Generate actionable recommendations based on difficulty.

        Args:
            difficulty: Difficulty result
            factors: Individual factor scores
            keyword: Target keyword

        Returns:
            list: Recommendations
        """
        recommendations = []
        level = difficulty.level

        # General recommendations by difficulty
        if level == DifficultyLevel.VERY_EASY:
            recommendations.append(
                "Low competition - create quality content and you should rank quickly"
            )
            recommendations.append(
                "Focus on comprehensive coverage to establish authority"
            )

        elif level == DifficultyLevel.EASY:
            recommendations.append(
                "Achievable with well-optimized, in-depth content (1500+ words)"
            )
            recommendations.append(
                "Build 5-10 quality backlinks to accelerate ranking"
            )

        elif level == DifficultyLevel.MODERATE:
            recommendations.append(
                "Create best-in-class content (2000+ words) with unique insights"
            )
            recommendations.append(
                "Aim for 20-50 quality backlinks from relevant sites"
            )
            recommendations.append(
                "Consider targeting long-tail variations first"
            )

        elif level == DifficultyLevel.HARD:
            recommendations.append(
                "Requires significant authority - build domain strength first"
            )
            recommendations.append(
                "Target 50-100+ backlinks from high-authority sources"
            )
            recommendations.append(
                "Consider building topical authority with related content"
            )
            recommendations.append(
                "May need 12-18 months of consistent effort"
            )

        else:  # VERY_HARD
            recommendations.append(
                "Dominated by major brands - consider alternative strategies"
            )
            recommendations.append(
                "Target long-tail variations of this keyword"
            )
            recommendations.append(
                "Focus on building overall domain authority first"
            )
            recommendations.append(
                "Consider featured snippet or PAA optimization"
            )

        # Factor-specific recommendations
        if factors.get("content_depth", 0) > 70:
            recommendations.append(
                "Competitors have deep content - aim for 2500+ words"
            )

        if factors.get("title_optimization", 0) > 70:
            recommendations.append(
                "Most competitors have optimized titles - ensure exact match in H1"
            )

        if factors.get("serp_features", 0) > 60:
            recommendations.append(
                "SERP has many features - optimize for featured snippets"
            )

        return recommendations

    def calculate_difficulty(
        self,
        keyword: str,
        serp_data: Dict[str, Any],
        organic_results: List[Dict[str, Any]],
    ) -> DifficultyResult:
        """
        Calculate keyword difficulty from SERP data.

        Args:
            keyword: Target keyword
            serp_data: SERP features dictionary
            organic_results: List of organic results with metadata

        Returns:
            DifficultyResult: Difficulty calculation
        """
        factors = {}
        weighted_scores = []

        # Calculate each factor
        factor_funcs = {
            "domain_authority": (
                lambda: self._calculate_domain_authority_score(organic_results)
            ),
            "content_depth": (
                lambda: self._calculate_content_depth_score(organic_results)
            ),
            "serp_features": (
                lambda: self._calculate_serp_feature_score(serp_data)
            ),
            "title_optimization": (
                lambda: self._calculate_title_optimization_score(keyword, organic_results)
            ),
            "backlink_indicators": (
                lambda: self._calculate_backlink_indicator_score(organic_results)
            ),
            "content_freshness": (
                lambda: self._calculate_freshness_score(organic_results)
            ),
        }

        for factor_name, calc_func in factor_funcs.items():
            try:
                score = calc_func()
                weight = self.FACTOR_WEIGHTS.get(factor_name, 0.1)

                factors[factor_name] = round(score, 2)
                weighted_scores.append(score * weight)

            except Exception as e:
                self.logger.debug(f"Error calculating {factor_name}: {e}")
                factors[factor_name] = 40.0  # Default

        # Calculate composite difficulty score
        total_weight = sum(self.FACTOR_WEIGHTS.values())
        difficulty_score = sum(weighted_scores) / total_weight if total_weight > 0 else 40

        # Determine level
        level = DifficultyLevel.VERY_EASY
        for threshold, lvl in sorted(self.LEVEL_THRESHOLDS.items(), reverse=True):
            if difficulty_score >= threshold:
                level = lvl
                break

        # Create result
        result = DifficultyResult(
            keyword=keyword,
            difficulty_score=round(difficulty_score, 2),
            level=level,
            factors=factors,
            recommendations=[],
            estimated_time_to_rank=self.TIME_TO_RANK.get(level, "6-12 months"),
            confidence=0.75,  # Based on available data
        )

        # Generate recommendations
        result.recommendations = self._generate_recommendations(result, factors, keyword)

        self.logger.debug(
            f"Difficulty for '{keyword}': {difficulty_score:.1f} ({level.value})"
        )

        return result

    def batch_calculate(
        self,
        keywords_data: List[Tuple[str, Dict, List[Dict]]],
    ) -> List[DifficultyResult]:
        """
        Calculate difficulty for multiple keywords.

        Args:
            keywords_data: List of (keyword, serp_data, organic_results) tuples

        Returns:
            list: DifficultyResult objects sorted by difficulty ascending
        """
        results = []

        for keyword, serp_data, organic_results in keywords_data:
            result = self.calculate_difficulty(keyword, serp_data, organic_results)
            results.append(result)

        # Sort by difficulty (easiest first)
        results.sort(key=lambda x: x.difficulty_score)

        return results

    def get_difficulty_label(self, score: float) -> str:
        """
        Get human-readable difficulty label.

        Args:
            score: Difficulty score (0-100)

        Returns:
            str: Label like "Easy (25/100)"
        """
        level = DifficultyLevel.VERY_EASY
        for threshold, lvl in sorted(self.LEVEL_THRESHOLDS.items(), reverse=True):
            if score >= threshold:
                level = lvl
                break

        return f"{level.value.replace('_', ' ').title()} ({score:.0f}/100)"


# Module-level singleton
_difficulty_calculator_instance = None


def get_difficulty_calculator() -> DifficultyCalculator:
    """Get or create the singleton DifficultyCalculator instance."""
    global _difficulty_calculator_instance

    if _difficulty_calculator_instance is None:
        _difficulty_calculator_instance = DifficultyCalculator()

    return _difficulty_calculator_instance
