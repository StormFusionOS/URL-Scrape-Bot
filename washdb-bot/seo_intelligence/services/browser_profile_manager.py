"""
Browser Profile Manager Service

Manages persistent browser profiles and hybrid headless/headed mode selection.

Features:
- Hybrid headless/headed mode: starts headless, upgrades to headed on detection
- Persistent browser profiles with cookies, localStorage, and history
- Domain-specific settings tracked in database
- Automatic profile creation and management
- Statistics tracking for mode effectiveness

Usage:
    from seo_intelligence.services.browser_profile_manager import get_browser_profile_manager

    manager = get_browser_profile_manager()

    # Check if domain needs headed browser
    use_headed = manager.requires_headed("google.com")

    # Get profile path for domain
    profile_path = manager.get_profile_path("google.com")

    # Record detection event (upgrades to headed after threshold)
    manager.record_detection("google.com", "CAPTCHA_DETECTED")

    # Record success/failure
    manager.record_success("google.com", headed=False)
    manager.record_failure("google.com", headed=True)
"""

import os
import shutil
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.models import DomainBrowserSettings, Base
from db.database_manager import get_db_manager
from runner.logging_setup import get_logger

# Initialize logger
logger = get_logger("browser_profile_manager")

# Base directory for browser profiles
BASE_PROFILE_DIR = Path(__file__).parent.parent.parent / "data" / "browser_profiles"

# Detection threshold - upgrade to headed after this many detections
DETECTION_THRESHOLD = 2

# Known domains that always need headed mode (major anti-bot sites)
ALWAYS_HEADED_DOMAINS = {
    "google.com",
    "www.google.com",
    "yelp.com",
    "www.yelp.com",
    "bbb.org",
    "www.bbb.org",
    "facebook.com",
    "www.facebook.com",
    "linkedin.com",
    "www.linkedin.com",
}


class BrowserProfileManager:
    """
    Manages browser profiles and hybrid headless/headed mode selection.

    Provides:
    - Domain-specific browser mode selection (headless vs headed)
    - Persistent browser profile management (cookies, localStorage)
    - Detection tracking and automatic mode upgrades
    - Statistics for success/failure rates by mode
    """

    def __init__(self):
        """Initialize browser profile manager."""
        self.db_manager = get_db_manager()
        self._ensure_profile_directory()
        self._ensure_table_exists()
        logger.info(f"BrowserProfileManager initialized (profiles at {BASE_PROFILE_DIR})")

    def _ensure_profile_directory(self):
        """Ensure the base profile directory exists."""
        BASE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Profile directory ensured: {BASE_PROFILE_DIR}")

    def _ensure_table_exists(self):
        """Ensure the domain_browser_settings table exists."""
        try:
            Base.metadata.create_all(self.db_manager.washdb_engine, tables=[DomainBrowserSettings.__table__])
            logger.debug("domain_browser_settings table ensured")
        except Exception as e:
            logger.warning(f"Could not ensure table exists: {e}")

    def _get_or_create_settings(self, session: Session, domain: str) -> DomainBrowserSettings:
        """
        Get or create browser settings for a domain.

        Args:
            session: SQLAlchemy session
            domain: Domain name

        Returns:
            DomainBrowserSettings: Settings for the domain
        """
        # Normalize domain (remove www. prefix for consistency)
        normalized_domain = domain.lower().replace("www.", "")

        stmt = select(DomainBrowserSettings).where(
            DomainBrowserSettings.domain == normalized_domain
        )
        settings = session.execute(stmt).scalar_one_or_none()

        if settings is None:
            # Check if this is a known always-headed domain
            requires_headed = (
                normalized_domain in ALWAYS_HEADED_DOMAINS or
                f"www.{normalized_domain}" in ALWAYS_HEADED_DOMAINS
            )

            settings = DomainBrowserSettings(
                domain=normalized_domain,
                requires_headed=requires_headed,
                detection_count=0,
                success_count_headed=0,
                success_count_headless=0,
                fail_count_headed=0,
                fail_count_headless=0,
                cookies_stored=False,
            )
            session.add(settings)
            session.flush()
            logger.info(f"Created browser settings for {normalized_domain} (headed={requires_headed})")

        return settings

    def requires_headed(self, domain: str) -> bool:
        """
        Check if a domain requires headed (visible) browser mode.

        Args:
            domain: Domain name

        Returns:
            bool: True if headed mode is required
        """
        # Normalize domain
        normalized_domain = domain.lower().replace("www.", "")

        # Quick check for always-headed domains
        if normalized_domain in ALWAYS_HEADED_DOMAINS:
            return True

        try:
            with self.db_manager.get_session() as session:
                settings = self._get_or_create_settings(session, domain)
                session.commit()
                return settings.requires_headed
        except Exception as e:
            logger.warning(f"Error checking headed requirement for {domain}: {e}")
            # Default to headless on error
            return False

    def get_profile_path(self, domain: str, create: bool = True) -> Optional[str]:
        """
        Get the browser profile path for a domain.

        Args:
            domain: Domain name
            create: Create profile directory if it doesn't exist

        Returns:
            str: Path to browser profile directory, or None if not using profiles
        """
        # Normalize domain for path
        normalized_domain = domain.lower().replace("www.", "").replace(".", "_")
        profile_path = BASE_PROFILE_DIR / normalized_domain

        if create and not profile_path.exists():
            profile_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created browser profile directory: {profile_path}")

            # Update database
            try:
                with self.db_manager.get_session() as session:
                    settings = self._get_or_create_settings(session, domain)
                    settings.profile_path = str(profile_path)
                    session.commit()
            except Exception as e:
                logger.warning(f"Error updating profile path in DB: {e}")

        return str(profile_path) if profile_path.exists() else None

    def record_detection(self, domain: str, reason: str) -> bool:
        """
        Record a bot detection event for a domain.

        If detection count exceeds threshold, upgrades domain to headed mode.

        Args:
            domain: Domain name
            reason: Detection reason (CAPTCHA_DETECTED, 403_FORBIDDEN, BOT_DETECTED)

        Returns:
            bool: True if domain was upgraded to headed mode
        """
        try:
            with self.db_manager.get_session() as session:
                settings = self._get_or_create_settings(session, domain)

                settings.detection_count += 1
                settings.last_detection = datetime.now(timezone.utc)
                settings.detection_reason = reason

                upgraded = False
                if settings.detection_count >= DETECTION_THRESHOLD and not settings.requires_headed:
                    settings.requires_headed = True
                    upgraded = True
                    logger.warning(
                        f"Domain {domain} upgraded to headed mode after "
                        f"{settings.detection_count} detections (reason: {reason})"
                    )
                else:
                    logger.info(
                        f"Detection recorded for {domain}: {reason} "
                        f"(count: {settings.detection_count}/{DETECTION_THRESHOLD})"
                    )

                session.commit()
                return upgraded

        except Exception as e:
            logger.error(f"Error recording detection for {domain}: {e}")
            return False

    def record_success(self, domain: str, headed: bool):
        """
        Record a successful request for a domain.

        Args:
            domain: Domain name
            headed: Whether headed mode was used
        """
        try:
            with self.db_manager.get_session() as session:
                settings = self._get_or_create_settings(session, domain)

                if headed:
                    settings.success_count_headed += 1
                else:
                    settings.success_count_headless += 1

                session.commit()
                logger.debug(f"Success recorded for {domain} (headed={headed})")

        except Exception as e:
            logger.warning(f"Error recording success for {domain}: {e}")

    def record_failure(self, domain: str, headed: bool, reason: Optional[str] = None):
        """
        Record a failed request for a domain.

        Args:
            domain: Domain name
            headed: Whether headed mode was used
            reason: Optional failure reason
        """
        try:
            with self.db_manager.get_session() as session:
                settings = self._get_or_create_settings(session, domain)

                if headed:
                    settings.fail_count_headed += 1
                else:
                    settings.fail_count_headless += 1

                session.commit()
                logger.debug(f"Failure recorded for {domain} (headed={headed}, reason={reason})")

        except Exception as e:
            logger.warning(f"Error recording failure for {domain}: {e}")

    def get_domain_stats(self, domain: str) -> Dict[str, Any]:
        """
        Get statistics for a domain.

        Args:
            domain: Domain name

        Returns:
            dict: Statistics including success/failure counts, mode, etc.
        """
        try:
            with self.db_manager.get_session() as session:
                settings = self._get_or_create_settings(session, domain)
                session.commit()

                return {
                    "domain": settings.domain,
                    "requires_headed": settings.requires_headed,
                    "detection_count": settings.detection_count,
                    "last_detection": settings.last_detection,
                    "detection_reason": settings.detection_reason,
                    "success_count_headed": settings.success_count_headed,
                    "success_count_headless": settings.success_count_headless,
                    "fail_count_headed": settings.fail_count_headed,
                    "fail_count_headless": settings.fail_count_headless,
                    "profile_path": settings.profile_path,
                    "cookies_stored": settings.cookies_stored,
                }

        except Exception as e:
            logger.error(f"Error getting stats for {domain}: {e}")
            return {"error": str(e)}

    def mark_cookies_stored(self, domain: str):
        """
        Mark that cookies have been stored for a domain.

        Args:
            domain: Domain name
        """
        try:
            with self.db_manager.get_session() as session:
                settings = self._get_or_create_settings(session, domain)
                settings.cookies_stored = True
                session.commit()
                logger.debug(f"Cookies marked as stored for {domain}")

        except Exception as e:
            logger.warning(f"Error marking cookies for {domain}: {e}")

    def reset_domain(self, domain: str):
        """
        Reset a domain to headless mode (for testing/recovery).

        Args:
            domain: Domain name
        """
        try:
            with self.db_manager.get_session() as session:
                settings = self._get_or_create_settings(session, domain)
                settings.requires_headed = False
                settings.detection_count = 0
                settings.last_detection = None
                settings.detection_reason = None
                session.commit()
                logger.info(f"Reset {domain} to headless mode")

        except Exception as e:
            logger.error(f"Error resetting {domain}: {e}")

    def clear_profile(self, domain: str):
        """
        Clear the browser profile for a domain.

        Args:
            domain: Domain name
        """
        profile_path = self.get_profile_path(domain, create=False)
        if profile_path and Path(profile_path).exists():
            try:
                shutil.rmtree(profile_path)
                logger.info(f"Cleared browser profile for {domain}")

                # Update database
                with self.db_manager.get_session() as session:
                    settings = self._get_or_create_settings(session, domain)
                    settings.cookies_stored = False
                    settings.profile_path = None
                    session.commit()

            except Exception as e:
                logger.error(f"Error clearing profile for {domain}: {e}")

    def get_all_headed_domains(self) -> list:
        """
        Get list of all domains that require headed mode.

        Returns:
            list: List of domain names requiring headed mode
        """
        try:
            with self.db_manager.get_session() as session:
                stmt = select(DomainBrowserSettings.domain).where(
                    DomainBrowserSettings.requires_headed == True
                )
                results = session.execute(stmt).scalars().all()
                return list(results)

        except Exception as e:
            logger.error(f"Error getting headed domains: {e}")
            return list(ALWAYS_HEADED_DOMAINS)


# Module-level singleton
_browser_profile_manager_instance = None


def get_browser_profile_manager() -> BrowserProfileManager:
    """Get or create the singleton BrowserProfileManager instance."""
    global _browser_profile_manager_instance

    if _browser_profile_manager_instance is None:
        _browser_profile_manager_instance = BrowserProfileManager()

    return _browser_profile_manager_instance
