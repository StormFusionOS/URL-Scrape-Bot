"""
Alert Manager

Monitors competitor changes and generates alerts for significant events:
- Ranking changes (improved or dropped significantly)
- New services detected
- Price changes
- Review spikes (sudden increase in reviews)
- Rating drops
- New content/pages
- Citation changes
- Threat level increases

Alert Severities:
- critical: Requires immediate attention
- high: Should be addressed soon
- medium: Worth noting
- low: Informational
- info: For tracking purposes
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import text

from db.database_manager import get_db_manager

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Types of competitor alerts."""
    RANKING_IMPROVED = 'ranking_improved'
    RANKING_DROPPED = 'ranking_dropped'
    NEW_SERVICE = 'new_service'
    PRICE_CHANGE = 'price_change'
    REVIEW_SPIKE = 'review_spike'
    RATING_DROP = 'rating_drop'
    RATING_INCREASE = 'rating_increase'
    NEW_CONTENT = 'new_content'
    CITATION_ADDED = 'citation_added'
    CITATION_LOST = 'citation_lost'
    THREAT_INCREASED = 'threat_increased'
    SOV_CHANGE = 'sov_change'


class AlertSeverity(Enum):
    """Alert severity levels."""
    CRITICAL = 'critical'
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    INFO = 'info'


@dataclass
class Alert:
    """Represents a competitor alert."""
    competitor_id: int
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    description: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    change_magnitude: Optional[float] = None
    company_id: Optional[int] = None
    metadata: Optional[Dict] = None


class AlertManager:
    """
    Manages competitor alerts.

    Detects significant changes and creates alerts based on
    configurable thresholds.
    """

    # Alert thresholds
    THRESHOLDS = {
        'ranking_major_change': 10,     # Positions changed
        'ranking_critical_change': 20,  # Positions changed
        'price_change_pct': 15,         # Percent change
        'review_spike_count': 5,        # New reviews in 7 days
        'rating_drop': 0.3,             # Rating points
        'sov_change': 5,                # Percentage points
    }

    def __init__(self, company_id: Optional[int] = None):
        self.company_id = company_id
        self.db_manager = get_db_manager()

    def check_all_alerts(self, competitor_id: int, domain: str) -> List[Alert]:
        """
        Check for all types of alerts for a competitor.

        Args:
            competitor_id: Competitor to check
            domain: Competitor's domain

        Returns:
            List of generated alerts
        """
        alerts = []

        try:
            # Check each alert type
            alerts.extend(self._check_ranking_changes(competitor_id, domain))
            alerts.extend(self._check_new_services(competitor_id))
            alerts.extend(self._check_price_changes(competitor_id))
            alerts.extend(self._check_review_spikes(competitor_id))
            alerts.extend(self._check_rating_changes(competitor_id))
            alerts.extend(self._check_citation_changes(competitor_id, domain))

            # Save any generated alerts
            for alert in alerts:
                self._save_alert(alert)

            if alerts:
                logger.info(f"Generated {len(alerts)} alerts for competitor {competitor_id}")

        except Exception as e:
            logger.error(f"Failed to check alerts for competitor {competitor_id}: {e}")

        return alerts

    def _check_ranking_changes(self, competitor_id: int, domain: str) -> List[Alert]:
        """Check for significant ranking changes."""
        alerts = []

        try:
            with self.db_manager.get_session() as session:
                # Get ranking changes in last 7 days
                result = session.execute(text("""
                    WITH ranked_data AS (
                        SELECT
                            keyword,
                            position,
                            captured_at,
                            LAG(position) OVER (
                                PARTITION BY keyword
                                ORDER BY captured_at
                            ) as prev_position
                        FROM keyword_rankings
                        WHERE domain = :domain
                          AND captured_at > NOW() - INTERVAL '7 days'
                    )
                    SELECT
                        keyword,
                        prev_position,
                        position as new_position,
                        (prev_position - position) as improvement
                    FROM ranked_data
                    WHERE prev_position IS NOT NULL
                      AND ABS(prev_position - position) >= :threshold
                    ORDER BY ABS(prev_position - position) DESC
                    LIMIT 10
                """), {
                    'domain': domain,
                    'threshold': self.THRESHOLDS['ranking_major_change'],
                })

                for row in result.fetchall():
                    keyword = row[0]
                    old_pos = row[1]
                    new_pos = row[2]
                    improvement = row[3]

                    if improvement > 0:
                        # They improved
                        if improvement >= self.THRESHOLDS['ranking_critical_change']:
                            severity = AlertSeverity.CRITICAL
                        else:
                            severity = AlertSeverity.HIGH

                        alert = Alert(
                            competitor_id=competitor_id,
                            company_id=self.company_id,
                            alert_type=AlertType.RANKING_IMPROVED,
                            severity=severity,
                            title=f"Competitor jumped {improvement} positions for '{keyword}'",
                            description=f"Moved from position {old_pos} to {new_pos}. "
                                        f"This could impact your visibility for this keyword.",
                            old_value=str(old_pos),
                            new_value=str(new_pos),
                            change_magnitude=float(improvement),
                            metadata={'keyword': keyword},
                        )
                        alerts.append(alert)
                    else:
                        # They dropped (we gained relative ground)
                        drop = abs(improvement)
                        if drop >= self.THRESHOLDS['ranking_critical_change']:
                            severity = AlertSeverity.INFO
                        else:
                            severity = AlertSeverity.LOW

                        alert = Alert(
                            competitor_id=competitor_id,
                            company_id=self.company_id,
                            alert_type=AlertType.RANKING_DROPPED,
                            severity=severity,
                            title=f"Competitor dropped {drop} positions for '{keyword}'",
                            description=f"Moved from position {old_pos} to {new_pos}. "
                                        f"Opportunity to capitalize on their decline.",
                            old_value=str(old_pos),
                            new_value=str(new_pos),
                            change_magnitude=float(-drop),
                            metadata={'keyword': keyword},
                        )
                        alerts.append(alert)

        except Exception as e:
            logger.debug(f"Error checking ranking changes: {e}")

        return alerts

    def _check_new_services(self, competitor_id: int) -> List[Alert]:
        """Check for newly detected services."""
        alerts = []

        try:
            with self.db_manager.get_session() as session:
                # Find services discovered in last 7 days
                result = session.execute(text("""
                    SELECT service_name, service_category, price_min, price_max
                    FROM competitor_services
                    WHERE competitor_id = :competitor_id
                      AND discovered_at > NOW() - INTERVAL '7 days'
                      AND is_active = true
                """), {'competitor_id': competitor_id})

                for row in result.fetchall():
                    service_name = row[0]
                    category = row[1]
                    price_min = row[2]
                    price_max = row[3]

                    price_info = ""
                    if price_min and price_max:
                        price_info = f" at ${price_min:.0f}-${price_max:.0f}"
                    elif price_min:
                        price_info = f" starting at ${price_min:.0f}"

                    alert = Alert(
                        competitor_id=competitor_id,
                        company_id=self.company_id,
                        alert_type=AlertType.NEW_SERVICE,
                        severity=AlertSeverity.MEDIUM,
                        title=f"New service detected: {service_name}",
                        description=f"Competitor now offers {service_name}{price_info}. "
                                    f"Category: {category or 'Unknown'}",
                        new_value=service_name,
                        metadata={
                            'service_name': service_name,
                            'category': category,
                            'price_min': float(price_min) if price_min else None,
                            'price_max': float(price_max) if price_max else None,
                        },
                    )
                    alerts.append(alert)

        except Exception as e:
            logger.debug(f"Error checking new services: {e}")

        return alerts

    def _check_price_changes(self, competitor_id: int) -> List[Alert]:
        """Check for significant price changes."""
        alerts = []

        try:
            with self.db_manager.get_session() as session:
                # This would require price history tracking
                # For now, compare current prices to metadata history
                result = session.execute(text("""
                    SELECT
                        service_name,
                        price_min,
                        price_max,
                        metadata->>'previous_price_min' as prev_min,
                        metadata->>'previous_price_max' as prev_max
                    FROM competitor_services
                    WHERE competitor_id = :competitor_id
                      AND is_active = true
                      AND metadata ? 'previous_price_min'
                """), {'competitor_id': competitor_id})

                for row in result.fetchall():
                    service = row[0]
                    current_min = float(row[1]) if row[1] else None
                    prev_min = float(row[3]) if row[3] else None

                    if current_min and prev_min and prev_min > 0:
                        change_pct = ((current_min - prev_min) / prev_min) * 100

                        if abs(change_pct) >= self.THRESHOLDS['price_change_pct']:
                            direction = "increased" if change_pct > 0 else "decreased"
                            severity = AlertSeverity.HIGH if abs(change_pct) >= 25 else AlertSeverity.MEDIUM

                            alert = Alert(
                                competitor_id=competitor_id,
                                company_id=self.company_id,
                                alert_type=AlertType.PRICE_CHANGE,
                                severity=severity,
                                title=f"Price {direction} {abs(change_pct):.0f}% for {service}",
                                description=f"Price changed from ${prev_min:.0f} to ${current_min:.0f}",
                                old_value=f"${prev_min:.0f}",
                                new_value=f"${current_min:.0f}",
                                change_magnitude=change_pct,
                                metadata={'service': service},
                            )
                            alerts.append(alert)

        except Exception as e:
            logger.debug(f"Error checking price changes: {e}")

        return alerts

    def _check_review_spikes(self, competitor_id: int) -> List[Alert]:
        """Check for sudden spikes in review counts."""
        alerts = []

        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT source, review_count_7d, rating_avg
                    FROM competitor_reviews_aggregate
                    WHERE competitor_id = :competitor_id
                      AND captured_at > NOW() - INTERVAL '7 days'
                      AND review_count_7d >= :threshold
                """), {
                    'competitor_id': competitor_id,
                    'threshold': self.THRESHOLDS['review_spike_count'],
                })

                for row in result.fetchall():
                    source = row[0]
                    new_reviews = row[1]
                    rating = row[2]

                    rating_text = f" with {rating:.1f} avg rating" if rating else ""

                    alert = Alert(
                        competitor_id=competitor_id,
                        company_id=self.company_id,
                        alert_type=AlertType.REVIEW_SPIKE,
                        severity=AlertSeverity.MEDIUM,
                        title=f"{new_reviews} new {source} reviews this week",
                        description=f"Competitor received {new_reviews} reviews on {source}{rating_text}. "
                                    f"Consider reviewing their strategy.",
                        new_value=str(new_reviews),
                        change_magnitude=float(new_reviews),
                        metadata={'source': source, 'rating': float(rating) if rating else None},
                    )
                    alerts.append(alert)

        except Exception as e:
            logger.debug(f"Error checking review spikes: {e}")

        return alerts

    def _check_rating_changes(self, competitor_id: int) -> List[Alert]:
        """Check for significant rating changes."""
        alerts = []

        try:
            with self.db_manager.get_session() as session:
                # Compare current vs 30-day-old ratings
                result = session.execute(text("""
                    WITH current_ratings AS (
                        SELECT source, rating_avg
                        FROM competitor_reviews_aggregate
                        WHERE competitor_id = :competitor_id
                          AND captured_at > NOW() - INTERVAL '3 days'
                    ),
                    old_ratings AS (
                        SELECT source, rating_avg
                        FROM competitor_reviews_aggregate
                        WHERE competitor_id = :competitor_id
                          AND captured_at BETWEEN NOW() - INTERVAL '35 days'
                                               AND NOW() - INTERVAL '28 days'
                    )
                    SELECT
                        c.source,
                        o.rating_avg as old_rating,
                        c.rating_avg as new_rating,
                        c.rating_avg - o.rating_avg as change
                    FROM current_ratings c
                    JOIN old_ratings o ON c.source = o.source
                    WHERE ABS(c.rating_avg - o.rating_avg) >= :threshold
                """), {
                    'competitor_id': competitor_id,
                    'threshold': self.THRESHOLDS['rating_drop'],
                })

                for row in result.fetchall():
                    source = row[0]
                    old_rating = float(row[1])
                    new_rating = float(row[2])
                    change = float(row[3])

                    if change < 0:
                        # Rating dropped
                        alert = Alert(
                            competitor_id=competitor_id,
                            company_id=self.company_id,
                            alert_type=AlertType.RATING_DROP,
                            severity=AlertSeverity.LOW,
                            title=f"{source} rating dropped by {abs(change):.1f} stars",
                            description=f"Rating went from {old_rating:.1f} to {new_rating:.1f}. "
                                        f"Opportunity to highlight your superior rating.",
                            old_value=f"{old_rating:.1f}",
                            new_value=f"{new_rating:.1f}",
                            change_magnitude=change,
                            metadata={'source': source},
                        )
                        alerts.append(alert)
                    else:
                        # Rating improved
                        alert = Alert(
                            competitor_id=competitor_id,
                            company_id=self.company_id,
                            alert_type=AlertType.RATING_INCREASE,
                            severity=AlertSeverity.MEDIUM,
                            title=f"{source} rating improved by {change:.1f} stars",
                            description=f"Rating went from {old_rating:.1f} to {new_rating:.1f}. "
                                        f"Monitor their review strategy.",
                            old_value=f"{old_rating:.1f}",
                            new_value=f"{new_rating:.1f}",
                            change_magnitude=change,
                            metadata={'source': source},
                        )
                        alerts.append(alert)

        except Exception as e:
            logger.debug(f"Error checking rating changes: {e}")

        return alerts

    def _check_citation_changes(self, competitor_id: int, domain: str) -> List[Alert]:
        """Check for new or lost citations."""
        alerts = []

        try:
            with self.db_manager.get_session() as session:
                # New citations in last 7 days
                result = session.execute(text("""
                    SELECT source_name, source_url
                    FROM discovery_citations
                    WHERE company_id IN (
                        SELECT company_id FROM company_competitors
                        WHERE competitor_id = :competitor_id
                    )
                    AND first_seen_at > NOW() - INTERVAL '7 days'
                    LIMIT 5
                """), {'competitor_id': competitor_id})

                new_citations = result.fetchall()

                if new_citations:
                    sources = [row[0] for row in new_citations]
                    alert = Alert(
                        competitor_id=competitor_id,
                        company_id=self.company_id,
                        alert_type=AlertType.CITATION_ADDED,
                        severity=AlertSeverity.LOW,
                        title=f"{len(new_citations)} new citations detected",
                        description=f"New listings on: {', '.join(sources[:3])}{'...' if len(sources) > 3 else ''}",
                        change_magnitude=float(len(new_citations)),
                        metadata={'sources': sources},
                    )
                    alerts.append(alert)

        except Exception as e:
            logger.debug(f"Error checking citation changes: {e}")

        return alerts

    def _save_alert(self, alert: Alert):
        """Save an alert to the database."""
        try:
            with self.db_manager.get_session() as session:
                import json

                session.execute(text("""
                    INSERT INTO competitor_alerts
                        (competitor_id, company_id, alert_type, severity,
                         title, description, old_value, new_value,
                         change_magnitude, metadata, triggered_at)
                    VALUES
                        (:competitor_id, :company_id, :alert_type, :severity,
                         :title, :description, :old_value, :new_value,
                         :change_magnitude, :metadata, NOW())
                """), {
                    'competitor_id': alert.competitor_id,
                    'company_id': alert.company_id,
                    'alert_type': alert.alert_type.value,
                    'severity': alert.severity.value,
                    'title': alert.title,
                    'description': alert.description,
                    'old_value': alert.old_value,
                    'new_value': alert.new_value,
                    'change_magnitude': alert.change_magnitude,
                    'metadata': json.dumps(alert.metadata) if alert.metadata else None,
                })

                session.commit()

        except Exception as e:
            logger.error(f"Failed to save alert: {e}")

    def get_unacknowledged_alerts(
        self,
        competitor_id: Optional[int] = None,
        severity: Optional[AlertSeverity] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get unacknowledged alerts."""
        try:
            with self.db_manager.get_session() as session:
                query = """
                    SELECT
                        id, competitor_id, alert_type, severity,
                        title, description, old_value, new_value,
                        change_magnitude, triggered_at, metadata
                    FROM competitor_alerts
                    WHERE acknowledged_at IS NULL
                """

                params = {}

                if self.company_id:
                    query += " AND company_id = :company_id"
                    params['company_id'] = self.company_id

                if competitor_id:
                    query += " AND competitor_id = :competitor_id"
                    params['competitor_id'] = competitor_id

                if severity:
                    query += " AND severity = :severity"
                    params['severity'] = severity.value

                query += " ORDER BY triggered_at DESC LIMIT :limit"
                params['limit'] = limit

                result = session.execute(text(query), params)

                alerts = []
                for row in result.fetchall():
                    alerts.append({
                        'id': row[0],
                        'competitor_id': row[1],
                        'alert_type': row[2],
                        'severity': row[3],
                        'title': row[4],
                        'description': row[5],
                        'old_value': row[6],
                        'new_value': row[7],
                        'change_magnitude': row[8],
                        'triggered_at': row[9].isoformat() if row[9] else None,
                        'metadata': row[10],
                    })

                return alerts

        except Exception as e:
            logger.error(f"Failed to get alerts: {e}")
            return []

    def acknowledge_alert(self, alert_id: int, acknowledged_by: str):
        """Mark an alert as acknowledged."""
        try:
            with self.db_manager.get_session() as session:
                session.execute(text("""
                    UPDATE competitor_alerts
                    SET acknowledged_at = NOW(),
                        acknowledged_by = :acked_by
                    WHERE id = :alert_id
                """), {
                    'alert_id': alert_id,
                    'acked_by': acknowledged_by,
                })

                session.commit()
                logger.debug(f"Acknowledged alert {alert_id}")

        except Exception as e:
            logger.error(f"Failed to acknowledge alert: {e}")

    def get_alert_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get a summary of alerts over a time period."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT
                        alert_type,
                        severity,
                        COUNT(*) as count,
                        COUNT(*) FILTER (WHERE acknowledged_at IS NULL) as unacked
                    FROM competitor_alerts
                    WHERE triggered_at > NOW() - INTERVAL ':days days'
                    GROUP BY alert_type, severity
                    ORDER BY count DESC
                """.replace(':days', str(days))))

                by_type = {}
                by_severity = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0}
                total = 0
                total_unacked = 0

                for row in result.fetchall():
                    alert_type = row[0]
                    severity = row[1]
                    count = row[2]
                    unacked = row[3]

                    by_type[alert_type] = by_type.get(alert_type, 0) + count
                    by_severity[severity] = by_severity.get(severity, 0) + count
                    total += count
                    total_unacked += unacked

                return {
                    'period_days': days,
                    'total_alerts': total,
                    'unacknowledged': total_unacked,
                    'by_type': by_type,
                    'by_severity': by_severity,
                }

        except Exception as e:
            logger.error(f"Failed to get alert summary: {e}")
            return {
                'period_days': days,
                'total_alerts': 0,
                'unacknowledged': 0,
                'by_type': {},
                'by_severity': {},
            }


def check_competitor_alerts(
    competitor_id: int,
    domain: str,
    company_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Main entry point for alert checking.

    Args:
        competitor_id: Competitor to check
        domain: Competitor's domain
        company_id: Optional company context

    Returns:
        Dict with alert results
    """
    manager = AlertManager(company_id)
    alerts = manager.check_all_alerts(competitor_id, domain)

    return {
        'success': True,
        'competitor_id': competitor_id,
        'alerts_generated': len(alerts),
        'alerts': [
            {
                'type': a.alert_type.value,
                'severity': a.severity.value,
                'title': a.title,
            }
            for a in alerts
        ],
    }
