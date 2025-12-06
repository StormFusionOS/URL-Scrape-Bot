"""
Competitive Analysis Worker

Worker for Phase 3 competitive analysis services:
- Keyword gap analysis
- Content gap analysis
- Backlink gap analysis
- Topic clustering
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


logger = get_logger("CompetitiveWorker")


class CompetitiveAnalysisWorker(BaseModuleWorker):
    """
    Worker for competitive analysis.

    Analyzes competitors for:
    - Keyword gaps (keywords they rank for that we don't)
    - Content gaps (topics they cover that we don't)
    - Backlink gaps (sites linking to them but not us)
    - Topic clustering for content strategy
    """

    def __init__(self, **kwargs):
        super().__init__(name="competitive", **kwargs)

        # Database connection
        database_url = os.environ.get('DATABASE_URL', '')
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

        # Services (lazy initialization)
        self._keyword_gap = None
        self._content_gap = None
        self._backlink_gap = None
        self._topic_clusterer = None
        self._competitive_analysis = None

    def _get_keyword_gap_analyzer(self):
        """Get or create keyword gap analyzer."""
        if self._keyword_gap is None:
            try:
                from seo_intelligence.services.keyword_gap_analyzer import get_keyword_gap_analyzer
                self._keyword_gap = get_keyword_gap_analyzer()
                logger.info("Keyword gap analyzer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize keyword gap analyzer: {e}")
        return self._keyword_gap

    def _get_content_gap_analyzer(self):
        """Get or create content gap analyzer."""
        if self._content_gap is None:
            try:
                from seo_intelligence.services.content_gap_analyzer import get_content_gap_analyzer
                self._content_gap = get_content_gap_analyzer()
                logger.info("Content gap analyzer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize content gap analyzer: {e}")
        return self._content_gap

    def _get_backlink_gap_analyzer(self):
        """Get or create backlink gap analyzer."""
        if self._backlink_gap is None:
            try:
                from seo_intelligence.services.backlink_gap_analyzer import get_backlink_gap_analyzer
                self._backlink_gap = get_backlink_gap_analyzer()
                logger.info("Backlink gap analyzer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize backlink gap analyzer: {e}")
        return self._backlink_gap

    def _get_topic_clusterer(self):
        """Get or create topic clusterer."""
        if self._topic_clusterer is None:
            try:
                from seo_intelligence.services.topic_clusterer import get_topic_clusterer
                self._topic_clusterer = get_topic_clusterer()
                logger.info("Topic clusterer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize topic clusterer: {e}")
        return self._topic_clusterer

    def _get_competitive_analysis(self):
        """Get or create competitive analysis orchestrator."""
        if self._competitive_analysis is None:
            try:
                from seo_intelligence.scrapers.competitive_analysis import get_competitive_analysis
                self._competitive_analysis = get_competitive_analysis()
                logger.info("Competitive analysis orchestrator initialized")
            except Exception as e:
                logger.error(f"Failed to initialize competitive analysis: {e}")
        return self._competitive_analysis

    def get_companies_to_process(
        self,
        limit: int,
        after_id: Optional[int] = None
    ) -> List[int]:
        """
        Get companies that need competitive analysis.

        Selects verified companies without recent competitive analysis.
        """
        session = self.Session()
        try:
            # Get verified companies without recent competitive analysis
            # Only process verified companies (passed verification or human-labeled as provider)
            verification_clause = self.get_verification_where_clause()
            query = text(f"""
                SELECT c.id
                FROM companies c
                LEFT JOIN competitive_analysis ca ON c.id = ca.company_id
                    AND ca.analyzed_at > NOW() - INTERVAL '14 days'
                WHERE c.website IS NOT NULL
                  AND c.active = true
                  AND c.domain IS NOT NULL
                  AND {verification_clause}
                  AND ca.id IS NULL
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
            # Fall back to simple query with verification filter if competitive_analysis table doesn't exist
            try:
                verification_clause = self.get_verification_where_clause()
                query = text(f"""
                    SELECT c.id
                    FROM companies c
                    WHERE c.website IS NOT NULL
                      AND c.active = true
                      AND c.domain IS NOT NULL
                      AND {verification_clause}
                      AND (:after_id IS NULL OR c.id > :after_id)
                    ORDER BY c.id ASC
                    LIMIT :limit
                """)
                result = session.execute(query, {
                    'limit': limit,
                    'after_id': after_id
                })
                return [row[0] for row in result]
            except Exception as e2:
                logger.error(f"Fallback query also failed: {e2}")
                return []
        finally:
            session.close()

    def process_company(self, company_id: int) -> WorkerResult:
        """
        Process competitive analysis for a company.

        Analyzes competitors to find keyword, content, and backlink gaps.
        """
        session = self.Session()
        try:
            # Get company details
            result = session.execute(
                text("""
                    SELECT id, name, website, domain
                    FROM companies WHERE id = :id
                """),
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
            domain = row[3]

            if not website or not domain:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="Company has no website or domain"
                )

            # Get competitors for this company
            competitors = self._get_competitors(session, company_id, domain)

            if not competitors:
                logger.info(f"No competitors found for company {company_id}, skipping analysis")
                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"No competitors found for {company_name}",
                    data={"status": "no_competitors"}
                )

            # Run competitive analysis
            try:
                analysis_result = self._run_competitive_analysis(
                    company_id=company_id,
                    domain=domain,
                    competitors=competitors
                )

                # Save results
                self._save_analysis(session, company_id, analysis_result)

                gaps_found = (
                    analysis_result.get('keyword_gaps', 0) +
                    analysis_result.get('content_gaps', 0) +
                    analysis_result.get('backlink_gaps', 0)
                )

                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"Competitive analysis complete for {company_name}: {gaps_found} gaps found",
                    data=analysis_result
                )

            except Exception as e:
                logger.error(f"Competitive analysis error: {e}")
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

    def _get_competitors(self, session, company_id: int, domain: str) -> List[str]:
        """Get competitor domains for a company."""
        try:
            # Try to get from competitor_profiles table
            result = session.execute(
                text("""
                    SELECT domain FROM competitor_profiles
                    WHERE target_company_id = :company_id
                    AND domain != :our_domain
                    LIMIT 5
                """),
                {'company_id': company_id, 'our_domain': domain}
            )
            competitors = [row[0] for row in result if row[0]]

            if competitors:
                return competitors

        except Exception as e:
            logger.debug(f"No competitor_profiles table or error: {e}")

        try:
            # Fall back to serp_results - find domains ranking for same keywords
            result = session.execute(
                text("""
                    SELECT DISTINCT sr2.domain
                    FROM serp_results sr1
                    JOIN serp_results sr2 ON sr1.keyword = sr2.keyword
                    WHERE sr1.domain = :our_domain
                      AND sr2.domain != :our_domain
                      AND sr2.position <= 20
                    ORDER BY COUNT(*) DESC
                    LIMIT 5
                """),
                {'our_domain': domain}
            )
            competitors = [row[0] for row in result if row[0]]

            if competitors:
                return competitors

        except Exception as e:
            logger.debug(f"No serp_results competitors found: {e}")

        return []

    def _run_competitive_analysis(
        self,
        company_id: int,
        domain: str,
        competitors: List[str]
    ) -> Dict[str, Any]:
        """Run comprehensive competitive analysis."""
        results = {
            'success': True,
            'keyword_gaps': 0,
            'content_gaps': 0,
            'backlink_gaps': 0,
            'topic_clusters': 0,
            'details': {}
        }

        # 1. Keyword Gap Analysis
        keyword_analyzer = self._get_keyword_gap_analyzer()
        if keyword_analyzer:
            try:
                gaps = keyword_analyzer.find_keyword_gaps(domain, competitors)
                results['keyword_gaps'] = len(gaps)
                results['details']['keyword_gaps'] = [
                    {
                        'keyword': g.keyword,
                        'category': g.category.value if hasattr(g.category, 'value') else str(g.category),
                        'competitor_best_position': g.competitor_best_position,
                        'opportunity_score': g.opportunity_score
                    }
                    for g in gaps[:20]  # Top 20
                ]
                logger.info(f"Found {len(gaps)} keyword gaps")
            except Exception as e:
                logger.warning(f"Keyword gap analysis failed: {e}")
                results['details']['keyword_gaps_error'] = str(e)

        # 2. Content Gap Analysis
        content_analyzer = self._get_content_gap_analyzer()
        if content_analyzer:
            try:
                gaps = content_analyzer.find_content_gaps(domain, competitors)
                results['content_gaps'] = len(gaps)
                results['details']['content_gaps'] = [
                    {
                        'topic': g.topic,
                        'gap_type': g.gap_type.value if hasattr(g.gap_type, 'value') else str(g.gap_type),
                        'priority_score': g.priority_score,
                        'competitor_examples': g.competitor_examples[:3]
                    }
                    for g in gaps[:15]  # Top 15
                ]
                logger.info(f"Found {len(gaps)} content gaps")
            except Exception as e:
                logger.warning(f"Content gap analysis failed: {e}")
                results['details']['content_gaps_error'] = str(e)

        # 3. Backlink Gap Analysis
        backlink_analyzer = self._get_backlink_gap_analyzer()
        if backlink_analyzer:
            try:
                opportunities = backlink_analyzer.find_backlink_gaps(domain, competitors)
                results['backlink_gaps'] = len(opportunities)
                results['details']['backlink_gaps'] = [
                    {
                        'domain': o.source_domain,
                        'link_type': o.link_type.value if hasattr(o.link_type, 'value') else str(o.link_type),
                        'domain_authority': o.domain_authority,
                        'opportunity_score': o.opportunity_score
                    }
                    for o in opportunities[:20]  # Top 20
                ]
                logger.info(f"Found {len(opportunities)} backlink opportunities")
            except Exception as e:
                logger.warning(f"Backlink gap analysis failed: {e}")
                results['details']['backlink_gaps_error'] = str(e)

        # 4. Topic Clustering
        topic_clusterer = self._get_topic_clusterer()
        if topic_clusterer:
            try:
                # Collect all keywords from gaps for clustering
                keywords = []
                for gap in results['details'].get('keyword_gaps', []):
                    keywords.append(gap['keyword'])

                if keywords:
                    clusters = topic_clusterer.cluster_keywords(keywords)
                    results['topic_clusters'] = len(clusters)
                    results['details']['topic_clusters'] = [
                        {
                            'name': c.name,
                            'keywords': c.keywords[:10],
                            'total_volume': c.total_volume
                        }
                        for c in clusters[:10]  # Top 10 clusters
                    ]
                    logger.info(f"Created {len(clusters)} topic clusters")
            except Exception as e:
                logger.warning(f"Topic clustering failed: {e}")
                results['details']['topic_clusters_error'] = str(e)

        return results

    def _save_analysis(self, session, company_id: int, analysis_result: Dict[str, Any]):
        """Save competitive analysis results to database."""
        try:
            # Try to insert into competitive_analysis table
            session.execute(
                text("""
                    INSERT INTO competitive_analysis
                    (company_id, analyzed_at, keyword_gaps, content_gaps, backlink_gaps, details)
                    VALUES (:company_id, NOW(), :keyword_gaps, :content_gaps, :backlink_gaps, :details)
                    ON CONFLICT (company_id) DO UPDATE SET
                        analyzed_at = NOW(),
                        keyword_gaps = EXCLUDED.keyword_gaps,
                        content_gaps = EXCLUDED.content_gaps,
                        backlink_gaps = EXCLUDED.backlink_gaps,
                        details = EXCLUDED.details
                """),
                {
                    'company_id': company_id,
                    'keyword_gaps': analysis_result.get('keyword_gaps', 0),
                    'content_gaps': analysis_result.get('content_gaps', 0),
                    'backlink_gaps': analysis_result.get('backlink_gaps', 0),
                    'details': json.dumps(analysis_result.get('details', {}))
                }
            )
            session.commit()
            logger.info(f"Saved competitive analysis for company {company_id}")
        except Exception as e:
            logger.warning(f"Could not save to competitive_analysis table: {e}")
            session.rollback()
            # Try alternative - save to page_audits using DELETE + INSERT
            try:
                session.execute(
                    text("DELETE FROM page_audits WHERE url = :url"),
                    {'url': f'competitive://{company_id}'}
                )
                session.execute(
                    text("""
                        INSERT INTO page_audits (url, audit_type, overall_score, audited_at, metadata)
                        VALUES (:url, 'competitive_analysis', :score, NOW(), :metadata)
                    """),
                    {
                        'url': f'competitive://{company_id}',
                        'score': analysis_result.get('keyword_gaps', 0) +
                                 analysis_result.get('content_gaps', 0) +
                                 analysis_result.get('backlink_gaps', 0),
                        'metadata': json.dumps({
                            'company_id': company_id,
                            **analysis_result
                        })
                    }
                )
                session.commit()
            except Exception as e2:
                logger.error(f"Failed to save analysis results: {e2}")
                session.rollback()
