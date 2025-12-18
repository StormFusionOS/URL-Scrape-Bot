"""
Directory Adapters for Citation Crawler

Provides structured parsing for specific business directories by reusing
existing robust parsers (YP, Yelp, Google) instead of naive text matching.

The adapter pattern allows:
- search(business_name, location) -> List[Dict] candidates
- parse_listing(html) -> Dict structured listing info
- match_score(listing, target_business) -> float confidence score

This eliminates false positives and provides complete NAP + metadata extraction.
"""

import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus

from runner.logging_setup import get_logger

logger = get_logger("directory_adapters")


@dataclass
class DirectoryListing:
    """
    Structured listing data extracted from a directory.

    Provides full NAP + metadata for accurate matching and storage.
    """
    # Core NAP fields
    name: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    website: str = ""

    # Extended metadata
    rating: Optional[float] = None
    review_count: int = 0
    categories: List[str] = field(default_factory=list)
    hours: Dict[str, str] = field(default_factory=dict)

    # Listing info
    listing_url: str = ""
    profile_url: str = ""
    is_claimed: bool = False
    is_sponsored: bool = False

    # Parse metadata
    confidence: float = 0.0
    source_directory: str = ""
    parse_errors: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @property
    def has_valid_nap(self) -> bool:
        """Check if listing has minimum NAP info."""
        return bool(self.name and (self.phone or self.address))

    @property
    def completeness_score(self) -> float:
        """
        Calculate how complete the listing data is (0-1).

        Weights:
        - Name: 0.2
        - Phone: 0.2
        - Address: 0.15
        - City/State: 0.1
        - Website: 0.1
        - Rating: 0.1
        - Reviews: 0.1
        - Categories: 0.05
        """
        score = 0.0

        if self.name:
            score += 0.2
        if self.phone:
            score += 0.2
        if self.address:
            score += 0.15
        if self.city or self.state:
            score += 0.1
        if self.website:
            score += 0.1
        if self.rating is not None:
            score += 0.1
        if self.review_count > 0:
            score += 0.1
        if self.categories:
            score += 0.05

        return score


class DirectoryAdapter(ABC):
    """
    Abstract base class for directory-specific parsing adapters.

    Each adapter knows how to:
    1. Build search URLs for its directory
    2. Parse search results to extract listing candidates
    3. Parse individual listing pages for full details
    4. Calculate match confidence against a target business
    """

    directory_name: str = "generic"
    base_url: str = ""

    @abstractmethod
    def build_search_url(self, business_name: str, location: str, zip_code: str = "") -> str:
        """
        Build the search URL for this directory.

        Args:
            business_name: Name to search for
            location: City, state or full location string
            zip_code: Optional zip code

        Returns:
            Complete search URL
        """
        pass

    @abstractmethod
    def parse_search_results(self, html: str) -> List[DirectoryListing]:
        """
        Parse search results page to extract listing candidates.

        Args:
            html: Search results page HTML

        Returns:
            List of DirectoryListing objects (may be partial data)
        """
        pass

    @abstractmethod
    def parse_listing_page(self, html: str) -> Optional[DirectoryListing]:
        """
        Parse a single listing page for full details.

        Args:
            html: Listing page HTML

        Returns:
            DirectoryListing with complete data, or None if parse failed
        """
        pass

    def calculate_match_score(
        self,
        listing: DirectoryListing,
        target_name: str,
        target_phone: str = "",
        target_address: str = "",
        target_city: str = "",
        target_state: str = "",
    ) -> Tuple[float, Dict[str, bool]]:
        """
        Calculate how well a listing matches the target business.

        Args:
            listing: Parsed listing data
            target_*: Target business info to match against

        Returns:
            Tuple of (overall_score, field_matches)
            where field_matches is dict like {"name": True, "phone": False, ...}
        """
        matches = {
            "name": False,
            "phone": False,
            "address": False,
            "city": False,
            "state": False,
        }

        # Name matching (fuzzy)
        if listing.name and target_name:
            matches["name"] = self._fuzzy_name_match(listing.name, target_name)

        # Phone matching (exact after normalization)
        if listing.phone and target_phone:
            matches["phone"] = self._phone_match(listing.phone, target_phone)

        # Address matching (fuzzy)
        if listing.address and target_address:
            matches["address"] = self._fuzzy_address_match(listing.address, target_address)

        # City matching
        if listing.city and target_city:
            matches["city"] = listing.city.lower().strip() == target_city.lower().strip()

        # State matching
        if listing.state and target_state:
            matches["state"] = self._state_match(listing.state, target_state)

        # Calculate weighted score
        weights = {
            "name": 0.35,
            "phone": 0.30,
            "address": 0.15,
            "city": 0.10,
            "state": 0.10,
        }

        score = sum(
            weights[field] for field, matched in matches.items() if matched
        )

        return score, matches

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone to digits only."""
        if not phone:
            return ""
        return re.sub(r'\D', '', phone)

    def _phone_match(self, phone1: str, phone2: str) -> bool:
        """Check if two phone numbers match (last 10 digits)."""
        p1 = self._normalize_phone(phone1)
        p2 = self._normalize_phone(phone2)
        if len(p1) >= 10 and len(p2) >= 10:
            return p1[-10:] == p2[-10:]
        return p1 == p2

    def _normalize_name(self, name: str) -> str:
        """Normalize business name for comparison."""
        if not name:
            return ""
        normalized = name.lower().strip()
        # Remove common suffixes
        suffixes = ['llc', 'inc', 'corp', 'co', 'company', 'ltd', 'l.l.c.', 'inc.', ',']
        for suffix in suffixes:
            normalized = re.sub(rf'\s*{re.escape(suffix)}\.?\s*$', '', normalized)
        # Remove punctuation and extra spaces
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()

    def _fuzzy_name_match(self, name1: str, name2: str) -> bool:
        """Check if two business names match (fuzzy)."""
        n1 = self._normalize_name(name1)
        n2 = self._normalize_name(name2)

        # Exact match
        if n1 == n2:
            return True

        # Substring match
        if n1 in n2 or n2 in n1:
            return True

        # Word overlap (at least 2 words or 50% overlap)
        words1 = set(n1.split())
        words2 = set(n2.split())
        overlap = len(words1 & words2)
        min_words = min(len(words1), len(words2))

        if overlap >= 2 or (min_words > 0 and overlap / min_words >= 0.5):
            return True

        return False

    def _normalize_address(self, address: str) -> str:
        """Normalize address for comparison."""
        if not address:
            return ""
        normalized = address.lower().strip()
        # Common abbreviations
        replacements = {
            'street': 'st', 'avenue': 'ave', 'boulevard': 'blvd',
            'drive': 'dr', 'road': 'rd', 'lane': 'ln',
            'court': 'ct', 'place': 'pl', 'circle': 'cir',
            'north': 'n', 'south': 's', 'east': 'e', 'west': 'w',
            'suite': 'ste', 'apartment': 'apt', 'unit': '#',
        }
        for full, abbr in replacements.items():
            normalized = normalized.replace(full, abbr)
        normalized = re.sub(r'[^\w\s#]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()

    def _fuzzy_address_match(self, addr1: str, addr2: str) -> bool:
        """Check if two addresses match (fuzzy)."""
        a1 = self._normalize_address(addr1)
        a2 = self._normalize_address(addr2)

        if not a1 or not a2:
            return False

        # Extract street number if present
        num1 = re.search(r'^\d+', a1)
        num2 = re.search(r'^\d+', a2)

        # If both have street numbers, they must match
        if num1 and num2:
            if num1.group() != num2.group():
                return False

        # Word overlap
        words1 = set(a1.split())
        words2 = set(a2.split())
        overlap = len(words1 & words2)

        return overlap >= min(3, len(words1) // 2 + 1)

    def _state_match(self, state1: str, state2: str) -> bool:
        """Check if two states match (handles abbreviations)."""
        state_abbrevs = {
            'alabama': 'al', 'alaska': 'ak', 'arizona': 'az', 'arkansas': 'ar',
            'california': 'ca', 'colorado': 'co', 'connecticut': 'ct', 'delaware': 'de',
            'florida': 'fl', 'georgia': 'ga', 'hawaii': 'hi', 'idaho': 'id',
            'illinois': 'il', 'indiana': 'in', 'iowa': 'ia', 'kansas': 'ks',
            'kentucky': 'ky', 'louisiana': 'la', 'maine': 'me', 'maryland': 'md',
            'massachusetts': 'ma', 'michigan': 'mi', 'minnesota': 'mn', 'mississippi': 'ms',
            'missouri': 'mo', 'montana': 'mt', 'nebraska': 'ne', 'nevada': 'nv',
            'new hampshire': 'nh', 'new jersey': 'nj', 'new mexico': 'nm', 'new york': 'ny',
            'north carolina': 'nc', 'north dakota': 'nd', 'ohio': 'oh', 'oklahoma': 'ok',
            'oregon': 'or', 'pennsylvania': 'pa', 'rhode island': 'ri', 'south carolina': 'sc',
            'south dakota': 'sd', 'tennessee': 'tn', 'texas': 'tx', 'utah': 'ut',
            'vermont': 'vt', 'virginia': 'va', 'washington': 'wa', 'west virginia': 'wv',
            'wisconsin': 'wi', 'wyoming': 'wy',
        }

        s1 = state1.lower().strip()
        s2 = state2.lower().strip()

        # Normalize to abbreviation
        s1 = state_abbrevs.get(s1, s1)
        s2 = state_abbrevs.get(s2, s2)

        return s1 == s2


class YellowPagesAdapter(DirectoryAdapter):
    """
    Adapter for Yellow Pages (yellowpages.com).

    Reuses parsing logic from scrape_yp/yp_parser_enhanced.py
    """

    directory_name = "yellowpages"
    base_url = "https://www.yellowpages.com"

    def build_search_url(self, business_name: str, location: str, zip_code: str = "") -> str:
        """Build YP search URL."""
        search_terms = quote_plus(business_name)
        geo_location = quote_plus(location) if location else quote_plus(zip_code)
        return f"{self.base_url}/search?search_terms={search_terms}&geo_location_terms={geo_location}"

    def parse_search_results(self, html: str) -> List[DirectoryListing]:
        """Parse YP search results page."""
        from scrape_yp.yp_parser_enhanced import (
            extract_category_tags,
            extract_profile_url,
            is_sponsored,
            clean_text,
        )

        soup = BeautifulSoup(html, 'html.parser')
        listings = []

        # Find listing containers
        result_containers = soup.select('.result, .organic, .srp-listing')

        for container in result_containers:
            try:
                listing = DirectoryListing(source_directory="yellowpages")

                # Skip sponsored listings for citation matching
                if is_sponsored(container):
                    listing.is_sponsored = True

                # Extract name
                name_elem = (
                    container.select_one('.business-name') or
                    container.select_one('h2.n a') or
                    container.select_one('a[itemprop="name"]')
                )
                if name_elem:
                    listing.name = clean_text(name_elem.get_text())

                # Extract profile URL
                listing.profile_url = extract_profile_url(container, self.base_url) or ""

                # Extract phone
                phone_elem = container.select_one('.phone, [itemprop="telephone"]')
                if phone_elem:
                    listing.phone = clean_text(phone_elem.get_text())

                # Extract address
                address_elem = (
                    container.select_one('.street-address, [itemprop="streetAddress"]')
                )
                if address_elem:
                    listing.address = clean_text(address_elem.get_text())

                locality_elem = container.select_one('.locality, [itemprop="addressLocality"]')
                if locality_elem:
                    listing.city = clean_text(locality_elem.get_text())

                region_elem = container.select_one('.region, [itemprop="addressRegion"]')
                if region_elem:
                    listing.state = clean_text(region_elem.get_text())

                postal_elem = container.select_one('.postal-code, [itemprop="postalCode"]')
                if postal_elem:
                    listing.zip_code = clean_text(postal_elem.get_text())

                # Extract categories
                listing.categories = extract_category_tags(container)

                # Extract rating
                rating_elem = container.select_one('.result-rating, [class*="rating"]')
                if rating_elem:
                    rating_text = rating_elem.get('class', [])
                    for cls in rating_text:
                        match = re.search(r'(\d+)', cls)
                        if match:
                            listing.rating = int(match.group(1)) / 2  # YP uses 0-10 scale
                            break

                # Extract review count
                review_elem = container.select_one('.rating-count, [class*="review"]')
                if review_elem:
                    review_text = clean_text(review_elem.get_text())
                    match = re.search(r'(\d+)', review_text.replace(',', ''))
                    if match:
                        listing.review_count = int(match.group(1))

                # Extract website
                website_elem = container.select_one('a.track-visit-website, a[class*="website"]')
                if website_elem:
                    website_url = website_elem.get('href', '')
                    # YP may wrap in redirect
                    if '/redirect?' in website_url or '/click' in website_url:
                        # Try to extract actual URL from params
                        import urllib.parse
                        parsed = urllib.parse.urlparse(website_url)
                        params = urllib.parse.parse_qs(parsed.query)
                        if 'u' in params:
                            listing.website = params['u'][0]
                        elif 'url' in params:
                            listing.website = params['url'][0]
                    elif website_url.startswith('http'):
                        listing.website = website_url

                # Calculate confidence based on completeness
                listing.confidence = listing.completeness_score

                if listing.name:
                    listings.append(listing)

            except Exception as e:
                logger.debug(f"Error parsing YP listing: {e}")
                continue

        return listings

    def parse_listing_page(self, html: str) -> Optional[DirectoryListing]:
        """Parse a YP listing detail page."""
        # For MVP, search results contain enough info
        # Full listing page parsing can be added later
        results = self.parse_search_results(html)
        return results[0] if results else None


class YelpAdapter(DirectoryAdapter):
    """
    Adapter for Yelp (yelp.com).

    Uses parsing patterns from scrape_yelp/yelp_parse.py
    """

    directory_name = "yelp"
    base_url = "https://www.yelp.com"

    def build_search_url(self, business_name: str, location: str, zip_code: str = "") -> str:
        """Build Yelp search URL."""
        find_desc = quote_plus(business_name)
        find_loc = quote_plus(location) if location else quote_plus(zip_code)
        return f"{self.base_url}/search?find_desc={find_desc}&find_loc={find_loc}"

    def parse_search_results(self, html: str) -> List[DirectoryListing]:
        """Parse Yelp search results page."""
        soup = BeautifulSoup(html, 'html.parser')
        listings = []

        # Yelp uses various container patterns
        # Look for business result cards
        result_containers = soup.select(
            '[data-testid="serp-ia-card"], '
            '.container__09f24__sxa6R, '
            '.businessResult, '
            'li[class*="result"]'
        )

        for container in result_containers:
            try:
                listing = DirectoryListing(source_directory="yelp")

                # Check if sponsored
                sponsored_elem = container.select_one('[class*="sponsored"], [class*="ad"]')
                listing.is_sponsored = sponsored_elem is not None

                # Extract name
                name_elem = (
                    container.select_one('h3 a, h4 a') or
                    container.select_one('[class*="businessName"] a') or
                    container.select_one('a[href*="/biz/"]')
                )
                if name_elem:
                    listing.name = name_elem.get_text(strip=True)
                    # Extract profile URL
                    href = name_elem.get('href', '')
                    if href.startswith('/biz/'):
                        listing.profile_url = self.base_url + href
                    elif href.startswith('http'):
                        listing.profile_url = href

                # Extract rating
                rating_elem = container.select_one('[aria-label*="star rating"]')
                if rating_elem:
                    rating_text = rating_elem.get('aria-label', '')
                    match = re.search(r'(\d+\.?\d*)\s*star', rating_text)
                    if match:
                        listing.rating = float(match.group(1))

                # Extract review count
                review_elem = container.select_one('[class*="reviewCount"]')
                if not review_elem:
                    # Try alternate pattern
                    review_text = container.get_text()
                    match = re.search(r'(\d+)\s*reviews?', review_text, re.I)
                    if match:
                        listing.review_count = int(match.group(1))
                else:
                    review_text = review_elem.get_text().replace(',', '')
                    match = re.search(r'(\d+)', review_text)
                    if match:
                        listing.review_count = int(match.group(1))

                # Extract categories
                category_elems = container.select('a[href*="/search?cflt="], [class*="category"]')
                for elem in category_elems[:5]:
                    cat = elem.get_text(strip=True)
                    if cat and cat not in listing.categories:
                        listing.categories.append(cat)

                # Extract address/location
                address_elem = container.select_one('[class*="address"], [class*="location"]')
                if address_elem:
                    addr_text = address_elem.get_text(strip=True)
                    listing.address = addr_text
                    # Try to parse city/state
                    location_match = re.search(r'([^,]+),\s*([A-Z]{2})', addr_text)
                    if location_match:
                        listing.city = location_match.group(1).strip()
                        listing.state = location_match.group(2).strip()

                # Extract phone
                phone_elem = container.select_one('[href^="tel:"], [class*="phone"]')
                if phone_elem:
                    phone_text = phone_elem.get_text(strip=True)
                    listing.phone = phone_text

                # Calculate confidence
                listing.confidence = listing.completeness_score

                if listing.name:
                    listings.append(listing)

            except Exception as e:
                logger.debug(f"Error parsing Yelp listing: {e}")
                continue

        return listings

    def parse_listing_page(self, html: str) -> Optional[DirectoryListing]:
        """Parse a Yelp business detail page."""
        # For full detail page parsing, we'd need async Playwright
        # For now, search results provide sufficient data
        results = self.parse_search_results(html)
        return results[0] if results else None


class BBBAdapter(DirectoryAdapter):
    """
    Adapter for Better Business Bureau (bbb.org).
    """

    directory_name = "bbb"
    base_url = "https://www.bbb.org"

    def build_search_url(self, business_name: str, location: str, zip_code: str = "") -> str:
        """Build BBB search URL."""
        find_text = quote_plus(business_name)
        find_loc = quote_plus(location) if location else quote_plus(zip_code)
        return f"{self.base_url}/search?find_text={find_text}&find_loc={find_loc}&page=1"

    def parse_search_results(self, html: str) -> List[DirectoryListing]:
        """Parse BBB search results page."""
        soup = BeautifulSoup(html, 'html.parser')
        listings = []

        # BBB search result containers
        result_containers = soup.select(
            '.search-results .result-item, '
            '[class*="SearchResult"], '
            '.business-card'
        )

        for container in result_containers:
            try:
                listing = DirectoryListing(source_directory="bbb")

                # Extract name
                name_elem = (
                    container.select_one('.business-name, h3 a, h4 a') or
                    container.select_one('a[href*="/us/"]')
                )
                if name_elem:
                    listing.name = name_elem.get_text(strip=True)
                    href = name_elem.get('href', '')
                    if href.startswith('/'):
                        listing.profile_url = self.base_url + href
                    elif href.startswith('http'):
                        listing.profile_url = href

                # Extract BBB rating
                rating_elem = container.select_one('[class*="rating"], .accreditation-status')
                if rating_elem:
                    rating_text = rating_elem.get_text(strip=True)
                    # BBB uses letter grades A+, A, B, etc.
                    grade_map = {'A+': 5.0, 'A': 4.5, 'A-': 4.0, 'B+': 3.5, 'B': 3.0,
                                 'B-': 2.5, 'C+': 2.0, 'C': 1.5, 'C-': 1.0, 'D+': 0.8,
                                 'D': 0.6, 'D-': 0.4, 'F': 0.2}
                    for grade, score in grade_map.items():
                        if grade in rating_text:
                            listing.rating = score
                            break

                # Check accreditation
                accredited = container.select_one('[class*="accredited"], .ab-seal')
                listing.is_claimed = accredited is not None

                # Extract address
                address_elem = container.select_one('.address, [class*="address"]')
                if address_elem:
                    listing.address = address_elem.get_text(strip=True)

                # Extract phone
                phone_elem = container.select_one('.phone, [href^="tel:"]')
                if phone_elem:
                    listing.phone = phone_elem.get_text(strip=True)

                # Extract categories
                category_elem = container.select_one('.categories, [class*="category"]')
                if category_elem:
                    cats = category_elem.get_text(strip=True).split(',')
                    listing.categories = [c.strip() for c in cats if c.strip()]

                listing.confidence = listing.completeness_score

                if listing.name:
                    listings.append(listing)

            except Exception as e:
                logger.debug(f"Error parsing BBB listing: {e}")
                continue

        return listings

    def parse_listing_page(self, html: str) -> Optional[DirectoryListing]:
        """Parse BBB business detail page."""
        results = self.parse_search_results(html)
        return results[0] if results else None


class MapQuestAdapter(DirectoryAdapter):
    """
    Adapter for MapQuest business search.
    """

    directory_name = "mapquest"
    base_url = "https://www.mapquest.com"

    def build_search_url(self, business_name: str, location: str, zip_code: str = "") -> str:
        """Build MapQuest search URL."""
        query = quote_plus(f"{business_name} {location}")
        return f"{self.base_url}/search/results?query={query}&page=0"

    def parse_search_results(self, html: str) -> List[DirectoryListing]:
        """Parse MapQuest search results."""
        soup = BeautifulSoup(html, 'html.parser')
        listings = []

        # MapQuest result containers
        result_containers = soup.select(
            '.search-result, '
            '[class*="result-item"], '
            '.business-listing'
        )

        for container in result_containers:
            try:
                listing = DirectoryListing(source_directory="mapquest")

                # Extract name
                name_elem = container.select_one('h2, h3, .name, [class*="name"]')
                if name_elem:
                    listing.name = name_elem.get_text(strip=True)

                # Extract address
                address_elem = container.select_one('.address, [class*="address"]')
                if address_elem:
                    listing.address = address_elem.get_text(strip=True)

                # Extract phone
                phone_elem = container.select_one('.phone, [href^="tel:"]')
                if phone_elem:
                    listing.phone = phone_elem.get_text(strip=True)

                # Extract rating
                rating_elem = container.select_one('[class*="rating"]')
                if rating_elem:
                    rating_text = rating_elem.get_text(strip=True)
                    match = re.search(r'(\d+\.?\d*)', rating_text)
                    if match:
                        listing.rating = float(match.group(1))

                listing.confidence = listing.completeness_score

                if listing.name:
                    listings.append(listing)

            except Exception as e:
                logger.debug(f"Error parsing MapQuest listing: {e}")
                continue

        return listings

    def parse_listing_page(self, html: str) -> Optional[DirectoryListing]:
        """Parse MapQuest listing page."""
        results = self.parse_search_results(html)
        return results[0] if results else None


class GenericDirectoryAdapter(DirectoryAdapter):
    """
    Fallback adapter for directories without specific parsing.

    Uses generic heuristics to find business information.
    """

    directory_name = "generic"
    base_url = ""

    def build_search_url(self, business_name: str, location: str, zip_code: str = "") -> str:
        """Build generic search URL - should be overridden."""
        return ""

    def parse_search_results(self, html: str) -> List[DirectoryListing]:
        """Generic parsing using common patterns."""
        soup = BeautifulSoup(html, 'html.parser')
        listings = []

        # Try to find business name in page
        page_text = soup.get_text(separator=' ', strip=True)

        # Look for phone patterns
        phone_matches = re.findall(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', page_text)

        # Look for address patterns
        address_matches = re.findall(
            r'\d+\s+[A-Za-z]+\s+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Rd|Road)',
            page_text
        )

        # Create single listing from found info
        if phone_matches or address_matches:
            listing = DirectoryListing(source_directory=self.directory_name)
            if phone_matches:
                listing.phone = phone_matches[0]
            if address_matches:
                listing.address = address_matches[0]
            listing.confidence = 0.3  # Low confidence for generic parsing
            listings.append(listing)

        return listings

    def parse_listing_page(self, html: str) -> Optional[DirectoryListing]:
        """Parse using generic heuristics."""
        results = self.parse_search_results(html)
        return results[0] if results else None


# Adapter registry
DIRECTORY_ADAPTERS: Dict[str, DirectoryAdapter] = {
    "yellowpages": YellowPagesAdapter(),
    "yelp": YelpAdapter(),
    "bbb": BBBAdapter(),
    "mapquest": MapQuestAdapter(),
}


def get_adapter(directory: str) -> DirectoryAdapter:
    """
    Get the appropriate adapter for a directory.

    Args:
        directory: Directory name (e.g., 'yelp', 'yellowpages')

    Returns:
        DirectoryAdapter instance (falls back to GenericDirectoryAdapter)
    """
    return DIRECTORY_ADAPTERS.get(directory.lower(), GenericDirectoryAdapter())


def parse_directory_page(
    html: str,
    directory: str,
    target_name: str,
    target_phone: str = "",
    target_address: str = "",
    target_city: str = "",
    target_state: str = "",
) -> Tuple[List[DirectoryListing], Optional[DirectoryListing]]:
    """
    Parse a directory page and find the best matching listing.

    Args:
        html: Page HTML
        directory: Directory name
        target_*: Target business info for matching

    Returns:
        Tuple of (all_listings, best_match_or_none)
    """
    adapter = get_adapter(directory)

    # Parse all listings
    listings = adapter.parse_search_results(html)

    if not listings:
        return [], None

    # Find best match
    best_match = None
    best_score = 0.0

    for listing in listings:
        score, matches = adapter.calculate_match_score(
            listing,
            target_name=target_name,
            target_phone=target_phone,
            target_address=target_address,
            target_city=target_city,
            target_state=target_state,
        )

        listing.raw_data["match_score"] = score
        listing.raw_data["field_matches"] = matches

        if score > best_score:
            best_score = score
            best_match = listing

    # Only return a match if score is above threshold
    if best_match and best_score >= 0.35:
        return listings, best_match

    return listings, None
