"""
SERP Worker

Worker for SERP tracking module.
Wraps the SerpScraper to process companies through the orchestrator.

Enhanced with Phase 4 services:
- Ranking trend tracking and alerts
- Traffic estimation based on positions
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


logger = get_logger("SERPWorker")


class SERPWorker(BaseModuleWorker):
    """
    Worker for SERP tracking.

    Tracks Google search rankings for company keywords including:
    - Position tracking
    - Ranking trend analysis with alerts
    - Traffic estimation based on positions
    """

    def __init__(self, **kwargs):
        super().__init__(name="serp", **kwargs)

        # Database connection - use psycopg2 format
        database_url = os.environ.get('DATABASE_URL', '')
        # Convert psycopg format to standard postgresql format
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

        # Scraper and services (lazy initialization)
        self._scraper = None
        self._ranking_trends = None
        self._traffic_estimator = None

    def _get_scraper(self):
        """Get or create SERP scraper."""
        if self._scraper is None:
            try:
                from seo_intelligence.scrapers.serp_scraper import SerpScraper
                self._scraper = SerpScraper(headless=True)
                logger.info("SERP scraper initialized")
            except Exception as e:
                logger.error(f"Failed to initialize SERP scraper: {e}")
        return self._scraper

    def _get_ranking_trends(self):
        """Get or create ranking trends analyzer."""
        if self._ranking_trends is None:
            try:
                from seo_intelligence.services.ranking_trends import get_ranking_trends
                self._ranking_trends = get_ranking_trends()
                logger.info("Ranking trends analyzer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize ranking trends: {e}")
        return self._ranking_trends

    def _get_traffic_estimator(self):
        """Get or create traffic estimator."""
        if self._traffic_estimator is None:
            try:
                from seo_intelligence.services.traffic_estimator import get_traffic_estimator
                self._traffic_estimator = get_traffic_estimator()
                logger.info("Traffic estimator initialized")
            except Exception as e:
                logger.error(f"Failed to initialize traffic estimator: {e}")
        return self._traffic_estimator

    def get_companies_to_process(
        self,
        limit: int,
        after_id: Optional[int] = None
    ) -> List[int]:
        """
        Get companies that need SERP tracking.

        Selects companies with websites that haven't had recent SERP checks.
        """
        session = self.Session()
        try:
            # Get active companies with websites for SERP tracking
            # Simple query - just get companies that need processing
            query = text("""
                SELECT c.id
                FROM companies c
                WHERE c.website IS NOT NULL
                  AND c.active = true
                  AND c.domain IS NOT NULL
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
        Process SERP tracking for a company.

        Searches Google for company-related keywords and tracks positions.
        """
        session = self.Session()
        try:
            # Get company details
            result = session.execute(
                text("SELECT id, name, website, domain FROM companies WHERE id = :id"),
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

            # Get scraper
            scraper = self._get_scraper()
            if not scraper:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="SERP scraper not available"
                )

            # Generate search queries based on company name and domain
            query_list = [
                {"query": company_name, "location": ""},
                {"query": f"{company_name} reviews", "location": ""},
            ]

            # Run comprehensive SERP tracking
            try:
                # Initialize results
                serp_data = {
                    'queries_tracked': 0,
                    'positions': [],
                    'ranking_alerts': [],
                    'estimated_traffic': 0
                }

                # 1. Run SERP scraper
                results = scraper.run(
                    queries=query_list,
                    our_domains=[domain] if domain else None,
                )

                if results:
                    serp_data['queries_tracked'] = len(query_list)
                    # Extract position data from results
                    if isinstance(results, dict):
                        serp_data['positions'] = results.get('positions', [])
                    logger.info(f"SERP tracking complete for {company_name}")

                # 2. Analyze ranking trends
                ranking_trends = self._get_ranking_trends()
                if ranking_trends and domain:
                    try:
                        trends = ranking_trends.get_domain_trends(domain)
                        if trends:
                            serp_data['ranking_alerts'] = [
                                {
                                    'keyword': a.keyword,
                                    'alert_type': a.alert_type.value if hasattr(a.alert_type, 'value') else str(a.alert_type),
                                    'message': a.message,
                                    'old_position': a.old_position,
                                    'new_position': a.new_position
                                }
                                for a in (trends.alerts or [])[:10]
                            ]
                            serp_data['trend_summary'] = {
                                'improving_keywords': trends.improving_count,
                                'declining_keywords': trends.declining_count,
                                'stable_keywords': trends.stable_count,
                                'avg_position_change': trends.avg_position_change
                            }
                            logger.info(f"Ranking trends: {len(serp_data['ranking_alerts'])} alerts")
                    except Exception as e:
                        logger.warning(f"Ranking trends failed: {e}")

                # 3. Estimate traffic
                traffic_estimator = self._get_traffic_estimator()
                if traffic_estimator and domain:
                    try:
                        traffic = traffic_estimator.estimate_domain_traffic(domain)
                        if traffic:
                            serp_data['estimated_traffic'] = traffic.total_traffic
                            serp_data['traffic_details'] = {
                                'total': traffic.total_traffic,
                                'quality': traffic.quality.value if hasattr(traffic.quality, 'value') else str(traffic.quality),
                                'top_keywords': [
                                    {'keyword': kt.keyword, 'traffic': kt.estimated_traffic}
                                    for kt in (traffic.keyword_traffic or [])[:5]
                                ]
                            }
                            logger.info(f"Estimated traffic: {traffic.total_traffic}")
                    except Exception as e:
                        logger.warning(f"Traffic estimation failed: {e}")

                # Save comprehensive SERP data
                self._save_serp_data(session, company_id, domain, serp_data)

                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"SERP tracking complete for {company_name}: {serp_data['queries_tracked']} queries, {len(serp_data['ranking_alerts'])} alerts",
                    data=serp_data
                )

            except Exception as e:
                logger.error(f"SERP tracking error: {e}")
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

    def _save_serp_data(
        self,
        session,
        company_id: int,
        domain: str,
        serp_data: Dict[str, Any]
    ):
        """Save comprehensive SERP data including trends and traffic."""
        try:
            # Try to save to serp_tracking table if it exists
            session.execute(
                text("""
                    INSERT INTO serp_tracking
                    (company_id, domain, tracked_at, queries_tracked,
                     estimated_traffic, ranking_alerts, details)
                    VALUES (:company_id, :domain, NOW(), :queries_tracked,
                            :traffic, :alerts, :details)
                    ON CONFLICT (company_id) DO UPDATE SET
                        tracked_at = NOW(),
                        queries_tracked = EXCLUDED.queries_tracked,
                        estimated_traffic = EXCLUDED.estimated_traffic,
                        ranking_alerts = EXCLUDED.ranking_alerts,
                        details = EXCLUDED.details
                """),
                {
                    'company_id': company_id,
                    'domain': domain,
                    'queries_tracked': serp_data.get('queries_tracked', 0),
                    'traffic': serp_data.get('estimated_traffic', 0),
                    'alerts': json.dumps(serp_data.get('ranking_alerts', [])),
                    'details': json.dumps({
                        'trend_summary': serp_data.get('trend_summary', {}),
                        'traffic_details': serp_data.get('traffic_details', {}),
                        'positions': serp_data.get('positions', [])
                    })
                }
            )
            session.commit()
            logger.info(f"Saved SERP tracking data for company {company_id}")
        except Exception as e:
            logger.warning(f"Could not save to serp_tracking table: {e}")
            session.rollback()
            # Fall back to page_audits - use DELETE + INSERT since no unique constraint
            try:
                # Delete existing entry if any
                session.execute(
                    text("DELETE FROM page_audits WHERE url = :url"),
                    {'url': f'serp://{company_id}/{domain}'}
                )
                # Insert new entry
                session.execute(
                    text("""
                        INSERT INTO page_audits (url, audit_type, overall_score, audited_at, metadata)
                        VALUES (:url, 'serp_tracking', :score, NOW(), :metadata)
                    """),
                    {
                        'url': f'serp://{company_id}/{domain}',
                        'score': serp_data.get('estimated_traffic', 0),
                        'metadata': json.dumps({
                            'company_id': company_id,
                            'domain': domain,
                            **serp_data
                        })
                    }
                )
                session.commit()
            except Exception as e2:
                logger.error(f"Failed to save SERP data: {e2}")
                session.rollback()
