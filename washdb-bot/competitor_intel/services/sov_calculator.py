"""
Share of Voice (SOV) Calculator

Calculates the share of voice (visibility) for our company vs competitors
in a given market segment. SOV measures what percentage of total search
visibility belongs to each competitor.

Metrics:
- Overall SOV percentage
- Keyword-level visibility
- Position distribution (top 3, top 10, page 1)
- Visibility score (weighted by keyword volume/importance)
- Trend analysis (7d, 30d changes)
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from collections import defaultdict

from sqlalchemy import text

from db.database_manager import get_db_manager

logger = logging.getLogger(__name__)


@dataclass
class SOVMetrics:
    """Share of Voice metrics for a single entity."""
    domain: str
    entity_id: Optional[int] = None  # company_id or competitor_id
    entity_type: str = 'company'  # 'company' or 'competitor'

    # Visibility metrics
    sov_percentage: float = 0.0
    visibility_score: float = 0.0
    rank: int = 0

    # Keyword counts
    keywords_tracked: int = 0
    keywords_top_3: int = 0
    keywords_top_10: int = 0
    keywords_page_1: int = 0  # Top 20

    # Position averages
    avg_position: Optional[float] = None
    median_position: Optional[float] = None

    # Trends
    sov_change_7d: Optional[float] = None
    sov_change_30d: Optional[float] = None


@dataclass
class MarketSOV:
    """Complete SOV analysis for a market segment."""
    market_segment: str
    captured_date: date
    our_metrics: Optional[SOVMetrics] = None
    competitor_metrics: List[SOVMetrics] = field(default_factory=list)
    total_visibility: float = 0.0
    total_keywords: int = 0


class SOVCalculator:
    """
    Calculates Share of Voice metrics for a company vs its competitors.

    SOV is calculated as:
        SOV = (Our Visibility Points / Total Market Visibility Points) * 100

    Visibility points are weighted by position:
        Position 1: 30 points
        Position 2: 20 points
        Position 3: 15 points
        Position 4-10: 10 - (position - 4) points
        Position 11-20: 3 points
        Position 21+: 1 point
    """

    # Position weights for visibility calculation
    POSITION_WEIGHTS = {
        1: 30,
        2: 20,
        3: 15,
        4: 10,
        5: 9,
        6: 8,
        7: 7,
        8: 6,
        9: 5,
        10: 4,
    }
    DEFAULT_WEIGHT = 3  # Positions 11-20
    MINIMAL_WEIGHT = 1  # Positions 21+

    def __init__(self, company_id: int):
        self.company_id = company_id
        self.db_manager = get_db_manager()
        self._company_domain = None
        self._market_keywords = None

    def calculate_sov(self, market_segment: str) -> MarketSOV:
        """
        Calculate SOV for a market segment.

        Args:
            market_segment: Market identifier (e.g., "pressure_washing_peoria_il")

        Returns:
            MarketSOV with all metrics
        """
        result = MarketSOV(
            market_segment=market_segment,
            captured_date=date.today(),
        )

        try:
            # Get our company domain
            self._load_company_domain()

            # Get all keywords for this market segment
            keywords = self._get_market_keywords(market_segment)
            result.total_keywords = len(keywords)

            if not keywords:
                logger.warning(f"No keywords found for market segment: {market_segment}")
                return result

            self._market_keywords = keywords

            # Get all domains competing in this market
            all_domains = self._get_competing_domains(keywords)

            # Calculate visibility for each domain
            visibility_data = {}
            total_visibility = 0

            for domain in all_domains:
                visibility = self._calculate_domain_visibility(domain, keywords)
                visibility_data[domain] = visibility
                total_visibility += visibility['points']

            result.total_visibility = total_visibility

            # Calculate SOV for our company
            if self._company_domain and self._company_domain in visibility_data:
                our_data = visibility_data[self._company_domain]
                result.our_metrics = self._create_sov_metrics(
                    domain=self._company_domain,
                    visibility_data=our_data,
                    total_visibility=total_visibility,
                    entity_id=self.company_id,
                    entity_type='company',
                )

            # Calculate SOV for competitors
            competitors = self._get_linked_competitors()

            for comp_id, comp_domain in competitors:
                if comp_domain in visibility_data:
                    comp_data = visibility_data[comp_domain]
                    metrics = self._create_sov_metrics(
                        domain=comp_domain,
                        visibility_data=comp_data,
                        total_visibility=total_visibility,
                        entity_id=comp_id,
                        entity_type='competitor',
                    )
                    result.competitor_metrics.append(metrics)

            # Sort competitors by SOV
            result.competitor_metrics.sort(key=lambda x: x.sov_percentage, reverse=True)

            # Assign ranks
            all_metrics = []
            if result.our_metrics:
                all_metrics.append(result.our_metrics)
            all_metrics.extend(result.competitor_metrics)
            all_metrics.sort(key=lambda x: x.sov_percentage, reverse=True)

            for i, m in enumerate(all_metrics, 1):
                m.rank = i

            # Load trends
            self._load_trends(result)

            # Save to database
            self._save_sov(result)

        except Exception as e:
            logger.error(f"Failed to calculate SOV for {market_segment}: {e}")

        return result

    def _load_company_domain(self):
        """Load our company's domain."""
        if self._company_domain is not None:
            return

        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT domain FROM companies WHERE id = :company_id
                """), {'company_id': self.company_id})

                row = result.fetchone()
                self._company_domain = row[0] if row else None

        except Exception as e:
            logger.error(f"Failed to load company domain: {e}")

    def _get_market_keywords(self, market_segment: str) -> List[str]:
        """Get all keywords for a market segment."""
        try:
            with self.db_manager.get_session() as session:
                # Try to get keywords from a keyword groups table first
                result = session.execute(text("""
                    SELECT keyword
                    FROM keyword_groups
                    WHERE group_name = :segment
                      OR market_segment = :segment
                """), {'segment': market_segment})

                keywords = [row[0] for row in result.fetchall()]

                if keywords:
                    return keywords

                # Fallback: derive from market segment name
                # e.g., "pressure_washing_peoria_il" -> keywords containing these terms
                parts = market_segment.lower().split('_')
                service_term = parts[0] if parts else ''
                location_terms = parts[1:] if len(parts) > 1 else []

                if service_term:
                    # Get all keywords containing the service term
                    result = session.execute(text("""
                        SELECT DISTINCT keyword
                        FROM keyword_rankings
                        WHERE LOWER(keyword) LIKE :pattern
                        LIMIT 200
                    """), {'pattern': f'%{service_term}%'})

                    keywords = [row[0] for row in result.fetchall()]

                return keywords

        except Exception as e:
            logger.error(f"Failed to get market keywords: {e}")
            return []

    def _get_competing_domains(self, keywords: List[str]) -> List[str]:
        """Get all domains that rank for these keywords."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT DISTINCT domain
                    FROM keyword_rankings
                    WHERE keyword = ANY(:keywords)
                      AND position <= 50
                      AND captured_at > NOW() - INTERVAL '7 days'
                """), {'keywords': keywords})

                return [row[0] for row in result.fetchall()]

        except Exception as e:
            logger.error(f"Failed to get competing domains: {e}")
            return []

    def _get_linked_competitors(self) -> List[Tuple[int, str]]:
        """Get competitors linked to our company."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT c.competitor_id, c.domain
                    FROM competitors c
                    JOIN company_competitors cc ON c.competitor_id = cc.competitor_id
                    WHERE cc.company_id = :company_id
                      AND c.is_active = true
                """), {'company_id': self.company_id})

                return [(row[0], row[1]) for row in result.fetchall()]

        except Exception as e:
            logger.error(f"Failed to get linked competitors: {e}")
            return []

    def _calculate_domain_visibility(self, domain: str, keywords: List[str]) -> Dict[str, Any]:
        """Calculate visibility metrics for a domain."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT keyword, position
                    FROM keyword_rankings
                    WHERE domain = :domain
                      AND keyword = ANY(:keywords)
                      AND captured_at > NOW() - INTERVAL '7 days'
                    ORDER BY captured_at DESC
                """), {'domain': domain, 'keywords': keywords})

                # Get latest position for each keyword
                keyword_positions = {}
                for row in result.fetchall():
                    if row[0] not in keyword_positions:
                        keyword_positions[row[0]] = row[1]

                # Calculate metrics
                total_points = 0
                positions = []
                top_3 = 0
                top_10 = 0
                page_1 = 0

                for keyword, position in keyword_positions.items():
                    if position:
                        positions.append(position)

                        # Get weight for this position
                        if position in self.POSITION_WEIGHTS:
                            weight = self.POSITION_WEIGHTS[position]
                        elif position <= 20:
                            weight = self.DEFAULT_WEIGHT
                        else:
                            weight = self.MINIMAL_WEIGHT

                        total_points += weight

                        # Count position buckets
                        if position <= 3:
                            top_3 += 1
                        if position <= 10:
                            top_10 += 1
                        if position <= 20:
                            page_1 += 1

                avg_position = sum(positions) / len(positions) if positions else None
                median_position = self._median(positions) if positions else None

                return {
                    'points': total_points,
                    'keywords_ranked': len(keyword_positions),
                    'top_3': top_3,
                    'top_10': top_10,
                    'page_1': page_1,
                    'avg_position': avg_position,
                    'median_position': median_position,
                }

        except Exception as e:
            logger.error(f"Failed to calculate visibility for {domain}: {e}")
            return {
                'points': 0,
                'keywords_ranked': 0,
                'top_3': 0,
                'top_10': 0,
                'page_1': 0,
                'avg_position': None,
                'median_position': None,
            }

    def _median(self, values: List[float]) -> float:
        """Calculate median of a list."""
        if not values:
            return 0
        sorted_values = sorted(values)
        n = len(sorted_values)
        if n % 2 == 0:
            return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2
        return sorted_values[n // 2]

    def _create_sov_metrics(
        self,
        domain: str,
        visibility_data: Dict,
        total_visibility: float,
        entity_id: Optional[int],
        entity_type: str,
    ) -> SOVMetrics:
        """Create SOV metrics from visibility data."""
        sov_pct = 0.0
        if total_visibility > 0:
            sov_pct = (visibility_data['points'] / total_visibility) * 100

        # Visibility score (normalized 0-100)
        # Max points = top 3 for all keywords = 30 * total_keywords
        max_possible = 30 * len(self._market_keywords or [])
        visibility_score = 0.0
        if max_possible > 0:
            visibility_score = (visibility_data['points'] / max_possible) * 100

        return SOVMetrics(
            domain=domain,
            entity_id=entity_id,
            entity_type=entity_type,
            sov_percentage=round(sov_pct, 2),
            visibility_score=round(visibility_score, 2),
            keywords_tracked=visibility_data['keywords_ranked'],
            keywords_top_3=visibility_data['top_3'],
            keywords_top_10=visibility_data['top_10'],
            keywords_page_1=visibility_data['page_1'],
            avg_position=round(visibility_data['avg_position'], 1) if visibility_data['avg_position'] else None,
            median_position=round(visibility_data['median_position'], 1) if visibility_data['median_position'] else None,
        )

    def _load_trends(self, result: MarketSOV):
        """Load historical trends for SOV metrics."""
        try:
            with self.db_manager.get_session() as session:
                # Get historical data
                hist_result = session.execute(text("""
                    SELECT captured_date, our_sov, visibility_score
                    FROM competitor_sov
                    WHERE market_segment = :segment
                      AND company_id = :company_id
                      AND captured_date >= CURRENT_DATE - INTERVAL '30 days'
                    ORDER BY captured_date DESC
                """), {
                    'segment': result.market_segment,
                    'company_id': self.company_id,
                })

                history = hist_result.fetchall()

                if history and result.our_metrics:
                    today = date.today()

                    # Find 7-day-ago value
                    for row in history:
                        days_ago = (today - row[0]).days
                        if days_ago >= 7 and result.our_metrics.sov_change_7d is None:
                            result.our_metrics.sov_change_7d = round(
                                result.our_metrics.sov_percentage - (row[1] or 0), 2
                            )
                        if days_ago >= 30 and result.our_metrics.sov_change_30d is None:
                            result.our_metrics.sov_change_30d = round(
                                result.our_metrics.sov_percentage - (row[1] or 0), 2
                            )
                            break

        except Exception as e:
            logger.debug(f"Failed to load SOV trends: {e}")

    def _save_sov(self, result: MarketSOV):
        """Save SOV data to database."""
        try:
            with self.db_manager.get_session() as session:
                import json

                # Build competitor data JSON
                competitor_data = {}
                for cm in result.competitor_metrics:
                    if cm.entity_id:
                        competitor_data[str(cm.entity_id)] = {
                            'sov': cm.sov_percentage,
                            'rank': cm.rank,
                            'keywords_top_10': cm.keywords_top_10,
                        }

                our_sov = result.our_metrics.sov_percentage if result.our_metrics else None
                our_rank = result.our_metrics.rank if result.our_metrics else None
                visibility = result.our_metrics.visibility_score if result.our_metrics else None
                keywords_top_3 = result.our_metrics.keywords_top_3 if result.our_metrics else 0
                keywords_top_10 = result.our_metrics.keywords_top_10 if result.our_metrics else 0
                keywords_page_1 = result.our_metrics.keywords_page_1 if result.our_metrics else 0
                trend_7d = result.our_metrics.sov_change_7d if result.our_metrics else None
                trend_30d = result.our_metrics.sov_change_30d if result.our_metrics else None

                session.execute(text("""
                    INSERT INTO competitor_sov
                        (market_segment, captured_date, company_id, competitor_data,
                         our_sov, our_rank, keywords_tracked, keywords_top_3,
                         keywords_top_10, keywords_page_1, visibility_score,
                         trend_7d, trend_30d)
                    VALUES
                        (:segment, :date, :company_id, :competitor_data,
                         :our_sov, :our_rank, :keywords_tracked, :keywords_top_3,
                         :keywords_top_10, :keywords_page_1, :visibility,
                         :trend_7d, :trend_30d)
                    ON CONFLICT (market_segment, captured_date, company_id)
                    DO UPDATE SET
                        competitor_data = EXCLUDED.competitor_data,
                        our_sov = EXCLUDED.our_sov,
                        our_rank = EXCLUDED.our_rank,
                        visibility_score = EXCLUDED.visibility_score
                """), {
                    'segment': result.market_segment,
                    'date': result.captured_date,
                    'company_id': self.company_id,
                    'competitor_data': json.dumps(competitor_data),
                    'our_sov': our_sov,
                    'our_rank': our_rank,
                    'keywords_tracked': result.total_keywords,
                    'keywords_top_3': keywords_top_3,
                    'keywords_top_10': keywords_top_10,
                    'keywords_page_1': keywords_page_1,
                    'visibility': visibility,
                    'trend_7d': trend_7d,
                    'trend_30d': trend_30d,
                })

                session.commit()
                logger.info(f"Saved SOV data for {result.market_segment}")

        except Exception as e:
            logger.error(f"Failed to save SOV data: {e}")

    def get_sov_summary(self, market_segment: str) -> Dict[str, Any]:
        """Get a summary of SOV for a market segment."""
        result = self.calculate_sov(market_segment)

        summary = {
            'market_segment': market_segment,
            'captured_date': result.captured_date.isoformat(),
            'total_keywords': result.total_keywords,
            'our_position': None,
            'competitors': [],
        }

        if result.our_metrics:
            summary['our_position'] = {
                'rank': result.our_metrics.rank,
                'sov_percentage': result.our_metrics.sov_percentage,
                'visibility_score': result.our_metrics.visibility_score,
                'keywords_top_3': result.our_metrics.keywords_top_3,
                'keywords_top_10': result.our_metrics.keywords_top_10,
                'trend_7d': result.our_metrics.sov_change_7d,
                'trend_30d': result.our_metrics.sov_change_30d,
            }

        for cm in result.competitor_metrics[:10]:  # Top 10
            summary['competitors'].append({
                'domain': cm.domain,
                'rank': cm.rank,
                'sov_percentage': cm.sov_percentage,
                'keywords_top_10': cm.keywords_top_10,
            })

        return summary


def calculate_market_sov(company_id: int, market_segment: str) -> Dict[str, Any]:
    """
    Main entry point for SOV calculation.

    Args:
        company_id: The company to analyze
        market_segment: Market segment identifier

    Returns:
        Dict with SOV summary
    """
    calculator = SOVCalculator(company_id)
    return calculator.get_sov_summary(market_segment)
