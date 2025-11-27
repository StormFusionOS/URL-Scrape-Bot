"""
Backlink Worker

Worker for backlink discovery module.
Wraps the BacklinkCrawler to process companies through the orchestrator.
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


logger = get_logger("BacklinkWorker")


class BacklinkWorker(BaseModuleWorker):
    """
    Worker for backlink discovery.

    Discovers and tracks referring domains for company websites.
    """

    def __init__(self, **kwargs):
        super().__init__(name="backlinks", **kwargs)

        # Database connection - use psycopg2 format
        database_url = os.environ.get('DATABASE_URL', '')
        # Convert psycopg format to standard postgresql format
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

        # Crawler (lazy initialization)
        self._crawler = None

    def _get_crawler(self):
        """Get or create backlink crawler."""
        if self._crawler is None:
            try:
                from seo_intelligence.scrapers.backlink_crawler import BacklinkCrawler
                self._crawler = BacklinkCrawler(headless=True)
                logger.info("Backlink crawler initialized")
            except Exception as e:
                logger.error(f"Failed to initialize backlink crawler: {e}")
        return self._crawler

    def get_companies_to_process(
        self,
        limit: int,
        after_id: Optional[int] = None
    ) -> List[int]:
        """
        Get companies that need backlink discovery.

        Selects companies without recent backlink checks.
        """
        session = self.Session()
        try:
            # Get active companies with domains for backlink discovery
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
        Process backlink discovery for a company.

        Discovers referring domains and tracks backlinks by checking external
        source URLs (profile pages, citations) for links to the company's domain.
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

            if not domain:
                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"No domain for {company_name}, skipping backlink check",
                    data={"backlinks_found": 0, "referring_domains": 0}
                )

            # Get external source URLs to check for backlinks
            # These are profile pages that might link to the company
            source_urls = self._get_external_source_urls(session, company_id, company_name)

            if not source_urls:
                # No external sources to check
                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"Found 0 backlinks from 0 domains for {company_name}",
                    data={"backlinks_found": 0, "referring_domains": 0}
                )

            # Get crawler
            crawler = self._get_crawler()
            if not crawler:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="Backlink crawler not available"
                )

            # Run backlink crawler - check EXTERNAL source URLs for links TO our domain
            try:
                results = crawler.run(
                    source_urls=source_urls,
                    target_domains=[domain]
                )

                backlinks_found = results.get('total_backlinks', 0)
                domains_found = len(set(bl.get('source_domain') for bl in results.get('backlinks', []) if bl.get('source_domain')))

                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"Found {backlinks_found} backlinks from {domains_found} domains for {company_name}",
                    data={
                        "backlinks_found": backlinks_found,
                        "referring_domains": domains_found,
                        "sources_checked": len(source_urls)
                    }
                )

            except Exception as e:
                logger.error(f"Backlink crawling error: {e}")
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

    def _get_external_source_urls(self, session, company_id: int, company_name: str) -> list:
        """
        Get external URLs that might contain backlinks to the company.

        Sources checked:
        1. Profile URLs from business_sources table (Yelp, YP, Google, etc.)
        2. Citation listing URLs from citations table

        Note: This requires external source URLs to be stored in the database.
        Without backlink API integration or citation data, this will return empty.

        Returns list of external URLs to check for backlinks.
        """
        source_urls = []

        try:
            # 1. Get profile URLs from business_sources
            result = session.execute(
                text("""
                    SELECT profile_url FROM business_sources
                    WHERE company_id = :company_id
                    AND profile_url IS NOT NULL
                """),
                {'company_id': company_id}
            )
            for row in result:
                if row[0]:
                    source_urls.append(row[0])

            # 2. Get citation listing URLs (if business_name matches)
            result = session.execute(
                text("""
                    SELECT listing_url FROM citations
                    WHERE business_name ILIKE :name
                    AND listing_url IS NOT NULL
                    AND has_website_link = true
                """),
                {'name': f'%{company_name}%'}
            )
            for row in result:
                if row[0]:
                    source_urls.append(row[0])

        except Exception as e:
            logger.warning(f"Error getting source URLs for company {company_id}: {e}")

        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in source_urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return unique_urls
