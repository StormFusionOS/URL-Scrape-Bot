#!/usr/bin/env python3
"""
Browser Content Extractor - Comprehensive content extraction from browser-rendered pages.

This module extracts all content needed for both verification AND standardization
in a single browser session, maximizing the data available to the LLM.

Extracts:
- JSON-LD structured data (most reliable for business info)
- OG meta tags (social metadata)
- Title, H1, meta description
- Services text (up to 4000 chars)
- About text (up to 4000 chars)
- Homepage text (up to 8000 chars)
- Contact info (phones, emails, address)
- Footer copyright (for name signals)
- Content metrics (word count, depth)
"""

import json
import re
import logging
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Content limits (increased from original)
SERVICES_TEXT_LIMIT = 4000
ABOUT_TEXT_LIMIT = 4000
HOMEPAGE_TEXT_LIMIT = 8000
BODY_TEXT_LIMIT = 2000

# Phone regex patterns
PHONE_PATTERNS = [
    r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',
    r'\(\d{3}\)\s*\d{3}[-.\s]?\d{4}',
    r'\b1[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',
]

# Email regex pattern
EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# Service-related keywords
SERVICE_KEYWORDS = [
    "services", "what we do", "our services", "pressure", "power wash",
    "window", "deck", "stain", "fence", "cleaning", "restoration",
    "gutter", "roof", "solar", "soft wash", "fleet",
]


@dataclass
class BrowserExtractedContent:
    """All content extracted from a browser-rendered page."""

    # Extraction status
    success: bool
    error: Optional[str] = None
    url: str = ""
    final_url: str = ""

    # Name signals (for standardization)
    title: Optional[str] = None
    h1_text: Optional[str] = None
    json_ld: List[Dict] = field(default_factory=list)
    og_site_name: Optional[str] = None
    og_title: Optional[str] = None
    meta_description: Optional[str] = None
    copyright_text: Optional[str] = None

    # Service signals (for verification)
    services_text: Optional[str] = None
    about_text: Optional[str] = None
    homepage_text: Optional[str] = None
    body_text: Optional[str] = None

    # Contact info
    phones: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    address: Optional[str] = None

    # Content metrics
    word_count: int = 0
    unique_words: int = 0
    content_depth: str = "unknown"
    paragraph_count: int = 0
    header_structure: Dict = field(default_factory=dict)

    # Extraction metadata
    extraction_time: datetime = field(default_factory=datetime.utcnow)
    browser_type: str = "unknown"
    js_rendered: bool = True
    detected_block: bool = False
    block_reason: Optional[str] = None


def extract_browser_content(
    driver: Any,
    url: str,
    browser_type: str = "selenium_uc"
) -> BrowserExtractedContent:
    """
    Extract comprehensive content from a browser-rendered page.

    Args:
        driver: Selenium WebDriver instance
        url: Original URL being processed

    Returns:
        BrowserExtractedContent with all extracted data
    """
    try:
        # Get page source and current URL
        html = driver.page_source
        final_url = driver.current_url

        # Parse with BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')

        # Extract all components
        json_ld = _extract_json_ld(soup)
        og_site_name, og_title = _extract_og_tags(soup)
        meta_description = _extract_meta_description(soup)
        title = _extract_title(soup)
        h1_text = _extract_h1(soup)
        copyright_text = _extract_copyright(soup)

        # Service/verification content
        services_text = _extract_services_text(soup, limit=SERVICES_TEXT_LIMIT)
        about_text = _extract_about_text(soup, limit=ABOUT_TEXT_LIMIT)
        homepage_text = _extract_homepage_text(soup, limit=HOMEPAGE_TEXT_LIMIT)
        body_text = _extract_body_text(driver, limit=BODY_TEXT_LIMIT)

        # Contact info
        phones = _extract_phones(soup)
        emails = _extract_emails(soup, url)
        address = _extract_address(soup, json_ld)

        # Content metrics
        metrics = _extract_content_metrics(soup)

        return BrowserExtractedContent(
            success=True,
            url=url,
            final_url=final_url,
            title=title,
            h1_text=h1_text,
            json_ld=json_ld,
            og_site_name=og_site_name,
            og_title=og_title,
            meta_description=meta_description,
            copyright_text=copyright_text,
            services_text=services_text,
            about_text=about_text,
            homepage_text=homepage_text,
            body_text=body_text,
            phones=phones,
            emails=emails,
            address=address,
            word_count=metrics.get('word_count', 0),
            unique_words=metrics.get('unique_words', 0),
            content_depth=metrics.get('content_depth', 'unknown'),
            paragraph_count=metrics.get('paragraph_count', 0),
            header_structure=metrics.get('header_structure', {}),
            browser_type=browser_type,
            js_rendered=True,
        )

    except Exception as e:
        logger.error(f"Content extraction failed for {url}: {e}")
        return BrowserExtractedContent(
            success=False,
            error=str(e),
            url=url,
        )


def _extract_json_ld(soup: BeautifulSoup) -> List[Dict]:
    """Extract JSON-LD structured data."""
    json_ld_data = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            content = script.string
            if not content:
                continue

            data = json.loads(content)

            # Handle arrays
            if isinstance(data, list):
                for item in data:
                    if _is_relevant_json_ld(item):
                        json_ld_data.append(item)
            elif isinstance(data, dict):
                # Handle @graph structure
                if '@graph' in data:
                    for item in data['@graph']:
                        if _is_relevant_json_ld(item):
                            json_ld_data.append(item)
                elif _is_relevant_json_ld(data):
                    json_ld_data.append(data)

        except (json.JSONDecodeError, AttributeError):
            continue

    return json_ld_data


def _is_relevant_json_ld(item: Dict) -> bool:
    """Check if JSON-LD item is relevant for business extraction."""
    if not isinstance(item, dict):
        return False
    item_type = item.get('@type', '')
    relevant_types = [
        'LocalBusiness', 'Organization', 'Corporation', 'WebSite',
        'ProfessionalService', 'HomeAndConstructionBusiness',
        'CleaningService', 'Service',
    ]
    return any(t in str(item_type) for t in relevant_types)


def _extract_og_tags(soup: BeautifulSoup) -> tuple:
    """Extract Open Graph meta tags."""
    og_site_name = None
    og_title = None

    site_name_tag = soup.find('meta', property='og:site_name')
    if site_name_tag:
        og_site_name = site_name_tag.get('content', '').strip()

    title_tag = soup.find('meta', property='og:title')
    if title_tag:
        og_title = title_tag.get('content', '').strip()

    return og_site_name, og_title


def _extract_meta_description(soup: BeautifulSoup) -> Optional[str]:
    """Extract meta description."""
    meta = soup.find('meta', attrs={'name': 'description'})
    if meta:
        return meta.get('content', '').strip()
    return None


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    """Extract page title."""
    title_tag = soup.find('title')
    if title_tag and title_tag.string:
        return title_tag.string.strip()
    return None


def _extract_h1(soup: BeautifulSoup) -> Optional[str]:
    """Extract first H1 heading."""
    h1 = soup.find('h1')
    if h1:
        text = h1.get_text(strip=True)
        if text and len(text) < 200:
            return text
    return None


def _extract_copyright(soup: BeautifulSoup) -> Optional[str]:
    """Extract copyright text from footer (often contains business name)."""
    # Look in footer
    footer = soup.find('footer')
    if footer:
        text = footer.get_text(separator=' ', strip=True)
        # Look for copyright pattern
        copyright_match = re.search(
            r'(?:©|\(c\)|copyright)\s*(?:\d{4}[–-]\d{4}|\d{4})?\s*([^.|,]{5,50})',
            text,
            re.IGNORECASE
        )
        if copyright_match:
            return copyright_match.group(1).strip()

    # Look for copyright class/id
    for elem in soup.find_all(['div', 'span', 'p'], class_=re.compile(r'copyright', re.I)):
        text = elem.get_text(strip=True)
        if text and 10 < len(text) < 200:
            return text

    return None


def _extract_services_text(soup: BeautifulSoup, limit: int = 4000) -> Optional[str]:
    """Extract services-related text content."""
    services_parts = []

    # Find sections with service keywords in headings
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
        heading_text = heading.get_text(strip=True).lower()
        if any(kw in heading_text for kw in SERVICE_KEYWORDS):
            # Get heading + following content
            section_text = heading.get_text(strip=True)

            # Get siblings
            for sibling in heading.find_next_siblings()[:5]:
                if sibling.name in ['h1', 'h2']:
                    break
                section_text += ' ' + sibling.get_text(separator=' ', strip=True)

            if section_text:
                services_parts.append(section_text)

    # Also check for service-related sections by class/id
    for elem in soup.find_all(['section', 'div'], class_=re.compile(r'service', re.I)):
        text = elem.get_text(separator=' ', strip=True)
        if text and len(text) > 50:
            services_parts.append(text[:1000])

    combined = ' '.join(services_parts)
    return combined[:limit] if combined else None


def _extract_about_text(soup: BeautifulSoup, limit: int = 4000) -> Optional[str]:
    """Extract about/company description text."""
    about_parts = []

    # Look for about sections by class/id
    for elem in soup.find_all(['section', 'div', 'article'], class_=re.compile(r'about', re.I)):
        about_parts.append(elem.get_text(separator=' ', strip=True))

    for elem in soup.find_all(['section', 'div', 'article'], id=re.compile(r'about', re.I)):
        about_parts.append(elem.get_text(separator=' ', strip=True))

    # Look for headings containing 'about'
    for heading in soup.find_all(['h1', 'h2', 'h3'], string=re.compile(r'about', re.I)):
        parent = heading.find_parent(['section', 'div', 'article'])
        if parent:
            about_parts.append(parent.get_text(separator=' ', strip=True))

    combined = ' '.join(about_parts)
    return combined[:limit] if combined else None


def _extract_homepage_text(soup: BeautifulSoup, limit: int = 8000) -> Optional[str]:
    """Extract main homepage body text."""
    # Work on a copy to avoid mutating
    soup_copy = copy(soup)

    # Remove non-content elements
    for element in soup_copy(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript']):
        element.decompose()

    # Try to find main content area
    main_content = soup_copy.find(['main', 'article'])
    if not main_content:
        main_content = soup_copy.find('div', class_=re.compile(r'content|main|body', re.I))
    if not main_content:
        main_content = soup_copy.find('body')

    if main_content:
        text = main_content.get_text(separator=' ', strip=True)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        return text[:limit] if text else None

    return None


def _extract_body_text(driver: Any, limit: int = 2000) -> Optional[str]:
    """Extract body text using Selenium's text property (rendered text only)."""
    try:
        body = driver.find_element("tag name", "body")
        text = body.text[:limit] if body.text else None
        return text
    except Exception:
        return None


def _extract_phones(soup: BeautifulSoup) -> List[str]:
    """Extract phone numbers."""
    phones = set()

    # From tel: links
    for link in soup.find_all('a', href=re.compile(r'^tel:')):
        href = link.get('href', '')
        phone = re.sub(r'^tel:', '', href)
        phone = re.sub(r'[^\d\-\.\s\(\)ext]', '', phone, flags=re.I)
        if phone.strip():
            phones.add(phone.strip())

    # From text content
    text = soup.get_text()
    for pattern in PHONE_PATTERNS:
        matches = re.findall(pattern, text)
        phones.update(matches)

    # Clean and validate
    cleaned = []
    for phone in phones:
        cleaned_phone = re.sub(r'\s+', ' ', phone.strip())
        if cleaned_phone and len(re.sub(r'[^\d]', '', cleaned_phone)) >= 10:
            cleaned.append(cleaned_phone)

    return list(set(cleaned))[:5]  # Limit to 5 phones


def _extract_emails(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Extract email addresses."""
    emails = set()

    # From mailto: links
    for link in soup.find_all('a', href=re.compile(r'^mailto:')):
        href = link.get('href', '')
        email = re.sub(r'^mailto:', '', href).split('?')[0].strip().lower()
        if email and '@' in email:
            emails.add(email)

    # From text
    text = soup.get_text()
    for match in re.findall(EMAIL_PATTERN, text, re.I):
        email = match.strip().lower()
        if not email.endswith(('.png', '.jpg', '.gif', '.svg')):
            emails.add(email)

    # Sort by domain preference
    base_domain = urlparse(base_url).netloc.replace('www.', '')
    email_list = sorted(
        emails,
        key=lambda e: (0 if base_domain in e else 1, e)
    )

    return email_list[:5]  # Limit to 5 emails


def _extract_address(soup: BeautifulSoup, json_ld: List[Dict]) -> Optional[str]:
    """Extract physical address."""
    # Try JSON-LD first
    for item in json_ld:
        address = item.get('address')
        if address:
            if isinstance(address, dict):
                parts = []
                for key in ['streetAddress', 'addressLocality', 'addressRegion', 'postalCode']:
                    if address.get(key):
                        parts.append(address[key])
                if parts:
                    return ', '.join(parts)
            elif isinstance(address, str):
                return address

    # Look for address elements
    addr_elem = soup.find(['address', 'div'], class_=re.compile(r'address', re.I))
    if addr_elem:
        text = addr_elem.get_text(strip=True)
        if text and len(text) < 300:
            return text

    return None


def _extract_content_metrics(soup: BeautifulSoup) -> Dict:
    """Extract content depth metrics."""
    soup_copy = copy(soup)

    # Remove non-content
    for element in soup_copy(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript']):
        element.decompose()

    body = soup_copy.find('body') or soup_copy

    # Get paragraphs
    paragraphs = body.find_all('p')
    paragraph_texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]

    # Word analysis
    full_text = body.get_text(separator=' ', strip=True)
    words = [w.lower() for w in re.split(r'\s+', full_text) if len(w) > 2 and w.isalpha()]
    word_count = len(words)
    unique_words = len(set(words))

    # Content depth classification
    if word_count < 300:
        content_depth = "thin"
    elif word_count < 800:
        content_depth = "moderate"
    elif word_count < 1500:
        content_depth = "comprehensive"
    else:
        content_depth = "in-depth"

    # Header structure
    header_structure = {
        'h1_count': len(soup_copy.find_all('h1')),
        'h2_count': len(soup_copy.find_all('h2')),
        'h3_count': len(soup_copy.find_all('h3')),
    }

    return {
        'word_count': word_count,
        'unique_words': unique_words,
        'content_depth': content_depth,
        'paragraph_count': len(paragraph_texts),
        'header_structure': header_structure,
    }


def get_json_ld_name(json_ld: List[Dict]) -> Optional[str]:
    """Get business name from JSON-LD data."""
    for item in json_ld:
        name = item.get('name')
        if name and isinstance(name, str) and len(name) > 2:
            return name.strip()
    return None


def get_json_ld_description(json_ld: List[Dict]) -> Optional[str]:
    """Get business description from JSON-LD data."""
    for item in json_ld:
        desc = item.get('description')
        if desc and isinstance(desc, str):
            return desc[:500].strip()
    return None


def get_json_ld_services(json_ld: List[Dict]) -> List[str]:
    """Get services from JSON-LD data."""
    services = []
    for item in json_ld:
        # Check serviceType
        svc_type = item.get('serviceType')
        if svc_type:
            if isinstance(svc_type, list):
                services.extend(svc_type)
            else:
                services.append(svc_type)

        # Check hasOfferCatalog
        catalog = item.get('hasOfferCatalog')
        if catalog and isinstance(catalog, dict):
            items = catalog.get('itemListElement', [])
            for svc_item in items:
                if isinstance(svc_item, dict):
                    name = svc_item.get('name')
                    if name:
                        services.append(name)

    return services[:10]
