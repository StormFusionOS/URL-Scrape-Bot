"""
SERP Parser Module

Parses Google Search Engine Results Pages (SERPs) to extract:
- Organic search results (title, URL, description, position)
- Featured snippets
- Local pack results
- People also ask
- Related searches

Uses BeautifulSoup for reliable HTML parsing with fallback strategies
for different Google SERP layouts.
"""

import re
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse, parse_qs, unquote
from dataclasses import dataclass, field, asdict
from bs4 import BeautifulSoup

from runner.logging_setup import get_logger

logger = get_logger("serp_parser")


@dataclass
class PAAQuestion:
    """Represents a People Also Ask question with full details."""
    question: str
    answer: str = ""
    source_url: str = ""
    source_domain: str = ""
    position: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class SerpResult:
    """Represents a single SERP result."""
    position: int
    url: str
    title: str
    description: str = ""
    domain: str = ""
    is_featured: bool = False
    is_local: bool = False
    is_ad: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Extract domain from URL if not provided."""
        if not self.domain and self.url:
            try:
                parsed = urlparse(self.url)
                self.domain = parsed.netloc.lower()
                if self.domain.startswith("www."):
                    self.domain = self.domain[4:]
            except Exception:
                pass

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class Sitelink:
    """Represents a sitelink from SERP results."""
    anchor: str
    url: str
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class SitelinkGroup:
    """Represents sitelinks for a domain in SERP."""
    domain: str
    position: int
    links: List[Sitelink] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "position": self.position,
            "links": [sl.to_dict() for sl in self.links],
        }


@dataclass
class SerpSnapshot:
    """Represents a complete SERP snapshot."""
    query: str
    location: Optional[str]
    results: List[SerpResult] = field(default_factory=list)
    total_results: Optional[int] = None
    featured_snippet: Optional[Dict] = None
    local_pack: List[Dict] = field(default_factory=list)
    people_also_ask: List[PAAQuestion] = field(default_factory=list)
    related_searches: List[str] = field(default_factory=list)
    serp_features: List[str] = field(default_factory=list)  # Track detected SERP features
    sitelinks: List[SitelinkGroup] = field(default_factory=list)  # Extracted sitelinks
    video_results: List[Dict] = field(default_factory=list)  # Video carousel/results
    image_pack: List[Dict] = field(default_factory=list)  # Image pack results
    knowledge_panel: Optional[Dict] = None  # Knowledge panel data
    ads: List[Dict] = field(default_factory=list)  # Paid ads (competitive intel)
    news_results: List[Dict] = field(default_factory=list)  # Top stories/news carousel
    discussions: List[Dict] = field(default_factory=list)  # Reddit/Quora/forum results
    refine_chips: List[str] = field(default_factory=list)  # Search refinement suggestions
    # NEW: Quality data extraction fields
    ai_overview: Optional[Dict] = None  # AI Overview/SGE content
    answer_boxes: List[Dict] = field(default_factory=list)  # Answer box variants
    serp_complexity_score: float = 0.0  # Overall SERP complexity (0-100)
    layout_metrics: Dict[str, Any] = field(default_factory=dict)  # Position/fold metrics
    intent_signals: Dict[str, Any] = field(default_factory=dict)  # Query intent detection
    feature_ordering: List[str] = field(default_factory=list)  # Order features appear
    schema_markup_detected: List[str] = field(default_factory=list)  # Schema types found
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "location": self.location,
            "results": [r.to_dict() for r in self.results],
            "total_results": self.total_results,
            "featured_snippet": self.featured_snippet,
            "local_pack": self.local_pack,
            "people_also_ask": [paa.to_dict() for paa in self.people_also_ask],
            "related_searches": self.related_searches,
            "serp_features": self.serp_features,
            "sitelinks": [sg.to_dict() for sg in self.sitelinks],
            "video_results": self.video_results,
            "image_pack": self.image_pack,
            "knowledge_panel": self.knowledge_panel,
            "ads": self.ads,
            "news_results": self.news_results,
            "discussions": self.discussions,
            "refine_chips": self.refine_chips,
            # NEW: Quality data fields
            "ai_overview": self.ai_overview,
            "answer_boxes": self.answer_boxes,
            "serp_complexity_score": self.serp_complexity_score,
            "layout_metrics": self.layout_metrics,
            "intent_signals": self.intent_signals,
            "feature_ordering": self.feature_ordering,
            "schema_markup_detected": self.schema_markup_detected,
            "metadata": self.metadata,
        }


class SerpParser:
    """
    Parser for Google Search Engine Results Pages.

    Handles multiple SERP layouts and extracts:
    - Organic results with position tracking
    - Featured snippets
    - Local pack/map results
    - People Also Ask questions
    - Related searches

    Uses multiple selector strategies for resilience against layout changes.
    """

    def __init__(self):
        """Initialize SERP parser."""
        # Selectors for organic results (multiple strategies)
        self.organic_selectors = [
            "div.g",                    # Traditional result container
            "div[data-hveid] > div.g",  # Results with tracking
            "div.tF2Cxc",               # Alternative container
            "div.yuRUbf",               # URL container
        ]

        # Selectors for ads
        self.ad_selectors = [
            "div.uEierd",               # Ad container
            "div[data-text-ad]",        # Text ad
            "div.commercial-unit",      # Commercial unit
        ]

        logger.info("SerpParser initialized")

    def _clean_url(self, url: str) -> str:
        """
        Clean and extract actual URL from Google redirect.

        Google often wraps URLs like:
        /url?q=https://example.com/page&sa=U&...

        Args:
            url: Raw URL from SERP

        Returns:
            str: Cleaned URL
        """
        if not url:
            return ""

        # Handle Google redirect URLs
        if url.startswith("/url?"):
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                if "q" in params:
                    return unquote(params["q"][0])
                if "url" in params:
                    return unquote(params["url"][0])
            except Exception:
                pass

        # Handle relative URLs
        if url.startswith("/"):
            return f"https://www.google.com{url}"

        return url

    def _extract_text(self, element, selector: str = None) -> str:
        """
        Safely extract text from element.

        Args:
            element: BeautifulSoup element
            selector: Optional CSS selector to find child element

        Returns:
            str: Extracted text or empty string
        """
        if element is None:
            return ""

        if selector:
            element = element.select_one(selector)
            if element is None:
                return ""

        return element.get_text(strip=True)

    def _parse_organic_result(self, element, position: int) -> Optional[SerpResult]:
        """
        Parse a single organic search result.

        Args:
            element: BeautifulSoup element containing the result
            position: Position in SERP (1-indexed)

        Returns:
            SerpResult or None if parsing fails
        """
        try:
            # Find title and URL
            title_elem = None
            url = ""
            title = ""

            # Try different title selectors
            for title_selector in ["h3", "h3.LC20lb", "div.yuRUbf h3"]:
                title_elem = element.select_one(title_selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    break

            # Find URL from anchor
            link_elem = element.select_one("a[href]")
            if link_elem:
                url = self._clean_url(link_elem.get("href", ""))

            # Skip if no title or URL
            if not title or not url:
                return None

            # Skip Google internal links
            if "google.com" in url and "/search" in url:
                return None

            # Find description
            description = ""
            for desc_selector in [
                "div.VwiC3b",           # Standard description
                "span.aCOpRe",          # Alternative
                "div.IsZvec",           # Another variant
                "div[data-snf]",        # Snippet container
            ]:
                desc_elem = element.select_one(desc_selector)
                if desc_elem:
                    description = desc_elem.get_text(strip=True)
                    break

            # Create result
            result = SerpResult(
                position=position,
                url=url,
                title=title,
                description=description,
                is_featured=False,
                is_local=False,
                is_ad=False,
            )

            # Extract rich snippets / structured data
            self._extract_rich_snippets(element, result)

            return result

        except Exception as e:
            logger.warning(f"Error parsing organic result at position {position}: {e}")
            return None

    def _extract_rich_snippets(self, element, result: SerpResult):
        """
        Extract rich snippet data from a search result element.

        Extracts:
        - Star ratings
        - Review counts
        - Prices
        - Dates
        - Authors
        - FAQ data

        Args:
            element: BeautifulSoup element containing the result
            result: SerpResult object to update with rich snippet data
        """
        try:
            # Extract star rating (multiple possible selectors)
            rating_selectors = [
                "span.z3HNkc",      # Standard rating stars
                "span.yi40Hd",      # Alternative rating
                "span.Fam1ne",      # Another variant
                "g-review-stars",   # Google review stars element
            ]
            for selector in rating_selectors:
                rating_elem = element.select_one(selector)
                if rating_elem:
                    # Try to get aria-label for exact rating
                    aria_label = rating_elem.get("aria-label", "")
                    if aria_label:
                        result.metadata['rating_text'] = aria_label
                        # Try to extract numeric rating
                        import re
                        rating_match = re.search(r"(\d+\.?\d*)", aria_label)
                        if rating_match:
                            result.metadata['rating'] = float(rating_match.group(1))
                    else:
                        result.metadata['rating_text'] = rating_elem.get_text(strip=True)
                    break

            # Extract review count
            review_selectors = [
                "span.fG8Fp",       # Review count container
                "span.RDApEe",      # Alternative review count
                "span.HRLxBb",      # Another variant
                "span.z5jxId",      # Review count text
            ]
            for selector in review_selectors:
                review_elem = element.select_one(selector)
                if review_elem:
                    review_text = review_elem.get_text(strip=True)
                    result.metadata['review_count_text'] = review_text
                    # Try to extract numeric count
                    import re
                    count_match = re.search(r"([\d,]+)", review_text)
                    if count_match:
                        result.metadata['review_count'] = int(count_match.group(1).replace(",", ""))
                    break

            # Extract price information
            price_selectors = [
                "span.A2b4td",      # Price container
                "span.HRLxBb",      # Price text
                "span.LI0TWe",      # Price range
                "span[data-price]", # Data attribute price
            ]
            for selector in price_selectors:
                price_elem = element.select_one(selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    if "$" in price_text or "€" in price_text or "£" in price_text:
                        result.metadata['price'] = price_text
                        break

            # Extract date/time information (for articles, events, etc.)
            date_selectors = [
                "span.f",           # Date container
                "span.xUrNXd",      # Alternative date
                "span.LEwnzc",      # Date text
                "time",             # HTML time element
            ]
            for selector in date_selectors:
                date_elem = element.select_one(selector)
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                    datetime_attr = date_elem.get("datetime", "")
                    if datetime_attr:
                        result.metadata['date_iso'] = datetime_attr
                    if date_text:
                        result.metadata['date_text'] = date_text
                    break

            # Extract author information
            author_selectors = [
                "span.oewGkc",      # Author name
                "span.WPsM5b",      # Alternative author
                "cite.iUh30",       # Citation/author
            ]
            for selector in author_selectors:
                author_elem = element.select_one(selector)
                if author_elem:
                    result.metadata['author'] = author_elem.get_text(strip=True)
                    break

            # Extract breadcrumb/path information
            breadcrumb_elem = element.select_one("cite.qLRx3b")
            if breadcrumb_elem:
                result.metadata['breadcrumb'] = breadcrumb_elem.get_text(strip=True)

            # Check for FAQ schema (accordion questions)
            faq_items = element.select("div.wDYxhc")
            if faq_items:
                faqs = []
                for faq in faq_items[:5]:  # Limit to 5 FAQs
                    q_elem = faq.select_one("div[role='button']")
                    a_elem = faq.select_one("div.bCOlv")
                    if q_elem:
                        faq_data = {
                            'question': q_elem.get_text(strip=True),
                            'answer': a_elem.get_text(strip=True)[:300] if a_elem else ""
                        }
                        faqs.append(faq_data)
                if faqs:
                    result.metadata['faqs'] = faqs

            # Extract snippet type indicators
            if element.select_one("div.xpdopen, div.ifM9O"):
                result.metadata['has_expanded_content'] = True

        except Exception as e:
            logger.debug(f"Error extracting rich snippets: {e}")

    def _parse_ads(self, soup: BeautifulSoup) -> List[SerpResult]:
        """
        Parse ad results from SERP.

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of SerpResult objects for ads
        """
        ads = []

        for selector in self.ad_selectors:
            ad_elements = soup.select(selector)
            for i, elem in enumerate(ad_elements, 1):
                try:
                    # Find title
                    title_elem = elem.select_one("div.CCgQ5")
                    title = title_elem.get_text(strip=True) if title_elem else ""

                    # Find URL
                    link_elem = elem.select_one("a[href]")
                    url = self._clean_url(link_elem.get("href", "")) if link_elem else ""

                    # Find description
                    desc_elem = elem.select_one("div.MUxGbd")
                    description = desc_elem.get_text(strip=True) if desc_elem else ""

                    if title and url:
                        ads.append(SerpResult(
                            position=i,
                            url=url,
                            title=title,
                            description=description,
                            is_ad=True,
                        ))
                except Exception as e:
                    logger.warning(f"Error parsing ad: {e}")
                    continue

        return ads

    def _parse_local_pack(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parse local pack / map results with enhanced extraction.

        Extracts comprehensive local business data including:
        - Business name
        - Rating and review count
        - Full address (street, city, state, zip)
        - Phone number
        - Hours of operation
        - Category/type
        - Website URL
        - Service offerings

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of local business dictionaries with comprehensive data
        """
        local_results = []

        # Multiple selectors for local pack container
        local_container_selectors = [
            "div.VkpGBb",               # Standard local pack
            "div[data-attrid='kc:/local:']",  # Local knowledge card
            "div.rlfl__tls",            # Local results container
            "div.cXedhc",               # Alternative local container
        ]

        local_container = None
        for selector in local_container_selectors:
            local_container = soup.select_one(selector)
            if local_container:
                break

        if not local_container:
            # Try finding local pack by heading
            local_heading = soup.select_one("div[aria-label*='Local results']")
            if local_heading:
                local_container = local_heading.parent

        if not local_container:
            return local_results

        # Multiple selectors for individual local listings
        listing_selectors = [
            "div.VkpGBb",       # Standard listing
            "div.rllt__link",   # Local link container
            "a.rllt__link",     # Local link
            "div.cXedhc",       # Alternative listing
        ]

        listings = []
        for selector in listing_selectors:
            listings = local_container.select(selector)
            if listings:
                break

        # If still no listings, look for any business cards
        if not listings:
            listings = local_container.select("div[data-cid]")

        for i, listing in enumerate(listings, 1):
            try:
                local_data = {"position": i}

                # Extract business name - multiple selectors
                name_selectors = [
                    "div.dbg0pd",       # Standard name
                    "span.OSrXXb",      # Alternative name
                    "div.qBF1Pd",       # Name container
                    "span.cXedhc",      # Another variant
                    "div[role='heading']",  # Heading role
                ]
                for selector in name_selectors:
                    name_elem = listing.select_one(selector)
                    if name_elem:
                        local_data['name'] = name_elem.get_text(strip=True)
                        break

                if not local_data.get('name'):
                    continue  # Skip if no name found

                # Extract rating (numeric)
                rating_selectors = [
                    "span.yi40Hd",      # Rating text
                    "span.z3HNkc",      # Rating stars
                    "span.Fam1ne",      # Alternative rating
                ]
                for selector in rating_selectors:
                    rating_elem = listing.select_one(selector)
                    if rating_elem:
                        rating_text = rating_elem.get_text(strip=True)
                        local_data['rating_text'] = rating_text
                        # Try to extract numeric rating
                        rating_match = re.search(r"(\d+\.?\d*)", rating_text)
                        if rating_match:
                            local_data['rating'] = float(rating_match.group(1))
                        break

                # Extract review count
                review_selectors = [
                    "span.RDApEe",      # Review count
                    "span.HRLxBb",      # Alternative review
                    "span.z5jxId",      # Review text
                ]
                for selector in review_selectors:
                    review_elem = listing.select_one(selector)
                    if review_elem:
                        review_text = review_elem.get_text(strip=True)
                        local_data['review_count_text'] = review_text
                        # Try to extract numeric count
                        count_match = re.search(r"([\d,]+)", review_text)
                        if count_match:
                            local_data['review_count'] = int(count_match.group(1).replace(",", ""))
                        break

                # Extract details container
                details_elem = listing.select_one("div.rllt__details")
                if details_elem:
                    details_text = details_elem.get_text(" | ", strip=True)
                    local_data['details'] = details_text

                    # Parse details into structured data
                    self._parse_local_details(details_text, local_data)

                # Extract category/type
                category_selectors = [
                    "span.YhemCb",      # Category span
                    "div.rllt__wrapped", # Wrapped category
                    "span.v5ovVe",      # Alternative category
                ]
                for selector in category_selectors:
                    cat_elem = listing.select_one(selector)
                    if cat_elem:
                        local_data['category'] = cat_elem.get_text(strip=True)
                        break

                # Extract phone number
                phone_selectors = [
                    "span.rllt__teln",  # Phone container
                    "span.LrzXr",       # Phone text
                    "a[href^='tel:']",  # Phone link
                ]
                for selector in phone_selectors:
                    phone_elem = listing.select_one(selector)
                    if phone_elem:
                        if phone_elem.name == 'a':
                            phone = phone_elem.get('href', '').replace('tel:', '')
                        else:
                            phone = phone_elem.get_text(strip=True)
                        if phone:
                            local_data['phone'] = phone
                        break

                # Extract website URL
                website_elem = listing.select_one("a[data-rc='website'], a.yYlJEf")
                if website_elem:
                    local_data['website'] = self._clean_url(website_elem.get('href', ''))

                # Extract directions/address URL
                directions_elem = listing.select_one("a[data-rc='directions'], a[href*='maps']")
                if directions_elem:
                    local_data['directions_url'] = directions_elem.get('href', '')

                # Extract hours
                hours_elem = listing.select_one("span.zhFJpc, div.UkvPoc")
                if hours_elem:
                    hours_text = hours_elem.get_text(strip=True)
                    local_data['hours'] = hours_text
                    # Check if open/closed
                    if 'open' in hours_text.lower():
                        local_data['is_open'] = True
                    elif 'closed' in hours_text.lower():
                        local_data['is_open'] = False

                # Extract service offerings if available
                services_elem = listing.select_one("div.Io6YTe")
                if services_elem:
                    local_data['services'] = services_elem.get_text(strip=True)

                # Extract price level if shown
                price_elem = listing.select_one("span.mgr77e")
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    if '$' in price_text:
                        local_data['price_level'] = price_text.count('$')

                local_results.append(local_data)

            except Exception as e:
                logger.warning(f"Error parsing local result at position {i}: {e}")
                continue

        if local_results:
            logger.info(f"Extracted {len(local_results)} enhanced local pack results")

        return local_results

    def _parse_local_details(self, details_text: str, local_data: Dict):
        """
        Parse local pack details text into structured address and info.

        Args:
            details_text: Raw details text from local result
            local_data: Dictionary to update with parsed data
        """
        try:
            parts = details_text.split(" | ")

            for part in parts:
                part = part.strip()

                # Check for address patterns
                # Full address: "123 Main St, Austin, TX 78701"
                address_match = re.match(
                    r"(\d+\s+[^,]+),\s*([^,]+),\s*([A-Z]{2})\s*(\d{5})?",
                    part
                )
                if address_match:
                    local_data['street'] = address_match.group(1)
                    local_data['city'] = address_match.group(2)
                    local_data['state'] = address_match.group(3)
                    if address_match.group(4):
                        local_data['zip_code'] = address_match.group(4)
                    continue

                # City, State pattern
                city_state_match = re.match(r"([^,]+),\s*([A-Z]{2})$", part)
                if city_state_match:
                    local_data['city'] = city_state_match.group(1)
                    local_data['state'] = city_state_match.group(2)
                    continue

                # Distance pattern (e.g., "2.3 mi")
                distance_match = re.match(r"([\d.]+)\s*(mi|miles?|km)", part, re.IGNORECASE)
                if distance_match:
                    local_data['distance'] = f"{distance_match.group(1)} {distance_match.group(2)}"
                    continue

                # Hours pattern
                hours_match = re.search(r"(open|closed|opens?|closes?)\s*(at\s*)?\d+", part, re.IGNORECASE)
                if hours_match:
                    local_data['hours_snippet'] = part
                    continue

                # Price range pattern
                if part.startswith('$') or '$$' in part:
                    local_data['price_range'] = part
                    continue

        except Exception as e:
            logger.debug(f"Error parsing local details: {e}")

    def _parse_people_also_ask(self, soup: BeautifulSoup) -> List[PAAQuestion]:
        """
        Parse "People Also Ask" questions with full structured data.

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of PAAQuestion objects with question, answer, source, position
        """
        paa_questions = []

        # Multiple selectors for PAA sections (Google layout varies)
        paa_selectors = [
            "div.related-question-pair",  # Classic PAA container
            "div[jsname='yEVEE']",        # Alternative container
            "div.cbphWd",                  # Another variant
            "div[data-q]",                 # Data attribute approach
        ]

        position = 1
        for selector in paa_selectors:
            paa_elements = soup.select(selector)

            for elem in paa_elements:
                try:
                    # Extract question text
                    question = None

                    # Try data-q attribute first
                    if elem.get("data-q"):
                        question = elem.get("data-q")
                    else:
                        # Look for question in various elements
                        question_elem = (
                            elem.select_one("div[role='button']") or
                            elem.select_one("span[jsname]") or
                            elem.select_one("div.JlqpRe") or
                            elem.select_one("div")
                        )
                        if question_elem:
                            question = question_elem.get_text(strip=True)

                    if not question or len(question) < 5:
                        continue

                    # Extract answer text (expandable content)
                    answer = ""
                    answer_elem = (
                        elem.select_one("div.hgKElc") or  # Answer container
                        elem.select_one("div.kno-rdesc") or  # Knowledge answer
                        elem.select_one("div[data-attrid='wa:/description']") or
                        elem.select_one("span.hgKElc")
                    )
                    if answer_elem:
                        answer = answer_elem.get_text(strip=True)

                    # Extract source URL and domain
                    source_url = ""
                    source_domain = ""
                    source_link = elem.select_one("a[href]")
                    if source_link:
                        source_url = self._clean_url(source_link.get("href", ""))
                        if source_url:
                            try:
                                parsed = urlparse(source_url)
                                source_domain = parsed.netloc.lower()
                                if source_domain.startswith("www."):
                                    source_domain = source_domain[4:]
                            except Exception:
                                pass

                    paa_questions.append(PAAQuestion(
                        question=question,
                        answer=answer[:500],  # Limit answer length
                        source_url=source_url,
                        source_domain=source_domain,
                        position=position
                    ))

                    position += 1

                except Exception as e:
                    logger.debug(f"Error parsing PAA question: {e}")
                    continue

            # If we found PAA questions, don't try other selectors
            if paa_questions:
                break

        return paa_questions

    def _parse_related_searches(self, soup: BeautifulSoup) -> List[str]:
        """
        Parse related searches.

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of related search terms
        """
        related = []

        # Find related searches container
        related_container = soup.select_one("div#brs") or soup.select_one("div.AJLUJb")

        if related_container:
            related_links = related_container.select("a")
            for link in related_links:
                text = link.get_text(strip=True)
                if text and len(text) > 2:
                    related.append(text)

        return related

    def _parse_sitelinks(self, soup: BeautifulSoup, results: List[SerpResult]) -> List[SitelinkGroup]:
        """
        Parse sitelinks from SERP results.

        Sitelinks appear beneath certain organic results as additional
        navigational links to important pages on the domain.

        Args:
            soup: BeautifulSoup object of SERP
            results: Parsed organic results (to get domain context)

        Returns:
            List of SitelinkGroup objects with domain, position, and links
        """
        sitelink_groups = []

        # Multiple selectors for sitelinks (Google layout varies)
        sitelink_selectors = [
            "div.usJj9c",          # Standard sitelinks container
            "table.jmjoTe",        # Table-based sitelinks
            "div.HiHjCd",          # Inline sitelinks
            "div[data-attrid='wa:/description'] + div a",  # Below description
        ]

        # Find all result containers with sitelinks
        result_containers = soup.select("div.g")

        for position, container in enumerate(result_containers, 1):
            # First check if this result has sitelinks
            sitelinks_container = None
            for selector in sitelink_selectors:
                sitelinks_container = container.select_one(selector)
                if sitelinks_container:
                    break

            if not sitelinks_container:
                # Also check for sitelinks in table format
                sitelinks_container = container.select_one("table")
                if sitelinks_container and not sitelinks_container.select("a[href]"):
                    sitelinks_container = None

            if not sitelinks_container:
                continue

            # Get the domain from the main result link
            main_link = container.select_one("a[href]")
            if not main_link:
                continue

            main_url = self._clean_url(main_link.get("href", ""))
            if not main_url or "google.com" in main_url:
                continue

            try:
                parsed = urlparse(main_url)
                domain = parsed.netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                continue

            # Extract individual sitelinks
            sitelinks = []
            sitelink_anchors = sitelinks_container.select("a[href]")

            for anchor in sitelink_anchors:
                href = anchor.get("href", "")
                url = self._clean_url(href)

                # Skip Google internal links and the main URL
                if not url or "google.com" in url or url == main_url:
                    continue

                anchor_text = anchor.get_text(strip=True)
                if not anchor_text or len(anchor_text) < 2:
                    continue

                # Try to get description (often in sibling or child element)
                description = ""
                parent = anchor.parent
                if parent:
                    desc_elem = parent.select_one("span, div.st")
                    if desc_elem:
                        description = desc_elem.get_text(strip=True)[:150]

                sitelinks.append(Sitelink(
                    anchor=anchor_text,
                    url=url,
                    description=description,
                ))

            if sitelinks:
                sitelink_groups.append(SitelinkGroup(
                    domain=domain,
                    position=position,
                    links=sitelinks,
                ))
                logger.debug(
                    f"Found {len(sitelinks)} sitelinks for {domain} at position {position}"
                )

        return sitelink_groups

    def _parse_video_results(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parse video results from SERP (YouTube and other video sources).

        Extracts video carousel/section data including:
        - Video title
        - Channel name
        - Duration
        - View count
        - Upload date
        - Thumbnail URL
        - Video URL

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of video result dictionaries
        """
        videos = []

        # Multiple selectors for video containers
        video_container_selectors = [
            "g-section-with-header[data-header-text*='Videos']",  # Video section
            "div.YpRj3e",  # Individual video result
            "div[data-attrid='VideoCarousel']",  # Video carousel
            "div.RzdJxc",  # Video result container
            "div.mnr-c g-inner-card",  # Video cards
        ]

        # Try to find the video section first
        video_section = None
        for selector in ["g-section-with-header", "div[data-hveid] div.MjjYud"]:
            section = soup.select_one(selector)
            if section:
                # Check if it contains video indicators
                if section.select("div.YpRj3e") or section.select("div.RzdJxc"):
                    video_section = section
                    break

        # If no section found, search entire page
        search_area = video_section if video_section else soup

        # Find individual video items
        video_selectors = [
            "div.YpRj3e",     # Standard video item
            "div.RzdJxc",     # Alternative video container
            "div.ct5Ked",     # Video card
            "g-inner-card",   # Google inner card (for videos)
        ]

        seen_urls = set()
        for selector in video_selectors:
            video_elements = search_area.select(selector)

            for elem in video_elements:
                try:
                    video_data = {}

                    # Extract video URL
                    link_elem = elem.select_one("a[href*='youtube.com'], a[href*='youtu.be'], a[href*='/watch']")
                    if not link_elem:
                        link_elem = elem.select_one("a[href]")

                    if link_elem:
                        video_url = self._clean_url(link_elem.get("href", ""))
                        if video_url in seen_urls:
                            continue
                        if not video_url or "google.com/search" in video_url:
                            continue
                        seen_urls.add(video_url)
                        video_data['url'] = video_url

                        # Determine source from URL
                        if 'youtube.com' in video_url or 'youtu.be' in video_url:
                            video_data['source'] = 'YouTube'
                        elif 'vimeo.com' in video_url:
                            video_data['source'] = 'Vimeo'
                        else:
                            video_data['source'] = 'Other'
                    else:
                        continue

                    # Extract title
                    title_selectors = [
                        "div.fc9yUc",   # Video title
                        "h3",           # Standard heading
                        "div.mCBkyc",   # Alternative title
                        "span.cHaqb",   # Title span
                    ]
                    for title_sel in title_selectors:
                        title_elem = elem.select_one(title_sel)
                        if title_elem:
                            video_data['title'] = title_elem.get_text(strip=True)
                            break

                    # Extract channel name
                    channel_selectors = [
                        "div.Zg1NU",    # Channel name container
                        "span.ocUPSd",  # Channel span
                        "div.gqF9jc",   # Alternative channel
                        "cite",         # Citation element
                    ]
                    for channel_sel in channel_selectors:
                        channel_elem = elem.select_one(channel_sel)
                        if channel_elem:
                            video_data['channel'] = channel_elem.get_text(strip=True)
                            break

                    # Extract duration
                    duration_selectors = [
                        "div.J1mWY",    # Duration badge
                        "span.J1mWY",   # Duration span
                        "div.FxLDp",    # Alternative duration
                    ]
                    for dur_sel in duration_selectors:
                        dur_elem = elem.select_one(dur_sel)
                        if dur_elem:
                            video_data['duration'] = dur_elem.get_text(strip=True)
                            break

                    # Extract view count and upload date (often together)
                    meta_selectors = [
                        "div.pcJO7e",   # Metadata container
                        "span.ocUPSd",  # Metadata span
                        "div.Uroaid",   # Alternative metadata
                    ]
                    for meta_sel in meta_selectors:
                        meta_elems = elem.select(meta_sel)
                        for meta_elem in meta_elems:
                            text = meta_elem.get_text(strip=True)
                            # Parse view count
                            if 'view' in text.lower():
                                video_data['views'] = text
                            # Parse upload date
                            elif any(t in text.lower() for t in ['ago', 'day', 'week', 'month', 'year']):
                                video_data['upload_date'] = text

                    # Extract thumbnail URL
                    img_elem = elem.select_one("img[src], img[data-src]")
                    if img_elem:
                        thumbnail = img_elem.get("src") or img_elem.get("data-src")
                        if thumbnail and not thumbnail.startswith("data:"):
                            video_data['thumbnail'] = thumbnail

                    # Only add if we have at least URL and title
                    if video_data.get('url') and video_data.get('title'):
                        videos.append(video_data)

                except Exception as e:
                    logger.debug(f"Error parsing video element: {e}")
                    continue

            # Stop if we found videos
            if videos:
                break

        if videos:
            logger.info(f"Extracted {len(videos)} video results")

        return videos

    def _parse_image_pack(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parse image pack/carousel from SERP.

        Extracts image results including:
        - Image URL (thumbnail)
        - Source page URL
        - Source domain
        - Alt text (if available)
        - Image title

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of image result dictionaries
        """
        images = []

        # Multiple selectors for image containers
        image_container_selectors = [
            "div.islrc",                    # Image results container
            "g-scrolling-carousel",         # Image carousel
            "div[data-tray]",               # Image tray
            "div#imagebox_bigimages",       # Image box
            "g-section-with-header[data-header-text*='Images']",  # Images section
        ]

        # Find image section
        image_section = None
        for selector in image_container_selectors:
            section = soup.select_one(selector)
            if section:
                image_section = section
                break

        if not image_section:
            # Try finding images anywhere on page
            image_section = soup

        # Find individual image items
        image_selectors = [
            "div.isv-r",          # Standard image result
            "div.ivg-i",          # Image in vertical grid
            "a.wXeWr",            # Image link
            "g-inner-card img",   # Image in card
            "div.eA0Zlc",         # Image container
        ]

        seen_urls = set()
        for selector in image_selectors:
            image_elements = image_section.select(selector)

            for elem in image_elements:
                try:
                    image_data = {}

                    # Find the image element
                    img_elem = elem if elem.name == 'img' else elem.select_one("img")

                    if img_elem:
                        # Get image source
                        src = img_elem.get("src") or img_elem.get("data-src")
                        if src and not src.startswith("data:") and src not in seen_urls:
                            seen_urls.add(src)
                            image_data['thumbnail_url'] = src

                        # Get alt text
                        alt = img_elem.get("alt", "")
                        if alt:
                            image_data['alt_text'] = alt

                        # Get title from alt or aria-label
                        title = img_elem.get("title") or alt
                        if title:
                            image_data['title'] = title

                    # Find source URL from parent link
                    link_elem = elem if elem.name == 'a' else elem.find_parent("a")
                    if not link_elem:
                        link_elem = elem.select_one("a[href]")

                    if link_elem:
                        href = link_elem.get("href", "")
                        source_url = self._clean_url(href)
                        if source_url and "google.com/search" not in source_url:
                            image_data['source_url'] = source_url

                            # Extract domain
                            try:
                                parsed = urlparse(source_url)
                                domain = parsed.netloc.lower()
                                if domain.startswith("www."):
                                    domain = domain[4:]
                                image_data['source_domain'] = domain
                            except Exception:
                                pass

                    # Only add if we have at least thumbnail URL
                    if image_data.get('thumbnail_url'):
                        images.append(image_data)

                except Exception as e:
                    logger.debug(f"Error parsing image element: {e}")
                    continue

            # Stop if we found images
            if images:
                break

        # Limit to reasonable number
        images = images[:20]

        if images:
            logger.info(f"Extracted {len(images)} image pack results")

        return images

    def _parse_knowledge_panel(self, soup: BeautifulSoup) -> Optional[Dict]:
        """
        Parse knowledge panel from SERP.

        Extracts knowledge panel data including:
        - Entity name and type
        - Description/subtitle
        - Website URL
        - Social media links
        - Key facts/attributes
        - Images

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            Knowledge panel dictionary or None if not present
        """
        # Multiple selectors for knowledge panel
        kp_selectors = [
            "div.kp-wholepage",       # Full page knowledge panel
            "div.knowledge-panel",    # Standard KP
            "div.kno-kp",             # KP container
            "div[data-attrid='kc:/']", # Knowledge card
            "div.osrp-blk",           # Organic search result panel
        ]

        kp_container = None
        for selector in kp_selectors:
            kp_container = soup.select_one(selector)
            if kp_container:
                break

        if not kp_container:
            return None

        panel_data = {}

        try:
            # Extract entity name (title)
            title_selectors = [
                "div[data-attrid='title'] span",
                "h2[data-attrid='title']",
                "div.kno-ecr-pt",       # Entity title
                "span.kno-fv",          # Feature value
                "div.qrShPb span",      # Title span
            ]
            for selector in title_selectors:
                title_elem = kp_container.select_one(selector)
                if title_elem:
                    panel_data['entity_name'] = title_elem.get_text(strip=True)
                    break

            # Extract entity type/subtitle
            subtitle_selectors = [
                "div[data-attrid='subtitle'] span",
                "div.kno-ecr-st",       # Entity subtitle
                "span.YhemCb",          # Subtitle span
            ]
            for selector in subtitle_selectors:
                subtitle_elem = kp_container.select_one(selector)
                if subtitle_elem:
                    panel_data['entity_type'] = subtitle_elem.get_text(strip=True)
                    break

            # Extract description
            desc_selectors = [
                "div[data-attrid='description'] span",
                "div.kno-rdesc span",   # Description span
                "span.kno-fv",          # Description value
                "div.LGOjhe",           # Description container
            ]
            for selector in desc_selectors:
                desc_elem = kp_container.select_one(selector)
                if desc_elem:
                    desc_text = desc_elem.get_text(strip=True)
                    if len(desc_text) > 20:  # Filter out short non-description text
                        panel_data['description'] = desc_text[:500]
                        break

            # Extract website URL
            website_elem = kp_container.select_one("a[data-attrid='visit_official_site']")
            if not website_elem:
                website_elem = kp_container.select_one("a.ab_button[href*='http']")
            if website_elem:
                panel_data['website'] = self._clean_url(website_elem.get("href", ""))

            # Extract social media links
            social_links = []
            social_container = kp_container.select_one("div[data-attrid='kc:/common/topic:social media presence']")
            if social_container:
                for link in social_container.select("a[href]"):
                    href = link.get("href", "")
                    if any(site in href for site in ['twitter', 'facebook', 'instagram', 'linkedin', 'youtube']):
                        social_links.append({
                            'platform': self._detect_social_platform(href),
                            'url': self._clean_url(href)
                        })
            if social_links:
                panel_data['social_links'] = social_links

            # Extract key facts/attributes
            facts = []
            fact_rows = kp_container.select("div.wDYxhc[data-attrid]")
            for row in fact_rows[:10]:  # Limit to 10 facts
                attrid = row.get("data-attrid", "")
                if attrid and "kc:/" in attrid:
                    # Extract fact name and value
                    fact_name = attrid.split(":")[-1].replace("_", " ").title()
                    fact_value_elem = row.select_one("span.LrzXr, span.kno-fv, span.hgKElc")
                    if fact_value_elem:
                        facts.append({
                            'name': fact_name,
                            'value': fact_value_elem.get_text(strip=True)[:200]
                        })
            if facts:
                panel_data['facts'] = facts

            # Extract image URLs
            images = []
            for img in kp_container.select("img.rISBZc, img.d6cvqb")[:5]:
                src = img.get("src") or img.get("data-src")
                if src and not src.startswith("data:"):
                    images.append(src)
            if images:
                panel_data['images'] = images

            # Check for Wikipedia link
            wiki_link = kp_container.select_one("a[href*='wikipedia.org']")
            if wiki_link:
                panel_data['wikipedia_url'] = wiki_link.get("href", "")

        except Exception as e:
            logger.debug(f"Error parsing knowledge panel: {e}")

        # Only return if we extracted meaningful data
        if panel_data.get('entity_name') or panel_data.get('description'):
            logger.info(f"Extracted knowledge panel for: {panel_data.get('entity_name', 'Unknown')}")
            return panel_data

        return None

    def _detect_social_platform(self, url: str) -> str:
        """Detect social media platform from URL."""
        url_lower = url.lower()
        if 'twitter.com' in url_lower or 'x.com' in url_lower:
            return 'Twitter/X'
        elif 'facebook.com' in url_lower:
            return 'Facebook'
        elif 'instagram.com' in url_lower:
            return 'Instagram'
        elif 'linkedin.com' in url_lower:
            return 'LinkedIn'
        elif 'youtube.com' in url_lower:
            return 'YouTube'
        elif 'tiktok.com' in url_lower:
            return 'TikTok'
        elif 'pinterest.com' in url_lower:
            return 'Pinterest'
        return 'Other'

    def _parse_ads_detailed(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parse paid advertisement results from SERP for competitive intelligence.

        Extracts ad data including:
        - Ad headline/title
        - Display URL
        - Landing page URL
        - Ad description/text
        - Ad extensions (sitelinks, callouts, phone)
        - Position (top/bottom)

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of ad dictionaries with comprehensive data
        """
        ads = []

        # Multiple selectors for ad containers (Google layout varies)
        ad_container_selectors = [
            "div.uEierd",              # Standard ad container
            "div[data-text-ad]",       # Text ad with data attribute
            "div.commercial-unit",     # Commercial unit
            "div.cu-container",        # Comparison unit container
            "li.ads-ad",               # List-style ads
            "div[data-hveid] div.pla-unit",  # Shopping ad
        ]

        # Find ad sections (top and bottom)
        top_ads_container = soup.select_one("div#tads, div[aria-label='Ads']")
        bottom_ads_container = soup.select_one("div#bottomads, div#tadsb")

        def extract_ads_from_container(container, position_type: str):
            if not container:
                return

            ad_elements = []
            for selector in ad_container_selectors:
                ad_elements = container.select(selector)
                if ad_elements:
                    break

            # Fallback: look for any elements with 'Ad' or 'Sponsored' label
            if not ad_elements:
                ad_elements = container.select("div:has(span:contains('Ad')), div:has(span:contains('Sponsored'))")

            for i, elem in enumerate(ad_elements, 1):
                try:
                    ad_data = {
                        'position': i,
                        'position_type': position_type,  # 'top' or 'bottom'
                    }

                    # Extract headline/title
                    headline_selectors = [
                        "div.CCgQ5",        # Ad headline container
                        "a div[role='heading']",  # Heading in link
                        "h3",               # Standard heading
                        "div.cfxYMc",       # Alternative headline
                        "a span.rNGBf",     # Headline span
                    ]
                    for selector in headline_selectors:
                        headline_elem = elem.select_one(selector)
                        if headline_elem:
                            ad_data['headline'] = headline_elem.get_text(strip=True)
                            break

                    # Extract landing page URL
                    link_elem = elem.select_one("a[href]")
                    if link_elem:
                        href = link_elem.get("href", "")
                        ad_data['landing_url'] = self._clean_url(href)

                        # Extract domain
                        try:
                            parsed = urlparse(ad_data['landing_url'])
                            domain = parsed.netloc.lower()
                            if domain.startswith("www."):
                                domain = domain[4:]
                            ad_data['domain'] = domain
                        except Exception:
                            pass

                    # Extract display URL (what user sees)
                    display_url_selectors = [
                        "span.qzEoUe",      # Display URL span
                        "cite.qLRx3b",      # Citation element
                        "div.eFM0qc cite",  # Cite in container
                        "span.x2VHCd",      # Alternative display URL
                    ]
                    for selector in display_url_selectors:
                        display_elem = elem.select_one(selector)
                        if display_elem:
                            ad_data['display_url'] = display_elem.get_text(strip=True)
                            break

                    # Extract description
                    desc_selectors = [
                        "div.MUxGbd",       # Description container
                        "div.yDYNvb",       # Alternative description
                        "span.r2fjmd",      # Description span
                        "div.Va3FIb",       # Description block
                    ]
                    for selector in desc_selectors:
                        desc_elem = elem.select_one(selector)
                        if desc_elem:
                            ad_data['description'] = desc_elem.get_text(strip=True)[:300]
                            break

                    # Extract ad extensions

                    # Sitelink extensions
                    sitelink_elems = elem.select("a.sJOJj, div.MhgNwc a")
                    if sitelink_elems:
                        ad_data['sitelinks'] = []
                        for sl in sitelink_elems[:6]:  # Max 6 sitelinks
                            sl_text = sl.get_text(strip=True)
                            sl_url = self._clean_url(sl.get("href", ""))
                            if sl_text and sl_url:
                                ad_data['sitelinks'].append({
                                    'text': sl_text,
                                    'url': sl_url
                                })

                    # Callout extensions
                    callout_elem = elem.select_one("div.bOeY0b, span.r2fjmd")
                    if callout_elem:
                        callout_text = callout_elem.get_text(strip=True)
                        if callout_text and '·' in callout_text:
                            ad_data['callouts'] = [c.strip() for c in callout_text.split('·')]

                    # Phone extension
                    phone_elem = elem.select_one("a[href^='tel:'], span.LrzXr")
                    if phone_elem:
                        if phone_elem.name == 'a':
                            ad_data['phone'] = phone_elem.get('href', '').replace('tel:', '')
                        else:
                            phone_text = phone_elem.get_text(strip=True)
                            if re.search(r'\d{3}.*\d{4}', phone_text):
                                ad_data['phone'] = phone_text

                    # Location extension
                    location_elem = elem.select_one("div.X3m4de, span.nMm4Ke")
                    if location_elem:
                        ad_data['location'] = location_elem.get_text(strip=True)

                    # Only add if we have at least headline and URL
                    if ad_data.get('headline') or ad_data.get('landing_url'):
                        ads.append(ad_data)

                except Exception as e:
                    logger.debug(f"Error parsing ad element: {e}")
                    continue

        # Extract from top ads
        extract_ads_from_container(top_ads_container, 'top')

        # Extract from bottom ads
        extract_ads_from_container(bottom_ads_container, 'bottom')

        if ads:
            logger.info(f"Extracted {len(ads)} ads ({sum(1 for a in ads if a.get('position_type') == 'top')} top, {sum(1 for a in ads if a.get('position_type') == 'bottom')} bottom)")

        return ads

    def _parse_news_results(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parse news/top stories results from SERP.

        Extracts news article data including:
        - Article title/headline
        - Source/publisher
        - Publication date/time
        - Article URL
        - Thumbnail image
        - Article snippet

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of news article dictionaries
        """
        news = []

        # Multiple selectors for news containers
        news_container_selectors = [
            "g-section-with-header[data-header-text*='Top stories']",
            "g-section-with-header[data-header-text*='News']",
            "div[data-attrid='TopStories']",
            "div.nChh6e",               # Top stories container
            "div.JJZKK",                # News carousel
            "div[jsname='WbKHeb']",     # News section
        ]

        news_section = None
        for selector in news_container_selectors:
            section = soup.select_one(selector)
            if section:
                news_section = section
                break

        if not news_section:
            return news

        # Find individual news items
        news_item_selectors = [
            "g-inner-card",             # News card
            "div.SoaBEf",               # News item
            "article",                  # Article element
            "div.WlydOe",               # Alternative news item
            "div.ftSUBd",               # News story
        ]

        news_items = []
        for selector in news_item_selectors:
            news_items = news_section.select(selector)
            if news_items:
                break

        seen_urls = set()
        for elem in news_items:
            try:
                news_data = {}

                # Extract article URL
                link_elem = elem.select_one("a[href]")
                if link_elem:
                    url = self._clean_url(link_elem.get("href", ""))
                    if url in seen_urls or "google.com/search" in url:
                        continue
                    seen_urls.add(url)
                    news_data['url'] = url

                    # Extract source domain
                    try:
                        parsed = urlparse(url)
                        domain = parsed.netloc.lower()
                        if domain.startswith("www."):
                            domain = domain[4:]
                        news_data['source_domain'] = domain
                    except Exception:
                        pass
                else:
                    continue

                # Extract title/headline
                title_selectors = [
                    "div.mCBkyc",       # News title
                    "div.n0jPhd",       # Alternative title
                    "h3",               # Heading
                    "div[role='heading']",  # Role heading
                    "span.CVA68e",      # Title span
                ]
                for selector in title_selectors:
                    title_elem = elem.select_one(selector)
                    if title_elem:
                        news_data['title'] = title_elem.get_text(strip=True)
                        break

                # Extract source/publisher name
                source_selectors = [
                    "div.CEMjEf span",  # Source span
                    "div.MgUUmf span",  # Alternative source
                    "cite",             # Citation element
                    "span.pcJO7e",      # Source name
                    "div.NUnG9d span",  # Publisher
                ]
                for selector in source_selectors:
                    source_elem = elem.select_one(selector)
                    if source_elem:
                        source_text = source_elem.get_text(strip=True)
                        if source_text and len(source_text) < 50:  # Avoid long text
                            news_data['source'] = source_text
                            break

                # Extract publication date/time
                date_selectors = [
                    "div.OSrXXb span",  # Date span
                    "span.r0bn4c",      # Timestamp
                    "time",             # Time element
                    "span.ZE0LJd",      # Date text
                    "div.FGlSad",       # Time ago
                ]
                for selector in date_selectors:
                    date_elem = elem.select_one(selector)
                    if date_elem:
                        date_text = date_elem.get_text(strip=True)
                        datetime_attr = date_elem.get("datetime", "")
                        if datetime_attr:
                            news_data['published_iso'] = datetime_attr
                        if date_text:
                            news_data['published_text'] = date_text
                        break

                # Extract snippet/description
                snippet_selectors = [
                    "div.GI74Re",       # Snippet
                    "div.VwiC3b",       # Description
                    "span.Y3v8qd",      # Snippet span
                ]
                for selector in snippet_selectors:
                    snippet_elem = elem.select_one(selector)
                    if snippet_elem:
                        news_data['snippet'] = snippet_elem.get_text(strip=True)[:200]
                        break

                # Extract thumbnail
                img_elem = elem.select_one("img[src], img[data-src]")
                if img_elem:
                    thumbnail = img_elem.get("src") or img_elem.get("data-src")
                    if thumbnail and not thumbnail.startswith("data:"):
                        news_data['thumbnail'] = thumbnail

                # Only add if we have URL and title
                if news_data.get('url') and news_data.get('title'):
                    news.append(news_data)

            except Exception as e:
                logger.debug(f"Error parsing news item: {e}")
                continue

        if news:
            logger.info(f"Extracted {len(news)} news/top stories results")

        return news

    def _parse_discussions(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parse discussions/forums results from SERP (Reddit, Quora, etc.).

        Extracts discussion data including:
        - Thread title
        - Platform (Reddit, Quora, etc.)
        - Subreddit/topic
        - Thread URL
        - Upvotes/engagement (if available)
        - Top response snippet

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of discussion dictionaries
        """
        discussions = []

        # Multiple selectors for discussions section
        discussion_container_selectors = [
            "g-section-with-header[data-header-text*='Discussions']",
            "g-section-with-header[data-header-text*='Forums']",
            "div[data-attrid='DiscussionsAndForums']",
            "div.GyAeWb",               # Discussions container
            "div[jsname='MZArnb']",     # Forums section
        ]

        discussion_section = None
        for selector in discussion_container_selectors:
            section = soup.select_one(selector)
            if section:
                discussion_section = section
                break

        # Also look for Reddit/Quora results in organic results
        # if no dedicated section found
        search_in_organic = discussion_section is None
        search_area = discussion_section if discussion_section else soup

        # Find discussion items
        discussion_item_selectors = [
            "div.GyAeWb div.g",         # Discussion in section
            "g-inner-card",             # Card format
            "div.WlydOe",               # Alternative container
            "div.N54PNb",               # Discussion item
        ]

        if search_in_organic:
            # Look for Reddit/Quora in organic results
            discussion_item_selectors = [
                "div.g:has(a[href*='reddit.com'])",
                "div.g:has(a[href*='quora.com'])",
                "div.g:has(a[href*='stackoverflow.com'])",
                "div.g:has(a[href*='stackexchange.com'])",
            ]

        discussion_items = []
        for selector in discussion_item_selectors:
            try:
                discussion_items = search_area.select(selector)
                if discussion_items:
                    break
            except Exception:
                continue

        seen_urls = set()
        for elem in discussion_items:
            try:
                disc_data = {}

                # Extract URL
                link_elem = elem.select_one("a[href]")
                if link_elem:
                    url = self._clean_url(link_elem.get("href", ""))
                    if url in seen_urls or "google.com/search" in url:
                        continue
                    seen_urls.add(url)
                    disc_data['url'] = url

                    # Determine platform
                    url_lower = url.lower()
                    if 'reddit.com' in url_lower:
                        disc_data['platform'] = 'Reddit'
                        # Extract subreddit
                        subreddit_match = re.search(r'/r/([^/]+)', url)
                        if subreddit_match:
                            disc_data['subreddit'] = subreddit_match.group(1)
                    elif 'quora.com' in url_lower:
                        disc_data['platform'] = 'Quora'
                    elif 'stackoverflow.com' in url_lower:
                        disc_data['platform'] = 'Stack Overflow'
                    elif 'stackexchange.com' in url_lower:
                        disc_data['platform'] = 'Stack Exchange'
                    else:
                        disc_data['platform'] = 'Forum'
                else:
                    continue

                # Extract title
                title_selectors = [
                    "h3",               # Heading
                    "div.mCBkyc",       # Title container
                    "div[role='heading']",  # Role heading
                    "span.CVA68e",      # Title span
                ]
                for selector in title_selectors:
                    title_elem = elem.select_one(selector)
                    if title_elem:
                        disc_data['title'] = title_elem.get_text(strip=True)
                        break

                # Extract post date
                date_selectors = [
                    "span.LEwnzc",      # Date span
                    "span.f",           # Date container
                    "time",             # Time element
                ]
                for selector in date_selectors:
                    date_elem = elem.select_one(selector)
                    if date_elem:
                        disc_data['posted_date'] = date_elem.get_text(strip=True)
                        break

                # Extract engagement metrics (upvotes, comments)
                engagement_selectors = [
                    "span.FxLDp",       # Engagement text
                    "span.oqSTJd",      # Stats
                    "div.pcJO7e",       # Info container
                ]
                for selector in engagement_selectors:
                    eng_elems = elem.select(selector)
                    for eng_elem in eng_elems:
                        text = eng_elem.get_text(strip=True).lower()
                        # Parse upvotes
                        upvote_match = re.search(r'([\d,.]+)\s*(upvote|point|vote)', text)
                        if upvote_match:
                            disc_data['upvotes'] = upvote_match.group(1)
                        # Parse comments
                        comment_match = re.search(r'([\d,.]+)\s*comment', text)
                        if comment_match:
                            disc_data['comments'] = comment_match.group(1)

                # Extract snippet/preview
                snippet_selectors = [
                    "div.VwiC3b",       # Description
                    "span.aCOpRe",      # Snippet
                    "div.IsZvec",       # Content preview
                ]
                for selector in snippet_selectors:
                    snippet_elem = elem.select_one(selector)
                    if snippet_elem:
                        disc_data['snippet'] = snippet_elem.get_text(strip=True)[:250]
                        break

                # Only add if we have URL and title
                if disc_data.get('url') and disc_data.get('title'):
                    discussions.append(disc_data)

            except Exception as e:
                logger.debug(f"Error parsing discussion item: {e}")
                continue

        if discussions:
            logger.info(f"Extracted {len(discussions)} discussion/forum results")

        return discussions

    def _parse_refine_chips(self, soup: BeautifulSoup) -> List[str]:
        """
        Parse search refinement chips/suggestions from SERP.

        These are the clickable chips that appear near the search box
        to help refine/narrow the search (e.g., "near me", "reviews", etc.)

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of refinement chip text strings
        """
        chips = []

        # Multiple selectors for refinement chips
        chip_container_selectors = [
            "div.YmvwI",                # Chip container
            "div[jsname='oCHwsc']",     # Refinement section
            "div.AaVjTc",               # Alternative chips container
            "g-scrolling-carousel[data-hveid]",  # Scrolling chips
            "div.crJ18e",               # Chips row
        ]

        chip_container = None
        for selector in chip_container_selectors:
            container = soup.select_one(selector)
            if container:
                chip_container = container
                break

        if not chip_container:
            # Try finding chips anywhere on page
            chip_container = soup

        # Find individual chips
        chip_selectors = [
            "div.YmvwI a",              # Chip links in container
            "a.T3FoJb",                 # Chip link
            "div.kno-fb-ctx",           # Knowledge chip
            "a.k8XOCe",                 # Alternative chip link
            "span.z4P7Tc",              # Chip text span
        ]

        seen_chips = set()
        for selector in chip_selectors:
            chip_elems = chip_container.select(selector)

            for elem in chip_elems:
                try:
                    chip_text = elem.get_text(strip=True)

                    # Filter out invalid chips
                    if not chip_text or len(chip_text) < 2:
                        continue
                    if chip_text.lower() in seen_chips:
                        continue
                    if len(chip_text) > 50:  # Too long, not a chip
                        continue

                    seen_chips.add(chip_text.lower())
                    chips.append(chip_text)

                except Exception as e:
                    logger.debug(f"Error parsing chip: {e}")
                    continue

            # Stop if we found chips
            if chips:
                break

        if chips:
            logger.info(f"Extracted {len(chips)} search refinement chips")

        return chips[:15]  # Limit to 15 chips

    def _extract_total_results(self, soup: BeautifulSoup) -> Optional[int]:
        """
        Extract total results count from SERP.

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            int: Total results count or None
        """
        try:
            # Look for result stats
            stats_elem = soup.select_one("div#result-stats")
            if stats_elem:
                text = stats_elem.get_text()
                # Extract number from "About X results"
                match = re.search(r"([\d,]+)\s+results", text)
                if match:
                    return int(match.group(1).replace(",", ""))
        except Exception:
            pass

        return None

    def _parse_ai_overview(self, soup: BeautifulSoup) -> Optional[Dict]:
        """
        Extract AI Overview / SGE (Search Generative Experience) content.

        Google's AI Overview appears at the top of many SERPs with AI-generated
        summaries. This is valuable competitive intelligence data.

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            Dict with AI overview content or None if not present
        """
        # Multiple selectors for AI Overview (Google changes these frequently)
        ai_selectors = [
            "div[data-attrid='ai-overview']",
            "div.kp-blk.c2xzTb",  # AI overview container
            "div[jsname='WbKHeb']",  # SGE container
            "div.M8OgIe",  # AI answer block
            "div.wDYxhc[data-md='61']",  # Another AI overview variant
            "div[data-sgrd]",  # SGE response container
        ]

        ai_container = None
        for selector in ai_selectors:
            ai_container = soup.select_one(selector)
            if ai_container:
                break

        if not ai_container:
            return None

        try:
            ai_data = {
                "has_ai_overview": True,
                "type": "ai_overview",
                "content": "",
                "sources": [],
                "topics": [],
                "follow_up_questions": [],
            }

            # Extract main content
            content_elem = ai_container.select_one("div.kno-rdesc, div.wDYxhc, span.hgKElc")
            if content_elem:
                ai_data["content"] = content_elem.get_text(strip=True)[:2000]

            # Extract source citations
            source_links = ai_container.select("a[href*='://']")
            for link in source_links[:10]:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if href and not href.startswith("/search"):
                    ai_data["sources"].append({
                        "url": self._clean_url(href),
                        "text": text[:100],
                    })

            # Extract follow-up question suggestions
            follow_ups = ai_container.select("div.related-question-pair, div[data-q]")
            for fu in follow_ups[:5]:
                q_text = fu.get_text(strip=True)
                if q_text:
                    ai_data["follow_up_questions"].append(q_text[:200])

            # Extract key topics/entities mentioned
            bold_terms = ai_container.select("b, strong")
            for term in bold_terms[:15]:
                term_text = term.get_text(strip=True)
                if term_text and len(term_text) < 50:
                    ai_data["topics"].append(term_text)

            logger.info("Extracted AI Overview content")
            return ai_data

        except Exception as e:
            logger.debug(f"Error parsing AI overview: {e}")
            return None

    def _parse_answer_boxes(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Extract various answer box types from SERP.

        Answer boxes include:
        - Direct answers (calculator, weather, conversions)
        - Definition boxes
        - List answers
        - Table answers
        - How-to steps

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of answer box dictionaries
        """
        answer_boxes = []

        # Answer box selectors by type
        answer_configs = [
            {
                "type": "direct_answer",
                "selectors": ["div.ULSxyf", "div.vXQmIe", "div.ayqGOc"],
            },
            {
                "type": "definition",
                "selectors": ["div.lr_dct_sf", "div.sdgPJe", "div[data-tts='answers']"],
            },
            {
                "type": "calculator",
                "selectors": ["div.tyYmIf", "div.card-section[data-calculator]"],
            },
            {
                "type": "weather",
                "selectors": ["div.wob_w", "div[data-wob-di]"],
            },
            {
                "type": "conversion",
                "selectors": ["div.vk_c", "div.card-section[data-unit-converter]"],
            },
            {
                "type": "list_answer",
                "selectors": ["div.di3YZe", "div.ifM9O"],
            },
            {
                "type": "table_answer",
                "selectors": ["div.webanswers-webanswers_table__webanswers-table", "table.zXOYe"],
            },
        ]

        for config in answer_configs:
            for selector in config["selectors"]:
                elem = soup.select_one(selector)
                if elem:
                    try:
                        answer_box = {
                            "type": config["type"],
                            "content": elem.get_text(strip=True)[:500],
                            "has_source": bool(elem.select_one("a[href]")),
                        }

                        # Extract source if present
                        source_link = elem.select_one("a[href*='://']")
                        if source_link:
                            answer_box["source_url"] = self._clean_url(source_link.get("href", ""))
                            answer_box["source_text"] = source_link.get_text(strip=True)[:100]

                        answer_boxes.append(answer_box)
                        break
                    except Exception as e:
                        logger.debug(f"Error parsing {config['type']} answer box: {e}")
                        continue

        if answer_boxes:
            logger.info(f"Extracted {len(answer_boxes)} answer boxes")

        return answer_boxes

    def _calculate_serp_complexity(self, soup: BeautifulSoup, features: List[str]) -> float:
        """
        Calculate a SERP complexity score (0-100).

        Higher scores indicate more competitive/complex SERPs with many features
        fighting for attention. This helps prioritize SEO opportunities.

        Factors:
        - Number of SERP features present
        - Presence of ads
        - Presence of AI overview
        - Number of rich results
        - Local pack presence
        - Knowledge panel presence

        Args:
            soup: BeautifulSoup object of SERP
            features: List of detected SERP features

        Returns:
            float: Complexity score 0-100
        """
        score = 0

        # Base score for number of features (0-30 points)
        feature_score = min(len(features) * 3, 30)
        score += feature_score

        # AI Overview present (15 points) - harder to rank above
        if "ai_overview" in features or soup.select_one("div[data-sgrd], div[data-attrid='ai-overview']"):
            score += 15

        # Ads present (10 points for top, 5 for bottom)
        if soup.select_one("div#tads"):
            score += 10
        if soup.select_one("div#bottomads"):
            score += 5

        # Knowledge panel (10 points) - reduces organic click share
        if "knowledge_panel" in features:
            score += 10

        # Local pack (10 points)
        if "local_pack" in features:
            score += 10

        # Featured snippet (8 points)
        if "featured_snippet" in features:
            score += 8

        # Shopping results (5 points)
        if "shopping_results" in features:
            score += 5

        # Video carousel (5 points)
        if "video_carousel" in features:
            score += 5

        # Image carousel (3 points)
        if "image_carousel" in features:
            score += 3

        # PAA questions (3 points)
        if "people_also_ask" in features:
            score += 3

        # Rich snippets with ratings (2 points per, max 6)
        rating_count = len(soup.select("span.z3HNkc, span.yi40Hd")[:3])
        score += rating_count * 2

        return min(score, 100)

    def _detect_query_intent(self, query: str, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Detect the likely search intent from query and SERP signals.

        Intent types:
        - Informational: seeking information/answers
        - Navigational: looking for specific site
        - Transactional: intent to purchase
        - Commercial investigation: comparing products/services
        - Local: seeking local business

        Args:
            query: The search query
            soup: BeautifulSoup object of SERP

        Returns:
            Dict with intent signals
        """
        query_lower = query.lower()
        intent_signals = {
            "primary_intent": "informational",  # default
            "confidence": 0.5,
            "signals": [],
            "modifiers": [],
        }

        # Intent modifier keywords
        transactional_keywords = ["buy", "price", "cheap", "deal", "discount", "order", "purchase", "cost", "hire", "book", "schedule"]
        informational_keywords = ["how", "what", "why", "when", "guide", "tutorial", "tips", "best way", "difference"]
        commercial_keywords = ["best", "top", "review", "comparison", "vs", "versus", "alternative"]
        navigational_keywords = ["login", "sign in", "official", "website", "contact", "phone number"]
        local_keywords = ["near me", "in", "local", "nearby", "closest"]

        # Check query for intent keywords
        for kw in transactional_keywords:
            if kw in query_lower:
                intent_signals["modifiers"].append(f"transactional:{kw}")

        for kw in informational_keywords:
            if kw in query_lower:
                intent_signals["modifiers"].append(f"informational:{kw}")

        for kw in commercial_keywords:
            if kw in query_lower:
                intent_signals["modifiers"].append(f"commercial:{kw}")

        for kw in navigational_keywords:
            if kw in query_lower:
                intent_signals["modifiers"].append(f"navigational:{kw}")

        for kw in local_keywords:
            if kw in query_lower:
                intent_signals["modifiers"].append(f"local:{kw}")

        # SERP feature signals
        if soup.select_one("div.VkpGBb"):  # Local pack
            intent_signals["signals"].append("local_pack_present")
            intent_signals["primary_intent"] = "local"
            intent_signals["confidence"] = 0.8

        if soup.select_one("div.pla-unit"):  # Shopping results
            intent_signals["signals"].append("shopping_results_present")
            if "transactional" not in intent_signals.get("primary_intent", ""):
                intent_signals["primary_intent"] = "transactional"
                intent_signals["confidence"] = 0.75

        if soup.select_one("div.kp-wholepage"):  # Knowledge panel
            intent_signals["signals"].append("knowledge_panel_present")
            if not intent_signals["modifiers"]:
                intent_signals["primary_intent"] = "informational"
                intent_signals["confidence"] = 0.7

        # PAA suggests informational
        if soup.select("div.related-question-pair"):
            intent_signals["signals"].append("paa_present")
            if intent_signals["primary_intent"] == "informational":
                intent_signals["confidence"] = min(intent_signals["confidence"] + 0.1, 1.0)

        # Determine primary intent from modifiers
        modifier_counts = {}
        for mod in intent_signals["modifiers"]:
            intent_type = mod.split(":")[0]
            modifier_counts[intent_type] = modifier_counts.get(intent_type, 0) + 1

        if modifier_counts:
            primary = max(modifier_counts, key=modifier_counts.get)
            intent_signals["primary_intent"] = primary
            intent_signals["confidence"] = min(0.5 + (modifier_counts[primary] * 0.15), 0.95)

        return intent_signals

    def _track_feature_ordering(self, soup: BeautifulSoup) -> List[str]:
        """
        Track the order in which SERP features appear on the page.

        The order matters for CTR - features above the fold get more attention.
        This tracks vertical ordering of major SERP components.

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of feature names in order of appearance
        """
        feature_order = []

        # Define feature selectors in a predictable structure
        feature_checks = [
            ("top_ads", "div#tads"),
            ("ai_overview", "div[data-sgrd], div[data-attrid='ai-overview']"),
            ("featured_snippet", "div.xpdopen, div[data-attrid='FeaturedSnippet']"),
            ("knowledge_panel", "div.kp-wholepage"),
            ("local_pack", "div.VkpGBb"),
            ("image_pack", "div.islrc, g-scrolling-carousel"),
            ("video_carousel", "div.YpRj3e"),
            ("people_also_ask", "div.related-question-pair"),
            ("organic_results", "div.g"),
            ("news_results", "div.nChh6e"),
            ("discussions", "g-section-with-header[data-header-text*='Discussions']"),
            ("related_searches", "div#brs, div.AJLUJb"),
            ("bottom_ads", "div#bottomads"),
        ]

        # Get all elements and their positions
        positioned_features = []
        for feature_name, selector in feature_checks:
            try:
                # Handle multiple selectors separated by comma
                for sel in selector.split(", "):
                    elem = soup.select_one(sel.strip())
                    if elem:
                        # Use element's position in document as proxy for vertical position
                        # (actual pixel position not available without rendering)
                        positioned_features.append((feature_name, str(elem)[:50]))
                        break
            except Exception:
                continue

        # Extract feature names maintaining order found
        seen = set()
        for feature_name, _ in positioned_features:
            if feature_name not in seen:
                feature_order.append(feature_name)
                seen.add(feature_name)

        return feature_order

    def _detect_schema_markup(self, soup: BeautifulSoup) -> List[str]:
        """
        Detect schema.org markup types present in SERP results.

        Schema markup can indicate:
        - LocalBusiness (local results)
        - Product (shopping)
        - Review (ratings)
        - Article (news)
        - FAQ (PAA-like)
        - HowTo (step results)

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of detected schema types
        """
        schema_types = []

        # Look for schema indicators in SERP
        schema_indicators = {
            "LocalBusiness": [
                "div.VkpGBb",  # Local pack
                "span.LrzXr",  # Address
            ],
            "Product": [
                "div.pla-unit",  # Shopping
                "span.HRLxBb",  # Price
            ],
            "Review": [
                "span.z3HNkc",  # Star rating
                "span.fG8Fp",  # Review count
            ],
            "Article": [
                "div.nChh6e",  # News
                "div.WlydOe",  # Article result
            ],
            "FAQ": [
                "div.related-question-pair",  # PAA
                "div.wQiwMc",  # FAQ blocks
            ],
            "HowTo": [
                "div.xpc",  # How-to steps
                "ol.X7NTVe",  # Ordered steps
            ],
            "Event": [
                "div[data-attrid='kc:/event']",
                "div.PcP8Tc",  # Event listing
            ],
            "Recipe": [
                "div.YwonT",  # Recipe card
                "span.wHYlTd",  # Cook time
            ],
            "Video": [
                "div.YpRj3e",  # Video result
                "div.RzdJxc",  # Video thumbnail
            ],
        }

        for schema_type, selectors in schema_indicators.items():
            for selector in selectors:
                if soup.select_one(selector):
                    if schema_type not in schema_types:
                        schema_types.append(schema_type)
                    break

        if schema_types:
            logger.info(f"Detected schema markup types: {schema_types}")

        return schema_types

    def _calculate_layout_metrics(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Calculate layout-related metrics for SERP analysis.

        Metrics include:
        - Estimated above-fold content
        - Number of ad slots
        - First organic position estimate
        - Result density

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            Dict with layout metrics
        """
        metrics = {
            "top_ads_count": 0,
            "bottom_ads_count": 0,
            "organic_count": 0,
            "first_organic_position": 1,
            "above_fold_features": [],
            "results_density": "normal",
        }

        # Count ads
        top_ads = soup.select("div#tads > div")
        metrics["top_ads_count"] = len(top_ads)

        bottom_ads = soup.select("div#bottomads > div")
        metrics["bottom_ads_count"] = len(bottom_ads)

        # Count organic results
        organic = soup.select("div.g:not([data-ad-query])")
        metrics["organic_count"] = len(organic)

        # Estimate first organic position (after ads and features)
        position = 1
        if metrics["top_ads_count"] > 0:
            position += metrics["top_ads_count"]

        # Check for features that push organic down
        if soup.select_one("div[data-sgrd], div[data-attrid='ai-overview']"):
            position += 1
            metrics["above_fold_features"].append("ai_overview")

        if soup.select_one("div.xpdopen"):
            position += 1
            metrics["above_fold_features"].append("featured_snippet")

        if soup.select_one("div.VkpGBb"):
            position += 1
            metrics["above_fold_features"].append("local_pack")

        metrics["first_organic_position"] = position

        # Estimate result density
        total_elements = len(top_ads) + metrics["organic_count"]
        if soup.select_one("div.kp-wholepage"):  # Knowledge panel takes space
            metrics["results_density"] = "low"
        elif total_elements > 12:
            metrics["results_density"] = "high"
        else:
            metrics["results_density"] = "normal"

        return metrics

    def _detect_serp_features(self, soup: BeautifulSoup) -> List[str]:
        """
        Detect and flag SERP features present on the page.

        Detects:
        - Featured snippets
        - Knowledge panels
        - Knowledge cards
        - Local packs / map results
        - Image carousels / packs
        - Video carousels
        - News results
        - Shopping results
        - People Also Ask
        - Related searches
        - Site links
        - Reviews/ratings

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of detected feature names
        """
        features = []

        # Featured snippet detection
        featured_selectors = [
            "div.xpdopen",              # Classic featured snippet
            "div.kp-blk",               # Knowledge panel variant
            "div[data-attrid='FeaturedSnippet']",
            "div.IZ6rdc",               # Answer box
            "div.kno-rdesc",            # Quick answer
        ]
        for selector in featured_selectors:
            if soup.select_one(selector):
                features.append("featured_snippet")
                break

        # Knowledge panel / card
        knowledge_selectors = [
            "div.kp-wholepage",         # Full knowledge panel
            "div.knowledge-panel",      # Knowledge panel container
            "div.kno-kp",               # KP container
            "div[data-attrid='kc:/']",  # Knowledge card
        ]
        for selector in knowledge_selectors:
            if soup.select_one(selector):
                features.append("knowledge_panel")
                break

        # Local pack / map results
        if soup.select_one("div.VkpGBb") or soup.select_one("div[data-attrid='kc:/local:']"):
            features.append("local_pack")

        # Image carousel / pack
        image_selectors = [
            "div.islrc",                # Image results container
            "g-scrolling-carousel",     # Image carousel
            "div[data-tray]",           # Image tray
        ]
        for selector in image_selectors:
            if soup.select_one(selector):
                features.append("image_carousel")
                break

        # Video carousel
        video_selectors = [
            "g-section-with-header[data-header-text*='Videos']",
            "div[data-attrid='VideoCarousel']",
            "div.YpRj3e",  # Video result container
        ]
        for selector in video_selectors:
            if soup.select_one(selector):
                features.append("video_carousel")
                break

        # News results / Top stories
        news_selectors = [
            "div.nChh6e",               # Top stories
            "div[data-attrid='TopStories']",
            "g-section-with-header[data-header-text*='Top stories']",
            "g-section-with-header[data-header-text*='News']",
        ]
        for selector in news_selectors:
            if soup.select_one(selector):
                features.append("news_results")
                break

        # Ads detection
        ads_selectors = [
            "div#tads",                 # Top ads
            "div#bottomads",            # Bottom ads
            "div.uEierd",               # Ad container
            "div[data-text-ad]",        # Text ad
        ]
        for selector in ads_selectors:
            if soup.select_one(selector):
                features.append("ads")
                break

        # Discussions / Forums
        discussion_selectors = [
            "g-section-with-header[data-header-text*='Discussions']",
            "g-section-with-header[data-header-text*='Forums']",
            "div[data-attrid='DiscussionsAndForums']",
            "div.GyAeWb",
        ]
        for selector in discussion_selectors:
            if soup.select_one(selector):
                features.append("discussions")
                break

        # Shopping results / product listings
        shopping_selectors = [
            "div.pla-unit",             # Shopping ad
            "div[data-attrid='ShoppingResults']",
            "div.cu-container",         # Comparison unit
        ]
        for selector in shopping_selectors:
            if soup.select_one(selector):
                features.append("shopping_results")
                break

        # People Also Ask
        paa_selectors = [
            "div.related-question-pair",
            "div[jsname='yEVEE']",
            "div.cbphWd",
        ]
        for selector in paa_selectors:
            if soup.select(selector):
                features.append("people_also_ask")
                break

        # Related searches
        if soup.select_one("div#brs") or soup.select_one("div.AJLUJb"):
            features.append("related_searches")

        # Site links (multiple links from same domain)
        if soup.select("div.usJj9c"):  # Sitelinks container
            features.append("sitelinks")

        # Reviews / ratings
        if soup.select_one("span.z3HNkc") or soup.select_one("div.fG8Fp"):
            features.append("reviews_ratings")

        # Twitter carousel / social media
        if soup.select_one("g-section-with-header[data-header-text*='Twitter']"):
            features.append("twitter_carousel")

        return list(set(features))  # Remove duplicates

    def parse(self, html: str, query: str, location: Optional[str] = None) -> SerpSnapshot:
        """
        Parse a Google SERP page.

        Args:
            html: Raw HTML of the SERP
            query: Search query that was used
            location: Location context (if any)

        Returns:
            SerpSnapshot: Parsed SERP data
        """
        soup = BeautifulSoup(html, "html.parser")

        # Initialize snapshot
        snapshot = SerpSnapshot(
            query=query,
            location=location,
        )

        # Extract total results
        snapshot.total_results = self._extract_total_results(soup)

        # Parse organic results
        position = 1
        seen_urls = set()

        for selector in self.organic_selectors:
            result_elements = soup.select(selector)

            for elem in result_elements:
                result = self._parse_organic_result(elem, position)

                if result and result.url not in seen_urls:
                    seen_urls.add(result.url)
                    snapshot.results.append(result)
                    position += 1

        # Parse additional SERP features
        snapshot.local_pack = self._parse_local_pack(soup)
        snapshot.people_also_ask = self._parse_people_also_ask(soup)
        snapshot.related_searches = self._parse_related_searches(soup)

        # Parse sitelinks
        snapshot.sitelinks = self._parse_sitelinks(soup, snapshot.results)

        # Parse video results
        snapshot.video_results = self._parse_video_results(soup)

        # Parse image pack
        snapshot.image_pack = self._parse_image_pack(soup)

        # Parse knowledge panel
        snapshot.knowledge_panel = self._parse_knowledge_panel(soup)

        # Parse ads (competitive intelligence)
        snapshot.ads = self._parse_ads_detailed(soup)

        # Parse news/top stories
        snapshot.news_results = self._parse_news_results(soup)

        # Parse discussions/forums
        snapshot.discussions = self._parse_discussions(soup)

        # Parse refinement chips
        snapshot.refine_chips = self._parse_refine_chips(soup)

        # Detect SERP features
        snapshot.serp_features = self._detect_serp_features(soup)

        # NEW: Quality data extraction
        # AI Overview / SGE
        snapshot.ai_overview = self._parse_ai_overview(soup)
        if snapshot.ai_overview:
            snapshot.serp_features.append("ai_overview")

        # Answer boxes (calculator, definitions, etc.)
        snapshot.answer_boxes = self._parse_answer_boxes(soup)

        # Query intent detection
        snapshot.intent_signals = self._detect_query_intent(query, soup)

        # Feature ordering (above-fold position tracking)
        snapshot.feature_ordering = self._track_feature_ordering(soup)

        # Schema markup detection
        snapshot.schema_markup_detected = self._detect_schema_markup(soup)

        # Layout metrics (ad counts, first organic position, etc.)
        snapshot.layout_metrics = self._calculate_layout_metrics(soup)

        # SERP complexity score (0-100)
        snapshot.serp_complexity_score = self._calculate_serp_complexity(soup, snapshot.serp_features)

        logger.info(
            f"Parsed SERP for '{query}': "
            f"{len(snapshot.results)} organic, "
            f"{len(snapshot.local_pack)} local, "
            f"{len(snapshot.people_also_ask)} PAA, "
            f"{len(snapshot.sitelinks)} sitelink groups, "
            f"{len(snapshot.video_results)} videos, "
            f"{len(snapshot.image_pack)} images, "
            f"{'KP' if snapshot.knowledge_panel else 'no KP'}, "
            f"{len(snapshot.ads)} ads, "
            f"{len(snapshot.news_results)} news, "
            f"{len(snapshot.discussions)} discussions, "
            f"{len(snapshot.refine_chips)} chips, "
            f"{len(snapshot.serp_features)} features, "
            f"{'AI' if snapshot.ai_overview else 'no AI'}, "
            f"complexity={snapshot.serp_complexity_score:.0f}, "
            f"intent={snapshot.intent_signals.get('primary_intent', 'unknown')}"
        )

        return snapshot


# Module-level singleton
_serp_parser_instance = None


def get_serp_parser() -> SerpParser:
    """Get or create the singleton SerpParser instance."""
    global _serp_parser_instance

    if _serp_parser_instance is None:
        _serp_parser_instance = SerpParser()

    return _serp_parser_instance


def main():
    """Demo: Test SERP parsing with sample HTML."""
    logger.info("=" * 60)
    logger.info("SERP Parser Demo")
    logger.info("=" * 60)
    logger.info("")

    parser = get_serp_parser()

    # Sample minimal SERP HTML for testing
    sample_html = """
    <html>
    <body>
        <div id="result-stats">About 1,234,567 results</div>
        <div class="g">
            <div class="yuRUbf">
                <a href="https://example.com/page1">
                    <h3>Example Page 1 - Great Content</h3>
                </a>
            </div>
            <div class="VwiC3b">This is the description for example page 1.</div>
        </div>
        <div class="g">
            <div class="yuRUbf">
                <a href="https://another-site.com/info">
                    <h3>Another Site - Information Page</h3>
                </a>
            </div>
            <div class="VwiC3b">Description for the second result.</div>
        </div>
        <div class="g">
            <div class="yuRUbf">
                <a href="https://third-example.org/">
                    <h3>Third Example Website</h3>
                </a>
            </div>
            <div class="VwiC3b">Third result description goes here.</div>
        </div>
    </body>
    </html>
    """

    # Parse sample SERP
    snapshot = parser.parse(sample_html, query="test query", location="Austin, TX")

    # Display results
    logger.info(f"Query: {snapshot.query}")
    logger.info(f"Location: {snapshot.location}")
    logger.info(f"Total results: {snapshot.total_results}")
    logger.info("")
    logger.info("Organic Results:")

    for result in snapshot.results:
        logger.info(f"  {result.position}. {result.title}")
        logger.info(f"     URL: {result.url}")
        logger.info(f"     Domain: {result.domain}")
        logger.info(f"     Description: {result.description[:50]}...")
        logger.info("")

    logger.info("=" * 60)
    logger.info("Demo complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
