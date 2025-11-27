#!/usr/bin/env python3
"""
Website content parser for washdb-bot.

This module extracts structured business information from raw HTML:
- Company name
- Phone numbers
- Email addresses
- Services offered
- Service area
- Physical address
- Reviews/testimonials
"""

import json
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from runner.logging_setup import get_logger


# Initialize logger
logger = get_logger("site_parse")

# Phone regex patterns
PHONE_PATTERNS = [
    r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',  # 555-123-4567 or 555.123.4567
    r'\(\d{3}\)\s*\d{3}[-.\s]?\d{4}',  # (555) 123-4567
    r'\b1[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',  # 1-555-123-4567
]

# Email regex pattern
EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# Service-related keywords
SERVICE_KEYWORDS = [
    "services",
    "what we do",
    "our services",
    "pressure",
    "power wash",
    "window",
    "deck",
    "stain",
    "fence",
    "log home",
    "cleaning",
    "restoration",
]

# Service area keywords
SERVICE_AREA_KEYWORDS = [
    "service area",
    "areas we serve",
    "serving",
    "coverage",
    "locations",
    "we serve",
]

# Review/testimonial keywords
REVIEW_KEYWORDS = [
    "reviews",
    "testimonials",
    "what clients say",
    "customer reviews",
    "client testimonials",
    "feedback",
]


def extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    """
    Extract JSON-LD structured data from HTML.

    Args:
        soup: BeautifulSoup object

    Returns:
        List of parsed JSON-LD objects
    """
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    json_ld_data = []

    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            # Handle both single objects and arrays
            if isinstance(data, list):
                json_ld_data.extend(data)
            else:
                json_ld_data.append(data)
        except (json.JSONDecodeError, AttributeError) as e:
            logger.debug(f"Failed to parse JSON-LD: {e}")
            continue

    return json_ld_data


def extract_company_name(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """
    Extract company name from HTML.

    Tries in order:
    1. Schema.org JSON-LD "name" field
    2. <title> tag
    3. First <h1> tag
    4. Domain name as fallback

    Args:
        soup: BeautifulSoup object
        base_url: Base URL of the site

    Returns:
        Company name or None
    """
    # Try JSON-LD first
    json_ld_data = extract_json_ld(soup)
    for item in json_ld_data:
        if item.get("@type") in ["LocalBusiness", "Organization", "Corporation"]:
            if item.get("name"):
                logger.debug(f"Found company name in JSON-LD: {item['name']}")
                return item["name"].strip()

    # Try title tag
    title = soup.find("title")
    if title and title.string:
        # Clean up title (remove common suffixes)
        title_text = title.string.strip()
        title_text = re.sub(r'\s*[|-]\s*(Home|Welcome).*$', '', title_text, flags=re.IGNORECASE)
        if title_text:
            logger.debug(f"Found company name in title: {title_text}")
            return title_text

    # Try first h1
    h1 = soup.find("h1")
    if h1:
        h1_text = h1.get_text(strip=True)
        if h1_text and len(h1_text) < 100:  # Reasonable length for company name
            logger.debug(f"Found company name in h1: {h1_text}")
            return h1_text

    # Fallback to domain name
    parsed = urlparse(base_url)
    domain = parsed.netloc.replace("www.", "")
    logger.debug(f"Using domain as company name: {domain}")
    return domain


def extract_phones(soup: BeautifulSoup) -> list[str]:
    """
    Extract phone numbers from HTML.

    Checks:
    1. tel: links
    2. Text content matching phone patterns

    Args:
        soup: BeautifulSoup object

    Returns:
        List of unique phone numbers
    """
    phones = set()

    # Extract from tel: links
    tel_links = soup.find_all("a", href=re.compile(r'^tel:'))
    for link in tel_links:
        href = link.get("href", "")
        # Clean tel: prefix and extract number
        phone = re.sub(r'^tel:', '', href)
        phone = re.sub(r'[^\d\-\.\s\(\)ext]', '', phone, flags=re.IGNORECASE)
        if phone.strip():
            phones.add(phone.strip())

    # Extract from text content
    text = soup.get_text()
    for pattern in PHONE_PATTERNS:
        matches = re.findall(pattern, text)
        phones.update(matches)

    # Clean and deduplicate
    cleaned_phones = []
    for phone in phones:
        # Remove extra spaces, ensure consistent format
        cleaned = re.sub(r'\s+', ' ', phone.strip())
        if cleaned and len(re.sub(r'[^\d]', '', cleaned)) >= 10:
            cleaned_phones.append(cleaned)

    logger.debug(f"Found {len(cleaned_phones)} phone numbers")
    return list(set(cleaned_phones))  # Deduplicate


def extract_emails(soup: BeautifulSoup, base_url: str) -> list[str]:
    """
    Extract email addresses from HTML.

    Checks:
    1. mailto: links
    2. Text content matching email pattern

    Prefers emails matching the business domain.

    Args:
        soup: BeautifulSoup object
        base_url: Base URL to prefer matching domain emails

    Returns:
        List of unique email addresses
    """
    emails = set()

    # Extract from mailto: links
    mailto_links = soup.find_all("a", href=re.compile(r'^mailto:'))
    for link in mailto_links:
        href = link.get("href", "")
        # Clean mailto: prefix
        email = re.sub(r'^mailto:', '', href)
        # Remove query parameters
        email = email.split("?")[0]
        email = email.strip().lower()
        if email and "@" in email:
            emails.add(email)

    # Extract from text content
    text = soup.get_text()
    matches = re.findall(EMAIL_PATTERN, text, re.IGNORECASE)
    for match in matches:
        email = match.strip().lower()
        # Filter out common false positives
        if not email.endswith((".png", ".jpg", ".gif", ".svg")):
            emails.add(email)

    # Sort by domain preference (business domain first)
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.replace("www.", "")

    email_list = list(emails)

    # Sort: business domain emails first
    def email_sort_key(email):
        if base_domain in email:
            return (0, email)  # Business domain
        return (1, email)  # Other domains

    email_list.sort(key=email_sort_key)

    logger.debug(f"Found {len(email_list)} email addresses")
    return email_list


def extract_services(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract services offered from HTML.

    Looks for sections with service-related keywords and extracts:
    - Bullet lists (<ul><li>)
    - Headings and short phrases

    Args:
        soup: BeautifulSoup object

    Returns:
        Comma-separated string of services or None
    """
    services = []

    # Find sections with service keywords
    for keyword in SERVICE_KEYWORDS:
        # Find headings containing keyword
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        for heading in headings:
            heading_text = heading.get_text(strip=True).lower()
            if keyword.lower() in heading_text:
                # Look for lists or paragraphs near this heading
                next_sibling = heading.find_next_sibling()

                # Collect up to 5 siblings or until next major heading
                for _ in range(5):
                    if not next_sibling:
                        break

                    if next_sibling.name in ["h1", "h2", "h3"]:
                        break  # Stop at next major heading

                    # Extract from lists
                    if next_sibling.name in ["ul", "ol"]:
                        items = next_sibling.find_all("li")
                        for item in items:
                            text = item.get_text(strip=True)
                            if text and len(text) < 100:  # Reasonable service name length
                                services.append(text)

                    # Extract from paragraphs (short ones)
                    elif next_sibling.name == "p":
                        text = next_sibling.get_text(strip=True)
                        if text and 10 < len(text) < 100:
                            services.append(text)

                    next_sibling = next_sibling.find_next_sibling()

    # Also search for lists with service-related keywords in items
    all_lists = soup.find_all(["ul", "ol"])
    for lst in all_lists:
        items = lst.find_all("li")
        for item in items:
            text = item.get_text(strip=True).lower()
            # Check if item contains service keywords
            if any(kw.lower() in text for kw in SERVICE_KEYWORDS):
                clean_text = item.get_text(strip=True)
                if clean_text and len(clean_text) < 100:
                    services.append(clean_text)

    # Deduplicate and clean
    services = list(set(services))

    if services:
        services_csv = ", ".join(services[:20])  # Limit to 20 services
        logger.debug(f"Found {len(services)} services")
        return services_csv

    return None


def extract_service_area(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract service area from HTML.

    Looks for sections with service area keywords.

    Args:
        soup: BeautifulSoup object

    Returns:
        Service area text or None
    """
    # Find sections with service area keywords
    for keyword in SERVICE_AREA_KEYWORDS:
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        for heading in headings:
            heading_text = heading.get_text(strip=True).lower()
            if keyword.lower() in heading_text:
                # Get next paragraph or list
                next_elem = heading.find_next_sibling()

                if next_elem:
                    if next_elem.name in ["ul", "ol"]:
                        items = next_elem.find_all("li")
                        locations = [item.get_text(strip=True) for item in items]
                        area_text = ", ".join(locations[:15])  # Limit to 15 locations
                        logger.debug(f"Found service area: {area_text[:100]}...")
                        return area_text
                    elif next_elem.name == "p":
                        area_text = next_elem.get_text(strip=True)
                        if area_text and len(area_text) < 500:
                            logger.debug(f"Found service area: {area_text[:100]}...")
                            return area_text

    return None


def extract_address(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract physical address from HTML.

    Tries:
    1. Schema.org PostalAddress in JSON-LD
    2. Common address patterns

    Args:
        soup: BeautifulSoup object

    Returns:
        Address string or None
    """
    # Try JSON-LD first
    json_ld_data = extract_json_ld(soup)
    for item in json_ld_data:
        if item.get("@type") in ["LocalBusiness", "Organization"]:
            address = item.get("address")
            if address:
                if isinstance(address, dict):
                    # Build address from components
                    parts = []
                    if address.get("streetAddress"):
                        parts.append(address["streetAddress"])
                    if address.get("addressLocality"):
                        parts.append(address["addressLocality"])
                    if address.get("addressRegion"):
                        parts.append(address["addressRegion"])
                    if address.get("postalCode"):
                        parts.append(address["postalCode"])

                    if parts:
                        addr_text = ", ".join(parts)
                        logger.debug(f"Found address in JSON-LD: {addr_text}")
                        return addr_text
                elif isinstance(address, str):
                    logger.debug(f"Found address in JSON-LD: {address}")
                    return address

    # Look for elements with address-related classes/attributes
    address_elem = soup.find(["address", "div"], class_=re.compile(r'address', re.IGNORECASE))
    if address_elem:
        addr_text = address_elem.get_text(strip=True)
        if addr_text and len(addr_text) < 300:
            logger.debug(f"Found address in HTML: {addr_text}")
            return addr_text

    return None


def extract_reviews(soup: BeautifulSoup) -> Optional[dict]:
    """
    Extract review/testimonial information from HTML.

    Args:
        soup: BeautifulSoup object

    Returns:
        Dict with 'count' and 'sample' or None
    """
    review_blocks = []

    # Find sections with review keywords
    for keyword in REVIEW_KEYWORDS:
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        for heading in headings:
            heading_text = heading.get_text(strip=True).lower()
            if keyword.lower() in heading_text:
                # Look for review blocks after heading
                parent = heading.parent
                if parent:
                    # Find all divs/sections in parent
                    blocks = parent.find_all(["div", "blockquote", "p"], limit=10)
                    for block in blocks:
                        text = block.get_text(strip=True)
                        # Reviews are typically 50-500 characters
                        if 50 < len(text) < 500:
                            review_blocks.append(text)

    if review_blocks:
        logger.debug(f"Found {len(review_blocks)} review blocks")
        return {
            "count": len(review_blocks),
            "sample": review_blocks[0] if review_blocks else None,
        }

    return None


def extract_about_text(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract 'About Us' or general description text from the page.

    Args:
        soup: BeautifulSoup object

    Returns:
        About text or None
    """
    about_sections = []

    # Look for sections with 'about' in class or id
    for elem in soup.find_all(['section', 'div', 'article'], class_=lambda x: x and 'about' in x.lower()):
        about_sections.append(elem.get_text(separator=' ', strip=True))

    for elem in soup.find_all(['section', 'div', 'article'], id=lambda x: x and 'about' in x.lower()):
        about_sections.append(elem.get_text(separator=' ', strip=True))

    # Look for headings containing 'about' and get following content
    for heading in soup.find_all(['h1', 'h2', 'h3'], string=re.compile(r'about', re.IGNORECASE)):
        parent = heading.find_parent(['section', 'div', 'article'])
        if parent:
            about_sections.append(parent.get_text(separator=' ', strip=True))

    # Return combined text, limited to reasonable length
    combined = ' '.join(about_sections)
    return combined[:5000] if combined else None


def extract_homepage_text(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract main body text from the homepage.

    Args:
        soup: BeautifulSoup object

    Returns:
        Homepage body text or None
    """
    # Remove script, style, and navigation elements
    for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
        element.decompose()

    # Get text from main content areas
    main_text = []

    # Try to find main content area
    main_content = soup.find(['main', 'article', 'div'], class_=lambda x: x and any(
        keyword in x.lower() for keyword in ['content', 'main', 'body']
    ))

    if main_content:
        main_text.append(main_content.get_text(separator=' ', strip=True))
    else:
        # Fall back to body text
        body = soup.find('body')
        if body:
            main_text.append(body.get_text(separator=' ', strip=True))

    # Return combined text, limited to reasonable length
    combined = ' '.join(main_text)
    return combined[:10000] if combined else None


def extract_content_metrics(soup: BeautifulSoup) -> dict:
    """
    Extract comprehensive content depth metrics from HTML.

    Analyzes content for:
    - Word count and unique words
    - Content depth classification
    - Paragraph statistics
    - Header structure and hierarchy validation

    Args:
        soup: BeautifulSoup object (should be a copy to avoid mutation)

    Returns:
        Dict with content metrics:
        - word_count: Total words in main content
        - unique_words: Count of unique words
        - content_depth: thin/moderate/comprehensive/in-depth
        - paragraph_count: Number of paragraphs
        - avg_paragraph_length: Average words per paragraph
        - header_structure: H1/H2/H3 counts and hierarchy validation
    """
    # Work on a copy to avoid mutating original soup
    from copy import copy
    soup_copy = copy(soup)

    # Remove non-content elements
    for element in soup_copy(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript']):
        element.decompose()

    # Extract all text
    body = soup_copy.find('body')
    if not body:
        body = soup_copy

    # Get all paragraphs for detailed analysis
    paragraphs = body.find_all('p')
    paragraph_texts = []
    for p in paragraphs:
        text = p.get_text(strip=True)
        if text and len(text) > 20:  # Filter out very short paragraphs
            paragraph_texts.append(text)

    # Get full body text for word analysis
    full_text = body.get_text(separator=' ', strip=True)

    # Tokenize words (simple split, filter out short tokens)
    words = [w.lower() for w in re.split(r'\s+', full_text) if len(w) > 2 and w.isalpha()]
    word_count = len(words)
    unique_words = len(set(words))

    # Calculate paragraph stats
    paragraph_count = len(paragraph_texts)
    paragraph_word_counts = [len(p.split()) for p in paragraph_texts]
    avg_paragraph_length = (
        sum(paragraph_word_counts) / len(paragraph_word_counts)
        if paragraph_word_counts else 0
    )

    # Classify content depth based on word count
    if word_count < 300:
        content_depth = "thin"
    elif word_count < 800:
        content_depth = "moderate"
    elif word_count < 1500:
        content_depth = "comprehensive"
    else:
        content_depth = "in-depth"

    # Analyze header structure
    h1_tags = soup_copy.find_all('h1')
    h2_tags = soup_copy.find_all('h2')
    h3_tags = soup_copy.find_all('h3')
    h4_tags = soup_copy.find_all('h4')

    h1_count = len(h1_tags)
    h2_count = len(h2_tags)
    h3_count = len(h3_tags)
    h4_count = len(h4_tags)

    # Validate hierarchy
    hierarchy_issues = []
    hierarchy_valid = True

    # Check for exactly one H1
    if h1_count == 0:
        hierarchy_issues.append("Missing H1 tag")
        hierarchy_valid = False
    elif h1_count > 1:
        hierarchy_issues.append(f"Multiple H1 tags ({h1_count})")
        hierarchy_valid = False

    # Check for H2s if content is substantial
    if word_count > 500 and h2_count == 0:
        hierarchy_issues.append("No H2 tags for long content")
        hierarchy_valid = False

    # Check for skipped heading levels (H1 -> H3 without H2)
    if h3_count > 0 and h2_count == 0:
        hierarchy_issues.append("H3 used without H2 (skipped level)")
        hierarchy_valid = False

    if h4_count > 0 and h3_count == 0:
        hierarchy_issues.append("H4 used without H3 (skipped level)")
        hierarchy_valid = False

    metrics = {
        "word_count": word_count,
        "unique_words": unique_words,
        "content_depth": content_depth,
        "paragraph_count": paragraph_count,
        "avg_paragraph_length": round(avg_paragraph_length, 1),
        "header_structure": {
            "h1_count": h1_count,
            "h2_count": h2_count,
            "h3_count": h3_count,
            "h4_count": h4_count,
            "hierarchy_valid": hierarchy_valid,
            "issues": hierarchy_issues,
        }
    }

    logger.debug(
        f"Content metrics: {word_count} words, {content_depth} depth, "
        f"H1:{h1_count} H2:{h2_count} H3:{h3_count}"
    )

    return metrics


def parse_site_content(html: str, base_url: str) -> dict:
    """
    Parse website HTML and extract business information.

    Args:
        html: Raw HTML content
        base_url: Base URL of the website

    Returns:
        Dict with extracted fields:
        - name: Company name
        - phones: List of phone numbers
        - emails: List of email addresses
        - services: Comma-separated services
        - service_area: Service area text
        - address: Physical address
        - reviews: Review information dict
        - about: About us text
        - homepage_text: Main homepage body text
        - content_metrics: Content depth analysis (word count, headers, etc.)
    """
    logger.info(f"Parsing site content for {base_url}")

    soup = BeautifulSoup(html, "lxml")

    # Extract content metrics first (before any soup mutations)
    content_metrics = extract_content_metrics(soup)

    result = {
        "name": extract_company_name(soup, base_url),
        "phones": extract_phones(soup),
        "emails": extract_emails(soup, base_url),
        "services": extract_services(soup),
        "service_area": extract_service_area(soup),
        "address": extract_address(soup),
        "reviews": extract_reviews(soup),
        "about": extract_about_text(soup),
        "homepage_text": extract_homepage_text(soup),
        "content_metrics": content_metrics,
    }

    # Log summary
    logger.info(f"Extraction complete:")
    logger.info(f"  Name: {result['name']}")
    logger.info(f"  Phones: {len(result['phones'])} found")
    logger.info(f"  Emails: {len(result['emails'])} found")
    logger.info(f"  Services: {'Yes' if result['services'] else 'No'}")
    logger.info(f"  Service Area: {'Yes' if result['service_area'] else 'No'}")
    logger.info(f"  Address: {'Yes' if result['address'] else 'No'}")
    logger.info(f"  Reviews: {result['reviews']['count'] if result['reviews'] else 0}")

    return result


def main():
    """Demo: Parse sample HTML."""
    logger.info("=" * 60)
    logger.info("Site Parser Demo")
    logger.info("=" * 60)
    logger.info("")

    # Sample HTML
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ABC Pressure Washing - Professional Cleaning Services</title>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": "ABC Pressure Washing",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "123 Main Street",
                "addressLocality": "Austin",
                "addressRegion": "TX",
                "postalCode": "78701"
            }
        }
        </script>
    </head>
    <body>
        <h1>ABC Pressure Washing</h1>

        <h2>Contact Us</h2>
        <p>Phone: <a href="tel:555-123-4567">(555) 123-4567</a></p>
        <p>Email: <a href="mailto:info@abcwashing.com">info@abcwashing.com</a></p>

        <h2>Our Services</h2>
        <ul>
            <li>Residential Pressure Washing</li>
            <li>Commercial Power Washing</li>
            <li>Deck Cleaning & Restoration</li>
            <li>Window Cleaning</li>
            <li>Fence Staining</li>
        </ul>

        <h2>Service Area</h2>
        <p>We proudly serve Austin, Round Rock, Cedar Park, and surrounding areas.</p>

        <h2>What Our Clients Say</h2>
        <blockquote>
            "Excellent service! My deck looks brand new. Highly recommend ABC Pressure Washing!"
        </blockquote>
        <blockquote>
            "Professional and thorough. They did an amazing job on our home's exterior."
        </blockquote>
    </body>
    </html>
    """

    base_url = "https://abcwashing.com"

    logger.info("Parsing sample HTML...")
    logger.info("")

    result = parse_site_content(sample_html, base_url)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Parsed Results:")
    logger.info("=" * 60)
    logger.info(f"Name: {result['name']}")
    logger.info(f"Phones: {result['phones']}")
    logger.info(f"Emails: {result['emails']}")
    logger.info(f"Services: {result['services']}")
    logger.info(f"Service Area: {result['service_area']}")
    logger.info(f"Address: {result['address']}")
    if result['reviews']:
        logger.info(f"Reviews: {result['reviews']['count']} found")
        logger.info(f"Sample Review: {result['reviews']['sample'][:100]}...")


if __name__ == "__main__":
    main()
