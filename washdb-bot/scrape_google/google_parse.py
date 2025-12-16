"""
Google Business Scraper - HTML Parsing Utilities

Robust HTML parsing for Google Maps/Business pages with multiple
selector strategies and fallbacks for handling Google's dynamic HTML.

Features:
- Multiple selector strategies per field
- Data cleaning and normalization
- Structured data parsing (hours, reviews, etc.)
- Confidence scoring

Author: washdb-bot
Date: 2025-11-10
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from playwright.async_api import Page, ElementHandle

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from scrape_yp.name_standardizer import (
    score_name_quality,
    parse_location_from_address,
    needs_standardization,
)


class GoogleMapsParser:
    """
    HTML parser for Google Maps business pages.

    Provides robust extraction methods with multiple selector strategies
    and fallbacks to handle Google's frequently changing HTML structure.
    """

    # Multiple selector strategies for each field (in priority order)
    SELECTORS = {
        "name": [
            'h1[class*="fontHeadline"]',
            'h1.DUwDvf',
            'h1[data-attrid="title"]',
            'div[role="main"] h1'
        ],
        "address": [
            'button[data-item-id*="address"]',
            'button[data-tooltip*="Copy address"]',
            '[data-item-id="address"] div[class*="fontBody"]',
            'div[aria-label*="Address"]'
        ],
        "phone": [
            'button[data-item-id*="phone:tel"]',
            'button[data-tooltip*="Copy phone number"]',
            'a[href^="tel:"]',
            '[aria-label*="Phone"]'
        ],
        "website": [
            'a[data-item-id*="authority"]',
            'a[data-tooltip*="Open website"]',
            'a[aria-label*="Website"]',
            'a[href*="http"]:not([href*="google.com"])'
        ],
        "rating": [
            'div[class*="fontDisplayLarge"]',
            'span[aria-label*="stars"]',
            'div.F7nice span[aria-hidden="true"]'
        ],
        "reviews_count": [
            'button[aria-label*="reviews"]',
            'span[aria-label*="reviews"]',
            'button.HHrUdb span'
        ],
        "category": [
            'button[class*="DkEaL"]',
            'button[jsaction*="category"]',
            'div[class*="fontBodyMedium"] button:first-of-type'
        ],
        "hours": [
            'div[aria-label*="Hours"]',
            'table[aria-label*="Hours"]',
            'div.t39EBf'
        ],
        "price_range": [
            'span[aria-label*="Price"]',
            'span:contains("$")'
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
        selectors = selectors or GoogleMapsParser.SELECTORS.get(field_name, [])

        for idx, selector in enumerate(selectors):
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.text_content()
                    if text and text.strip():
                        # Confidence decreases with fallback depth
                        confidence = 1.0 - (idx * 0.2)
                        return text.strip(), max(confidence, 0.3)

            except Exception:
                continue

        return None, 0.0

    @staticmethod
    async def extract_name(page: Page) -> Tuple[Optional[str], float]:
        """Extract business name."""
        name, confidence = await GoogleMapsParser.extract_field(page, "name")
        if name:
            name = GoogleMapsParser._clean_text(name)
        return name, confidence

    @staticmethod
    async def extract_address(page: Page) -> Tuple[Optional[str], float]:
        """Extract business address."""
        address, confidence = await GoogleMapsParser.extract_field(page, "address")
        if address:
            address = GoogleMapsParser._clean_address(address)
        return address, confidence

    @staticmethod
    async def extract_phone(page: Page) -> Tuple[Optional[str], float]:
        """Extract phone number."""
        # Try to get from text first
        phone, confidence = await GoogleMapsParser.extract_field(page, "phone")

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
            phone = GoogleMapsParser._clean_phone(phone)

        return phone, confidence

    @staticmethod
    async def extract_website(page: Page) -> Tuple[Optional[str], float]:
        """Extract website URL."""
        website = None
        confidence = 0.0

        for selector in GoogleMapsParser.SELECTORS["website"]:
            try:
                element = await page.query_selector(selector)
                if element:
                    href = await element.get_attribute("href")
                    if href and GoogleMapsParser._is_valid_website(href):
                        website = href
                        confidence = 0.9
                        break
            except Exception:
                continue

        return website, confidence

    @staticmethod
    async def extract_rating(page: Page) -> Tuple[Optional[float], float]:
        """Extract rating score."""
        rating_text, confidence = await GoogleMapsParser.extract_field(page, "rating")

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
        reviews_text, confidence = await GoogleMapsParser.extract_field(page, "reviews_count")

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
        category, confidence = await GoogleMapsParser.extract_field(page, "category")
        if category:
            category = GoogleMapsParser._clean_text(category)
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
            for selector in GoogleMapsParser.SELECTORS["hours"]:
                hours_container = await page.query_selector(selector)
                if hours_container:
                    # Extract all text from hours section
                    hours_text = await hours_container.text_content()
                    if hours_text:
                        hours_dict = GoogleMapsParser._parse_hours_text(hours_text)
                        confidence = 0.8 if hours_dict else 0.0
                        break

        except Exception:
            pass

        return hours_dict if hours_dict else None, confidence

    @staticmethod
    async def extract_price_range(page: Page) -> Tuple[Optional[str], float]:
        """Extract price range (e.g., "$", "$$", "$$$")."""
        price, confidence = await GoogleMapsParser.extract_field(page, "price_range")
        if price:
            # Normalize to dollar signs
            price = GoogleMapsParser._normalize_price_range(price)
        return price, confidence

    @staticmethod
    async def extract_all_fields(page: Page) -> Dict[str, Any]:
        """
        Extract all available fields from the page.

        Returns:
            Dictionary with extracted fields and metadata
        """
        result = {}

        # Extract each field
        name, name_conf = await GoogleMapsParser.extract_name(page)
        if name:
            result["name"] = name
            result["_conf_name"] = name_conf
            # Calculate name quality score
            result["name_quality_score"] = score_name_quality(name)
            result["name_length_flag"] = needs_standardization(name)

        address, addr_conf = await GoogleMapsParser.extract_address(page)
        if address:
            result["address"] = address
            result["_conf_address"] = addr_conf
            # Parse city/state/zip from address
            location = parse_location_from_address(address)
            result["city"] = location.get("city")
            result["state"] = location.get("state")
            result["zip_code"] = location.get("zip_code")

        phone, phone_conf = await GoogleMapsParser.extract_phone(page)
        if phone:
            result["phone"] = phone
            result["_conf_phone"] = phone_conf

        website, web_conf = await GoogleMapsParser.extract_website(page)
        if website:
            result["website"] = website
            result["_conf_website"] = web_conf

        rating, rating_conf = await GoogleMapsParser.extract_rating(page)
        if rating is not None:
            result["rating"] = rating
            result["_conf_rating"] = rating_conf

        reviews, reviews_conf = await GoogleMapsParser.extract_reviews_count(page)
        if reviews is not None:
            result["reviews_count"] = reviews
            result["_conf_reviews_count"] = reviews_conf

        category, cat_conf = await GoogleMapsParser.extract_category(page)
        if category:
            result["category"] = category
            result["_conf_category"] = cat_conf

        hours, hours_conf = await GoogleMapsParser.extract_hours(page)
        if hours:
            result["hours"] = hours
            result["_conf_hours"] = hours_conf

        price, price_conf = await GoogleMapsParser.extract_price_range(page)
        if price:
            result["price_range"] = price
            result["_conf_price_range"] = price_conf

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

        address = GoogleMapsParser._clean_text(address)

        # Remove "Copy address" or similar buttons text
        address = re.sub(r'(Copy address|Get directions)', '', address, flags=re.IGNORECASE)
        address = address.strip()

        return address

    @staticmethod
    def _clean_phone(phone: str) -> str:
        """Clean and normalize phone number."""
        if not phone:
            return ""

        # Remove common prefixes/suffixes
        phone = re.sub(r'(Call|Phone|Copy phone|Copy)', '', phone, flags=re.IGNORECASE)
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

        # Should not be Google domains
        google_domains = ["google.com", "gstatic.com", "googleapis.com"]
        if any(domain in url for domain in google_domains):
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
    def _normalize_price_range(price_text: str) -> str:
        """
        Normalize price range to dollar sign format.

        Args:
            price_text: Raw price range text

        Returns:
            Normalized price range ("$", "$$", "$$$", "$$$$")
        """
        if not price_text:
            return ""

        # Count dollar signs
        dollar_count = price_text.count('$')

        # If we found dollar signs, return them
        if dollar_count > 0:
            return '$' * min(dollar_count, 4)

        # Try to map text to dollar signs
        price_map = {
            "inexpensive": "$",
            "cheap": "$",
            "moderate": "$$",
            "mid-range": "$$",
            "expensive": "$$$",
            "very expensive": "$$$$",
            "luxury": "$$$$"
        }

        price_lower = price_text.lower()
        for key, value in price_map.items():
            if key in price_lower:
                return value

        return ""

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
    Parse all fields from a Google Maps business page.

    Args:
        page: Playwright Page object

    Returns:
        Dictionary with extracted business data
    """
    parser = GoogleMapsParser()
    return await parser.extract_all_fields(page)
