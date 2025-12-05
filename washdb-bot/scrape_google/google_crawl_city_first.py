#!/usr/bin/env python3
"""
Google Maps city-first crawler for washdb-bot.

This module implements the city-first scraping strategy for Google Maps:
- Reads targets from google_targets table (city × category combinations)
- Uses Playwright with advanced anti-detection measures
- Implements session rotation and break management
- Updates target status as it progresses

Usage:
    from scrape_google.google_crawl_city_first import crawl_city_targets

    async for batch in crawl_city_targets(
        state_ids=['RI'],
        session=db_session,
        max_results_per_target=20
    ):
        results = batch['results']
        stats = batch['stats']
"""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Generator, Optional, Dict, List
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from db.models import GoogleTarget, Company, canonicalize_url, domain_from_url
from runner.logging_setup import get_logger
from scrape_google.google_parse import GoogleMapsParser
from scrape_google.google_filter import GoogleFilter
from scrape_google.google_stealth import (
    get_playwright_context_params,
    get_enhanced_playwright_init_scripts,
    human_delay,
    get_exponential_backoff_delay,
    get_human_reading_delay,
    get_scroll_delays,
    SessionBreakManager,
)
from scrape_google.browser_pool import get_browser_pool
from scrape_google.html_cache import get_html_cache

# Initialize logger
logger = get_logger("google_crawl_city_first")


async def fetch_google_maps_search(
    search_query: str,
    max_results: int = 20,
    max_retries: int = 3,
    worker_id: int = 0
) -> tuple[str, list[dict]]:
    """
    Fetch Google Maps search results for a query using Playwright with browser pooling.

    Args:
        search_query: Full search query (e.g., "car wash near Seattle, WA")
        max_results: Maximum number of results to extract
        max_retries: Maximum number of retry attempts
        worker_id: Worker ID for browser pool isolation (default: 0)

    Returns:
        Tuple of (html_content, results_list)

    Raises:
        Exception: If all retry attempts fail
    """
    logger.debug(f"Fetching Google Maps search: {search_query}")

    # Build Google Maps search URL
    # Format: https://www.google.com/maps/search/{query}
    import urllib.parse
    encoded_query = urllib.parse.quote_plus(search_query)
    url = f"https://www.google.com/maps/search/{encoded_query}"

    # Add human-like random delay before starting
    await asyncio.sleep(random.uniform(2.0, 5.0))

    last_exception = None

    for attempt in range(max_retries):
        # Get browser pool (persistent browsers)
        pool = await get_browser_pool()
        page, context = await pool.get_page(worker_id)

        try:
            # Navigate to Google Maps search
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for search results to load
            try:
                # Wait for the results container
                await page.wait_for_selector('div[role="feed"]', timeout=10000)
            except PlaywrightTimeoutError:
                logger.warning("Search results container not found")
                # Continue anyway, might still have results

            # Simulate human behavior: scroll to load more results
            scroll_delays = get_scroll_delays()
            results_loaded = 0

            for i, scroll_delay in enumerate(scroll_delays):
                # Scroll within the results feed
                try:
                    feed = await page.query_selector('div[role="feed"]')
                    if feed:
                        # Scroll to bottom of feed
                        await page.evaluate('''
                            (feed) => {
                                const scrollEl = feed.parentElement;
                                if (scrollEl) {
                                    scrollEl.scrollTop = scrollEl.scrollHeight;
                                }
                            }
                        ''', feed)

                    # Wait for new results to load
                    await asyncio.sleep(scroll_delay)

                    # Count current results
                    result_cards = await page.query_selector_all('div[role="feed"] > div > div > a')
                    results_loaded = len(result_cards)

                    logger.debug(f"Scroll {i+1}: {results_loaded} results loaded")

                    # Stop scrolling if we have enough results
                    if results_loaded >= max_results:
                        break

                except Exception as e:
                    logger.warning(f"Error during scroll {i+1}: {e}")
                    break

            # Simulate reading the page
            html_preview = await page.content()
            content_length = len(html_preview) // 2
            reading_delay = get_human_reading_delay(min(content_length, 2000))
            await asyncio.sleep(reading_delay * random.uniform(0.3, 0.6))

            # Extract business cards from search results
            results = await extract_search_results(page, max_results)

            # Get final HTML
            html = await page.content()

            logger.info(f"Extracted {len(results)} business cards from search")

            return html, results

        except Exception as e:
            last_exception = e
            logger.warning(f"Fetch attempt {attempt + 1}/{max_retries} failed: {e}")

            if attempt < max_retries - 1:
                # Calculate exponential backoff delay
                backoff_delay = get_exponential_backoff_delay(attempt, base_delay=3.0, max_delay=30.0)
                logger.info(f"Retrying in {backoff_delay:.1f} seconds...")
                await asyncio.sleep(backoff_delay)
            else:
                # Last attempt failed
                logger.error(f"All {max_retries} fetch attempts failed")
                raise last_exception
        finally:
            # Close context and page (browser persists in pool)
            try:
                if page:
                    await page.close()
            except Exception as e:
                logger.debug(f"Error closing page: {e}")

            try:
                if context:
                    await context.close()
            except Exception as e:
                logger.debug(f"Error closing context: {e}")


async def extract_search_results(page, max_results: int) -> list[dict]:
    """
    Extract business information from Google Maps search results.

    Args:
        page: Playwright Page object
        max_results: Maximum number of results to extract

    Returns:
        List of business dictionaries with basic info (name, address, rating, etc.)
    """
    results = []

    try:
        # Find all result cards in the feed
        result_cards = await page.query_selector_all('div[role="feed"] > div > div > a')

        logger.debug(f"Found {len(result_cards)} result cards")

        for idx, card in enumerate(result_cards[:max_results]):
            try:
                # Extract data attributes and aria-labels
                aria_label = await card.get_attribute('aria-label')
                href = await card.get_attribute('href')

                if not aria_label:
                    continue

                # Parse aria-label which contains: "Name · Rating · Category · Address"
                # Example: "ABC Car Wash · 4.5⭐ · Car wash · 123 Main St, Seattle, WA"

                business = {
                    'aria_label': aria_label,
                    'url': href if href and href.startswith('http') else None,
                }

                # Try to extract place_id from URL
                if href:
                    import re
                    # Google Maps URLs contain place_id like: /maps/place/...data=...1s0x123:0x456...
                    # or !1s followed by the place ID
                    place_id_match = re.search(r'!1s([^!]+)', href)
                    if place_id_match:
                        business['place_id'] = place_id_match.group(1)

                # Parse aria-label to extract structured data
                parts = aria_label.split(' · ')
                if len(parts) >= 1:
                    business['name'] = parts[0].strip()

                if len(parts) >= 2:
                    # Rating (e.g., "4.5⭐" or "4.5 stars")
                    rating_text = parts[1].strip()
                    import re
                    rating_match = re.search(r'(\d+\.?\d*)', rating_text)
                    if rating_match:
                        try:
                            business['rating'] = float(rating_match.group(1))
                        except ValueError:
                            pass

                if len(parts) >= 3:
                    business['category'] = parts[2].strip()

                if len(parts) >= 4:
                    # Remaining parts are usually address
                    business['address'] = ' · '.join(parts[3:]).strip()

                results.append(business)

            except Exception as e:
                logger.warning(f"Error extracting result card {idx}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error extracting search results: {e}")

    return results


async def scrape_business_details(business_url: str, max_retries: int = 2) -> dict:
    """
    Scrape detailed information from a Google Maps business page.

    Args:
        business_url: Google Maps business URL
        max_retries: Maximum retry attempts

    Returns:
        Dictionary with detailed business information
    """
    logger.debug(f"Scraping business details: {business_url}")

    await asyncio.sleep(random.uniform(1.5, 3.0))

    last_exception = None

    for attempt in range(max_retries):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security',
                        '--no-sandbox',
                    ]
                )

                context_params = get_playwright_context_params()
                context = await browser.new_context(**context_params)

                init_scripts = get_enhanced_playwright_init_scripts()
                for script in init_scripts:
                    await context.add_init_script(script)

                page = await context.new_page()

                try:
                    await page.goto(business_url, wait_until="domcontentloaded", timeout=20000)

                    # Wait for business info to load
                    await asyncio.sleep(random.uniform(2.0, 4.0))

                    # Use GoogleMapsParser to extract all fields
                    details = await GoogleMapsParser.extract_all_fields(page)

                    return details

                finally:
                    # Close resources in correct order: page → context → browser
                    try:
                        if page:
                            await page.close()
                    except Exception as e:
                        logger.debug(f"Error closing page: {e}")

                    try:
                        if context:
                            await context.close()
                    except Exception as e:
                        logger.debug(f"Error closing context: {e}")

                    try:
                        await browser.close()
                    except Exception as e:
                        logger.debug(f"Error closing browser: {e}")

        except Exception as e:
            last_exception = e
            logger.warning(f"Detail scrape attempt {attempt + 1}/{max_retries} failed: {e}")

            if attempt < max_retries - 1:
                backoff_delay = get_exponential_backoff_delay(attempt, base_delay=2.0, max_delay=15.0)
                await asyncio.sleep(backoff_delay)
            else:
                logger.error(f"Failed to scrape business details after {max_retries} attempts")
                return {}


def save_business_to_db(business_data: dict, session) -> Optional[int]:
    """
    Save business to companies table.

    Args:
        business_data: Business information dictionary
        session: SQLAlchemy session

    Returns:
        Company ID if saved successfully, None otherwise
    """
    try:
        # Check if business already exists by website
        website = business_data.get('website')
        if website:
            existing = session.query(Company).filter_by(website=website).first()
            if existing:
                logger.debug(f"Business already exists in DB: {business_data.get('name')} ({website})")
                return existing.id

        # Create new company record
        company = Company(
            name=business_data.get('name', 'Unknown'),
            website=website,
            domain=business_data.get('domain'),
            phone=business_data.get('phone'),
            address=business_data.get('address'),
            source='Google',
            rating_google=business_data.get('rating'),
            reviews_google=business_data.get('reviews_count'),
            active=True,
        )

        session.add(company)
        session.commit()

        logger.debug(f"Saved business to DB: {company.name} (ID: {company.id})")
        return company.id

    except Exception as e:
        logger.error(f"Failed to save business to database: {e}")
        session.rollback()
        return None


async def crawl_single_target(
    target: GoogleTarget,
    session,
    scrape_details: bool = True,
    save_to_db: bool = True,
    worker_id: int = 0,
) -> tuple[list[dict], dict]:
    """
    Crawl a single target (city × category) with browser pooling.

    Process:
    1. Update target status to IN_PROGRESS
    2. Fetch Google Maps search results using persistent browser pool
    3. Extract business cards
    4. Optionally scrape detailed info for each business
    5. Check for duplicates by place_id
    6. Save to companies table
    7. Update target status to DONE

    Args:
        target: GoogleTarget database object
        session: SQLAlchemy session
        scrape_details: Whether to scrape detailed info for each business
        save_to_db: Whether to save results to database
        worker_id: Worker ID for browser pool isolation (default: 0)

    Returns:
        Tuple of (accepted_results, stats_dict)
    """
    logger.info(
        f"Crawling target: {target.city}, {target.state_id} - {target.category_label} "
        f"(max_results={target.max_results}, priority={target.priority})"
    )

    # Update target status
    target.status = "IN_PROGRESS"
    target.claimed_at = datetime.utcnow()
    target.heartbeat_at = datetime.utcnow()
    session.commit()

    all_results = []
    seen_place_ids = set()
    seen_domains = set()
    total_found = 0
    total_saved = 0
    duplicates_skipped = 0
    filtered_out = 0
    captcha_detected = False

    # Initialize filter
    business_filter = GoogleFilter()

    try:
        # Fetch search results (using browser pool)
        html, search_results = await fetch_google_maps_search(
            search_query=target.search_query,
            max_results=target.max_results,
            worker_id=worker_id
        )

        total_found = len(search_results)

        # Check for CAPTCHA
        if 'captcha' in html.lower() or 'unusual traffic' in html.lower():
            logger.warning("⚠️  CAPTCHA detected!")
            captcha_detected = True
            target.captcha_detected = True

        if not search_results:
            logger.info("No results found in search")
            target.status = "DONE"
            target.note = "completed_no_results"
            target.results_found = 0
            target.finished_at = datetime.utcnow()
            session.commit()

            return [], {
                'total_found': 0,
                'total_saved': 0,
                'duplicates_skipped': 0,
                'captcha_detected': captcha_detected
            }

        logger.info(f"Found {len(search_results)} businesses in search results")

        # Process each business
        for idx, business in enumerate(search_results, 1):
            try:
                logger.debug(f"Processing {idx}/{len(search_results)}: {business.get('name', 'Unknown')}")

                # Check for duplicate by place_id
                place_id = business.get('place_id')
                if place_id:
                    if place_id in seen_place_ids:
                        logger.debug(f"Duplicate place_id in batch: {place_id}")
                        duplicates_skipped += 1
                        continue

                    # Check database for existing place_id in companies table
                    if save_to_db:
                        from db.models import Company
                        # Check if we already have a company with this Google place_id
                        # Note: We store place_id in the 'notes' field or we can skip this check
                        # since we already do domain-based deduplication below
                        pass  # Rely on domain deduplication instead

                    seen_place_ids.add(place_id)

                # Scrape detailed info if requested
                business_data = business.copy()
                if scrape_details and business.get('url'):
                    logger.debug(f"Scraping details for: {business.get('name')}")
                    details = await scrape_business_details(business['url'])
                    business_data.update(details)

                # Add metadata
                business_data['source'] = 'Google'
                business_data['city'] = target.city
                business_data['state'] = target.state_id
                business_data['category_label'] = target.category_label
                business_data['category_keyword'] = target.category_keyword

                # Check for website and domain deduplication
                if business_data.get('website'):
                    try:
                        canonical = canonicalize_url(business_data['website'])
                        business_data['website'] = canonical
                        business_data['domain'] = domain_from_url(canonical)

                        # Check for duplicate domain
                        if business_data['domain'] in seen_domains:
                            logger.debug(f"Duplicate domain: {business_data['domain']}")
                            duplicates_skipped += 1
                            continue

                        seen_domains.add(business_data['domain'])

                    except Exception as e:
                        logger.warning(f"Failed to canonicalize URL '{business_data['website']}': {e}")
                        continue
                else:
                    logger.debug(f"Skipping business without website: {business_data.get('name')}")
                    continue

                # Apply quality filter
                filter_result = business_filter.filter_business(business_data)
                if not filter_result['passed']:
                    logger.info(f"FILTERED: {business_data.get('name')} - {filter_result['filter_reason']}")
                    filtered_out += 1
                    continue

                # Add confidence score to metadata
                business_data['confidence_score'] = filter_result['confidence']

                # Save to database if requested
                if save_to_db:
                    try:
                        company_id = save_business_to_db(business_data, session)
                        if company_id:
                            business_data['company_id'] = company_id
                            all_results.append(business_data)
                            total_saved += 1
                        else:
                            logger.warning(f"Failed to save {business_data.get('name')} to database")
                    except Exception as e:
                        logger.error(f"Failed to save business: {e}")
                else:
                    all_results.append(business_data)
                    total_saved += 1

            except Exception as e:
                logger.error(f"Error processing business {idx}: {e}")
                continue

        # Update target status to DONE
        target.status = "DONE"
        target.note = f"completed_{total_saved}_saved"
        target.results_found = total_found
        target.results_saved = total_saved
        target.duplicates_skipped = duplicates_skipped
        target.finished_at = datetime.utcnow()
        session.commit()

        stats = {
            'total_found': total_found,
            'total_saved': total_saved,
            'duplicates_skipped': duplicates_skipped,
            'filtered_out': filtered_out,
            'captcha_detected': captcha_detected,
        }

        logger.info(
            f"Target complete: {target.city}, {target.state_id} - {target.category_label} | "
            f"found={total_found}, saved={total_saved}, duplicates={duplicates_skipped}, filtered={filtered_out}"
        )

        return all_results, stats

    except Exception as e:
        logger.error(f"Target failed: {target.city}, {target.state_id} - {target.category_label} | {e}")
        target.status = "FAILED"
        target.last_error = str(e)[:500]
        target.note = f"error: {str(e)[:200]}"
        session.commit()
        raise


async def crawl_city_targets(
    state_ids: list[str],
    session,
    max_targets: Optional[int] = None,
    scrape_details: bool = True,
    save_to_db: bool = True,
    use_session_breaks: bool = True,
    checkpoint_interval: int = 10,
    recover_orphans: bool = True,
    orphan_timeout_minutes: int = 60,
):
    """
    Crawl all targets for specified states.

    Reads targets from google_targets table and processes them in priority order.

    Args:
        state_ids: List of 2-letter state codes (e.g., ['RI', 'CA'])
        session: SQLAlchemy session
        max_targets: Optional limit on number of targets to process
        scrape_details: Whether to scrape detailed info for each business
        save_to_db: Whether to save results to database
        use_session_breaks: Take breaks every 50 requests (default: True)
        checkpoint_interval: Save checkpoint every N targets (default: 10)
        recover_orphans: Recover orphaned targets on startup (default: True)
        orphan_timeout_minutes: Minutes before marking target as orphaned (default: 60)

    Yields:
        Dict with keys:
        - target: GoogleTarget object
        - results: List of business dicts
        - stats: Dict with scraping stats
    """
    logger.info(f"Starting city-first crawl for states: {', '.join(state_ids)}")

    # Recover orphaned targets (targets stuck in IN_PROGRESS)
    if recover_orphans:
        logger.info(f"\n{'='*80}")
        logger.info("ORPHAN RECOVERY")
        logger.info(f"{'='*80}")

        orphan_cutoff = datetime.utcnow() - timedelta(minutes=orphan_timeout_minutes)
        orphaned = session.query(GoogleTarget).filter(
            GoogleTarget.state_id.in_(state_ids),
            GoogleTarget.status == "IN_PROGRESS",
            GoogleTarget.heartbeat_at < orphan_cutoff
        ).all()

        for target in orphaned:
            target.status = "PLANNED"
            target.claimed_by = None
            target.claimed_at = None
            target.heartbeat_at = None

        session.commit()

        if len(orphaned) > 0:
            logger.warning(f"Recovered {len(orphaned)} orphaned targets")

        logger.info(f"{'='*80}\n")

    # Show current progress
    logger.info(f"\n{'='*80}")
    logger.info("CURRENT PROGRESS")
    logger.info(f"{'='*80}")

    total_targets = session.query(GoogleTarget).filter(
        GoogleTarget.state_id.in_(state_ids)
    ).count()

    done_count = session.query(GoogleTarget).filter(
        GoogleTarget.state_id.in_(state_ids),
        GoogleTarget.status == "DONE"
    ).count()

    planned_count = session.query(GoogleTarget).filter(
        GoogleTarget.state_id.in_(state_ids),
        GoogleTarget.status == "PLANNED"
    ).count()

    failed_count = session.query(GoogleTarget).filter(
        GoogleTarget.state_id.in_(state_ids),
        GoogleTarget.status == "FAILED"
    ).count()

    progress_pct = (done_count / total_targets * 100) if total_targets > 0 else 0

    logger.info(f"Total targets: {total_targets}")
    logger.info(f"Completed: {done_count} ({progress_pct:.1f}%)")
    logger.info(f"Remaining (planned): {planned_count}")
    logger.info(f"Failed: {failed_count}")
    logger.info(f"{'='*80}\n")

    # Initialize session break manager
    session_break_mgr = SessionBreakManager(requests_per_session=50) if use_session_breaks else None

    # Query targets (status='PLANNED', ordered by priority)
    query = (
        session.query(GoogleTarget)
        .filter(
            GoogleTarget.state_id.in_(state_ids),
            GoogleTarget.status == "PLANNED"
        )
        .order_by(GoogleTarget.priority.asc(), GoogleTarget.id.asc())
    )

    if max_targets:
        query = query.limit(max_targets)

    targets = query.all()
    total_targets_to_process = len(targets)

    logger.info(f"Found {total_targets_to_process} targets to process")

    if total_targets_to_process == 0:
        logger.warning("No planned targets found. Generate targets first with generate_city_targets.py")
        return

    total_results = 0
    total_errors = 0
    total_captchas = 0

    for idx, target in enumerate(targets, 1):
        logger.info(f"\n{'='*80}")
        logger.info(f"Target {idx}/{total_targets_to_process}")

        try:
            # Crawl single target
            results, stats = await crawl_single_target(
                target,
                session,
                scrape_details=scrape_details,
                save_to_db=save_to_db
            )

            total_results += len(results)
            if stats.get('captcha_detected'):
                total_captchas += 1

            # Yield batch
            yield {
                'target': target,
                'results': results,
                'stats': stats,
            }

            # Check if we should take a session break
            if session_break_mgr:
                took_break = await session_break_mgr.increment()
                if took_break:
                    logger.info(f"✓ Session break complete (break #{session_break_mgr.total_breaks})")

        except Exception as e:
            logger.error(f"Failed to crawl target {idx}/{total_targets_to_process}: {e}")
            total_errors += 1
            # Rollback session to recover from errors
            session.rollback()
            # Refresh target to get latest state from DB
            try:
                session.refresh(target)
            except Exception:
                pass
            continue

        # Rate limiting: delay between targets
        if idx < total_targets_to_process:
            delay = random.uniform(10, 20)
            logger.info(f"Waiting {delay:.1f}s before next target...")
            await asyncio.sleep(delay)

        # Periodic checkpoint
        if idx % checkpoint_interval == 0:
            logger.info(f"\n{'='*80}")
            logger.info(f"CHECKPOINT #{idx//checkpoint_interval}")
            logger.info(f"{'='*80}")
            logger.info(f"Progress: {idx}/{total_targets_to_process} targets processed")
            logger.info(f"Results collected: {total_results}")
            logger.info(f"Errors: {total_errors}")
            logger.info(f"CAPTCHAs detected: {total_captchas}")

            if total_captchas > 0:
                captcha_rate = (total_captchas / idx * 100)
                logger.warning(f"CAPTCHA rate: {captcha_rate:.1f}%")

                if captcha_rate > 10:
                    logger.error("⚠️  High CAPTCHA rate! Consider increasing delays or using proxies")

            logger.info(f"{'='*80}\n")

    # Final summary
    logger.info(f"\n{'='*80}")
    logger.info(f"City-first crawl complete!")
    logger.info(f"  States: {', '.join(state_ids)}")
    logger.info(f"  Targets processed: {total_targets_to_process}")
    logger.info(f"  Total results: {total_results}")
    logger.info(f"  Errors: {total_errors}")
    logger.info(f"  CAPTCHAs: {total_captchas}")
    logger.info(f"{'='*80}\n")
