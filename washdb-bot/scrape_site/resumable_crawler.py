#!/usr/bin/env python3
"""
Resumable site crawler with cursor-based state management.

Features:
- Saves crawl state after each page
- Resumes from last completed URL on restart
- Bounded queue (max 50 URLs)
- Idempotent state saving
"""

from datetime import datetime
from typing import Optional, Dict, List
from sqlalchemy.orm import Session
from sqlalchemy import select

from db.models import SiteCrawlState, domain_from_url
from runner.logging_setup import get_logger
from scrape_site.site_scraper import fetch_page, discover_internal_links
from scrape_site.site_parse import parse_site_content

logger = get_logger("resumable_crawler")

# Configuration
MAX_QUEUE_SIZE = 50
MAX_PAGES_PER_DOMAIN = 20
MAX_ERRORS_BEFORE_FAIL = 5


def get_or_create_crawl_state(session: Session, domain: str, website_url: str) -> SiteCrawlState:
    """
    Get existing crawl state or create new one for domain.

    Args:
        session: Database session
        domain: Domain being crawled (e.g., 'example.com')
        website_url: Homepage URL

    Returns:
        SiteCrawlState object
    """
    # Try to find existing state
    stmt = select(SiteCrawlState).where(SiteCrawlState.domain == domain)
    state = session.execute(stmt).scalar_one_or_none()

    if state:
        logger.info(f"Found existing crawl state for {domain} (phase={state.phase}, pages={state.pages_crawled})")
        return state

    # Create new state
    logger.info(f"Creating new crawl state for {domain}")
    state = SiteCrawlState(
        domain=domain,
        phase='parsing_home',
        last_completed_url=None,
        pending_queue={'urls': [website_url]},  # Start with homepage
        discovered_targets={'contact': [], 'about': [], 'services': []},
        pages_crawled=0,
        targets_found=0,
        errors_count=0
    )
    session.add(state)
    session.commit()
    return state


def save_cursor(session: Session, state: SiteCrawlState, last_url: str,
                pending_urls: List[str], discovered: Dict[str, List[str]]) -> None:
    """
    Save crawl cursor (idempotent).

    Args:
        session: Database session
        state: SiteCrawlState object
        last_url: Last URL successfully parsed
        pending_urls: List of URLs still to crawl (will be truncated to MAX_QUEUE_SIZE)
        discovered: Dict with discovered URLs by category
    """
    # Truncate queue if needed
    if len(pending_urls) > MAX_QUEUE_SIZE:
        logger.warning(f"Queue size {len(pending_urls)} exceeds max {MAX_QUEUE_SIZE}, truncating")
        pending_urls = pending_urls[:MAX_QUEUE_SIZE]

    # Update state
    state.last_completed_url = last_url
    state.pending_queue = {'urls': pending_urls}
    state.discovered_targets = discovered
    state.last_updated = datetime.now()

    session.commit()
    logger.debug(f"Saved cursor for {state.domain}: last={last_url}, queue_size={len(pending_urls)}")


def crawl_site_resumable(session: Session, domain: str, website_url: str) -> Dict:
    """
    Crawl a site with resumable state management.

    Phases:
        1. parsing_home: Parse homepage, discover internal links
        2. crawling_internal: Crawl discovered target pages (contact/about/services)
        3. done: All pages crawled successfully
        4. failed: Too many errors or max pages reached

    Args:
        session: Database session
        domain: Domain to crawl
        website_url: Homepage URL

    Returns:
        Dict with crawl results: {
            'domain': str,
            'phase': str,
            'pages_crawled': int,
            'targets_found': int,
            'discovered_data': dict,
            'completed': bool
        }
    """
    # Get or create crawl state
    state = get_or_create_crawl_state(session, domain, website_url)

    # Check if already complete
    if state.phase in ('done', 'failed'):
        logger.info(f"Crawl for {domain} already {state.phase}")
        return {
            'domain': domain,
            'phase': state.phase,
            'pages_crawled': state.pages_crawled,
            'targets_found': state.targets_found,
            'discovered_data': {},
            'completed': True
        }

    # Rebuild queue from saved state
    pending_urls = state.pending_queue.get('urls', []) if state.pending_queue else [website_url]
    discovered_targets = state.discovered_targets or {'contact': [], 'about': [], 'services': []}
    discovered_data = {}

    logger.info(f"Resuming crawl for {domain}: phase={state.phase}, queue_size={len(pending_urls)}, pages_done={state.pages_crawled}")

    try:
        # Crawl pending URLs
        while pending_urls and state.pages_crawled < MAX_PAGES_PER_DOMAIN:
            # Get next URL
            current_url = pending_urls.pop(0)

            # Check if already completed (skip duplicates)
            if state.last_completed_url == current_url:
                logger.debug(f"Skipping already completed URL: {current_url}")
                continue

            logger.info(f"Crawling [{state.pages_crawled + 1}/{MAX_PAGES_PER_DOMAIN}]: {current_url}")

            # Fetch page
            html = fetch_page(current_url)

            if not html:
                state.errors_count += 1
                state.last_error = f"Failed to fetch {current_url}"
                logger.warning(f"Failed to fetch {current_url} (errors: {state.errors_count})")

                # Check error threshold
                if state.errors_count >= MAX_ERRORS_BEFORE_FAIL:
                    logger.error(f"Too many errors ({state.errors_count}), marking as failed")
                    state.phase = 'failed'
                    state.completed_at = datetime.now()
                    session.commit()
                    break

                # Save cursor and continue
                save_cursor(session, state, current_url, pending_urls, discovered_targets)
                continue

            # Parse page
            page_data = parse_site_content(html, current_url)

            # Merge discovered data
            if page_data:
                for key, value in page_data.items():
                    if value and not discovered_data.get(key):
                        discovered_data[key] = value

            # Update pages crawled
            state.pages_crawled += 1

            # Phase 1: Parse homepage and discover internal links
            if state.phase == 'parsing_home':
                # Discover internal pages
                links = discover_internal_links(html, website_url)

                # Add discovered links to targets
                for category, urls in links.items():
                    if category in discovered_targets:
                        discovered_targets[category].extend(urls)
                        state.targets_found += len(urls)

                # Add target pages to pending queue
                all_targets = links.get('contact', []) + links.get('about', []) + links.get('services', [])
                for url in all_targets:
                    if url not in pending_urls and url != current_url:
                        pending_urls.append(url)

                # Move to next phase
                state.phase = 'crawling_internal'
                logger.info(f"Discovered {len(all_targets)} target pages, moving to crawling_internal phase")

            # Save cursor after each page
            save_cursor(session, state, current_url, pending_urls, discovered_targets)

        # Mark as done if queue is empty
        if not pending_urls or state.pages_crawled >= MAX_PAGES_PER_DOMAIN:
            state.phase = 'done'
            state.completed_at = datetime.now()
            session.commit()
            logger.info(f"✓ Crawl complete for {domain}: {state.pages_crawled} pages, {state.targets_found} targets")

        return {
            'domain': domain,
            'phase': state.phase,
            'pages_crawled': state.pages_crawled,
            'targets_found': state.targets_found,
            'discovered_data': discovered_data,
            'completed': state.phase in ('done', 'failed')
        }

    except Exception as e:
        logger.error(f"Error crawling {domain}: {e}")
        state.phase = 'failed'
        state.last_error = str(e)
        state.errors_count += 1
        state.completed_at = datetime.now()
        session.commit()
        raise


def reset_crawl_state(session: Session, domain: str) -> bool:
    """
    Reset crawl state for a domain (allows re-crawl).

    Args:
        session: Database session
        domain: Domain to reset

    Returns:
        bool: True if reset successfully, False if not found
    """
    stmt = select(SiteCrawlState).where(SiteCrawlState.domain == domain)
    state = session.execute(stmt).scalar_one_or_none()

    if not state:
        logger.warning(f"No crawl state found for {domain}")
        return False

    logger.info(f"Resetting crawl state for {domain}")
    session.delete(state)
    session.commit()
    return True


def get_crawl_status(session: Session, domain: str) -> Optional[Dict]:
    """
    Get crawl status for a domain.

    Args:
        session: Database session
        domain: Domain to check

    Returns:
        Dict with status info or None if not found
    """
    stmt = select(SiteCrawlState).where(SiteCrawlState.domain == domain)
    state = session.execute(stmt).scalar_one_or_none()

    if not state:
        return None

    return {
        'domain': state.domain,
        'phase': state.phase,
        'pages_crawled': state.pages_crawled,
        'targets_found': state.targets_found,
        'errors_count': state.errors_count,
        'last_error': state.last_error,
        'started_at': state.started_at.isoformat() if state.started_at else None,
        'last_updated': state.last_updated.isoformat() if state.last_updated else None,
        'completed_at': state.completed_at.isoformat() if state.completed_at else None,
        'can_resume': state.phase not in ('done', 'failed')
    }
