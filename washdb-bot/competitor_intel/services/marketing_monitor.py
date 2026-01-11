"""
Marketing Monitor for Competitor Intelligence

Synthesizes marketing activity across channels:
- Activity scoring and alerts
- Campaign detection
- Marketing strategy analysis
- Competitive positioning
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import text

from competitor_intel.config import MARKETING_CONFIG
from db.database_manager import create_session

logger = logging.getLogger(__name__)


class ActivityLevel(Enum):
    """Marketing activity level classification."""
    DORMANT = "dormant"     # No activity in 90+ days
    LOW = "low"             # Minimal activity
    MODERATE = "moderate"   # Regular activity
    HIGH = "high"           # Active marketing
    AGGRESSIVE = "aggressive"  # Heavy marketing push


@dataclass
class MarketingActivity:
    """Individual marketing activity record."""
    activity_type: str  # blog_post, social_post, ad_campaign, etc.
    platform: str
    description: str
    detected_at: datetime = field(default_factory=datetime.now)
    significance: str = "normal"  # low, normal, high


@dataclass
class MarketingSnapshot:
    """Point-in-time marketing snapshot for a competitor."""
    competitor_id: int
    snapshot_date: datetime
    activity_level: ActivityLevel
    activity_score: int  # 0-100
    recent_activities: List[MarketingActivity] = field(default_factory=list)
    # Channel activity flags
    is_blogging: bool = False
    is_advertising: bool = False
    is_social_active: bool = False
    # Metrics
    blog_velocity: float = 0.0  # posts per month
    ad_spend_indicator: str = "unknown"  # none, low, medium, high
    social_engagement: str = "unknown"


@dataclass
class MarketingAlert:
    """Marketing activity alert."""
    alert_type: str
    severity: str  # low, medium, high
    title: str
    description: str
    competitor_id: int
    detected_at: datetime = field(default_factory=datetime.now)


class MarketingMonitor:
    """
    Monitors and synthesizes competitor marketing activity.

    Aggregates signals from:
    - Blog posts (content marketing)
    - Social media activity
    - Advertising (Google, Facebook)
    - Website changes
    """

    def __init__(self):
        self.alert_thresholds = MARKETING_CONFIG.get("alert_thresholds", {})
        self.scoring_weights = MARKETING_CONFIG.get("scoring_weights", {
            "blog": 15,
            "social": 10,
            "ads": 25,
            "content_changes": 10,
        })

        logger.info("MarketingMonitor initialized")

    def create_snapshot(self, competitor_id: int) -> MarketingSnapshot:
        """
        Create a marketing activity snapshot for a competitor.

        Args:
            competitor_id: The competitor to analyze

        Returns:
            MarketingSnapshot with current state
        """
        now = datetime.now()
        thirty_days = now - timedelta(days=30)
        ninety_days = now - timedelta(days=90)

        # Gather data from all channels
        blog_data = self._get_blog_activity(competitor_id, thirty_days)
        social_data = self._get_social_activity(competitor_id, thirty_days)
        ad_data = self._get_ad_activity(competitor_id, thirty_days)
        content_data = self._get_content_activity(competitor_id, thirty_days)

        # Calculate activity score
        score = self._calculate_activity_score(blog_data, social_data, ad_data, content_data)

        # Determine activity level
        level = self._score_to_level(score)

        # Compile recent activities
        activities = self._compile_activities(blog_data, social_data, ad_data, content_data)

        return MarketingSnapshot(
            competitor_id=competitor_id,
            snapshot_date=now,
            activity_level=level,
            activity_score=score,
            recent_activities=activities[:20],  # Top 20 recent
            is_blogging=blog_data.get("is_active", False),
            is_advertising=ad_data.get("is_active", False),
            is_social_active=social_data.get("is_active", False),
            blog_velocity=blog_data.get("velocity", 0.0),
            ad_spend_indicator=ad_data.get("spend_indicator", "unknown"),
            social_engagement=social_data.get("engagement_level", "unknown"),
        )

    def _get_blog_activity(self, competitor_id: int, since: datetime) -> Dict:
        """Get blog activity metrics."""
        session = create_session()
        try:
            result = session.execute(text("""
                SELECT COUNT(*) as post_count,
                       MAX(published_date) as last_post
                FROM competitor_blog_posts
                WHERE competitor_id = :competitor_id
                  AND published_date >= :since
            """), {
                "competitor_id": competitor_id,
                "since": since,
            }).fetchone()

            post_count = result[0] or 0
            last_post = result[1]

            return {
                "is_active": post_count > 0,
                "post_count": post_count,
                "velocity": post_count / 1.0,  # Per month
                "last_post": last_post,
            }
        finally:
            session.close()

    def _get_social_activity(self, competitor_id: int, since: datetime) -> Dict:
        """Get social media activity metrics."""
        session = create_session()
        try:
            result = session.execute(text("""
                SELECT COUNT(*) as profile_count,
                       SUM(COALESCE(follower_count, 0)) as total_followers,
                       MAX(last_post_date) as last_activity
                FROM competitor_social_profiles
                WHERE competitor_id = :competitor_id AND is_active = true
            """), {"competitor_id": competitor_id}).fetchone()

            profile_count = result[0] or 0
            total_followers = result[1] or 0
            last_activity = result[2]

            # Determine engagement level based on follower count
            if total_followers > 10000:
                engagement = "high"
            elif total_followers > 1000:
                engagement = "medium"
            elif profile_count > 0:
                engagement = "low"
            else:
                engagement = "none"

            return {
                "is_active": profile_count > 0,
                "profile_count": profile_count,
                "total_followers": total_followers,
                "engagement_level": engagement,
                "last_activity": last_activity,
            }
        finally:
            session.close()

    def _get_ad_activity(self, competitor_id: int, since: datetime) -> Dict:
        """Get advertising activity metrics."""
        session = create_session()
        try:
            result = session.execute(text("""
                SELECT COUNT(*) as ad_count,
                       COUNT(DISTINCT platform) as platforms,
                       MAX(first_seen_at) as last_ad
                FROM competitor_ads
                WHERE competitor_id = :competitor_id
                  AND first_seen_at >= :since
                  AND is_active = true
            """), {
                "competitor_id": competitor_id,
                "since": since,
            }).fetchone()

            ad_count = result[0] or 0
            platforms = result[1] or 0
            last_ad = result[2]

            # Estimate spend indicator
            if ad_count > 10:
                spend = "high"
            elif ad_count > 3:
                spend = "medium"
            elif ad_count > 0:
                spend = "low"
            else:
                spend = "none"

            return {
                "is_active": ad_count > 0,
                "ad_count": ad_count,
                "platforms": platforms,
                "spend_indicator": spend,
                "last_ad": last_ad,
            }
        finally:
            session.close()

    def _get_content_activity(self, competitor_id: int, since: datetime) -> Dict:
        """Get content change activity."""
        session = create_session()
        try:
            result = session.execute(text("""
                SELECT COUNT(*) as change_count,
                       AVG(change_percentage) as avg_change
                FROM competitor_content_archive
                WHERE competitor_id = :competitor_id
                  AND captured_at >= :since
                  AND change_detected = true
            """), {
                "competitor_id": competitor_id,
                "since": since,
            }).fetchone()

            change_count = result[0] or 0
            avg_change = result[1] or 0.0

            return {
                "is_active": change_count > 0,
                "change_count": change_count,
                "avg_change_pct": float(avg_change),
            }
        finally:
            session.close()

    def _calculate_activity_score(
        self,
        blog_data: Dict,
        social_data: Dict,
        ad_data: Dict,
        content_data: Dict
    ) -> int:
        """Calculate overall marketing activity score (0-100)."""
        score = 0

        # Blog contribution (up to 25 points)
        if blog_data.get("is_active"):
            velocity = blog_data.get("velocity", 0)
            blog_score = min(25, int(velocity * 10))
            score += blog_score

        # Social contribution (up to 25 points)
        if social_data.get("is_active"):
            engagement = social_data.get("engagement_level", "none")
            social_scores = {"none": 0, "low": 8, "medium": 15, "high": 25}
            score += social_scores.get(engagement, 0)

        # Advertising contribution (up to 35 points)
        if ad_data.get("is_active"):
            spend = ad_data.get("spend_indicator", "none")
            ad_scores = {"none": 0, "low": 12, "medium": 25, "high": 35}
            score += ad_scores.get(spend, 0)

        # Content changes (up to 15 points)
        if content_data.get("is_active"):
            changes = content_data.get("change_count", 0)
            content_score = min(15, changes * 3)
            score += content_score

        return min(100, score)

    def _score_to_level(self, score: int) -> ActivityLevel:
        """Convert activity score to level."""
        if score >= 80:
            return ActivityLevel.AGGRESSIVE
        elif score >= 60:
            return ActivityLevel.HIGH
        elif score >= 35:
            return ActivityLevel.MODERATE
        elif score >= 15:
            return ActivityLevel.LOW
        else:
            return ActivityLevel.DORMANT

    def _compile_activities(
        self,
        blog_data: Dict,
        social_data: Dict,
        ad_data: Dict,
        content_data: Dict
    ) -> List[MarketingActivity]:
        """Compile individual activities from all channels."""
        activities = []

        if blog_data.get("is_active"):
            activities.append(MarketingActivity(
                activity_type="blog_posts",
                platform="website",
                description=f"{blog_data.get('post_count', 0)} blog posts in last 30 days",
            ))

        if ad_data.get("is_active"):
            activities.append(MarketingActivity(
                activity_type="advertising",
                platform="paid",
                description=f"{ad_data.get('ad_count', 0)} ads detected across {ad_data.get('platforms', 0)} platforms",
                significance="high" if ad_data.get("spend_indicator") == "high" else "normal",
            ))

        if social_data.get("is_active"):
            activities.append(MarketingActivity(
                activity_type="social_presence",
                platform="social",
                description=f"{social_data.get('profile_count', 0)} active social profiles",
            ))

        if content_data.get("is_active"):
            activities.append(MarketingActivity(
                activity_type="content_updates",
                platform="website",
                description=f"{content_data.get('change_count', 0)} significant content changes",
            ))

        return activities

    def generate_alerts(self, competitor_id: int, snapshot: MarketingSnapshot) -> List[MarketingAlert]:
        """
        Generate marketing alerts based on snapshot.

        Args:
            competitor_id: The competitor ID
            snapshot: Current marketing snapshot

        Returns:
            List of alerts to raise
        """
        alerts = []

        # Alert on aggressive marketing
        if snapshot.activity_level == ActivityLevel.AGGRESSIVE:
            alerts.append(MarketingAlert(
                alert_type="AGGRESSIVE_MARKETING",
                severity="high",
                title="Competitor Aggressive Marketing Detected",
                description=f"Activity score: {snapshot.activity_score}/100. Multiple channels active.",
                competitor_id=competitor_id,
            ))

        # Alert on new advertising
        if snapshot.is_advertising and snapshot.ad_spend_indicator in ["medium", "high"]:
            alerts.append(MarketingAlert(
                alert_type="COMPETITOR_ADVERTISING",
                severity="medium",
                title="Competitor Running Ads",
                description=f"Detected paid advertising with {snapshot.ad_spend_indicator} spend indicator.",
                competitor_id=competitor_id,
            ))

        # Alert on active blogging
        if snapshot.blog_velocity >= 4:  # 4+ posts per month
            alerts.append(MarketingAlert(
                alert_type="HIGH_CONTENT_VELOCITY",
                severity="medium",
                title="Competitor High Blog Activity",
                description=f"Publishing {snapshot.blog_velocity:.1f} posts per month.",
                competitor_id=competitor_id,
            ))

        return alerts

    def save_snapshot(self, snapshot: MarketingSnapshot):
        """Save marketing snapshot to database."""
        session = create_session()
        try:
            # Update competitor record with latest marketing score
            session.execute(text("""
                UPDATE competitors
                SET marketing_activity_score = :score,
                    marketing_activity_level = :level,
                    last_marketing_check = NOW()
                WHERE id = :competitor_id
            """), {
                "competitor_id": snapshot.competitor_id,
                "score": snapshot.activity_score,
                "level": snapshot.activity_level.value,
            })
            session.commit()
            logger.info(f"Saved marketing snapshot for competitor {snapshot.competitor_id}")
        except Exception as e:
            logger.error(f"Failed to save marketing snapshot: {e}")
            session.rollback()
        finally:
            session.close()


def analyze_marketing_activity(competitor_id: int) -> MarketingSnapshot:
    """
    Convenience function to analyze marketing activity.

    Args:
        competitor_id: The competitor to analyze

    Returns:
        MarketingSnapshot
    """
    monitor = MarketingMonitor()
    return monitor.create_snapshot(competitor_id)
