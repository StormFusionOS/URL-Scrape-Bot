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

            return result

        except Exception as e:
            logger.warning(f"Error parsing organic result at position {position}: {e}")
            return None

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
        Parse local pack / map results.

        Args:
            soup: BeautifulSoup object of SERP

        Returns:
            List of local business dictionaries
        """
        local_results = []

        # Look for local pack container
        local_container = soup.select_one("div.VkpGBb") or soup.select_one("div[data-attrid='kc:/local:']")

        if not local_container:
            return local_results

        # Find individual local listings
        listings = local_container.select("div.VkpGBb")

        for i, listing in enumerate(listings, 1):
            try:
                # Extract business name
                name_elem = listing.select_one("div.dbg0pd")
                name = name_elem.get_text(strip=True) if name_elem else ""

                # Extract rating
                rating_elem = listing.select_one("span.yi40Hd")
                rating = rating_elem.get_text(strip=True) if rating_elem else ""

                # Extract address/info
                info_elem = listing.select_one("div.rllt__details")
                info = info_elem.get_text(" ", strip=True) if info_elem else ""

                if name:
                    local_results.append({
                        "position": i,
                        "name": name,
                        "rating": rating,
                        "info": info,
                    })
            except Exception as e:
                logger.warning(f"Error parsing local result: {e}")
                continue

        return local_results

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

        # News results
        news_selectors = [
            "div.nChh6e",               # Top stories
            "div[data-attrid='TopStories']",
            "g-section-with-header[data-header-text*='Top stories']",
        ]
        for selector in news_selectors:
            if soup.select_one(selector):
                features.append("news_results")
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

        # Detect SERP features
        snapshot.serp_features = self._detect_serp_features(soup)

        logger.info(
            f"Parsed SERP for '{query}': "
            f"{len(snapshot.results)} organic, "
            f"{len(snapshot.local_pack)} local, "
            f"{len(snapshot.people_also_ask)} PAA, "
            f"{len(snapshot.serp_features)} features"
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
