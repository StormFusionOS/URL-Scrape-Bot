"""
Social Media Tracker for Competitor Intelligence

Discovers and tracks competitor social media presence:
- Profile detection from website
- Platform-specific data extraction
- Engagement metrics (where available)
- Activity tracking
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from sqlalchemy import text

from competitor_intel.config import SOCIAL_PLATFORMS, SOCIAL_CONFIG
from db.database_manager import create_session

logger = logging.getLogger(__name__)


@dataclass
class SocialProfile:
    """Detected social media profile."""
    platform: str
    profile_url: str
    handle: Optional[str] = None
    profile_id: Optional[str] = None
    is_verified: bool = False
    # Metrics (may be None if not accessible)
    follower_count: Optional[int] = None
    post_count: Optional[int] = None
    engagement_rate: Optional[float] = None
    last_post_date: Optional[datetime] = None


@dataclass
class SocialDiscoveryResult:
    """Result of social profile discovery."""
    competitor_id: int
    profiles_found: List[SocialProfile] = field(default_factory=list)
    profiles_new: int = 0
    profiles_updated: int = 0


class SocialTracker:
    """
    Discovers and tracks competitor social media presence.

    Detection methods:
    1. Link extraction from website HTML
    2. Common URL pattern matching
    3. Social meta tag analysis
    """

    # Platform URL patterns for detection
    PLATFORM_PATTERNS = {
        "facebook": [
            r'(?:https?://)?(?:www\.)?facebook\.com/([^/?#\s]+)',
            r'(?:https?://)?(?:www\.)?fb\.com/([^/?#\s]+)',
        ],
        "instagram": [
            r'(?:https?://)?(?:www\.)?instagram\.com/([^/?#\s]+)',
        ],
        "youtube": [
            r'(?:https?://)?(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)?([^/?#\s]+)',
        ],
        "twitter": [
            r'(?:https?://)?(?:www\.)?twitter\.com/([^/?#\s]+)',
            r'(?:https?://)?(?:www\.)?x\.com/([^/?#\s]+)',
        ],
        "linkedin": [
            r'(?:https?://)?(?:www\.)?linkedin\.com/(?:company|in)/([^/?#\s]+)',
        ],
        "tiktok": [
            r'(?:https?://)?(?:www\.)?tiktok\.com/@([^/?#\s]+)',
        ],
    }

    def __init__(self):
        self.platforms = SOCIAL_PLATFORMS
        self.track_followers = SOCIAL_CONFIG.get("track_followers", True)
        self.track_posts = SOCIAL_CONFIG.get("track_posts", True)

        # Compile patterns
        self._compiled_patterns = {}
        for platform, patterns in self.PLATFORM_PATTERNS.items():
            self._compiled_patterns[platform] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

        logger.info(f"SocialTracker initialized for platforms: {self.platforms}")

    def discover_profiles(self, html: str, website_url: str) -> List[SocialProfile]:
        """
        Discover social profiles from website HTML.

        Args:
            html: Website HTML content
            website_url: The website URL (for context)

        Returns:
            List of discovered SocialProfile objects
        """
        profiles = []
        found_urls = set()

        soup = BeautifulSoup(html, 'html.parser')

        # Method 1: Extract from links
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')
            profile = self._parse_social_url(href)
            if profile and profile.profile_url not in found_urls:
                found_urls.add(profile.profile_url)
                profiles.append(profile)

        # Method 2: Check meta tags (og:url, etc.)
        meta_profiles = self._extract_from_meta(soup)
        for profile in meta_profiles:
            if profile.profile_url not in found_urls:
                found_urls.add(profile.profile_url)
                profiles.append(profile)

        # Method 3: Check for social icons/widgets
        widget_profiles = self._extract_from_widgets(soup)
        for profile in widget_profiles:
            if profile.profile_url not in found_urls:
                found_urls.add(profile.profile_url)
                profiles.append(profile)

        logger.info(f"Discovered {len(profiles)} social profiles from {website_url}")
        return profiles

    def _parse_social_url(self, url: str) -> Optional[SocialProfile]:
        """Parse a URL and extract social profile info if it matches a known platform."""
        if not url or not url.startswith(('http', '//')):
            return None

        for platform, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                match = pattern.search(url)
                if match:
                    handle = match.group(1) if match.groups() else None

                    # Clean up handle
                    if handle:
                        handle = handle.strip('/').lower()
                        # Skip common non-profile paths
                        if handle in ['share', 'sharer', 'intent', 'login', 'signup']:
                            continue

                    # For Facebook profile.php URLs, preserve original URL with query params
                    if platform == 'facebook' and 'profile.php' in url:
                        normalized_url = url.split('#')[0]  # Remove fragment only
                        # Extract profile ID from query string
                        import re as url_re
                        id_match = url_re.search(r'[?&]id=(\d+)', url)
                        if id_match:
                            handle = f"profile_{id_match.group(1)}"
                    else:
                        # Normalize URL
                        normalized_url = self._normalize_profile_url(platform, handle)

                    return SocialProfile(
                        platform=platform,
                        profile_url=normalized_url,
                        handle=handle,
                    )

        return None

    def _normalize_profile_url(self, platform: str, handle: str) -> str:
        """Create normalized profile URL."""
        base_urls = {
            "facebook": "https://www.facebook.com/",
            "instagram": "https://www.instagram.com/",
            "youtube": "https://www.youtube.com/@",
            "twitter": "https://twitter.com/",
            "linkedin": "https://www.linkedin.com/company/",
            "tiktok": "https://www.tiktok.com/@",
        }

        base = base_urls.get(platform, f"https://{platform}.com/")
        return f"{base}{handle}"

    def _extract_from_meta(self, soup: BeautifulSoup) -> List[SocialProfile]:
        """Extract social profiles from meta tags."""
        profiles = []

        # Check og:url for social sites
        og_url = soup.find('meta', property='og:url')
        if og_url:
            url = og_url.get('content', '')
            profile = self._parse_social_url(url)
            if profile:
                profiles.append(profile)

        # Check twitter:site
        twitter_site = soup.find('meta', attrs={'name': 'twitter:site'})
        if twitter_site:
            handle = twitter_site.get('content', '').strip('@')
            if handle:
                profiles.append(SocialProfile(
                    platform="twitter",
                    profile_url=f"https://twitter.com/{handle}",
                    handle=handle,
                ))

        return profiles

    def _extract_from_widgets(self, soup: BeautifulSoup) -> List[SocialProfile]:
        """Extract social profiles from embedded widgets."""
        profiles = []

        # Look for Facebook page plugin
        fb_page = soup.find('div', {'class': 'fb-page'})
        if fb_page:
            href = fb_page.get('data-href', '')
            profile = self._parse_social_url(href)
            if profile:
                profiles.append(profile)

        # Look for Instagram embeds
        ig_embed = soup.find('blockquote', {'class': 'instagram-media'})
        if ig_embed:
            data_instgrm = ig_embed.get('data-instgrm-permalink', '')
            profile = self._parse_social_url(data_instgrm)
            if profile:
                profiles.append(profile)

        return profiles

    def save_profiles(
        self, competitor_id: int, profiles: List[SocialProfile]
    ) -> SocialDiscoveryResult:
        """
        Save discovered profiles to database.

        Args:
            competitor_id: The competitor ID
            profiles: List of discovered profiles

        Returns:
            SocialDiscoveryResult with counts
        """
        result = SocialDiscoveryResult(
            competitor_id=competitor_id,
            profiles_found=profiles,
        )

        session = create_session()
        try:
            for profile in profiles:
                # Check if exists
                existing = session.execute(text("""
                    SELECT id, profile_url FROM competitor_social_profiles
                    WHERE competitor_id = :competitor_id AND platform = :platform
                """), {
                    "competitor_id": competitor_id,
                    "platform": profile.platform,
                }).fetchone()

                if existing:
                    # Update
                    session.execute(text("""
                        UPDATE competitor_social_profiles
                        SET profile_url = :profile_url,
                            handle = :handle,
                            last_checked_at = NOW()
                        WHERE id = :id
                    """), {
                        "id": existing[0],
                        "profile_url": profile.profile_url,
                        "handle": profile.handle,
                    })
                    result.profiles_updated += 1
                else:
                    # Insert
                    session.execute(text("""
                        INSERT INTO competitor_social_profiles (
                            competitor_id, platform, profile_url, handle,
                            is_verified, follower_count, post_count,
                            engagement_rate, last_post_date, is_active
                        ) VALUES (
                            :competitor_id, :platform, :profile_url, :handle,
                            :is_verified, :follower_count, :post_count,
                            :engagement_rate, :last_post_date, true
                        )
                    """), {
                        "competitor_id": competitor_id,
                        "platform": profile.platform,
                        "profile_url": profile.profile_url,
                        "handle": profile.handle,
                        "is_verified": profile.is_verified,
                        "follower_count": profile.follower_count,
                        "post_count": profile.post_count,
                        "engagement_rate": profile.engagement_rate,
                        "last_post_date": profile.last_post_date,
                    })
                    result.profiles_new += 1

            session.commit()
            logger.info(
                f"Saved {result.profiles_new} new, "
                f"{result.profiles_updated} updated profiles for competitor {competitor_id}"
            )
        except Exception as e:
            logger.error(f"Failed to save social profiles: {e}")
            session.rollback()
        finally:
            session.close()

        return result

    def get_competitor_profiles(self, competitor_id: int) -> List[SocialProfile]:
        """Get all social profiles for a competitor."""
        session = create_session()
        try:
            result = session.execute(text("""
                SELECT platform, profile_url, handle, profile_id,
                       is_verified, follower_count, post_count,
                       engagement_rate, last_post_date
                FROM competitor_social_profiles
                WHERE competitor_id = :competitor_id AND is_active = true
            """), {"competitor_id": competitor_id}).fetchall()

            return [
                SocialProfile(
                    platform=r[0],
                    profile_url=r[1],
                    handle=r[2],
                    profile_id=r[3],
                    is_verified=r[4],
                    follower_count=r[5],
                    post_count=r[6],
                    engagement_rate=r[7],
                    last_post_date=r[8],
                )
                for r in result
            ]
        finally:
            session.close()


def discover_social_profiles(html: str, website_url: str) -> List[SocialProfile]:
    """
    Convenience function to discover social profiles.

    Args:
        html: Website HTML content
        website_url: The website URL

    Returns:
        List of SocialProfile objects
    """
    tracker = SocialTracker()
    return tracker.discover_profiles(html, website_url)
