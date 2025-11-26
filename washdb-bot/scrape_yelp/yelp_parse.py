#!/usr/bin/env python3
"""
Yelp business parser - extract structured data from Yelp business pages.

Extracts:
- Business name
- Address
- Phone number
- Website
- Rating
- Review count
- Categories
- Business hours
- Description/specialties
"""

import re
from typing import Dict, List, Optional
from playwright.async_api import Page

from runner.logging_setup import get_logger

logger = get_logger("yelp_parse")


class YelpParser:
    """
    Parse business information from Yelp pages.
    """

    @staticmethod
    async def extract_all_fields(page: Page) -> Dict:
        """
        Extract all available fields from a Yelp business page.

        Args:
            page: Playwright Page object

        Returns:
            Dict with business information
        """
        data = {}

        try:
            # Business name
            try:
                name_elem = await page.query_selector('h1')
                if name_elem:
                    data['name'] = await name_elem.inner_text()
            except Exception as e:
                logger.debug(f"Failed to extract name: {e}")

            # Rating
            try:
                rating_elem = await page.query_selector('[aria-label*="star rating"]')
                if rating_elem:
                    rating_text = await rating_elem.get_attribute('aria-label')
                    if rating_text:
                        match = re.search(r'(\d+\.?\d*)\s*star', rating_text)
                        if match:
                            data['rating'] = float(match.group(1))
            except Exception as e:
                logger.debug(f"Failed to extract rating: {e}")

            # Review count
            try:
                review_elem = await page.query_selector('a[href*="#reviews"]')
                if review_elem:
                    review_text = await review_elem.inner_text()
                    match = re.search(r'(\d+)', review_text.replace(',', ''))
                    if match:
                        data['reviews_count'] = int(match.group(1))
            except Exception as e:
                logger.debug(f"Failed to extract review count: {e}")

            # Categories
            try:
                categories = []
                category_elems = await page.query_selector_all('a[href*="/search?cflt="]')
                for elem in category_elems[:5]:  # Limit to first 5
                    cat = await elem.inner_text()
                    if cat:
                        categories.append(cat.strip())
                if categories:
                    data['categories'] = categories
            except Exception as e:
                logger.debug(f"Failed to extract categories: {e}")

            # Address
            try:
                address_elem = await page.query_selector('[data-testid="businessinfo-address"]')
                if address_elem:
                    address_text = await address_elem.inner_text()
                    data['address'] = address_text.strip()
            except Exception as e:
                logger.debug(f"Failed to extract address: {e}")

            # Phone
            try:
                phone_elem = await page.query_selector('[href^="tel:"]')
                if phone_elem:
                    phone = await phone_elem.inner_text()
                    data['phone'] = phone.strip()
            except Exception as e:
                logger.debug(f"Failed to extract phone: {e}")

            # Website
            try:
                website_elem = await page.query_selector('a[href*="/biz_redir"]')
                if website_elem:
                    # Yelp wraps business websites through a redirect
                    # We'll store the redirect URL for now
                    website_url = await website_elem.get_attribute('href')
                    if website_url and '/biz_redir' in website_url:
                        # Try to extract actual URL from redirect
                        # Format: /biz_redir?url=<encoded_url>&...
                        import urllib.parse
                        parsed = urllib.parse.urlparse(website_url)
                        params = urllib.parse.parse_qs(parsed.query)
                        if 'url' in params:
                            actual_url = params['url'][0]
                            data['website'] = actual_url
            except Exception as e:
                logger.debug(f"Failed to extract website: {e}")

            # Business hours
            try:
                hours_table = await page.query_selector('table[aria-label="Hours"]')
                if hours_table:
                    hours = {}
                    rows = await hours_table.query_selector_all('tr')
                    for row in rows:
                        cells = await row.query_selector_all('td, th')
                        if len(cells) >= 2:
                            day = await cells[0].inner_text()
                            time = await cells[1].inner_text()
                            hours[day.strip()] = time.strip()
                    if hours:
                        data['hours'] = hours
            except Exception as e:
                logger.debug(f"Failed to extract hours: {e}")

            # Description/About section
            try:
                about_elem = await page.query_selector('[data-testid="businessinfo-specialties"]')
                if about_elem:
                    description = await about_elem.inner_text()
                    data['description'] = description.strip()
            except Exception as e:
                logger.debug(f"Failed to extract description: {e}")

        except Exception as e:
            logger.error(f"Error extracting fields from Yelp page: {e}")

        return data

    @staticmethod
    async def extract_search_results(page: Page, max_results: int = 20) -> List[Dict]:
        """
        Extract business cards from Yelp search results.

        Args:
            page: Playwright Page object
            max_results: Maximum number of results to extract

        Returns:
            List of business dicts
        """
        results = []

        try:
            # Yelp search results are in a list format
            # Each result is typically an article or li element
            result_cards = await page.query_selector_all('[data-testid="serp-ia-card"]')

            if not result_cards:
                # Fallback selectors
                result_cards = await page.query_selector_all('li[data-id]')

            logger.debug(f"Found {len(result_cards)} result cards")

            for idx, card in enumerate(result_cards[:max_results]):
                try:
                    business = {}

                    # Extract business name and URL
                    name_link = await card.query_selector('a[href*="/biz/"]')
                    if name_link:
                        business['name'] = await name_link.inner_text()
                        business['url'] = 'https://www.yelp.com' + await name_link.get_attribute('href')

                    # Extract rating
                    rating_elem = await card.query_selector('[aria-label*="star rating"]')
                    if rating_elem:
                        rating_text = await rating_elem.get_attribute('aria-label')
                        if rating_text:
                            match = re.search(r'(\d+\.?\d*)\s*star', rating_text)
                            if match:
                                business['rating'] = float(match.group(1))

                    # Extract review count
                    review_elem = await card.query_selector('span[aria-label*="reviews"]')
                    if review_elem:
                        review_text = await review_elem.inner_text()
                        match = re.search(r'(\d+)', review_text.replace(',', ''))
                        if match:
                            business['reviews_count'] = int(match.group(1))

                    # Extract categories
                    category_elems = await card.query_selector_all('a[href*="/search?cflt="]')
                    if category_elems:
                        categories = []
                        for cat_elem in category_elems[:3]:
                            cat = await cat_elem.inner_text()
                            if cat:
                                categories.append(cat.strip())
                        business['categories'] = categories

                    # Extract address
                    address_elem = await card.query_selector('p[data-testid="address"]')
                    if address_elem:
                        business['address'] = await address_elem.inner_text()

                    # Extract phone
                    phone_elem = await card.query_selector('[href^="tel:"]')
                    if phone_elem:
                        business['phone'] = await phone_elem.inner_text()

                    # Only add if we got at least a name
                    if business.get('name'):
                        results.append(business)

                except Exception as e:
                    logger.warning(f"Error extracting result card {idx}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error extracting search results: {e}")

        return results
