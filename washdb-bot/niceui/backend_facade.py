"""
Backend facade - real integrations to scraper modules.
Provides synchronous wrappers for NiceGUI frontend.
"""

import os
import csv
import json
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from pathlib import Path

# Import actual scraper modules
from scrape_yp.yp_crawl import crawl_all_states, CATEGORIES as DEFAULT_CATEGORIES, STATES as DEFAULT_STATES
from scrape_site.site_scraper import scrape_website
from db.save_discoveries import upsert_discovered, create_session
from db.update_details import update_batch
from db.models import Company, canonicalize_url, domain_from_url
from runner.logging_setup import get_logger

# SQLAlchemy imports for queries
from sqlalchemy import select, func, or_, and_


# Initialize logger
logger = get_logger("backend_facade")


class BackendFacade:
    """Facade for interacting with scraper backend."""

    def __init__(self):
        self.running = False
        self.last_run = None

    def discover(
        self,
        categories: List[str],
        states: List[str],
        pages_per_pair: int,
        cancel_flag: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None
    ) -> Dict[str, int]:
        """
        Run YP discovery across category×state with pagination and dedup.

        Args:
            categories: List of business categories to search
            states: List of state codes to search
            pages_per_pair: Number of pages to crawl per category-state pair
            cancel_flag: Optional callable that returns True to cancel operation
            progress_callback: Optional callable to receive progress updates

        Returns:
            Dict with keys:
            - found: Total businesses found
            - new: New businesses added to database
            - updated: Existing businesses updated
            - errors: Number of errors encountered
            - pairs_done: Number of category-state pairs completed
            - pairs_total: Total number of pairs to process
        """
        logger.info(
            f"Starting discovery: {len(categories)} categories × {len(states)} states "
            f"× {pages_per_pair} pages/each"
        )

        # Use defaults if not provided
        if not categories:
            categories = DEFAULT_CATEGORIES[:3]  # Use first 3 for reasonable scope
        if not states:
            states = DEFAULT_STATES

        total_pairs = len(categories) * len(states)
        pairs_done = 0
        total_found = 0
        total_new = 0
        total_updated = 0
        total_errors = 0

        try:
            # Iterate through all category-state combinations
            for batch in crawl_all_states(
                categories=categories,
                states=states,
                limit_per_state=pages_per_pair
            ):
                # Check for cancellation
                if cancel_flag and cancel_flag():
                    logger.warning("Discovery cancelled by user")
                    if progress_callback:
                        progress_callback({
                            'type': 'cancelled',
                            'pairs_done': pairs_done,
                            'pairs_total': total_pairs
                        })
                    break

                pairs_done += 1

                # Get category and state from batch metadata if available
                category = batch.get("category", "")
                state = batch.get("state", "")

                # Report progress: starting batch
                if progress_callback:
                    progress_callback({
                        'type': 'batch_start',
                        'pairs_done': pairs_done,
                        'pairs_total': total_pairs,
                        'category': category,
                        'state': state
                    })

                # Check if batch has results
                if batch.get("error"):
                    total_errors += 1
                    logger.warning(f"Error in batch {pairs_done}/{total_pairs}: {batch['error']}")
                    if progress_callback:
                        progress_callback({
                            'type': 'batch_error',
                            'pairs_done': pairs_done,
                            'pairs_total': total_pairs,
                            'category': category,
                            'state': state,
                            'error': batch['error']
                        })
                    continue

                results = batch.get("results", [])
                if not results:
                    logger.info(f"No results in batch {pairs_done}/{total_pairs}")
                    if progress_callback:
                        progress_callback({
                            'type': 'batch_empty',
                            'pairs_done': pairs_done,
                            'pairs_total': total_pairs,
                            'category': category,
                            'state': state
                        })
                    continue

                total_found += len(results)

                # Save to database
                try:
                    inserted, skipped, updated = upsert_discovered(results)
                    total_new += inserted
                    total_updated += updated

                    logger.info(
                        f"Batch {pairs_done}/{total_pairs}: "
                        f"{len(results)} found, {inserted} new, {updated} updated"
                    )

                    # Report progress: batch complete
                    if progress_callback:
                        progress_callback({
                            'type': 'batch_complete',
                            'pairs_done': pairs_done,
                            'pairs_total': total_pairs,
                            'category': category,
                            'state': state,
                            'found': len(results),
                            'new': inserted,
                            'updated': updated,
                            'total_found': total_found,
                            'total_new': total_new,
                            'total_updated': total_updated,
                            'total_errors': total_errors
                        })

                except Exception as e:
                    total_errors += 1
                    logger.error(f"Error saving batch {pairs_done}: {e}", exc_info=True)
                    if progress_callback:
                        progress_callback({
                            'type': 'save_error',
                            'pairs_done': pairs_done,
                            'pairs_total': total_pairs,
                            'category': category,
                            'state': state,
                            'error': str(e)
                        })
                    continue

        except Exception as e:
            logger.error(f"Discovery error: {e}", exc_info=True)
            total_errors += 1

        result = {
            "found": total_found,
            "new": total_new,
            "updated": total_updated,
            "errors": total_errors,
            "pairs_done": pairs_done,
            "pairs_total": total_pairs
        }

        logger.info(f"Discovery complete: {result}")
        return result

    def scrape_batch(
        self,
        limit: Optional[int] = None,
        stale_days: Optional[int] = None,
        only_missing_email: bool = False,
        cancel_flag: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None
    ) -> Dict[str, int]:
        """
        Run detail enrichment over queued/stale companies.

        Args:
            limit: Maximum number of companies to process (None = no limit)
            stale_days: Consider companies stale after N days (None = use default 30)
            only_missing_email: Only process companies missing email
            cancel_flag: Optional callable that returns True to cancel operation
            progress_callback: Optional callable to receive progress updates

        Returns:
            Dict with keys:
            - processed: Total companies processed
            - updated: Companies successfully updated
            - skipped: Companies skipped (no updates needed)
            - errors: Number of errors encountered
        """
        logger.info(
            f"Starting batch scrape: limit={limit}, stale_days={stale_days}, "
            f"only_missing_email={only_missing_email}"
        )

        # Use defaults
        if limit is None:
            limit = 100
        if stale_days is None:
            stale_days = 30

        try:
            # Use existing update_batch function with cancellation and progress support
            summary = update_batch(
                limit=limit,
                stale_days=stale_days,
                only_missing_email=only_missing_email,
                cancel_flag=cancel_flag,
                progress_callback=progress_callback
            )

            result = {
                "processed": summary.get("total_processed", 0),
                "updated": summary.get("updated", 0),
                "skipped": summary.get("skipped", 0),
                "errors": summary.get("errors", 0)
            }

            logger.info(f"Batch scrape complete: {result}")
            return result

        except Exception as e:
            logger.error(f"Batch scrape error: {e}", exc_info=True)
            return {
                "processed": 0,
                "updated": 0,
                "skipped": 0,
                "errors": 1
            }

    def scrape_one_preview(self, url: str) -> Dict[str, Any]:
        """
        Scrape one site WITHOUT saving to database (preview only).

        Args:
            url: Website URL to scrape

        Returns:
            Dict with extracted business information including:
            - url: Original URL
            - canonical_url: Canonicalized URL
            - domain: Extracted domain
            - name: Business name
            - phones: List of phone numbers
            - emails: List of email addresses
            - services: Services description
            - service_area: Service area description
            - address: Physical address
            - reviews: Review information
            - status: 'success' or 'error'
            - error: Error message if status is 'error'
        """
        logger.info(f"Scraping single URL (preview): {url}")

        try:
            # Canonicalize URL
            canonical_url = canonicalize_url(url)
            domain = domain_from_url(canonical_url)

            # Scrape the website
            site_data = scrape_website(canonical_url)

            # Return full result (without upserting)
            result = {
                "url": url,
                "canonical_url": canonical_url,
                "domain": domain,
                "name": site_data.get("name"),
                "phones": site_data.get("phones", []),
                "emails": site_data.get("emails", []),
                "services": site_data.get("services"),
                "service_area": site_data.get("service_area"),
                "address": site_data.get("address"),
                "reviews": site_data.get("reviews"),
                "status": "success"
            }

            logger.info(f"Preview scrape complete for {domain}")
            return result

        except Exception as e:
            logger.error(f"Error scraping {url}: {e}", exc_info=True)
            return {
                "url": url,
                "status": "error",
                "error": str(e)
            }

    def upsert_from_scrape(self, scrape_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upsert a previously scraped result to the database.

        Args:
            scrape_result: Result dict from scrape_one_preview()

        Returns:
            Dict with keys:
            - success: True if upsert succeeded
            - message: Status message
            - domain: Domain that was upserted (if successful)
        """
        logger.info(f"Upserting scrape result for {scrape_result.get('domain')}")

        try:
            if scrape_result.get("status") == "error":
                return {
                    "success": False,
                    "message": "Cannot upsert failed scrape result",
                }

            # Prepare company data for upsert
            company_data = {
                "name": scrape_result.get("name"),
                "website": scrape_result.get("canonical_url"),
                "domain": scrape_result.get("domain"),
                "phone": scrape_result.get("phones", [])[0] if scrape_result.get("phones") else None,
                "email": scrape_result.get("emails", [])[0] if scrape_result.get("emails") else None,
                "services": scrape_result.get("services"),
                "service_area": scrape_result.get("service_area"),
                "address": scrape_result.get("address"),
                "source": "Manual",
            }

            # Upsert to database
            upsert_discovered([company_data])
            logger.info(f"Successfully upserted {company_data['domain']}")

            return {
                "success": True,
                "message": f"Successfully saved {company_data['domain']} to database",
                "domain": company_data["domain"]
            }

        except Exception as e:
            logger.error(f"Error upserting to database: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Database error: {str(e)}"
            }

    def scrape_one(self, url: str) -> Dict[str, Any]:
        """
        Scrape one site (homepage + obvious subpages), parse fields, upsert, and return full fields dict.

        Args:
            url: Website URL to scrape

        Returns:
            Dict with extracted business information including:
            - url: Original URL
            - canonical_url: Canonicalized URL
            - domain: Extracted domain
            - name: Business name
            - phones: List of phone numbers
            - emails: List of email addresses
            - services: Services description
            - service_area: Service area description
            - address: Physical address
            - reviews: Review information
            - status: 'success' or 'error'
            - error: Error message if status is 'error'
        """
        logger.info(f"Scraping single URL: {url}")

        try:
            # Canonicalize URL
            canonical_url = canonicalize_url(url)
            domain = domain_from_url(canonical_url)

            # Scrape the website
            site_data = scrape_website(canonical_url)

            # Prepare company data for upsert
            company_data = {
                "name": site_data.get("name"),
                "website": canonical_url,
                "domain": domain,
                "phone": site_data.get("phones", [])[0] if site_data.get("phones") else None,
                "email": site_data.get("emails", [])[0] if site_data.get("emails") else None,
                "services": site_data.get("services"),
                "service_area": site_data.get("service_area"),
                "address": site_data.get("address"),
                "source": "Manual",
            }

            # Upsert to database
            try:
                upsert_discovered([company_data])
                logger.info(f"Successfully upserted {domain}")
            except Exception as e:
                logger.warning(f"Error upserting to database: {e}")

            # Return full result
            result = {
                "url": url,
                "canonical_url": canonical_url,
                "domain": domain,
                "name": site_data.get("name"),
                "phones": site_data.get("phones", []),
                "emails": site_data.get("emails", []),
                "services": site_data.get("services"),
                "service_area": site_data.get("service_area"),
                "address": site_data.get("address"),
                "reviews": site_data.get("reviews"),
                "status": "success"
            }

            return result

        except Exception as e:
            logger.error(f"Error scraping {url}: {e}", exc_info=True)
            return {
                "url": url,
                "status": "error",
                "error": str(e)
            }

    def fetch_companies(
        self,
        search: Optional[str] = None,
        limit: int = 5000
    ) -> List[Dict[str, Any]]:
        """
        Fetch companies from database.

        Args:
            search: Optional search term to filter by name/domain/website
            limit: Maximum number of rows to return

        Returns:
            List of company dicts with keys:
            - id, name, website, phone, email, services, service_area,
              address, source, last_updated
        """
        logger.info(f"Fetching companies: search='{search}', limit={limit}")

        session = create_session()

        try:
            # Build query
            stmt = select(Company).where(Company.active == True)

            # Apply search filter
            if search:
                search_term = f"%{search}%"
                stmt = stmt.where(
                    or_(
                        Company.name.ilike(search_term),
                        Company.domain.ilike(search_term),
                        Company.website.ilike(search_term)
                    )
                )

            # Apply limit and order
            stmt = stmt.limit(limit).order_by(Company.last_updated.desc().nullslast())

            # Execute query
            companies = session.execute(stmt).scalars().all()

            # Convert to dicts
            results = []
            for company in companies:
                results.append({
                    "id": company.id,
                    "name": company.name,
                    "website": company.website,
                    "phone": company.phone,
                    "email": company.email,
                    "services": company.services,
                    "service_area": company.service_area,
                    "address": company.address,
                    "source": company.source,
                    "last_updated": company.last_updated.isoformat() if company.last_updated else None
                })

            logger.info(f"Fetched {len(results)} companies")
            return results

        except Exception as e:
            logger.error(f"Error fetching companies: {e}", exc_info=True)
            return []

        finally:
            session.close()

    def kpis(self) -> Dict[str, Any]:
        """
        Get key performance indicators.

        Returns:
            Dict with keys:
            - total_companies: Total number of companies
            - with_email: Companies with email addresses
            - with_phone: Companies with phone numbers
            - updated_30d: Companies updated in last 30 days
            - new_7d: Companies added in last 7 days
        """
        logger.info("Calculating KPIs")

        try:
            session = create_session()
        except Exception as e:
            logger.warning(f"Database not available: {e}")
            return {
                "total_companies": 0,
                "with_email": 0,
                "with_phone": 0,
                "updated_30d": 0,
                "new_7d": 0
            }

        try:
            # Total companies
            total = session.execute(
                select(func.count(Company.id)).where(Company.active == True)
            ).scalar()

            # With email
            with_email = session.execute(
                select(func.count(Company.id)).where(
                    and_(Company.active == True, Company.email.isnot(None))
                )
            ).scalar()

            # With phone
            with_phone = session.execute(
                select(func.count(Company.id)).where(
                    and_(Company.active == True, Company.phone.isnot(None))
                )
            ).scalar()

            # Updated in last 30 days
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            updated_30d = session.execute(
                select(func.count(Company.id)).where(
                    and_(
                        Company.active == True,
                        Company.last_updated >= thirty_days_ago
                    )
                )
            ).scalar()

            # New in last 7 days
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            new_7d = session.execute(
                select(func.count(Company.id)).where(
                    and_(
                        Company.active == True,
                        Company.created_at >= seven_days_ago
                    )
                )
            ).scalar()

            result = {
                "total_companies": total or 0,
                "with_email": with_email or 0,
                "with_phone": with_phone or 0,
                "updated_30d": updated_30d or 0,
                "new_7d": new_7d or 0
            }

            logger.info(f"KPIs: {result}")
            return result

        except Exception as e:
            logger.error(f"Error calculating KPIs: {e}", exc_info=True)
            return {
                "total_companies": 0,
                "with_email": 0,
                "with_phone": 0,
                "updated_30d": 0,
                "new_7d": 0
            }

        finally:
            session.close()

    def export_new_urls(
        self,
        days: int,
        out_csv: str,
        out_jsonl: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Export new URLs added since N days to CSV (and optionally JSONL).

        Args:
            days: Export companies added in last N days
            out_csv: Output CSV file path
            out_jsonl: Optional output JSONL file path

        Returns:
            Dict with keys:
            - count: Number of companies exported
            - csv: Path to CSV file
            - jsonl: Path to JSONL file (None if not requested)
        """
        logger.info(f"Exporting URLs from last {days} days to {out_csv}")

        session = create_session()

        try:
            # Calculate date threshold
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            # Query for new companies
            stmt = select(Company).where(
                and_(
                    Company.active == True,
                    Company.created_at >= cutoff_date
                )
            ).order_by(Company.created_at.desc())

            companies = session.execute(stmt).scalars().all()

            # Write CSV
            csv_path = Path(out_csv)
            csv_path.parent.mkdir(parents=True, exist_ok=True)

            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                if companies:
                    # Use first company to get fieldnames
                    fieldnames = ['id', 'name', 'website', 'domain', 'phone', 'email',
                                 'services', 'service_area', 'address', 'source', 'created_at']

                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()

                    for company in companies:
                        writer.writerow({
                            'id': company.id,
                            'name': company.name,
                            'website': company.website,
                            'domain': company.domain,
                            'phone': company.phone,
                            'email': company.email,
                            'services': company.services,
                            'service_area': company.service_area,
                            'address': company.address,
                            'source': company.source,
                            'created_at': company.created_at.isoformat() if company.created_at else None
                        })

            logger.info(f"Wrote {len(companies)} companies to {csv_path}")

            # Write JSONL if requested
            jsonl_path = None
            if out_jsonl:
                jsonl_path = Path(out_jsonl)
                jsonl_path.parent.mkdir(parents=True, exist_ok=True)

                with open(jsonl_path, 'w', encoding='utf-8') as f:
                    for company in companies:
                        record = {
                            'id': company.id,
                            'name': company.name,
                            'website': company.website,
                            'domain': company.domain,
                            'phone': company.phone,
                            'email': company.email,
                            'services': company.services,
                            'service_area': company.service_area,
                            'address': company.address,
                            'source': company.source,
                            'created_at': company.created_at.isoformat() if company.created_at else None
                        }
                        f.write(json.dumps(record) + '\n')

                logger.info(f"Wrote {len(companies)} companies to {jsonl_path}")

            return {
                "count": len(companies),
                "csv": str(csv_path),
                "jsonl": str(jsonl_path) if jsonl_path else None
            }

        except Exception as e:
            logger.error(f"Error exporting URLs: {e}", exc_info=True)
            return {
                "count": 0,
                "csv": out_csv,
                "jsonl": None,
                "error": str(e)
            }

        finally:
            session.close()

    # Legacy methods for backward compatibility
    def get_kpis(self) -> Dict[str, Any]:
        """Legacy method - calls kpis()."""
        kpi_data = self.kpis()
        return {
            'total_urls': kpi_data['total_companies'],
            'scraped_today': kpi_data['new_7d'],
            'success_rate': 100.0,  # Calculate from actual data if needed
            'avg_response_time': 0.0,
            'active_jobs': 0
        }

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        session = create_session()
        try:
            total = session.execute(
                select(func.count(Company.id)).where(Company.active == True)
            ).scalar() or 0

            with_details = session.execute(
                select(func.count(Company.id)).where(
                    and_(
                        Company.active == True,
                        Company.last_updated.isnot(None)
                    )
                )
            ).scalar() or 0

            pending = total - with_details
            failed = 0  # Would need to track failures separately

            return {
                'total_urls': total,
                'scraped': with_details,
                'pending': pending,
                'failed': failed
            }
        finally:
            session.close()

    def get_database_rows(self, limit: int = 100, offset: int = 0, filters: Optional[Dict] = None) -> List[Dict]:
        """Fetch rows from database."""
        return self.fetch_companies(search=None, limit=limit)

    def check_database_connection(self) -> Dict[str, Any]:
        """Check database connection status."""
        try:
            from sqlalchemy import text
            session = create_session()
            # Simple query to test connection (doesn't require tables to exist)
            session.execute(text("SELECT 1")).scalar()
            session.close()
            return {
                'connected': True,
                'message': 'Database connection OK'
            }
        except Exception as e:
            return {
                'connected': False,
                'message': f'Database error: {str(e)}'
            }

    def get_scrape_status(self) -> Dict[str, Any]:
        """Get current scraping status."""
        return {
            'running': self.running,
            'processed': 0,
            'success': 0,
            'failed': 0,
            'last_run': self.last_run.isoformat() if self.last_run else None
        }

    def start_scrape(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Start scraping process."""
        self.running = True
        self.last_run = datetime.now()
        return {
            'status': 'started',
            'message': 'Scraping process initiated',
            'timestamp': self.last_run.isoformat()
        }

    def stop_scrape(self) -> Dict[str, Any]:
        """Stop scraping process."""
        self.running = False
        return {
            'status': 'stopped',
            'message': 'Scraping process stopped',
            'timestamp': datetime.now().isoformat()
        }

    def get_discovery_status(self) -> Dict[str, Any]:
        """Get current discovery status."""
        return {
            'running': False,
            'total_found': 0,
            'last_run': None
        }

    def get_logs(self, limit: int = 100, level: Optional[str] = None) -> List[Dict]:
        """Get application logs."""
        # For now, return empty list - logs are handled by ui.log binding
        return []


# Global backend instance
backend = BackendFacade()
