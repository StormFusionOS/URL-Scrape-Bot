#!/usr/bin/env python3
"""
YP listing filtering and scoring module.

This module implements precision-first filtering to eliminate:
- Equipment sellers/suppliers
- Installation/repair services
- Janitorial/interior cleaning
- Auto detailing
- Other non-target businesses

Filtering logic:
1. Must have at least one category tag in allowlist
2. Must NOT have any category tag in blocklist
3. Must NOT have anti-keywords in business name/description
4. Special handling for "Equipment & Services" category
5. Confidence scoring based on positive/negative signals
"""

import re
from pathlib import Path
from typing import List, Dict, Set, Tuple
from urllib.parse import urlparse

from runner.logging_setup import get_logger

logger = get_logger("yp_filter")


class YPFilter:
    """
    Filter and score YP listings based on category tags and keywords.
    """

    def __init__(
        self,
        allowlist_file: str = 'data/yp_category_allowlist.txt',
        blocklist_file: str = 'data/yp_category_blocklist.txt',
        anti_keywords_file: str = 'data/anti_keywords.txt',
        positive_hints_file: str = 'data/yp_positive_hints.txt'
    ):
        """
        Initialize filter with data files.

        Args:
            allowlist_file: Path to category allowlist
            blocklist_file: Path to category blocklist
            anti_keywords_file: Path to shared anti-keywords file
            positive_hints_file: Path to positive hint phrases
        """
        self.allowlist = self._load_set(allowlist_file)
        self.blocklist = self._load_set(blocklist_file)
        self.anti_keywords = self._load_set(anti_keywords_file)
        self.positive_hints = self._load_set(positive_hints_file)

        # Special category that needs extra filtering
        self.equipment_category = "Pressure Washing Equipment & Services"

        print(f"✓ Filter initialized:")
        print(f"  Allowlist: {len(self.allowlist)} categories")
        print(f"  Blocklist: {len(self.blocklist)} categories")
        print(f"  Anti-keywords: {len(self.anti_keywords)} terms")
        print(f"  Positive hints: {len(self.positive_hints)} phrases")

    def _load_set(self, file_path: str) -> Set[str]:
        """Load a text file into a set (case-insensitive)."""
        path = Path(file_path)
        if not path.exists():
            print(f"Warning: {file_path} not found")
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
            # Use word boundary matching to avoid false positives
            # e.g., "supplies" should match but "supplier cleaning" should also match
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

    def _check_category_tags(self, tags: List[str]) -> Dict[str, any]:
        """
        Check category tags against allowlist and blocklist.

        Args:
            tags: List of category tag strings

        Returns:
            Dict with:
            - allowed_tags: List of tags in allowlist
            - blocked_tags: List of tags in blocklist
            - has_equipment: Boolean indicating if "Equipment & Services" category
        """
        tags_normalized = [self._normalize(tag) for tag in tags]

        allowed_tags = []
        blocked_tags = []
        has_equipment = False

        for i, tag_norm in enumerate(tags_normalized):
            original_tag = tags[i]

            # Check allowlist
            if tag_norm in self.allowlist:
                allowed_tags.append(original_tag)

            # Check blocklist
            if tag_norm in self.blocklist:
                blocked_tags.append(original_tag)

            # Check for equipment category
            if tag_norm == self._normalize(self.equipment_category):
                has_equipment = True

        return {
            'allowed_tags': allowed_tags,
            'blocked_tags': blocked_tags,
            'has_equipment': has_equipment
        }

    def _is_ecommerce_url(self, url: str) -> Tuple[bool, str]:
        """
        Detect e-commerce sites based on URL patterns.

        This method blocks websites that are clearly selling products online
        rather than providing services. Detection is done purely by URL analysis
        with no HTTP requests, making it fast and efficient.

        Args:
            url: Website URL to check

        Returns:
            Tuple of (is_ecommerce, detected_pattern)
            - is_ecommerce: True if URL indicates an e-commerce site
            - detected_pattern: String describing what pattern was detected
        """
        if not url:
            return False, ""

        url_lower = url.lower()

        # E-commerce platform subdomains (100% confidence)
        ecommerce_domains = [
            '.myshopify.com',      # Shopify stores
            '.bigcartel.com',      # Big Cartel
            '.square.site',        # Square online stores
            '.ecwid.com',          # Ecwid stores
            '.shoplightspeed.com', # Lightspeed
            '.shoplo.com',         # Shoplo
            '.3dcart.com',         # 3dcart
            '.squarespace.com/commerce',  # Squarespace commerce
            '.wixsite.com/shop',   # Wix commerce (with /shop)
        ]

        for domain in ecommerce_domains:
            if domain in url_lower:
                return True, f"e-commerce platform: {domain}"

        # E-commerce URL paths (95%+ confidence)
        ecommerce_paths = [
            '/shop/',
            '/shop',
            '/store/',
            '/store',
            '/products/',
            '/product/',
            '/cart/',
            '/cart',
            '/checkout/',
            '/checkout',
            '/collections/',      # Shopify pattern
            '/buy-now',
            '/order-online',
            '/merchandise',
            '/merch',
            '/add-to-cart',
        ]

        for path in ecommerce_paths:
            if path in url_lower:
                return True, f"e-commerce path: {path}"

        # Check domain for shop/store keywords (conservative)
        # Only flag if it's clearly an online store in the domain itself
        try:
            parsed = urlparse(url_lower)
            domain = parsed.netloc.replace('www.', '')

            # Be conservative - only flag obvious e-commerce domain names
            # Don't flag "Joe's Pressure Wash Shop" type business names
            ecommerce_domain_keywords = ['onlinestore', 'webstore', 'webshop', 'eshop', 'e-shop']
            for kw in ecommerce_domain_keywords:
                if kw in domain.replace('-', '').replace('_', ''):
                    return True, f"e-commerce domain keyword: {kw}"

        except Exception:
            # If URL parsing fails, don't block
            pass

        return False, ""

    def _is_toll_free_number(self, phone: str) -> Tuple[bool, str]:
        """
        Check if phone number is a toll-free number.

        Toll-free numbers (1-800, 1-888, 1-877, 1-866, 1-855, 1-844, 1-833)
        typically indicate national chains, lead-gen services, or call centers
        rather than local service businesses.

        Args:
            phone: Phone number string

        Returns:
            Tuple of (is_toll_free, reason)
        """
        if not phone:
            return False, ""

        # Normalize phone - remove all non-digits
        digits = re.sub(r'\D', '', phone)

        # Toll-free prefixes (after removing leading 1 for US numbers)
        toll_free_prefixes = ['800', '888', '877', '866', '855', '844', '833']

        # Check if starts with 1 + toll-free prefix or just toll-free prefix
        for prefix in toll_free_prefixes:
            if digits.startswith('1' + prefix) or digits.startswith(prefix):
                return True, f"toll-free: {prefix}"

        return False, ""

    def should_include(self, listing: Dict) -> Tuple[bool, str, float]:
        """
        Determine if a listing should be included based on filtering rules.

        Filtering logic:
        1. Must have at least one allowed category tag
        2. Must NOT have any blocked category tags
        3. Must NOT have anti-keywords in name
        4. Special case for "Equipment & Services" category
        5. Must NOT have e-commerce URL
        6. Must have website

        Args:
            listing: Listing dict with keys: name, category_tags, description (optional)

        Returns:
            Tuple of (should_include, reason_code, confidence_score)
            - should_include: Boolean
            - reason_code: Concise code explaining the decision (e.g., "no_website", "mismatch_category")
            - confidence_score: Float (0-100) indicating confidence
        """
        name = listing.get('name', '')
        category_tags = listing.get('category_tags', [])
        description = listing.get('description', '')
        services = listing.get('services', '')

        # Combine text fields for keyword checking
        combined_text = f"{name} {description} {services}".lower()

        # Check category tags
        tag_check = self._check_category_tags(category_tags)
        allowed_tags = tag_check['allowed_tags']
        blocked_tags = tag_check['blocked_tags']
        has_equipment = tag_check['has_equipment']

        # Rule 1: Must have at least one allowed tag
        if not allowed_tags:
            # Debug: log what category tags were found
            if category_tags:
                logger.debug(f"Rejected '{name}': Found tags {category_tags} but none matched allowlist")
                return False, "mismatch_category", 0.0
            else:
                logger.debug(f"Rejected '{name}': No category tags extracted")
                return False, "no_category", 0.0

        # Rule 2: Must NOT have blocked tags
        if blocked_tags:
            # Return first blocked tag as part of code
            return False, f"blocked_category:{blocked_tags[0][:20]}", 0.0

        # Rule 3: Check for anti-keywords in name
        has_anti, anti_matches = self._has_anti_keyword(name)
        if has_anti:
            # Return first anti-keyword match
            return False, f"anti_keyword:{anti_matches[0][:20]}", 0.0

        # Rule 4: Special case for "Equipment & Services"
        if has_equipment:
            # Only keep if:
            # a) Has another positive tag, OR
            # b) Has positive hints in description/services
            has_other_positive = len(allowed_tags) > 1  # More than just equipment tag

            has_positive_hint, hint_matches = self._has_positive_hint(combined_text)

            if not has_other_positive and not has_positive_hint:
                return False, "equipment_only", 0.0

        # Rule 5: Check for e-commerce URLs
        website = listing.get('website', '')
        if website:
            is_ecommerce, ecommerce_reason = self._is_ecommerce_url(website)
            if is_ecommerce:
                return False, "ecommerce_url", 0.0

        # Rule 6: Must have website
        if not website:
            return False, "no_website", 0.0

        # Calculate confidence score
        score = self._calculate_score(listing, allowed_tags, combined_text)

        return True, "accepted", score

    def _calculate_score(
        self,
        listing: Dict,
        allowed_tags: List[str],
        combined_text: str
    ) -> float:
        """
        Calculate confidence score for a listing (0-100).

        Scoring:
        - +10 points per allowed category tag
        - +5 points per positive hint phrase in text
        - -10 points if "Equipment & Services" is only allowed tag
        - +5 points if has website
        - +3 points if has rating
        - -10 points per anti-keyword in description (not name, already filtered)

        Args:
            listing: Listing dict
            allowed_tags: List of allowed category tags
            combined_text: Combined text for keyword checking

        Returns:
            Confidence score (0-100)
        """
        score = 50.0  # Base score

        # Category tags (max +50)
        score += min(len(allowed_tags) * 10, 50)

        # Positive hints (max +25)
        has_positive, hint_matches = self._has_positive_hint(combined_text)
        score += min(len(hint_matches) * 5, 25)

        # Penalize if only equipment tag (reduced from -20 to -10 to be less aggressive)
        if "equipment" in " ".join(allowed_tags).lower() and len(allowed_tags) == 1:
            score -= 10

        # Bonus for having website
        if listing.get('website'):
            score += 5

        # Bonus for having rating/reviews
        if listing.get('rating_yp'):
            score += 3

        # Check for anti-keywords in description (less harsh than in name)
        services = listing.get('services', [])
        services_text = ' '.join(services) if isinstance(services, list) else str(services) if services else ''
        description = listing.get('description', '') + ' ' + services_text
        if description:
            has_anti, anti_matches = self._has_anti_keyword(description)
            if has_anti:
                score -= min(len(anti_matches) * 10, 30)

        # Clamp to 0-100
        score = max(0.0, min(100.0, score))

        return score

    def filter_listings(
        self,
        listings: List[Dict],
        min_score: float = 40.0,
        include_sponsored: bool = False
    ) -> Tuple[List[Dict], Dict[str, int]]:
        """
        Filter a list of listings and add scores.

        Args:
            listings: List of listing dicts
            min_score: Minimum confidence score to include (default: 50.0)
            include_sponsored: Include sponsored/ad listings (default: False)

        Returns:
            Tuple of (filtered_listings, stats_dict)
            - filtered_listings: List of accepted listings with 'filter_score' and 'filter_reason' added
            - stats_dict: Dict with filtering statistics
        """
        stats = {
            'total': len(listings),
            'accepted': 0,
            'rejected': 0,
            'rejected_reasons': {},
            'score_avg': 0.0,
            'score_min': 100.0,
            'score_max': 0.0,
        }

        accepted = []
        scores = []

        for listing in listings:
            # Skip sponsored if requested
            if not include_sponsored and listing.get('is_sponsored', False):
                stats['rejected'] += 1
                reason = 'sponsored'  # Concise code
                stats['rejected_reasons'][reason] = stats['rejected_reasons'].get(reason, 0) + 1
                continue

            # Apply filtering rules
            should_include, reason, score = self.should_include(listing)

            if should_include and score >= min_score:
                # Add filter metadata
                listing['filter_score'] = score
                listing['filter_reason'] = reason
                accepted.append(listing)
                scores.append(score)
                stats['accepted'] += 1
            else:
                stats['rejected'] += 1
                # Handle low score rejection
                if should_include and score < min_score:
                    reason = f"low_score:{int(score)}"
                stats['rejected_reasons'][reason] = stats['rejected_reasons'].get(reason, 0) + 1

        # Calculate score statistics
        if scores:
            stats['score_avg'] = sum(scores) / len(scores)
            stats['score_min'] = min(scores)
            stats['score_max'] = max(scores)

        return accepted, stats


# Convenience function for quick filtering
def filter_yp_listings(
    listings: List[Dict],
    min_score: float = 40.0,
    include_sponsored: bool = False
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Convenience function to filter listings with default settings.

    Args:
        listings: List of listing dicts
        min_score: Minimum confidence score
        include_sponsored: Include sponsored listings

    Returns:
        Tuple of (filtered_listings, stats)
    """
    filter_obj = YPFilter()
    return filter_obj.filter_listings(listings, min_score, include_sponsored)
