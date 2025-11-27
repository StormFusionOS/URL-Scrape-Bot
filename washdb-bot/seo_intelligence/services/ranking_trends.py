"""
Ranking Trends Service

Tracks and analyzes keyword ranking position changes over time:
- Historical position tracking
- Trend direction analysis (up/down/stable)
- Volatility detection
- Rank improvement/decline alerts
- Competitor movement tracking

No external APIs - uses historical SERP data from database.

Usage:
    from seo_intelligence.services.ranking_trends import get_ranking_trends

    tracker = get_ranking_trends()

    # Record a new ranking
    tracker.record_ranking(keyword="car wash", domain="example.com", position=5)

    # Get trend analysis
    trend = tracker.analyze_trend(keyword="car wash", domain="example.com")

    # Get movement alerts
    alerts = tracker.get_alerts(domain="example.com")
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

from runner.logging_setup import get_logger
from db.database_manager import get_db_manager


class TrendDirection(Enum):
    """Direction of ranking trend."""
    STRONG_UP = "strong_up"      # Significant improvement
    UP = "up"                    # Moderate improvement
    STABLE = "stable"           # No significant change
    DOWN = "down"               # Moderate decline
    STRONG_DOWN = "strong_down"  # Significant decline
    NEW = "new"                 # New ranking
    LOST = "lost"               # No longer ranking


class VolatilityLevel(Enum):
    """Ranking volatility level."""
    STABLE = "stable"           # < 2 position variance
    LOW = "low"                 # 2-5 position variance
    MODERATE = "moderate"       # 5-10 position variance
    HIGH = "high"               # 10-20 position variance
    EXTREME = "extreme"         # > 20 position variance


class AlertType(Enum):
    """Type of ranking alert."""
    ENTERED_TOP_3 = "entered_top_3"
    ENTERED_TOP_10 = "entered_top_10"
    LEFT_TOP_10 = "left_top_10"
    LEFT_TOP_20 = "left_top_20"
    BIG_JUMP = "big_jump"           # +10 positions
    BIG_DROP = "big_drop"           # -10 positions
    NEW_RANKING = "new_ranking"
    LOST_RANKING = "lost_ranking"
    COMPETITOR_OVERTOOK = "competitor_overtook"


@dataclass
class RankingSnapshot:
    """Single ranking data point."""
    keyword: str
    domain: str
    position: int
    url: Optional[str] = None
    recorded_at: datetime = field(default_factory=datetime.now)


@dataclass
class TrendAnalysis:
    """Complete trend analysis for a keyword/domain."""
    keyword: str
    domain: str
    current_position: Optional[int]
    previous_position: Optional[int]
    position_change: int
    trend_direction: TrendDirection
    volatility: VolatilityLevel
    avg_position_7d: float
    avg_position_30d: float
    best_position: int
    worst_position: int
    days_in_top_10: int
    total_data_points: int
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "keyword": self.keyword,
            "domain": self.domain,
            "current_position": self.current_position,
            "previous_position": self.previous_position,
            "position_change": self.position_change,
            "trend_direction": self.trend_direction.value,
            "volatility": self.volatility.value,
            "avg_position_7d": round(self.avg_position_7d, 1),
            "avg_position_30d": round(self.avg_position_30d, 1),
            "best_position": self.best_position,
            "worst_position": self.worst_position,
            "days_in_top_10": self.days_in_top_10,
            "total_data_points": self.total_data_points,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }


@dataclass
class RankingAlert:
    """Ranking alert notification."""
    keyword: str
    domain: str
    alert_type: AlertType
    message: str
    old_position: Optional[int]
    new_position: Optional[int]
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "keyword": self.keyword,
            "domain": self.domain,
            "alert_type": self.alert_type.value,
            "message": self.message,
            "old_position": self.old_position,
            "new_position": self.new_position,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class DomainTrendSummary:
    """Summary of all ranking trends for a domain."""
    domain: str
    total_keywords: int
    keywords_improving: int
    keywords_declining: int
    keywords_stable: int
    keywords_new: int
    keywords_lost: int
    avg_position: float
    avg_position_change: float
    keywords_in_top_3: int
    keywords_in_top_10: int
    keywords_in_top_20: int
    top_movers: List[TrendAnalysis] = field(default_factory=list)
    biggest_drops: List[TrendAnalysis] = field(default_factory=list)
    alerts: List[RankingAlert] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "total_keywords": self.total_keywords,
            "movement": {
                "improving": self.keywords_improving,
                "declining": self.keywords_declining,
                "stable": self.keywords_stable,
                "new": self.keywords_new,
                "lost": self.keywords_lost,
            },
            "positions": {
                "average": round(self.avg_position, 1),
                "avg_change": round(self.avg_position_change, 1),
                "top_3": self.keywords_in_top_3,
                "top_10": self.keywords_in_top_10,
                "top_20": self.keywords_in_top_20,
            },
            "top_movers": [t.to_dict() for t in self.top_movers[:5]],
            "biggest_drops": [t.to_dict() for t in self.biggest_drops[:5]],
            "alerts": [a.to_dict() for a in self.alerts[:10]],
            "analyzed_at": self.analyzed_at.isoformat(),
        }


class RankingTrends:
    """
    Tracks and analyzes keyword ranking trends.

    Provides historical tracking and trend analysis from
    stored SERP position data.
    """

    def __init__(self):
        """Initialize ranking trends tracker."""
        self.logger = get_logger("ranking_trends")
        self.db = get_db_manager()

        # In-memory cache for recent rankings
        self._recent_rankings: Dict[str, List[RankingSnapshot]] = defaultdict(list)

        self.logger.info("RankingTrends initialized")

    def _get_cache_key(self, keyword: str, domain: str) -> str:
        """Generate cache key."""
        return f"{keyword.lower()}|{domain.lower()}"

    def record_ranking(
        self,
        keyword: str,
        domain: str,
        position: int,
        url: Optional[str] = None,
        recorded_at: Optional[datetime] = None,
    ) -> Optional[RankingAlert]:
        """
        Record a new ranking data point.

        Args:
            keyword: Search keyword
            domain: Ranking domain
            position: SERP position (1-100+)
            url: Ranking URL
            recorded_at: Timestamp (defaults to now)

        Returns:
            RankingAlert if significant change detected
        """
        recorded_at = recorded_at or datetime.now()
        cache_key = self._get_cache_key(keyword, domain)

        # Create snapshot
        snapshot = RankingSnapshot(
            keyword=keyword.lower(),
            domain=domain.lower(),
            position=position,
            url=url,
            recorded_at=recorded_at,
        )

        # Get previous position for alert detection
        previous_position = None
        if self._recent_rankings[cache_key]:
            previous_position = self._recent_rankings[cache_key][-1].position

        # Add to cache
        self._recent_rankings[cache_key].append(snapshot)

        # Keep only last 90 days in cache
        cutoff = datetime.now() - timedelta(days=90)
        self._recent_rankings[cache_key] = [
            s for s in self._recent_rankings[cache_key]
            if s.recorded_at > cutoff
        ]

        # Save to database
        self._save_ranking(snapshot)

        # Check for alerts
        return self._check_alerts(
            keyword, domain, position, previous_position
        )

    def _save_ranking(self, snapshot: RankingSnapshot):
        """Save ranking to database."""
        try:
            conn = self.db.engine.connect()

            query = """
                INSERT INTO keyword_ranking_history (
                    keyword, domain, position, url, recorded_at
                ) VALUES (
                    %(keyword)s, %(domain)s, %(position)s,
                    %(url)s, %(recorded_at)s
                )
            """

            conn.execute(query, {
                "keyword": snapshot.keyword,
                "domain": snapshot.domain,
                "position": snapshot.position,
                "url": snapshot.url,
                "recorded_at": snapshot.recorded_at,
            })

            conn.close()

        except Exception as e:
            self.logger.warning(f"Failed to save ranking: {e}")

    def _check_alerts(
        self,
        keyword: str,
        domain: str,
        new_position: int,
        old_position: Optional[int],
    ) -> Optional[RankingAlert]:
        """
        Check for alert-worthy position changes.

        Args:
            keyword: Search keyword
            domain: Domain
            new_position: New position
            old_position: Previous position

        Returns:
            RankingAlert if significant change
        """
        # New ranking
        if old_position is None:
            return RankingAlert(
                keyword=keyword,
                domain=domain,
                alert_type=AlertType.NEW_RANKING,
                message=f"New ranking at position {new_position}",
                old_position=None,
                new_position=new_position,
            )

        # Lost ranking
        if new_position > 100 and old_position <= 100:
            return RankingAlert(
                keyword=keyword,
                domain=domain,
                alert_type=AlertType.LOST_RANKING,
                message=f"Lost ranking (was position {old_position})",
                old_position=old_position,
                new_position=None,
            )

        # Position change
        change = old_position - new_position  # Positive = improvement

        # Entered top 3
        if new_position <= 3 and old_position > 3:
            return RankingAlert(
                keyword=keyword,
                domain=domain,
                alert_type=AlertType.ENTERED_TOP_3,
                message=f"Entered top 3 (moved from #{old_position} to #{new_position})",
                old_position=old_position,
                new_position=new_position,
            )

        # Entered top 10
        if new_position <= 10 and old_position > 10:
            return RankingAlert(
                keyword=keyword,
                domain=domain,
                alert_type=AlertType.ENTERED_TOP_10,
                message=f"Entered top 10 (moved from #{old_position} to #{new_position})",
                old_position=old_position,
                new_position=new_position,
            )

        # Left top 10
        if new_position > 10 and old_position <= 10:
            return RankingAlert(
                keyword=keyword,
                domain=domain,
                alert_type=AlertType.LEFT_TOP_10,
                message=f"Dropped out of top 10 (moved from #{old_position} to #{new_position})",
                old_position=old_position,
                new_position=new_position,
            )

        # Left top 20
        if new_position > 20 and old_position <= 20:
            return RankingAlert(
                keyword=keyword,
                domain=domain,
                alert_type=AlertType.LEFT_TOP_20,
                message=f"Dropped out of top 20 (moved from #{old_position} to #{new_position})",
                old_position=old_position,
                new_position=new_position,
            )

        # Big jump (improvement of 10+)
        if change >= 10:
            return RankingAlert(
                keyword=keyword,
                domain=domain,
                alert_type=AlertType.BIG_JUMP,
                message=f"Big jump: +{change} positions (from #{old_position} to #{new_position})",
                old_position=old_position,
                new_position=new_position,
            )

        # Big drop (-10 or worse)
        if change <= -10:
            return RankingAlert(
                keyword=keyword,
                domain=domain,
                alert_type=AlertType.BIG_DROP,
                message=f"Big drop: {change} positions (from #{old_position} to #{new_position})",
                old_position=old_position,
                new_position=new_position,
            )

        return None

    def get_history(
        self,
        keyword: str,
        domain: str,
        days: int = 30,
    ) -> List[RankingSnapshot]:
        """
        Get ranking history for a keyword/domain.

        Args:
            keyword: Search keyword
            domain: Domain
            days: Days of history

        Returns:
            list: Historical snapshots
        """
        cache_key = self._get_cache_key(keyword, domain)
        cutoff = datetime.now() - timedelta(days=days)

        # Check cache first
        cached = [
            s for s in self._recent_rankings[cache_key]
            if s.recorded_at > cutoff
        ]

        if cached:
            return cached

        # Load from database
        return self._load_history(keyword, domain, days)

    def _load_history(
        self,
        keyword: str,
        domain: str,
        days: int,
    ) -> List[RankingSnapshot]:
        """Load history from database."""
        try:
            conn = self.db.engine.connect()
            cutoff = datetime.now() - timedelta(days=days)

            query = """
                SELECT keyword, domain, position, url, recorded_at
                FROM keyword_ranking_history
                WHERE keyword = %(keyword)s
                  AND domain = %(domain)s
                  AND recorded_at > %(cutoff)s
                ORDER BY recorded_at ASC
            """

            result = conn.execute(query, {
                "keyword": keyword.lower(),
                "domain": domain.lower(),
                "cutoff": cutoff,
            })

            snapshots = [
                RankingSnapshot(
                    keyword=row["keyword"],
                    domain=row["domain"],
                    position=row["position"],
                    url=row.get("url"),
                    recorded_at=row["recorded_at"],
                )
                for row in result
            ]

            conn.close()

            # Update cache
            cache_key = self._get_cache_key(keyword, domain)
            self._recent_rankings[cache_key] = snapshots

            return snapshots

        except Exception as e:
            self.logger.warning(f"Failed to load history: {e}")
            return []

    def _calculate_volatility(self, positions: List[int]) -> VolatilityLevel:
        """
        Calculate ranking volatility.

        Args:
            positions: List of positions

        Returns:
            VolatilityLevel: Volatility classification
        """
        if len(positions) < 2:
            return VolatilityLevel.STABLE

        # Calculate variance
        avg = sum(positions) / len(positions)
        variance = sum((p - avg) ** 2 for p in positions) / len(positions)
        std_dev = variance ** 0.5

        if std_dev < 2:
            return VolatilityLevel.STABLE
        elif std_dev < 5:
            return VolatilityLevel.LOW
        elif std_dev < 10:
            return VolatilityLevel.MODERATE
        elif std_dev < 20:
            return VolatilityLevel.HIGH
        else:
            return VolatilityLevel.EXTREME

    def _determine_trend(
        self,
        current: Optional[int],
        previous: Optional[int],
        change: int,
    ) -> TrendDirection:
        """
        Determine trend direction.

        Args:
            current: Current position
            previous: Previous position
            change: Position change

        Returns:
            TrendDirection: Trend classification
        """
        if current is None and previous is not None:
            return TrendDirection.LOST
        if previous is None:
            return TrendDirection.NEW

        if change >= 10:
            return TrendDirection.STRONG_UP
        elif change >= 3:
            return TrendDirection.UP
        elif change <= -10:
            return TrendDirection.STRONG_DOWN
        elif change <= -3:
            return TrendDirection.DOWN
        else:
            return TrendDirection.STABLE

    def analyze_trend(
        self,
        keyword: str,
        domain: str,
        days: int = 30,
    ) -> TrendAnalysis:
        """
        Analyze ranking trend for a keyword/domain.

        Args:
            keyword: Search keyword
            domain: Domain
            days: Days to analyze

        Returns:
            TrendAnalysis: Complete trend analysis
        """
        history = self.get_history(keyword, domain, days)

        if not history:
            return TrendAnalysis(
                keyword=keyword,
                domain=domain,
                current_position=None,
                previous_position=None,
                position_change=0,
                trend_direction=TrendDirection.NEW,
                volatility=VolatilityLevel.STABLE,
                avg_position_7d=0,
                avg_position_30d=0,
                best_position=0,
                worst_position=0,
                days_in_top_10=0,
                total_data_points=0,
            )

        positions = [s.position for s in history]

        # Current and previous positions
        current_position = history[-1].position if history else None
        previous_position = history[-2].position if len(history) >= 2 else None

        # Position change
        if current_position and previous_position:
            change = previous_position - current_position  # Positive = improvement
        else:
            change = 0

        # Calculate averages
        now = datetime.now()
        positions_7d = [
            s.position for s in history
            if s.recorded_at > now - timedelta(days=7)
        ]
        positions_30d = positions

        avg_7d = sum(positions_7d) / len(positions_7d) if positions_7d else 0
        avg_30d = sum(positions_30d) / len(positions_30d) if positions_30d else 0

        # Best/worst
        best_position = min(positions)
        worst_position = max(positions)

        # Days in top 10 (count unique days)
        top_10_days = set()
        for s in history:
            if s.position <= 10:
                top_10_days.add(s.recorded_at.date())

        return TrendAnalysis(
            keyword=keyword,
            domain=domain,
            current_position=current_position,
            previous_position=previous_position,
            position_change=change,
            trend_direction=self._determine_trend(current_position, previous_position, change),
            volatility=self._calculate_volatility(positions),
            avg_position_7d=avg_7d,
            avg_position_30d=avg_30d,
            best_position=best_position,
            worst_position=worst_position,
            days_in_top_10=len(top_10_days),
            total_data_points=len(history),
            first_seen=history[0].recorded_at if history else None,
            last_seen=history[-1].recorded_at if history else None,
        )

    def get_domain_summary(
        self,
        domain: str,
        days: int = 7,
    ) -> DomainTrendSummary:
        """
        Get trend summary for all keywords for a domain.

        Args:
            domain: Domain to analyze
            days: Days to analyze

        Returns:
            DomainTrendSummary: Complete summary
        """
        self.logger.info(f"Generating trend summary for {domain}")

        # Get all keywords for domain from cache
        domain_lower = domain.lower()
        keyword_trends = []
        alerts = []

        for cache_key, snapshots in self._recent_rankings.items():
            if f"|{domain_lower}" not in cache_key:
                continue

            keyword = cache_key.split("|")[0]
            trend = self.analyze_trend(keyword, domain, days)
            keyword_trends.append(trend)

            # Collect recent alerts
            if snapshots and len(snapshots) >= 2:
                alert = self._check_alerts(
                    keyword, domain,
                    snapshots[-1].position,
                    snapshots[-2].position,
                )
                if alert:
                    alerts.append(alert)

        if not keyword_trends:
            return DomainTrendSummary(
                domain=domain,
                total_keywords=0,
                keywords_improving=0,
                keywords_declining=0,
                keywords_stable=0,
                keywords_new=0,
                keywords_lost=0,
                avg_position=0,
                avg_position_change=0,
                keywords_in_top_3=0,
                keywords_in_top_10=0,
                keywords_in_top_20=0,
            )

        # Count by trend direction
        improving = sum(1 for t in keyword_trends if t.trend_direction in (TrendDirection.UP, TrendDirection.STRONG_UP))
        declining = sum(1 for t in keyword_trends if t.trend_direction in (TrendDirection.DOWN, TrendDirection.STRONG_DOWN))
        stable = sum(1 for t in keyword_trends if t.trend_direction == TrendDirection.STABLE)
        new_count = sum(1 for t in keyword_trends if t.trend_direction == TrendDirection.NEW)
        lost = sum(1 for t in keyword_trends if t.trend_direction == TrendDirection.LOST)

        # Position distribution
        active_trends = [t for t in keyword_trends if t.current_position]
        top_3 = sum(1 for t in active_trends if t.current_position <= 3)
        top_10 = sum(1 for t in active_trends if t.current_position <= 10)
        top_20 = sum(1 for t in active_trends if t.current_position <= 20)

        # Averages
        positions = [t.current_position for t in active_trends if t.current_position]
        changes = [t.position_change for t in keyword_trends]

        avg_pos = sum(positions) / len(positions) if positions else 0
        avg_change = sum(changes) / len(changes) if changes else 0

        # Top movers (biggest improvements)
        top_movers = sorted(
            [t for t in keyword_trends if t.position_change > 0],
            key=lambda x: x.position_change,
            reverse=True,
        )[:5]

        # Biggest drops
        biggest_drops = sorted(
            [t for t in keyword_trends if t.position_change < 0],
            key=lambda x: x.position_change,
        )[:5]

        return DomainTrendSummary(
            domain=domain,
            total_keywords=len(keyword_trends),
            keywords_improving=improving,
            keywords_declining=declining,
            keywords_stable=stable,
            keywords_new=new_count,
            keywords_lost=lost,
            avg_position=avg_pos,
            avg_position_change=avg_change,
            keywords_in_top_3=top_3,
            keywords_in_top_10=top_10,
            keywords_in_top_20=top_20,
            top_movers=top_movers,
            biggest_drops=biggest_drops,
            alerts=alerts,
        )

    def compare_domains(
        self,
        keyword: str,
        domains: List[str],
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Compare ranking trends across domains for a keyword.

        Args:
            keyword: Search keyword
            domains: Domains to compare
            days: Days to analyze

        Returns:
            dict: Comparison results
        """
        trends = {}
        for domain in domains:
            trends[domain] = self.analyze_trend(keyword, domain, days)

        # Sort by current position
        sorted_trends = sorted(
            trends.items(),
            key=lambda x: x[1].current_position or 999,
        )

        return {
            "keyword": keyword,
            "domains_analyzed": len(domains),
            "rankings": [
                {
                    "rank": i + 1,
                    "domain": domain,
                    "position": trend.current_position,
                    "change": trend.position_change,
                    "trend": trend.trend_direction.value,
                }
                for i, (domain, trend) in enumerate(sorted_trends)
            ],
            "leader": sorted_trends[0][0] if sorted_trends else None,
            "most_improved": max(trends.items(), key=lambda x: x[1].position_change)[0] if trends else None,
        }

    def get_alerts(
        self,
        domain: str,
        alert_types: Optional[List[AlertType]] = None,
        limit: int = 20,
    ) -> List[RankingAlert]:
        """
        Get ranking alerts for a domain.

        Args:
            domain: Domain to check
            alert_types: Filter by alert types
            limit: Maximum alerts to return

        Returns:
            list: Recent alerts
        """
        alerts = []
        domain_lower = domain.lower()

        # Check all cached rankings for this domain
        for cache_key, snapshots in self._recent_rankings.items():
            if f"|{domain_lower}" not in cache_key:
                continue

            if len(snapshots) < 2:
                continue

            keyword = cache_key.split("|")[0]

            # Check last transition
            alert = self._check_alerts(
                keyword, domain,
                snapshots[-1].position,
                snapshots[-2].position,
            )

            if alert:
                if alert_types is None or alert.alert_type in alert_types:
                    alerts.append(alert)

        # Sort by created_at and limit
        alerts.sort(key=lambda x: x.created_at, reverse=True)
        return alerts[:limit]

    def bulk_record(
        self,
        rankings: List[Dict[str, Any]],
    ) -> List[RankingAlert]:
        """
        Record multiple rankings at once.

        Args:
            rankings: List of {keyword, domain, position, url?}

        Returns:
            list: Generated alerts
        """
        alerts = []

        for ranking in rankings:
            alert = self.record_ranking(
                keyword=ranking["keyword"],
                domain=ranking["domain"],
                position=ranking["position"],
                url=ranking.get("url"),
            )
            if alert:
                alerts.append(alert)

        self.logger.info(
            f"Recorded {len(rankings)} rankings, generated {len(alerts)} alerts"
        )

        return alerts


# Module-level singleton
_ranking_trends_instance = None


def get_ranking_trends() -> RankingTrends:
    """Get or create the singleton RankingTrends instance."""
    global _ranking_trends_instance

    if _ranking_trends_instance is None:
        _ranking_trends_instance = RankingTrends()

    return _ranking_trends_instance
