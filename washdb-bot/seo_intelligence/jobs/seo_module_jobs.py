"""
SEO Module Jobs.

Implements job classes for each of the 9 SEO modules.
Each job handles both initial scrape and quarterly deep refresh modes.
"""

import json
import logging
import os
import time
import traceback
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import Dict, Optional, Any, Type

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database_manager import get_db_manager

logger = logging.getLogger(__name__)


# Module timeout constants (seconds)
# Updated 2026-01-05 based on actual P95 durations + headroom
# P95 values: tech_audit=132s, core_vitals=77s, backlinks=229s, competitors=118s
# serp=937s, autocomplete=2025s, keyword_intel=1829s
MODULE_TIMEOUTS = {
    'technical_audit': 300,      # 5 minutes (was 3, P95=132s)
    'core_vitals': 180,          # 3 minutes (P95=77s, OK)
    'backlinks': 480,            # 8 minutes (was 5, P95=229s)
    'citations': 300,            # 5 minutes (checks multiple directories)
    'competitors': 300,          # 5 minutes (was 3, P95=118s)
    'serp': 1800,                # 30 minutes (was 10, P95=937s, shared browser soft timeout)
    'autocomplete': 3600,        # 60 minutes (was 10, P95=2025s, shared browser soft timeout)
    'keyword_intel': 3600,       # 60 minutes (was 15, P95=1829s, shared browser soft timeout)
    'competitive_analysis': 300, # 5 minutes
}
DEFAULT_MODULE_TIMEOUT = 300  # 5 minutes default (was 3)

# Modules that use GoogleCoordinator's shared browser - skip ThreadPoolExecutor
# These use soft timeouts checked within their loops instead
GOOGLE_BROWSER_MODULES = {'serp', 'autocomplete', 'keyword_intel'}

# Module name constants
MODULE_TECHNICAL_AUDIT = 'technical_audit'
MODULE_CORE_VITALS = 'core_vitals'
MODULE_BACKLINKS = 'backlinks'
MODULE_CITATIONS = 'citations'
MODULE_COMPETITORS = 'competitors'
MODULE_SERP = 'serp'
MODULE_AUTOCOMPLETE = 'autocomplete'
MODULE_KEYWORD_INTEL = 'keyword_intel'
MODULE_COMPETITIVE_ANALYSIS = 'competitive_analysis'

# Company flag column mapping
MODULE_FLAG_MAP = {
    MODULE_TECHNICAL_AUDIT: 'seo_technical_audit_done',
    MODULE_CORE_VITALS: 'seo_core_vitals_done',
    MODULE_BACKLINKS: 'seo_backlinks_done',
    MODULE_CITATIONS: 'seo_citations_done',
    MODULE_COMPETITORS: 'seo_competitors_done',
    MODULE_SERP: 'seo_serp_done',
    MODULE_AUTOCOMPLETE: 'seo_autocomplete_done',
    MODULE_KEYWORD_INTEL: 'seo_keyword_intel_done',
    MODULE_COMPETITIVE_ANALYSIS: 'seo_competitive_analysis_done',
}


class SEOModuleJob(ABC):
    """
    Base class for SEO module jobs.

    Each module job handles:
    - Initial scrape (first time for a company)
    - Deep refresh (quarterly, expanded scope)
    - Job tracking (logging start, complete, failure)
    - Company flag updates
    """

    def __init__(self, module_name: str, db_manager=None):
        """
        Initialize SEO module job.

        Args:
            module_name: Name of the SEO module
            db_manager: Database manager (optional, will get singleton if not provided)
        """
        self.module_name = module_name
        self.db_manager = db_manager or get_db_manager()
        self.flag_column = MODULE_FLAG_MAP.get(module_name)

    def run_for_company(self, company_id: int, run_type: str = 'initial') -> Dict[str, Any]:
        """
        Run this SEO module for a single company with timeout protection.

        Args:
            company_id: Company ID to process
            run_type: Type of run ('initial', 'quarterly', 'deep_refresh', 'retry')

        Returns:
            Dict with results: {success, records_created, records_updated, error, metadata}
        """
        tracking_id = None
        started_at = datetime.now()
        timeout = MODULE_TIMEOUTS.get(self.module_name, DEFAULT_MODULE_TIMEOUT)

        try:
            # Log job start
            tracking_id = self._log_job_start(company_id, run_type)

            # Get company data
            company = self._get_company(company_id)
            if not company:
                raise ValueError(f"Company {company_id} not found")

            logger.info(f"[{self.module_name}] Starting {run_type} for company {company_id}: {company.get('domain')} (timeout: {timeout}s)")

            # All modules use ThreadPoolExecutor for hard timeout protection
            # Google browser modules also get soft timeout passed for graceful shutdown
            result = self._run_with_timeout(company, run_type, timeout)

            # Log success
            self._log_job_complete(tracking_id, result, started_at)

            # Update company flag
            self._update_company_flag(company_id, True)

            logger.info(f"[{self.module_name}] Completed {run_type} for company {company_id}: {result.get('records_created', 0)} records")

            return {
                'success': True,
                'company_id': company_id,
                'module': self.module_name,
                'run_type': run_type,
                **result
            }

        except FuturesTimeoutError:
            error_msg = f"Module timed out after {timeout} seconds"
            logger.error(f"[{self.module_name}] TIMEOUT for company {company_id}: {error_msg}")

            if tracking_id:
                self._log_job_failed(tracking_id, error_msg, f"TimeoutError: {error_msg}")

            return {
                'success': False,
                'company_id': company_id,
                'module': self.module_name,
                'run_type': run_type,
                'error': error_msg,
                'timed_out': True
            }

        except RuntimeError as e:
            # Thread exhaustion or other runtime errors
            error_msg = str(e)
            import threading
            logger.error(
                f"[{self.module_name}] RUNTIME ERROR for company {company_id}: {error_msg} "
                f"(threads: {threading.active_count()})"
            )

            if tracking_id:
                self._log_job_failed(tracking_id, error_msg, f"RuntimeError: {error_msg}")

            return {
                'success': False,
                'company_id': company_id,
                'module': self.module_name,
                'run_type': run_type,
                'error': error_msg,
                'thread_exhausted': 'thread' in error_msg.lower()
            }

        except Exception as e:
            error_msg = str(e)
            error_tb = traceback.format_exc()
            logger.error(f"[{self.module_name}] Failed for company {company_id}: {error_msg}")

            if tracking_id:
                self._log_job_failed(tracking_id, error_msg, error_tb)

            return {
                'success': False,
                'company_id': company_id,
                'module': self.module_name,
                'run_type': run_type,
                'error': error_msg
            }

    def _run_with_timeout(self, company: Dict, run_type: str, timeout: int) -> Dict[str, Any]:
        """
        Run the module with timeout protection using shared executor.

        Uses shared ThreadPoolExecutor to prevent thread exhaustion from
        creating new executor for each module execution.

        Google browser modules (serp, autocomplete, keyword_intel) receive
        the timeout parameter for internal soft timeout checks, allowing
        graceful shutdown before the hard timeout fires.

        Args:
            company: Company data dict
            run_type: 'initial' or 'deep_refresh'
            timeout: Timeout in seconds

        Returns:
            Result dict from run_initial or run_deep_refresh

        Raises:
            FuturesTimeoutError: If execution exceeds timeout
            RuntimeError: If thread limit is critical
        """
        from seo_intelligence.utils.shared_executor import run_with_timeout

        # Google browser modules accept timeout parameter for soft timeout checks
        # Use lambda wrapper to avoid argument confusion
        if self.module_name in GOOGLE_BROWSER_MODULES:
            if run_type == 'initial':
                return run_with_timeout(
                    lambda: self.run_initial(company, timeout=timeout),
                    timeout
                )
            else:
                return run_with_timeout(
                    lambda: self.run_deep_refresh(company, timeout=timeout),
                    timeout
                )
        else:
            if run_type == 'initial':
                return run_with_timeout(self.run_initial, timeout, company)
            else:
                return run_with_timeout(self.run_deep_refresh, timeout, company)

    @abstractmethod
    def run_initial(self, company: Dict) -> Dict[str, Any]:
        """
        Run initial scrape for a company.

        Args:
            company: Company data dict

        Returns:
            Dict with {records_created, records_updated, metadata}
        """
        pass

    @abstractmethod
    def run_deep_refresh(self, company: Dict) -> Dict[str, Any]:
        """
        Run deep refresh scrape for a company.

        Args:
            company: Company data dict

        Returns:
            Dict with {records_created, records_updated, metadata}
        """
        pass

    def _get_company(self, company_id: int) -> Optional[Dict]:
        """Get company data by ID."""
        with self.db_manager.get_session() as session:
            query = text("""
                SELECT id, name, domain, website, service_area,
                       standardized_name, city, state
                FROM companies
                WHERE id = :company_id
            """)
            result = session.execute(query, {"company_id": company_id})
            row = result.fetchone()
            if row:
                return {
                    'id': row[0],
                    'name': row[1],
                    'domain': row[2],
                    'website': row[3],
                    'service_area': row[4],
                    'standardized_name': row[5],
                    'city': row[6],
                    'state': row[7]
                }
            return None

    def _log_job_start(self, company_id: int, run_type: str) -> int:
        """Log job start and return tracking ID."""
        with self.db_manager.get_session() as session:
            query = text("""
                INSERT INTO seo_job_tracking
                    (company_id, module_name, run_type, status, started_at)
                VALUES
                    (:company_id, :module_name, :run_type, 'running', NOW())
                RETURNING tracking_id
            """)
            result = session.execute(query, {
                "company_id": company_id,
                "module_name": self.module_name,
                "run_type": run_type
            })
            tracking_id = result.fetchone()[0]
            session.commit()
            return tracking_id

    def _log_job_complete(self, tracking_id: int, result: Dict, started_at: datetime):
        """Log job completion."""
        duration = (datetime.now() - started_at).total_seconds()
        with self.db_manager.get_session() as session:
            query = text("""
                UPDATE seo_job_tracking
                SET status = 'completed',
                    completed_at = NOW(),
                    duration_seconds = :duration,
                    records_created = :created,
                    records_updated = :updated,
                    metadata = :metadata
                WHERE tracking_id = :tracking_id
            """)
            session.execute(query, {
                "tracking_id": tracking_id,
                "duration": duration,
                "created": result.get('records_created', 0),
                "updated": result.get('records_updated', 0),
                "metadata": json.dumps(result.get('metadata', {}))
            })
            session.commit()

    def _log_job_failed(self, tracking_id: int, error_msg: str, error_tb: str):
        """Log job failure."""
        with self.db_manager.get_session() as session:
            query = text("""
                UPDATE seo_job_tracking
                SET status = 'failed',
                    completed_at = NOW(),
                    error_message = :error_msg,
                    error_traceback = :error_tb,
                    retry_count = retry_count + 1
                WHERE tracking_id = :tracking_id
            """)
            session.execute(query, {
                "tracking_id": tracking_id,
                "error_msg": error_msg,
                "error_tb": error_tb
            })
            session.commit()

    def _update_company_flag(self, company_id: int, value: bool):
        """Update company SEO module flag."""
        if not self.flag_column:
            return
        with self.db_manager.get_session() as session:
            query = text(f"""
                UPDATE companies
                SET {self.flag_column} = :value
                WHERE id = :company_id
            """)
            session.execute(query, {"company_id": company_id, "value": value})
            session.commit()


class TechnicalAuditJob(SEOModuleJob):
    """Technical Auditor job - analyzes website technical SEO factors."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_TECHNICAL_AUDIT, db_manager)

    def run_initial(self, company: Dict) -> Dict[str, Any]:
        """Run full technical audit."""
        from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium

        website = company.get('website')
        if not website:
            return {'records_created': 0, 'metadata': {'error': 'No website'}}

        auditor = TechnicalAuditorSelenium(headless=False, use_proxy=False)
        result = auditor.audit_page(website)

        # Save audit to database
        audit_id = None
        if result and result.overall_score > 0:
            company_id = company.get('id')
            audit_id = auditor.save_audit_to_db(result, company_id=company_id)

        return {
            'records_created': 1 if audit_id else 0,
            'metadata': {
                'audit_id': audit_id,
                'score': result.overall_score if result else None,
                'issues': len(result.issues) if result else 0
            }
        }

    def run_deep_refresh(self, company: Dict) -> Dict[str, Any]:
        """Same as initial - full re-audit."""
        return self.run_initial(company)


class CoreWebVitalsJob(SEOModuleJob):
    """Core Web Vitals job - measures LCP, FID, CLS."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_CORE_VITALS, db_manager)

    def run_initial(self, company: Dict) -> Dict[str, Any]:
        """Run Core Web Vitals on homepage."""
        from seo_intelligence.scrapers.core_web_vitals_selenium import CoreWebVitalsSelenium

        website = company.get('website')
        if not website:
            return {'records_created': 0, 'metadata': {'error': 'No website'}}

        scraper = CoreWebVitalsSelenium(headless=False, use_proxy=False)
        result = scraper.measure_url(website)

        # Save to database
        record_id = None
        if result and not result.error:
            company_id = company.get('id')
            record_id = scraper.save_to_db(result, company_id=company_id)

        return {
            'records_created': 1 if record_id else 0,
            'metadata': {
                'record_id': record_id,
                'grade': result.grade if result else None,
                'lcp': result.lcp_ms if result else None,
                'score': result.cwv_score if result else None
            }
        }

    def run_deep_refresh(self, company: Dict) -> Dict[str, Any]:
        """Run Core Web Vitals on multiple pages."""
        # For deep refresh, analyze more pages
        from seo_intelligence.scrapers.core_web_vitals_selenium import CoreWebVitalsSelenium
        from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium

        website = company.get('website')
        if not website:
            return {'records_created': 0, 'metadata': {'error': 'No website'}}

        company_id = company.get('id')

        # First, get list of internal pages
        crawler = CompetitorCrawlerSelenium(headless=False, use_proxy=False, max_pages=15)
        crawl_result = crawler.crawl_competitor(company.get('domain') or website)
        pages = crawl_result.get('pages', []) if crawl_result else []

        # Analyze each page
        vitals_scraper = CoreWebVitalsSelenium(headless=False, use_proxy=False)
        records = 0
        for page in pages[:5]:
            try:
                result = vitals_scraper.measure_url(page.get('url', website))
                if result and not result.error:
                    record_id = vitals_scraper.save_to_db(result, company_id=company_id)
                    if record_id:
                        records += 1
                time.sleep(5)  # Rate limit
            except Exception as e:
                logger.warning(f"CWV failed for {page}: {e}")

        return {
            'records_created': records,
            'metadata': {'pages_analyzed': records}
        }


class BacklinksJob(SEOModuleJob):
    """Backlinks job - discovers inbound links."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_BACKLINKS, db_manager)

    def run_initial(self, company: Dict) -> Dict[str, Any]:
        """Run backlink crawl for domain."""
        from seo_intelligence.scrapers.backlink_crawler_selenium import BacklinkCrawlerSelenium

        domain = company.get('domain')
        if not domain:
            return {'records_created': 0, 'metadata': {'error': 'No domain'}}

        crawler = BacklinkCrawlerSelenium(headless=False, use_proxy=False)
        result = crawler.discover_backlinks(domain)

        # discover_backlinks returns List[Dict] directly, not {'backlinks': [...]}
        if isinstance(result, list):
            backlinks = result
        elif isinstance(result, dict):
            backlinks = result.get('backlinks', [])
        else:
            backlinks = []

        return {
            'records_created': len(backlinks),
            'metadata': {'backlinks_found': len(backlinks)}
        }

    def run_deep_refresh(self, company: Dict) -> Dict[str, Any]:
        """Same as initial - full re-crawl."""
        return self.run_initial(company)


class CitationsJob(SEOModuleJob):
    """Citations job - checks directory listings."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_CITATIONS, db_manager)

    def run_initial(self, company: Dict) -> Dict[str, Any]:
        """Check top 8 directories for citations."""
        from seo_intelligence.scrapers.citation_crawler_selenium import CitationCrawlerSelenium, BusinessInfo

        business_name = company.get('standardized_name') or company.get('name')
        if not business_name:
            return {'records_created': 0, 'metadata': {'error': 'No business name'}}

        # Create BusinessInfo object
        business_info = BusinessInfo(
            name=business_name,
            address=company.get('address', ''),
            city=company.get('city', ''),
            state=company.get('state', ''),
            zip_code=company.get('zip', ''),
            phone=company.get('phone', ''),
            website=company.get('website', '') or company.get('domain', '')
        )

        crawler = CitationCrawlerSelenium()
        result = crawler.check_all_directories(business_info)

        # Result is Dict[str, CitationResult]
        citations_found = len(result) if result else 0
        return {
            'records_created': citations_found,
            'metadata': {'citations_found': citations_found, 'directories_checked': 8}
        }

    def run_deep_refresh(self, company: Dict) -> Dict[str, Any]:
        """Check all directories for citations."""
        # Same as initial but we could expand to more directories in future
        return self.run_initial(company)


class CompetitorsJob(SEOModuleJob):
    """Competitors job - crawls competitor pages."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_COMPETITORS, db_manager)

    def run_initial(self, company: Dict) -> Dict[str, Any]:
        """Crawl homepage only."""
        from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium

        domain = company.get('domain')
        website = company.get('website')
        if not domain and not website:
            return {'records_created': 0, 'metadata': {'error': 'No domain or website'}}

        crawler = CompetitorCrawlerSelenium(headless=False, use_proxy=False, max_pages=10)
        result = crawler.crawl_competitor(domain or website)

        pages_crawled = result.get('pages_crawled', 0) if result else 0
        return {
            'records_created': pages_crawled,
            'metadata': {'pages_crawled': pages_crawled}
        }

    def run_deep_refresh(self, company: Dict) -> Dict[str, Any]:
        """Crawl up to 10 internal pages."""
        from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium

        domain = company.get('domain')
        website = company.get('website')
        if not domain and not website:
            return {'records_created': 0, 'metadata': {'error': 'No domain or website'}}

        # Deep refresh crawls more pages (25 vs 10 for initial)
        crawler = CompetitorCrawlerSelenium(headless=False, use_proxy=False, max_pages=25)
        result = crawler.crawl_competitor(domain or website)

        pages_crawled = result.get('pages_crawled', 0) if result else 0
        return {
            'records_created': pages_crawled,
            'metadata': {'pages_crawled': pages_crawled}
        }


class SerpJob(SEOModuleJob):
    """SERP job - tracks keyword rankings."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_SERP, db_manager)

    def _get_company_keywords(self, company_id: int, limit: int = 20) -> list:
        """Get keywords assigned to this company."""
        with self.db_manager.get_session() as session:
            query = text("""
                SELECT keyword_text
                FROM keyword_company_tracking
                WHERE company_id = :company_id
                  AND status = 'tracking'
                ORDER BY assignment_tier ASC, opportunity_score DESC NULLS LAST
                LIMIT :limit
            """)
            result = session.execute(query, {"company_id": company_id, "limit": limit})
            return [row[0] for row in result.fetchall()]

    def run_initial(self, company: Dict, timeout: int = 600) -> Dict[str, Any]:
        """Track top 20 keywords with enterprise SERP system."""
        # Check if SERP is enabled
        if os.getenv('SERP_ENABLED', 'true').lower() == 'false':
            logger.info("SERP module disabled via SERP_ENABLED=false")
            return {'records_created': 0, 'metadata': {'skipped': True, 'reason': 'SERP disabled'}}

        # Use enterprise SERP system based on config
        serp_backend = os.getenv('SERP_BACKEND', 'enterprise')

        keywords = self._get_company_keywords(company.get('id'), limit=20)
        if not keywords:
            return {'records_created': 0, 'metadata': {'error': 'No keywords assigned'}}

        if serp_backend == 'enterprise':
            # Use enterprise SERP system (reliable, slow)
            from seo_intelligence.scrapers.serp_scraper_enterprise import EnterpriseSerpScraper
            scraper = EnterpriseSerpScraper(use_proxy=True)
            logger.info(f"SERP tracking using enterprise system for {len(keywords)} keywords")
        else:
            # Fallback to legacy Selenium scraper
            from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium
            scraper = SerpScraperSelenium(headless=False, use_proxy=True)
            logger.info(f"SERP tracking using legacy Selenium for {len(keywords)} keywords")

        start_time = time.time()
        records = 0
        keywords_processed = 0
        company_id = company.get('id')

        for keyword in keywords:
            # Soft timeout check - stop if we're running out of time
            elapsed = time.time() - start_time
            if elapsed > timeout - 60:  # Leave 60s buffer
                logger.warning(f"SERP soft timeout after {elapsed:.0f}s, processed {keywords_processed}/{len(keywords)} keywords")
                break

            try:
                # Call scrape_serp with appropriate args based on backend
                if serp_backend == 'enterprise':
                    result = scraper.scrape_serp(keyword, company_id=company_id)
                else:
                    # SeleniumBase scraper has different signature
                    result = scraper.scrape_serp(keyword)
                if result:
                    records += 1
                keywords_processed += 1
                # Enterprise system has built-in delays, legacy needs manual delay
                if serp_backend != 'enterprise':
                    time.sleep(20)
            except Exception as e:
                logger.warning(f"SERP failed for '{keyword}': {e}")
                keywords_processed += 1

        return {
            'records_created': records,
            'metadata': {'keywords_checked': keywords_processed, 'results': records}
        }

    def run_deep_refresh(self, company: Dict, timeout: int = 600) -> Dict[str, Any]:
        """Track all assigned keywords with enterprise SERP system."""
        # Check if SERP is enabled
        if os.getenv('SERP_ENABLED', 'true').lower() == 'false':
            logger.info("SERP module disabled via SERP_ENABLED=false")
            return {'records_created': 0, 'metadata': {'skipped': True, 'reason': 'SERP disabled'}}

        # Use enterprise SERP system based on config
        serp_backend = os.getenv('SERP_BACKEND', 'enterprise')

        keywords = self._get_company_keywords(company.get('id'), limit=100)
        if not keywords:
            return {'records_created': 0, 'metadata': {'error': 'No keywords assigned'}}

        if serp_backend == 'enterprise':
            # Use enterprise SERP system (reliable, slow)
            from seo_intelligence.scrapers.serp_scraper_enterprise import EnterpriseSerpScraper
            scraper = EnterpriseSerpScraper(use_proxy=True)
            logger.info(f"SERP deep refresh using enterprise system for {len(keywords)} keywords")
        else:
            # Fallback to legacy Selenium scraper
            from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium
            scraper = SerpScraperSelenium(headless=False, use_proxy=True)
            logger.info(f"SERP deep refresh using legacy Selenium for {len(keywords)} keywords")

        start_time = time.time()
        records = 0
        keywords_processed = 0
        company_id = company.get('id')

        for keyword in keywords:
            # Soft timeout check
            elapsed = time.time() - start_time
            if elapsed > timeout - 60:
                logger.warning(f"SERP deep refresh soft timeout after {elapsed:.0f}s, processed {keywords_processed}/{len(keywords)} keywords")
                break

            try:
                # Call scrape_serp with appropriate args based on backend
                if serp_backend == 'enterprise':
                    result = scraper.scrape_serp(keyword, company_id=company_id)
                else:
                    # SeleniumBase scraper has different signature
                    result = scraper.scrape_serp(keyword)
                if result:
                    records += 1
                keywords_processed += 1
                # Enterprise system has built-in delays, legacy needs manual delay
                if serp_backend != 'enterprise':
                    time.sleep(20)
            except Exception as e:
                logger.warning(f"SERP failed for '{keyword}': {e}")
                keywords_processed += 1

        return {
            'records_created': records,
            'metadata': {'keywords_checked': len(keywords), 'results': records}
        }


class AutocompleteJob(SEOModuleJob):
    """Autocomplete job - discovers keyword suggestions."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_AUTOCOMPLETE, db_manager)

    def run_initial(self, company: Dict, timeout: int = 600) -> Dict[str, Any]:
        """Expand Tier 1+2 seed keywords with shared browser session."""
        from seo_intelligence.scrapers.autocomplete_scraper_selenium import AutocompleteScraperSelenium

        # Get company service type to determine seed keywords
        from seo_intelligence.jobs.keyword_assigner import KeywordAssigner
        assigner = KeywordAssigner(self.db_manager)

        # Get full company data with proper session
        with self.db_manager.get_session() as session:
            company_full = assigner._get_company(session, company.get('id'))
        if not company_full:
            company_full = company

        services = assigner._extract_services(company_full)
        tier1_keywords = assigner._get_tier1_keywords(services)[:5]  # Top 5 seeds

        if not tier1_keywords:
            return {'records_created': 0, 'metadata': {'error': 'No seed keywords'}}

        scraper = AutocompleteScraperSelenium(headless=False, use_proxy=False)
        start_time = time.time()
        total_saved = 0
        total_found = 0
        seeds_processed = 0
        company_id = company.get('id')

        for seed in tier1_keywords:
            # Soft timeout check
            elapsed = time.time() - start_time
            if elapsed > timeout - 60:
                logger.warning(f"Autocomplete soft timeout after {elapsed:.0f}s, processed {seeds_processed}/{len(tier1_keywords)} seeds")
                break

            try:
                # Use shared browser via GoogleCoordinator (no thread pool now)
                suggestions = scraper.expand_keyword(seed, max_expansions=10, use_coordinator=True)
                if suggestions:
                    total_found += len(suggestions)
                    # Save incrementally after each seed to avoid losing data on timeout/crash
                    saved = self._save_suggestions(suggestions, company_id)
                    total_saved += saved
                    logger.info(f"Autocomplete: saved {saved} suggestions for seed '{seed}'")
                seeds_processed += 1
                time.sleep(15)  # Rate limit
            except Exception as e:
                logger.warning(f"Autocomplete failed for '{seed}': {e}")
                seeds_processed += 1

        return {
            'records_created': total_saved,
            'metadata': {'seeds_expanded': seeds_processed, 'suggestions_found': total_found}
        }

    def _save_suggestions(self, suggestions: list, company_id: int) -> int:
        """Save autocomplete suggestions to keyword_suggestions table."""
        if not suggestions:
            return 0

        saved = 0
        with self.db_manager.get_session() as session:
            for suggestion in suggestions:
                try:
                    # Get position from metadata if available
                    position = suggestion.metadata.get('position') if hasattr(suggestion, 'metadata') else None

                    session.execute(text("""
                        INSERT INTO keyword_suggestions
                            (seed_keyword, suggestion_text, source, position, suggestion_type, discovered_at)
                        VALUES
                            (:seed, :text, :source, :position, :type, NOW())
                        ON CONFLICT (seed_keyword, suggestion_text, source)
                        DO UPDATE SET
                            last_seen_at = NOW(),
                            frequency_count = keyword_suggestions.frequency_count + 1
                    """), {
                        'seed': suggestion.seed_keyword,
                        'text': suggestion.keyword,
                        'source': suggestion.source,
                        'position': position,
                        'type': suggestion.suggestion_type
                    })
                    saved += 1
                except Exception as e:
                    logger.debug(f"Error saving suggestion: {e}")

            session.commit()

        logger.info(f"Saved {saved} autocomplete suggestions for company {company_id}")
        return saved

    def run_deep_refresh(self, company: Dict, timeout: int = 600) -> Dict[str, Any]:
        """Re-expand all tier keywords."""
        return self.run_initial(company, timeout=timeout)


class KeywordIntelJob(SEOModuleJob):
    """Keyword Intelligence job - analyzes keyword opportunities."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_KEYWORD_INTEL, db_manager)

    def _get_company_keywords(self, company_id: int, limit: int = 20) -> list:
        """Get keywords assigned to this company."""
        with self.db_manager.get_session() as session:
            query = text("""
                SELECT keyword_text
                FROM keyword_company_tracking
                WHERE company_id = :company_id
                  AND status = 'tracking'
                ORDER BY assignment_tier ASC
                LIMIT :limit
            """)
            result = session.execute(query, {"company_id": company_id, "limit": limit})
            return [row[0] for row in result.fetchall()]

    def run_initial(self, company: Dict, timeout: int = 900) -> Dict[str, Any]:
        """Analyze top 5 keywords with shared browser session (each takes ~3 min)."""
        from seo_intelligence.scrapers.keyword_intelligence_selenium import KeywordIntelligenceSelenium

        keywords = self._get_company_keywords(company.get('id'), limit=5)
        if not keywords:
            return {'records_created': 0, 'metadata': {'error': 'No keywords assigned'}}

        company_id = company.get('id')

        # KeywordIntelligenceSelenium uses GoogleCoordinator internally
        scraper = KeywordIntelligenceSelenium(headless=False, use_proxy=False)
        start_time = time.time()
        analyzed = 0
        keywords_processed = 0
        opportunities = []

        for keyword in keywords:
            # Soft timeout check - leave 120s buffer for cleanup
            elapsed = time.time() - start_time
            if elapsed > timeout - 120:
                logger.warning(f"Keyword intel soft timeout after {elapsed:.0f}s, processed {keywords_processed}/{len(keywords)} keywords")
                break

            try:
                result = scraper.analyze_keyword(keyword)
                if result:
                    analyzed += 1
                    # Collect opportunity for batch save
                    if result.opportunity:
                        opportunities.append(result.opportunity)
                keywords_processed += 1
                time.sleep(10)  # Rate limit
            except Exception as e:
                logger.warning(f"Keyword intel failed for '{keyword}': {e}")
                keywords_processed += 1

        # Save all opportunities to database
        if opportunities:
            try:
                scraper.save_analysis(opportunities, competitor_id=company_id)
                logger.info(f"Saved {len(opportunities)} keyword opportunities for company {company_id}")
            except Exception as e:
                logger.error(f"Failed to save keyword opportunities: {e}")

        return {
            'records_created': len(opportunities),
            'metadata': {'keywords_analyzed': keywords_processed, 'successful': analyzed}
        }

    def run_deep_refresh(self, company: Dict, timeout: int = 900) -> Dict[str, Any]:
        """Analyze more keywords (quarterly refresh) with shared browser."""
        from seo_intelligence.scrapers.keyword_intelligence_selenium import KeywordIntelligenceSelenium

        # Use up to 10 keywords for deep refresh
        keywords = self._get_company_keywords(company.get('id'), limit=10)
        if not keywords:
            return {'records_created': 0, 'metadata': {'error': 'No keywords assigned'}}

        company_id = company.get('id')

        scraper = KeywordIntelligenceSelenium(headless=False, use_proxy=False)
        start_time = time.time()
        analyzed = 0
        keywords_processed = 0
        opportunities = []

        for keyword in keywords:
            # Soft timeout check
            elapsed = time.time() - start_time
            if elapsed > timeout - 120:
                logger.warning(f"Keyword intel deep refresh soft timeout after {elapsed:.0f}s, processed {keywords_processed}/{len(keywords)} keywords")
                break

            try:
                result = scraper.analyze_keyword(keyword)
                if result:
                    analyzed += 1
                    if result.opportunity:
                        opportunities.append(result.opportunity)
                keywords_processed += 1
                time.sleep(10)  # Rate limit
            except Exception as e:
                logger.warning(f"Keyword intel failed for '{keyword}': {e}")
                keywords_processed += 1

        # Save all opportunities to database
        if opportunities:
            try:
                scraper.save_analysis(opportunities, competitor_id=company_id)
                logger.info(f"Saved {len(opportunities)} keyword opportunities for company {company_id}")
            except Exception as e:
                logger.error(f"Failed to save keyword opportunities: {e}")

        return {
            'records_created': len(opportunities),
            'metadata': {'keywords_analyzed': keywords_processed, 'successful': analyzed}
        }


class CompetitiveAnalysisJob(SEOModuleJob):
    """Competitive Analysis job - full competitor comparison."""

    def __init__(self, db_manager=None):
        super().__init__(MODULE_COMPETITIVE_ANALYSIS, db_manager)

    def _get_competitor_domains(self, company_id: int, limit: int = 5) -> list:
        """Get competitor domains from the competitors table."""
        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    SELECT DISTINCT domain FROM competitors
                    WHERE company_id = :company_id
                    LIMIT :limit
                """)
                result = session.execute(query, {"company_id": company_id, "limit": limit})
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.debug(f"Could not get competitor domains: {e}")
            return []

    def _get_seed_keywords(self, company_id: int, limit: int = 20) -> list:
        """Get seed keywords from keyword_company_tracking table."""
        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    SELECT keyword_text FROM keyword_company_tracking
                    WHERE company_id = :company_id
                    ORDER BY assignment_tier, tracking_id
                    LIMIT :limit
                """)
                result = session.execute(query, {"company_id": company_id, "limit": limit})
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.debug(f"Could not get seed keywords: {e}")
            return []

    def run_initial(self, company: Dict) -> Dict[str, Any]:
        """Analyze competitors with keyword gaps."""
        from seo_intelligence.scrapers.competitive_analysis_selenium import CompetitiveAnalysisSelenium

        domain = company.get('domain')
        company_id = company.get('id')
        if not domain:
            return {'records_created': 0, 'metadata': {'error': 'No domain'}}

        # Get competitor domains and seed keywords
        competitor_domains = self._get_competitor_domains(company_id, limit=3)
        seed_keywords = self._get_seed_keywords(company_id, limit=20)

        if not competitor_domains:
            return {'records_created': 0, 'metadata': {'error': 'No competitors found', 'note': 'Run competitors module first'}}

        if not seed_keywords:
            # Use default service keywords if none assigned
            seed_keywords = ['pressure washing', 'window cleaning', 'soft washing']

        scraper = CompetitiveAnalysisSelenium(headless=False, use_proxy=False)

        try:
            result = scraper.analyze_competitors(
                your_domain=domain,
                competitor_domains=competitor_domains,
                seed_keywords=seed_keywords,
                include_backlinks=True,
                max_keywords=50
            )

            # Result is CompetitiveAnalysisResult dataclass
            keyword_gaps = len(result.keyword_gaps) if result else 0
            return {
                'records_created': len(competitor_domains),
                'metadata': {
                    'competitors_analyzed': len(competitor_domains),
                    'keyword_gaps': keyword_gaps,
                    'seed_keywords_used': len(seed_keywords)
                }
            }
        except Exception as e:
            logger.error(f"Competitive analysis failed: {e}")
            return {'records_created': 0, 'metadata': {'error': str(e)}}

    def run_deep_refresh(self, company: Dict) -> Dict[str, Any]:
        """Analyze more competitors with full gaps."""
        from seo_intelligence.scrapers.competitive_analysis_selenium import CompetitiveAnalysisSelenium

        domain = company.get('domain')
        company_id = company.get('id')
        if not domain:
            return {'records_created': 0, 'metadata': {'error': 'No domain'}}

        # Get more competitor domains and keywords for deep refresh
        competitor_domains = self._get_competitor_domains(company_id, limit=5)
        seed_keywords = self._get_seed_keywords(company_id, limit=50)

        if not competitor_domains:
            return {'records_created': 0, 'metadata': {'error': 'No competitors found'}}

        if not seed_keywords:
            seed_keywords = ['pressure washing', 'window cleaning', 'soft washing', 'roof cleaning', 'gutter cleaning']

        scraper = CompetitiveAnalysisSelenium(headless=False, use_proxy=False)

        try:
            result = scraper.analyze_competitors(
                your_domain=domain,
                competitor_domains=competitor_domains,
                seed_keywords=seed_keywords,
                include_backlinks=True,
                max_keywords=100
            )

            keyword_gaps = len(result.keyword_gaps) if result else 0
            return {
                'records_created': len(competitor_domains),
                'metadata': {
                    'competitors_analyzed': len(competitor_domains),
                    'keyword_gaps': keyword_gaps,
                    'seed_keywords_used': len(seed_keywords)
                }
            }
        except Exception as e:
            logger.error(f"Competitive analysis failed: {e}")
            return {'records_created': 0, 'metadata': {'error': str(e)}}


# Factory function to get all job classes
def get_all_job_classes() -> Dict[str, Type[SEOModuleJob]]:
    """Return mapping of module name to job class."""
    return {
        MODULE_TECHNICAL_AUDIT: TechnicalAuditJob,
        MODULE_CORE_VITALS: CoreWebVitalsJob,
        MODULE_BACKLINKS: BacklinksJob,
        MODULE_CITATIONS: CitationsJob,
        MODULE_COMPETITORS: CompetitorsJob,
        MODULE_SERP: SerpJob,
        MODULE_AUTOCOMPLETE: AutocompleteJob,
        MODULE_KEYWORD_INTEL: KeywordIntelJob,
        MODULE_COMPETITIVE_ANALYSIS: CompetitiveAnalysisJob,
    }


# Ordered list of modules for initial scrape (dependencies)
INITIAL_SCRAPE_ORDER = [
    # Technical modules (can run in parallel)
    MODULE_TECHNICAL_AUDIT,
    MODULE_CORE_VITALS,
    MODULE_BACKLINKS,
    MODULE_CITATIONS,  # Re-enabled with enterprise stealth
    MODULE_COMPETITORS,
    # Keyword modules (sequential, rate-limited)
    MODULE_SERP,
    MODULE_AUTOCOMPLETE,
    MODULE_KEYWORD_INTEL,
    # Competitive analysis (depends on previous)
    MODULE_COMPETITIVE_ANALYSIS,
]
