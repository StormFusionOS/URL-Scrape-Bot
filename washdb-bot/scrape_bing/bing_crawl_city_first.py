#!/usr/bin/env python3
"""
Bing Local Search city-first crawler for washdb-bot.

This module implements the city-first scraping strategy for Bing Local Search:
- Reads targets from bing_targets table (city × category combinations)
- Uses Playwright with advanced anti-detection measures
- Implements session rotation and break management
- Updates target status as it progresses

Usage:
    from scrape_bing.bing_crawl_city_first import crawl_city_targets

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

from db.models import BingTarget, Company, canonicalize_url, domain_from_url
from runner.logging_setup import get_logger
from scrape_bing.bing_parse import BingLocalParser, parse_search_results
from scrape_bing.bing_filter import BingFilter
from scrape_google.google_stealth import (
    get_playwright_context_params,
    get_enhanced_playwright_init_scripts,
    human_delay,
    get_exponential_backoff_delay,
    get_human_reading_delay,
    get_scroll_delays,
    SessionBreakManager,
)

# Initialize logger
logger = get_logger("bing_crawl_city_first")


async def fetch_bing_local_search(
    search_query: str,
    max_results: int = 20,
    max_retries: int = 3
) -> tuple[str, list[dict]]:
    """
    Fetch Bing Local Search results for a query using Playwright.

    Args:
        search_query: Full search query (e.g., "window cleaning near Seattle, WA")
        max_results: Maximum number of results to extract
        max_retries: Maximum number of retry attempts

    Returns:
        Tuple of (html_content, results_list)

    Raises:
        Exception: If all retry attempts fail
    """
    logger.debug(f"Fetching Bing Local Search: {search_query}")

    # Build Bing Local Search URL
    # Format: https://www.bing.com/local?q={query}
    import urllib.parse
    encoded_query = urllib.parse.quote_plus(search_query)
    url = f"https://www.bing.com/local?q={encoded_query}"

    # Add LONGER human-like random delay before starting (increased from 2-5s to 5-10s)
    initial_delay = random.uniform(5.0, 10.0)
    logger.info(f"Waiting {initial_delay:.1f}s before starting (anti-bot measure)...")
    await asyncio.sleep(initial_delay)

    last_exception = None

    for attempt in range(max_retries):
        try:
            async with async_playwright() as p:
                # Launch browser with enhanced anti-detection
                # Use headless=new for better stealth (Chromium headless mode)
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-web-security',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--no-first-run',
                        '--no-zygote',
                        '--disable-gpu',
                    ],
                    # Use specific chromium channel for better compatibility
                    channel='chromium'
                )

                # Get randomized context parameters with MORE realistic settings
                context_params = get_playwright_context_params()

                # Override with MORE realistic settings
                context_params.update({
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'viewport': {'width': 1920, 'height': 1080},
                    'locale': 'en-US',
                    'timezone_id': 'America/New_York',
                    'permissions': ['geolocation'],
                    'geolocation': {'latitude': 41.8240, 'longitude': -71.4128},  # Providence, RI
                    'color_scheme': 'light',
                })

                context = await browser.new_context(**context_params)

                # Add all enhanced anti-detection scripts
                init_scripts = get_enhanced_playwright_init_scripts()
                for script in init_scripts:
                    await context.add_init_script(script)

                page = await context.new_page()

                try:
                    # Navigate to Bing Local Search
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                    # Check for bot detection / error page
                    html_content = await page.content()
                    page_title = await page.title()

                    # Detect Bing's error page
                    if "It's not you, it's us" in html_content or "isn't available right now" in html_content:
                        logger.error("🚨 BOT DETECTED! Bing is blocking us with error page")

                        # Save debug info (wrapped in try/except to not prevent exception)
                        try:
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            debug_dir = Path("logs/bing_debug")
                            debug_dir.mkdir(exist_ok=True)

                            # Save HTML
                            html_path = debug_dir / f"blocked_{timestamp}.html"
                            with open(html_path, 'w', encoding='utf-8') as f:
                                f.write(html_content)
                            logger.error(f"Saved blocked page HTML: {html_path}")

                            # Save screenshot
                            screenshot_path = debug_dir / f"blocked_{timestamp}.png"
                            await page.screenshot(path=str(screenshot_path))
                            logger.error(f"Saved blocked page screenshot: {screenshot_path}")

                            # Extract reference code for tracking
                            import re
                            ref_match = re.search(r'Ref A: ([A-F0-9]+)', html_content)
                            if ref_match:
                                logger.error(f"Bing Reference Code: {ref_match.group(1)}")
                        except Exception as save_error:
                            logger.warning(f"Failed to save bot detection debug files: {save_error}")

                        # Always raise the bot detection exception
                        raise Exception("Bing bot detection triggered - access blocked")

                    # Wait for results to load
                    try:
                        # Wait for the results container (Bing uses different selectors than Google)
                        await page.wait_for_selector('li.b_algo, div.bm_box, div.localEntityCard', timeout=10000)
                    except PlaywrightTimeoutError:
                        logger.warning("Search results container not found")

                        # Save debug info even when no error page is detected
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        debug_dir = Path("logs/bing_debug")
                        debug_dir.mkdir(exist_ok=True)

                        html_path = debug_dir / f"no_results_{timestamp}.html"
                        with open(html_path, 'w', encoding='utf-8') as f:
                            f.write(html_content)
                        logger.warning(f"Saved no-results HTML: {html_path}")

                        screenshot_path = debug_dir / f"no_results_{timestamp}.png"
                        await page.screenshot(path=str(screenshot_path))
                        logger.warning(f"Saved no-results screenshot: {screenshot_path}")

                        # Continue anyway, might still have results

                    # Simulate human behavior: scroll to load more results
                    scroll_delays = get_scroll_delays()
                    results_loaded = 0

                    for i, scroll_delay in enumerate(scroll_delays):
                        # Scroll down the page
                        try:
                            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')

                            # Wait for new results to load
                            await asyncio.sleep(scroll_delay)

                            # Count current results
                            result_cards = await page.query_selector_all('li.b_algo, div.bm_box')
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

                    # Extract business listings from search results
                    results = await parse_search_results(page)

                    # Limit results
                    results = results[:max_results]

                    # Get final HTML
                    html = await page.content()

                    logger.info(f"Extracted {len(results)} business listings from search")

                    return html, results

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
            error_msg = str(e)
            logger.warning(f"Fetch attempt {attempt + 1}/{max_retries} failed: {error_msg}")

            if attempt < max_retries - 1:
                # If bot detection triggered, use MUCH longer cooldown
                if "bot detection" in error_msg.lower() or "blocked" in error_msg.lower():
                    # Bot detected - wait 60-120 seconds before retry
                    cooldown = random.uniform(60.0, 120.0)
                    logger.error(f"🚨 Bot detected! Cooling down for {cooldown:.0f}s...")
                    await asyncio.sleep(cooldown)
                else:
                    # Calculate exponential backoff delay (increased base delay)
                    backoff_delay = get_exponential_backoff_delay(attempt, base_delay=10.0, max_delay=60.0)
                    logger.info(f"Retrying in {backoff_delay:.1f} seconds...")
                    await asyncio.sleep(backoff_delay)
            else:
                # Last attempt failed
                logger.error(f"All {max_retries} fetch attempts failed")
                raise last_exception


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
            canonical = canonicalize_url(website)
            existing = session.query(Company).filter_by(website=canonical).first()
            if existing:
                # Update existing company with Bing data
                logger.debug(f"Updating existing business with Bing data: {business_data.get('name')} ({canonical})")

                # Update Bing-specific fields
                if business_data.get('rating'):
                    existing.rating_bing = business_data['rating']
                if business_data.get('reviews_count'):
                    existing.reviews_bing = business_data['reviews_count']

                # Update other fields if they're better/newer
                if business_data.get('phone') and not existing.phone:
                    existing.phone = business_data['phone']
                if business_data.get('address') and not existing.address:
                    existing.address = business_data['address']

                existing.active = True
                session.commit()

                return existing.id

        # Create new company record
        company = Company(
            name=business_data.get('name', 'Unknown'),
            website=canonicalize_url(website) if website else None,
            domain=business_data.get('domain'),
            phone=business_data.get('phone'),
            address=business_data.get('address'),
            source='Bing',
            rating_bing=business_data.get('rating'),
            reviews_bing=business_data.get('reviews_count'),
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
    target: BingTarget,
    session,
    save_to_db: bool = True,
) -> tuple[list[dict], dict]:
    """
    Crawl a single target (city × category).

    Process:
    1. Update target status to IN_PROGRESS
    2. Fetch Bing Local Search results
    3. Extract business listings
    4. Check for duplicates by domain
    5. Save to companies table
    6. Update target status to DONE

    Args:
        target: BingTarget database object
        session: SQLAlchemy session
        save_to_db: Whether to save results to database

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
    seen_domains = set()
    total_found = 0
    total_saved = 0
    duplicates_skipped = 0
    filtered_out = 0
    captcha_detected = False

    # Initialize filter
    business_filter = BingFilter()

    try:
        # Fetch search results
        html, search_results = await fetch_bing_local_search(
            search_query=target.search_query,
            max_results=target.max_results
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

                # Add metadata
                business_data = business.copy()
                business_data['source'] = 'Bing'
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

                        # Check for duplicate domain in this batch
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
    save_to_db: bool = True,
    use_session_breaks: bool = True,
    checkpoint_interval: int = 10,
    recover_orphans: bool = True,
    orphan_timeout_minutes: int = 60,
):
    """
    Crawl all targets for specified states.

    Reads targets from bing_targets table and processes them in priority order.

    Args:
        state_ids: List of 2-letter state codes (e.g., ['RI', 'CA'])
        session: SQLAlchemy session
        max_targets: Optional limit on number of targets to process
        save_to_db: Whether to save results to database
        use_session_breaks: Take breaks every 50 requests (default: True)
        checkpoint_interval: Save checkpoint every N targets (default: 10)
        recover_orphans: Recover orphaned targets on startup (default: True)
        orphan_timeout_minutes: Minutes before marking target as orphaned (default: 60)

    Yields:
        Dict with keys:
        - target: BingTarget object
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
        orphaned = session.query(BingTarget).filter(
            BingTarget.state_id.in_(state_ids),
            BingTarget.status == "IN_PROGRESS",
            BingTarget.heartbeat_at < orphan_cutoff
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

    total_targets = session.query(BingTarget).filter(
        BingTarget.state_id.in_(state_ids)
    ).count()

    done_count = session.query(BingTarget).filter(
        BingTarget.state_id.in_(state_ids),
        BingTarget.status == "DONE"
    ).count()

    planned_count = session.query(BingTarget).filter(
        BingTarget.state_id.in_(state_ids),
        BingTarget.status == "PLANNED"
    ).count()

    failed_count = session.query(BingTarget).filter(
        BingTarget.state_id.in_(state_ids),
        BingTarget.status == "FAILED"
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
        session.query(BingTarget)
        .filter(
            BingTarget.state_id.in_(state_ids),
            BingTarget.status == "PLANNED"
        )
        .order_by(BingTarget.priority.asc(), BingTarget.id.asc())
    )

    if max_targets:
        query = query.limit(max_targets)

    targets = query.all()
    total_targets_to_process = len(targets)

    logger.info(f"Found {total_targets_to_process} targets to process")

    if total_targets_to_process == 0:
        logger.warning("No planned targets found. Generate targets first with generate_bing_targets.py")
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
            delay = random.uniform(45, 90)  # Bing: more conservative delays
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
