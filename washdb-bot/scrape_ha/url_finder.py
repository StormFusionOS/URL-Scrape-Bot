#!/usr/bin/env python3
"""
URL Finder Bot - Phase 2 of HomeAdvisor Discovery

Searches DuckDuckGo for external websites of businesses discovered from HomeAdvisor.
Updates database to replace temporary HomeAdvisor profile URLs with real external websites.
"""
from __future__ import annotations
import asyncio
import random
import re
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, Browser
from sqlalchemy import select

from db.models import Company, canonicalize_url, domain_from_url
from db.save_discoveries import create_session, normalize_phone
from runner.logging_setup import get_logger

logger = get_logger("url_finder")

# Delay between searches (seconds) to avoid rate limiting
MIN_SEARCH_DELAY = 8
MAX_SEARCH_DELAY = 15

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def extract_city_state_from_address(address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Extract city and state from address string.

    Args:
        address: Full address string (e.g., "123 Main St, Austin, TX 78701")

    Returns:
        Tuple of (city, state) or (None, None) if extraction fails

    Examples:
        >>> extract_city_state_from_address("123 Main St, Austin, TX 78701")
        ('Austin', 'TX')
        >>> extract_city_state_from_address("456 Oak Ave, Dallas, Texas 75201")
        ('Dallas', 'Texas')
    """
    if not address:
        return (None, None)

    # Try to match pattern: "City, State ZIP" or "City, State"
    # Look for comma-separated parts
    parts = [p.strip() for p in address.split(",")]

    if len(parts) < 2:
        return (None, None)

    # City is typically second-to-last or third-to-last part
    # State is typically last or second-to-last part

    # Try last part for state (might have ZIP)
    last_part = parts[-1].strip()

    # Extract state (2-letter code or full name)
    state_match = re.search(r'\b([A-Z]{2})\b', last_part)
    if state_match:
        state = state_match.group(1)
        # City is second-to-last part
        city = parts[-2].strip() if len(parts) >= 2 else None
        return (city, state)

    # Try full state name
    state_words = last_part.split()
    if state_words:
        state = state_words[0]
        city = parts[-2].strip() if len(parts) >= 2 else None
        return (city, state)

    return (None, None)


def build_search_query(name: str, address: Optional[str]) -> str:
    """
    Build DuckDuckGo search query for business.

    Args:
        name: Business name
        address: Full address string

    Returns:
        Search query string (e.g., "ABC Pressure Washing Austin TX")
    """
    city, state = extract_city_state_from_address(address)

    query_parts = [name]
    if city:
        query_parts.append(city)
    if state:
        query_parts.append(state)

    return " ".join(query_parts)


async def search_duckduckgo(page: Page, query: str) -> list[dict]:
    """
    Search DuckDuckGo and extract organic search results.

    Args:
        page: Playwright page instance
        query: Search query string

    Returns:
        List of dicts with keys: title, url, snippet
    """
    logger.info(f"[Search] Query: {query}")

    # Navigate to DuckDuckGo search
    search_url = f"https://duckduckgo.com/?q={query}"

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for search results to load
        await page.wait_for_selector("article[data-testid='result']", timeout=10000)

        # Extract organic results
        results = []
        articles = await page.query_selector_all("article[data-testid='result']")

        for article in articles[:10]:  # First 10 results
            try:
                # Extract title and URL
                title_elem = await article.query_selector("h2 a")
                if not title_elem:
                    continue

                title = await title_elem.inner_text()
                url = await title_elem.get_attribute("href")

                # Extract snippet
                snippet_elem = await article.query_selector("[data-result='snippet']")
                snippet = await snippet_elem.inner_text() if snippet_elem else ""

                if url and title:
                    results.append({
                        "title": title.strip(),
                        "url": url.strip(),
                        "snippet": snippet.strip(),
                    })

            except Exception as e:
                logger.debug(f"Error extracting result: {e}")
                continue

        logger.info(f"[Search] Found {len(results)} results")
        return results

    except Exception as e:
        logger.error(f"Search failed for '{query}': {e}")
        return []


def score_url_match(url: str, business_name: str, city: Optional[str], state: Optional[str]) -> float:
    """
    Score how well a URL matches the business based on heuristics.

    Args:
        url: Candidate URL
        business_name: Business name
        city: City name
        state: State code

    Returns:
        Score (0.0 to 1.0), higher is better match
    """
    score = 0.0

    try:
        parsed = urlparse(url.lower())
        domain = parsed.netloc.lower()

        # Skip known aggregator/directory sites
        blacklist_domains = [
            "yellowpages.com", "yelp.com", "homeadvisor.com",
            "thumbtack.com", "angieslist.com", "facebook.com",
            "linkedin.com", "twitter.com", "instagram.com",
            "bbb.org", "google.com", "mapquest.com",
        ]

        for blacklisted in blacklist_domains:
            if blacklisted in domain:
                return 0.0

        # Extract business name keywords
        name_words = re.findall(r'\b\w+\b', business_name.lower())
        name_words = [w for w in name_words if len(w) > 2]  # Skip short words

        # Score based on business name keywords in domain
        domain_clean = re.sub(r'[^a-z0-9]', '', domain)

        for word in name_words:
            if word in domain_clean:
                score += 0.3

        # Bonus for having multiple name words
        if len(name_words) >= 2:
            if all(word in domain_clean for word in name_words[:2]):
                score += 0.4

        # Bonus for city/state in domain
        if city and city.lower() in domain_clean:
            score += 0.1

        if state and state.lower() in domain_clean:
            score += 0.1

        # Prefer .com domains
        if domain.endswith(".com"):
            score += 0.1

        # Cap score at 1.0
        return min(score, 1.0)

    except Exception as e:
        logger.debug(f"Error scoring URL '{url}': {e}")
        return 0.0


async def find_business_url(page: Page, company: Company) -> Optional[str]:
    """
    Search for external website URL for a business.

    Args:
        page: Playwright page instance
        company: Company record from database

    Returns:
        External website URL or None if not found
    """
    logger.info(f"[Find URL] {company.name}")

    # Build search query
    query = build_search_query(company.name, company.address)

    # Search DuckDuckGo
    results = await search_duckduckgo(page, query)

    if not results:
        logger.warning(f"[Find URL] No results for {company.name}")
        return None

    # Extract city/state for scoring
    city, state = extract_city_state_from_address(company.address)

    # Score all results
    scored_results = []
    for result in results:
        score = score_url_match(result["url"], company.name, city, state)
        if score > 0.0:
            scored_results.append({
                "url": result["url"],
                "score": score,
                "title": result["title"],
            })

    # Sort by score (highest first)
    scored_results.sort(key=lambda x: x["score"], reverse=True)

    if scored_results:
        best_match = scored_results[0]
        logger.info(
            f"[Find URL] Best match: {best_match['url']} "
            f"(score: {best_match['score']:.2f})"
        )
        return best_match["url"]

    logger.warning(f"[Find URL] No good matches for {company.name}")
    return None


async def process_companies_batch(companies: list[Company], batch_size: int = 10) -> tuple[int, int]:
    """
    Process a batch of companies to find external URLs.

    Args:
        companies: List of Company records to process
        batch_size: Number of companies to process before creating new browser

    Returns:
        Tuple of (found_count, failed_count)
    """
    found = 0
    failed = 0

    async with async_playwright() as p:
        # Process in batches to avoid memory issues
        for i in range(0, len(companies), batch_size):
            batch = companies[i:i+batch_size]

            logger.info(f"[Batch] Processing {len(batch)} companies ({i+1}-{i+len(batch)}/{len(companies)})")

            # Create browser for this batch
            browser = await p.chromium.launch(headless=True)

            try:
                # Random user agent
                user_agent = random.choice(USER_AGENTS)
                context = await browser.new_context(user_agent=user_agent)
                page = await context.new_page()

                session = create_session()

                try:
                    for company in batch:
                        try:
                            # Find external URL
                            external_url = await find_business_url(page, company)

                            if external_url:
                                # Canonicalize and update database
                                try:
                                    canonical_url = canonicalize_url(external_url)
                                    new_domain = domain_from_url(canonical_url)

                                    # Update company record
                                    company.website = canonical_url
                                    company.domain = new_domain

                                    session.commit()

                                    logger.info(
                                        f"[Update] {company.name}: "
                                        f"{new_domain}"
                                    )
                                    found += 1

                                except Exception as e:
                                    logger.error(f"Error updating {company.name}: {e}")
                                    session.rollback()
                                    failed += 1

                            else:
                                logger.warning(f"[Skip] {company.name}: No URL found")
                                failed += 1

                            # Random delay between searches
                            delay = random.uniform(MIN_SEARCH_DELAY, MAX_SEARCH_DELAY)
                            logger.debug(f"[Sleep] {delay:.1f}s")
                            await asyncio.sleep(delay)

                        except Exception as e:
                            logger.error(f"Error processing {company.name}: {e}")
                            failed += 1
                            continue

                finally:
                    session.close()
                    await page.close()
                    await context.close()

            finally:
                await browser.close()

    return (found, failed)


async def find_urls_for_ha_companies(limit: Optional[int] = None) -> tuple[int, int]:
    """
    Find external URLs for HomeAdvisor companies with placeholder URLs.

    Args:
        limit: Maximum number of companies to process (None = all)

    Returns:
        Tuple of (found_count, failed_count)
    """
    logger.info("=" * 60)
    logger.info("URL Finder - HomeAdvisor Companies")
    logger.info("=" * 60)

    # Query database for HA companies with homeadvisor.com domain
    session = create_session()

    try:
        stmt = (
            select(Company)
            .where(Company.domain == "homeadvisor.com")
            .where(Company.active == True)
        )

        if limit:
            stmt = stmt.limit(limit)

        companies = session.execute(stmt).scalars().all()

        logger.info(f"Found {len(companies)} HomeAdvisor companies to process")

        if not companies:
            logger.info("No companies to process")
            return (0, 0)

        # Process companies
        found, failed = await process_companies_batch(list(companies))

        logger.info("")
        logger.info("=" * 60)
        logger.info("Results:")
        logger.info(f"  Found:  {found}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"  Total:  {len(companies)}")
        logger.info("=" * 60)

        return (found, failed)

    finally:
        session.close()


def main():
    """CLI entry point."""
    import sys

    # Parse optional limit argument
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            logger.error(f"Invalid limit: {sys.argv[1]}")
            sys.exit(1)

    # Run async function
    asyncio.run(find_urls_for_ha_companies(limit))


if __name__ == "__main__":
    main()
