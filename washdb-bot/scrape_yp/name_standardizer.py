"""
Name Standardization Utilities

This module provides utilities for:
- Scoring business name quality (0-100)
- Standardizing names using domain inference
- Parsing location from address strings
- Building optimal search names for citation lookups

Example:
    Company "Hydro" with website hydrosoftwashne.com and address in Omaha
    becomes "Hydro Soft Wash NE, Omaha, NE" for citation searches.
"""

import re
import logging
from typing import Optional, Tuple, Dict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Common business suffixes to strip/normalize
BUSINESS_SUFFIXES = [
    'llc', 'inc', 'corp', 'co', 'ltd', 'limited', 'company',
    'services', 'service', 'solutions', 'group', 'enterprises',
]

# Common pressure washing/soft wash related words
SERVICE_KEYWORDS = [
    'pressure', 'power', 'soft', 'wash', 'washing', 'clean', 'cleaning',
    'exterior', 'roof', 'house', 'home', 'gutter', 'window', 'surface',
    'restoration', 'maintenance', 'hydro', 'pro', 'professional',
]

# State abbreviations
STATE_ABBREVS = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
    'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
    'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS',
    'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS',
    'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
    'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
    'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK',
    'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT',
    'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
    'wisconsin': 'WI', 'wyoming': 'WY', 'district of columbia': 'DC',
}

# Reverse mapping: abbreviation -> full name
ABBREV_TO_STATE = {v: k.title() for k, v in STATE_ABBREVS.items()}


def score_name_quality(name: str) -> int:
    """
    Score business name quality from 0-100.

    Factors:
    - Length (short names get penalized)
    - Contains service keywords (bonus)
    - Contains location indicator (bonus)
    - Is just a single word (penalty)
    - Contains only letters/numbers vs special chars

    Args:
        name: The business name to score

    Returns:
        Integer score 0-100
    """
    if not name or not name.strip():
        return 0

    name = name.strip()
    name_lower = name.lower()
    score = 50  # Start at neutral

    # Length scoring
    length = len(name)
    if length < 3:
        score -= 40  # Very short, very bad
    elif length < 5:
        score -= 30
    elif length < 8:
        score -= 20
    elif length < 10:
        score -= 10
    elif length >= 15:
        score += 10  # Longer names are more specific
    elif length >= 25:
        score += 15

    # Single word penalty
    words = name.split()
    if len(words) == 1:
        score -= 15
    elif len(words) >= 3:
        score += 10

    # Service keyword bonus
    service_keyword_count = sum(1 for kw in SERVICE_KEYWORDS if kw in name_lower)
    score += min(service_keyword_count * 5, 15)  # Cap bonus at 15

    # Location indicator bonus (state abbrev at end like "NE", "TX")
    has_location = False
    for abbrev in STATE_ABBREVS.values():
        if name_lower.endswith(f' {abbrev.lower()}') or name_lower.endswith(abbrev.lower()):
            has_location = True
            score += 10
            break

    # Check for city name in business name
    if not has_location:
        # Common location indicators
        location_words = ['city', 'county', 'metro', 'area', 'region']
        if any(word in name_lower for word in location_words):
            score += 5

    # Alphanumeric ratio (penalize names with too many special chars)
    alphanum_count = sum(1 for c in name if c.isalnum() or c.isspace())
    if length > 0:
        ratio = alphanum_count / length
        if ratio < 0.8:
            score -= 10

    # Generic name penalty (single common words)
    generic_names = ['wash', 'clean', 'pro', 'best', 'top', 'first', 'one', 'hydro']
    if name_lower in generic_names:
        score -= 25

    # Ensure score stays in 0-100 range
    return max(0, min(100, score))


def infer_name_from_domain(domain: str) -> Optional[str]:
    """
    Extract a readable business name from a domain.

    Example:
        hydrosoftwashne.com -> 'Hydro Soft Wash NE'
        abcpressurewashing.com -> 'ABC Pressure Washing'

    Args:
        domain: Domain name (with or without protocol)

    Returns:
        Inferred business name or None if couldn't parse
    """
    if not domain:
        return None

    # Extract domain from URL if full URL provided
    if '://' in domain:
        try:
            parsed = urlparse(domain)
            domain = parsed.netloc
        except Exception:
            pass

    # Remove www. prefix
    if domain.startswith('www.'):
        domain = domain[4:]

    # Remove TLD
    domain_parts = domain.split('.')
    if len(domain_parts) >= 2:
        name_part = domain_parts[0]
    else:
        name_part = domain

    # Don't process very short domains
    if len(name_part) < 4:
        return None

    # Split camelCase and concatenated words
    # First, insert spaces before capitals (for camelCase)
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', name_part)

    # Approach: use greedy matching to find all known words in order
    # Build list of known words (longer first for greedy match)
    known_words = [
        # Compound terms
        'pressurewashing', 'powerwashing', 'softwashing', 'softwash',
        # -ing forms (prioritize over base due to common domain patterns)
        'washing', 'cleaning', 'roofing', 'siding',
        # -s plurals - these are often used in domains
        'solutions', 'services', 'enterprises', 'exteriors',
        # Long base words
        'professional', 'restoration', 'maintenance', 'exterior',
        'pressure', 'company', 'service', 'solution',
        # Medium base words
        'window', 'gutter', 'surface', 'power', 'house', 'clean',
        # Short words
        'hydro', 'home', 'roof', 'soft', 'wash', 'pros', 'pro',
        'llc', 'inc',
    ]

    result_lower = result.lower()

    # Smart matching with backtracking
    def try_parse(text, word_list, memo=None):
        """Recursively try to parse text into known words with backtracking."""
        if memo is None:
            memo = {}
        if text in memo:
            return memo[text]
        if not text:
            return []

        best_result = None
        best_score = -1

        # Sort by length descending for greedy first attempt
        sorted_words = sorted(word_list, key=len, reverse=True)

        for word in sorted_words:
            if text.lower().startswith(word):
                rest = text[len(word):]
                rest_parsed = try_parse(rest, word_list, memo)
                if rest_parsed is not None:
                    candidate = [word] + rest_parsed
                    # Score: count of known words (more = better)
                    known_count = sum(1 for w in candidate if w in word_list)
                    # Penalize leftover unmatched text
                    unknown_chars = sum(len(w) for w in candidate if w not in word_list)
                    score = known_count * 10 - unknown_chars
                    if score > best_score:
                        best_score = score
                        best_result = candidate

        # If no word match or best result leaves unmatched text, try prefix extraction
        if best_result is None:
            # Check if there's any known word somewhere in the string
            for i in range(1, min(len(text) + 1, 20)):  # Limit prefix length
                for word in sorted_words:
                    if text[i:].lower().startswith(word):
                        rest_parsed = try_parse(text[i:], word_list, memo)
                        if rest_parsed is not None:
                            candidate = [text[:i]] + rest_parsed
                            known_count = sum(1 for w in candidate if w in word_list)
                            unknown_chars = sum(len(w) for w in candidate if w not in word_list)
                            score = known_count * 10 - unknown_chars
                            if score > best_score:
                                best_score = score
                                best_result = candidate

        if best_result is None:
            # Can't parse - return text as single unknown word
            best_result = [text]

        memo[text] = best_result
        return best_result

    words_found = try_parse(result_lower, known_words)

    # Filter out empty strings and join with spaces
    result_lower = ' '.join(w for w in words_found if w)

    # Check for state abbreviation at the END of string only
    # (to avoid matching "wa" in "wash", "in" in "cleaning", etc.)
    trailing_state = None
    for abbrev in STATE_ABBREVS.values():
        abbrev_lower = abbrev.lower()
        # Check if domain ends with state abbrev (2 chars)
        if result_lower.rstrip().endswith(abbrev_lower):
            # Make sure it's not part of a word (check char before)
            pos = result_lower.rstrip().rfind(abbrev_lower)
            if pos > 0:
                char_before = result_lower[pos - 1]
                if char_before == ' ':
                    # Already separated
                    trailing_state = abbrev
                    break
                elif char_before.isalpha():
                    # Stuck to word - separate it
                    result_lower = result_lower[:pos] + ' ' + result_lower[pos:]
                    trailing_state = abbrev
                    break

    # Handle numbers stuck to words
    result_lower = re.sub(r'(\d+)([a-z])', r'\1 \2', result_lower)
    result_lower = re.sub(r'([a-z])(\d+)', r'\1 \2', result_lower)

    # Clean up multiple spaces
    result_lower = re.sub(r'\s+', ' ', result_lower).strip()

    # Capitalize words appropriately
    words = result_lower.split()
    capitalized = []
    for i, word in enumerate(words):
        word_upper = word.upper()
        # Keep state abbreviations uppercase (but only if it's the trailing one)
        if i == len(words) - 1 and word_upper in STATE_ABBREVS.values():
            capitalized.append(word_upper)
        # Capitalize normal words
        else:
            capitalized.append(word.capitalize())

    result = ' '.join(capitalized)

    # Only return if we got something meaningful
    if len(result) >= 5 and len(result.split()) >= 2:
        return result

    return None


def parse_location_from_address(address: str) -> Dict[str, Optional[str]]:
    """
    Extract city, state, and ZIP from an address string.

    Examples:
        "123 Main St, Dallas, TX 75001" -> {city: "Dallas", state: "TX", zip: "75001"}
        "Dallas TX" -> {city: "Dallas", state: "TX", zip: None}

    Args:
        address: Full address string

    Returns:
        Dict with city, state, zip_code keys (values may be None)
    """
    result = {
        'city': None,
        'state': None,
        'zip_code': None,
    }

    if not address or not address.strip():
        return result

    address = address.strip()

    # Try to extract ZIP code (5 or 5+4 format)
    zip_match = re.search(r'\b(\d{5})(?:-\d{4})?\b', address)
    if zip_match:
        result['zip_code'] = zip_match.group(1)
        # Remove ZIP from address for further parsing
        address = address[:zip_match.start()].strip().rstrip(',')

    # Try to find state abbreviation
    state_pattern = r'\b([A-Z]{2})\b'
    state_matches = re.findall(state_pattern, address)

    # Filter to valid state abbreviations
    valid_states = [s for s in state_matches if s in ABBREV_TO_STATE]

    if valid_states:
        # Use the last valid state (usually comes after city)
        result['state'] = valid_states[-1]

        # Try to extract city (word(s) before state)
        state_idx = address.rfind(result['state'])
        if state_idx > 0:
            before_state = address[:state_idx].strip().rstrip(',').strip()
            # City is usually the last part after comma, or last 1-2 words
            if ',' in before_state:
                parts = before_state.split(',')
                result['city'] = parts[-1].strip()
            else:
                # Take last word or two as city name
                words = before_state.split()
                if len(words) >= 1:
                    # Handle multi-word cities like "New York", "Los Angeles"
                    if len(words) >= 2 and words[-2].lower() in ['new', 'los', 'san', 'las', 'fort', 'saint', 'st', 'el', 'la']:
                        result['city'] = ' '.join(words[-2:])
                    else:
                        result['city'] = words[-1]
    else:
        # Try to find full state name
        address_lower = address.lower()
        for state_name, abbrev in STATE_ABBREVS.items():
            if state_name in address_lower:
                result['state'] = abbrev
                # Find city before state name
                state_idx = address_lower.find(state_name)
                if state_idx > 0:
                    before = address[:state_idx].strip().rstrip(',').strip()
                    if ',' in before:
                        result['city'] = before.split(',')[-1].strip()
                break

    # Clean up city name
    if result['city']:
        # Remove any remaining numbers/special chars from city
        result['city'] = re.sub(r'^\d+\s*', '', result['city'])
        result['city'] = result['city'].strip(',').strip()
        # Capitalize properly
        result['city'] = result['city'].title()

    return result


def standardize_name(
    original_name: str,
    website_name: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    domain: Optional[str] = None
) -> Tuple[str, str, float]:
    """
    Create a standardized business name for citation searches.

    Priority order:
    1. If original name is good quality (score >= 60), use it
    2. If website_name provided and better, use it
    3. Try inferring from domain
    4. Add location suffix if name is short

    Args:
        original_name: The current business name
        website_name: Name found on website (if any)
        city: City for the business
        state: State abbreviation
        domain: Website domain

    Returns:
        Tuple of (standardized_name, source, confidence)
        - source: 'original', 'website', 'domain', 'location_enhanced'
        - confidence: 0.0-1.0
    """
    if not original_name:
        # Can't standardize without at least an original name
        if domain:
            inferred = infer_name_from_domain(domain)
            if inferred:
                return (inferred, 'domain', 0.6)
        return ('', 'none', 0.0)

    original_name = original_name.strip()
    original_score = score_name_quality(original_name)

    # Try website name if provided
    if website_name and website_name.strip():
        website_score = score_name_quality(website_name)
        if website_score > original_score and website_score >= 50:
            return (website_name.strip(), 'website', min(website_score / 100, 0.95))

    # Try domain inference if original is poor
    if original_score < 50 and domain:
        inferred = infer_name_from_domain(domain)
        if inferred:
            inferred_score = score_name_quality(inferred)
            if inferred_score > original_score:
                return (inferred, 'domain', min(inferred_score / 100, 0.85))

    # If name is short/generic but we have location, add location suffix
    if original_score < 60 and (city or state):
        location_suffix = []
        if city:
            location_suffix.append(city)
        if state:
            location_suffix.append(state)

        if location_suffix:
            enhanced_name = f"{original_name}, {', '.join(location_suffix)}"
            return (enhanced_name, 'location_enhanced', 0.7)

    # Original is good enough
    confidence = min(original_score / 100, 0.95)
    return (original_name, 'original', confidence)


def get_search_name(
    name: str,
    standardized_name: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None
) -> str:
    """
    Build the optimal search string for citation lookups.

    Uses standardized_name if available, otherwise name.
    Appends city, state if available and not already in name.

    Args:
        name: Original business name
        standardized_name: Standardized name (if available)
        city: City for location
        state: State abbreviation

    Returns:
        Search string optimized for citation directory lookups
    """
    # Use standardized name if available, otherwise original
    search_name = standardized_name if standardized_name else name

    if not search_name:
        return ""

    search_name = search_name.strip()
    search_lower = search_name.lower()

    # Build location parts
    location_parts = []

    if city and city.lower() not in search_lower:
        location_parts.append(city)

    if state:
        state_upper = state.upper()
        # Check if state is already in name
        if state_upper not in search_name.upper():
            location_parts.append(state_upper)

    # Append location if we have any
    if location_parts:
        search_name = f"{search_name}, {', '.join(location_parts)}"

    return search_name


def needs_standardization(name: str) -> bool:
    """
    Check if a business name needs standardization.

    Args:
        name: Business name to check

    Returns:
        True if name should be standardized
    """
    if not name or not name.strip():
        return True

    score = score_name_quality(name)
    return score < 50 or len(name.strip()) < 10


# For testing
if __name__ == '__main__':
    # Test cases
    test_names = [
        "Hydro",
        "A+",
        "1",
        "Best Pressure Washing LLC",
        "Dallas Power Wash TX",
        "Clean Pro Services",
    ]

    print("Name Quality Scores:")
    print("-" * 50)
    for name in test_names:
        score = score_name_quality(name)
        needs = needs_standardization(name)
        print(f"  {name:30} -> Score: {score:3}, Needs standardization: {needs}")

    print("\nDomain Inference:")
    print("-" * 50)
    test_domains = [
        "hydrosoftwashne.com",
        "abcpressurewashing.com",
        "dallascleaning.com",
        "abc.com",
    ]
    for domain in test_domains:
        inferred = infer_name_from_domain(domain)
        print(f"  {domain:30} -> {inferred}")

    print("\nAddress Parsing:")
    print("-" * 50)
    test_addresses = [
        "123 Main St, Dallas, TX 75001",
        "456 Oak Ave, Los Angeles, CA",
        "Omaha NE",
        "New York, NY 10001",
    ]
    for addr in test_addresses:
        parsed = parse_location_from_address(addr)
        print(f"  {addr:35} -> {parsed}")

    print("\nStandardization:")
    print("-" * 50)
    std_name, source, conf = standardize_name(
        "Hydro",
        domain="hydrosoftwashne.com",
        city="Omaha",
        state="NE"
    )
    print(f"  'Hydro' + hydrosoftwashne.com + Omaha, NE")
    print(f"    -> {std_name} (source: {source}, confidence: {conf:.2f})")
