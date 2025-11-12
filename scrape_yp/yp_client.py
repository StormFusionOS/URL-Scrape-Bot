#!/usr/bin/env python3
"""
Yellow Pages scraper client for washdb-bot.

This module handles:
- Fetching search results from Yellow Pages
- Parsing business listings from HTML
- Polite crawling with rate limiting and retries
- Playwright support for bypassing anti-bot protection
"""

import os
import re
import time
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

# Configuration
YP_BASE = os.getenv("YP_BASE", "https://www.yellowpages.com/search")
CRAWL_DELAY_SECONDS = float(os.getenv("CRAWL_DELAY_SECONDS", "2"))
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "true").lower() == "true"

# Common desktop browser User-Agent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Request headers
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # Exponential backoff: 2, 4, 8 seconds


def fetch_yp_search_page(
    category: str,
    location: str,
    page: int = 1,
    delay: Optional[float] = None,
) -> str:
    """
    Fetch a Yellow Pages search results page.

    Uses Playwright (headless browser) if USE_PLAYWRIGHT=true,
    otherwise falls back to requests library.

    Args:
        category: Search category/terms (e.g., "pressure washing")
        location: Geographic location (e.g., "Texas")
        page: Page number (default: 1)
        delay: Optional delay before request (uses CRAWL_DELAY_SECONDS if None)

    Returns:
        HTML content as string

    Raises:
        Exception: If request fails after retries
    """
    # Use Playwright if enabled
    if USE_PLAYWRIGHT:
        try:
            return fetch_yp_search_page_playwright(category, location, page, delay)
        except Exception as e:
            print(f"Playwright failed: {e}")
            print("Falling back to requests library...")
            # Fall through to requests method

    # Apply rate limiting with randomization to avoid detection
    if delay is None:
        delay = CRAWL_DELAY_SECONDS

    if delay > 0:
        # Add ±20% random jitter to make timing less predictable
        import random
        jittered_delay = delay * random.uniform(0.8, 1.2)
        time.sleep(jittered_delay)

    # Build query URL
    url = (
        f"{YP_BASE}?"
        f"search_terms={quote_plus(category)}&"
        f"geo_location_terms={quote_plus(location)}&"
        f"page={page}"
    )

    print(f"Fetching: {url}")

    # Attempt request with retries
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)

            # Check for 403 Forbidden - aggressive backoff
            if response.status_code == 403:
                # Forbidden - apply aggressive exponential backoff
                backoff = 10 * (RETRY_BACKOFF_BASE ** attempt)  # 10, 20, 40 seconds
                print(f"Forbidden (403). Retrying in {backoff}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(backoff)
                continue

            # Check for rate limiting
            elif response.status_code == 429:
                # Too Many Requests - apply backoff
                backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"Rate limited (429). Retrying in {backoff}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(backoff)
                continue

            elif 500 <= response.status_code < 600:
                # Server error - apply backoff
                backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"Server error ({response.status_code}). Retrying in {backoff}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(backoff)
                continue

            # Raise for other error status codes
            response.raise_for_status()

            print(f"✓ Successfully fetched page {page} ({len(response.text)} bytes)")
            return response.text

        except requests.Timeout:
            backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
            print(f"Timeout. Retrying in {backoff}s... (attempt {attempt + 1}/{MAX_RETRIES})")
            time.sleep(backoff)

        except requests.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                # Last attempt, raise the error
                raise
            backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
            print(f"Request failed: {e}. Retrying in {backoff}s... (attempt {attempt + 1}/{MAX_RETRIES})")
            time.sleep(backoff)

    # Should not reach here, but raise if all retries failed
    raise requests.RequestException(f"Failed to fetch page after {MAX_RETRIES} attempts")


def parse_yp_results(html: str) -> list[dict]:
    """
    Parse Yellow Pages search results HTML.

    Args:
        html: HTML content from Yellow Pages search page

    Returns:
        List of dicts with keys:
        - name: Business name
        - phone: Phone number (or None)
        - address: Business address (or None)
        - website: Website URL (or None)
        - rating_yp: Yellow Pages rating as float (or None)
        - reviews_yp: Number of reviews as int (or None)
    """
    soup = BeautifulSoup(html, "lxml")
    results = []

    # Find all business listings
    # YP uses various classes, try multiple selectors
    listings = (
        soup.select("div.result") or
        soup.select("div.search-results div.srp-listing") or
        soup.select("div.organic") or
        soup.select("div[data-business-name]") or
        []
    )

    print(f"Found {len(listings)} potential listings")

    for listing in listings:
        try:
            result = parse_single_listing(listing)
            if result and result.get("name"):
                results.append(result)
        except Exception as e:
            # Skip individual listing errors
            print(f"Warning: Failed to parse listing: {e}")
            continue

    return results


def parse_single_listing(listing) -> dict:
    """
    Parse a single business listing element.

    Args:
        listing: BeautifulSoup element for a business listing

    Returns:
        Dict with business information
    """
    result = {
        "name": None,
        "phone": None,
        "address": None,
        "website": None,
        "rating_yp": None,
        "reviews_yp": None,
    }

    # Extract business name
    name_elem = (
        listing.select_one("a.business-name") or
        listing.select_one("h2.n") or
        listing.select_one("h3.n") or
        listing.select_one("a[data-analytics='businessName']") or
        listing.select_one("span.business-name") or
        listing.select_one("[class*='business-name']")
    )
    if name_elem:
        result["name"] = clean_text(name_elem.get_text())

    # Extract phone number
    phone_elem = (
        listing.select_one("div.phones") or
        listing.select_one("a.phone") or
        listing.select_one("span.phone") or
        listing.select_one("[class*='phone']")
    )
    if phone_elem:
        phone_text = clean_text(phone_elem.get_text())
        # Clean phone number (remove "Call", etc.)
        phone_text = re.sub(r'^(Call|Phone|Tel)[:\s]*', '', phone_text, flags=re.IGNORECASE)
        result["phone"] = phone_text if phone_text else None

    # Extract address
    address_elem = (
        listing.select_one("div.street-address") or
        listing.select_one("p.adr") or
        listing.select_one("span.adr") or
        listing.select_one("[class*='street-address']") or
        listing.select_one("[class*='adr']")
    )
    if address_elem:
        result["address"] = clean_text(address_elem.get_text())
    else:
        # Try to find locality/region as fallback
        locality = listing.select_one("div.locality") or listing.select_one("span.locality")
        region = listing.select_one("div.region") or listing.select_one("span.region")
        if locality or region:
            parts = []
            if locality:
                parts.append(clean_text(locality.get_text()))
            if region:
                parts.append(clean_text(region.get_text()))
            result["address"] = ", ".join(parts) if parts else None

    # Extract website
    # Look for website links (various patterns)
    website_elem = (
        listing.select_one("a[href*='http'][class*='website']") or
        listing.select_one("a[href*='http'][class*='site']") or
        listing.select_one("a.track-visit-website") or
        listing.select_one("a[data-analytics*='website']")
    )

    if website_elem:
        href = website_elem.get("href", "")
        # Extract actual URL from YP redirect/tracking links
        if href:
            # Pattern: /mip/...?url=<actual_url>
            url_match = re.search(r'[?&]url=([^&]+)', href)
            if url_match:
                from urllib.parse import unquote
                result["website"] = unquote(url_match.group(1))
            elif href.startswith("http"):
                result["website"] = href

    # Fallback: search for any external link in the listing
    if not result["website"]:
        for link in listing.select("a[href^='http']"):
            href = link.get("href", "")
            # Skip YP internal links
            if "yellowpages.com" not in href.lower():
                result["website"] = href
                break

    # Extract rating
    rating_elem = (
        listing.select_one("div.rating span.count") or
        listing.select_one("span.rating") or
        listing.select_one("div[class*='rating']")
    )
    if rating_elem:
        rating_text = clean_text(rating_elem.get_text())
        # Extract float from text like "4.5" or "4.5 out of 5"
        rating_match = re.search(r'(\d+\.?\d*)', rating_text)
        if rating_match:
            try:
                result["rating_yp"] = float(rating_match.group(1))
            except ValueError:
                pass

    # Extract review count
    review_elem = (
        listing.select_one("span.count") or
        listing.select_one("a.reviews") or
        listing.select_one("[class*='review-count']")
    )
    if review_elem:
        review_text = clean_text(review_elem.get_text())
        # Extract integer from text like "123 Reviews" or "(45)"
        review_match = re.search(r'(\d+)', review_text)
        if review_match:
            try:
                result["reviews_yp"] = int(review_match.group(1))
            except ValueError:
                pass

    return result


def clean_text(text: str) -> str:
    """
    Clean extracted text by removing extra whitespace and newlines.

    Args:
        text: Raw text string

    Returns:
        Cleaned text string
    """
    if not text:
        return ""

    # Replace multiple whitespace/newlines with single space
    cleaned = re.sub(r'\s+', ' ', text)
    # Strip leading/trailing whitespace
    cleaned = cleaned.strip()

    return cleaned


def fetch_yp_search_page_playwright(
    category: str,
    location: str,
    page: int = 1,
    delay: Optional[float] = None,
) -> str:
    """
    Fetch Yellow Pages search page using persistent browser with stealth mode.

    This uses the new YellowPagesBrowser class which provides:
    - Persistent browser instance (reused across requests)
    - playwright-stealth integration for maximum anti-detection
    - Exponential backoff on 403 errors
    - Human-like behavior simulation

    Args:
        category: Search category/terms
        location: Geographic location
        page: Page number
        delay: Optional delay before request (unused, browser handles delays)

    Returns:
        HTML content as string
    """
    from scrape_yp.yp_browser import get_yp_browser

    # Build query URL
    url = (
        f"{YP_BASE}?"
        f"search_terms={quote_plus(category)}&"
        f"geo_location_terms={quote_plus(location)}&"
        f"page={page}"
    )

    print(f"Fetching with persistent YP browser: {url}")

    # Get global browser instance (reused across requests for efficiency)
    browser = get_yp_browser()

    # Fetch page with built-in retry logic and exponential backoff
    html = browser.fetch_page(
        url=url,
        wait_for_selector='div.result, div.srp-listing, div.organic',  # Wait for listings
        min_delay=3,  # Minimum delay after page load
        max_delay=7   # Maximum delay after page load
    )

    if html:
        print(f"✓ Successfully fetched page {page} ({len(html)} bytes)")
        return html
    else:
        raise Exception(f"Failed to fetch page {page} after all retries")


def main():
    """Demo: Fetch and parse Yellow Pages results."""
    print("=" * 60)
    print("Yellow Pages Scraper Demo")
    print("=" * 60)
    print()

    # Demo parameters
    category = "pressure washing"
    location = "Texas"
    page = 1

    print(f"Category: {category}")
    print(f"Location: {location}")
    print(f"Page: {page}")
    print()

    try:
        # Fetch search page
        html = fetch_yp_search_page(category, location, page)

        # Parse results
        results = parse_yp_results(html)

        print()
        print("=" * 60)
        print(f"Parsed {len(results)} results")
        print("=" * 60)
        print()

        # Display first few results
        for i, result in enumerate(results[:5], 1):
            print(f"{i}. {result['name']}")
            if result["phone"]:
                print(f"   Phone: {result['phone']}")
            if result["address"]:
                print(f"   Address: {result['address']}")
            if result["website"]:
                print(f"   Website: {result['website']}")
            if result["rating_yp"]:
                print(f"   Rating: {result['rating_yp']}", end="")
                if result["reviews_yp"]:
                    print(f" ({result['reviews_yp']} reviews)", end="")
                print()
            print()

        if len(results) > 5:
            print(f"... and {len(results) - 5} more results")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
