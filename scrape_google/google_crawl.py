"""
Google Business Scraper - Orchestration Layer

Handles batch processing, database integration, duplicate detection,
and progress tracking for Google Maps/Business scraping.

Features:
- Queue-based processing
- Duplicate detection by place_id
- Database integration (companies + scrape_logs tables)
- Progress tracking and resumption
- Error handling and retry logic

Author: washdb-bot
Date: 2025-11-10
"""

import asyncio
import time
from typing import Dict, List, Optional, Callable
from datetime import datetime
import psycopg
from psycopg.rows import dict_row

from .google_client import GoogleBusinessClient
from .google_config import GoogleConfig
from .google_logger import GoogleScraperLogger


class GoogleCrawler:
    """
    High-level orchestration for Google Business scraping.

    Manages search -> extract -> save workflow with duplicate detection,
    error handling, and progress tracking.
    """

    def __init__(
        self,
        config: GoogleConfig = None,
        logger: GoogleScraperLogger = None,
        db_connection_string: str = None
    ):
        """
        Initialize the Google crawler.

        Args:
            config: GoogleConfig instance
            logger: GoogleScraperLogger instance
            db_connection_string: PostgreSQL connection string
        """
        self.config = config or GoogleConfig.from_env()
        self.logger = logger or GoogleScraperLogger(log_dir=self.config.log_dir)

        # Database connection string
        self.db_connection_string = db_connection_string or self.config.database.get_connection_string()

        # Statistics
        self.stats = {
            "searches_completed": 0,
            "businesses_found": 0,
            "businesses_scraped": 0,
            "businesses_saved": 0,
            "duplicates_skipped": 0,
            "errors": 0
        }

        # Progress tracking
        self.progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable):
        """
        Set callback function for progress updates.

        Args:
            callback: Function(status, message, stats) to call on progress
        """
        self.progress_callback = callback

    def _report_progress(self, status: str, message: str):
        """Report progress via callback if set."""
        if self.progress_callback:
            try:
                self.progress_callback(status, message, self.stats.copy())
            except Exception as e:
                self.logger.error("Error in progress callback", error=e)

    async def search_and_save(
        self,
        query: str,
        location: str = None,
        max_results: int = None,
        scrape_details: bool = True
    ) -> Dict:
        """
        Search Google Maps and save results to database.

        Args:
            query: Search query (e.g., "car wash")
            location: Location (e.g., "Seattle, WA")
            max_results: Maximum results to process
            scrape_details: Whether to scrape detailed info for each business

        Returns:
            Dictionary with statistics and results
        """
        self.logger.operation_started("search_and_save", {
            "query": query,
            "location": location,
            "max_results": max_results,
            "scrape_details": scrape_details
        })

        start_time = time.time()
        results = []

        try:
            self._report_progress("searching", f"Searching for '{query}' in '{location}'...")

            # Search Google Maps
            async with GoogleBusinessClient(config=self.config, logger=self.logger) as client:
                # Perform search
                search_results = await client.search_google_maps(
                    query=query,
                    location=location,
                    max_results=max_results
                )

                self.stats["searches_completed"] += 1
                self.stats["businesses_found"] += len(search_results)

                self._report_progress(
                    "processing",
                    f"Found {len(search_results)} businesses, processing..."
                )

                # Process each business
                for idx, business in enumerate(search_results, 1):
                    try:
                        self._report_progress(
                            "processing",
                            f"Processing business {idx}/{len(search_results)}: {business.get('name', 'Unknown')}"
                        )

                        # Check for duplicate by place_id
                        place_id = business.get('place_id')
                        if place_id and await self._is_duplicate(place_id):
                            self.logger.duplicate_detected(place_id, "place_id")
                            self.stats["duplicates_skipped"] += 1

                            # Still update existing record if scraping details
                            if scrape_details and business.get('url'):
                                await self._update_existing_business(
                                    place_id,
                                    business.get('url'),
                                    client
                                )
                            continue

                        # Scrape detailed info if requested
                        business_data = business.copy()
                        if scrape_details and business.get('url'):
                            self._report_progress(
                                "scraping",
                                f"Scraping details for: {business.get('name', 'Unknown')}"
                            )

                            details = await client.scrape_business_details(business['url'])
                            business_data.update(details)
                            self.stats["businesses_scraped"] += 1

                        # Save to database
                        saved_id = await self._save_business(business_data, query, location)
                        if saved_id:
                            business_data['id'] = saved_id
                            results.append(business_data)
                            self.stats["businesses_saved"] += 1

                            self._report_progress(
                                "saved",
                                f"Saved: {business_data.get('name', 'Unknown')} (ID: {saved_id})"
                            )

                    except Exception as e:
                        self.logger.error(
                            f"Error processing business {idx}",
                            error=e,
                            context={"business": business.get('name')}
                        )
                        self.stats["errors"] += 1

            duration = time.time() - start_time

            self.logger.operation_completed("search_and_save", "success")
            self.logger.session_summary(
                total_scraped=self.stats["businesses_found"],
                successful=self.stats["businesses_saved"],
                failed=self.stats["errors"],
                duration_minutes=duration / 60,
                avg_quality_score=self._calculate_avg_quality(results)
            )

            self._report_progress(
                "completed",
                f"Completed! Saved {self.stats['businesses_saved']} businesses"
            )

            return {
                "success": True,
                "stats": self.stats.copy(),
                "results": results,
                "duration_seconds": duration
            }

        except Exception as e:
            self.logger.error("Fatal error in search_and_save", error=e)
            self._report_progress("error", f"Error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "stats": self.stats.copy()
            }

    async def _is_duplicate(self, place_id: str) -> bool:
        """
        Check if a business already exists by place_id.

        Args:
            place_id: Google Place ID

        Returns:
            True if duplicate, False otherwise
        """
        try:
            async with await psycopg.AsyncConnection.connect(
                self.db_connection_string,
                row_factory=dict_row
            ) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id FROM companies WHERE place_id = %s LIMIT 1",
                        (place_id,)
                    )
                    result = await cur.fetchone()
                    return result is not None

        except Exception as e:
            self.logger.error("Error checking duplicate", error=e, context={"place_id": place_id})
            return False

    async def _update_existing_business(
        self,
        place_id: str,
        business_url: str,
        client: GoogleBusinessClient
    ):
        """
        Update existing business record with fresh data.

        Args:
            place_id: Google Place ID
            business_url: Google Maps URL
            client: GoogleBusinessClient instance
        """
        try:
            # Scrape fresh data
            details = await client.scrape_business_details(business_url)

            if not details:
                return

            # Update database
            async with await psycopg.AsyncConnection.connect(
                self.db_connection_string
            ) as conn:
                async with conn.cursor() as cur:
                    # Build update query for available fields
                    update_fields = []
                    values = []

                    field_mapping = {
                        'name': 'name',
                        'address': 'address',
                        'phone': 'phone',
                        'website': 'website',
                        'rating': 'rating',
                        'category': 'category',
                        'data_completeness': 'data_completeness'
                    }

                    for field, col in field_mapping.items():
                        if field in details and details[field]:
                            update_fields.append(f"{col} = %s")
                            values.append(details[field])

                    # Always update scrape metadata
                    update_fields.extend([
                        "scrape_method = %s",
                        "scrape_timestamp = %s",
                        "last_scrape_attempt = %s",
                        "updated_at = CURRENT_TIMESTAMP"
                    ])
                    values.extend([
                        "playwright",
                        datetime.now(),
                        datetime.now()
                    ])

                    # Add place_id for WHERE clause
                    values.append(place_id)

                    query = f"""
                        UPDATE companies
                        SET {', '.join(update_fields)}
                        WHERE place_id = %s
                    """

                    await cur.execute(query, values)
                    await conn.commit()

                    self.logger.database_update(
                        "companies",
                        0,  # Don't have ID, using place_id
                        list(field_mapping.values())
                    )

        except Exception as e:
            self.logger.error("Error updating existing business", error=e, context={"place_id": place_id})

    async def _save_business(
        self,
        business_data: Dict,
        search_query: str = None,
        search_location: str = None
    ) -> Optional[int]:
        """
        Save business to database.

        Args:
            business_data: Business information dictionary
            search_query: Original search query
            search_location: Original search location

        Returns:
            Inserted company ID or None
        """
        try:
            async with await psycopg.AsyncConnection.connect(
                self.db_connection_string
            ) as conn:
                async with conn.cursor() as cur:
                    # Prepare data
                    query_parts = []
                    values = []

                    # Required fields
                    query_parts.append("name")
                    values.append(business_data.get('name', 'Unknown'))

                    # Source
                    query_parts.append("source")
                    values.append("Google")

                    # Optional fields
                    optional_fields = {
                        'address': 'address',
                        'phone': 'phone',
                        'website': 'website',
                        'rating': 'rating',
                        'category': 'category',
                        'place_id': 'place_id',
                        'google_business_url': 'google_business_url',
                        'data_completeness': 'data_completeness'
                    }

                    for field, col in optional_fields.items():
                        if field in business_data and business_data[field]:
                            query_parts.append(col)
                            values.append(business_data[field])

                    # Scraping metadata
                    query_parts.extend([
                        "scrape_method",
                        "scrape_timestamp",
                        "last_scrape_attempt"
                    ])
                    values.extend([
                        "playwright",
                        datetime.now(),
                        datetime.now()
                    ])

                    # Build INSERT query
                    placeholders = ', '.join(['%s'] * len(values))
                    query = f"""
                        INSERT INTO companies ({', '.join(query_parts)})
                        VALUES ({placeholders})
                        RETURNING id
                    """

                    await cur.execute(query, values)
                    result = await cur.fetchone()
                    company_id = result[0] if result else None

                    await conn.commit()

                    # Log to scrape_logs table
                    if company_id:
                        await self._log_scrape(
                            conn,
                            company_id,
                            "success",
                            list(optional_fields.values())
                        )

                    self.logger.database_update("companies", company_id or 0, query_parts)

                    return company_id

        except Exception as e:
            self.logger.database_error("insert", e, {"name": business_data.get('name')})
            return None

    async def _log_scrape(
        self,
        conn,
        company_id: int,
        status: str,
        fields_updated: List[str],
        error_message: str = None,
        duration_ms: int = None
    ):
        """
        Log scrape attempt to scrape_logs table.

        Args:
            conn: Database connection
            company_id: Company ID
            status: Scrape status (success, partial, failed)
            fields_updated: List of fields that were updated
            error_message: Error message if failed
            duration_ms: Scrape duration in milliseconds
        """
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO scrape_logs (
                        company_id,
                        scrape_method,
                        status,
                        fields_updated,
                        error_message,
                        scrape_duration_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        company_id,
                        "playwright",
                        status,
                        fields_updated,
                        error_message,
                        duration_ms
                    )
                )
            # Note: Don't commit here, let the caller commit
        except Exception as e:
            self.logger.error("Error logging scrape", error=e)

    def _calculate_avg_quality(self, results: List[Dict]) -> float:
        """Calculate average quality score from results."""
        scores = [r.get('data_completeness', 0) for r in results if 'data_completeness' in r]
        return sum(scores) / len(scores) if scores else 0.0

    def get_stats(self) -> Dict:
        """Get current statistics."""
        return self.stats.copy()


# Convenience function for quick scraping
async def scrape_google_maps(
    query: str,
    location: str = None,
    max_results: int = 20,
    scrape_details: bool = True,
    config: GoogleConfig = None,
    progress_callback: Callable = None
) -> Dict:
    """
    Convenience function to search Google Maps and save to database.

    Args:
        query: Search query
        location: Location
        max_results: Max results to process
        scrape_details: Whether to scrape detailed info
        config: GoogleConfig instance
        progress_callback: Progress callback function

    Returns:
        Dictionary with results and statistics
    """
    crawler = GoogleCrawler(config=config)
    if progress_callback:
        crawler.set_progress_callback(progress_callback)

    return await crawler.search_and_save(
        query=query,
        location=location,
        max_results=max_results,
        scrape_details=scrape_details
    )
