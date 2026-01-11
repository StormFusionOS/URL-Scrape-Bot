"""
Price Tracker for Competitor Intelligence

Tracks competitor pricing over time:
- Daily price snapshots
- Change detection with alerts
- Trend analysis (rising, falling, stable)
- Promotional period detection
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from competitor_intel.config import PRICING_CONFIG
from db.database_manager import create_session

logger = logging.getLogger(__name__)


@dataclass
class PriceSnapshot:
    """A single price snapshot."""
    service_id: int
    price_min: Decimal
    price_max: Decimal
    price_unit: str
    pricing_model: str
    is_promotional: bool = False
    promotion_name: Optional[str] = None
    captured_at: datetime = field(default_factory=datetime.now)


@dataclass
class PriceChange:
    """Detected price change."""
    service_id: int
    service_name: str
    old_price_min: Decimal
    old_price_max: Decimal
    new_price_min: Decimal
    new_price_max: Decimal
    change_type: str  # increase, decrease
    change_amount: Decimal
    change_percent: float
    detected_at: datetime = field(default_factory=datetime.now)


@dataclass
class PriceTrend:
    """Price trend analysis result."""
    service_id: int
    trend_direction: str  # rising, falling, stable
    avg_price: Decimal
    min_price: Decimal
    max_price: Decimal
    price_volatility: float  # Standard deviation as percentage
    data_points: int


class PriceTracker:
    """
    Tracks and analyzes competitor pricing over time.

    Features:
    - Record daily price snapshots
    - Detect significant price changes
    - Analyze price trends
    - Detect promotional pricing periods
    """

    def __init__(self):
        self.change_threshold = PRICING_CONFIG.get("change_threshold", 0.10)
        self.history_days = PRICING_CONFIG.get("history_days", 365)

        logger.info("PriceTracker initialized")

    def record_snapshot(
        self,
        competitor_id: int,
        service_id: int,
        price_min: float,
        price_max: float,
        price_unit: str = None,
        pricing_model: str = None,
        is_promotional: bool = False,
        promotion_name: str = None,
        source_url: str = None,
        confidence: float = 1.0,
    ) -> Optional[PriceChange]:
        """
        Record a price snapshot and detect changes.

        Args:
            competitor_id: The competitor ID
            service_id: The service ID
            price_min: Minimum price
            price_max: Maximum price (can be same as min)
            price_unit: Price unit (per_hour, per_sqft, etc.)
            pricing_model: Pricing model (flat, hourly, etc.)
            is_promotional: Whether this is promotional pricing
            promotion_name: Name of promotion if applicable
            source_url: URL where price was found
            confidence: Extraction confidence (0-1)

        Returns:
            PriceChange if a significant change was detected, None otherwise
        """
        session = create_session()
        change_detected = None

        try:
            # Get previous price
            prev = session.execute(text("""
                SELECT price_min, price_max
                FROM competitor_price_history
                WHERE service_id = :service_id
                ORDER BY captured_at DESC
                LIMIT 1
            """), {"service_id": service_id}).fetchone()

            # Detect change
            if prev:
                old_min, old_max = Decimal(str(prev[0])), Decimal(str(prev[1]))
                new_min, new_max = Decimal(str(price_min)), Decimal(str(price_max))

                # Calculate change percentage (using avg of min/max)
                old_avg = (old_min + old_max) / 2
                new_avg = (new_min + new_max) / 2

                if old_avg > 0:
                    change_pct = float((new_avg - old_avg) / old_avg)

                    if abs(change_pct) >= self.change_threshold:
                        change_type = "increase" if change_pct > 0 else "decrease"

                        # Get service name
                        service_name = session.execute(text("""
                            SELECT service_name FROM competitor_services
                            WHERE id = :id
                        """), {"id": service_id}).fetchone()

                        change_detected = PriceChange(
                            service_id=service_id,
                            service_name=service_name[0] if service_name else "Unknown",
                            old_price_min=old_min,
                            old_price_max=old_max,
                            new_price_min=new_min,
                            new_price_max=new_max,
                            change_type=change_type,
                            change_amount=new_avg - old_avg,
                            change_percent=round(change_pct * 100, 1),
                        )

                        # Update service with previous prices
                        session.execute(text("""
                            UPDATE competitor_services
                            SET previous_price_min = :old_min,
                                previous_price_max = :old_max,
                                price_last_changed_at = NOW()
                            WHERE id = :service_id
                        """), {
                            "old_min": old_min,
                            "old_max": old_max,
                            "service_id": service_id,
                        })

            # Insert snapshot
            session.execute(text("""
                INSERT INTO competitor_price_history (
                    competitor_id, service_id, price_min, price_max,
                    price_unit, pricing_model, is_promotional,
                    promotion_name, source_url, extraction_confidence
                ) VALUES (
                    :competitor_id, :service_id, :price_min, :price_max,
                    :price_unit, :pricing_model, :is_promotional,
                    :promotion_name, :source_url, :confidence
                )
            """), {
                "competitor_id": competitor_id,
                "service_id": service_id,
                "price_min": price_min,
                "price_max": price_max,
                "price_unit": price_unit,
                "pricing_model": pricing_model,
                "is_promotional": is_promotional,
                "promotion_name": promotion_name,
                "source_url": source_url,
                "confidence": confidence,
            })

            session.commit()
            logger.debug(f"Recorded price snapshot for service {service_id}")

        except Exception as e:
            logger.error(f"Failed to record price snapshot: {e}")
            session.rollback()
        finally:
            session.close()

        return change_detected

    def get_price_history(
        self, service_id: int, days: int = None
    ) -> List[PriceSnapshot]:
        """
        Get price history for a service.

        Args:
            service_id: The service ID
            days: Number of days of history (default: config setting)

        Returns:
            List of PriceSnapshot objects
        """
        days = days or self.history_days
        cutoff = datetime.now() - timedelta(days=days)

        session = create_session()
        try:
            result = session.execute(text("""
                SELECT service_id, price_min, price_max, price_unit,
                       pricing_model, is_promotional, promotion_name, captured_at
                FROM competitor_price_history
                WHERE service_id = :service_id AND captured_at >= :cutoff
                ORDER BY captured_at ASC
            """), {
                "service_id": service_id,
                "cutoff": cutoff,
            }).fetchall()

            return [
                PriceSnapshot(
                    service_id=r[0],
                    price_min=Decimal(str(r[1])),
                    price_max=Decimal(str(r[2])),
                    price_unit=r[3],
                    pricing_model=r[4],
                    is_promotional=r[5],
                    promotion_name=r[6],
                    captured_at=r[7],
                )
                for r in result
            ]
        finally:
            session.close()

    def calculate_trend(self, service_id: int, days: int = 90) -> Optional[PriceTrend]:
        """
        Calculate price trend for a service.

        Args:
            service_id: The service ID
            days: Analysis period in days

        Returns:
            PriceTrend or None if insufficient data
        """
        history = self.get_price_history(service_id, days)

        if len(history) < 2:
            return None

        # Calculate statistics
        prices = [(float(h.price_min) + float(h.price_max)) / 2 for h in history]

        avg_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)

        # Calculate volatility (coefficient of variation)
        if avg_price > 0:
            variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
            std_dev = variance ** 0.5
            volatility = (std_dev / avg_price) * 100
        else:
            volatility = 0.0

        # Determine trend direction
        first_half = prices[:len(prices)//2]
        second_half = prices[len(prices)//2:]

        first_avg = sum(first_half) / len(first_half) if first_half else 0
        second_avg = sum(second_half) / len(second_half) if second_half else 0

        if second_avg > first_avg * 1.05:
            trend_direction = "rising"
        elif second_avg < first_avg * 0.95:
            trend_direction = "falling"
        else:
            trend_direction = "stable"

        return PriceTrend(
            service_id=service_id,
            trend_direction=trend_direction,
            avg_price=Decimal(str(round(avg_price, 2))),
            min_price=Decimal(str(round(min_price, 2))),
            max_price=Decimal(str(round(max_price, 2))),
            price_volatility=round(volatility, 2),
            data_points=len(history),
        )

    def detect_promotional_periods(
        self, service_id: int, days: int = 365
    ) -> List[Dict]:
        """
        Detect periods of promotional pricing.

        Args:
            service_id: The service ID
            days: Analysis period

        Returns:
            List of promotional period dicts
        """
        history = self.get_price_history(service_id, days)

        promotional_periods = []
        current_promo = None

        for snapshot in history:
            if snapshot.is_promotional:
                if current_promo is None:
                    current_promo = {
                        "start_date": snapshot.captured_at,
                        "promotion_name": snapshot.promotion_name,
                        "price_min": snapshot.price_min,
                        "price_max": snapshot.price_max,
                    }
            else:
                if current_promo is not None:
                    current_promo["end_date"] = snapshot.captured_at
                    promotional_periods.append(current_promo)
                    current_promo = None

        # Handle ongoing promotion
        if current_promo is not None:
            current_promo["end_date"] = None  # Still active
            promotional_periods.append(current_promo)

        return promotional_periods

    def get_competitor_price_changes(
        self, competitor_id: int, days: int = 30
    ) -> List[PriceChange]:
        """
        Get all price changes for a competitor in the given period.

        Args:
            competitor_id: The competitor ID
            days: Period to check

        Returns:
            List of PriceChange objects
        """
        session = create_session()
        try:
            cutoff = datetime.now() - timedelta(days=days)

            result = session.execute(text("""
                SELECT cs.id, cs.service_name,
                       cs.previous_price_min, cs.previous_price_max,
                       cs.price_min, cs.price_max,
                       cs.price_last_changed_at
                FROM competitor_services cs
                WHERE cs.competitor_id = :competitor_id
                  AND cs.price_last_changed_at >= :cutoff
                  AND cs.previous_price_min IS NOT NULL
            """), {
                "competitor_id": competitor_id,
                "cutoff": cutoff,
            }).fetchall()

            changes = []
            for r in result:
                old_avg = (Decimal(str(r[2])) + Decimal(str(r[3]))) / 2
                new_avg = (Decimal(str(r[4])) + Decimal(str(r[5]))) / 2

                if old_avg > 0:
                    change_pct = float((new_avg - old_avg) / old_avg) * 100
                else:
                    change_pct = 100.0

                changes.append(PriceChange(
                    service_id=r[0],
                    service_name=r[1],
                    old_price_min=Decimal(str(r[2])),
                    old_price_max=Decimal(str(r[3])),
                    new_price_min=Decimal(str(r[4])),
                    new_price_max=Decimal(str(r[5])),
                    change_type="increase" if change_pct > 0 else "decrease",
                    change_amount=new_avg - old_avg,
                    change_percent=round(change_pct, 1),
                    detected_at=r[6],
                ))

            return changes
        finally:
            session.close()


def record_price_snapshot(
    competitor_id: int,
    service_id: int,
    price_min: float,
    price_max: float,
    **kwargs
) -> Optional[PriceChange]:
    """
    Convenience function to record a price snapshot.

    Returns:
        PriceChange if significant change detected
    """
    tracker = PriceTracker()
    return tracker.record_snapshot(
        competitor_id, service_id, price_min, price_max, **kwargs
    )
