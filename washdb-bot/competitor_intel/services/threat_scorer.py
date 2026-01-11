"""
Threat Scorer

Calculates competitive threat levels for each competitor based on:
- Ranking overlap (same keywords)
- Service overlap (same services offered)
- Geographic overlap (same market area)
- Review strength (ratings and volume)
- Market presence (citations, backlinks)
- Growth velocity (ranking changes, review velocity)

Threat Level Scale: 1-5
    1: Low threat - minimal overlap, weak presence
    2: Minor threat - some overlap, moderate presence
    3: Moderate threat - significant overlap, good presence
    4: High threat - strong overlap, strong presence
    5: Critical threat - direct competitor, dominant presence
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import text

from db.database_manager import get_db_manager

logger = logging.getLogger(__name__)


@dataclass
class ThreatFactors:
    """Individual threat factor scores (0-100 scale)."""
    ranking_overlap: float = 0.0
    service_overlap: float = 0.0
    geographic_overlap: float = 0.0
    review_strength: float = 0.0
    market_presence: float = 0.0
    growth_velocity: float = 0.0

    # Computed scores
    raw_score: float = 0.0
    weighted_score: float = 0.0
    threat_level: int = 1


class ThreatScorer:
    """
    Calculates competitive threat scores for competitors.

    Uses multiple factors weighted by importance to generate
    an overall threat level from 1-5.
    """

    # Factor weights (must sum to 1.0)
    WEIGHTS = {
        'ranking_overlap': 0.25,      # How much they rank for our keywords
        'service_overlap': 0.20,      # How similar their services are
        'geographic_overlap': 0.15,   # Same market area
        'review_strength': 0.15,      # Ratings and volume
        'market_presence': 0.15,      # Citations, visibility
        'growth_velocity': 0.10,      # How fast they're growing
    }

    # Threat level thresholds (weighted score -> level)
    THREAT_THRESHOLDS = [
        (80, 5),  # >= 80 = Critical threat
        (60, 4),  # >= 60 = High threat
        (40, 3),  # >= 40 = Moderate threat
        (20, 2),  # >= 20 = Minor threat
        (0, 1),   # < 20 = Low threat
    ]

    def __init__(self, company_id: int):
        self.company_id = company_id
        self.db_manager = get_db_manager()
        self._company_data = None
        self._company_keywords = None
        self._company_services = None

    def calculate_threat(self, competitor_id: int, domain: str) -> ThreatFactors:
        """
        Calculate the threat score for a competitor.

        Args:
            competitor_id: The competitor ID
            domain: Competitor's domain name

        Returns:
            ThreatFactors with all scores and final threat level
        """
        factors = ThreatFactors()

        try:
            # Load company data once for comparison
            self._load_company_data()

            # Calculate each factor
            factors.ranking_overlap = self._calc_ranking_overlap(competitor_id, domain)
            factors.service_overlap = self._calc_service_overlap(competitor_id)
            factors.geographic_overlap = self._calc_geographic_overlap(competitor_id)
            factors.review_strength = self._calc_review_strength(competitor_id)
            factors.market_presence = self._calc_market_presence(competitor_id, domain)
            factors.growth_velocity = self._calc_growth_velocity(competitor_id, domain)

            # Calculate weighted score
            factors.raw_score = sum([
                factors.ranking_overlap,
                factors.service_overlap,
                factors.geographic_overlap,
                factors.review_strength,
                factors.market_presence,
                factors.growth_velocity,
            ]) / 6

            factors.weighted_score = (
                factors.ranking_overlap * self.WEIGHTS['ranking_overlap'] +
                factors.service_overlap * self.WEIGHTS['service_overlap'] +
                factors.geographic_overlap * self.WEIGHTS['geographic_overlap'] +
                factors.review_strength * self.WEIGHTS['review_strength'] +
                factors.market_presence * self.WEIGHTS['market_presence'] +
                factors.growth_velocity * self.WEIGHTS['growth_velocity']
            )

            # Convert to threat level
            factors.threat_level = self._score_to_level(factors.weighted_score)

            # Save to database
            self._save_threat_score(competitor_id, factors)

        except Exception as e:
            logger.error(f"Failed to calculate threat for competitor {competitor_id}: {e}")

        return factors

    def _load_company_data(self):
        """Load our company's data for comparison."""
        if self._company_data is not None:
            return

        try:
            with self.db_manager.get_session() as session:
                # Get company info
                result = session.execute(text("""
                    SELECT domain, city, state, primary_service_category
                    FROM companies
                    WHERE id = :company_id
                """), {'company_id': self.company_id})

                row = result.fetchone()
                if row:
                    self._company_data = {
                        'domain': row[0],
                        'city': row[1],
                        'state': row[2],
                        'category': row[3],
                    }

                # Get our keywords
                result = session.execute(text("""
                    SELECT DISTINCT keyword
                    FROM keyword_rankings
                    WHERE domain = :domain
                """), {'domain': self._company_data.get('domain', '')})

                self._company_keywords = set(row[0] for row in result.fetchall())

                # Get our services (if we track them)
                result = session.execute(text("""
                    SELECT DISTINCT service_name
                    FROM company_services
                    WHERE company_id = :company_id
                """), {'company_id': self.company_id})

                self._company_services = set(row[0].lower() for row in result.fetchall())

        except Exception as e:
            logger.debug(f"Error loading company data: {e}")
            self._company_data = {}
            self._company_keywords = set()
            self._company_services = set()

    def _calc_ranking_overlap(self, competitor_id: int, domain: str) -> float:
        """
        Calculate ranking overlap score (0-100).

        Based on:
        - How many of our keywords they also rank for
        - Their positions relative to ours
        """
        if not self._company_keywords:
            return 50.0  # Default to moderate if no data

        try:
            with self.db_manager.get_session() as session:
                # Get competitor's keyword rankings
                result = session.execute(text("""
                    SELECT keyword, position
                    FROM keyword_rankings
                    WHERE domain = :domain
                    ORDER BY captured_at DESC
                """), {'domain': domain})

                competitor_rankings = {}
                for row in result.fetchall():
                    if row[0] not in competitor_rankings:
                        competitor_rankings[row[0]] = row[1]

                # Count overlapping keywords
                overlap_count = 0
                beating_us_count = 0

                for keyword in self._company_keywords:
                    if keyword in competitor_rankings:
                        overlap_count += 1
                        # Check if they're beating us
                        our_pos = self._get_our_position(keyword)
                        their_pos = competitor_rankings[keyword]
                        if their_pos and our_pos and their_pos < our_pos:
                            beating_us_count += 1

                if not self._company_keywords:
                    return 0.0

                # Score: 60% for overlap percentage, 40% for positions
                overlap_pct = (overlap_count / len(self._company_keywords)) * 100
                beating_pct = (beating_us_count / max(overlap_count, 1)) * 100

                score = (overlap_pct * 0.6) + (beating_pct * 0.4)
                return min(score, 100.0)

        except Exception as e:
            logger.debug(f"Error calculating ranking overlap: {e}")
            return 0.0

    def _get_our_position(self, keyword: str) -> Optional[int]:
        """Get our position for a keyword."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT position
                    FROM keyword_rankings
                    WHERE domain = :domain AND keyword = :keyword
                    ORDER BY captured_at DESC
                    LIMIT 1
                """), {
                    'domain': self._company_data.get('domain', ''),
                    'keyword': keyword,
                })

                row = result.fetchone()
                return row[0] if row else None

        except Exception:
            return None

    def _calc_service_overlap(self, competitor_id: int) -> float:
        """
        Calculate service overlap score (0-100).

        Based on how many services they offer that we also offer.
        """
        if not self._company_services:
            return 50.0  # Default if no service data

        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT service_name
                    FROM competitor_services
                    WHERE competitor_id = :competitor_id AND is_active = true
                """), {'competitor_id': competitor_id})

                competitor_services = set(row[0].lower() for row in result.fetchall())

                if not competitor_services:
                    return 0.0

                # Calculate Jaccard similarity
                intersection = len(self._company_services & competitor_services)
                union = len(self._company_services | competitor_services)

                if union == 0:
                    return 0.0

                similarity = (intersection / union) * 100
                return similarity

        except Exception as e:
            logger.debug(f"Error calculating service overlap: {e}")
            return 0.0

    def _calc_geographic_overlap(self, competitor_id: int) -> float:
        """
        Calculate geographic overlap score (0-100).

        Based on same city/market area.
        """
        if not self._company_data:
            return 50.0

        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT city, state, service_area_radius
                    FROM competitors
                    WHERE competitor_id = :competitor_id
                """), {'competitor_id': competitor_id})

                row = result.fetchone()
                if not row:
                    return 0.0

                competitor_city = (row[0] or '').lower()
                competitor_state = (row[1] or '').lower()

                our_city = (self._company_data.get('city') or '').lower()
                our_state = (self._company_data.get('state') or '').lower()

                score = 0.0

                # Same city = high overlap
                if competitor_city and our_city:
                    if competitor_city == our_city:
                        score = 100.0
                    elif competitor_state == our_state:
                        score = 50.0  # Same state, different city
                    else:
                        score = 10.0  # Different state

                return score

        except Exception as e:
            logger.debug(f"Error calculating geographic overlap: {e}")
            return 0.0

    def _calc_review_strength(self, competitor_id: int) -> float:
        """
        Calculate review strength score (0-100).

        Based on:
        - Average rating across platforms
        - Total review count
        - Recent review velocity
        """
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT
                        AVG(rating_avg) as avg_rating,
                        SUM(review_count) as total_reviews,
                        SUM(review_count_30d) as recent_reviews
                    FROM competitor_reviews_aggregate
                    WHERE competitor_id = :competitor_id
                      AND captured_at > NOW() - INTERVAL '7 days'
                """), {'competitor_id': competitor_id})

                row = result.fetchone()
                if not row or not row[0]:
                    return 0.0

                avg_rating = float(row[0]) if row[0] else 0
                total_reviews = int(row[1]) if row[1] else 0
                recent_reviews = int(row[2]) if row[2] else 0

                # Rating score (4.5+ = 100, 4.0 = 75, 3.5 = 50, etc.)
                rating_score = max(0, min(100, (avg_rating - 2.5) * 40))

                # Volume score (logarithmic scale)
                import math
                volume_score = min(100, math.log10(max(1, total_reviews)) * 33)

                # Velocity score (recent reviews)
                velocity_score = min(100, recent_reviews * 5)

                # Weighted average
                score = (rating_score * 0.5) + (volume_score * 0.3) + (velocity_score * 0.2)
                return score

        except Exception as e:
            logger.debug(f"Error calculating review strength: {e}")
            return 0.0

    def _calc_market_presence(self, competitor_id: int, domain: str) -> float:
        """
        Calculate market presence score (0-100).

        Based on:
        - Citation count
        - Directory presence
        - Domain authority (if available)
        """
        try:
            with self.db_manager.get_session() as session:
                # Count citations
                result = session.execute(text("""
                    SELECT COUNT(*)
                    FROM discovery_citations
                    WHERE company_id IN (
                        SELECT company_id FROM company_competitors
                        WHERE competitor_id = :competitor_id
                    )
                """), {'competitor_id': competitor_id})

                citation_count = result.scalar() or 0

                # Check for major directory presence
                result = session.execute(text("""
                    SELECT COUNT(DISTINCT source_name)
                    FROM discovery_citations
                    WHERE company_id IN (
                        SELECT company_id FROM company_competitors
                        WHERE competitor_id = :competitor_id
                    )
                    AND source_name IN ('Google Business', 'Yelp', 'Facebook', 'BBB', 'Angi')
                """), {'competitor_id': competitor_id})

                major_directories = result.scalar() or 0

                # Citation score (logarithmic, max at ~50 citations)
                import math
                citation_score = min(100, math.log10(max(1, citation_count)) * 50)

                # Directory score (5 major = 100)
                directory_score = (major_directories / 5) * 100

                score = (citation_score * 0.6) + (directory_score * 0.4)
                return score

        except Exception as e:
            logger.debug(f"Error calculating market presence: {e}")
            return 0.0

    def _calc_growth_velocity(self, competitor_id: int, domain: str) -> float:
        """
        Calculate growth velocity score (0-100).

        Based on:
        - Ranking improvements over 30 days
        - Review growth rate
        - New content/pages
        """
        try:
            with self.db_manager.get_session() as session:
                # Check ranking improvements
                result = session.execute(text("""
                    SELECT
                        COUNT(*) FILTER (WHERE change < 0) as improved,
                        COUNT(*) FILTER (WHERE change > 0) as declined,
                        COUNT(*) as total
                    FROM (
                        SELECT
                            keyword,
                            position - LAG(position) OVER (
                                PARTITION BY keyword
                                ORDER BY captured_at
                            ) as change
                        FROM keyword_rankings
                        WHERE domain = :domain
                          AND captured_at > NOW() - INTERVAL '30 days'
                    ) changes
                    WHERE change IS NOT NULL
                """), {'domain': domain})

                row = result.fetchone()
                improved = int(row[0]) if row and row[0] else 0
                declined = int(row[1]) if row and row[1] else 0
                total = int(row[2]) if row and row[2] else 1

                # Net improvement ratio
                if total > 0:
                    improvement_ratio = (improved - declined) / total
                    ranking_velocity = 50 + (improvement_ratio * 50)  # -1 to 1 -> 0 to 100
                else:
                    ranking_velocity = 50

                # Review velocity
                result = session.execute(text("""
                    SELECT SUM(review_count_30d)
                    FROM competitor_reviews_aggregate
                    WHERE competitor_id = :competitor_id
                      AND captured_at > NOW() - INTERVAL '7 days'
                """), {'competitor_id': competitor_id})

                recent_reviews = result.scalar() or 0
                review_velocity = min(100, recent_reviews * 10)  # 10+ reviews/month = max

                score = (ranking_velocity * 0.6) + (review_velocity * 0.4)
                return max(0, min(100, score))

        except Exception as e:
            logger.debug(f"Error calculating growth velocity: {e}")
            return 0.0

    def _score_to_level(self, weighted_score: float) -> int:
        """Convert weighted score to threat level (1-5)."""
        for threshold, level in self.THREAT_THRESHOLDS:
            if weighted_score >= threshold:
                return level
        return 1

    def _save_threat_score(self, competitor_id: int, factors: ThreatFactors):
        """Save the threat score to the database."""
        try:
            with self.db_manager.get_session() as session:
                # Update the company_competitors relationship
                session.execute(text("""
                    UPDATE company_competitors
                    SET threat_level = :threat_level,
                        updated_at = NOW()
                    WHERE company_id = :company_id
                      AND competitor_id = :competitor_id
                """), {
                    'company_id': self.company_id,
                    'competitor_id': competitor_id,
                    'threat_level': factors.threat_level,
                })

                session.commit()
                logger.debug(f"Saved threat level {factors.threat_level} for competitor {competitor_id}")

        except Exception as e:
            logger.error(f"Failed to save threat score: {e}")

    def get_threat_summary(self, competitor_id: int) -> Dict[str, Any]:
        """Get a summary of threat factors for a competitor."""
        factors = self.calculate_threat(competitor_id, '')

        return {
            'threat_level': factors.threat_level,
            'threat_label': self._level_to_label(factors.threat_level),
            'weighted_score': round(factors.weighted_score, 1),
            'factors': {
                'ranking_overlap': round(factors.ranking_overlap, 1),
                'service_overlap': round(factors.service_overlap, 1),
                'geographic_overlap': round(factors.geographic_overlap, 1),
                'review_strength': round(factors.review_strength, 1),
                'market_presence': round(factors.market_presence, 1),
                'growth_velocity': round(factors.growth_velocity, 1),
            },
            'recommendations': self._get_recommendations(factors),
        }

    def _level_to_label(self, level: int) -> str:
        """Convert threat level to human-readable label."""
        labels = {
            1: 'Low',
            2: 'Minor',
            3: 'Moderate',
            4: 'High',
            5: 'Critical',
        }
        return labels.get(level, 'Unknown')

    def _get_recommendations(self, factors: ThreatFactors) -> List[str]:
        """Generate recommendations based on threat factors."""
        recommendations = []

        if factors.ranking_overlap >= 70:
            recommendations.append("Focus on keyword differentiation and content optimization")

        if factors.service_overlap >= 70:
            recommendations.append("Highlight unique service offerings and specializations")

        if factors.review_strength >= 70:
            recommendations.append("Prioritize review generation campaign")

        if factors.growth_velocity >= 70:
            recommendations.append("Monitor competitor closely - rapid growth detected")

        if factors.market_presence >= 70:
            recommendations.append("Expand citation presence across directories")

        if not recommendations:
            recommendations.append("Continue monitoring - no immediate action required")

        return recommendations


def calculate_threat_for_competitor(
    company_id: int,
    competitor_id: int,
    domain: str
) -> Dict[str, Any]:
    """
    Main entry point for threat scoring.

    Args:
        company_id: The company to compare against
        competitor_id: Competitor to analyze
        domain: Competitor's domain

    Returns:
        Dict with threat level and factors
    """
    scorer = ThreatScorer(company_id)
    factors = scorer.calculate_threat(competitor_id, domain)

    return {
        'success': True,
        'competitor_id': competitor_id,
        'threat_level': factors.threat_level,
        'weighted_score': round(factors.weighted_score, 1),
    }
