#!/usr/bin/env python3
"""
Advanced deduplication module for Yellow Pages data.

This module provides fuzzy matching and deduplication capabilities:
- Fuzzy name matching (Levenshtein distance)
- Phone number deduplication
- Address similarity detection
- URL/domain deduplication
- Multi-field composite matching
"""

import re
from typing import List, Dict, Tuple, Set, Optional
from difflib import SequenceMatcher


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate Levenshtein distance between two strings.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Edit distance (number of operations to transform s1 into s2)
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity_ratio(s1: str, s2: str) -> float:
    """
    Calculate similarity ratio between two strings (0-1).

    Uses SequenceMatcher for fast similarity calculation.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Similarity ratio (0.0 = completely different, 1.0 = identical)
    """
    if not s1 or not s2:
        return 0.0

    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def fuzzy_match_threshold(s1: str, s2: str, threshold: float = 0.85) -> bool:
    """
    Check if two strings match above a similarity threshold.

    Args:
        s1: First string
        s2: Second string
        threshold: Similarity threshold (0-1, default: 0.85)

    Returns:
        True if similarity >= threshold
    """
    if not s1 or not s2:
        return False

    return similarity_ratio(s1, s2) >= threshold


def normalize_business_name_for_matching(name: str) -> str:
    """
    Normalize business name for fuzzy matching.

    Removes common variations:
    - Legal suffixes (LLC, Inc, Corp)
    - Special characters
    - Extra whitespace
    - Case differences

    Args:
        name: Business name

    Returns:
        Normalized name for matching
    """
    if not name:
        return ""

    # Convert to lowercase
    normalized = name.lower()

    # Remove common legal suffixes
    suffixes = [
        r'\bllc\b', r'\bllp\b', r'\binc\b', r'\bincorporated\b',
        r'\bcorp\b', r'\bcorporation\b', r'\bltd\b', r'\blimited\b',
        r'\bco\b', r'\bcompany\b', r'\benterprises\b'
    ]
    for suffix in suffixes:
        normalized = re.sub(suffix, '', normalized, flags=re.IGNORECASE)

    # Remove special characters (keep letters, numbers, spaces)
    normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)

    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    return normalized


def fuzzy_match_business_name(name1: str, name2: str, threshold: float = 0.85) -> Tuple[bool, float]:
    """
    Check if two business names are likely duplicates using fuzzy matching.

    Args:
        name1: First business name
        name2: Second business name
        threshold: Similarity threshold (default: 0.85)

    Returns:
        Tuple of (is_duplicate, similarity_score)
    """
    if not name1 or not name2:
        return False, 0.0

    # Normalize both names
    norm1 = normalize_business_name_for_matching(name1)
    norm2 = normalize_business_name_for_matching(name2)

    # Calculate similarity
    similarity = similarity_ratio(norm1, norm2)

    # Check if above threshold
    is_match = similarity >= threshold

    return is_match, similarity


def extract_domain(url: str) -> Optional[str]:
    """
    Extract domain from URL.

    Args:
        url: Full URL

    Returns:
        Domain (e.g., 'example.com') or None
    """
    if not url:
        return None

    # Remove protocol
    domain = re.sub(r'^https?://', '', url.lower())

    # Remove www.
    domain = re.sub(r'^www\.', '', domain)

    # Remove path and query
    domain = domain.split('/')[0].split('?')[0]

    return domain if domain else None


def are_same_business(
    business1: Dict,
    business2: Dict,
    name_threshold: float = 0.85,
    strict: bool = False
) -> Tuple[bool, str, float]:
    """
    Determine if two business records represent the same business.

    Uses multi-field matching:
    - Phone number (exact match)
    - Domain (exact match)
    - Business name (fuzzy match)
    - Address (fuzzy match if available)

    Args:
        business1: First business dict
        business2: Second business dict
        name_threshold: Fuzzy matching threshold for names (default: 0.85)
        strict: If True, require multiple field matches (default: False)

    Returns:
        Tuple of (is_duplicate, reason, confidence_score)
        - is_duplicate: Boolean
        - reason: String explaining the match
        - confidence_score: 0-100 indicating confidence
    """
    matches = []
    confidence = 0.0

    # 1. Check phone number (exact match after normalization)
    phone1 = business1.get('phone')
    phone2 = business2.get('phone')
    if phone1 and phone2 and phone1 == phone2:
        matches.append('phone')
        confidence += 40.0  # Phone match is very strong signal

    # 2. Check domain (exact match)
    website1 = business1.get('website')
    website2 = business2.get('website')
    if website1 and website2:
        domain1 = extract_domain(website1)
        domain2 = extract_domain(website2)
        if domain1 and domain2 and domain1 == domain2:
            matches.append('domain')
            confidence += 35.0  # Domain match is strong signal

    # 3. Check business name (fuzzy match)
    name1 = business1.get('name')
    name2 = business2.get('name')
    if name1 and name2:
        is_name_match, name_similarity = fuzzy_match_business_name(name1, name2, name_threshold)
        if is_name_match:
            matches.append('name')
            confidence += name_similarity * 25.0  # Up to 25 points for name

    # 4. Check address (fuzzy match if both have addresses)
    address1 = business1.get('address')
    address2 = business2.get('address')
    if address1 and address2:
        addr_similarity = similarity_ratio(address1, address2)
        if addr_similarity >= 0.80:
            matches.append('address')
            confidence += addr_similarity * 20.0  # Up to 20 points for address

    # Decision logic
    if strict:
        # Strict mode: require at least 2 field matches
        is_duplicate = len(matches) >= 2
    else:
        # Normal mode: any strong signal is enough
        is_duplicate = (
            'phone' in matches or
            'domain' in matches or
            (len(matches) >= 2)  # Or 2+ weaker signals
        )

    # Build reason string
    if matches:
        reason = f"Matched on: {', '.join(matches)}"
    else:
        reason = "No significant matches"

    # Clamp confidence to 0-100
    confidence = max(0.0, min(100.0, confidence))

    return is_duplicate, reason, confidence


class DuplicateDetector:
    """
    Detects and tracks duplicates in a stream of business records.

    Maintains an internal index of seen businesses and performs
    fuzzy matching against new records.
    """

    def __init__(self, name_threshold: float = 0.85, strict: bool = False):
        """
        Initialize duplicate detector.

        Args:
            name_threshold: Fuzzy matching threshold for names (0-1)
            strict: Require multiple field matches (default: False)
        """
        self.name_threshold = name_threshold
        self.strict = strict

        # Indexes for fast lookup
        self.phone_index: Dict[str, List[Dict]] = {}  # phone -> [businesses]
        self.domain_index: Dict[str, List[Dict]] = {}  # domain -> [businesses]
        self.all_businesses: List[Dict] = []

        # Statistics
        self.total_checked = 0
        self.duplicates_found = 0
        self.unique_found = 0

    def is_duplicate(self, business: Dict) -> Tuple[bool, Optional[Dict], str, float]:
        """
        Check if a business is a duplicate of any previously seen business.

        Args:
            business: Business dict to check

        Returns:
            Tuple of (is_duplicate, matching_business, reason, confidence)
        """
        self.total_checked += 1

        # Quick lookup by phone
        phone = business.get('phone')
        if phone and phone in self.phone_index:
            for existing in self.phone_index[phone]:
                is_dup, reason, confidence = are_same_business(
                    business, existing, self.name_threshold, self.strict
                )
                if is_dup:
                    self.duplicates_found += 1
                    return True, existing, reason, confidence

        # Quick lookup by domain
        website = business.get('website')
        if website:
            domain = extract_domain(website)
            if domain and domain in self.domain_index:
                for existing in self.domain_index[domain]:
                    is_dup, reason, confidence = are_same_business(
                        business, existing, self.name_threshold, self.strict
                    )
                    if is_dup:
                        self.duplicates_found += 1
                        return True, existing, reason, confidence

        # Fuzzy matching against all businesses (slower)
        # Only do this if no phone/domain match found
        # Limited to prevent O(n²) performance issues
        name = business.get('name')
        if name:
            # Check only last 100 businesses for fuzzy name match
            # (Assuming recent businesses are more likely to be duplicates)
            for existing in self.all_businesses[-100:]:
                is_dup, reason, confidence = are_same_business(
                    business, existing, self.name_threshold, self.strict
                )
                if is_dup:
                    self.duplicates_found += 1
                    return True, existing, reason, confidence

        # Not a duplicate
        self.unique_found += 1
        return False, None, "No duplicates found", 0.0

    def add(self, business: Dict):
        """
        Add a business to the duplicate detector's index.

        Args:
            business: Business dict to add
        """
        # Add to phone index
        phone = business.get('phone')
        if phone:
            if phone not in self.phone_index:
                self.phone_index[phone] = []
            self.phone_index[phone].append(business)

        # Add to domain index
        website = business.get('website')
        if website:
            domain = extract_domain(website)
            if domain:
                if domain not in self.domain_index:
                    self.domain_index[domain] = []
                self.domain_index[domain].append(business)

        # Add to all businesses list
        self.all_businesses.append(business)

    def check_and_add(self, business: Dict) -> Tuple[bool, Optional[Dict], str, float]:
        """
        Check if duplicate, and if not, add to index.

        Convenience method that combines is_duplicate() and add().

        Args:
            business: Business dict to check and add

        Returns:
            Tuple of (is_duplicate, matching_business, reason, confidence)
        """
        is_dup, matching, reason, confidence = self.is_duplicate(business)

        if not is_dup:
            self.add(business)

        return is_dup, matching, reason, confidence

    def get_stats(self) -> Dict[str, int]:
        """
        Get deduplication statistics.

        Returns:
            Dict with statistics
        """
        return {
            'total_checked': self.total_checked,
            'duplicates_found': self.duplicates_found,
            'unique_found': self.unique_found,
            'duplicate_rate': (
                (self.duplicates_found / self.total_checked * 100)
                if self.total_checked > 0 else 0.0
            ),
            'indexed_businesses': len(self.all_businesses),
            'phone_index_size': len(self.phone_index),
            'domain_index_size': len(self.domain_index),
        }


def deduplicate_list(
    businesses: List[Dict],
    name_threshold: float = 0.85,
    strict: bool = False
) -> Tuple[List[Dict], List[Dict]]:
    """
    Deduplicate a list of businesses.

    Args:
        businesses: List of business dicts
        name_threshold: Fuzzy matching threshold
        strict: Require multiple field matches

    Returns:
        Tuple of (unique_businesses, duplicates_removed)
    """
    detector = DuplicateDetector(name_threshold=name_threshold, strict=strict)

    unique = []
    duplicates = []

    for business in businesses:
        is_dup, matching, reason, confidence = detector.check_and_add(business)

        if is_dup:
            # Add metadata about the duplicate
            business['duplicate_of'] = matching.get('name')
            business['duplicate_reason'] = reason
            business['duplicate_confidence'] = confidence
            duplicates.append(business)
        else:
            unique.append(business)

    return unique, duplicates
