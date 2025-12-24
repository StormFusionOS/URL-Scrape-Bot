"""
Browser Escalation Manager

Implements a multi-tier browser escalation strategy for handling CAPTCHAs:

Tier 1: SeleniumBase UC (Undetected Chrome) - default
Tier 2: SeleniumBase UC with fresh profile (clear cookies/cache)
Tier 3: Camoufox (Firefox-based undetected browser)
Tier 4: Camoufox with different fingerprint

When CAPTCHA is detected, escalate to the next tier.
Track success rates per domain to learn optimal strategies.
"""

import os
import json
import time
import shutil
import random
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, Callable
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager

from runner.logging_setup import get_logger

logger = get_logger("browser_escalation")


class BrowserTier(Enum):
    """Browser escalation tiers."""
    SELENIUM_UC = 1           # SeleniumBase Undetected Chrome
    SELENIUM_UC_FRESH = 2     # SeleniumBase UC with fresh profile
    CAMOUFOX = 3              # Camoufox (Firefox-based)
    CAMOUFOX_NEW_FP = 4       # Camoufox with new fingerprint


@dataclass
class EscalationState:
    """Tracks escalation state for a domain."""
    domain: str
    current_tier: BrowserTier = BrowserTier.SELENIUM_UC
    consecutive_failures: int = 0
    last_success_tier: Optional[BrowserTier] = None
    last_captcha_at: Optional[datetime] = None
    success_count: Dict[str, int] = field(default_factory=dict)
    failure_count: Dict[str, int] = field(default_factory=dict)

    def record_success(self, tier: BrowserTier):
        """Record successful request at tier."""
        tier_name = tier.name
        self.success_count[tier_name] = self.success_count.get(tier_name, 0) + 1
        self.consecutive_failures = 0
        self.last_success_tier = tier

    def record_failure(self, tier: BrowserTier, is_captcha: bool = False):
        """Record failed request at tier."""
        tier_name = tier.name
        self.failure_count[tier_name] = self.failure_count.get(tier_name, 0) + 1
        self.consecutive_failures += 1
        if is_captcha:
            self.last_captcha_at = datetime.now()

    def should_escalate(self) -> bool:
        """Check if we should escalate to next tier."""
        # Escalate after 2 consecutive failures or any CAPTCHA
        return self.consecutive_failures >= 2

    def get_best_tier(self) -> BrowserTier:
        """Get the tier with best success rate for this domain."""
        if not self.success_count:
            return BrowserTier.SELENIUM_UC

        # Calculate success rates
        best_tier = BrowserTier.SELENIUM_UC
        best_rate = 0

        for tier in BrowserTier:
            tier_name = tier.name
            successes = self.success_count.get(tier_name, 0)
            failures = self.failure_count.get(tier_name, 0)
            total = successes + failures

            if total > 0:
                rate = successes / total
                if rate > best_rate:
                    best_rate = rate
                    best_tier = tier

        return best_tier


class BrowserProfileManager:
    """Manages browser profiles for rotation."""

    def __init__(self, base_path: str = None):
        self.base_path = Path(base_path or "/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/browser_profiles")
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.selenium_profiles = self.base_path / "selenium_uc"
        self.camoufox_profiles = self.base_path / "camoufox"
        self.selenium_profiles.mkdir(exist_ok=True)
        self.camoufox_profiles.mkdir(exist_ok=True)

    def get_selenium_profile_path(self, profile_id: str = "default") -> str:
        """Get path for a SeleniumBase UC profile."""
        profile_path = self.selenium_profiles / profile_id
        profile_path.mkdir(exist_ok=True)
        return str(profile_path)

    def create_fresh_selenium_profile(self) -> str:
        """Create a fresh SeleniumBase profile with unique ID."""
        profile_id = f"fresh_{int(time.time())}_{random.randint(1000, 9999)}"
        return self.get_selenium_profile_path(profile_id)

    def clear_selenium_profile(self, profile_id: str = "default"):
        """Clear a SeleniumBase profile (cookies, cache)."""
        profile_path = self.selenium_profiles / profile_id
        if profile_path.exists():
            # Clear cache and cookies but keep the profile directory
            for item in ["Cache", "Cookies", "Cookies-journal", "Session Storage", "Local Storage"]:
                item_path = profile_path / item
                if item_path.exists():
                    if item_path.is_dir():
                        shutil.rmtree(item_path)
                    else:
                        item_path.unlink()
            logger.info(f"Cleared SeleniumBase profile: {profile_id}")

    def cleanup_old_profiles(self, max_age_hours: int = 24):
        """Remove old temporary profiles."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)

        for profile_dir in [self.selenium_profiles, self.camoufox_profiles]:
            for profile_path in profile_dir.iterdir():
                if profile_path.name.startswith("fresh_"):
                    try:
                        # Extract timestamp from profile name
                        parts = profile_path.name.split("_")
                        if len(parts) >= 2:
                            ts = int(parts[1])
                            if datetime.fromtimestamp(ts) < cutoff:
                                shutil.rmtree(profile_path)
                                logger.info(f"Cleaned up old profile: {profile_path.name}")
                    except (ValueError, OSError) as e:
                        logger.debug(f"Could not clean profile {profile_path}: {e}")


class BrowserEscalationManager:
    """
    Manages browser escalation strategy across all scrapers.

    Provides a unified interface for:
    - Getting the appropriate browser for a domain
    - Tracking CAPTCHA/block events
    - Escalating to more stealthy browsers
    - Profile rotation
    """

    _instance = None

    def __init__(self):
        self.profile_manager = BrowserProfileManager()
        self.domain_states: Dict[str, EscalationState] = {}
        self.state_file = Path("/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/escalation_state.json")
        self._load_state()

        # Escalation settings
        self.max_tier = BrowserTier.CAMOUFOX_NEW_FP
        self.cooldown_minutes = 30  # Time before de-escalating
        self.captcha_escalate_immediately = True

        logger.info("BrowserEscalationManager initialized")

    @classmethod
    def get_instance(cls) -> "BrowserEscalationManager":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_state(self):
        """Load saved escalation state."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                    for domain, state_dict in data.items():
                        state = EscalationState(domain=domain)
                        state.current_tier = BrowserTier[state_dict.get("current_tier", "SELENIUM_UC")]
                        state.consecutive_failures = state_dict.get("consecutive_failures", 0)
                        if state_dict.get("last_success_tier"):
                            state.last_success_tier = BrowserTier[state_dict["last_success_tier"]]
                        state.success_count = state_dict.get("success_count", {})
                        state.failure_count = state_dict.get("failure_count", {})
                        self.domain_states[domain] = state
                logger.info(f"Loaded escalation state for {len(self.domain_states)} domains")
            except Exception as e:
                logger.warning(f"Could not load escalation state: {e}")

    def _save_state(self):
        """Save escalation state to disk."""
        try:
            data = {}
            for domain, state in self.domain_states.items():
                data[domain] = {
                    "current_tier": state.current_tier.name,
                    "consecutive_failures": state.consecutive_failures,
                    "last_success_tier": state.last_success_tier.name if state.last_success_tier else None,
                    "success_count": state.success_count,
                    "failure_count": state.failure_count,
                }

            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save escalation state: {e}")

    def get_state(self, domain: str) -> EscalationState:
        """Get or create escalation state for domain."""
        if domain not in self.domain_states:
            self.domain_states[domain] = EscalationState(domain=domain)
        return self.domain_states[domain]

    def get_current_tier(self, domain: str) -> BrowserTier:
        """Get the current browser tier for a domain."""
        state = self.get_state(domain)
        return state.current_tier

    def escalate(self, domain: str, reason: str = "CAPTCHA") -> BrowserTier:
        """
        Escalate to next browser tier for domain.

        Returns the new tier.
        """
        state = self.get_state(domain)
        old_tier = state.current_tier

        # Find next tier
        if old_tier.value < self.max_tier.value:
            new_tier = BrowserTier(old_tier.value + 1)
            state.current_tier = new_tier
            logger.warning(f"Escalating {domain}: {old_tier.name} -> {new_tier.name} (reason: {reason})")
        else:
            new_tier = old_tier
            logger.warning(f"Already at max tier for {domain}: {old_tier.name}")

        self._save_state()
        return new_tier

    def de_escalate(self, domain: str) -> BrowserTier:
        """
        De-escalate to lower tier after success.

        Returns the new tier.
        """
        state = self.get_state(domain)
        old_tier = state.current_tier

        # Only de-escalate if we've had consistent success
        if state.consecutive_failures == 0 and old_tier.value > BrowserTier.SELENIUM_UC.value:
            # Check if the lower tier has good success rate
            lower_tier = BrowserTier(old_tier.value - 1)
            lower_successes = state.success_count.get(lower_tier.name, 0)
            lower_failures = state.failure_count.get(lower_tier.name, 0)

            # Only de-escalate if lower tier had decent success (>50% or no data)
            if lower_failures == 0 or lower_successes / (lower_successes + lower_failures) > 0.5:
                state.current_tier = lower_tier
                logger.info(f"De-escalating {domain}: {old_tier.name} -> {lower_tier.name}")
                self._save_state()
                return lower_tier

        return old_tier

    def record_success(self, domain: str, tier: BrowserTier = None):
        """Record successful request."""
        state = self.get_state(domain)
        tier = tier or state.current_tier
        state.record_success(tier)
        self._save_state()

    def record_failure(self, domain: str, is_captcha: bool = False, tier: BrowserTier = None):
        """Record failed request and possibly escalate."""
        state = self.get_state(domain)
        tier = tier or state.current_tier
        state.record_failure(tier, is_captcha)

        # Auto-escalate on CAPTCHA
        if is_captcha and self.captcha_escalate_immediately:
            self.escalate(domain, reason="CAPTCHA_DETECTED")
        elif state.should_escalate():
            self.escalate(domain, reason="CONSECUTIVE_FAILURES")

        self._save_state()

    def reset_domain(self, domain: str):
        """Reset escalation state for domain."""
        if domain in self.domain_states:
            del self.domain_states[domain]
            self._save_state()
            logger.info(f"Reset escalation state for {domain}")

    def get_stats(self) -> Dict[str, Any]:
        """Get escalation statistics."""
        tier_counts = {tier.name: 0 for tier in BrowserTier}
        for state in self.domain_states.values():
            tier_counts[state.current_tier.name] += 1

        return {
            "domains_tracked": len(self.domain_states),
            "tier_distribution": tier_counts,
            "domains_at_max_tier": sum(1 for s in self.domain_states.values()
                                       if s.current_tier == self.max_tier),
        }

    @contextmanager
    def get_selenium_uc_driver(self, domain: str, fresh_profile: bool = False):
        """
        Get a SeleniumBase UC driver for the domain.

        Args:
            domain: Target domain
            fresh_profile: Force a fresh profile

        Yields:
            Configured SeleniumBase driver
        """
        from seleniumbase import Driver

        state = self.get_state(domain)
        use_fresh = fresh_profile or state.current_tier == BrowserTier.SELENIUM_UC_FRESH

        if use_fresh:
            profile_path = self.profile_manager.create_fresh_selenium_profile()
            logger.info(f"Using fresh SeleniumBase profile for {domain}")
        else:
            profile_path = self.profile_manager.get_selenium_profile_path("default")

        driver = None
        try:
            driver = Driver(
                browser="chrome",
                uc=True,  # Undetected Chrome mode
                headless=False,  # Non-headless for better stealth
                user_data_dir=profile_path,
                disable_js=False,
                disable_csp=True,
            )
            yield driver
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    @contextmanager
    def get_camoufox_browser(self, domain: str, new_fingerprint: bool = False):
        """
        Get a Camoufox browser for the domain.

        Args:
            domain: Target domain
            new_fingerprint: Generate new fingerprint

        Yields:
            Camoufox browser context
        """
        import asyncio

        # Patch asyncio.get_running_loop BEFORE importing/using Camoufox
        # This prevents "Playwright Sync API inside asyncio loop" errors
        # when nest_asyncio is applied globally
        original_get_running_loop = asyncio.get_running_loop

        def patched_get_running_loop():
            raise RuntimeError("no running event loop")

        asyncio.get_running_loop = patched_get_running_loop

        browser = None
        try:
            from camoufox.sync_api import Camoufox

            state = self.get_state(domain)
            use_new_fp = new_fingerprint or state.current_tier == BrowserTier.CAMOUFOX_NEW_FP

            # Camoufox options
            options = {
                "headless": False,  # Better fingerprinting in headed mode
                "humanize": True,   # Add human-like behaviors
                "i_know_what_im_doing": True,  # Skip warnings
            }

            if use_new_fp:
                # Force new fingerprint by not persisting
                logger.info(f"Using Camoufox with fresh fingerprint for {domain}")

            browser = Camoufox(**options)
        finally:
            # Restore original asyncio function
            asyncio.get_running_loop = original_get_running_loop

        try:
            yield browser
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    def get_browser_for_domain(self, domain: str) -> Tuple[str, Any]:
        """
        Get the appropriate browser type and config for a domain.

        Returns:
            Tuple of (browser_type, config_dict)
            browser_type: "selenium_uc" or "camoufox"
        """
        state = self.get_state(domain)
        tier = state.current_tier

        if tier in (BrowserTier.SELENIUM_UC, BrowserTier.SELENIUM_UC_FRESH):
            return "selenium_uc", {
                "fresh_profile": tier == BrowserTier.SELENIUM_UC_FRESH,
                "tier": tier.name,
            }
        else:
            return "camoufox", {
                "new_fingerprint": tier == BrowserTier.CAMOUFOX_NEW_FP,
                "tier": tier.name,
            }


def get_escalation_manager() -> BrowserEscalationManager:
    """Get the singleton escalation manager."""
    return BrowserEscalationManager.get_instance()


# Convenience functions
def should_use_camoufox(domain: str) -> bool:
    """Check if domain should use Camoufox based on escalation state."""
    manager = get_escalation_manager()
    tier = manager.get_current_tier(domain)
    return tier in (BrowserTier.CAMOUFOX, BrowserTier.CAMOUFOX_NEW_FP)


def report_captcha(domain: str):
    """Report CAPTCHA detection for a domain."""
    manager = get_escalation_manager()
    manager.record_failure(domain, is_captcha=True)


def report_success(domain: str):
    """Report successful request for a domain."""
    manager = get_escalation_manager()
    manager.record_success(domain)
