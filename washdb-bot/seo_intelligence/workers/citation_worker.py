"""
Citation Worker

Worker for citation tracking module.
Wraps the CitationCrawler to process companies through the orchestrator.
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


logger = get_logger("CitationWorker")


class CitationWorker(BaseModuleWorker):
    """
    Worker for citation tracking.

    Checks business directory listings and NAP consistency.
    """

    def __init__(self, **kwargs):
        super().__init__(name="citations", **kwargs)

        # Database connection - use psycopg2 format
        database_url = os.environ.get('DATABASE_URL', '')
        # Convert psycopg format to standard postgresql format
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

        # Scraper (lazy initialization)
        self._crawler = None

    def _get_crawler(self):
        """Get or create citation crawler (SeleniumBase UC version)."""
        if self._crawler is None:
            try:
                # Use SeleniumBase version for better anti-detection on Yelp/BBB/YP
                from seo_intelligence.scrapers.citation_crawler_selenium import CitationCrawlerSelenium
                self._crawler = CitationCrawlerSelenium(headless=True)
                logger.info("Citation crawler initialized (SeleniumBase UC)")
            except Exception as e:
                logger.error(f"Failed to initialize citation crawler: {e}")
        return self._crawler

    def get_companies_to_process(
        self,
        limit: int,
        after_id: Optional[int] = None
    ) -> List[int]:
        """
        Get companies that need citation checking.

        Selects verified companies without recent citation checks.
        """
        session = self.Session()
        try:
            # Get active verified companies for citation checking
            # Only process verified companies (passed verification or human-labeled as provider)
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

        except Exception as e:
            logger.error(f"Error getting companies: {e}")
            return []
        finally:
            session.close()

    def process_company(self, company_id: int) -> WorkerResult:
        """
        Process citation checking for a company.

        Checks major directories for business listings.
        """
        session = self.Session()
        try:
            # Get company details (including new standardization fields)
            result = session.execute(
                text("""
                    SELECT id, name, website, phone, address, service_area,
                           standardized_name, city, state, zip_code
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

            # Extract fields
            original_name = row[1]
            website = row[2]
            phone = row[3] or ""
            address = row[4] or ""
            service_area = row[5] or ""
            standardized_name = row[6]
            city = row[7] or ""
            state = row[8] or ""
            zip_code = row[9] or ""

            # Use standardized_name for searches if available, otherwise original
            company_name = standardized_name if standardized_name else original_name

            # Get crawler
            crawler = self._get_crawler()
            if not crawler:
                return WorkerResult(
                    company_id=company_id,
                    success=False,
                    error="Citation crawler not available"
                )

            # Build business info for CitationCrawler (SeleniumBase version)
            # Uses standardized_name + city/state for better search results
            from seo_intelligence.scrapers.citation_crawler_selenium import BusinessInfo
            business_info = BusinessInfo(
                name=company_name,
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                phone=phone,
                website=website
            )

            # Run citation crawler
            try:
                results = crawler.run(
                    businesses=[business_info]
                )

                citations_found = results.get('citations_found', 0)
                return WorkerResult(
                    company_id=company_id,
                    success=True,
                    message=f"Found {citations_found} citations for {company_name}",
                    data={"citations_found": citations_found}
                )

            except Exception as e:
                logger.error(f"Citation crawling error: {e}")
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
