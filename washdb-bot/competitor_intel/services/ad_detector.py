"""
Ad Detector for Competitor Intelligence

Detects competitor advertising activity:
- Google Ads detection via SERP observation
- Facebook Ad Library integration
- Ad copy/headline tracking
- Campaign detection
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from sqlalchemy import text

from competitor_intel.config import AD_DETECTION_CONFIG
from db.database_manager import create_session

logger = logging.getLogger(__name__)


@dataclass
class DetectedAd:
    """A detected competitor advertisement."""
    platform: str  # google, facebook, instagram, youtube
    headline: str
    description: Optional[str] = None
    display_url: Optional[str] = None
    landing_url: Optional[str] = None
    detected_keywords: List[str] = field(default_factory=list)
    detected_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    ad_format: Optional[str] = None  # search, display, video, etc.


@dataclass
class AdIntelligence:
    """Aggregated ad intelligence for a competitor."""
    competitor_id: int
    is_advertising: bool
    platforms_active: List[str] = field(default_factory=list)
    total_ads_detected: int = 0
    google_ads_count: int = 0
    facebook_ads_count: int = 0
    detected_keywords: List[str] = field(default_factory=list)
    ad_copy_themes: List[str] = field(default_factory=list)
    first_ad_seen: Optional[datetime] = None
    last_ad_seen: Optional[datetime] = None


class AdDetector:
    """
    Detects competitor advertising activity.

    Sources:
    - Google Search results (sponsored listings)
    - Facebook Ad Library API
    - Social media profiles (promoted content indicators)
    """

    def __init__(self):
        self.track_keywords = AD_DETECTION_CONFIG.get("track_keywords", True)
        self.enabled_platforms = AD_DETECTION_CONFIG.get("platforms", ["google", "facebook"])

        logger.info(f"AdDetector initialized for platforms: {self.enabled_platforms}")

    def detect_google_ads(
        self, serp_html: str, competitor_domain: str
    ) -> List[DetectedAd]:
        """
        Detect Google Ads from SERP HTML.

        Args:
            serp_html: Google search results HTML
            competitor_domain: The competitor's domain to look for

        Returns:
            List of detected ads for the competitor
        """
        ads = []
        soup = BeautifulSoup(serp_html, 'html.parser')

        # Normalize domain for matching
        domain_pattern = self._create_domain_pattern(competitor_domain)

        # Google ads typically have specific markers
        # Look for sponsored listings
        ad_containers = self._find_ad_containers(soup)

        for container in ad_containers:
            ad = self._extract_google_ad(container, domain_pattern)
            if ad:
                ads.append(ad)

        logger.debug(f"Detected {len(ads)} Google ads for {competitor_domain}")
        return ads

    def _create_domain_pattern(self, domain: str) -> re.Pattern:
        """Create regex pattern for domain matching."""
        # Handle www and non-www
        domain = domain.lower().replace('www.', '')
        pattern = rf'(?:www\.)?{re.escape(domain)}'
        return re.compile(pattern, re.IGNORECASE)

    def _find_ad_containers(self, soup: BeautifulSoup) -> List:
        """Find Google ad containers in SERP."""
        containers = []

        # Method 1: Look for "Sponsored" or "Ad" labels
        for elem in soup.find_all(string=re.compile(r'^(Sponsored|Ad)$', re.I)):
            parent = elem.find_parent('div')
            if parent:
                # Go up to find the ad container
                ad_block = parent.find_parent('div', recursive=True)
                if ad_block and ad_block not in containers:
                    containers.append(ad_block)

        # Method 2: Look for data-* attributes common in ads
        for elem in soup.find_all(attrs={'data-text-ad': True}):
            if elem not in containers:
                containers.append(elem)

        # Method 3: Look for common ad container classes
        ad_class_patterns = ['ads-ad', 'commercial-unit', 'pla-unit']
        for pattern in ad_class_patterns:
            for elem in soup.find_all(class_=re.compile(pattern, re.I)):
                if elem not in containers:
                    containers.append(elem)

        return containers

    def _extract_google_ad(
        self, container, domain_pattern: re.Pattern
    ) -> Optional[DetectedAd]:
        """Extract ad information from container if it matches domain."""
        # Find displayed URL
        display_url = None
        for elem in container.find_all(['cite', 'span']):
            text = elem.get_text().strip()
            if domain_pattern.search(text):
                display_url = text
                break

        if not display_url:
            # Check links
            for link in container.find_all('a', href=True):
                href = link.get('href', '')
                if domain_pattern.search(href):
                    display_url = href
                    break

        if not display_url:
            return None  # Not our competitor's ad

        # Extract headline
        headline = ""
        for heading in container.find_all(['h3', 'h2', 'a']):
            text = heading.get_text().strip()
            if len(text) > 10:
                headline = text
                break

        if not headline:
            return None

        # Extract description
        description = None
        for elem in container.find_all(['div', 'span']):
            text = elem.get_text().strip()
            if len(text) > 50 and text != headline:
                description = text[:300]
                break

        # Extract landing URL
        landing_url = None
        for link in container.find_all('a', href=True):
            href = link.get('href', '')
            if href.startswith('http') and 'google' not in href:
                landing_url = href
                break

        return DetectedAd(
            platform="google",
            headline=headline,
            description=description,
            display_url=display_url,
            landing_url=landing_url,
            ad_format="search",
        )

    def detect_facebook_ads(
        self, competitor_name: str, competitor_domain: str
    ) -> List[DetectedAd]:
        """
        Detect Facebook ads using Ad Library.

        Note: This requires fetching from Facebook Ad Library API.
        Returns empty list if API not configured.

        Args:
            competitor_name: Business name to search
            competitor_domain: Domain for verification

        Returns:
            List of detected Facebook ads
        """
        # Facebook Ad Library requires API access
        # This is a placeholder for the integration
        logger.debug(f"Facebook ad detection for {competitor_name} (API integration pending)")
        return []

    def extract_ad_keywords(self, ads: List[DetectedAd]) -> List[str]:
        """
        Extract common keywords from ad copy.

        Args:
            ads: List of detected ads

        Returns:
            List of keywords found in ads
        """
        keyword_counts = {}

        # Service-related keywords to look for
        service_keywords = [
            'pressure wash', 'power wash', 'soft wash', 'roof clean',
            'gutter clean', 'house wash', 'driveway clean', 'deck clean',
            'commercial', 'residential', 'free estimate', 'free quote',
            'same day', 'affordable', 'professional', 'licensed', 'insured',
            'satisfaction guaranteed', 'eco-friendly', 'safe', 'fast',
        ]

        for ad in ads:
            text = f"{ad.headline} {ad.description or ''}".lower()

            for keyword in service_keywords:
                if keyword in text:
                    keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

        # Sort by frequency
        sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
        return [kw for kw, _ in sorted_keywords[:15]]

    def identify_ad_themes(self, ads: List[DetectedAd]) -> List[str]:
        """
        Identify common themes in ad messaging.

        Args:
            ads: List of detected ads

        Returns:
            List of identified themes
        """
        themes = []

        # Theme patterns
        theme_patterns = {
            'price_focused': [r'affordable', r'low price', r'cheap', r'\$\d+', r'discount', r'save'],
            'quality_focused': [r'professional', r'expert', r'quality', r'best', r'top-rated'],
            'trust_focused': [r'licensed', r'insured', r'certified', r'guarantee', r'trusted'],
            'urgency_focused': [r'today', r'same day', r'fast', r'quick', r'now', r'limited'],
            'local_focused': [r'local', r'nearby', r'your area', r'community', r'neighborhood'],
            'free_offers': [r'free estimate', r'free quote', r'no obligation', r'free inspection'],
        }

        for ad in ads:
            text = f"{ad.headline} {ad.description or ''}".lower()

            for theme, patterns in theme_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, text, re.I):
                        if theme not in themes:
                            themes.append(theme)
                        break

        return themes

    def get_ad_intelligence(self, competitor_id: int) -> AdIntelligence:
        """
        Get aggregated ad intelligence for a competitor.

        Args:
            competitor_id: The competitor ID

        Returns:
            AdIntelligence summary
        """
        ads = self._fetch_ads_from_db(competitor_id)

        if not ads:
            return AdIntelligence(
                competitor_id=competitor_id,
                is_advertising=False,
            )

        # Count by platform
        platform_counts = {}
        for ad in ads:
            platform_counts[ad.platform] = platform_counts.get(ad.platform, 0) + 1

        # Extract keywords and themes
        keywords = self.extract_ad_keywords(ads)
        themes = self.identify_ad_themes(ads)

        # Get date range
        dates = [ad.detected_at for ad in ads if ad.detected_at]
        first_seen = min(dates) if dates else None
        last_seen = max(dates) if dates else None

        return AdIntelligence(
            competitor_id=competitor_id,
            is_advertising=True,
            platforms_active=list(platform_counts.keys()),
            total_ads_detected=len(ads),
            google_ads_count=platform_counts.get('google', 0),
            facebook_ads_count=platform_counts.get('facebook', 0),
            detected_keywords=keywords,
            ad_copy_themes=themes,
            first_ad_seen=first_seen,
            last_ad_seen=last_seen,
        )

    def _fetch_ads_from_db(self, competitor_id: int) -> List[DetectedAd]:
        """Fetch detected ads from database."""
        session = create_session()
        try:
            result = session.execute(text("""
                SELECT platform, headline, description, display_url,
                       destination_url, detected_keywords, first_seen_at,
                       is_active, ad_type
                FROM competitor_ads
                WHERE competitor_id = :competitor_id
                ORDER BY first_seen_at DESC
                LIMIT 100
            """), {"competitor_id": competitor_id}).fetchall()

            return [
                DetectedAd(
                    platform=r[0],
                    headline=r[1] or "",
                    description=r[2],
                    display_url=r[3],
                    landing_url=r[4],
                    detected_keywords=list(r[5]) if r[5] else [],
                    detected_at=r[6],
                    is_active=r[7],
                    ad_format=r[8],
                )
                for r in result
            ]
        finally:
            session.close()

    def save_ads(self, competitor_id: int, ads: List[DetectedAd]):
        """Save detected ads to database."""
        session = create_session()
        try:
            for ad in ads:
                # Check for duplicate by headline + platform
                existing = session.execute(text("""
                    SELECT id FROM competitor_ads
                    WHERE competitor_id = :competitor_id
                      AND platform = :platform
                      AND headline = :headline
                """), {
                    "competitor_id": competitor_id,
                    "platform": ad.platform,
                    "headline": ad.headline,
                }).fetchone()

                if existing:
                    # Update last seen
                    session.execute(text("""
                        UPDATE competitor_ads
                        SET is_active = true,
                            last_seen_at = NOW()
                        WHERE id = :id
                    """), {"id": existing[0]})
                else:
                    # Insert new
                    session.execute(text("""
                        INSERT INTO competitor_ads (
                            competitor_id, platform, headline, description,
                            display_url, destination_url, detected_keywords,
                            ad_type, is_active, first_seen_at
                        ) VALUES (
                            :competitor_id, :platform, :headline, :description,
                            :display_url, :destination_url, :detected_keywords::jsonb,
                            :ad_type, true, NOW()
                        )
                    """), {
                        "competitor_id": competitor_id,
                        "platform": ad.platform,
                        "headline": ad.headline,
                        "description": ad.description,
                        "display_url": ad.display_url,
                        "destination_url": ad.landing_url,
                        "detected_keywords": str(ad.detected_keywords).replace("'", '"'),
                        "ad_type": ad.ad_format,
                    })

            session.commit()
            logger.info(f"Saved {len(ads)} ads for competitor {competitor_id}")
        except Exception as e:
            logger.error(f"Failed to save ads: {e}")
            session.rollback()
        finally:
            session.close()


def detect_competitor_ads(
    serp_html: str, competitor_domain: str
) -> List[DetectedAd]:
    """
    Convenience function to detect ads from SERP.

    Args:
        serp_html: Google SERP HTML
        competitor_domain: Competitor's domain

    Returns:
        List of detected ads
    """
    detector = AdDetector()
    return detector.detect_google_ads(serp_html, competitor_domain)
