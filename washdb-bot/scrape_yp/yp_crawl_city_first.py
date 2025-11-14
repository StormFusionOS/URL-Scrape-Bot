#!/usr/bin/env python3
"""
Yellow Pages city-first crawler for washdb-bot.

This module implements the city-first scraping strategy:
- Reads targets from yp_targets table (city × category combinations)
- Uses shallow pagination (1-3 pages per city based on population tier)
- Implements early-exit (stops if page 1 has zero accepted results)
- Updates target status as it progresses

Usage:
    from scrape_yp.yp_crawl_city_first import crawl_city_targets
    results, stats = crawl_city_targets(state_ids=['RI'], min_score=50.0)
"""

import time
import random
from datetime import datetime
from typing import Generator, Optional
from urllib.parse import urlparse

from db.models import YPTarget, canonicalize_url, domain_from_url
from runner.logging_setup import get_logger
# City-first has its own fetch functions (fetch_city_category_page, _fetch_url_playwright)
# No need to import from old yp_client
from scrape_yp.yp_parser_enhanced import parse_yp_results_enhanced
from scrape_yp.yp_filter import YPFilter
from scrape_yp.yp_stealth import (
    get_playwright_context_params,
    human_delay,
    get_exponential_backoff_delay,
    get_enhanced_playwright_init_scripts,
    get_human_reading_delay,
    get_scroll_delays,
    SessionBreakManager,
)
from scrape_yp.yp_monitor import ScraperMonitor

# Initialize logger
logger = get_logger("yp_crawl_city_first")


def fetch_city_category_page(url: str, page: int = 1, use_playwright: bool = True, max_retries: int = 3) -> str:
    """
    Fetch a city-category page from Yellow Pages with retry logic.

    Args:
        url: Base URL (primary or fallback)
        page: Page number (default: 1)
        use_playwright: Use Playwright for fetching (default: True)
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        HTML content as string

    Raises:
        Exception: If all retry attempts fail
    """
    # Append page parameter if page > 1
    if page > 1:
        if "?" in url:
            url = f"{url}&page={page}"
        else:
            url = f"{url}?page={page}"

    logger.debug(f"Fetching URL: {url}")

    # Retry logic with exponential backoff
    last_exception = None
    for attempt in range(max_retries):
        try:
            # Use Playwright if enabled
            if use_playwright:
                return _fetch_url_playwright(url)
            else:
                # Fallback: Use requests library
                import requests

                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                }

                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()

                return response.text

        except Exception as e:
            last_exception = e
            logger.warning(f"Fetch attempt {attempt + 1}/{max_retries} failed: {e}")

            if attempt < max_retries - 1:
                # Calculate exponential backoff delay
                backoff_delay = get_exponential_backoff_delay(attempt, base_delay=2.0, max_delay=30.0)
                logger.info(f"Retrying in {backoff_delay:.1f} seconds...")
                time.sleep(backoff_delay)
            else:
                # Last attempt failed
                logger.error(f"All {max_retries} fetch attempts failed for {url}")
                raise last_exception


def _fetch_url_playwright(url: str) -> str:
    """
    Fetch a URL using Playwright (headless browser) with anti-detection measures.

    Args:
        url: Full URL to fetch

    Returns:
        HTML content as string
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

    # Add human-like random delay with jitter (2-5 seconds + jitter)
    human_delay(min_seconds=2.0, max_seconds=5.0, jitter=0.5)

    with sync_playwright() as p:
        # Launch browser with anti-detection flags
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',  # Hide automation
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-web-security',
                '--no-sandbox',
            ]
        )

        # Get randomized context parameters (user agent, viewport, timezone, etc.)
        context_params = get_playwright_context_params()
        context = browser.new_context(**context_params)

        # Add all enhanced anti-detection scripts
        init_scripts = get_enhanced_playwright_init_scripts()
        for script in init_scripts:
            context.add_init_script(script)

        page = context.new_page()

        try:
            # Navigate to URL with timeout
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for results to load
            try:
                page.wait_for_selector("div.result, div.srp-listing, div.organic", timeout=5000)
            except PlaywrightTimeoutError:
                # No results found, but page loaded
                pass

            # Simulate human behavior: scroll through page
            scroll_delays = get_scroll_delays()
            for i, scroll_delay in enumerate(scroll_delays):
                # Scroll down in increments (simulate reading)
                scroll_amount = random.randint(200, 600)
                page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                time.sleep(scroll_delay)

            # Simulate human reading the page
            # Estimate content length for reading delay
            html_preview = page.content()
            content_length = len(html_preview) // 2  # Rough estimate of visible content
            reading_delay = get_human_reading_delay(min(content_length, 2000))

            # Take a portion of the reading delay (we already scrolled)
            remaining_delay = reading_delay * random.uniform(0.3, 0.6)
            time.sleep(remaining_delay)

            # Get HTML content
            html = page.content()

            return html

        finally:
            browser.close()


def crawl_single_target(
    target: YPTarget,
    session,
    yp_filter: YPFilter,
    min_score: float = 40.0,
    include_sponsored: bool = False,
    use_fallback_on_404: bool = True,
    monitor: Optional[ScraperMonitor] = None,
) -> tuple[list[dict], dict]:
    """
    Crawl a single target (city × category).

    Implements pagination with smart exit logic:
    - Fetches pages 1 to max_pages
    - Stops early if page has 0 parsed results (empty page)
    - Stops if page has all duplicate results (domain dedup)
    - Updates target status in database

    Args:
        target: YPTarget database object
        session: SQLAlchemy session
        yp_filter: YPFilter instance for filtering
        min_score: Minimum confidence score (0-100)
        include_sponsored: Include sponsored/ad listings
        use_fallback_on_404: Use fallback URL if primary fails

    Returns:
        Tuple of (accepted_results, stats_dict)
    """
    logger.info(
        f"Crawling target: {target.city}, {target.state_id} - {target.category_label} "
        f"(max_pages={target.max_pages}, priority={target.priority})"
    )

    # Update target status to in_progress
    target.status = "in_progress"
    target.last_attempt_ts = datetime.utcnow()
    target.attempts += 1
    session.commit()

    all_results = []
    seen_domains = set()
    seen_websites = set()
    total_parsed = 0
    total_filtered_out = 0
    url_to_use = target.primary_url
    used_fallback = False

    try:
        for page in range(1, target.max_pages + 1):
            logger.info(f"  Fetching page {page}/{target.max_pages}...")

            try:
                # Fetch page HTML
                html = fetch_city_category_page(url_to_use, page)

                # Record successful request
                if monitor:
                    monitor.record_request(success=True, html=html)

                # Parse results with enhanced parser
                results = parse_yp_results_enhanced(html)
                total_parsed += len(results)

                if not results:
                    logger.info(f"  No results found on page {page}")
                    if page == 1 and use_fallback_on_404 and not used_fallback:
                        # Try fallback URL
                        logger.info(f"  Trying fallback URL...")
                        url_to_use = target.fallback_url
                        used_fallback = True
                        html = fetch_city_category_page(url_to_use, page)

                        # Record fallback request
                        if monitor:
                            monitor.record_request(success=True, html=html)

                        results = parse_yp_results_enhanced(html)
                        total_parsed += len(results)

                        if not results:
                            logger.info(f"  Fallback URL also returned no results")
                            break
                    else:
                        break

                logger.info(f"  Parsed {len(results)} results from page {page}")

                # Apply filter
                filtered_results, filter_stats = yp_filter.filter_listings(
                    results,
                    min_score=min_score,
                    include_sponsored=include_sponsored
                )

                logger.info(
                    f"  Filter: {filter_stats['accepted']} accepted, "
                    f"{filter_stats['rejected']} rejected"
                )
                total_filtered_out += filter_stats['rejected']

                # Record results for monitoring
                if monitor:
                    monitor.record_results(
                        found=len(results),
                        accepted=filter_stats['accepted'],
                        filtered=filter_stats['rejected']
                    )

                # Note: Early-exit logic removed to allow pagination even when filters reject all results
                # This ensures we don't stop pagination just because our filters are strict
                # We only stop when YP actually has no more results (handled by empty page check above)

                # Process filtered results
                new_results = 0
                for result in filtered_results:
                    # Add source and location metadata
                    result["source"] = "YP"
                    result["city"] = target.city
                    result["state"] = target.state_id

                    # Normalize and add domain if website exists
                    if result.get("website"):
                        try:
                            # Canonicalize URL
                            canonical = canonicalize_url(result["website"])
                            result["website"] = canonical

                            # Extract domain
                            result["domain"] = domain_from_url(canonical)

                            # Check for duplicates
                            if result["domain"] in seen_domains:
                                logger.debug(f"  Skipping duplicate domain: {result['domain']}")
                                continue

                            if result["website"] in seen_websites:
                                logger.debug(f"  Skipping duplicate website: {result['website']}")
                                continue

                            # Mark as seen
                            seen_domains.add(result["domain"])
                            seen_websites.add(result["website"])

                        except Exception as e:
                            logger.warning(f"  Failed to normalize URL '{result['website']}': {e}")
                            continue
                    else:
                        # No website - skip
                        logger.debug(f"  Skipping business without website: {result.get('name')}")
                        continue

                    # Add to results
                    all_results.append(result)
                    new_results += 1

                logger.info(f"  Added {new_results} new unique results from page {page}")

                # If no new results were added, end pagination
                if new_results == 0:
                    logger.info(f"  No new unique results found. Ending pagination.")
                    break

            except Exception as e:
                logger.error(f"  Error fetching page {page}: {e}")

                # Record failed request
                if monitor:
                    monitor.record_request(success=False, html="")

                # Continue to next page or end
                if page == 1:
                    # First page failed - try fallback if available
                    if use_fallback_on_404 and not used_fallback:
                        logger.info(f"  Trying fallback URL after error...")
                        url_to_use = target.fallback_url
                        used_fallback = True
                        continue
                    else:
                        # Can't proceed
                        target.status = "failed"
                        target.note = f"error_page1: {str(e)[:200]}"
                        session.commit()
                        raise
                else:
                    # Later page failed - just stop pagination
                    logger.warning(f"  Stopping pagination due to error on page {page}")
                    break

        # Mark target as done
        target.status = "done"
        target.note = f"completed_{len(all_results)}_results" if all_results else "completed_no_results"
        session.commit()

        # Summary stats
        stats = {
            'total_parsed': total_parsed,
            'total_filtered_out': total_filtered_out,
            'total_accepted': len(all_results),
            'acceptance_rate': (len(all_results) / total_parsed * 100) if total_parsed > 0 else 0,
            'early_exit': False,
            'pages_fetched': page,
            'used_fallback': used_fallback,
        }

        logger.info(
            f"Target complete: {target.city}, {target.state_id} - {target.category_label} | "
            f"pages={page}, parsed={total_parsed}, accepted={len(all_results)} "
            f"({stats['acceptance_rate']:.1f}%)"
        )

        return all_results, stats

    except Exception as e:
        logger.error(f"Target failed: {target.city}, {target.state_id} - {target.category_label} | {e}")
        target.status = "failed"
        target.note = f"error: {str(e)[:200]}"
        session.commit()
        raise


def crawl_city_targets(
    state_ids: list[str],
    session,
    min_score: float = 40.0,
    include_sponsored: bool = False,
    max_targets: Optional[int] = None,
    progress_callback: Optional[callable] = None,
    use_session_breaks: bool = True,
    use_monitoring: bool = True,
    use_adaptive_rate_limiting: bool = True,
) -> Generator[dict, None, None]:
    """
    Crawl all targets for specified states.

    Reads targets from yp_targets table and processes them in priority order.

    Args:
        state_ids: List of 2-letter state codes (e.g., ['RI', 'CA'])
        session: SQLAlchemy session
        min_score: Minimum confidence score (0-100)
        include_sponsored: Include sponsored/ad listings
        max_targets: Optional limit on number of targets to process
        progress_callback: Optional callback(target_index, total_targets, target, results, stats)
        use_session_breaks: Take breaks every 50 requests (default: True)

    Yields:
        Dict with keys:
        - target: YPTarget object
        - results: List of accepted business dicts
        - stats: Dict with parsing/filtering stats
    """
    logger.info(f"Starting city-first crawl for states: {', '.join(state_ids)}")

    # Initialize filter
    yp_filter = YPFilter()

    # Initialize session break manager
    session_break_mgr = SessionBreakManager(requests_per_session=50) if use_session_breaks else None

    # Initialize monitoring system
    monitor = ScraperMonitor(
        enable_adaptive_rate_limiting=use_adaptive_rate_limiting,
        base_delay=5.0
    ) if use_monitoring else None

    if monitor:
        logger.info("Monitoring enabled: tracking metrics, health, and adaptive rate limiting")

    # Query targets (status='planned', ordered by priority)
    query = (
        session.query(YPTarget)
        .filter(
            YPTarget.state_id.in_(state_ids),
            YPTarget.status == "planned"
        )
        .order_by(YPTarget.priority.asc(), YPTarget.id.asc())
    )

    if max_targets:
        query = query.limit(max_targets)

    targets = query.all()
    total_targets = len(targets)

    logger.info(f"Found {total_targets} targets to process")

    if total_targets == 0:
        logger.warning("No planned targets found. Generate targets first with generate_city_targets.py")
        return

    total_results = 0
    total_early_exits = 0
    total_errors = 0

    for idx, target in enumerate(targets, 1):
        logger.info(f"\n{'='*80}")
        logger.info(f"Target {idx}/{total_targets}")

        try:
            # Crawl single target
            results, stats = crawl_single_target(
                target,
                session,
                yp_filter,
                min_score=min_score,
                include_sponsored=include_sponsored,
                monitor=monitor,
            )

            total_results += len(results)
            if stats.get('early_exit'):
                total_early_exits += 1

            # Yield batch
            yield {
                'target': target,
                'results': results,
                'stats': stats,
            }

            # Call progress callback if provided
            if progress_callback:
                progress_callback(idx, total_targets, target, results, stats)

            # Check if we should take a session break
            if session_break_mgr:
                session_break_mgr.increment()

        except Exception as e:
            logger.error(f"Failed to crawl target {idx}/{total_targets}: {e}")
            total_errors += 1
            # Rollback session to recover from errors
            session.rollback()
            # Refresh target to get latest state from DB
            try:
                session.refresh(target)
            except Exception:
                pass  # Target may have been deleted
            continue

        # Rate limiting: delay between targets
        if idx < total_targets:
            if monitor and use_adaptive_rate_limiting:
                # Use adaptive delay
                delay = monitor.get_delay()
                logger.info(f"Waiting {delay:.1f}s (adaptive) before next target...")
            else:
                # Random delay between 5-15 seconds
                delay = random.uniform(5, 15)
                logger.info(f"Waiting {delay:.1f}s before next target...")
            time.sleep(delay)

        # Periodic health check (every 10 targets)
        if monitor and idx % 10 == 0:
            status, issues, recommendations = monitor.check_health()

            logger.info(f"Health check #{idx//10}: {status.upper()}")

            if issues:
                logger.warning(f"Issues detected ({len(issues)}):")
                for issue in issues:
                    logger.warning(f"  - {issue}")

            if status in ('unhealthy', 'critical'):
                logger.error(f"Scraper health is {status}!")
                if recommendations:
                    logger.info("Recommendations:")
                    for rec in recommendations[:3]:
                        logger.info(f"  {rec}")

            if status == 'critical':
                logger.critical("CRITICAL health status - consider stopping!")

            # Log summary
            summary = monitor.get_summary()
            logger.info(
                f"Stats: {summary['success_rate']:.1f}% success, "
                f"{summary['captcha_rate']:.1f}% CAPTCHA, "
                f"{summary['requests_per_minute']:.1f} req/min"
            )

    # Final summary
    logger.info(f"\n{'='*80}")
    logger.info(f"City-first crawl complete!")
    logger.info(f"  States: {', '.join(state_ids)}")
    logger.info(f"  Targets processed: {total_targets}")
    logger.info(f"  Total results: {total_results}")
    logger.info(f"  Early exits: {total_early_exits}")
    logger.info(f"  Errors: {total_errors}")

    # Monitoring summary
    if monitor:
        logger.info(f"\n{'='*80}")
        logger.info("MONITORING SUMMARY")
        logger.info(f"{'='*80}")

        summary = monitor.get_summary()

        # Overall health
        status_emoji = {
            'healthy': '✅',
            'degraded': '⚠️',
            'unhealthy': '🔴',
            'critical': '🚨'
        }
        logger.info(f"\nHealth Status: {status_emoji.get(summary['status'], '❓')} {summary['status'].upper()}")

        # Request metrics
        logger.info(f"\nRequest Metrics:")
        logger.info(f"  Total requests: {summary['total_requests']}")
        logger.info(f"  Success rate: {summary['success_rate']:.1f}%")
        logger.info(f"  Recent success rate: {summary['recent_success_rate']:.1f}%")
        logger.info(f"  CAPTCHA rate: {summary['captcha_rate']:.1f}%")
        logger.info(f"  Requests/min: {summary['requests_per_minute']:.1f}")

        # Results metrics
        logger.info(f"\nResult Metrics:")
        logger.info(f"  Results found: {summary['results_found']}")
        logger.info(f"  Results accepted: {summary['results_accepted']}")
        logger.info(f"  Acceptance rate: {summary['acceptance_rate']:.1f}%")

        # Rate limiting
        if summary['current_delay']:
            logger.info(f"\nRate Limiting:")
            logger.info(f"  Current delay: {summary['current_delay']:.1f}s")

        # Uptime
        uptime_hours = summary['uptime_seconds'] / 3600
        logger.info(f"\nUptime: {uptime_hours:.2f} hours")

        # Issues
        if summary['issues']:
            logger.info(f"\n⚠️  Issues Detected ({len(summary['issues'])}):")
            for issue in summary['issues']:
                logger.warning(f"  - {issue}")

        # Recommendations
        if summary['recommendations']:
            logger.info(f"\n💡 Recommendations:")
            for rec in summary['recommendations'][:5]:
                logger.info(f"  {rec}")

    logger.info(f"\n{'='*80}\n")
