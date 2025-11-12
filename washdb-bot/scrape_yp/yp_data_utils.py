#!/usr/bin/env python3
"""
Data normalization and validation utilities for Yellow Pages scraping.

This module provides utilities for:
- Phone number normalization and validation
- URL validation and cleaning
- Address normalization
- Email extraction and validation
"""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse


def normalize_phone(phone: str) -> Optional[str]:
    """
    Normalize a phone number to E.164 format (US numbers).

    Handles various input formats:
    - (555) 123-4567
    - 555-123-4567
    - 555.123.4567
    - 5551234567
    - +1 555 123 4567
    - 1-555-123-4567

    Args:
        phone: Raw phone number string

    Returns:
        Normalized phone in format: +1-555-123-4567
        Returns None if invalid
    """
    if not phone:
        return None

    # Remove all non-digit characters except + at start
    digits = re.sub(r'[^\d+]', '', phone)

    # Remove + prefix for processing
    if digits.startswith('+'):
        digits = digits[1:]

    # Remove leading 1 (US country code) if present
    if digits.startswith('1') and len(digits) == 11:
        digits = digits[1:]

    # Must be exactly 10 digits for valid US number
    if len(digits) != 10:
        return None

    # Validate area code (first 3 digits)
    area_code = digits[0:3]
    # Area code can't start with 0 or 1
    if area_code[0] in ('0', '1'):
        return None

    # Format as +1-XXX-XXX-XXXX
    formatted = f"+1-{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"

    return formatted


def validate_phone(phone: str) -> bool:
    """
    Validate if a phone number is valid (US numbers only).

    Args:
        phone: Phone number string

    Returns:
        True if valid, False otherwise
    """
    normalized = normalize_phone(phone)
    return normalized is not None


def extract_phone_from_text(text: str) -> Optional[str]:
    """
    Extract the first phone number from a text string.

    Args:
        text: Text that may contain a phone number

    Returns:
        Normalized phone number or None
    """
    if not text:
        return None

    # Common phone number patterns
    patterns = [
        r'\+?1?\s*\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}',  # (555) 123-4567, 555-123-4567
        r'\d{3}[\s.-]\d{3}[\s.-]\d{4}',  # 555.123.4567
        r'\d{10}',  # 5551234567
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            phone = match.group(0)
            normalized = normalize_phone(phone)
            if normalized:
                return normalized

    return None


def validate_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate and clean a URL.

    Args:
        url: URL string to validate

    Returns:
        Tuple of (is_valid, cleaned_url)
        - is_valid: True if URL is valid
        - cleaned_url: Cleaned URL or None if invalid
    """
    if not url:
        return False, None

    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        parsed = urlparse(url)

        # Must have scheme and netloc
        if not parsed.scheme or not parsed.netloc:
            return False, None

        # Scheme must be http or https
        if parsed.scheme not in ('http', 'https'):
            return False, None

        # Netloc must have at least one dot (domain.tld)
        if '.' not in parsed.netloc:
            return False, None

        # Rebuild URL (normalizes it)
        cleaned = urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),  # Lowercase domain
            parsed.path,
            parsed.params,
            parsed.query,
            ''  # Remove fragment
        ))

        return True, cleaned

    except Exception:
        return False, None


def is_valid_website_url(url: str) -> bool:
    """
    Check if a URL is a valid website URL (not YP internal, social media, etc.).

    Args:
        url: URL to check

    Returns:
        True if valid website URL
    """
    if not url:
        return False

    is_valid, cleaned = validate_url(url)
    if not is_valid:
        return False

    url_lower = cleaned.lower()

    # Reject YP internal links
    if 'yellowpages.com' in url_lower:
        return False

    # Reject common non-website domains
    non_website_domains = [
        'facebook.com',
        'twitter.com',
        'instagram.com',
        'linkedin.com',
        'youtube.com',
        'yelp.com',
        'google.com',
        'apple.com/maps',
        'mapquest.com',
    ]

    for domain in non_website_domains:
        if domain in url_lower:
            return False

    return True


def extract_email_from_text(text: str) -> Optional[str]:
    """
    Extract the first email address from a text string.

    Args:
        text: Text that may contain an email

    Returns:
        Email address or None
    """
    if not text:
        return None

    # Simple email pattern
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    match = re.search(email_pattern, text)

    if match:
        email = match.group(0).lower()
        # Validate email format
        if validate_email(email):
            return email

    return None


def validate_email(email: str) -> bool:
    """
    Validate an email address format.

    Args:
        email: Email address to validate

    Returns:
        True if valid format
    """
    if not email:
        return False

    # RFC 5322 simplified pattern
    pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'
    return re.match(pattern, email) is not None


def normalize_address(address: str) -> Optional[str]:
    """
    Normalize a US address string.

    Performs basic normalization:
    - Standardize abbreviations (St -> Street, Ave -> Avenue)
    - Remove extra whitespace
    - Capitalize properly

    Args:
        address: Raw address string

    Returns:
        Normalized address or None
    """
    if not address:
        return None

    # Remove extra whitespace
    address = re.sub(r'\s+', ' ', address.strip())

    # Common street type abbreviations
    replacements = {
        r'\bSt\b': 'Street',
        r'\bAve\b': 'Avenue',
        r'\bBlvd\b': 'Boulevard',
        r'\bRd\b': 'Road',
        r'\bDr\b': 'Drive',
        r'\bLn\b': 'Lane',
        r'\bCt\b': 'Court',
        r'\bPl\b': 'Place',
        r'\bPkwy\b': 'Parkway',
        r'\bCir\b': 'Circle',
    }

    for abbrev, full in replacements.items():
        address = re.sub(abbrev, full, address, flags=re.IGNORECASE)

    # Capitalize words (simple title case)
    address = address.title()

    return address


def clean_business_name(name: str) -> Optional[str]:
    """
    Clean and normalize a business name.

    Args:
        name: Raw business name

    Returns:
        Cleaned business name or None
    """
    if not name:
        return None

    # Remove extra whitespace
    name = re.sub(r'\s+', ' ', name.strip())

    # Remove common suffixes if they're the entire name (data quality issue)
    if name.lower() in ('inc', 'llc', 'ltd', 'corp', 'company'):
        return None

    # Must have at least 2 characters
    if len(name) < 2:
        return None

    return name


def extract_zip_code(text: str) -> Optional[str]:
    """
    Extract ZIP code from text (US ZIP or ZIP+4).

    Args:
        text: Text that may contain a ZIP code

    Returns:
        ZIP code string or None
    """
    if not text:
        return None

    # Match 5-digit ZIP or ZIP+4 (12345 or 12345-6789)
    pattern = r'\b\d{5}(?:-\d{4})?\b'
    match = re.search(pattern, text)

    if match:
        return match.group(0)

    return None


def parse_city_state_zip(location: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse city, state, and ZIP from a location string.

    Expected formats:
    - "Providence, RI 02903"
    - "Providence RI 02903"
    - "Providence, Rhode Island 02903"

    Args:
        location: Location string

    Returns:
        Tuple of (city, state, zip_code)
    """
    if not location:
        return None, None, None

    city = None
    state = None
    zip_code = None

    # Extract ZIP code first
    zip_code = extract_zip_code(location)
    if zip_code:
        # Remove ZIP from string
        location = location.replace(zip_code, '').strip()

    # Split by comma or multiple spaces
    parts = re.split(r',|\s{2,}', location)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) >= 2:
        city = parts[0]
        state = parts[1]
    elif len(parts) == 1:
        # Try to split last word as state
        words = parts[0].split()
        if len(words) >= 2:
            city = ' '.join(words[:-1])
            state = words[-1]

    return city, state, zip_code
