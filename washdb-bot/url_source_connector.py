"""
URL Source Connector Module

This module provides integration between the SEO Scraper and the URL Scraper's database.
It allows the SEO scraper to pull URLs from the washbot_db (URL scraper database)
and create crawl targets from them.

Key Features:
- Connect to washbot_db database
- Pull URLs from companies table
- Sync URLs to SEO scraper's crawl_targets table
- Track sync status and avoid duplicates
- Support for filtering by various criteria
"""

import sys
import os
import psycopg2
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from structured_logging import get_logger
from config.read_properties import ReadConfig


class URLSourceConnector:
    """
    Manages connection and synchronization between URL scraper database and SEO scraper.

    This class pulls URLs from the washbot_db.companies table and creates
    crawl targets in the SEO scraper's database.
    """

    def __init__(self, logger=None):
        """
        Initialize the URL source connector.

        Args:
            logger: Logger instance
        """
        if not logger:
            logger = get_logger('url_source_connector')
        self.logger = logger

        # URL Scraper Database (washbot_db) - Read from config
        self.source_host = ReadConfig.get_washdb_host()
        self.source_dbname = ReadConfig.get_washdb_name()
        self.source_user = ReadConfig.get_washdb_user()
        self.source_password = ReadConfig.get_washdb_password()
        self.source_port = int(ReadConfig.get_washdb_port())

        # SEO Scraper Database (scraper) - Read from config
        self.target_host = ReadConfig.get_database_host()
        self.target_dbname = ReadConfig.get_database_name()
        self.target_user = ReadConfig.get_database_user()
        self.target_password = ReadConfig.get_database_password()
        self.target_port = int(ReadConfig.get_database_port())

        self.logger.info("URLSourceConnector initialized with config from config.ini")

    def _get_source_connection(self):
        """Get connection to URL scraper database (washbot_db)."""
        return psycopg2.connect(
            host=self.source_host,
            dbname=self.source_dbname,
            user=self.source_user,
            password=self.source_password,
            port=self.source_port
        )

    def _get_target_connection(self):
        """Get connection to SEO scraper database (scraper)."""
        return psycopg2.connect(
            host=self.target_host,
            dbname=self.target_dbname,
            user=self.target_user,
            password=self.target_password,
            port=self.target_port
        )

    def _log_sync_operation(
        self,
        washbot_company_id: int,
        company_name: str,
        website_url: str,
        domain: str,
        sync_status: str,
        error_message: str = None,
        source: str = None,
        confidence_score: float = None,
        data_completeness: float = None,
        created_target_id: int = None,
        batch_id: str = None,
        batch_size: int = None
    ) -> bool:
        """
        Log a sync operation to the url_sync_history table.

        Args:
            washbot_company_id: ID from washbot_db.companies
            company_name: Company name
            website_url: Website URL
            domain: Extracted domain
            sync_status: 'success', 'failed', or 'skipped'
            error_message: Error message if failed
            source: Source of the URL (e.g., 'YP', 'HA')
            confidence_score: Confidence score from washbot_db
            data_completeness: Data completeness from washbot_db
            created_target_id: ID of created crawl target/job
            batch_id: UUID for batch tracking
            batch_size: Size of the batch

        Returns:
            bool: True if logged successfully, False otherwise
        """
        try:
            conn = self._get_target_connection()
            cursor = conn.cursor()

            insert_query = """
                INSERT INTO public.url_sync_history (
                    washbot_company_id,
                    company_name,
                    website_url,
                    domain,
                    sync_status,
                    error_message,
                    source,
                    confidence_score,
                    data_completeness,
                    created_target_id,
                    batch_id,
                    batch_size
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (washbot_company_id, website_url) DO UPDATE SET
                    synced_at = CURRENT_TIMESTAMP,
                    sync_status = EXCLUDED.sync_status,
                    error_message = EXCLUDED.error_message,
                    created_target_id = COALESCE(EXCLUDED.created_target_id, url_sync_history.created_target_id)
            """

            cursor.execute(
                insert_query,
                (
                    washbot_company_id,
                    company_name,
                    website_url,
                    domain,
                    sync_status,
                    error_message,
                    source,
                    confidence_score,
                    data_completeness,
                    created_target_id,
                    batch_id,
                    batch_size
                )
            )

            conn.commit()
            cursor.close()
            conn.close()

            return True

        except Exception as e:
            self.logger.error(f"Error logging sync operation: {str(e)}")
            return False

    def get_companies_from_source(
        self,
        limit: int = 100,
        offset: int = 0,
        min_confidence_score: float = None,
        source_filter: str = None,
        exclude_synced: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Fetch companies/URLs from the washbot_db database.

        Args:
            limit: Maximum number of URLs to fetch
            offset: Number of records to skip
            min_confidence_score: Minimum confidence score filter
            source_filter: Filter by source (e.g., 'YP', 'HA')
            exclude_synced: Whether to exclude already synced URLs

        Returns:
            List of company dictionaries with URL and metadata
        """
        try:
            conn = self._get_source_connection()
            cursor = conn.cursor()

            # Build query with filters
            query = """
                SELECT
                    id,
                    name,
                    website,
                    domain,
                    phone,
                    email,
                    services,
                    service_area,
                    address,
                    source,
                    rating_yp,
                    rating_google,
                    rating_ha,
                    reviews_google,
                    reviews_yp,
                    reviews_ha,
                    confidence_score,
                    data_completeness,
                    created_at
                FROM companies
                WHERE website IS NOT NULL
            """

            params = []

            if min_confidence_score is not None and min_confidence_score > 0:
                query += " AND confidence_score >= %s"
                params.append(min_confidence_score)

            if source_filter:
                query += " AND source = %s"
                params.append(source_filter)

            # TODO: Track synced URLs in a separate table to exclude them
            # For now, we'll sync all

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            companies = []
            for row in rows:
                companies.append({
                    'id': row[0],
                    'name': row[1],
                    'website': row[2],
                    'domain': row[3],
                    'phone': row[4],
                    'email': row[5],
                    'services': row[6],
                    'service_area': row[7],
                    'address': row[8],
                    'source': row[9],
                    'rating_yp': row[10],
                    'rating_google': row[11],
                    'rating_ha': row[12],
                    'reviews_google': row[13],
                    'reviews_yp': row[14],
                    'reviews_ha': row[15],
                    'confidence_score': row[16],
                    'data_completeness': row[17],
                    'created_at': row[18]
                })

            cursor.close()
            conn.close()

            self.logger.info(f"Fetched {len(companies)} companies from washbot_db")
            return companies

        except Exception as e:
            self.logger.error(f"Error fetching companies from source: {str(e)}")
            return []

    def create_crawl_target(
        self,
        url: str,
        priority: int = 5,
        source_metadata: Dict[str, Any] = None
    ) -> bool:
        """
        Create a crawl target in the SEO scraper database.

        Args:
            url: URL to crawl
            priority: Crawl priority (1-10, higher = more important)
            source_metadata: Metadata from source company record

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            conn = self._get_target_connection()
            cursor = conn.cursor()

            # Check if target already exists
            cursor.execute(
                "SELECT target_id FROM crawl_targets WHERE url = %s",
                (url,)
            )
            existing = cursor.fetchone()

            if existing:
                self.logger.debug(f"Crawl target already exists for {url}")
                cursor.close()
                conn.close()
                return True

            # Extract domain from URL
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc

            # Insert new crawl target
            insert_query = """
                INSERT INTO crawl_targets (
                    url,
                    domain,
                    priority,
                    status,
                    metadata
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING target_id
            """

            metadata_json = None
            if source_metadata:
                import json
                source_metadata['source'] = 'url_scraper_db'
                metadata_json = json.dumps(source_metadata)

            cursor.execute(
                insert_query,
                (
                    url,
                    domain,
                    priority,
                    'pending',
                    metadata_json
                )
            )

            target_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            conn.close()

            self.logger.info(f"Created crawl target {target_id} for {url}")
            return True

        except Exception as e:
            self.logger.error(f"Error creating crawl target for {url}: {str(e)}")
            return False

    def sync_urls_to_crawler(
        self,
        batch_size: int = 100,
        min_confidence: float = 50.0,
        priority: int = 5
    ) -> Dict[str, int]:
        """
        Sync URLs from washbot_db to SEO scraper's crawl_targets.

        Args:
            batch_size: Number of URLs to sync at once
            min_confidence: Minimum confidence score to sync
            priority: Priority to assign to synced targets

        Returns:
            dict: Statistics about the sync operation
        """
        stats = {
            'fetched': 0,
            'created': 0,
            'skipped': 0,
            'errors': 0
        }

        # Generate batch ID for tracking
        batch_id = str(uuid.uuid4())

        try:
            # Fetch companies from source
            companies = self.get_companies_from_source(
                limit=batch_size,
                min_confidence_score=min_confidence
            )
            stats['fetched'] = len(companies)

            self.logger.info(f"Starting sync batch {batch_id} with {len(companies)} companies")

            # Create crawl targets
            for company in companies:
                source_metadata = {
                    'company_id': company['id'],
                    'name': company['name'],
                    'domain': company['domain'],
                    'source': company['source'],
                    'confidence_score': company['confidence_score'],
                    'data_completeness': company['data_completeness']
                }

                success = self.create_crawl_target(
                    url=company['website'],
                    priority=priority,
                    source_metadata=source_metadata
                )

                # Log the sync operation
                sync_status = 'success' if success else 'failed'
                error_msg = None if success else "Failed to create crawl target"

                self._log_sync_operation(
                    washbot_company_id=company['id'],
                    company_name=company['name'],
                    website_url=company['website'],
                    domain=company['domain'],
                    sync_status=sync_status,
                    error_message=error_msg,
                    source=company['source'],
                    confidence_score=company['confidence_score'],
                    data_completeness=company['data_completeness'],
                    created_target_id=None,  # We don't track target_id in current implementation
                    batch_id=batch_id,
                    batch_size=batch_size
                )

                if success:
                    stats['created'] += 1
                else:
                    stats['errors'] += 1

            stats['skipped'] = stats['fetched'] - stats['created'] - stats['errors']

            self.logger.info(
                f"Sync batch {batch_id} complete: {stats['created']} created, "
                f"{stats['skipped']} skipped, {stats['errors']} errors"
            )

            return stats

        except Exception as e:
            self.logger.error(f"Error during URL sync (batch {batch_id}): {str(e)}")
            stats['errors'] += 1
            return stats

    def get_source_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get statistics about the URL source database.

        Returns:
            dict: Statistics about companies in washbot_db
        """
        try:
            conn = self._get_source_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total_companies,
                    COUNT(DISTINCT domain) as unique_domains,
                    COUNT(CASE WHEN source = 'YP' THEN 1 END) as yp_sources,
                    COUNT(CASE WHEN source = 'HA' THEN 1 END) as ha_sources,
                    COUNT(CASE WHEN source = 'Manual' THEN 1 END) as manual_sources,
                    AVG(confidence_score) as avg_confidence,
                    AVG(data_completeness) as avg_completeness
                FROM companies
                WHERE website IS NOT NULL
            """)

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if row:
                return {
                    'total_companies': row[0],
                    'unique_domains': row[1],
                    'yp_sources': row[2],
                    'ha_sources': row[3],
                    'manual_sources': row[4],
                    'avg_confidence': float(row[5]) if row[5] else 0,
                    'avg_completeness': float(row[6]) if row[6] else 0
                }

            return None

        except Exception as e:
            self.logger.error(f"Error getting source stats: {str(e)}")
            return None


def main():
    """CLI interface for URL source connector."""
    import argparse

    parser = argparse.ArgumentParser(description='URL Source Connector')
    parser.add_argument('command', choices=['stats', 'sync', 'test'])
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for sync')
    parser.add_argument('--min-confidence', type=float, default=50.0, help='Minimum confidence score')
    parser.add_argument('--priority', type=int, default=5, help='Crawl priority (1-10)')

    args = parser.parse_args()

    connector = URLSourceConnector()

    if args.command == 'stats':
        stats = connector.get_source_stats()
        if stats:
            print("\nURL Source Database Statistics:")
            print("=" * 60)
            print(f"Total Companies:    {stats['total_companies']}")
            print(f"Unique Domains:     {stats['unique_domains']}")
            print(f"YP Sources:         {stats['yp_sources']}")
            print(f"HA Sources:         {stats['ha_sources']}")
            print(f"Manual Sources:     {stats['manual_sources']}")
            print(f"Avg Confidence:     {stats['avg_confidence']:.2f}")
            print(f"Avg Completeness:   {stats['avg_completeness']:.2f}")
        else:
            print("Could not retrieve stats")

    elif args.command == 'sync':
        print(f"\nSyncing URLs from washbot_db to SEO scraper...")
        print(f"Batch size: {args.batch_size}")
        print(f"Min confidence: {args.min_confidence}")
        print(f"Priority: {args.priority}")
        print("-" * 60)

        stats = connector.sync_urls_to_crawler(
            batch_size=args.batch_size,
            min_confidence=args.min_confidence,
            priority=args.priority
        )

        print("\nSync Results:")
        print("=" * 60)
        print(f"Fetched:  {stats['fetched']}")
        print(f"Created:  {stats['created']}")
        print(f"Skipped:  {stats['skipped']}")
        print(f"Errors:   {stats['errors']}")

    elif args.command == 'test':
        print("\nTesting URL source connector...")
        print("-" * 60)

        # Test source connection
        try:
            conn = connector._get_source_connection()
            print("✓ Source database connection successful (washbot_db)")
            conn.close()
        except Exception as e:
            print(f"✗ Source database connection failed: {str(e)}")

        # Test target connection
        try:
            conn = connector._get_target_connection()
            print("✓ Target database connection successful (scraper)")
            conn.close()
        except Exception as e:
            print(f"✗ Target database connection failed: {str(e)}")

        # Test fetching companies
        companies = connector.get_companies_from_source(limit=5)
        print(f"✓ Fetched {len(companies)} sample companies")
        if companies:
            print("\nSample companies:")
            for i, company in enumerate(companies[:3], 1):
                print(f"  {i}. {company['name']} - {company['website']}")


if __name__ == "__main__":
    main()
