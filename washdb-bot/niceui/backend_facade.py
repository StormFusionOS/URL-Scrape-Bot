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
# NOTE: YP scraper now uses city-first approach via CLI subprocess (see niceui/pages/discover.py)
# from scrape_yp.yp_crawl import crawl_all_states, CATEGORIES as DEFAULT_CATEGORIES, STATES as DEFAULT_STATES
from scrape_site.site_scraper import scrape_website
from db.save_discoveries import upsert_discovered, create_session
from db.update_details import update_batch
from db.models import Company, canonicalize_url, domain_from_url
from runner.logging_setup import get_logger

# Import Google scraper modules
from scrape_google.google_crawl import GoogleCrawler
from scrape_google.google_config import GoogleConfig
from scrape_google.google_crawl_city_first import crawl_city_targets
from scrape_google.generate_city_targets import load_categories, generate_targets
import asyncio

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
        progress_callback: Optional[Callable[[dict], None]] = None,
        providers: List[str] = None,
        use_enhanced_filter: bool = True,
        min_score: float = 50.0,
        include_sponsored: bool = False
    ) -> Dict[str, int]:
        """
        Run multi-provider discovery across category×state with pagination and dedup.

        Args:
            categories: List of business categories to search (optional, uses provider defaults)
            states: List of state codes to search
            pages_per_pair: Search depth (number of result pages per category-state search)
            cancel_flag: Optional callable that returns True to cancel operation
            progress_callback: Optional callable to receive progress updates
            providers: List of provider codes to use (e.g., ["YP"]). Default: ["YP"]
            use_enhanced_filter: Use enhanced YP filtering with category tags (default: False)
            min_score: Minimum confidence score for enhanced filter (0-100, default: 50)
            include_sponsored: Include sponsored/ad listings with enhanced filter (default: False)

        Returns:
            Dict with keys:
            - found: Total businesses found
            - new: New businesses added to database
            - updated: Existing businesses updated
            - errors: Number of errors encountered
            - pairs_done: Number of category-state pairs completed
            - pairs_total: Total number of pairs to process
        """
        # Default to YP only for backward compatibility
        if providers is None:
            providers = ["YP"]

        # Determine which providers to use
        use_yp = "YP" in providers

        # Build category list from providers if not specified
        if not categories:
            categories = []
            if use_yp:
                categories.extend(DEFAULT_CATEGORIES[:3])  # Use first 3 for reasonable scope

        # Use default states if not provided
        if not states:
            states = DEFAULT_STATES

        logger.info(
            f"Starting multi-provider discovery: providers={providers}, "
            f"{len(categories)} categories × {len(states)} states × {pages_per_pair} pages/each"
        )

        # Calculate total based on provider-specific categories
        yp_categories = [c for c in categories if c in DEFAULT_CATEGORIES] if use_yp else []
        total_pairs = len(yp_categories) * len(states)

        pairs_done = 0
        total_found = 0
        total_new = 0
        total_updated = 0
        total_errors = 0

        try:
            # Create page callback for YP crawling
            # Store current category and state to use in page callback
            current_context = {'category': '', 'state': ''}

            def page_callback(page, total_pages, new_results, total_results):
                """Send page-level progress updates to UI."""
                if progress_callback:
                    progress_callback({
                        'type': 'page_complete',
                        'page': page,
                        'total_pages': total_pages,
                        'new_results': new_results,
                        'total_results': total_results,
                        'category': current_context['category'],
                        'state': current_context['state']
                    })
                # Return cancellation check
                if cancel_flag and cancel_flag():
                    return True
                return False

            # Create generators for each provider
            generators = []

            # NOTE: YP scraper now uses city-first approach via CLI subprocess
            # The GUI calls cli_crawl_yp.py directly (see niceui/pages/discover.py)
            # Old state-first code has been removed.
            if use_yp and yp_categories:
                logger.warning(
                    "YP scraper is now city-first and uses CLI subprocess. "
                    "Please use the Discovery page in the GUI to run YP scraping."
                )
                # Skip YP in this legacy backend facade method

            # Chain generators together to process sequentially
            import itertools
            combined_generator = itertools.chain(*generators)

            # Iterate through all category-state combinations from all providers
            for batch in combined_generator:
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

                # Update context for page callback
                current_context['category'] = category
                current_context['state'] = state

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
                        should_stop = progress_callback({
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
                        # Stop if progress callback requests it
                        if should_stop:
                            logger.warning("Discovery cancelled by progress callback")
                            break

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

    def discover_google(
        self,
        query: str,
        location: str = None,
        max_results: int = 20,
        scrape_details: bool = True,
        cancel_flag: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None
    ) -> Dict[str, Any]:
        """
        Run Google Maps discovery and scraping.

        Args:
            query: Search query (e.g., "car wash")
            location: Location (e.g., "Seattle, WA")
            max_results: Maximum results to scrape
            scrape_details: Whether to scrape detailed info for each business
            cancel_flag: Optional callable that returns True to cancel operation
            progress_callback: Optional callable to receive progress updates

        Returns:
            Dict with keys:
            - success: Boolean indicating if operation completed successfully
            - found: Total businesses found
            - saved: Businesses saved to database
            - duplicates: Duplicates skipped
            - errors: Number of errors encountered
            - results: List of scraped business data
        """
        logger.info(
            f"Starting Google discovery: query='{query}', location='{location}', "
            f"max_results={max_results}, scrape_details={scrape_details}"
        )

        # Create Google config (can be customized via environment variables)
        config = GoogleConfig.from_env()

        # Create crawler with progress tracking
        crawler = GoogleCrawler(config=config, logger=None)

        # Set up progress callback wrapper
        def google_progress_callback(status: str, message: str, stats: Dict):
            """Wrapper to adapt GoogleCrawler progress to GUI format."""
            if cancel_flag and cancel_flag():
                # Cancellation is handled by the async task
                logger.warning("Google discovery cancelled by user")
                return

            if progress_callback:
                progress_callback({
                    'type': status,
                    'message': message,
                    'found': stats.get('businesses_found', 0),
                    'saved': stats.get('businesses_saved', 0),
                    'duplicates': stats.get('duplicates_skipped', 0),
                    'errors': stats.get('errors', 0)
                })

        crawler.set_progress_callback(google_progress_callback)

        # Run the async scraping operation
        try:
            # Create async task
            result = asyncio.run(crawler.search_and_save(
                query=query,
                location=location,
                max_results=max_results,
                scrape_details=scrape_details
            ))

            logger.info(f"Google discovery complete: {result}")
            return result

        except Exception as e:
            logger.error(f"Google discovery error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "found": 0,
                "saved": 0,
                "duplicates": 0,
                "errors": 1
            }

    def discover_google_city_first(
        self,
        state_ids: List[str],
        max_targets: Optional[int] = None,
        scrape_details: bool = True,
        save_to_db: bool = True,
        cancel_flag: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None
    ) -> Dict[str, Any]:
        """
        Run Google Maps city-first discovery across all targets in specified states.

        This method uses the city × category expansion approach to systematically
        scrape Google Maps for businesses in each city-category combination.

        Args:
            state_ids: List of 2-letter state codes (e.g., ['RI', 'MA'])
            max_targets: Maximum number of targets to process (None = all)
            scrape_details: Whether to scrape detailed business info
            save_to_db: Whether to save results to database
            cancel_flag: Optional callable that returns True to cancel operation
            progress_callback: Optional callable to receive progress updates

        Returns:
            Dict with keys:
            - success: Boolean indicating if operation completed successfully
            - targets_processed: Number of targets completed
            - total_businesses: Total businesses found across all targets
            - saved: Businesses saved to database
            - duplicates: Duplicates skipped
            - captchas: Number of CAPTCHAs detected
            - errors: Number of errors encountered
        """
        logger.info(
            f"Starting Google city-first discovery: states={state_ids}, "
            f"max_targets={max_targets}, scrape_details={scrape_details}"
        )

        # Create database session
        session = create_session()

        try:
            # Track overall stats
            total_targets = 0
            total_businesses = 0
            total_saved = 0
            total_duplicates = 0
            total_captchas = 0
            total_errors = 0

            # Run async crawler
            async def run_crawler():
                nonlocal total_targets, total_businesses, total_saved, total_duplicates, total_captchas, total_errors

                async for batch in crawl_city_targets(
                    state_ids=state_ids,
                    session=session,
                    max_targets=max_targets,
                    scrape_details=scrape_details,
                    save_to_db=save_to_db,
                    use_session_breaks=True,
                    checkpoint_interval=10,
                    recover_orphans=True
                ):
                    # Check for cancellation
                    if cancel_flag and cancel_flag():
                        logger.warning("Google city-first discovery cancelled by user")
                        break

                    # Extract batch data
                    target = batch['target']
                    results = batch['results']
                    stats = batch['stats']

                    # Update totals
                    total_targets += 1
                    total_businesses += stats['total_found']
                    total_saved += stats['total_saved']
                    total_duplicates += stats['duplicates_skipped']
                    if stats.get('captcha_detected'):
                        total_captchas += 1

                    # Send progress update
                    if progress_callback:
                        progress_callback({
                            'type': 'progress',
                            'message': f"Completed: {target.city}, {target.state_id} - {target.category_label}",
                            'target': f"{target.city} - {target.category_label}",
                            'found': stats['total_found'],
                            'saved': stats['total_saved'],
                            'duplicates': stats['duplicates_skipped'],
                            'captcha': stats.get('captcha_detected', False),
                            'total_targets': total_targets,
                            'total_businesses': total_businesses,
                            'total_saved': total_saved,
                            'total_duplicates': total_duplicates,
                            'total_captchas': total_captchas
                        })

            # Run the crawler
            asyncio.run(run_crawler())

            # Final result
            result = {
                "success": True,
                "targets_processed": total_targets,
                "total_businesses": total_businesses,
                "saved": total_saved,
                "duplicates": total_duplicates,
                "captchas": total_captchas,
                "errors": total_errors
            }

            logger.info(f"Google city-first discovery complete: {result}")
            return result

        except Exception as e:
            logger.error(f"Google city-first discovery error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "targets_processed": 0,
                "total_businesses": 0,
                "saved": 0,
                "duplicates": 0,
                "captchas": 0,
                "errors": 1
            }
        finally:
            session.close()

    def get_google_target_stats(self, state_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get statistics about Google Maps city-first targets.

        Args:
            state_ids: Optional list of state codes to filter by

        Returns:
            Dict with target statistics by status and priority
        """
        from db.models import GoogleTarget

        session = create_session()
        try:
            query = session.query(GoogleTarget)
            if state_ids:
                query = query.filter(GoogleTarget.state_id.in_(state_ids))

            total = query.count()

            # Get counts by status
            by_status = {}
            for status in ["PLANNED", "IN_PROGRESS", "DONE", "FAILED"]:
                count = query.filter(GoogleTarget.status == status).count()
                if count > 0:
                    by_status[status] = count

            # Get counts by priority
            by_priority = {}
            for priority in [1, 2, 3]:
                count = query.filter(GoogleTarget.priority == priority).count()
                if count > 0:
                    by_priority[priority] = count

            return {
                "total": total,
                "by_status": by_status,
                "by_priority": by_priority,
                "states": state_ids if state_ids else "all"
            }
        finally:
            session.close()

    def get_discovery_source_statuses(self) -> Dict[str, Dict[str, Any]]:
        """
        Get comprehensive status for all discovery sources.

        Returns:
            Dict with status for each source (YP, Google, Site):
            {
                'YP': {
                    'is_running': bool,
                    'active_count': int,
                    'pending_count': int,
                    'done_count': int,
                    'failed_count': int,
                    'last_run': {'timestamp': str, 'city': str, 'category': str} or None
                },
                'Google': {...},
                'Site': {...}
            }
        """
        from db.models import YPTarget, GoogleTarget
        from sqlalchemy import func, desc
        from datetime import datetime

        session = create_session()
        statuses = {}

        try:
            # ===== YP (Yellow Pages) Status =====
            yp_in_progress = session.query(func.count(YPTarget.id)).filter(
                YPTarget.status == 'in_progress'
            ).scalar() or 0

            yp_planned = session.query(func.count(YPTarget.id)).filter(
                YPTarget.status == 'planned'
            ).scalar() or 0

            yp_done = session.query(func.count(YPTarget.id)).filter(
                YPTarget.status == 'done'
            ).scalar() or 0

            yp_failed = session.query(func.count(YPTarget.id)).filter(
                YPTarget.status == 'failed'
            ).scalar() or 0

            # Get last completed YP target
            yp_last = session.query(YPTarget).filter(
                YPTarget.status == 'done',
                YPTarget.finished_at.isnot(None)
            ).order_by(desc(YPTarget.finished_at)).first()

            statuses['YP'] = {
                'is_running': yp_in_progress > 0,
                'active_count': yp_in_progress,
                'pending_count': yp_planned,
                'done_count': yp_done,
                'failed_count': yp_failed,
                'last_run': {
                    'timestamp': yp_last.finished_at.isoformat() if yp_last.finished_at else None,
                    'city': yp_last.city,
                    'category': yp_last.category_label
                } if yp_last else None
            }

            # ===== Google Maps Status =====
            google_in_progress = session.query(func.count(GoogleTarget.id)).filter(
                func.upper(GoogleTarget.status) == 'IN_PROGRESS'
            ).scalar() or 0

            google_planned = session.query(func.count(GoogleTarget.id)).filter(
                func.upper(GoogleTarget.status) == 'PLANNED'
            ).scalar() or 0

            google_done = session.query(func.count(GoogleTarget.id)).filter(
                func.upper(GoogleTarget.status) == 'DONE'
            ).scalar() or 0

            google_failed = session.query(func.count(GoogleTarget.id)).filter(
                func.upper(GoogleTarget.status) == 'FAILED'
            ).scalar() or 0

            # Get last completed Google target
            google_last = session.query(GoogleTarget).filter(
                func.upper(GoogleTarget.status) == 'DONE',
                GoogleTarget.finished_at.isnot(None)
            ).order_by(desc(GoogleTarget.finished_at)).first()

            statuses['Google'] = {
                'is_running': google_in_progress > 0,
                'active_count': google_in_progress,
                'pending_count': google_planned,
                'done_count': google_done,
                'failed_count': google_failed,
                'last_run': {
                    'timestamp': google_last.finished_at.isoformat() if google_last.finished_at else None,
                    'city': google_last.city,
                    'category': google_last.category_label,
                    'results_saved': google_last.results_saved or 0
                } if google_last else None
            }

            return statuses

        finally:
            session.close()

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

    # ========================================================================
    # SCHEDULER METHODS
    # ========================================================================

    def get_scheduled_jobs(self) -> List[Dict[str, Any]]:
        """Get all scheduled jobs."""
        from db.models import ScheduledJob

        try:
            session = create_session()
            stmt = select(ScheduledJob).order_by(ScheduledJob.created_at.desc())
            jobs = session.scalars(stmt).all()

            result = []
            for job in jobs:
                result.append({
                    'id': job.id,
                    'name': job.name,
                    'description': job.description,
                    'job_type': job.job_type,
                    'schedule_cron': job.schedule_cron,
                    'config': json.loads(job.config) if job.config else {},
                    'enabled': job.enabled,
                    'priority': job.priority,
                    'timeout_minutes': job.timeout_minutes,
                    'max_retries': job.max_retries,
                    'last_run': job.last_run.isoformat() if job.last_run else None,
                    'last_status': job.last_status,
                    'next_run': job.next_run.isoformat() if job.next_run else None,
                    'total_runs': job.total_runs,
                    'success_runs': job.success_runs,
                    'failed_runs': job.failed_runs,
                    'created_at': job.created_at.isoformat() if job.created_at else None,
                    'created_by': job.created_by,
                    'updated_at': job.updated_at.isoformat() if job.updated_at else None,
                })

            session.close()
            return result

        except Exception as e:
            logger.error(f"Error fetching scheduled jobs: {e}")
            return []

    def create_scheduled_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new scheduled job."""
        from db.models import ScheduledJob

        try:
            session = create_session()

            # Create job instance
            job = ScheduledJob(
                name=job_data['name'],
                description=job_data.get('description'),
                job_type=job_data['job_type'],
                schedule_cron=job_data['schedule_cron'],
                config=json.dumps(job_data.get('config', {})),
                enabled=job_data.get('enabled', True),
                priority=job_data.get('priority', 2),
                timeout_minutes=job_data.get('timeout_minutes', 60),
                max_retries=job_data.get('max_retries', 3),
                created_by=job_data.get('created_by', 'dashboard')
            )

            session.add(job)
            session.commit()

            job_id = job.id
            session.close()

            logger.info(f"Created scheduled job: {job.name} (ID: {job_id})")

            return {
                'success': True,
                'job_id': job_id,
                'message': f'Job "{job_data["name"]}" created successfully'
            }

        except Exception as e:
            logger.error(f"Error creating scheduled job: {e}")
            return {
                'success': False,
                'message': f'Error creating job: {str(e)}'
            }

    def update_scheduled_job(self, job_id: int, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing scheduled job."""
        from db.models import ScheduledJob

        try:
            session = create_session()
            job = session.get(ScheduledJob, job_id)

            if not job:
                session.close()
                return {
                    'success': False,
                    'message': f'Job with ID {job_id} not found'
                }

            # Update fields
            if 'name' in job_data:
                job.name = job_data['name']
            if 'description' in job_data:
                job.description = job_data['description']
            if 'job_type' in job_data:
                job.job_type = job_data['job_type']
            if 'schedule_cron' in job_data:
                job.schedule_cron = job_data['schedule_cron']
            if 'config' in job_data:
                job.config = json.dumps(job_data['config'])
            if 'enabled' in job_data:
                job.enabled = job_data['enabled']
            if 'priority' in job_data:
                job.priority = job_data['priority']
            if 'timeout_minutes' in job_data:
                job.timeout_minutes = job_data['timeout_minutes']
            if 'max_retries' in job_data:
                job.max_retries = job_data['max_retries']

            session.commit()
            session.close()

            logger.info(f"Updated scheduled job ID: {job_id}")

            return {
                'success': True,
                'message': f'Job updated successfully'
            }

        except Exception as e:
            logger.error(f"Error updating scheduled job: {e}")
            return {
                'success': False,
                'message': f'Error updating job: {str(e)}'
            }

    def delete_scheduled_job(self, job_id: int) -> Dict[str, Any]:
        """Delete a scheduled job."""
        from db.models import ScheduledJob

        try:
            session = create_session()
            job = session.get(ScheduledJob, job_id)

            if not job:
                session.close()
                return {
                    'success': False,
                    'message': f'Job with ID {job_id} not found'
                }

            job_name = job.name
            session.delete(job)
            session.commit()
            session.close()

            logger.info(f"Deleted scheduled job: {job_name} (ID: {job_id})")

            return {
                'success': True,
                'message': f'Job "{job_name}" deleted successfully'
            }

        except Exception as e:
            logger.error(f"Error deleting scheduled job: {e}")
            return {
                'success': False,
                'message': f'Error deleting job: {str(e)}'
            }

    def toggle_scheduled_job(self, job_id: int, enabled: bool) -> Dict[str, Any]:
        """Enable or disable a scheduled job."""
        from db.models import ScheduledJob

        try:
            session = create_session()
            job = session.get(ScheduledJob, job_id)

            if not job:
                session.close()
                return {
                    'success': False,
                    'message': f'Job with ID {job_id} not found'
                }

            job.enabled = enabled
            session.commit()
            session.close()

            status = 'enabled' if enabled else 'disabled'
            logger.info(f"Job {job_id} {status}")

            return {
                'success': True,
                'message': f'Job {status} successfully'
            }

        except Exception as e:
            logger.error(f"Error toggling scheduled job: {e}")
            return {
                'success': False,
                'message': f'Error: {str(e)}'
            }

    def get_job_execution_logs(self, job_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get job execution logs."""
        from db.models import JobExecutionLog

        try:
            session = create_session()

            if job_id:
                stmt = select(JobExecutionLog).where(
                    JobExecutionLog.job_id == job_id
                ).order_by(JobExecutionLog.started_at.desc()).limit(limit)
            else:
                stmt = select(JobExecutionLog).order_by(
                    JobExecutionLog.started_at.desc()
                ).limit(limit)

            logs = session.scalars(stmt).all()

            result = []
            for log in logs:
                result.append({
                    'id': log.id,
                    'job_id': log.job_id,
                    'started_at': log.started_at.isoformat() if log.started_at else None,
                    'completed_at': log.completed_at.isoformat() if log.completed_at else None,
                    'duration_seconds': log.duration_seconds,
                    'status': log.status,
                    'items_found': log.items_found,
                    'items_new': log.items_new,
                    'items_updated': log.items_updated,
                    'items_skipped': log.items_skipped,
                    'errors_count': log.errors_count,
                    'output_log': log.output_log,
                    'error_log': log.error_log,
                    'triggered_by': log.triggered_by,
                })

            session.close()
            return result

        except Exception as e:
            logger.error(f"Error fetching job execution logs: {e}")
            return []

    def get_scheduler_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        from db.models import ScheduledJob, JobExecutionLog
        from sqlalchemy import func as sql_func

        try:
            session = create_session()

            # Total jobs
            total_jobs = session.query(sql_func.count(ScheduledJob.id)).scalar() or 0

            # Active jobs
            active_jobs = session.query(sql_func.count(ScheduledJob.id)).where(
                ScheduledJob.enabled == True
            ).scalar() or 0

            # Failed jobs in last 24h
            yesterday = datetime.now() - timedelta(days=1)
            failed_24h = session.query(sql_func.count(JobExecutionLog.id)).where(
                and_(
                    JobExecutionLog.status == 'failed',
                    JobExecutionLog.started_at >= yesterday
                )
            ).scalar() or 0

            session.close()

            return {
                'total_jobs': total_jobs,
                'active_jobs': active_jobs,
                'running_jobs': 0,  # Would need scheduler service integration
                'failed_24h': failed_24h
            }

        except Exception as e:
            logger.error(f"Error fetching scheduler stats: {e}")
            return {
                'total_jobs': 0,
                'active_jobs': 0,
                'running_jobs': 0,
                'failed_24h': 0
            }

    def clear_database(self) -> Dict[str, Any]:
        """
        Clear all companies from the database (for testing purposes).

        Returns:
            Dict with keys:
            - success: Boolean indicating if operation completed successfully
            - deleted_count: Number of companies deleted
            - message: Status message
        """
        logger.warning("Clearing all companies from database")

        try:
            session = create_session()

            # Count companies before deletion
            count_stmt = select(func.count(Company.id))
            deleted_count = session.execute(count_stmt).scalar() or 0

            # Delete all companies
            from sqlalchemy import delete
            delete_stmt = delete(Company)
            session.execute(delete_stmt)
            session.commit()
            session.close()

            logger.info(f"Cleared {deleted_count} companies from database")

            return {
                'success': True,
                'deleted_count': deleted_count,
                'message': f'Successfully deleted {deleted_count} companies from database'
            }

        except Exception as e:
            logger.error(f"Error clearing database: {e}", exc_info=True)
            return {
                'success': False,
                'deleted_count': 0,
                'message': f'Error clearing database: {str(e)}'
            }

    def count_yp_targets_by_status(self, status: str) -> int:
        """
        Count YP targets by status.

        Args:
            status: Target status to count (e.g., 'planned', 'scraping', 'done')

        Returns:
            Count of targets with the specified status
        """
        try:
            from sqlalchemy import text
            session = create_session()

            query = text("SELECT COUNT(*) FROM yp_targets WHERE status = :status")
            count = session.execute(query, {"status": status}).scalar() or 0

            session.close()
            return count

        except Exception as e:
            logger.error(f"Error counting YP targets by status '{status}': {e}", exc_info=True)
            return 0


# Global backend instance
backend = BackendFacade()
