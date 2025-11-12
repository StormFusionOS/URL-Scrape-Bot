#!/usr/bin/env python3
"""
Enhanced Yellow Pages parser with category tag extraction and filtering.

This module extends the basic YP parser to:
- Extract ALL category tags from each listing
- Capture YP profile URLs for fallback
- Detect sponsored/ad listings
- Provide better field extraction
"""

import re
from typing import List, Dict, Optional
from urllib.parse import unquote
from bs4 import BeautifulSoup

from scrape_yp.yp_data_utils import (
    normalize_phone,
    validate_url,
    is_valid_website_url,
    clean_business_name,
    normalize_address,
    extract_email_from_text,
)


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


def extract_category_tags(listing) -> List[str]:
    """
    Extract all category tags displayed on a listing card.

    Args:
        listing: BeautifulSoup element for a business listing

    Returns:
        List of category tag strings
    """
    tags = []

    # Look for various category tag patterns
    # YP displays categories in different ways
    tag_selectors = [
        "div.categories a",
        "span.categories a",
        "div.business-categories a",
        "ul.categories li",
        "span.category",
        "div[class*='categor'] a",
        "div[class*='categor'] span",
        ".cat a",
        ".cat span",
    ]

    for selector in tag_selectors:
        elements = listing.select(selector)
        for elem in elements:
            tag_text = clean_text(elem.get_text())
            if tag_text and len(tag_text) > 2:
                tags.append(tag_text)

    # Also check data attributes
    categories_data = listing.get('data-categories') or listing.get('data-category')
    if categories_data:
        # May be JSON or comma-separated
        if ',' in categories_data:
            tags.extend([c.strip() for c in categories_data.split(',') if c.strip()])
        else:
            tags.append(categories_data.strip())

    # Deduplicate while preserving order
    seen = set()
    unique_tags = []
    for tag in tags:
        tag_lower = tag.lower()
        if tag_lower not in seen:
            seen.add(tag_lower)
            unique_tags.append(tag)

    return unique_tags


def extract_profile_url(listing, base_url: str = "https://www.yellowpages.com") -> Optional[str]:
    """
    Extract the YP profile page URL (/mip/ or /bpp/).

    Args:
        listing: BeautifulSoup element for a business listing
        base_url: Base URL for relative links

    Returns:
        Full profile URL or None
    """
    # Look for business name link (usually goes to profile)
    name_link = (
        listing.select_one("a.business-name") or
        listing.select_one("h2.n a") or
        listing.select_one("h3.n a") or
        listing.select_one("a[data-analytics='businessName']")
    )

    if name_link:
        href = name_link.get("href", "")
        if href:
            # Make absolute URL
            if href.startswith("/"):
                return base_url + href
            elif href.startswith("http"):
                return href

    # Alternative: look for any /mip/ or /bpp/ link
    for link in listing.select("a[href]"):
        href = link.get("href", "")
        if "/mip/" in href or "/bpp/" in href:
            if href.startswith("/"):
                return base_url + href
            elif href.startswith("http"):
                return href

    return None


def is_sponsored(listing) -> bool:
    """
    Detect if a listing is sponsored/ad.

    Args:
        listing: BeautifulSoup element for a business listing

    Returns:
        True if sponsored
    """
    # Check for sponsored indicators (using more specific patterns to avoid false positives)
    # Note: "ad" alone matches too much (address, roadmap, etc.)
    sponsored_indicators = [
        "sponsored",
        "advertisement",
        "promoted",
        "paid-placement",
    ]

    # Specific class patterns for sponsored listings
    sponsored_classes = ["sponsored", "ad-listing", "paid-result", "promoted-listing"]

    # Check class names with word boundaries
    class_str = " ".join(listing.get("class", [])).lower()
    if any(cls in class_str for cls in sponsored_classes):
        return True

    # Check data attributes
    for attr, value in listing.attrs.items():
        if isinstance(value, str):
            value_lower = value.lower()
            if any(ind in value_lower for ind in sponsored_indicators):
                return True

    # Check for "Sponsored" or "Advertisement" badges/labels
    for elem in listing.select("span.badge, div.badge, span.label, div.label, span.ad-badge"):
        text = clean_text(elem.get_text()).lower()
        if "sponsored" in text or "advertisement" in text:
            return True

    return False


def extract_website_url(listing) -> Optional[str]:
    """
    Extract website URL with improved logic.

    Args:
        listing: BeautifulSoup element for a business listing

    Returns:
        Website URL or None
    """
    # Look for website links (various patterns)
    website_elem = (
        listing.select_one("a[href*='http'][class*='website']") or
        listing.select_one("a[href*='http'][class*='site']") or
        listing.select_one("a.track-visit-website") or
        listing.select_one("a[data-analytics*='website']") or
        listing.select_one("a[title*='Website']") or
        listing.select_one("a[aria-label*='Website']")
    )

    if website_elem:
        href = website_elem.get("href", "")
        if href:
            # Extract actual URL from YP redirect/tracking links
            # Pattern: /mip/...?url=<actual_url>
            url_match = re.search(r'[?&]url=([^&]+)', href)
            if url_match:
                return unquote(url_match.group(1))
            elif href.startswith("http"):
                # Skip yellowpages.com links
                if "yellowpages.com" not in href.lower():
                    return href

    # Fallback: search for any external link in the listing
    for link in listing.select("a[href^='http']"):
        href = link.get("href", "")
        # Skip YP internal links and common non-website links
        if href and "yellowpages.com" not in href.lower():
            # Skip social media links (we want the main website)
            if not any(social in href.lower() for social in ['facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com']):
                return href

    return None


def extract_business_hours(listing) -> Optional[str]:
    """
    Extract business hours from a listing.

    Args:
        listing: BeautifulSoup element for a business listing

    Returns:
        Business hours string or None
    """
    # Look for various hour patterns
    hours_selectors = [
        "div.hours",
        "span.hours",
        "div.business-hours",
        "div[class*='hours']",
        "span[class*='hours']",
        "div.open-details",
        "div.open-status",
    ]

    for selector in hours_selectors:
        elem = listing.select_one(selector)
        if elem:
            hours_text = clean_text(elem.get_text())
            if hours_text and len(hours_text) > 3:
                return hours_text

    # Check for "Open Now" / "Closed Now" indicators
    status_elem = listing.select_one("span.open, span.closed, div.status")
    if status_elem:
        status_text = clean_text(status_elem.get_text())
        if status_text:
            return status_text

    return None


def extract_business_description(listing) -> Optional[str]:
    """
    Extract business description/snippet from a listing.

    Args:
        listing: BeautifulSoup element for a business listing

    Returns:
        Description string or None
    """
    # Look for description/snippet patterns
    desc_selectors = [
        "p.snippet",
        "div.snippet",
        "p.description",
        "div.description",
        "div.business-description",
        "p.info",
        "div.info",
        "div[class*='snippet']",
        "div[class*='description']",
    ]

    for selector in desc_selectors:
        elem = listing.select_one(selector)
        if elem:
            desc_text = clean_text(elem.get_text())
            # Only return if substantial (>20 chars)
            if desc_text and len(desc_text) > 20:
                return desc_text

    return None


def extract_services_offered(listing) -> List[str]:
    """
    Extract services offered from a listing.

    Args:
        listing: BeautifulSoup element for a business listing

    Returns:
        List of service strings
    """
    services = []

    # Look for services/amenities sections
    services_selectors = [
        "ul.services li",
        "ul.amenities li",
        "div.services span",
        "div.amenities span",
        "ul[class*='service'] li",
        "ul[class*='amenity'] li",
    ]

    for selector in services_selectors:
        elements = listing.select(selector)
        for elem in elements:
            service_text = clean_text(elem.get_text())
            if service_text and len(service_text) > 2:
                services.append(service_text)

    # Deduplicate
    seen = set()
    unique_services = []
    for service in services:
        service_lower = service.lower()
        if service_lower not in seen:
            seen.add(service_lower)
            unique_services.append(service)

    return unique_services


def parse_single_listing_enhanced(listing) -> Dict:
    """
    Parse a single business listing with enhanced field extraction.

    Args:
        listing: BeautifulSoup element for a business listing

    Returns:
        Dict with business information including:
        - name: Business name
        - phone: Phone number
        - address: Business address
        - website: Website URL
        - profile_url: YP profile page URL
        - category_tags: List of category tags
        - rating_yp: YP rating (float)
        - reviews_yp: Number of reviews (int)
        - is_sponsored: Boolean indicating if ad/sponsored
        - business_hours: Business hours string (NEW)
        - description: Business description (NEW)
        - services: List of services offered (NEW)
    """
    result = {
        "name": None,
        "phone": None,
        "address": None,
        "normalized_address": None,  # NEW
        "email": None,  # NEW
        "website": None,
        "profile_url": None,
        "category_tags": [],
        "rating_yp": None,
        "reviews_yp": None,
        "is_sponsored": False,
        "business_hours": None,
        "description": None,
        "services": [],
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
        raw_name = clean_text(name_elem.get_text())
        result["name"] = clean_business_name(raw_name)

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
        # Normalize to standard format
        result["phone"] = normalize_phone(phone_text)

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

    # Normalize address (NEW)
    if result["address"]:
        result["normalized_address"] = normalize_address(result["address"])

    # Extract website (enhanced with validation)
    raw_website = extract_website_url(listing)
    if raw_website:
        # Validate and clean URL
        is_valid, cleaned_url = validate_url(raw_website)
        if is_valid and is_valid_website_url(cleaned_url):
            result["website"] = cleaned_url
        else:
            result["website"] = None
    else:
        result["website"] = None

    # Extract profile URL
    result["profile_url"] = extract_profile_url(listing)

    # Extract category tags
    result["category_tags"] = extract_category_tags(listing)

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

    # Check if sponsored
    result["is_sponsored"] = is_sponsored(listing)

    # Extract business hours (NEW)
    result["business_hours"] = extract_business_hours(listing)

    # Extract description (NEW)
    result["description"] = extract_business_description(listing)

    # Extract services (NEW)
    result["services"] = extract_services_offered(listing)

    # Extract email from description/services text (NEW)
    # Check description first
    if result["description"]:
        email = extract_email_from_text(result["description"])
        if email:
            result["email"] = email

    # If no email in description, try services
    if not result["email"] and result["services"]:
        for service in result["services"]:
            email = extract_email_from_text(service)
            if email:
                result["email"] = email
                break

    return result


def parse_yp_results_enhanced(html: str) -> List[Dict]:
    """
    Parse Yellow Pages search results with enhanced extraction.

    Args:
        html: HTML content from Yellow Pages search page

    Returns:
        List of dicts with enhanced business information
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
            result = parse_single_listing_enhanced(listing)
            # Only include if has a name
            if result and result.get("name"):
                results.append(result)
        except Exception as e:
            # Skip individual listing errors
            print(f"Warning: Failed to parse listing: {e}")
            continue

    return results


# Backward compatibility: if called as standalone parser
def parse_yp_results(html: str) -> List[Dict]:
    """Alias for backward compatibility."""
    return parse_yp_results_enhanced(html)
