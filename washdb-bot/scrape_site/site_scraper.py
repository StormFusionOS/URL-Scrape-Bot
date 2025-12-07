#!/usr/bin/env python3
"""
Website scraper for individual business sites.

This module handles:
- Fetching and parsing business websites
- Discovering internal pages (Contact, About, Services)
- Merging information from multiple pages
- Polite crawling with rate limiting
"""

import os
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from runner.logging_setup import get_logger
from scrape_site.site_parse import parse_site_content


# Load environment
load_dotenv()

# Configuration
CRAWL_DELAY_SECONDS = float(os.getenv("CRAWL_DELAY_SECONDS", "2"))
MAX_CONCURRENT_SITE_SCRAPES = int(os.getenv("MAX_CONCURRENT_SITE_SCRAPES", "5"))

# Request settings
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Page discovery keywords
CONTACT_KEYWORDS = ["contact", "contact-us", "get-in-touch", "reach-us"]
ABOUT_KEYWORDS = ["about", "about-us", "who-we-are", "our-story"]
SERVICES_KEYWORDS = ["services", "what-we-do", "our-services", "solutions"]

# Initialize logger
logger = get_logger("site_scraper")


def fetch_page(url: str, delay: float = None) -> Optional[str]:
    """
    Fetch a web page with polite crawling.

    Args:
        url: URL to fetch
        delay: Optional delay before request (uses CRAWL_DELAY_SECONDS if None)

    Returns:
        HTML content as string or None on error
    """
    if delay is None:
        delay = CRAWL_DELAY_SECONDS

    # Apply rate limiting
    if delay > 0:
        time.sleep(delay)

    logger.debug(f"Fetching: {url}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        response.raise_for_status()
        logger.debug(f"✓ Fetched {url} ({len(response.text)} bytes)")
        return response.text

    except requests.Timeout:
        logger.warning(f"Timeout fetching {url}")
        return None

    except requests.RequestException as e:
        logger.warning(f"Error fetching {url}: {e}")
        return None


def discover_internal_links(html: str, base_url: str) -> dict:
    """
    Discover internal links for Contact, About, and Services pages.

    Args:
        html: HTML content of the page
        base_url: Base URL of the site

    Returns:
        Dict with keys 'contact', 'about', 'services' containing URLs or None
    """
    soup = BeautifulSoup(html, "lxml")
    discovered = {
        "contact": None,
        "about": None,
        "services": None,
    }

    # Parse base URL for domain matching
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc

    # Find all links
    links = soup.find_all("a", href=True)

    for link in links:
        href = link.get("href", "")
        text = link.get_text(strip=True).lower()

        # Make absolute URL
        absolute_url = urljoin(base_url, href)
        parsed_url = urlparse(absolute_url)

        # Only consider internal links
        if parsed_url.netloc != base_domain:
            continue

        # Skip anchors, javascript, etc.
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        # Check for contact page
        if not discovered["contact"]:
            if any(kw in text for kw in CONTACT_KEYWORDS) or \
               any(kw in href.lower() for kw in CONTACT_KEYWORDS):
                discovered["contact"] = absolute_url
                logger.debug(f"Found contact page: {absolute_url}")

        # Check for about page
        if not discovered["about"]:
            if any(kw in text for kw in ABOUT_KEYWORDS) or \
               any(kw in href.lower() for kw in ABOUT_KEYWORDS):
                discovered["about"] = absolute_url
                logger.debug(f"Found about page: {absolute_url}")

        # Check for services page
        if not discovered["services"]:
            if any(kw in text for kw in SERVICES_KEYWORDS) or \
               any(kw in href.lower() for kw in SERVICES_KEYWORDS):
                discovered["services"] = absolute_url
                logger.debug(f"Found services page: {absolute_url}")

        # Stop if we found all three
        if all(discovered.values()):
            break

    return discovered


def merge_results(base_result: dict, additional_results: list[dict], base_url: str) -> dict:
    """
    Merge results from multiple pages, preferring non-null values.

    For emails, prefers business domain emails.
    For phones, merges unique values.
    For other fields, uses first non-null value.

    Args:
        base_result: Result from homepage
        additional_results: List of results from other pages
        base_url: Base URL for domain preference

    Returns:
        Merged result dict
    """
    merged = base_result.copy()

    # Extract domain from base URL
    parsed = urlparse(base_url)
    base_domain = parsed.netloc.replace("www.", "")

    # Merge phones (collect unique)
    all_phones = set(merged.get("phones", []) or [])
    for result in additional_results:
        phones = result.get("phones", []) or []
        all_phones.update(phones)
    merged["phones"] = list(all_phones) if all_phones else []

    # Merge emails (prefer business domain)
    all_emails = set(merged.get("emails", []) or [])
    for result in additional_results:
        emails = result.get("emails", []) or []
        all_emails.update(emails)

    # Sort emails: business domain first
    if all_emails:
        email_list = list(all_emails)
        email_list.sort(key=lambda e: (0 if base_domain in e else 1, e))
        merged["emails"] = email_list
    else:
        merged["emails"] = []

    # Merge other fields (use first non-null)
    for field in ["name", "services", "service_area", "address"]:
        if not merged.get(field):
            for result in additional_results:
                if result.get(field):
                    merged[field] = result[field]
                    break

    # Merge reviews (use highest count)
    if merged.get("reviews"):
        max_count = merged["reviews"].get("count", 0)
        best_reviews = merged["reviews"]
    else:
        max_count = 0
        best_reviews = None

    for result in additional_results:
        if result.get("reviews"):
            count = result["reviews"].get("count", 0)
            if count > max_count:
                max_count = count
                best_reviews = result["reviews"]

    merged["reviews"] = best_reviews

    # Preserve content_metrics from homepage (primary source for SEO analysis)
    # This includes word_count, content_depth, header_structure
    if not merged.get("content_metrics") and base_result.get("content_metrics"):
        merged["content_metrics"] = base_result["content_metrics"]

    return merged


def scrape_website(url: str) -> dict:
    """
    Scrape a business website, fetching multiple pages if needed.

    Process:
    1. Fetch homepage
    2. Parse for business information
    3. If key fields missing, discover Contact/About/Services pages
    4. Fetch up to 3 additional pages
    5. Merge results

    Args:
        url: Website URL to scrape

    Returns:
        Dict with extracted business information
        Returns minimal info on errors (never crashes)
    """
    logger.info(f"Scraping website: {url}")

    # Minimal fallback result
    minimal_result = {
        "name": None,
        "phones": [],
        "emails": [],
        "services": None,
        "service_area": None,
        "address": None,
        "reviews": None,
        "content_metrics": None,
    }

    try:
        # Fetch homepage (no delay for first request)
        homepage_html = fetch_page(url, delay=0)

        if not homepage_html:
            logger.warning(f"Failed to fetch homepage: {url}")
            return minimal_result

        # Parse homepage
        homepage_result = parse_site_content(homepage_html, url)

        # Check if we need to fetch additional pages
        needs_contact = not (homepage_result.get("phones") and homepage_result.get("emails"))
        needs_services = not homepage_result.get("services")

        if not (needs_contact or needs_services):
            logger.info("Homepage has all needed information")
            return homepage_result

        # Discover internal pages
        logger.info("Discovering internal pages for missing information...")
        discovered = discover_internal_links(homepage_html, url)

        # Fetch additional pages
        additional_results = []
        pages_to_fetch = []

        # Prioritize pages based on what's missing
        if needs_contact and discovered["contact"]:
            pages_to_fetch.append(("contact", discovered["contact"]))

        if needs_services and discovered["services"]:
            pages_to_fetch.append(("services", discovered["services"]))

        # Add about page if we still need info
        if (needs_contact or needs_services) and discovered["about"]:
            pages_to_fetch.append(("about", discovered["about"]))

        # Limit to 3 additional pages
        pages_to_fetch = pages_to_fetch[:3]

        logger.info(f"Fetching {len(pages_to_fetch)} additional pages")

        for page_type, page_url in pages_to_fetch:
            logger.debug(f"Fetching {page_type} page: {page_url}")

            page_html = fetch_page(page_url)  # Uses default delay

            if page_html:
                try:
                    page_result = parse_site_content(page_html, url)
                    additional_results.append(page_result)
                    logger.debug(f"Parsed {page_type} page successfully")
                except Exception as e:
                    logger.warning(f"Error parsing {page_type} page: {e}")
                    continue

        # Merge results
        if additional_results:
            merged_result = merge_results(homepage_result, additional_results, url)
            logger.info(f"Merged results from {len(additional_results) + 1} pages")
            return merged_result
        else:
            logger.info("No additional pages fetched, using homepage results")
            return homepage_result

    except Exception as e:
        logger.error(f"Unexpected error scraping {url}: {e}", exc_info=True)
        return minimal_result


def main():
    """Demo: Scrape a sample website."""
    logger.info("=" * 60)
    logger.info("Site Scraper Demo")
    logger.info("=" * 60)
    logger.info("")

    # Example URL (replace with a real URL for testing)
    test_url = "https://example.com"

    logger.info(f"Scraping: {test_url}")
    logger.info("")

    result = scrape_website(test_url)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Scraping Results:")
    logger.info("=" * 60)
    logger.info(f"Name: {result['name']}")
    logger.info(f"Phones: {result['phones']}")
    logger.info(f"Emails: {result['emails']}")
    logger.info(f"Services: {result['services'][:100] if result['services'] else 'None'}...")
    logger.info(f"Service Area: {result['service_area'][:100] if result['service_area'] else 'None'}...")
    logger.info(f"Address: {result['address']}")
    if result['reviews']:
        logger.info(f"Reviews: {result['reviews']['count']} found")


if __name__ == "__main__":
    main()
