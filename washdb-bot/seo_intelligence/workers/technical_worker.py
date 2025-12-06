"""
Technical Worker

Worker for technical SEO audits module.
Wraps the TechnicalAuditor to process companies through the orchestrator.

Enhanced with Phase 1 & 4 services:
- Core Web Vitals
- Readability Analysis
- Engagement Analysis
"""

import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure environment is loaded
load_dotenv(Path(__file__).parent.parent.parent / '.env')

from seo_intelligence.orchestrator.module_worker import BaseModuleWorker, WorkerResult
from runner.logging_setup import get_logger


logger = get_logger("TechnicalWorker")


class TechnicalWorker(BaseModuleWorker):
    """
    Worker for technical SEO audits.

    Performs comprehensive technical audits on company websites including:
    - Technical SEO audit
    - Core Web Vitals
    - Readability analysis
    - Engagement analysis
    """

    def __init__(self, **kwargs):
        super().__init__(name="technical", **kwargs)

        # Database connection - use psycopg2 format
        database_url = os.environ.get('DATABASE_URL', '')
        # Convert psycopg format to standard postgresql format
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

        # Auditor and services (lazy initialization)
        self._auditor = None
        self._readability_analyzer = None
        self._engagement_analyzer = None
        self._cwv_service = None

    def _get_auditor(self):
        """Get or create technical auditor."""
        if self._auditor is None:
            try:
                from seo_intelligence.scrapers.technical_auditor import TechnicalAuditor
                self._auditor = TechnicalAuditor(headless=True)
                logger.info("Technical auditor initialized")
            except Exception as e:
                logger.error(f"Failed to initialize technical auditor: {e}")
        return self._auditor

    def _get_readability_analyzer(self):
        """Get or create readability analyzer."""
        if self._readability_analyzer is None:
            try:
                from seo_intelligence.services.readability_analyzer import get_readability_analyzer
                self._readability_analyzer = get_readability_analyzer()
                logger.info("Readability analyzer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize readability analyzer: {e}")
        return self._readability_analyzer

    def _get_engagement_analyzer(self):
        """Get or create engagement analyzer."""
        if self._engagement_analyzer is None:
            try:
                from seo_intelligence.services.engagement_analyzer import get_engagement_analyzer
                self._engagement_analyzer = get_engagement_analyzer()
                logger.info("Engagement analyzer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize engagement analyzer: {e}")
        return self._engagement_analyzer

    def _get_cwv_service(self):
        """Get or create CWV metrics service."""
        if self._cwv_service is None:
            try:
                from seo_intelligence.services.cwv_metrics import get_cwv_metrics_service
                self._cwv_service = get_cwv_metrics_service()
                logger.info("CWV metrics service initialized")
            except Exception as e:
                logger.error(f"Failed to initialize CWV service: {e}")
        return self._cwv_service

    def get_companies_to_process(
        self,
        limit: int,
        after_id: Optional[int] = None
    ) -> List[int]:
        """
        Get companies that need technical audits.

        Selects verified companies without recent page audits.
        """
        session = self.Session()
        try:
            # Get verified companies without recent audits
            # Only process verified companies (passed verification or human-labeled as provider)
            # page_audits uses url field, audited_at for timestamp
            verification_clause = self.get_verification_where_clause()
            query = text(f"""
                SELECT c.id
                FROM companies c
                LEFT JOIN page_audits pa ON c.website = pa.url
                    AND pa.audited_at > NOW() - INTERVAL '7 days'
                WHERE c.website IS NOT NULL
                  AND c.active = true
                  AND {verification_clause}
                  AND pa.audit_id IS NULL
                  AND (:after_id IS NULL OR c.id > :after_id)
                ORDER BY c.id ASC
                LIMIT :limit
            """)

            result = session.execute(query, {
                'limit': limit,
                'after_id': after_id
            })

            return [row[0] for row in result]

        except Exception as e:
            logger.error(f"Error getting companies: {e}")
            return []
        finally:
            session.close()

    def process_company(self, company_id: int) -> WorkerResult:
        """
        Process technical audit for a company.

        Performs comprehensive SEO audit on company website.
        """
        session = self.Session()
        try:
            # Get company details
            result = session.execute(
                text("SELECT id, name, website FROM companies WHERE id = :id"),
                {'id': company_id}
            )
            row = result.fetchone()

            if not row:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="Company not found"
                )

            company_name = row[1]
            website = row[2]

            if not website:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="Company has no website"
                )

            # Get auditor
            auditor = self._get_auditor()
            if not auditor:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="Technical auditor not available"
                )

            # Run comprehensive audit with all services
            try:
                # Initialize results
                audit_data = {
                    'technical_audit': None,
                    'readability': None,
                    'engagement': None,
                    'cwv': None
                }

                # 1. Technical audit
                audit_result = auditor.run(urls=[website])
                if audit_result and audit_result.get('successful', 0) > 0:
                    audit_data['technical_audit'] = audit_result
                    logger.info(f"Technical audit complete for {company_name}")

                # 2. Readability analysis
                readability_analyzer = self._get_readability_analyzer()
                if readability_analyzer:
                    try:
                        readability_result = readability_analyzer.analyze_url(website)
                        if readability_result:
                            audit_data['readability'] = {
                                'flesch_reading_ease': readability_result.flesch_reading_ease,
                                'grade_level': readability_result.grade_level,
                                'reading_time_seconds': readability_result.reading_time_seconds,
                                'word_count': readability_result.word_count
                            }
                            logger.info(f"Readability analysis complete: Grade {readability_result.grade_level}")
                    except Exception as e:
                        logger.warning(f"Readability analysis failed: {e}")

                # 3. Engagement analysis
                engagement_analyzer = self._get_engagement_analyzer()
                if engagement_analyzer:
                    try:
                        engagement_result = engagement_analyzer.analyze_url(website)
                        if engagement_result:
                            audit_data['engagement'] = {
                                'engagement_score': engagement_result.engagement_score,
                                'engagement_level': engagement_result.level.value if hasattr(engagement_result.level, 'value') else str(engagement_result.level),
                                'bounce_risk': engagement_result.signals.bounce_risk if engagement_result.signals else None,
                                'cta_count': engagement_result.signals.cta_count if engagement_result.signals else 0,
                                'has_video': engagement_result.signals.has_video if engagement_result.signals else False,
                                'has_interactive': engagement_result.signals.has_interactive if engagement_result.signals else False
                            }
                            logger.info(f"Engagement analysis complete: Score {engagement_result.engagement_score}")
                    except Exception as e:
                        logger.warning(f"Engagement analysis failed: {e}")

                # 4. CWV scoring
                cwv_service = self._get_cwv_service()
                if cwv_service and audit_result:
                    try:
                        # Extract CWV metrics from audit result if available
                        metrics = audit_result.get('metrics', {})
                        if metrics:
                            cwv_scores = {
                                'lcp_rating': cwv_service.rate_lcp(metrics.get('lcp_ms', 0)).value if metrics.get('lcp_ms') else None,
                                'fid_rating': cwv_service.rate_fid(metrics.get('fid_ms', 0)).value if metrics.get('fid_ms') else None,
                                'cls_rating': cwv_service.rate_cls(metrics.get('cls', 0)).value if metrics.get('cls') else None,
                            }
                            audit_data['cwv'] = cwv_scores
                    except Exception as e:
                        logger.warning(f"CWV scoring failed: {e}")

                # Save comprehensive audit result
                self._save_audit(session, company_id, website, audit_data)

                overall_score = audit_result.get('average_score', 0) if audit_result else 0
                issues_count = (audit_result.get('critical_issues', 0) + audit_result.get('high_issues', 0)) if audit_result else 0

                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"Comprehensive audit complete for {company_name}: Score {overall_score:.0f}/100",
                    data={
                        "overall_score": overall_score,
                        "issues_count": issues_count,
                        "readability_grade": audit_data.get('readability', {}).get('grade_level') if audit_data.get('readability') else None,
                        "engagement_score": audit_data.get('engagement', {}).get('engagement_score') if audit_data.get('engagement') else None
                    }
                )

            except Exception as e:
                logger.error(f"Technical audit error: {e}")
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error=str(e)
                )

        except Exception as e:
            logger.error(f"Error processing company {company_id}: {e}")
            return WorkerResult(
                company_id=company_id,
                success=False,
                error=str(e)
            )
        finally:
            session.close()

    def _save_audit(self, session, company_id: int, url: str, audit_data: Dict[str, Any]):
        """Save comprehensive audit result to database."""
        try:
            # Extract technical audit if present
            tech_audit = audit_data.get('technical_audit', {}) or {}

            # Build comprehensive metadata
            metadata = {
                'company_id': company_id,
                'performance_score': tech_audit.get('performance_score', 0),
                'seo_score': tech_audit.get('seo_score', 0),
                'accessibility_score': tech_audit.get('accessibility_score', 0),
                'security_score': tech_audit.get('security_score', 0),
                'metrics': tech_audit.get('metrics', {}),
                # Phase 1 & 4 enhancements
                'readability': audit_data.get('readability'),
                'engagement': audit_data.get('engagement'),
                'cwv_ratings': audit_data.get('cwv')
            }

            # Insert page audit - matches actual schema
            session.execute(
                text("""
                    INSERT INTO page_audits (url, audit_type, overall_score, audited_at, metadata)
                    VALUES (:url, 'technical', :overall_score, NOW(), :metadata)
                    ON CONFLICT (url) DO UPDATE SET
                        audited_at = NOW(),
                        overall_score = EXCLUDED.overall_score,
                        metadata = EXCLUDED.metadata
                """),
                {
                    'url': url,
                    'overall_score': tech_audit.get('overall_score', 0),
                    'metadata': json.dumps(metadata)
                }
            )
            session.commit()
            logger.info(f"Saved comprehensive audit for {url}")
        except Exception as e:
            logger.error(f"Error saving audit: {e}")
            session.rollback()
