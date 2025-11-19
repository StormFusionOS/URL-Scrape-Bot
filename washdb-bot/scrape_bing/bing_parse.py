"""
Bing Local Search Scraper - HTML Parsing Utilities

Robust HTML parsing for Bing Local Search results with multiple
selector strategies and fallbacks for handling Bing's dynamic HTML.

Features:
- Multiple selector strategies per field
- Data cleaning and normalization
- Structured data parsing (hours, reviews, etc.)
- Confidence scoring

Author: washdb-bot
Date: 2025-11-18
"""

import re
from typing import Dict, List, Optional, Tuple, Any
from playwright.async_api import Page, ElementHandle


class BingLocalParser:
    """
    HTML parser for Bing Local Search business listings.

    Provides robust extraction methods with multiple selector strategies
    and fallbacks to handle Bing's frequently changing HTML structure.
    """

    # Multiple selector strategies for each field (in priority order)
    SELECTORS = {
        "name": [
            'h2[class*="title"]',
            'div[class*="businessTitle"]',
            'a[class*="businessTitle"]',
            'div.bm_name',
            'h2.b_title',
            'div[data-businessname]'
        ],
        "address": [
            'div[class*="address"]',
            'span[class*="address"]',
            'div.bm_address',
            'div.addressLine',
            'span.bm_addr',
            'div[itemprop="address"]'
        ],
        "phone": [
            'a[href^="tel:"]',
            'span[class*="phone"]',
            'div[class*="phone"]',
            'div.bm_phone',
            'span.phoneNumber',
            'div[itemprop="telephone"]'
        ],
        "website": [
            'a[class*="website"]',
            'a[href*="http"]:not([href*="bing.com"])',
            'a.bm_website',
            'a[itemprop="url"]',
            'div.websiteUrl a'
        ],
        "rating": [
            'div[class*="rating"]',
            'span[class*="rating"]',
            'div.csrc',
            'div.b_ratnum',
            'span.star-rating',
            'div[itemprop="ratingValue"]'
        ],
        "reviews_count": [
            'span[class*="review"]',
            'div[class*="review"]',
            'span.b_rev',
            'div.reviewCount',
            'span[itemprop="reviewCount"]'
        ],
        "category": [
            'div[class*="category"]',
            'span[class*="category"]',
            'div.bm_cat',
            'span.businessCategory',
            'div[itemprop="category"]'
        ],
        "hours": [
            'div[class*="hours"]',
            'div[class*="openHours"]',
            'div.businessHours',
            'table.hoursTable',
            'div[itemprop="openingHours"]'
        ]
    }

    @staticmethod
    async def extract_field(
        page: Page,
        field_name: str,
        selectors: List[str] = None
    ) -> Tuple[Optional[str], float]:
        """
        Extract a field using multiple selector strategies.

        Args:
            page: Playwright Page object
            field_name: Name of field to extract
            selectors: Custom selectors (uses defaults if None)

        Returns:
            Tuple of (extracted_value, confidence_score)
        """
        selectors = selectors or BingLocalParser.SELECTORS.get(field_name, [])

        for idx, selector in enumerate(selectors):
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.text_content()
                    if text and text.strip():
                        # Confidence decreases with fallback depth
                        confidence = 1.0 - (idx * 0.15)
                        return text.strip(), max(confidence, 0.3)

            except Exception:
                continue

        return None, 0.0

    @staticmethod
    async def extract_name(page: Page) -> Tuple[Optional[str], float]:
        """Extract business name."""
        name, confidence = await BingLocalParser.extract_field(page, "name")
        if name:
            name = BingLocalParser._clean_text(name)
        return name, confidence

    @staticmethod
    async def extract_address(page: Page) -> Tuple[Optional[str], float]:
        """Extract business address."""
        address, confidence = await BingLocalParser.extract_field(page, "address")
        if address:
            address = BingLocalParser._clean_address(address)
        return address, confidence

    @staticmethod
    async def extract_phone(page: Page) -> Tuple[Optional[str], float]:
        """Extract phone number."""
        # Try to get from text first
        phone, confidence = await BingLocalParser.extract_field(page, "phone")

        # Also try to get from href attribute
        if not phone:
            try:
                phone_link = await page.query_selector('a[href^="tel:"]')
                if phone_link:
                    href = await phone_link.get_attribute("href")
                    phone = href.replace("tel:", "") if href else None
                    confidence = 0.9
            except Exception:
                pass

        if phone:
            phone = BingLocalParser._clean_phone(phone)

        return phone, confidence

    @staticmethod
    async def extract_website(page: Page) -> Tuple[Optional[str], float]:
        """Extract website URL."""
        website = None
        confidence = 0.0

        for selector in BingLocalParser.SELECTORS["website"]:
            try:
                element = await page.query_selector(selector)
                if element:
                    href = await element.get_attribute("href")
                    if href and BingLocalParser._is_valid_website(href):
                        website = href
                        confidence = 0.9
                        break
            except Exception:
                continue

        return website, confidence

    @staticmethod
    async def extract_rating(page: Page) -> Tuple[Optional[float], float]:
        """Extract rating score."""
        rating_text, confidence = await BingLocalParser.extract_field(page, "rating")

        if rating_text:
            try:
                # Extract first number from text
                match = re.search(r'(\d+\.?\d*)', rating_text)
                if match:
                    rating = float(match.group(1))
                    # Validate rating is in reasonable range
                    if 0.0 <= rating <= 5.0:
                        return rating, confidence
            except ValueError:
                pass

        return None, 0.0

    @staticmethod
    async def extract_reviews_count(page: Page) -> Tuple[Optional[int], float]:
        """Extract number of reviews."""
        reviews_text, confidence = await BingLocalParser.extract_field(page, "reviews_count")

        if reviews_text:
            try:
                # Extract number from text like "1,234 reviews"
                # Remove commas and extract digits
                cleaned = re.sub(r'[^\d]', '', reviews_text)
                if cleaned:
                    reviews_count = int(cleaned)
                    return reviews_count, confidence
            except ValueError:
                pass

        return None, 0.0

    @staticmethod
    async def extract_category(page: Page) -> Tuple[Optional[str], float]:
        """Extract business category."""
        category, confidence = await BingLocalParser.extract_field(page, "category")
        if category:
            category = BingLocalParser._clean_text(category)
        return category, confidence

    @staticmethod
    async def extract_hours(page: Page) -> Tuple[Optional[Dict], float]:
        """
        Extract business hours.

        Returns:
            Tuple of (hours_dict, confidence) where hours_dict maps day to hours
        """
        hours_dict = {}
        confidence = 0.0

        try:
            # Try to find hours table or container
            for selector in BingLocalParser.SELECTORS["hours"]:
                hours_container = await page.query_selector(selector)
                if hours_container:
                    # Extract all text from hours section
                    hours_text = await hours_container.text_content()
                    if hours_text:
                        hours_dict = BingLocalParser._parse_hours_text(hours_text)
                        confidence = 0.8 if hours_dict else 0.0
                        break

        except Exception:
            pass

        return hours_dict if hours_dict else None, confidence

    @staticmethod
    async def extract_all_fields(page: Page) -> Dict[str, Any]:
        """
        Extract all available fields from the page.

        Returns:
            Dictionary with extracted fields and metadata
        """
        result = {}

        # Extract each field
        name, name_conf = await BingLocalParser.extract_name(page)
        if name:
            result["name"] = name
            result["_conf_name"] = name_conf

        address, addr_conf = await BingLocalParser.extract_address(page)
        if address:
            result["address"] = address
            result["_conf_address"] = addr_conf

        phone, phone_conf = await BingLocalParser.extract_phone(page)
        if phone:
            result["phone"] = phone
            result["_conf_phone"] = phone_conf

        website, web_conf = await BingLocalParser.extract_website(page)
        if website:
            result["website"] = website
            result["_conf_website"] = web_conf

        rating, rating_conf = await BingLocalParser.extract_rating(page)
        if rating is not None:
            result["rating"] = rating
            result["_conf_rating"] = rating_conf

        reviews, reviews_conf = await BingLocalParser.extract_reviews_count(page)
        if reviews is not None:
            result["reviews_count"] = reviews
            result["_conf_reviews_count"] = reviews_conf

        category, cat_conf = await BingLocalParser.extract_category(page)
        if category:
            result["category"] = category
            result["_conf_category"] = cat_conf

        hours, hours_conf = await BingLocalParser.extract_hours(page)
        if hours:
            result["hours"] = hours
            result["_conf_hours"] = hours_conf

        # Calculate overall confidence
        confidence_scores = [v for k, v in result.items() if k.startswith("_conf_")]
        if confidence_scores:
            result["_overall_confidence"] = sum(confidence_scores) / len(confidence_scores)
        else:
            result["_overall_confidence"] = 0.0

        return result

    @staticmethod
    async def extract_all_results_from_page(page: Page) -> List[Dict[str, Any]]:
        """
        Extract all business listings from a Bing Local Search results page.

        Args:
            page: Playwright Page object

        Returns:
            List of dictionaries, each containing extracted business data
        """
        results = []

        # Common selectors for business listings container
        listing_selectors = [
            'li.b_algo',  # Standard Bing result
            'div.bm_box',  # Bing Maps business box
            'div.localEntityCard',  # Local entity card
            'div[data-businessid]',  # Business with ID
            'li[data-bm]'  # Business listing
        ]

        listing_elements = []
        for selector in listing_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    listing_elements = elements
                    break
            except Exception:
                continue

        # Extract data from each listing
        for listing in listing_elements:
            try:
                business = await BingLocalParser._extract_from_listing(listing)
                if business and business.get("name"):
                    results.append(business)
            except Exception as e:
                # Log error but continue with other listings
                continue

        return results

    @staticmethod
    async def _extract_from_listing(listing: ElementHandle) -> Dict[str, Any]:
        """
        Extract business data from a single listing element.

        Args:
            listing: ElementHandle for the listing

        Returns:
            Dictionary with extracted business data
        """
        result = {}

        # Extract name
        name_selectors = ['h2', 'a[class*="title"]', 'div[class*="name"]']
        for selector in name_selectors:
            try:
                name_elem = await listing.query_selector(selector)
                if name_elem:
                    name = await name_elem.text_content()
                    if name and name.strip():
                        result["name"] = BingLocalParser._clean_text(name)
                        result["_conf_name"] = 0.9
                        break
            except Exception:
                continue

        # Extract address
        addr_selectors = ['div[class*="address"]', 'span[class*="address"]']
        for selector in addr_selectors:
            try:
                addr_elem = await listing.query_selector(selector)
                if addr_elem:
                    address = await addr_elem.text_content()
                    if address and address.strip():
                        result["address"] = BingLocalParser._clean_address(address)
                        result["_conf_address"] = 0.8
                        break
            except Exception:
                continue

        # Extract phone
        try:
            phone_link = await listing.query_selector('a[href^="tel:"]')
            if phone_link:
                href = await phone_link.get_attribute("href")
                if href:
                    phone = href.replace("tel:", "")
                    result["phone"] = BingLocalParser._clean_phone(phone)
                    result["_conf_phone"] = 0.9
        except Exception:
            pass

        # Extract website
        try:
            website_link = await listing.query_selector('a[href*="http"]:not([href*="bing.com"])')
            if website_link:
                href = await website_link.get_attribute("href")
                if href and BingLocalParser._is_valid_website(href):
                    result["website"] = href
                    result["_conf_website"] = 0.9
        except Exception:
            pass

        # Extract rating
        rating_selectors = ['div[class*="rating"]', 'span[class*="rating"]']
        for selector in rating_selectors:
            try:
                rating_elem = await listing.query_selector(selector)
                if rating_elem:
                    rating_text = await rating_elem.text_content()
                    if rating_text:
                        match = re.search(r'(\d+\.?\d*)', rating_text)
                        if match:
                            rating = float(match.group(1))
                            if 0.0 <= rating <= 5.0:
                                result["rating"] = rating
                                result["_conf_rating"] = 0.8
                                break
            except Exception:
                continue

        # Extract review count
        review_selectors = ['span[class*="review"]', 'div[class*="review"]']
        for selector in review_selectors:
            try:
                review_elem = await listing.query_selector(selector)
                if review_elem:
                    review_text = await review_elem.text_content()
                    if review_text:
                        cleaned = re.sub(r'[^\d]', '', review_text)
                        if cleaned:
                            result["reviews_count"] = int(cleaned)
                            result["_conf_reviews_count"] = 0.8
                            break
            except Exception:
                continue

        # Calculate overall confidence
        confidence_scores = [v for k, v in result.items() if k.startswith("_conf_")]
        if confidence_scores:
            result["_overall_confidence"] = sum(confidence_scores) / len(confidence_scores)
        else:
            result["_overall_confidence"] = 0.0

        return result

    # Data cleaning and normalization methods

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""

        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        return text

    @staticmethod
    def _clean_address(address: str) -> str:
        """Clean and normalize address."""
        if not address:
            return ""

        address = BingLocalParser._clean_text(address)

        # Remove "Directions" or similar button text
        address = re.sub(r'(Directions|Get directions|Map)', '', address, flags=re.IGNORECASE)
        address = address.strip()

        return address

    @staticmethod
    def _clean_phone(phone: str) -> str:
        """Clean and normalize phone number."""
        if not phone:
            return ""

        # Remove common prefixes/suffixes
        phone = re.sub(r'(Call|Phone|Contact)', '', phone, flags=re.IGNORECASE)
        phone = phone.strip()

        # Keep only digits, spaces, dashes, parentheses, and plus sign
        phone = re.sub(r'[^\d\s\-\(\)\+]', '', phone)
        phone = phone.strip()

        return phone

    @staticmethod
    def _is_valid_website(url: str) -> bool:
        """Check if URL is a valid external website."""
        if not url:
            return False

        # Must start with http or https
        if not url.startswith(("http://", "https://")):
            return False

        # Should not be Bing/Microsoft domains
        bing_domains = ["bing.com", "microsoft.com", "msn.com"]
        if any(domain in url for domain in bing_domains):
            return False

        return True

    @staticmethod
    def _parse_hours_text(hours_text: str) -> Dict[str, str]:
        """
        Parse hours text into structured format.

        Args:
            hours_text: Raw hours text from page

        Returns:
            Dictionary mapping day to hours string
        """
        hours_dict = {}

        if not hours_text:
            return hours_dict

        # Try to extract day-hours pairs
        # Common patterns: "Monday 9 AM–5 PM", "Mon: 9:00 AM - 5:00 PM"
        day_patterns = [
            r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*(.*?)(?=Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|$)',
            r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[:\s]+(.*?)(?=Mon|Tue|Wed|Thu|Fri|Sat|Sun|$)'
        ]

        for pattern in day_patterns:
            matches = re.finditer(pattern, hours_text, re.IGNORECASE)
            for match in matches:
                day = match.group(1)
                hours = match.group(2).strip()
                if hours:
                    hours_dict[day] = hours

        return hours_dict

    @staticmethod
    def calculate_field_confidence(result: Dict) -> float:
        """
        Calculate overall confidence score for extracted data.

        Args:
            result: Dictionary with extracted fields (including _conf_ fields)

        Returns:
            Overall confidence score (0.0 - 1.0)
        """
        confidence_fields = [k for k in result.keys() if k.startswith("_conf_")]

        if not confidence_fields:
            return 0.0

        total_confidence = sum(result[k] for k in confidence_fields)
        return total_confidence / len(confidence_fields)


# Convenience function for quick extraction
async def parse_business_page(page: Page) -> Dict:
    """
    Parse all fields from a Bing Local Search business page.

    Args:
        page: Playwright Page object

    Returns:
        Dictionary with extracted business data
    """
    parser = BingLocalParser()
    return await parser.extract_all_fields(page)


async def parse_search_results(page: Page) -> List[Dict]:
    """
    Parse all business listings from a Bing Local Search results page.

    Args:
        page: Playwright Page object

    Returns:
        List of dictionaries with extracted business data
    """
    parser = BingLocalParser()
    return await parser.extract_all_results_from_page(page)
