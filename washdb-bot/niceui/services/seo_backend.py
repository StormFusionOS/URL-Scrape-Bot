"""
SEO Backend Service

Provides SEO analysis functions for the NiceGUI dashboard.
Connects to washdb companies as "sources" for SEO intelligence.
"""

import os
import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, field

from sqlalchemy import select, and_, or_, func, text
from sqlalchemy.orm import Session

from db.models import Company
from db.save_discoveries import create_session

# Try to import Competitor model
try:
    from db.models import Competitor
    COMPETITOR_MODEL_AVAILABLE = True
except ImportError:
    COMPETITOR_MODEL_AVAILABLE = False
from runner.logging_setup import get_logger

logger = get_logger("seo_backend")

# Try to import SEO Intelligence modules
try:
    from seo_intelligence.services import (
        get_change_manager,
        get_las_calculator,
        get_task_logger,
    )
    from seo_intelligence.scrapers import (
        get_technical_auditor,
        get_competitor_parser,
    )
    SEO_MODULES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"SEO Intelligence modules not available: {e}")
    SEO_MODULES_AVAILABLE = False


@dataclass
class SEOSource:
    """Represents a company as an SEO source."""
    id: int
    name: str
    website: str
    domain: str
    phone: str = ""
    email: str = ""
    address: str = ""
    source: str = ""
    rating_google: float = None
    rating_yp: float = None
    reviews_google: int = 0
    reviews_yp: int = 0
    created_at: datetime = None
    last_updated: datetime = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or "",
            "website": self.website or "",
            "domain": self.domain or "",
            "phone": self.phone or "",
            "email": self.email or "",
            "address": self.address or "",
            "source": self.source or "",
            "rating_google": self.rating_google,
            "rating_yp": self.rating_yp,
            "reviews_google": self.reviews_google or 0,
            "reviews_yp": self.reviews_yp or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


@dataclass
class AnalysisResult:
    """Result of an SEO analysis."""
    source_id: int
    source_name: str
    analysis_type: str  # audit, las, competitor
    score: float = 0.0
    grade: str = ""
    issues_count: int = 0
    critical_count: int = 0
    recommendations: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "analysis_type": self.analysis_type,
            "score": self.score,
            "grade": self.grade,
            "issues_count": self.issues_count,
            "critical_count": self.critical_count,
            "recommendations": self.recommendations,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


class SEOBackend:
    """
    Backend service for SEO Intelligence integration.

    Provides methods to:
    - Fetch companies as SEO sources
    - Run SEO audits with progress callbacks
    - Calculate LAS scores
    - Propose changes through governance system
    """

    def __init__(self):
        self._analysis_running = False
        self._should_stop = False
        self._current_results: List[AnalysisResult] = []
        logger.info("SEOBackend initialized")

    def _get_local_competitors(
        self,
        search: str = "",
        limit: int = 500,
    ) -> List[SEOSource]:
        """
        Fetch local competitors from competitors table.

        Args:
            search: Search term for name/domain
            limit: Maximum results

        Returns:
            List of SEOSource objects
        """
        try:
            session = create_session()

            # Use raw SQL since Competitor model may not exist
            query = """
                SELECT competitor_id, name, domain, website_url, business_type,
                       location, is_active, discovered_at, last_crawled_at
                FROM competitors
                WHERE is_active = TRUE
            """
            params = {}

            if search:
                query += " AND (name ILIKE :search OR domain ILIKE :search)"
                params["search"] = f"%{search}%"

            query += " ORDER BY competitor_id DESC LIMIT :limit"
            params["limit"] = limit

            result = session.execute(text(query), params)
            rows = result.fetchall()

            sources = []
            for row in rows:
                sources.append(SEOSource(
                    id=row[0],  # competitor_id
                    name=row[1] or row[2],  # name or domain
                    website=row[3] or f"https://{row[2]}",  # website_url or construct from domain
                    domain=row[2],  # domain
                    phone="",
                    email="",
                    address=row[5] or "",  # location
                    source="Local",
                    rating_google=None,
                    rating_yp=None,
                    reviews_google=0,
                    reviews_yp=0,
                    created_at=row[7],  # discovered_at
                    last_updated=row[8],  # last_crawled_at
                ))

            session.close()
            logger.info(f"Fetched {len(sources)} local competitors")
            return sources

        except Exception as e:
            logger.error(f"Error fetching local competitors: {e}")
            return []

    def get_seo_sources(
        self,
        search: str = "",
        source_filter: str = "",
        has_website_only: bool = True,
        limit: int = 500,
    ) -> List[SEOSource]:
        """
        Fetch companies from database as SEO sources.

        Args:
            search: Search term for name/domain
            source_filter: Filter by source (Local, National, or All)
            has_website_only: Only return companies with websites
            limit: Maximum results

        Returns:
            List of SEOSource objects
        """
        # If "Local" selected, fetch from competitors table
        if source_filter == "Local":
            return self._get_local_competitors(search=search, limit=limit)

        try:
            session = create_session()

            # Build query for companies (National sources)
            conditions = [Company.active == True]

            if has_website_only:
                conditions.append(Company.website.isnot(None))
                conditions.append(Company.website != "")

            if search:
                search_pattern = f"%{search}%"
                conditions.append(
                    or_(
                        Company.name.ilike(search_pattern),
                        Company.domain.ilike(search_pattern),
                        Company.website.ilike(search_pattern),
                    )
                )

            stmt = (
                select(Company)
                .where(and_(*conditions))
                .order_by(Company.created_at.desc())
                .limit(limit)
            )

            result = session.execute(stmt)
            companies = result.scalars().all()

            sources = []
            for c in companies:
                sources.append(SEOSource(
                    id=c.id,
                    name=c.name,
                    website=c.website,
                    domain=c.domain,
                    phone=c.phone,
                    email=c.email,
                    address=c.address,
                    source=c.source or "National",
                    rating_google=c.rating_google,
                    rating_yp=c.rating_yp,
                    reviews_google=c.reviews_google,
                    reviews_yp=c.reviews_yp,
                    created_at=c.created_at,
                    last_updated=c.last_updated,
                ))

            session.close()
            logger.info(f"Fetched {len(sources)} SEO sources")
            return sources

        except Exception as e:
            logger.error(f"Error fetching SEO sources: {e}")
            return []

    def get_source_stats(self) -> Dict[str, Any]:
        """Get statistics about available SEO sources."""
        try:
            session = create_session()

            # Total companies with websites (National)
            total_with_website = session.execute(
                select(func.count(Company.id)).where(
                    and_(
                        Company.active == True,
                        Company.website.isnot(None),
                        Company.website != ""
                    )
                )
            ).scalar()

            # Local competitors count
            local_count = 0
            try:
                local_result = session.execute(
                    text("SELECT COUNT(*) FROM competitors WHERE is_active = TRUE")
                )
                local_count = local_result.scalar() or 0
            except Exception:
                pass

            # By source
            by_source = {
                "Local": local_count,
                "National": total_with_website or 0,
            }

            # With ratings
            with_ratings = session.execute(
                select(func.count(Company.id)).where(
                    and_(
                        Company.active == True,
                        or_(
                            Company.rating_google.isnot(None),
                            Company.rating_yp.isnot(None)
                        )
                    )
                )
            ).scalar()

            session.close()

            return {
                "total_with_website": (total_with_website or 0) + local_count,
                "by_source": by_source,
                "with_ratings": with_ratings or 0,
            }

        except Exception as e:
            logger.error(f"Error getting source stats: {e}")
            return {"total_with_website": 0, "by_source": {}, "with_ratings": 0}

    def run_technical_audit(
        self,
        source: SEOSource,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[AnalysisResult]:
        """
        Run technical SEO audit on a source.

        Args:
            source: SEO source to audit
            progress_callback: Callback for progress updates

        Returns:
            AnalysisResult or None
        """
        if not SEO_MODULES_AVAILABLE:
            if progress_callback:
                progress_callback("[ERROR] SEO modules not available")
            return None

        if not source.website:
            if progress_callback:
                progress_callback(f"[SKIP] {source.name} - No website")
            return None

        try:
            if progress_callback:
                progress_callback(f"[START] Auditing {source.name} ({source.website})")

            # Ensure URL has protocol
            url = source.website
            if not url.startswith("http"):
                url = f"https://{url}"

            auditor = get_technical_auditor()
            audit_result = auditor.audit_page(url)

            if progress_callback:
                progress_callback(f"[SCORE] {source.name}: {audit_result.overall_score:.0f}/100")
                if audit_result.critical_issues:
                    progress_callback(f"[WARN] {len(audit_result.critical_issues)} critical issues found")

            result = AnalysisResult(
                source_id=source.id,
                source_name=source.name,
                analysis_type="audit",
                score=audit_result.overall_score,
                grade=self._score_to_grade(audit_result.overall_score),
                issues_count=len(audit_result.issues),
                critical_count=len(audit_result.critical_issues),
                recommendations=[i.recommendation for i in audit_result.issues[:5]],
                details={
                    "seo_score": audit_result.seo_score,
                    "performance_score": audit_result.performance_score,
                    "accessibility_score": audit_result.accessibility_score,
                    "security_score": audit_result.security_score,
                    "metrics": audit_result.metrics,
                },
            )

            self._current_results.append(result)
            return result

        except Exception as e:
            if progress_callback:
                progress_callback(f"[ERROR] {source.name}: {str(e)}")
            logger.error(f"Error auditing {source.name}: {e}")
            return None

    def run_las_calculation(
        self,
        source: SEOSource,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[AnalysisResult]:
        """
        Calculate Local Authority Score for a source.

        Args:
            source: SEO source to analyze
            progress_callback: Callback for progress updates

        Returns:
            AnalysisResult or None
        """
        if not SEO_MODULES_AVAILABLE:
            if progress_callback:
                progress_callback("[ERROR] SEO modules not available")
            return None

        try:
            if progress_callback:
                progress_callback(f"[START] Calculating LAS for {source.name}")

            calculator = get_las_calculator()
            las_result = calculator.calculate(
                business_name=source.name,
                domain=source.domain,
            )

            if progress_callback:
                progress_callback(f"[SCORE] {source.name}: LAS {las_result.las_score:.1f} ({las_result.grade})")

            result = AnalysisResult(
                source_id=source.id,
                source_name=source.name,
                analysis_type="las",
                score=las_result.las_score,
                grade=las_result.grade,
                recommendations=las_result.recommendations,
                details={
                    "citation_score": las_result.components.citation_score,
                    "backlink_score": las_result.components.backlink_score,
                    "review_score": las_result.components.review_score,
                    "completeness_score": las_result.components.completeness_score,
                },
            )

            self._current_results.append(result)
            return result

        except Exception as e:
            if progress_callback:
                progress_callback(f"[ERROR] {source.name}: {str(e)}")
            logger.error(f"Error calculating LAS for {source.name}: {e}")
            return None

    def propose_seo_changes(
        self,
        result: AnalysisResult,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Propose SEO changes based on analysis results.

        Args:
            result: Analysis result to create proposals from
            progress_callback: Callback for progress updates

        Returns:
            bool: Success status
        """
        if not SEO_MODULES_AVAILABLE:
            return False

        try:
            manager = get_change_manager()

            # Create change proposals for recommendations
            for rec in result.recommendations[:3]:
                change_id = manager.propose_change(
                    change_type="seo_recommendation",
                    entity_type="company",
                    entity_id=result.source_id,
                    proposed_value={"recommendation": rec},
                    current_value={"score": result.score},
                    reason=f"SEO {result.analysis_type} recommendation for {result.source_name}",
                    priority="medium" if result.score >= 60 else "high",
                    source="seo_intelligence",
                )

                if progress_callback and change_id:
                    progress_callback(f"[CHANGE] Proposed: {rec[:50]}...")

            return True

        except Exception as e:
            logger.error(f"Error proposing changes: {e}")
            return False

    async def run_batch_analysis(
        self,
        sources: List[SEOSource],
        analysis_type: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> List[AnalysisResult]:
        """
        Run analysis on multiple sources.

        Args:
            sources: List of sources to analyze
            analysis_type: "audit" or "las"
            progress_callback: Callback for progress updates

        Returns:
            List of AnalysisResult
        """
        self._analysis_running = True
        self._should_stop = False
        self._current_results = []

        results = []
        total = len(sources)

        for i, source in enumerate(sources):
            if self._should_stop:
                if progress_callback:
                    progress_callback("[STOPPED] Analysis cancelled by user")
                break

            if progress_callback:
                progress_callback(f"[PROGRESS] {i+1}/{total} - Processing {source.name}")

            if analysis_type == "audit":
                result = self.run_technical_audit(source, progress_callback)
            elif analysis_type == "las":
                result = self.run_las_calculation(source, progress_callback)
            else:
                continue

            if result:
                results.append(result)

            # Small delay between analyses
            await asyncio.sleep(0.5)

        self._analysis_running = False

        if progress_callback:
            progress_callback(f"[COMPLETE] Analyzed {len(results)}/{total} sources")

        return results

    def stop_analysis(self):
        """Stop any running analysis."""
        self._should_stop = True

    def is_running(self) -> bool:
        """Check if analysis is currently running."""
        return self._analysis_running

    def get_current_results(self) -> List[AnalysisResult]:
        """Get results from current/last analysis."""
        return self._current_results

    def clear_results(self):
        """Clear current results."""
        self._current_results = []

    def _score_to_grade(self, score: float) -> str:
        """Convert score to letter grade."""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        return "F"


# Singleton instance
_seo_backend_instance = None


def get_seo_backend() -> SEOBackend:
    """Get or create singleton SEOBackend instance."""
    global _seo_backend_instance
    if _seo_backend_instance is None:
        _seo_backend_instance = SEOBackend()
    return _seo_backend_instance
