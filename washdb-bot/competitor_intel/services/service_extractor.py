"""
Service Extractor

Extracts services and pricing information from competitor websites.
Uses page content analysis to identify:
- Services offered
- Pricing models (flat rate, hourly, per sqft, etc.)
- Price ranges
- Service descriptions
"""

import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from db.database_manager import get_db_manager

logger = logging.getLogger(__name__)


@dataclass
class ExtractedService:
    """Represents an extracted service."""
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    pricing_model: Optional[str] = None  # flat, hourly, sqft, custom, quote
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    price_unit: Optional[str] = None
    confidence: float = 0.5
    source_url: Optional[str] = None


class ServiceExtractor:
    """
    Extracts services and pricing from competitor websites.

    Uses pattern matching and content analysis to identify:
    - Service names from headings and lists
    - Pricing patterns ($XX, $XX-$XX, starting at, etc.)
    - Service categories based on keywords
    """

    # Common service categories for pressure washing / exterior cleaning
    SERVICE_CATEGORIES = {
        'pressure_washing': [
            'pressure wash', 'power wash', 'pressure cleaning',
            'driveway cleaning', 'sidewalk cleaning', 'concrete cleaning',
        ],
        'soft_washing': [
            'soft wash', 'softwash', 'low pressure', 'chemical wash',
            'house wash', 'roof wash', 'siding wash',
        ],
        'window_cleaning': [
            'window clean', 'window wash', 'glass clean',
            'window service', 'residential window', 'commercial window',
        ],
        'gutter_cleaning': [
            'gutter clean', 'gutter service', 'gutter flush',
            'downspout', 'gutter guard',
        ],
        'roof_cleaning': [
            'roof clean', 'roof wash', 'roof treatment',
            'moss removal', 'algae removal', 'roof soft wash',
        ],
        'deck_cleaning': [
            'deck clean', 'deck wash', 'deck restoration',
            'deck stain', 'wood restoration', 'fence clean',
        ],
        'commercial': [
            'commercial clean', 'fleet wash', 'building wash',
            'storefront', 'parking lot', 'graffiti removal',
        ],
    }

    # Pricing patterns
    PRICE_PATTERNS = [
        # $XX - $XX format
        r'\$(\d+(?:,\d{3})*(?:\.\d{2})?)\s*[-–—to]+\s*\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
        # Starting at $XX
        r'(?:starting\s+(?:at|from)|from)\s*\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
        # $XX per hour/sqft/etc
        r'\$(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:per|/)\s*(hour|hr|sqft|sq\s*ft|linear\s*ft|window|job)',
        # Single price $XX
        r'\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
    ]

    # Pricing model indicators
    PRICING_MODEL_PATTERNS = {
        'hourly': r'(?:per|/)\s*(?:hour|hr)|hourly|by the hour',
        'sqft': r'(?:per|/)\s*(?:sqft|sq\s*ft|square\s*foot)|by square foot',
        'flat': r'flat\s*rate|fixed\s*price|set\s*price',
        'quote': r'free\s*(?:quote|estimate)|call\s*for\s*(?:price|quote)|request\s*(?:a\s*)?quote',
        'custom': r'custom\s*(?:price|quote)|varies|depends',
    }

    def __init__(self):
        self.db_manager = get_db_manager()

    def extract_from_pages(self, competitor_id: int, pages: List[Dict[str, Any]]) -> List[ExtractedService]:
        """
        Extract services from a list of crawled pages.

        Args:
            competitor_id: The competitor ID
            pages: List of page dicts with 'url', 'title', 'content', 'html'

        Returns:
            List of extracted services
        """
        all_services = []

        for page in pages:
            # Focus on service-related pages
            url = page.get('url', '').lower()
            title = page.get('title', '').lower()

            is_service_page = any(kw in url or kw in title for kw in [
                'service', 'pricing', 'price', 'rate', 'cost',
                'wash', 'clean', 'what-we-do', 'our-work'
            ])

            if is_service_page or page.get('page_type') == 'services':
                services = self._extract_from_page(page)
                for svc in services:
                    svc.source_url = page.get('url')
                all_services.extend(services)

        # Deduplicate and merge
        merged = self._merge_services(all_services)

        return merged

    def extract_from_html(self, html: str, url: str = None) -> List[ExtractedService]:
        """
        Extract services from raw HTML content.

        Args:
            html: Raw HTML content
            url: Source URL for reference

        Returns:
            List of extracted services
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')

        # Remove script and style elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()

        text_content = soup.get_text(separator=' ', strip=True)

        page = {
            'url': url,
            'content': text_content,
            'html': html,
        }

        return self._extract_from_page(page)

    def _extract_from_page(self, page: Dict[str, Any]) -> List[ExtractedService]:
        """Extract services from a single page."""
        services = []
        content = page.get('content', '')
        html = page.get('html', '')

        # Extract from headings
        heading_services = self._extract_from_headings(html)
        services.extend(heading_services)

        # Extract from lists
        list_services = self._extract_from_lists(html)
        services.extend(list_services)

        # Extract pricing for found services
        for svc in services:
            pricing = self._extract_pricing(content, svc.name)
            if pricing:
                svc.pricing_model = pricing.get('model')
                svc.price_min = pricing.get('min')
                svc.price_max = pricing.get('max')
                svc.price_unit = pricing.get('unit')

        # Categorize services
        for svc in services:
            svc.category = self._categorize_service(svc.name)

        return services

    def _extract_from_headings(self, html: str) -> List[ExtractedService]:
        """Extract service names from headings."""
        from bs4 import BeautifulSoup

        services = []
        soup = BeautifulSoup(html, 'html.parser')

        # Look for h2, h3 headings that might be services
        for heading in soup.find_all(['h2', 'h3', 'h4']):
            text = heading.get_text(strip=True)

            # Check if it looks like a service
            if self._is_service_name(text):
                # Get description from following paragraph
                description = None
                next_p = heading.find_next_sibling('p')
                if next_p:
                    description = next_p.get_text(strip=True)[:500]

                services.append(ExtractedService(
                    name=self._normalize_service_name(text),
                    description=description,
                    confidence=0.7,
                ))

        return services

    def _extract_from_lists(self, html: str) -> List[ExtractedService]:
        """Extract service names from lists."""
        from bs4 import BeautifulSoup

        services = []
        soup = BeautifulSoup(html, 'html.parser')

        # Find lists that might contain services
        for ul in soup.find_all(['ul', 'ol']):
            # Check if parent or preceding sibling indicates services
            parent_text = ''
            if ul.parent:
                parent_text = ul.parent.get_text()[:200].lower()

            if any(kw in parent_text for kw in ['service', 'offer', 'provide', 'include']):
                for li in ul.find_all('li', recursive=False):
                    text = li.get_text(strip=True)
                    if self._is_service_name(text) and len(text) < 100:
                        services.append(ExtractedService(
                            name=self._normalize_service_name(text),
                            confidence=0.6,
                        ))

        return services

    def _is_service_name(self, text: str) -> bool:
        """Check if text looks like a service name."""
        text_lower = text.lower()

        # Must contain service-related keywords
        service_keywords = [
            'wash', 'clean', 'removal', 'restoration', 'treatment',
            'service', 'maintenance', 'repair', 'installation',
        ]

        has_keyword = any(kw in text_lower for kw in service_keywords)

        # Should be reasonable length
        reasonable_length = 3 < len(text) < 100

        # Should not be navigation or common non-service text
        excluded = [
            'contact', 'about', 'home', 'blog', 'faq', 'login',
            'sign up', 'cart', 'checkout', 'privacy', 'terms',
        ]
        not_excluded = not any(ex in text_lower for ex in excluded)

        return has_keyword and reasonable_length and not_excluded

    def _normalize_service_name(self, name: str) -> str:
        """Normalize a service name."""
        # Remove extra whitespace
        name = ' '.join(name.split())

        # Title case
        name = name.title()

        # Remove trailing punctuation
        name = name.rstrip('.,;:')

        return name

    def _categorize_service(self, service_name: str) -> Optional[str]:
        """Categorize a service based on keywords."""
        name_lower = service_name.lower()

        for category, keywords in self.SERVICE_CATEGORIES.items():
            if any(kw in name_lower for kw in keywords):
                return category

        return None

    def _extract_pricing(self, content: str, service_name: str) -> Optional[Dict]:
        """Extract pricing information related to a service."""
        content_lower = content.lower()
        service_lower = service_name.lower()

        # Find content near service name
        idx = content_lower.find(service_lower)
        if idx == -1:
            return None

        # Look at text within 500 chars of service name
        start = max(0, idx - 100)
        end = min(len(content), idx + 500)
        context = content[start:end]

        result = {}

        # Detect pricing model
        for model, pattern in self.PRICING_MODEL_PATTERNS.items():
            if re.search(pattern, context, re.IGNORECASE):
                result['model'] = model
                break

        # Extract prices
        for pattern in self.PRICE_PATTERNS:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 2 and groups[1]:
                    # Range or price with unit
                    try:
                        price1 = float(groups[0].replace(',', ''))
                        if groups[1].replace(',', '').replace('.', '').isdigit():
                            price2 = float(groups[1].replace(',', ''))
                            result['min'] = min(price1, price2)
                            result['max'] = max(price1, price2)
                        else:
                            result['min'] = price1
                            result['unit'] = groups[1]
                    except ValueError:
                        pass
                elif len(groups) >= 1:
                    try:
                        result['min'] = float(groups[0].replace(',', ''))
                    except ValueError:
                        pass
                break

        return result if result else None

    def _merge_services(self, services: List[ExtractedService]) -> List[ExtractedService]:
        """Merge duplicate services, keeping best data."""
        merged = {}

        for svc in services:
            key = svc.name.lower()

            if key not in merged:
                merged[key] = svc
            else:
                existing = merged[key]
                # Keep higher confidence
                if svc.confidence > existing.confidence:
                    merged[key] = svc
                # Merge pricing if missing
                if not existing.price_min and svc.price_min:
                    existing.price_min = svc.price_min
                    existing.price_max = svc.price_max
                    existing.pricing_model = svc.pricing_model
                if not existing.description and svc.description:
                    existing.description = svc.description

        return list(merged.values())

    def save_services(self, competitor_id: int, services: List[ExtractedService]) -> int:
        """
        Save extracted services to database.

        Returns:
            Number of services saved/updated
        """
        saved = 0

        try:
            with self.db_manager.get_session() as session:
                for svc in services:
                    query = text("""
                        INSERT INTO competitor_services
                            (competitor_id, service_name, service_category, pricing_model,
                             price_min, price_max, price_unit, description, source_url,
                             confidence_score, discovered_at, last_seen_at)
                        VALUES
                            (:competitor_id, :name, :category, :pricing_model,
                             :price_min, :price_max, :price_unit, :description, :source_url,
                             :confidence, NOW(), NOW())
                        ON CONFLICT (competitor_id, service_name)
                        DO UPDATE SET
                            service_category = COALESCE(EXCLUDED.service_category, competitor_services.service_category),
                            pricing_model = COALESCE(EXCLUDED.pricing_model, competitor_services.pricing_model),
                            price_min = COALESCE(EXCLUDED.price_min, competitor_services.price_min),
                            price_max = COALESCE(EXCLUDED.price_max, competitor_services.price_max),
                            price_unit = COALESCE(EXCLUDED.price_unit, competitor_services.price_unit),
                            description = COALESCE(EXCLUDED.description, competitor_services.description),
                            source_url = COALESCE(EXCLUDED.source_url, competitor_services.source_url),
                            confidence_score = GREATEST(EXCLUDED.confidence_score, competitor_services.confidence_score),
                            last_seen_at = NOW()
                    """)

                    session.execute(query, {
                        'competitor_id': competitor_id,
                        'name': svc.name,
                        'category': svc.category,
                        'pricing_model': svc.pricing_model,
                        'price_min': svc.price_min,
                        'price_max': svc.price_max,
                        'price_unit': svc.price_unit,
                        'description': svc.description[:500] if svc.description else None,
                        'source_url': svc.source_url,
                        'confidence': svc.confidence,
                    })
                    saved += 1

                session.commit()
                logger.info(f"Saved {saved} services for competitor {competitor_id}")

        except Exception as e:
            logger.error(f"Failed to save services: {e}")

        return saved

    def get_competitor_services(self, competitor_id: int) -> List[Dict]:
        """Get all services for a competitor."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT service_name, service_category, pricing_model,
                           price_min, price_max, price_unit, description,
                           confidence_score, last_seen_at
                    FROM competitor_services
                    WHERE competitor_id = :competitor_id AND is_active = true
                    ORDER BY service_category, service_name
                """), {'competitor_id': competitor_id})

                return [dict(r._mapping) for r in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get services: {e}")
            return []


def extract_services_for_competitor(competitor_id: int, website_url: str) -> Dict[str, Any]:
    """
    Main entry point for service extraction.

    Args:
        competitor_id: Competitor to extract services for
        website_url: Website URL to crawl

    Returns:
        Dict with success status and extracted services count
    """
    from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium

    try:
        # Extract domain from URL
        domain = website_url.replace('https://', '').replace('http://', '').split('/')[0]

        # Crawl competitor pages
        crawler = CompetitorCrawlerSelenium()
        crawl_result = crawler.crawl_competitor(
            domain=domain,
            website_url=website_url,
        )

        # Extract services from crawl result if available
        extractor = ServiceExtractor()
        services = []

        if crawl_result and isinstance(crawl_result, dict):
            pages = crawl_result.get('pages', [])

            for page in pages:
                page_type = page.get('page_type', '')
                if page_type in ['services', 'pricing', 'homepage', ''] or not page_type:
                    try:
                        html = page.get('html') or page.get('content', '')
                        if html:
                            page_services = extractor.extract_from_html(html, page.get('url', website_url))
                            services.extend(page_services)
                    except Exception as e:
                        logger.debug(f"Failed to extract from page: {e}")

        # If no pages from crawl, try direct extraction from main URL
        if not services:
            try:
                result = crawler.fetch_page(website_url)
                if result and result.get('html'):
                    services = extractor.extract_from_html(result['html'], website_url)
            except Exception as e:
                logger.debug(f"Failed to fetch main page: {e}")

        # Merge and save
        merged = extractor._merge_services(services)
        saved = extractor.save_services(competitor_id, merged)

        return {
            'success': True,
            'services_found': len(merged),
            'services_saved': saved,
        }

    except Exception as e:
        logger.error(f"Service extraction failed: {e}")
        return {
            'success': False,
            'error': str(e),
        }
