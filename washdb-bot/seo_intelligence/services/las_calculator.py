"""
Local Authority Score (LAS) Calculator

Calculates a composite score measuring local SEO authority based on:
- Citation presence and NAP consistency
- Backlink profile strength
- Review signals
- Directory coverage

Score ranges from 0-100, with weighted components:
- Citations: 40% (presence + NAP accuracy)
- Backlinks: 30% (quantity + quality)
- Reviews: 20% (rating + volume)
- Completeness: 10% (profile completeness)
"""

import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("las_calculator")


@dataclass
class LASComponents:
    """Individual components of the Local Authority Score."""
    citation_score: float = 0.0      # 0-100: Citation presence and accuracy
    backlink_score: float = 0.0      # 0-100: Backlink strength
    review_score: float = 0.0        # 0-100: Review signals
    completeness_score: float = 0.0  # 0-100: Profile completeness

    @property
    def total_score(self) -> float:
        """Calculate weighted total LAS."""
        weights = {
            'citation': 0.40,
            'backlink': 0.30,
            'review': 0.20,
            'completeness': 0.10,
        }
        return (
            self.citation_score * weights['citation'] +
            self.backlink_score * weights['backlink'] +
            self.review_score * weights['review'] +
            self.completeness_score * weights['completeness']
        )

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['total_score'] = self.total_score
        return result


@dataclass
class LASResult:
    """Complete LAS calculation result."""
    business_name: str
    domain: Optional[str]
    las_score: float
    components: LASComponents
    grade: str  # A, B, C, D, F
    recommendations: List[str]
    calculated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "business_name": self.business_name,
            "domain": self.domain,
            "las_score": self.las_score,
            "grade": self.grade,
            "components": self.components.to_dict(),
            "recommendations": self.recommendations,
            "calculated_at": self.calculated_at.isoformat(),
        }


# Key directories for citation scoring
KEY_DIRECTORIES = [
    'google_business',  # Critical - worth 25 points
    'yelp',             # Important - worth 15 points
    'yellowpages',      # Important - worth 10 points
    'bbb',              # Important - worth 10 points
    'facebook',         # Moderate - worth 10 points
]

# Additional directories
SECONDARY_DIRECTORIES = [
    'angies_list', 'thumbtack', 'homeadvisor', 'mapquest', 'manta',
]


class LASCalculator:
    """
    Calculator for Local Authority Score (LAS).

    Aggregates citation, backlink, and review data to produce
    a composite score measuring local SEO authority.
    """

    def __init__(self):
        """Initialize LAS calculator."""
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database queries disabled")

        logger.info("LASCalculator initialized")

    def _score_to_grade(self, score: float) -> str:
        """Convert numeric score to letter grade."""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"

    def _calculate_citation_score(
        self,
        session: Session,
        business_name: str,
    ) -> tuple[float, List[str]]:
        """
        Calculate citation component score.

        Args:
            session: Database session
            business_name: Business name to look up

        Returns:
            Tuple of (score, recommendations)
        """
        recommendations = []

        # Get citations for this business
        result = session.execute(
            text("""
                SELECT directory_name, is_present, nap_match_score,
                       name_match, address_match, phone_match
                FROM citations
                WHERE business_name = :name
            """),
            {"name": business_name}
        )
        citations = {row[0]: row for row in result.fetchall()}

        score = 0.0
        max_score = 100.0

        # Score key directories (worth 70 points total)
        key_weights = {
            'google_business': 25,
            'yelp': 15,
            'yellowpages': 10,
            'bbb': 10,
            'facebook': 10,
        }

        for directory, weight in key_weights.items():
            if directory in citations:
                citation = citations[directory]
                is_present = citation[1]
                nap_score = citation[2] or 0

                if is_present:
                    # Base points for presence
                    score += weight * 0.6
                    # Additional points for NAP accuracy
                    score += weight * 0.4 * nap_score
                else:
                    recommendations.append(f"Get listed on {directory.replace('_', ' ').title()}")
            else:
                recommendations.append(f"Check {directory.replace('_', ' ').title()} listing")

        # Score secondary directories (worth 30 points total)
        secondary_found = 0
        secondary_accurate = 0

        for directory in SECONDARY_DIRECTORIES:
            if directory in citations:
                citation = citations[directory]
                if citation[1]:  # is_present
                    secondary_found += 1
                    if citation[2] and citation[2] >= 0.7:  # nap_score
                        secondary_accurate += 1

        # 3 points per secondary directory (up to 30)
        score += min(secondary_found * 3, 30)

        if secondary_found < 3:
            recommendations.append("Expand citations to more secondary directories")

        # Check for NAP consistency issues
        inconsistent = []
        for directory, citation in citations.items():
            if citation[1] and citation[2] and citation[2] < 0.7:
                inconsistent.append(directory.replace('_', ' ').title())

        if inconsistent:
            recommendations.append(f"Fix NAP inconsistencies on: {', '.join(inconsistent[:3])}")

        return min(score, max_score), recommendations

    def _calculate_backlink_score(
        self,
        session: Session,
        domain: str,
    ) -> tuple[float, List[str]]:
        """
        Calculate backlink component score.

        Args:
            session: Database session
            domain: Business domain

        Returns:
            Tuple of (score, recommendations)
        """
        recommendations = []
        score = 0.0

        if not domain:
            recommendations.append("Add website domain to track backlinks")
            return 0.0, recommendations

        # Get backlink stats
        result = session.execute(
            text("""
                SELECT
                    COUNT(DISTINCT b.backlink_id) as total_backlinks,
                    COUNT(DISTINCT b.domain_id) as referring_domains,
                    SUM(CASE WHEN b.link_type = 'dofollow' THEN 1 ELSE 0 END) as dofollow_count,
                    AVG(rd.domain_authority) as avg_da
                FROM backlinks b
                JOIN referring_domains rd ON b.domain_id = rd.domain_id
                WHERE b.target_url LIKE :domain_pattern
                AND b.is_active = TRUE
            """),
            {"domain_pattern": f"%{domain}%"}
        )
        row = result.fetchone()

        if row:
            total_backlinks = row[0] or 0
            referring_domains = row[1] or 0
            dofollow_count = row[2] or 0
            avg_da = row[3] or 0

            # Score based on referring domains (up to 40 points)
            # 1-5: 10 pts, 6-10: 20 pts, 11-20: 30 pts, 21+: 40 pts
            if referring_domains >= 21:
                score += 40
            elif referring_domains >= 11:
                score += 30
            elif referring_domains >= 6:
                score += 20
            elif referring_domains >= 1:
                score += 10
            else:
                recommendations.append("Build backlinks from local websites")

            # Score based on dofollow ratio (up to 30 points)
            if total_backlinks > 0:
                dofollow_ratio = dofollow_count / total_backlinks
                score += dofollow_ratio * 30
            else:
                recommendations.append("Focus on acquiring dofollow backlinks")

            # Score based on average domain authority (up to 30 points)
            # DA 0-20: 10 pts, 21-40: 20 pts, 41+: 30 pts
            if avg_da >= 41:
                score += 30
            elif avg_da >= 21:
                score += 20
            elif avg_da >= 1:
                score += 10
            else:
                recommendations.append("Target higher authority websites for backlinks")

        else:
            recommendations.append("Start backlink outreach campaign")

        return min(score, 100.0), recommendations

    def _calculate_review_score(
        self,
        session: Session,
        business_name: str,
    ) -> tuple[float, List[str]]:
        """
        Calculate review component score.

        Args:
            session: Database session
            business_name: Business name

        Returns:
            Tuple of (score, recommendations)
        """
        recommendations = []
        score = 0.0

        # Get review data from citations metadata
        result = session.execute(
            text("""
                SELECT directory_name, metadata
                FROM citations
                WHERE business_name = :name
                AND is_present = TRUE
            """),
            {"name": business_name}
        )

        total_reviews = 0
        ratings = []

        for row in result.fetchall():
            metadata = row[1] or {}
            if isinstance(metadata, str):
                import json
                metadata = json.loads(metadata)

            if metadata.get('has_reviews'):
                total_reviews += metadata.get('review_count', 0)

            if metadata.get('rating'):
                ratings.append(metadata['rating'])

        # Score based on review volume (up to 50 points)
        # 1-10: 15 pts, 11-25: 25 pts, 26-50: 35 pts, 51+: 50 pts
        if total_reviews >= 51:
            score += 50
        elif total_reviews >= 26:
            score += 35
        elif total_reviews >= 11:
            score += 25
        elif total_reviews >= 1:
            score += 15
        else:
            recommendations.append("Encourage customers to leave reviews")

        # Score based on average rating (up to 50 points)
        if ratings:
            avg_rating = sum(ratings) / len(ratings)
            # 4.5+: 50 pts, 4.0-4.4: 40 pts, 3.5-3.9: 30 pts, 3.0-3.4: 20 pts
            if avg_rating >= 4.5:
                score += 50
            elif avg_rating >= 4.0:
                score += 40
            elif avg_rating >= 3.5:
                score += 30
            elif avg_rating >= 3.0:
                score += 20
            else:
                score += 10
                recommendations.append("Focus on improving customer satisfaction")
        else:
            recommendations.append("No ratings found - request reviews from satisfied customers")

        return min(score, 100.0), recommendations

    def _calculate_completeness_score(
        self,
        session: Session,
        business_name: str,
        domain: Optional[str],
    ) -> tuple[float, List[str]]:
        """
        Calculate profile completeness score.

        Args:
            session: Database session
            business_name: Business name
            domain: Business domain

        Returns:
            Tuple of (score, recommendations)
        """
        recommendations = []
        score = 0.0

        # Check for Google Business specifically
        result = session.execute(
            text("""
                SELECT is_present, nap_match_score, metadata
                FROM citations
                WHERE business_name = :name
                AND directory_name = 'google_business'
            """),
            {"name": business_name}
        )
        row = result.fetchone()

        if row:
            is_present = row[0]
            nap_score = row[1] or 0
            metadata = row[2] or {}

            if is_present:
                score += 30  # Listed on Google
                if nap_score >= 0.8:
                    score += 20  # NAP accurate
                else:
                    recommendations.append("Update Google Business Profile with accurate NAP")
            else:
                recommendations.append("Claim and verify Google Business Profile")
        else:
            score += 0
            recommendations.append("Set up Google Business Profile")

        # Check website presence
        if domain:
            score += 30  # Has website
            # Could add more checks here (SSL, mobile-friendly, etc.)
        else:
            recommendations.append("Create a business website")

        # Check citation coverage
        result = session.execute(
            text("""
                SELECT COUNT(*) FROM citations
                WHERE business_name = :name AND is_present = TRUE
            """),
            {"name": business_name}
        )
        citation_count = result.fetchone()[0]

        if citation_count >= 5:
            score += 20
        elif citation_count >= 3:
            score += 10
        else:
            recommendations.append("Expand presence across more directories")

        return min(score, 100.0), recommendations

    def calculate(
        self,
        business_name: str,
        domain: Optional[str] = None,
    ) -> LASResult:
        """
        Calculate Local Authority Score for a business.

        Args:
            business_name: Business name
            domain: Business website domain (optional)

        Returns:
            LASResult with score breakdown and recommendations
        """
        components = LASComponents()
        all_recommendations = []

        if self.engine:
            with Session(self.engine) as session:
                # Calculate each component
                citation_score, citation_recs = self._calculate_citation_score(
                    session, business_name
                )
                components.citation_score = citation_score
                all_recommendations.extend(citation_recs)

                backlink_score, backlink_recs = self._calculate_backlink_score(
                    session, domain or ""
                )
                components.backlink_score = backlink_score
                all_recommendations.extend(backlink_recs)

                review_score, review_recs = self._calculate_review_score(
                    session, business_name
                )
                components.review_score = review_score
                all_recommendations.extend(review_recs)

                completeness_score, completeness_recs = self._calculate_completeness_score(
                    session, business_name, domain
                )
                components.completeness_score = completeness_score
                all_recommendations.extend(completeness_recs)
        else:
            all_recommendations.append("Database not configured - cannot calculate LAS")

        total_score = components.total_score
        grade = self._score_to_grade(total_score)

        # Prioritize recommendations (top 5)
        recommendations = all_recommendations[:5]

        result = LASResult(
            business_name=business_name,
            domain=domain,
            las_score=total_score,
            components=components,
            grade=grade,
            recommendations=recommendations,
            calculated_at=datetime.now(),
        )

        logger.info(
            f"LAS calculated for '{business_name}': {total_score:.1f} ({grade}) - "
            f"Citations: {components.citation_score:.1f}, "
            f"Backlinks: {components.backlink_score:.1f}, "
            f"Reviews: {components.review_score:.1f}"
        )

        return result

    def calculate_bulk(
        self,
        businesses: List[Dict[str, str]],
    ) -> List[LASResult]:
        """
        Calculate LAS for multiple businesses.

        Args:
            businesses: List of dicts with 'name' and optional 'domain'

        Returns:
            List of LASResult objects
        """
        results = []

        for business in businesses:
            name = business.get('name', '')
            domain = business.get('domain')

            if name:
                result = self.calculate(name, domain)
                results.append(result)

        return results


# Module-level singleton
_las_calculator_instance = None


def get_las_calculator() -> LASCalculator:
    """Get or create the singleton LASCalculator instance."""
    global _las_calculator_instance

    if _las_calculator_instance is None:
        _las_calculator_instance = LASCalculator()

    return _las_calculator_instance


def main():
    """Demo/CLI interface for LAS calculator."""
    import argparse

    parser = argparse.ArgumentParser(description="Local Authority Score Calculator")
    parser.add_argument("--name", "-n", help="Business name")
    parser.add_argument("--domain", "-d", help="Business domain")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("Local Authority Score (LAS) Calculator Demo")
        logger.info("=" * 60)
        logger.info("")
        logger.info("LAS Components:")
        logger.info("  - Citations (40%): Directory presence & NAP accuracy")
        logger.info("  - Backlinks (30%): Link quantity & quality")
        logger.info("  - Reviews (20%): Rating & volume")
        logger.info("  - Completeness (10%): Profile completeness")
        logger.info("")
        logger.info("Grades: A (90+), B (80-89), C (70-79), D (60-69), F (<60)")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python las_calculator.py --name 'ABC Pressure Washing' --domain 'abcwash.com'")
        logger.info("")
        logger.info("=" * 60)
        return

    if not args.name:
        parser.print_help()
        return

    calculator = get_las_calculator()
    result = calculator.calculate(args.name, args.domain)

    logger.info("")
    logger.info(f"Local Authority Score for '{args.name}'")
    logger.info("=" * 60)
    logger.info(f"Overall Score: {result.las_score:.1f} ({result.grade})")
    logger.info("")
    logger.info("Component Scores:")
    logger.info(f"  Citations:    {result.components.citation_score:.1f}/100")
    logger.info(f"  Backlinks:    {result.components.backlink_score:.1f}/100")
    logger.info(f"  Reviews:      {result.components.review_score:.1f}/100")
    logger.info(f"  Completeness: {result.components.completeness_score:.1f}/100")
    logger.info("")
    logger.info("Top Recommendations:")
    for i, rec in enumerate(result.recommendations, 1):
        logger.info(f"  {i}. {rec}")
    logger.info("")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
