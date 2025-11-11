#!/usr/bin/env python3
"""
Yellow Pages scraper client with Playwright support.

This module provides enhanced scraping with headless browser to bypass anti-bot protection.
"""

import os
import re
import time
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# Load environment variables
load_dotenv()

# Configuration
YP_BASE = os.getenv("YP_BASE", "https://www.yellowpages.com/search")
CRAWL_DELAY_SECONDS = float(os.getenv("CRAWL_DELAY_SECONDS", "2"))
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "true").lower() == "true"

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2


def fetch_yp_search_page_playwright(
    category: str,
    location: str,
    page: int = 1,
    delay: Optional[float] = None,
) -> str:
    """
    Fetch Yellow Pages search page using Playwright (headless browser).

    Args:
        category: Search category/terms (e.g., "pressure washing")
        location: Geographic location (e.g., "Texas")
        page: Page number (default: 1)
        delay: Optional delay before request

    Returns:
        HTML content as string

    Raises:
        Exception: If request fails after retries
    """
    # Apply rate limiting
    if delay is None:
        delay = CRAWL_DELAY_SECONDS

    if delay > 0:
        time.sleep(delay)

    # Build query URL
    url = (
        f"{YP_BASE}?"
        f"search_terms={quote_plus(category)}&"
        f"geo_location_terms={quote_plus(location)}&"
        f"page={page}"
    )

    print(f"Fetching with Playwright: {url}")

    for attempt in range(MAX_RETRIES):
        try:
            with sync_playwright() as p:
                # Launch browser in headless mode
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                    ]
                )

                # Create context with realistic settings
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent=(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    ),
                    locale='en-US',
                    timezone_id='America/New_York',
                )

                # Create page
                page_obj = context.new_page()

                # Set extra HTTP headers
                page_obj.set_extra_http_headers({
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                })

                # Navigate to page
                response = page_obj.goto(url, wait_until='domcontentloaded', timeout=30000)

                if response.status == 403:
                    print(f"403 Forbidden (attempt {attempt + 1}/{MAX_RETRIES})")
                    browser.close()
                    if attempt < MAX_RETRIES - 1:
                        backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
                        print(f"Retrying in {backoff}s...")
                        time.sleep(backoff)
                        continue
                    raise Exception("403 Forbidden after all retries")

                # Wait a bit for dynamic content
                page_obj.wait_for_timeout(2000)

                # Get HTML content
                html = page_obj.content()

                # Close browser
                browser.close()

                print(f"✓ Successfully fetched page {page} ({len(html)} bytes)")
                return html

        except PlaywrightTimeoutError:
            print(f"Timeout (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"Retrying in {backoff}s...")
                time.sleep(backoff)
                continue
            raise

        except Exception as e:
            print(f"Error: {e} (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"Retrying in {backoff}s...")
                time.sleep(backoff)
                continue
            raise

    raise Exception(f"Failed to fetch page after {MAX_RETRIES} attempts")


def parse_yp_results(html: str) -> list[dict]:
    """
    Parse Yellow Pages search results HTML.

    Args:
        html: HTML content from Yellow Pages search page

    Returns:
        List of dicts with business information
    """
    soup = BeautifulSoup(html, "lxml")
    results = []

    # Find all business listings - try multiple selectors
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
            print(f"Warning: Failed to parse listing: {e}")
            continue

    return results


def parse_single_listing(listing) -> dict:
    """Parse a single business listing element."""
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
    website_elem = (
        listing.select_one("a[href*='http'][class*='website']") or
        listing.select_one("a[href*='http'][class*='site']") or
        listing.select_one("a.track-visit-website") or
        listing.select_one("a[data-analytics*='website']")
    )

    if website_elem:
        href = website_elem.get("href", "")
        if href:
            # Extract actual URL from YP redirect links
            url_match = re.search(r'[?&]url=([^&]+)', href)
            if url_match:
                from urllib.parse import unquote
                result["website"] = unquote(url_match.group(1))
            elif href.startswith("http"):
                result["website"] = href

    # Fallback: search for any external link
    if not result["website"]:
        for link in listing.select("a[href^='http']"):
            href = link.get("href", "")
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
        review_match = re.search(r'(\d+)', review_text)
        if review_match:
            try:
                result["reviews_yp"] = int(review_match.group(1))
            except ValueError:
                pass

    return result


def clean_text(text: str) -> str:
    """Clean extracted text."""
    if not text:
        return ""
    cleaned = re.sub(r'\s+', ' ', text)
    cleaned = cleaned.strip()
    return cleaned
