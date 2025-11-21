"""
Competitor Page Parser Module

Extracts SEO-relevant content from competitor pages:
- Title and meta tags
- Heading structure (H1-H6)
- Schema.org markup
- Internal/external links
- Word count and content analysis
- Images and alt text

Per SCRAPING_NOTES.md:
- "Extract meta title, description, H1s"
- "Parse schema.org JSON-LD markup"
- "Count words for content depth analysis"
- "Analyze internal/external link structure"
"""

import re
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

from runner.logging_setup import get_logger

logger = get_logger("competitor_parser")


@dataclass
class PageMetrics:
    """Metrics extracted from a competitor page."""
    url: str
    title: str = ""
    meta_description: str = ""
    meta_keywords: str = ""
    canonical_url: str = ""

    # OpenGraph metadata
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_type: str = ""
    og_url: str = ""

    # Twitter Card metadata
    twitter_card: str = ""
    twitter_title: str = ""
    twitter_description: str = ""
    twitter_image: str = ""

    # Robots directives
    robots_meta: str = ""  # index, noindex, follow, nofollow, etc.
    x_robots_tag: str = ""  # From HTTP header if available

    # International & pagination
    hreflang_links: List[Dict[str, str]] = field(default_factory=list)  # [{"lang": "en", "url": "..."}]
    rel_prev: str = ""
    rel_next: str = ""

    # Headings
    h1_tags: List[str] = field(default_factory=list)
    h2_tags: List[str] = field(default_factory=list)
    h3_tags: List[str] = field(default_factory=list)

    # Content metrics
    word_count: int = 0
    content_sections: List[Dict[str, str]] = field(default_factory=list)  # Sections split by H2/H3

    # Link analysis
    internal_links: int = 0
    external_links: int = 0

    # Images
    images: int = 0
    images_with_alt: int = 0

    # Schema
    schema_types: List[str] = field(default_factory=list)
    schema_markup: List[Dict] = field(default_factory=list)
    schema_summary: Dict[str, Any] = field(default_factory=dict)  # Completeness scoring

    # Contact info
    has_contact_form: bool = False
    has_phone: bool = False
    has_email: bool = False
    social_links: List[str] = field(default_factory=list)

    # Page classification
    page_type: str = ""  # homepage, services, about, contact, blog, etc.

    # Extended metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class CompetitorParser:
    """
    Parser for extracting SEO metrics from competitor pages.

    Extracts:
    - Meta information (title, description, canonical)
    - Heading structure (H1-H6)
    - Schema.org structured data
    - Link analysis (internal vs external)
    - Content metrics (word count)
    - Contact information indicators
    """

    def __init__(self):
        """Initialize competitor parser."""
        # Phone number regex patterns
        self.phone_patterns = [
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # (555) 123-4567
            r'\d{3}[-.\s]\d{3}[-.\s]\d{4}',          # 555-123-4567
            r'\+1[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # +1-555-123-4567
        ]

        # Email regex pattern
        self.email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

        # Social media domains
        self.social_domains = [
            'facebook.com', 'instagram.com', 'twitter.com', 'x.com',
            'linkedin.com', 'youtube.com', 'tiktok.com', 'pinterest.com',
            'yelp.com', 'google.com/maps', 'maps.google.com'
        ]

        # Page type indicators
        self.page_type_patterns = {
            'homepage': [r'^/$', r'^/index', r'^/home'],
            'services': [r'/services?', r'/what-we-do', r'/offerings?'],
            'about': [r'/about', r'/who-we-are', r'/our-story', r'/team'],
            'contact': [r'/contact', r'/get-in-touch', r'/reach-us'],
            'blog': [r'/blog', r'/news', r'/articles?', r'/posts?'],
            'pricing': [r'/pricing', r'/prices?', r'/rates?', r'/cost'],
            'gallery': [r'/gallery', r'/portfolio', r'/work', r'/projects?'],
            'faq': [r'/faq', r'/frequently-asked', r'/questions?'],
            'testimonials': [r'/testimonials?', r'/reviews?', r'/feedback'],
        }

        logger.info("CompetitorParser initialized")

    def _extract_text(self, soup: BeautifulSoup, selector: str) -> str:
        """Safely extract text from selector."""
        elem = soup.select_one(selector)
        return elem.get_text(strip=True) if elem else ""

    def _extract_meta(self, soup: BeautifulSoup, name: str) -> str:
        """Extract meta tag content by name."""
        meta = soup.find('meta', attrs={'name': name})
        if meta:
            return meta.get('content', '')

        # Try property attribute (for og: tags)
        meta = soup.find('meta', attrs={'property': name})
        if meta:
            return meta.get('content', '')

        return ""

    def _extract_headings(self, soup: BeautifulSoup, tag: str) -> List[str]:
        """Extract all headings of a given tag."""
        headings = []
        for elem in soup.find_all(tag):
            text = elem.get_text(strip=True)
            if text:
                headings.append(text)
        return headings

    def _extract_schema(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract schema.org JSON-LD markup."""
        schemas = []

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                content = script.string
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        schemas.extend(data)
                    else:
                        schemas.append(data)
            except json.JSONDecodeError:
                logger.debug("Failed to parse JSON-LD schema")
                continue

        return schemas

    def _extract_schema_types(self, schemas: List[Dict]) -> List[str]:
        """Extract @type values from schemas."""
        types = set()

        def extract_type(obj):
            if isinstance(obj, dict):
                if '@type' in obj:
                    t = obj['@type']
                    if isinstance(t, list):
                        types.update(t)
                    else:
                        types.add(t)
                for v in obj.values():
                    extract_type(v)
            elif isinstance(obj, list):
                for item in obj:
                    extract_type(item)

        for schema in schemas:
            extract_type(schema)

        return list(types)

    def _count_words(self, soup: BeautifulSoup) -> int:
        """Count words in main content area."""
        # Remove script and style elements
        for elem in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            elem.decompose()

        # Get text
        text = soup.get_text(separator=' ', strip=True)

        # Count words
        words = re.findall(r'\b\w+\b', text)
        return len(words)

    def _analyze_links(self, soup: BeautifulSoup, base_url: str) -> Dict[str, Any]:
        """Analyze internal and external links."""
        base_domain = urlparse(base_url).netloc

        internal = 0
        external = 0
        social = []

        for link in soup.find_all('a', href=True):
            href = link.get('href', '')

            # Skip empty or anchor links
            if not href or href.startswith('#'):
                continue

            # Resolve relative URLs
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)

            # Categorize link
            if parsed.netloc == base_domain or not parsed.netloc:
                internal += 1
            else:
                external += 1

                # Check for social links
                for social_domain in self.social_domains:
                    if social_domain in parsed.netloc:
                        social.append(full_url)
                        break

        return {
            'internal': internal,
            'external': external,
            'social': list(set(social))  # Deduplicate
        }

    def _analyze_images(self, soup: BeautifulSoup) -> Dict[str, int]:
        """Analyze images and alt text."""
        images = soup.find_all('img')
        total = len(images)
        with_alt = sum(1 for img in images if img.get('alt', '').strip())

        return {
            'total': total,
            'with_alt': with_alt
        }

    def _detect_contact_info(self, soup: BeautifulSoup) -> Dict[str, bool]:
        """Detect presence of contact information."""
        text = soup.get_text()

        # Check for phone
        has_phone = any(
            re.search(pattern, text)
            for pattern in self.phone_patterns
        )

        # Check for email
        has_email = bool(re.search(self.email_pattern, text))

        # Check for contact form
        has_form = bool(soup.find('form')) or bool(
            soup.find(attrs={'class': re.compile(r'contact|form', re.I)})
        )

        return {
            'has_phone': has_phone,
            'has_email': has_email,
            'has_form': has_form
        }

    def _detect_page_type(self, url: str, soup: BeautifulSoup) -> str:
        """Detect page type based on URL and content."""
        path = urlparse(url).path.lower()

        for page_type, patterns in self.page_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, path):
                    return page_type

        # Default based on content
        title = soup.title.string.lower() if soup.title else ""

        if 'service' in title:
            return 'services'
        elif 'about' in title:
            return 'about'
        elif 'contact' in title:
            return 'contact'
        elif 'blog' in title or 'news' in title:
            return 'blog'

        return 'other'

    def _extract_opengraph(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract OpenGraph metadata."""
        og_data = {}

        og_properties = ['og:title', 'og:description', 'og:image', 'og:type', 'og:url']
        for prop in og_properties:
            meta = soup.find('meta', property=prop)
            if meta:
                key = prop.replace('og:', 'og_')
                og_data[key] = meta.get('content', '')

        return og_data

    def _extract_twitter_card(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract Twitter Card metadata."""
        twitter_data = {}

        twitter_properties = [
            'twitter:card', 'twitter:title', 'twitter:description', 'twitter:image'
        ]
        for prop in twitter_properties:
            meta = soup.find('meta', attrs={'name': prop})
            if meta:
                key = prop.replace(':', '_')
                twitter_data[key] = meta.get('content', '')

        return twitter_data

    def _extract_robots(self, soup: BeautifulSoup) -> str:
        """Extract robots meta directives."""
        robots_meta = soup.find('meta', attrs={'name': 'robots'})
        if robots_meta:
            return robots_meta.get('content', '')
        return ""

    def _extract_hreflang(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract hreflang links for international targeting."""
        hreflang_links = []

        for link in soup.find_all('link', rel='alternate', hreflang=True):
            hreflang_links.append({
                'lang': link.get('hreflang', ''),
                'url': link.get('href', '')
            })

        return hreflang_links

    def _extract_pagination(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract pagination links (rel=prev/next)."""
        pagination = {'prev': '', 'next': ''}

        prev_link = soup.find('link', rel='prev')
        if prev_link:
            pagination['prev'] = prev_link.get('href', '')

        next_link = soup.find('link', rel='next')
        if next_link:
            pagination['next'] = next_link.get('href', '')

        return pagination

    def _split_content_sections(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """
        Split page content into sections by H2/H3 headings.

        Returns:
            List of sections with heading and content
        """
        sections = []

        # Remove script, style, nav, header, footer
        for elem in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            elem.decompose()

        # Find all H2 headings
        h2_headings = soup.find_all('h2')

        for i, h2 in enumerate(h2_headings):
            heading_text = h2.get_text(strip=True)

            # Get content until next H2
            content_parts = []
            current = h2.find_next_sibling()

            while current:
                # Stop at next H2
                if current.name == 'h2':
                    break

                # Collect H3 and content
                if current.name in ['h3', 'p', 'ul', 'ol', 'div']:
                    text = current.get_text(separator=' ', strip=True)
                    if text:
                        content_parts.append(text)

                current = current.find_next_sibling()

            content = ' '.join(content_parts)

            if heading_text and content:
                sections.append({
                    'heading': heading_text,
                    'heading_level': 'h2',
                    'content': content[:2000],  # Limit content length
                    'word_count': len(content.split())
                })

        # If no H2 sections found, create one default section
        if not sections:
            body_text = soup.get_text(separator=' ', strip=True)
            if body_text:
                sections.append({
                    'heading': 'Main Content',
                    'heading_level': 'body',
                    'content': body_text[:2000],
                    'word_count': len(body_text.split())
                })

        return sections

    def _calculate_schema_summary(self, schemas: List[Dict]) -> Dict[str, Any]:
        """
        Calculate schema completeness scoring.

        Analyzes schema.org markup and scores completeness for:
        - LocalBusiness
        - Organization
        - FAQPage
        - Review / AggregateRating

        Returns:
            Dict with completeness scores and detected types
        """
        summary = {
            'has_local_business': False,
            'has_organization': False,
            'has_faq': False,
            'has_review': False,
            'local_business_score': 0,
            'organization_score': 0,
            'required_fields': {},
            'optional_fields': {}
        }

        # Define required/optional fields for key schema types
        local_business_required = ['name', 'address', 'telephone']
        local_business_optional = ['url', 'image', 'priceRange', 'openingHours', 'geo']

        organization_required = ['name', 'url']
        organization_optional = ['logo', 'contactPoint', 'sameAs', 'address']

        for schema in schemas:
            schema_type = schema.get('@type', '')

            if isinstance(schema_type, list):
                schema_type = schema_type[0] if schema_type else ''

            # Check LocalBusiness
            if 'LocalBusiness' in str(schema_type):
                summary['has_local_business'] = True
                required_present = sum(1 for field in local_business_required if field in schema)
                optional_present = sum(1 for field in local_business_optional if field in schema)

                # Score: 70% from required, 30% from optional
                req_score = (required_present / len(local_business_required)) * 70
                opt_score = (optional_present / len(local_business_optional)) * 30
                summary['local_business_score'] = int(req_score + opt_score)

                summary['required_fields']['local_business'] = {
                    field: (field in schema) for field in local_business_required
                }

            # Check Organization
            if schema_type == 'Organization':
                summary['has_organization'] = True
                required_present = sum(1 for field in organization_required if field in schema)
                optional_present = sum(1 for field in organization_optional if field in schema)

                req_score = (required_present / len(organization_required)) * 70
                opt_score = (optional_present / len(organization_optional)) * 30
                summary['organization_score'] = int(req_score + opt_score)

                summary['required_fields']['organization'] = {
                    field: (field in schema) for field in organization_required
                }

            # Check FAQPage
            if schema_type == 'FAQPage':
                summary['has_faq'] = True

            # Check Review / AggregateRating
            if 'Review' in str(schema_type) or 'aggregateRating' in schema:
                summary['has_review'] = True

        return summary

    def parse(self, html: str, url: str) -> PageMetrics:
        """
        Parse a competitor page and extract metrics.

        Args:
            html: Raw HTML content
            url: Page URL

        Returns:
            PageMetrics: Extracted page metrics
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Extract title
        title = ""
        if soup.title:
            title = soup.title.string or ""

        # Extract meta tags
        meta_description = self._extract_meta(soup, 'description')
        meta_keywords = self._extract_meta(soup, 'keywords')

        # Extract canonical
        canonical_elem = soup.find('link', rel='canonical')
        canonical_url = canonical_elem.get('href', '') if canonical_elem else ""

        # Extract OpenGraph metadata
        og_data = self._extract_opengraph(soup)

        # Extract Twitter Card metadata
        twitter_data = self._extract_twitter_card(soup)

        # Extract robots directives
        robots_meta = self._extract_robots(soup)

        # Extract hreflang links
        hreflang_links = self._extract_hreflang(soup)

        # Extract pagination links
        pagination = self._extract_pagination(soup)

        # Extract headings
        h1_tags = self._extract_headings(soup, 'h1')
        h2_tags = self._extract_headings(soup, 'h2')
        h3_tags = self._extract_headings(soup, 'h3')

        # Split content into sections
        content_sections = self._split_content_sections(soup)

        # Extract schema
        schemas = self._extract_schema(soup)
        schema_types = self._extract_schema_types(schemas)
        schema_summary = self._calculate_schema_summary(schemas)

        # Count words
        word_count = self._count_words(soup)

        # Analyze links
        links = self._analyze_links(soup, url)

        # Analyze images
        images = self._analyze_images(soup)

        # Detect contact info
        contact = self._detect_contact_info(soup)

        # Detect page type
        page_type = self._detect_page_type(url, soup)

        # Build metrics
        metrics = PageMetrics(
            url=url,
            title=title.strip(),
            meta_description=meta_description,
            meta_keywords=meta_keywords,
            canonical_url=canonical_url,
            # OpenGraph
            og_title=og_data.get('og_title', ''),
            og_description=og_data.get('og_description', ''),
            og_image=og_data.get('og_image', ''),
            og_type=og_data.get('og_type', ''),
            og_url=og_data.get('og_url', ''),
            # Twitter Card
            twitter_card=twitter_data.get('twitter_card', ''),
            twitter_title=twitter_data.get('twitter_title', ''),
            twitter_description=twitter_data.get('twitter_description', ''),
            twitter_image=twitter_data.get('twitter_image', ''),
            # Robots
            robots_meta=robots_meta,
            # International & Pagination
            hreflang_links=hreflang_links,
            rel_prev=pagination['prev'],
            rel_next=pagination['next'],
            # Headings
            h1_tags=h1_tags,
            h2_tags=h2_tags[:10],  # Limit to first 10
            h3_tags=h3_tags[:10],
            # Content
            word_count=word_count,
            content_sections=content_sections,
            # Links
            internal_links=links['internal'],
            external_links=links['external'],
            # Images
            images=images['total'],
            images_with_alt=images['with_alt'],
            # Schema
            schema_types=schema_types,
            schema_markup=schemas,
            schema_summary=schema_summary,
            # Contact
            has_contact_form=contact['has_form'],
            has_phone=contact['has_phone'],
            has_email=contact['has_email'],
            social_links=links['social'],
            # Page type
            page_type=page_type,
        )

        logger.debug(
            f"Parsed {url}: {word_count} words, "
            f"{len(h1_tags)} H1s, {len(schema_types)} schema types"
        )

        return metrics


# Module-level singleton
_competitor_parser_instance = None


def get_competitor_parser() -> CompetitorParser:
    """Get or create the singleton CompetitorParser instance."""
    global _competitor_parser_instance

    if _competitor_parser_instance is None:
        _competitor_parser_instance = CompetitorParser()

    return _competitor_parser_instance


def main():
    """Demo: Test competitor page parsing."""
    logger.info("=" * 60)
    logger.info("Competitor Parser Demo")
    logger.info("=" * 60)
    logger.info("")

    parser = get_competitor_parser()

    # Sample HTML for testing
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Best Pressure Washing in Austin | ABC Cleaning</title>
        <meta name="description" content="Professional pressure washing services in Austin, TX. Call (512) 555-1234 for a free quote.">
        <meta name="keywords" content="pressure washing, austin, cleaning">
        <link rel="canonical" href="https://abccleaning.com/">
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": "ABC Cleaning",
            "telephone": "(512) 555-1234",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Austin",
                "addressRegion": "TX"
            }
        }
        </script>
    </head>
    <body>
        <nav><a href="/">Home</a> <a href="/services">Services</a></nav>
        <h1>Professional Pressure Washing Services</h1>
        <p>Welcome to ABC Cleaning! We offer the best pressure washing services in Austin.</p>
        <h2>Our Services</h2>
        <p>Driveway cleaning, house washing, deck cleaning, and more. Contact us at info@abccleaning.com</p>
        <h2>Why Choose Us</h2>
        <p>With 10 years of experience, we deliver quality results every time.</p>
        <img src="truck.jpg" alt="Our pressure washing truck">
        <img src="results.jpg">
        <a href="https://facebook.com/abccleaning">Facebook</a>
        <a href="https://yelp.com/biz/abc-cleaning">Yelp</a>
        <form><input type="text" name="name"><button>Contact Us</button></form>
    </body>
    </html>
    """

    # Parse sample page
    metrics = parser.parse(sample_html, "https://abccleaning.com/")

    # Display results
    logger.info(f"URL: {metrics.url}")
    logger.info(f"Title: {metrics.title}")
    logger.info(f"Meta Description: {metrics.meta_description}")
    logger.info(f"Canonical: {metrics.canonical_url}")
    logger.info(f"Page Type: {metrics.page_type}")
    logger.info("")
    logger.info(f"H1 Tags: {metrics.h1_tags}")
    logger.info(f"H2 Tags: {metrics.h2_tags}")
    logger.info(f"Word Count: {metrics.word_count}")
    logger.info("")
    logger.info(f"Internal Links: {metrics.internal_links}")
    logger.info(f"External Links: {metrics.external_links}")
    logger.info(f"Social Links: {metrics.social_links}")
    logger.info("")
    logger.info(f"Images: {metrics.images} ({metrics.images_with_alt} with alt)")
    logger.info(f"Has Phone: {metrics.has_phone}")
    logger.info(f"Has Email: {metrics.has_email}")
    logger.info(f"Has Contact Form: {metrics.has_contact_form}")
    logger.info("")
    logger.info(f"Schema Types: {metrics.schema_types}")
    logger.info("")
    logger.info("=" * 60)
    logger.info("Demo complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
