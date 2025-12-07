"""
SERP Priority Queue Service

Prioritizes companies for SERP scraping based on:
1. Never scraped (highest priority)
2. Oldest scrape date
3. High-value indicators (verified, complete website, services match)
4. Service tier (high-value services first)

This ensures efficient use of limited scraping capacity by focusing on
the most important companies first.
"""

import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import IntEnum

from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger

logger = get_logger("serp_priority_queue")


class Priority(IntEnum):
    """Priority levels for SERP scraping."""
    CRITICAL = 1    # Never scraped, high-value service
    HIGH = 2        # Never scraped OR high-value + stale (>30 days)
    MEDIUM = 3      # Scraped but stale (>60 days)
    LOW = 4         # Recently scraped (<60 days)
    SKIP = 5        # Recently scraped (<14 days) or low-value


@dataclass
class QueuedCompany:
    """A company queued for SERP scraping with priority info."""
    company_id: int
    name: str
    website: str
    priority: Priority
    last_scraped: Optional[datetime]
    days_since_scrape: Optional[int]
    is_high_value: bool
    services: List[str]
    score_factors: Dict[str, float]


class SerpPriorityQueue:
    """
    Priority queue for SERP scraping.

    Intelligently prioritizes companies to maximize value from limited
    scraping capacity.
    """

    # High-value services that indicate important companies
    HIGH_VALUE_SERVICES = [
        'pressure_washing', 'power_washing',
        'window_cleaning', 'commercial_cleaning',
        'soft_washing', 'roof_cleaning',
    ]

    # Freshness thresholds (days)
    STALE_THRESHOLD = 30     # Consider stale after 30 days
    VERY_STALE_THRESHOLD = 60  # Very stale after 60 days
    FRESH_THRESHOLD = 14     # Fresh if scraped within 14 days

    def __init__(self):
        """Initialize the priority queue service."""
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - queue disabled")

    def _calculate_priority(
        self,
        last_scraped: Optional[datetime],
        is_high_value: bool,
        has_complete_profile: bool
    ) -> Priority:
        """
        Calculate priority based on scrape history and company value.

        Args:
            last_scraped: When the company was last scraped (None if never)
            is_high_value: True if company has high-value services
            has_complete_profile: True if company has complete info

        Returns:
            Priority level
        """
        if last_scraped is None:
            # Never scraped - highest priority
            if is_high_value:
                return Priority.CRITICAL
            else:
                return Priority.HIGH

        days_since_scrape = (datetime.now() - last_scraped).days

        if days_since_scrape < self.FRESH_THRESHOLD:
            # Recently scraped - skip unless critical
            return Priority.SKIP

        if days_since_scrape > self.VERY_STALE_THRESHOLD:
            # Very stale
            if is_high_value:
                return Priority.HIGH
            else:
                return Priority.MEDIUM

        if days_since_scrape > self.STALE_THRESHOLD:
            # Stale
            if is_high_value:
                return Priority.MEDIUM
            else:
                return Priority.LOW

        # Moderately fresh
        return Priority.LOW

    def _is_high_value(self, services: List[str]) -> bool:
        """Check if company has high-value services."""
        if not services:
            return False

        for service in services:
            service_lower = service.lower()
            for high_value in self.HIGH_VALUE_SERVICES:
                if high_value in service_lower:
                    return True

        return False

    def get_next_batch(
        self,
        limit: int = 10,
        priority_filter: Optional[Priority] = None,
        exclude_ids: Optional[List[int]] = None
    ) -> List[QueuedCompany]:
        """
        Get the next batch of companies to scrape, ordered by priority.

        Args:
            limit: Maximum number of companies to return
            priority_filter: Only return companies with this priority or higher
            exclude_ids: Company IDs to exclude

        Returns:
            List of QueuedCompany objects
        """
        if not self.engine:
            return []

        exclude_ids = exclude_ids or []
        exclude_clause = ""
        if exclude_ids:
            exclude_clause = f"AND c.id NOT IN ({','.join(map(str, exclude_ids))})"

        # Query companies with their SERP scrape history
        # Uses standardized schema: verified=true for verified companies
        query = f"""
            WITH company_serp_status AS (
                SELECT
                    c.id as company_id,
                    c.name,
                    c.website,
                    c.parse_metadata,
                    -- Get last SERP scrape time
                    (
                        SELECT MAX(ss.scraped_at)
                        FROM serp_snapshots ss
                        JOIN search_queries sq ON sq.query_id = ss.query_id
                        WHERE sq.query_text LIKE '%' || c.name || '%'
                    ) as last_scraped,
                    -- Check for complete profile
                    CASE
                        WHEN c.website IS NOT NULL
                            AND c.name IS NOT NULL
                            AND (c.parse_metadata->>'services_text') IS NOT NULL
                        THEN true
                        ELSE false
                    END as has_complete_profile
                FROM companies c
                WHERE c.verified = true
                  AND c.website IS NOT NULL
                  {exclude_clause}
            )
            SELECT
                company_id,
                name,
                website,
                parse_metadata,
                last_scraped,
                has_complete_profile,
                EXTRACT(DAY FROM (NOW() - last_scraped)) as days_since_scrape
            FROM company_serp_status
            ORDER BY
                -- Never scraped first
                CASE WHEN last_scraped IS NULL THEN 0 ELSE 1 END,
                -- Then by days since last scrape (oldest first)
                COALESCE(EXTRACT(DAY FROM (NOW() - last_scraped)), 9999) DESC,
                -- Then by ID (consistent ordering)
                company_id
            LIMIT :limit
        """

        queued = []

        try:
            with Session(self.engine) as session:
                result = session.execute(
                    text(query),
                    {'limit': limit * 2}  # Fetch extra to filter by priority
                )

                for row in result:
                    company_id = row[0]
                    name = row[1]
                    website = row[2]
                    parse_metadata = row[3] or {}
                    last_scraped = row[4]
                    has_complete_profile = row[5]
                    days_since_scrape = int(row[6]) if row[6] else None

                    # Extract services from metadata
                    services = []
                    llm_class = parse_metadata.get('verification', {}).get('llm_classification', {})
                    if llm_class:
                        services = llm_class.get('services', [])

                    # Calculate priority
                    is_high_value = self._is_high_value(services)
                    priority = self._calculate_priority(
                        last_scraped, is_high_value, has_complete_profile
                    )

                    # Apply priority filter
                    if priority_filter and priority.value > priority_filter.value:
                        continue

                    # Skip low priority unless we need them
                    if priority == Priority.SKIP:
                        continue

                    # Score factors for transparency
                    score_factors = {
                        'never_scraped': 1.0 if last_scraped is None else 0.0,
                        'high_value': 1.0 if is_high_value else 0.0,
                        'complete_profile': 1.0 if has_complete_profile else 0.5,
                        'staleness': min(1.0, (days_since_scrape or 365) / 90),
                    }

                    queued.append(QueuedCompany(
                        company_id=company_id,
                        name=name,
                        website=website,
                        priority=priority,
                        last_scraped=last_scraped,
                        days_since_scrape=days_since_scrape,
                        is_high_value=is_high_value,
                        services=services,
                        score_factors=score_factors
                    ))

                    if len(queued) >= limit:
                        break

        except Exception as e:
            logger.error(f"Error fetching priority queue: {e}", exc_info=True)

        return queued

    def get_tier_counts(self) -> Dict[str, int]:
        """
        Get counts of companies by priority tier.

        Returns:
            Dictionary with counts per tier
        """
        if not self.engine:
            return {}

        # Uses standardized schema: verified=true for verified companies
        query = """
            WITH company_status AS (
                SELECT
                    c.id,
                    c.parse_metadata,
                    (
                        SELECT MAX(ss.scraped_at)
                        FROM serp_snapshots ss
                        JOIN search_queries sq ON sq.query_id = ss.query_id
                        WHERE sq.query_text LIKE '%' || c.name || '%'
                    ) as last_scraped
                FROM companies c
                WHERE c.verified = true
                  AND c.website IS NOT NULL
            )
            SELECT
                CASE
                    WHEN last_scraped IS NULL THEN 'never_scraped'
                    WHEN last_scraped < NOW() - INTERVAL '60 days' THEN 'very_stale'
                    WHEN last_scraped < NOW() - INTERVAL '30 days' THEN 'stale'
                    WHEN last_scraped < NOW() - INTERVAL '14 days' THEN 'moderate'
                    ELSE 'fresh'
                END as status,
                COUNT(*) as count
            FROM company_status
            GROUP BY status
        """

        try:
            with Session(self.engine) as session:
                result = session.execute(text(query))
                return {row[0]: row[1] for row in result}
        except Exception as e:
            logger.error(f"Error getting tier counts: {e}", exc_info=True)
            return {}

    def get_estimated_completion(self, scrapes_per_day: int = 30) -> Dict[str, Any]:
        """
        Estimate time to complete scraping all companies.

        Args:
            scrapes_per_day: Expected successful scrapes per day

        Returns:
            Dictionary with completion estimates
        """
        tier_counts = self.get_tier_counts()

        total_to_scrape = (
            tier_counts.get('never_scraped', 0) +
            tier_counts.get('very_stale', 0) +
            tier_counts.get('stale', 0)
        )

        days_to_complete = total_to_scrape / max(1, scrapes_per_day)
        completion_date = datetime.now() + timedelta(days=days_to_complete)

        return {
            'total_companies': sum(tier_counts.values()),
            'to_scrape': total_to_scrape,
            'already_fresh': tier_counts.get('fresh', 0) + tier_counts.get('moderate', 0),
            'estimated_days': round(days_to_complete, 1),
            'estimated_completion': completion_date.strftime('%Y-%m-%d'),
            'scrapes_per_day': scrapes_per_day,
            'tier_breakdown': tier_counts,
        }


# Singleton instance
_priority_queue = None


def get_serp_priority_queue() -> SerpPriorityQueue:
    """Get or create singleton priority queue instance."""
    global _priority_queue
    if _priority_queue is None:
        _priority_queue = SerpPriorityQueue()
    return _priority_queue
