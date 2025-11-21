#!/usr/bin/env python3
"""
Google Maps business filtering module.

Filters out unwanted businesses:
- Equipment sellers/suppliers
- Ecommerce sites (Amazon, eBay, Home Depot, etc.)
- Installation/repair services
- Janitorial/interior cleaning
- Auto detailing
- Marketplaces and directories

Filtering logic:
1. Check for anti-keywords in business name/description
2. Check for ecommerce domains
3. Check for marketplace/directory domains
4. Calculate confidence score
"""

import re
from pathlib import Path
from typing import Dict, Set, Tuple, List
from urllib.parse import urlparse

from runner.logging_setup import get_logger

logger = get_logger("google_filter")


class GoogleFilter:
    """
    Filter and score Google Maps businesses based on keywords and domains.
    """

    def __init__(
        self,
        anti_keywords_file: str = 'data/anti_keywords.txt',
        positive_hints_file: str = 'data/yp_positive_hints.txt'
    ):
        """
        Initialize filter with data files.

        Args:
            anti_keywords_file: Path to shared anti-keywords file
            positive_hints_file: Path to positive hint phrases
        """
        self.anti_keywords = self._load_set(anti_keywords_file)
        self.positive_hints = self._load_set(positive_hints_file)

        # Ecommerce and marketplace domains to exclude
        self.blocked_domains = {
            # Ecommerce retailers
            'amazon.com', 'ebay.com', 'walmart.com', 'target.com',
            'homedepot.com', 'lowes.com', 'menards.com', 'acehardware.com',
            'northerntool.com', 'harborfreight.com', 'tractorsupply.com',

            # Marketplaces
            'etsy.com', 'alibaba.com', 'aliexpress.com',

            # Directories and listing sites
            'yelp.com', 'yellowpages.com', 'whitepages.com', 'superpages.com',
            'mapquest.com', 'angieslist.com', 'thumbtack.com',
            'porch.com', 'houzz.com', 'bbb.org', 'manta.com',

            # Social media
            'facebook.com', 'instagram.com', 'linkedin.com', 'twitter.com',
            'youtube.com', 'tiktok.com',

            # Generic/placeholder
            'example.com', 'test.com', 'placeholder.com',
        }

        # Ecommerce indicators in domain/URL
        self.ecommerce_indicators = {
            'shop', 'store', 'cart', 'checkout', 'buy', 'order',
            'ecommerce', 'e-commerce', 'online-store', 'webstore'
        }

        logger.info(f"✓ Google Filter initialized:")
        logger.info(f"  Anti-keywords: {len(self.anti_keywords)} terms")
        logger.info(f"  Positive hints: {len(self.positive_hints)} phrases")
        logger.info(f"  Blocked domains: {len(self.blocked_domains)} domains")

    def _load_set(self, file_path: str) -> Set[str]:
        """Load a text file into a set (case-insensitive)."""
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"{file_path} not found")
            return set()

        with open(path, 'r', encoding='utf-8') as f:
            items = {line.strip().lower() for line in f if line.strip()}

        return items

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison (lowercase, strip)."""
        if not text:
            return ""
        return text.lower().strip()

    def _has_anti_keyword(self, text: str) -> Tuple[bool, List[str]]:
        """
        Check if text contains any anti-keywords.

        Args:
            text: Text to check

        Returns:
            Tuple of (has_keyword, list_of_matches)
        """
        if not text:
            return False, []

        text_lower = self._normalize(text)
        matches = []

        for keyword in self.anti_keywords:
            if keyword in text_lower:
                matches.append(keyword)

        return len(matches) > 0, matches

    def _has_positive_hint(self, text: str) -> Tuple[bool, List[str]]:
        """
        Check if text contains any positive hint phrases.

        Args:
            text: Text to check

        Returns:
            Tuple of (has_hint, list_of_matches)
        """
        if not text:
            return False, []

        text_lower = self._normalize(text)
        matches = []

        for hint in self.positive_hints:
            if hint in text_lower:
                matches.append(hint)

        return len(matches) > 0, matches

    def _is_blocked_domain(self, url: str) -> Tuple[bool, str]:
        """
        Check if URL is from a blocked domain (ecommerce, marketplace, etc.).

        Args:
            url: URL to check

        Returns:
            Tuple of (is_blocked, domain)
        """
        if not url:
            return False, ""

        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]

            # Check exact domain matches
            if domain in self.blocked_domains:
                return True, domain

            # Check if any blocked domain is a suffix (e.g., amazon.com matches smile.amazon.com)
            for blocked in self.blocked_domains:
                if domain.endswith('.' + blocked) or domain == blocked:
                    return True, domain

            # Check for ecommerce indicators in domain
            for indicator in self.ecommerce_indicators:
                if indicator in domain:
                    logger.debug(f"Ecommerce indicator '{indicator}' found in domain: {domain}")
                    return True, domain

            return False, domain

        except Exception as e:
            logger.warning(f"Failed to parse URL '{url}': {e}")
            return False, ""

    def filter_business(self, business_data: Dict) -> Dict:
        """
        Filter a single Google Maps business.

        Args:
            business_data: Dict with keys: name, description, categories, url, website

        Returns:
            Dict with:
            - passed: Boolean (True if business passed filter)
            - confidence: Float 0-1 (confidence score)
            - filter_reason: String (reason for rejection if failed)
            - signals: Dict of positive/negative signals
        """
        name = business_data.get('name', '')
        description = business_data.get('description', '')
        categories = business_data.get('categories', [])
        url = business_data.get('url', '')  # Google Maps URL
        website = business_data.get('website', '')  # Business website

        # Combine text for checking
        combined_text = ' '.join([
            name,
            description,
            ' '.join(categories) if isinstance(categories, list) else str(categories)
        ])

        result = {
            'passed': True,
            'confidence': 0.5,  # Neutral starting point
            'filter_reason': '',
            'signals': {
                'anti_keywords': [],
                'positive_hints': [],
                'blocked_domain': False,
                'domain': ''
            }
        }

        # Check for anti-keywords in business name/description
        has_anti, anti_matches = self._has_anti_keyword(combined_text)
        if has_anti:
            result['passed'] = False
            result['confidence'] = 0.2
            result['filter_reason'] = f"Anti-keywords in business info: {', '.join(anti_matches[:3])}"
            result['signals']['anti_keywords'] = anti_matches
            logger.debug(f"FILTERED: {name} - Anti-keywords: {anti_matches}")
            return result

        # Check for blocked/ecommerce domains
        is_blocked, domain = self._is_blocked_domain(website)
        if is_blocked:
            result['passed'] = False
            result['confidence'] = 0.1
            result['filter_reason'] = f"Blocked domain: {domain}"
            result['signals']['blocked_domain'] = True
            result['signals']['domain'] = domain
            logger.debug(f"FILTERED: {name} - Blocked domain: {domain}")
            return result

        # Check for positive hints (boosts confidence)
        has_positive, positive_matches = self._has_positive_hint(combined_text)
        if has_positive:
            result['confidence'] = 0.8
            result['signals']['positive_hints'] = positive_matches
            logger.debug(f"BOOSTED: {name} - Positive hints: {positive_matches}")
        else:
            # No anti-keywords, no positive hints = neutral
            result['confidence'] = 0.6

        result['signals']['domain'] = domain
        return result

    def filter_batch(self, businesses: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Filter a batch of businesses.

        Args:
            businesses: List of business dicts

        Returns:
            Tuple of (passed_businesses, filtered_businesses)
        """
        passed = []
        filtered = []

        for business in businesses:
            filter_result = self.filter_business(business)

            # Add filter metadata to business
            business['filter_result'] = filter_result
            business['confidence_score'] = filter_result['confidence']

            if filter_result['passed']:
                passed.append(business)
            else:
                filtered.append(business)

        logger.info(f"Filter results: {len(passed)} passed, {len(filtered)} filtered")
        return passed, filtered


# Module-level function for easy import
def create_filter() -> GoogleFilter:
    """Create and return a GoogleFilter instance."""
    return GoogleFilter()


if __name__ == "__main__":
    # Quick test
    filter = create_filter()

    test_businesses = [
        {
            'name': 'ABC Pressure Washing',
            'description': 'Professional pressure washing services',
            'categories': ['Pressure Washing'],
            'website': 'https://abcpressurewashing.com'
        },
        {
            'name': 'Home Depot',
            'description': 'Pressure washer equipment and supplies',
            'categories': ['Hardware Store'],
            'website': 'https://www.homedepot.com/pressure-washers'
        },
        {
            'name': 'Joe\'s Pressure Washer Rental',
            'description': 'Equipment rental',
            'categories': ['Equipment Rental'],
            'website': 'https://joesrentals.com'
        }
    ]

    for biz in test_businesses:
        result = filter.filter_business(biz)
        print(f"\n{biz['name']}: {'PASS' if result['passed'] else 'FAIL'}")
        print(f"  Confidence: {result['confidence']}")
        if not result['passed']:
            print(f"  Reason: {result['filter_reason']}")
