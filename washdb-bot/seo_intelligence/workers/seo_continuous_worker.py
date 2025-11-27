"""
SEO Continuous Worker

Worker that wraps the existing SEO Worker Service functionality.
Runs comprehensive SEO audits on company websites.
"""

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure environment is loaded
load_dotenv(Path(__file__).parent.parent.parent / '.env')

from seo_intelligence.orchestrator.module_worker import BaseModuleWorker, WorkerResult
from runner.logging_setup import get_logger


logger = get_logger("SEOContinuousWorker")


class SEOContinuousWorker(BaseModuleWorker):
    """
    Worker for comprehensive SEO processing.

    Combines multiple SEO checks into one pass:
    - Technical audit
    - Meta tag analysis
    - Content quality
    - Local SEO signals
    """

    def __init__(self, **kwargs):
        super().__init__(name="seo_worker", **kwargs)

        # Database connection - use psycopg2 format
        database_url = os.environ.get('DATABASE_URL', '')
        # Convert psycopg format to standard postgresql format
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

        # Auditor (lazy initialization)
        self._auditor = None

    def _get_auditor(self):
        """Get or create technical auditor."""
        if self._auditor is None:
            try:
                from seo_intelligence.scrapers.technical_auditor import TechnicalAuditor
                self._auditor = TechnicalAuditor(headless=True)
                logger.info("SEO worker auditor initialized")
            except Exception as e:
                logger.error(f"Failed to initialize auditor: {e}")
        return self._auditor

    def get_companies_to_process(
        self,
        limit: int,
        after_id: Optional[int] = None
    ) -> List[int]:
        """
        Get companies for comprehensive SEO processing.

        Selects companies that haven't been fully processed recently.
        """
        session = self.Session()
        try:
            # Get companies without recent comprehensive SEO processing
            # Uses the page_audits table as a proxy for "processed"
            query = text("""
                SELECT c.id
                FROM companies c
                LEFT JOIN page_audits pa ON c.website = pa.url
                    AND pa.audited_at > NOW() - INTERVAL '7 days'
                WHERE c.website IS NOT NULL
                  AND c.active = true
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
        Process comprehensive SEO for a company.

        Runs full SEO analysis including technical audit, meta analysis,
        and local SEO signal detection.
        """
        session = self.Session()
        try:
            # Get company details
            result = session.execute(
                text("""
                    SELECT id, name, website, domain, service_area
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
            service_area = row[4] or ""
            # Parse city/state from service_area if available
            city = ""
            state = ""
            if service_area and ',' in service_area:
                parts = service_area.split(',')
                city = parts[0].strip()
                if len(parts) > 1:
                    state = parts[1].strip()

            if not website:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="Company has no website"
                )

            # Run comprehensive SEO analysis
            try:
                analysis_result = self._run_seo_analysis(
                    company_id=company_id,
                    company_name=company_name,
                    website=website,
                    domain=domain,
                    city=city,
                    state=state
                )

                if analysis_result['success']:
                    return WorkerResult(
                        company_id=company_id,
                        success=True,
                        message=f"SEO analysis complete for {company_name}",
                        data=analysis_result.get('data', {})
                    )
                else:
                    return WorkerResult(
                        company_id=company_id,
                        success=False,
                        error=analysis_result.get('error', 'Unknown error')
                    )

            except Exception as e:
                logger.error(f"SEO analysis error: {e}")
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

    def _run_seo_analysis(
        self,
        company_id: int,
        company_name: str,
        website: str,
        domain: str,
        city: str,
        state: str
    ) -> dict:
        """
        Run comprehensive SEO analysis.

        Returns dict with success flag and analysis results.
        """
        results = {
            'success': False,
            'data': {},
            'error': None
        }

        # Get auditor
        auditor = self._get_auditor()

        # 1. Technical audit
        if auditor:
            try:
                audit_result = auditor.run(url=website)
                if audit_result:
                    results['data']['technical_audit'] = {
                        'overall_score': audit_result.get('overall_score', 0),
                        'issues_count': len(audit_result.get('issues', []))
                    }

                    # Save audit result
                    self._save_audit_result(company_id, website, audit_result)
            except Exception as e:
                logger.warning(f"Technical audit failed: {e}")
                results['data']['technical_audit'] = {'error': str(e)}

        # 2. Simple meta analysis (fallback if auditor unavailable)
        try:
            meta_result = self._simple_meta_check(website)
            results['data']['meta_analysis'] = meta_result
        except Exception as e:
            logger.warning(f"Meta analysis failed: {e}")

        # 3. Local SEO signals
        if city and state:
            try:
                local_result = self._check_local_signals(website, city, state)
                results['data']['local_seo'] = local_result
            except Exception as e:
                logger.warning(f"Local SEO check failed: {e}")

        # Mark as success if we got any results
        if results['data']:
            results['success'] = True

        return results

    def _simple_meta_check(self, website: str) -> dict:
        """Simple meta tag check using requests."""
        import requests
        from bs4 import BeautifulSoup

        try:
            response = requests.get(website, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; SEOBot/1.0)'
            })

            soup = BeautifulSoup(response.text, 'html.parser')

            title = soup.find('title')
            meta_desc = soup.find('meta', attrs={'name': 'description'})

            return {
                'has_title': title is not None,
                'title_length': len(title.text) if title else 0,
                'has_meta_description': meta_desc is not None,
                'meta_description_length': len(meta_desc.get('content', '')) if meta_desc else 0
            }

        except Exception as e:
            return {'error': str(e)}

    def _check_local_signals(self, website: str, city: str, state: str) -> dict:
        """Check for local SEO signals on the page."""
        import requests

        try:
            response = requests.get(website, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; SEOBot/1.0)'
            })

            content = response.text.lower()

            return {
                'has_city_mention': city.lower() in content if city else False,
                'has_state_mention': state.lower() in content if state else False,
                'has_address': any(keyword in content for keyword in ['address', 'location', 'directions']),
                'has_phone': any(keyword in content for keyword in ['phone', 'call us', 'contact'])
            }

        except Exception as e:
            return {'error': str(e)}

    def _save_audit_result(self, company_id: int, url: str, audit_result: dict):
        """Save audit result to database."""
        import json
        session = self.Session()
        try:
            session.execute(
                text("""
                    INSERT INTO page_audits (url, audit_type, overall_score, audited_at, metadata)
                    VALUES (:url, 'seo_continuous', :overall_score, NOW(), :metadata)
                    ON CONFLICT (url) DO UPDATE SET
                        audited_at = NOW(),
                        overall_score = EXCLUDED.overall_score,
                        metadata = EXCLUDED.metadata
                """),
                {
                    'url': url,
                    'overall_score': audit_result.get('overall_score', 0),
                    'metadata': json.dumps({
                        'company_id': company_id,
                        'performance_score': audit_result.get('performance_score', 0),
                        'seo_score': audit_result.get('seo_score', 0),
                        'accessibility_score': audit_result.get('accessibility_score', 0),
                        'security_score': audit_result.get('security_score', 0)
                    })
                }
            )
            session.commit()
        except Exception as e:
            logger.error(f"Error saving audit: {e}")
            session.rollback()
        finally:
            session.close()
