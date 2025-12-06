"""
Keyword Intelligence Worker

Worker for Phase 2 keyword research services:
- Autocomplete scraping for keyword discovery
- Search volume estimation
- Keyword difficulty calculation
- Opportunity analysis and prioritization
- Traffic estimation
- Ranking trends tracking
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


logger = get_logger("KeywordWorker")


class KeywordIntelligenceWorker(BaseModuleWorker):
    """
    Worker for keyword intelligence and research.

    Performs:
    - Keyword discovery via autocomplete
    - Search volume estimation
    - Keyword difficulty analysis
    - Opportunity scoring and prioritization
    - Ranking trend analysis
    - Traffic estimation
    """

    def __init__(self, **kwargs):
        super().__init__(name="keyword_intel", **kwargs)

        # Database connection
        database_url = os.environ.get('DATABASE_URL', '')
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

        # Services (lazy initialization)
        self._keyword_intelligence = None
        self._volume_estimator = None
        self._difficulty_calculator = None
        self._opportunity_analyzer = None
        self._ranking_trends = None
        self._traffic_estimator = None

    def _get_keyword_intelligence(self):
        """Get or create keyword intelligence orchestrator."""
        if self._keyword_intelligence is None:
            try:
                from seo_intelligence.scrapers.keyword_intelligence import get_keyword_intelligence
                self._keyword_intelligence = get_keyword_intelligence()
                logger.info("Keyword intelligence initialized")
            except Exception as e:
                logger.error(f"Failed to initialize keyword intelligence: {e}")
        return self._keyword_intelligence

    def _get_volume_estimator(self):
        """Get or create volume estimator."""
        if self._volume_estimator is None:
            try:
                from seo_intelligence.services.volume_estimator import get_volume_estimator
                self._volume_estimator = get_volume_estimator()
                logger.info("Volume estimator initialized")
            except Exception as e:
                logger.error(f"Failed to initialize volume estimator: {e}")
        return self._volume_estimator

    def _get_difficulty_calculator(self):
        """Get or create difficulty calculator."""
        if self._difficulty_calculator is None:
            try:
                from seo_intelligence.services.difficulty_calculator import get_difficulty_calculator
                self._difficulty_calculator = get_difficulty_calculator()
                logger.info("Difficulty calculator initialized")
            except Exception as e:
                logger.error(f"Failed to initialize difficulty calculator: {e}")
        return self._difficulty_calculator

    def _get_opportunity_analyzer(self):
        """Get or create opportunity analyzer."""
        if self._opportunity_analyzer is None:
            try:
                from seo_intelligence.services.opportunity_analyzer import get_opportunity_analyzer
                self._opportunity_analyzer = get_opportunity_analyzer()
                logger.info("Opportunity analyzer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize opportunity analyzer: {e}")
        return self._opportunity_analyzer

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
        Get companies that need keyword analysis.

        Selects verified companies without recent keyword research.
        """
        session = self.Session()
        try:
            # Get verified companies without recent keyword research
            # Only process verified companies (passed verification or human-labeled as provider)
            verification_clause = self.get_verification_where_clause()
            query = text(f"""
                SELECT c.id
                FROM companies c
                LEFT JOIN keyword_research kr ON c.id = kr.company_id
                    AND kr.analyzed_at > NOW() - INTERVAL '7 days'
                WHERE c.website IS NOT NULL
                  AND c.active = true
                  AND {verification_clause}
                  AND kr.id IS NULL
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
            # Fall back to simple query with verification filter
            try:
                verification_clause = self.get_verification_where_clause()
                query = text(f"""
                    SELECT c.id
                    FROM companies c
                    WHERE c.website IS NOT NULL
                      AND c.active = true
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
                logger.error(f"Fallback query failed: {e2}")
                return []
        finally:
            session.close()

    def process_company(self, company_id: int) -> WorkerResult:
        """
        Process keyword intelligence for a company.

        Discovers keywords, estimates volume/difficulty, finds opportunities.
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

            if not website:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="Company has no website"
                )

            # Generate seed keywords from company name and service area
            seed_keywords = self._generate_seed_keywords(company_name, service_area)

            # Run keyword analysis
            try:
                analysis_result = self._run_keyword_analysis(
                    company_id=company_id,
                    domain=domain,
                    seed_keywords=seed_keywords
                )

                # Save results
                self._save_analysis(session, company_id, analysis_result)

                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"Keyword analysis complete for {company_name}: {analysis_result.get('keywords_found', 0)} keywords discovered",
                    data=analysis_result
                )

            except Exception as e:
                logger.error(f"Keyword analysis error: {e}")
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

    def _generate_seed_keywords(self, company_name: str, service_area: str) -> List[str]:
        """Generate seed keywords from company info."""
        keywords = []

        # Company name variations
        keywords.append(company_name)
        keywords.append(f"{company_name} reviews")

        # Common service-related terms for local businesses
        if service_area:
            city = service_area.split(',')[0].strip() if ',' in service_area else service_area
            keywords.append(f"{city} car wash")
            keywords.append(f"car wash near {city}")
            keywords.append(f"best car wash {city}")
            keywords.append(f"auto detailing {city}")

        # Generic car wash keywords
        keywords.extend([
            "car wash near me",
            "express car wash",
            "full service car wash",
            "touchless car wash",
            "auto detailing",
            "car wash prices"
        ])

        return keywords[:10]  # Limit to 10 seeds

    def _run_keyword_analysis(
        self,
        company_id: int,
        domain: str,
        seed_keywords: List[str]
    ) -> Dict[str, Any]:
        """Run comprehensive keyword analysis."""
        results = {
            'success': True,
            'keywords_found': 0,
            'high_opportunity': 0,
            'top_opportunities': [],
            'ranking_alerts': [],
            'estimated_traffic': 0,
            'details': {}
        }

        all_keywords = set(seed_keywords)

        # 1. Keyword Discovery via Autocomplete
        kw_intel = self._get_keyword_intelligence()
        if kw_intel:
            try:
                for seed in seed_keywords[:3]:  # Limit autocomplete to first 3 seeds
                    analysis = kw_intel.analyze_keyword(seed, domain)
                    if analysis and hasattr(analysis, 'related_keywords'):
                        all_keywords.update(analysis.related_keywords[:10])
                logger.info(f"Discovered {len(all_keywords)} keywords via autocomplete")
            except Exception as e:
                logger.warning(f"Keyword discovery failed: {e}")

        results['keywords_found'] = len(all_keywords)

        # 2. Volume Estimation
        volume_estimator = self._get_volume_estimator()
        keyword_volumes = {}
        if volume_estimator:
            try:
                for kw in list(all_keywords)[:20]:  # Limit to 20 keywords
                    estimate = volume_estimator.estimate_volume(kw)
                    if estimate:
                        keyword_volumes[kw] = {
                            'volume': estimate.estimated_volume,
                            'category': estimate.category.value if hasattr(estimate.category, 'value') else str(estimate.category)
                        }
                logger.info(f"Estimated volume for {len(keyword_volumes)} keywords")
            except Exception as e:
                logger.warning(f"Volume estimation failed: {e}")

        results['details']['volumes'] = keyword_volumes

        # 3. Difficulty Analysis
        difficulty_calc = self._get_difficulty_calculator()
        keyword_difficulties = {}
        if difficulty_calc:
            try:
                for kw in list(all_keywords)[:20]:
                    difficulty = difficulty_calc.calculate_difficulty(kw)
                    if difficulty:
                        keyword_difficulties[kw] = {
                            'score': difficulty.score,
                            'level': difficulty.level.value if hasattr(difficulty.level, 'value') else str(difficulty.level)
                        }
                logger.info(f"Calculated difficulty for {len(keyword_difficulties)} keywords")
            except Exception as e:
                logger.warning(f"Difficulty calculation failed: {e}")

        results['details']['difficulties'] = keyword_difficulties

        # 4. Opportunity Analysis
        opportunity_analyzer = self._get_opportunity_analyzer()
        if opportunity_analyzer:
            try:
                opportunities = []
                for kw in list(all_keywords)[:20]:
                    opp = opportunity_analyzer.analyze_opportunity(
                        keyword=kw,
                        domain=domain,
                        volume=keyword_volumes.get(kw, {}).get('volume', 0),
                        difficulty=keyword_difficulties.get(kw, {}).get('score', 50)
                    )
                    if opp and opp.score > 50:
                        opportunities.append({
                            'keyword': kw,
                            'score': opp.score,
                            'tier': opp.tier.value if hasattr(opp.tier, 'value') else str(opp.tier),
                            'intent': opp.intent.value if hasattr(opp.intent, 'value') else str(opp.intent)
                        })

                # Sort by score and take top 10
                opportunities.sort(key=lambda x: x['score'], reverse=True)
                results['top_opportunities'] = opportunities[:10]
                results['high_opportunity'] = len([o for o in opportunities if o['score'] > 70])
                logger.info(f"Found {len(opportunities)} keyword opportunities")
            except Exception as e:
                logger.warning(f"Opportunity analysis failed: {e}")

        # 5. Ranking Trends
        ranking_trends = self._get_ranking_trends()
        if ranking_trends and domain:
            try:
                trends = ranking_trends.get_domain_trends(domain)
                if trends:
                    results['ranking_alerts'] = [
                        {
                            'keyword': a.keyword,
                            'alert_type': a.alert_type.value if hasattr(a.alert_type, 'value') else str(a.alert_type),
                            'message': a.message
                        }
                        for a in (trends.alerts or [])[:10]
                    ]
                logger.info(f"Retrieved {len(results['ranking_alerts'])} ranking alerts")
            except Exception as e:
                logger.warning(f"Ranking trends failed: {e}")

        # 6. Traffic Estimation
        traffic_estimator = self._get_traffic_estimator()
        if traffic_estimator and domain:
            try:
                traffic = traffic_estimator.estimate_domain_traffic(domain)
                if traffic:
                    results['estimated_traffic'] = traffic.total_traffic
                    results['details']['traffic'] = {
                        'total': traffic.total_traffic,
                        'quality': traffic.quality.value if hasattr(traffic.quality, 'value') else str(traffic.quality)
                    }
                logger.info(f"Estimated traffic: {results['estimated_traffic']}")
            except Exception as e:
                logger.warning(f"Traffic estimation failed: {e}")

        return results

    def _save_analysis(self, session, company_id: int, analysis_result: Dict[str, Any]):
        """Save keyword analysis results to database."""
        try:
            # Try to insert into keyword_research table
            session.execute(
                text("""
                    INSERT INTO keyword_research
                    (company_id, analyzed_at, keywords_found, high_opportunity_count,
                     estimated_traffic, details)
                    VALUES (:company_id, NOW(), :keywords_found, :high_opportunity,
                            :traffic, :details)
                    ON CONFLICT (company_id) DO UPDATE SET
                        analyzed_at = NOW(),
                        keywords_found = EXCLUDED.keywords_found,
                        high_opportunity_count = EXCLUDED.high_opportunity_count,
                        estimated_traffic = EXCLUDED.estimated_traffic,
                        details = EXCLUDED.details
                """),
                {
                    'company_id': company_id,
                    'keywords_found': analysis_result.get('keywords_found', 0),
                    'high_opportunity': analysis_result.get('high_opportunity', 0),
                    'traffic': analysis_result.get('estimated_traffic', 0),
                    'details': json.dumps({
                        'top_opportunities': analysis_result.get('top_opportunities', []),
                        'ranking_alerts': analysis_result.get('ranking_alerts', []),
                        **analysis_result.get('details', {})
                    })
                }
            )
            session.commit()
            logger.info(f"Saved keyword research for company {company_id}")
        except Exception as e:
            logger.warning(f"Could not save to keyword_research table: {e}")
            session.rollback()
            # Fall back to page_audits - use DELETE + INSERT since no unique constraint
            try:
                session.execute(
                    text("DELETE FROM page_audits WHERE url = :url"),
                    {'url': f'keywords://{company_id}'}
                )
                session.execute(
                    text("""
                        INSERT INTO page_audits (url, audit_type, overall_score, audited_at, metadata)
                        VALUES (:url, 'keyword_research', :score, NOW(), :metadata)
                    """),
                    {
                        'url': f'keywords://{company_id}',
                        'score': analysis_result.get('keywords_found', 0),
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
