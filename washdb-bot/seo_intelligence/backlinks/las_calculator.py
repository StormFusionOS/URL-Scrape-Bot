"""
Local Authority Score (LAS) calculator.

Computes normalized authority scores (0-100) based on:
- Number of referring domains
- Number of in-body links
- Backlink quality signals
"""
import logging
import math
import os
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from db.models import Backlink, Competitor, ReferringDomain
from ..infrastructure.task_logger import task_logger

logger = logging.getLogger(__name__)


class LASCalculator:
    """
    Calculates Local Authority Score for domains.

    LAS Formula:
    - Base score from number of referring domains (logarithmic)
    - Bonus for in-body link percentage
    - Normalized to 0-100 scale
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize LAS calculator.

        Args:
            database_url: Database URL (defaults to DATABASE_URL env var)
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")

        # Database setup
        self.engine = create_engine(self.database_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def calculate_las(
        self,
        referring_domain_count: int,
        total_backlinks: int,
        in_body_backlinks: int
    ) -> float:
        """
        Calculate Local Authority Score.

        Args:
            referring_domain_count: Number of unique referring domains
            total_backlinks: Total number of backlinks
            in_body_backlinks: Number of in-body backlinks

        Returns:
            LAS score (0-100)
        """
        # Base score from referring domains (logarithmic scale)
        # log10(1) = 0, log10(10) = 1, log10(100) = 2, log10(1000) = 3
        if referring_domain_count == 0:
            return 0.0

        base_score = math.log10(referring_domain_count) * 20  # Max 60 points for 1000 domains

        # Quality bonus from in-body percentage
        in_body_pct = (in_body_backlinks / total_backlinks * 100) if total_backlinks > 0 else 0
        quality_bonus = (in_body_pct / 100) * 40  # Max 40 points for 100% in-body

        # Total score (capped at 100)
        las = min(base_score + quality_bonus, 100.0)

        return round(las, 2)

    def compute_domain_las(self, session, target_domain: str) -> Dict:
        """
        Compute LAS for a specific target domain.

        Args:
            session: SQLAlchemy session
            target_domain: Domain to compute LAS for

        Returns:
            Dict with LAS stats
        """
        try:
            # Count referring domains
            referring_domains = session.query(
                func.count(func.distinct(ReferringDomain.source_domain))
            ).filter(
                ReferringDomain.target_domain == target_domain
            ).scalar() or 0

            # Aggregate backlink stats
            backlink_stats = session.query(
                func.count(Backlink.id).label('total'),
                func.sum(func.case((Backlink.position == 'in-body', 1), else_=0)).label('in_body')
            ).filter(
                Backlink.target_domain == target_domain,
                Backlink.alive == True
            ).first()

            total_backlinks = backlink_stats.total or 0
            in_body_backlinks = backlink_stats.in_body or 0

            # Calculate LAS
            las = self.calculate_las(
                referring_domains,
                total_backlinks,
                in_body_backlinks
            )

            stats = {
                'domain': target_domain,
                'las': las,
                'referring_domains': referring_domains,
                'total_backlinks': total_backlinks,
                'in_body_backlinks': in_body_backlinks,
                'in_body_percentage': (in_body_backlinks / total_backlinks * 100) if total_backlinks > 0 else 0
            }

            logger.info(
                f"LAS for {target_domain}: {las:.2f} "
                f"({referring_domains} domains, {total_backlinks} links)"
            )

            return stats

        except Exception as e:
            logger.error(f"Error computing LAS for {target_domain}: {e}")
            return {}

    def update_competitor_las(self, session, competitor_id: int) -> float:
        """
        Update LAS for a specific competitor.

        Args:
            session: SQLAlchemy session
            competitor_id: Competitor database ID

        Returns:
            Updated LAS score
        """
        try:
            # Get competitor
            competitor = session.query(Competitor).filter(
                Competitor.id == competitor_id
            ).first()

            if not competitor:
                raise ValueError(f"Competitor {competitor_id} not found")

            # Compute LAS
            stats = self.compute_domain_las(session, competitor.domain)

            if stats:
                # Update competitor record
                competitor.las = stats['las']
                session.commit()

                logger.info(f"Updated LAS for {competitor.name}: {stats['las']:.2f}")
                return stats['las']

            return 0.0

        except Exception as e:
            logger.error(f"Error updating LAS for competitor {competitor_id}: {e}")
            session.rollback()
            return 0.0

    def update_all_competitors(self) -> Dict[str, int]:
        """
        Update LAS for all tracked competitors.

        Returns:
            Dict with processing stats
        """
        with task_logger.log_task("las_calculator", "backlinks") as log_id:
            with self.SessionLocal() as session:
                # Get all tracked competitors
                competitors = session.query(Competitor).filter(
                    Competitor.track == True
                ).all()

                logger.info(f"Updating LAS for {len(competitors)} competitors")

                updated = 0
                failed = 0

                for i, competitor in enumerate(competitors, 1):
                    try:
                        las = self.update_competitor_las(session, competitor.id)
                        if las > 0:
                            updated += 1

                        # Update progress
                        task_logger.update_progress(
                            log_id,
                            items_processed=i,
                            items_updated=updated,
                            items_failed=failed
                        )

                    except Exception as e:
                        logger.error(f"Failed to update LAS for competitor {competitor.id}: {e}")
                        failed += 1

                results = {
                    'updated': updated,
                    'failed': failed
                }

                logger.info(
                    f"LAS update complete: {updated} updated, {failed} failed"
                )

                return results

    def get_top_competitors(
        self,
        limit: int = 10,
        track_only: bool = True
    ) -> List[Dict]:
        """
        Get top competitors by LAS.

        Args:
            limit: Maximum results to return (default: 10)
            track_only: Only tracked competitors (default: True)

        Returns:
            List of competitor dicts with LAS scores
        """
        with self.SessionLocal() as session:
            query = session.query(Competitor).filter(
                Competitor.las.isnot(None)
            )

            if track_only:
                query = query.filter(Competitor.track == True)

            competitors = query.order_by(
                Competitor.las.desc()
            ).limit(limit).all()

            results = []
            for comp in competitors:
                results.append({
                    'id': comp.id,
                    'name': comp.name,
                    'domain': comp.domain,
                    'las': comp.las
                })

            return results
