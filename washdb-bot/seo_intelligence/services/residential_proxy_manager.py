"""
Residential Proxy Manager

Manages static residential proxy pool with:
- Directory-specific proxy pools (sticky assignment)
- Timezone matching for target businesses
- GPS geolocation spoofing
- Health tracking and automatic blacklisting

Static IP Design:
- Proxies are assigned to directory pools at initialization
- Same proxy always serves same directory (builds reputation)
- Round-robin within pool
- Blacklisting is temporary (static IPs recover)

Author: WashDB Bot
"""

import os
import json
import threading
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple

from runner.logging_setup import get_logger

logger = get_logger("residential_proxy_manager")


@dataclass
class ResidentialProxy:
    """Static residential proxy with location data."""
    host: str
    port: int
    username: str
    password: str
    # Location data
    country_code: str = "US"
    city_name: str = ""
    state: str = ""
    timezone: str = "America/New_York"
    timezone_offset: int = -300  # minutes from UTC
    latitude: float = 0.0
    longitude: float = 0.0
    # Health tracking
    success_count: int = 0
    failure_count: int = 0
    last_used: Optional[str] = None
    blacklisted: bool = False
    blacklist_until: Optional[str] = None
    # Pool assignment
    assigned_pool: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_healthy(self) -> bool:
        """Check if proxy is healthy and not blacklisted."""
        if self.blacklisted:
            # Check if blacklist has expired
            if self.blacklist_until:
                try:
                    until = datetime.fromisoformat(self.blacklist_until)
                    if datetime.now() < until:
                        return False
                    # Blacklist expired
                    self.blacklisted = False
                    self.blacklist_until = None
                except:
                    pass
            else:
                return False

        # Check success rate if we have enough attempts
        total = self.success_count + self.failure_count
        if total >= 10:
            success_rate = self.success_count / total
            return success_rate >= 0.5

        return True

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total

    def to_selenium_format(self) -> str:
        """Format: user:pass@host:port"""
        return f"{self.username}:{self.password}@{self.host}:{self.port}"

    def to_playwright_format(self) -> Dict[str, str]:
        """Format for Playwright browser context."""
        return {
            "server": f"http://{self.host}:{self.port}",
            "username": self.username,
            "password": self.password
        }


# Directory to pool mapping
DIRECTORY_POOLS = {
    "yellowpages": "pool_yp",
    "yelp": "pool_yelp",
    "manta": "pool_manta",
    "google": "pool_google",
    "bbb": "pool_other",
    "mapquest": "pool_other",
    "foursquare": "pool_other",
    "facebook": "pool_other",
}

# Pool allocation counts
POOL_SIZES = {
    "pool_yp": int(os.getenv("PROXY_POOL_YP_COUNT", "12")),
    "pool_yelp": int(os.getenv("PROXY_POOL_YELP_COUNT", "12")),
    "pool_manta": int(os.getenv("PROXY_POOL_MANTA_COUNT", "6")),
    "pool_google": int(os.getenv("PROXY_POOL_GOOGLE_COUNT", "15")),
    "pool_other": int(os.getenv("PROXY_POOL_OTHER_COUNT", "5")),
}


class ResidentialProxyManager:
    """Manages static residential proxy pool with location-aware selection.

    Key features:
    - Directory-specific proxy pools (sticky assignment)
    - Timezone/geolocation matching for target businesses
    - Health tracking and automatic blacklisting
    - Thread-safe proxy selection
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern - one manager across all scrapers."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: str = None):
        """Initialize proxy manager.

        Args:
            config_path: Path to residential_proxies.json
        """
        # Avoid re-initialization of singleton
        if hasattr(self, '_initialized') and self._initialized:
            return

        self.config_path = config_path or os.getenv(
            "RESIDENTIAL_PROXY_FILE",
            "data/residential_proxies.json"
        )
        self.proxies: List[ResidentialProxy] = []
        self.pools: Dict[str, List[ResidentialProxy]] = {}
        self.pool_cursors: Dict[str, int] = {}  # For round-robin
        self._lock = threading.Lock()

        # Load config
        self._load_config()
        self._assign_proxies_to_pools()

        self._initialized = True
        logger.info(f"ResidentialProxyManager initialized with {len(self.proxies)} proxies")

    def _load_config(self):
        """Load proxies from JSON config file."""
        try:
            with open(self.config_path) as f:
                data = json.load(f)

            self.proxies = []
            for p in data.get("proxies", []):
                proxy = ResidentialProxy(
                    host=p.get("host", ""),
                    port=p.get("port", 0),
                    username=p.get("username", ""),
                    password=p.get("password", ""),
                    country_code=p.get("country_code", "US"),
                    city_name=p.get("city_name", ""),
                    state=p.get("state", ""),
                    timezone=p.get("timezone", "America/New_York"),
                    timezone_offset=p.get("timezone_offset", -300),
                    latitude=p.get("latitude", 0.0),
                    longitude=p.get("longitude", 0.0),
                    success_count=p.get("health", {}).get("success_count", 0),
                    failure_count=p.get("health", {}).get("failure_count", 0),
                    last_used=p.get("health", {}).get("last_used"),
                    blacklisted=p.get("health", {}).get("blacklisted", False),
                    blacklist_until=p.get("health", {}).get("blacklist_until"),
                    assigned_pool=p.get("assigned_pool"),
                )
                self.proxies.append(proxy)

            logger.info(f"Loaded {len(self.proxies)} proxies from {self.config_path}")

        except FileNotFoundError:
            logger.warning(f"Proxy config not found: {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to load proxy config: {e}")

    def _assign_proxies_to_pools(self):
        """Assign proxies to directory-specific pools."""
        # Reset pools
        self.pools = {pool: [] for pool in POOL_SIZES.keys()}
        self.pool_cursors = {pool: 0 for pool in POOL_SIZES.keys()}

        # Check if proxies already have pool assignments
        has_assignments = any(p.assigned_pool for p in self.proxies)

        if has_assignments:
            # Use existing assignments
            for proxy in self.proxies:
                if proxy.assigned_pool and proxy.assigned_pool in self.pools:
                    self.pools[proxy.assigned_pool].append(proxy)
        else:
            # Assign based on pool sizes
            proxy_idx = 0
            for pool_name, size in POOL_SIZES.items():
                for _ in range(size):
                    if proxy_idx < len(self.proxies):
                        self.proxies[proxy_idx].assigned_pool = pool_name
                        self.pools[pool_name].append(self.proxies[proxy_idx])
                        proxy_idx += 1

            # Save assignments
            self._save_config()

        # Log pool distribution
        for pool, proxies in self.pools.items():
            logger.info(f"Pool {pool}: {len(proxies)} proxies")

    def _save_config(self):
        """Save current proxy state to JSON file."""
        try:
            with open(self.config_path) as f:
                data = json.load(f)

            # Update proxy entries
            proxy_map = {f"{p.host}:{p.port}": p for p in self.proxies}
            for p in data.get("proxies", []):
                key = f"{p.get('host')}:{p.get('port')}"
                if key in proxy_map:
                    proxy = proxy_map[key]
                    p["health"] = {
                        "success_count": proxy.success_count,
                        "failure_count": proxy.failure_count,
                        "last_used": proxy.last_used,
                        "blacklisted": proxy.blacklisted,
                        "blacklist_until": proxy.blacklist_until,
                    }
                    p["assigned_pool"] = proxy.assigned_pool

            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save proxy config: {e}")

    def get_proxy_for_directory(self, directory: str) -> Optional[ResidentialProxy]:
        """Get next healthy proxy from directory's assigned pool.

        Args:
            directory: Directory name (e.g., 'yellowpages', 'yelp')

        Returns:
            ResidentialProxy or None if no healthy proxies available
        """
        pool_name = DIRECTORY_POOLS.get(directory, "pool_other")
        return self._get_next_proxy_from_pool(pool_name)

    def _get_next_proxy_from_pool(self, pool_name: str) -> Optional[ResidentialProxy]:
        """Get next healthy proxy from pool using round-robin."""
        with self._lock:
            pool = self.pools.get(pool_name, [])
            if not pool:
                return None

            # Try to find a healthy proxy starting from current cursor
            start_idx = self.pool_cursors.get(pool_name, 0)
            for i in range(len(pool)):
                idx = (start_idx + i) % len(pool)
                proxy = pool[idx]
                if proxy.is_healthy:
                    self.pool_cursors[pool_name] = (idx + 1) % len(pool)
                    proxy.last_used = datetime.now().isoformat()
                    return proxy

            # No healthy proxy found
            logger.warning(f"No healthy proxies in pool {pool_name}")
            return None

    def get_proxy_for_state(self, state_code: str) -> Optional[ResidentialProxy]:
        """Get proxy in same state as target (for timezone matching).

        Args:
            state_code: Two-letter state code (e.g., 'TX', 'CA')

        Returns:
            Proxy in that state, or any healthy proxy if no match
        """
        with self._lock:
            # First try exact state match
            for proxy in self.proxies:
                if proxy.state == state_code and proxy.is_healthy:
                    proxy.last_used = datetime.now().isoformat()
                    return proxy

            # Fallback to any healthy proxy
            for proxy in self.proxies:
                if proxy.is_healthy:
                    proxy.last_used = datetime.now().isoformat()
                    return proxy

            return None

    def get_proxy(self) -> Optional[ResidentialProxy]:
        """Get any healthy proxy using round-robin.

        Returns:
            ResidentialProxy or None if no healthy proxies available
        """
        with self._lock:
            if not self.proxies:
                logger.warning("No proxies configured")
                return None

            # Use round-robin cursor across all proxies
            cursor_key = "_global"
            start_idx = self.pool_cursors.get(cursor_key, 0)

            for i in range(len(self.proxies)):
                idx = (start_idx + i) % len(self.proxies)
                proxy = self.proxies[idx]
                if proxy.is_healthy:
                    self.pool_cursors[cursor_key] = (idx + 1) % len(self.proxies)
                    proxy.last_used = datetime.now().isoformat()
                    return proxy

            logger.warning("No healthy proxies available")
            return None

    def get_browser_config(self, proxy: ResidentialProxy) -> Dict[str, Any]:
        """Get complete browser configuration for a proxy.

        Returns dict with:
        - proxy: Playwright-format proxy config
        - timezone: Timezone ID
        - geolocation: {latitude, longitude}
        """
        return {
            "proxy": proxy.to_playwright_format(),
            "timezone_id": proxy.timezone,
            "geolocation": {
                "latitude": proxy.latitude,
                "longitude": proxy.longitude,
                "accuracy": 100,
            }
        }

    def report_success(self, proxy: ResidentialProxy, directory: str = None):
        """Report successful request through proxy."""
        with self._lock:
            proxy.success_count += 1
            proxy.last_used = datetime.now().isoformat()

            # Clear blacklist on success
            if proxy.blacklisted:
                proxy.blacklisted = False
                proxy.blacklist_until = None
                logger.info(f"Proxy {proxy.host} un-blacklisted after success")

        # Periodic save (every 10 successes)
        if proxy.success_count % 10 == 0:
            self._save_config()

    def report_failure(self, proxy: ResidentialProxy, error_type: str, directory: str = None):
        """Report failed request through proxy.

        Args:
            proxy: The proxy that failed
            error_type: Type of error (e.g., 'CAPTCHA', '403', 'timeout')
            directory: Directory being accessed (optional)
        """
        threshold = int(os.getenv("RESIDENTIAL_PROXY_BLACKLIST_THRESHOLD", "5"))
        duration = int(os.getenv("RESIDENTIAL_PROXY_BLACKLIST_DURATION_MINUTES", "120"))

        with self._lock:
            proxy.failure_count += 1
            proxy.last_used = datetime.now().isoformat()

            # Check for blacklisting
            recent_failures = proxy.failure_count - proxy.success_count
            if recent_failures >= threshold and not proxy.blacklisted:
                proxy.blacklisted = True
                proxy.blacklist_until = (datetime.now() + timedelta(minutes=duration)).isoformat()
                logger.warning(f"Proxy {proxy.host} BLACKLISTED for {duration} minutes "
                              f"(type={error_type}, dir={directory})")

        self._save_config()

    def has_healthy_proxies(self, pool_name: str = None) -> bool:
        """Check if there are healthy proxies available.

        Args:
            pool_name: Specific pool to check, or None for any pool
        """
        with self._lock:
            if pool_name:
                pool = self.pools.get(pool_name, [])
                return any(p.is_healthy for p in pool)
            else:
                return any(p.is_healthy for p in self.proxies)

    def has_healthy_proxies_for_directory(self, directory: str) -> bool:
        """Check if there are healthy proxies for a specific directory."""
        pool_name = DIRECTORY_POOLS.get(directory, "pool_other")
        return self.has_healthy_proxies(pool_name)

    def get_stats(self) -> Dict[str, Any]:
        """Get overall proxy pool statistics."""
        with self._lock:
            total = len(self.proxies)
            healthy = sum(1 for p in self.proxies if p.is_healthy)
            blacklisted = sum(1 for p in self.proxies if p.blacklisted)
            total_success = sum(p.success_count for p in self.proxies)
            total_failure = sum(p.failure_count for p in self.proxies)

            pool_stats = {}
            for pool_name, proxies in self.pools.items():
                pool_stats[pool_name] = {
                    "total": len(proxies),
                    "healthy": sum(1 for p in proxies if p.is_healthy),
                    "blacklisted": sum(1 for p in proxies if p.blacklisted),
                }

            return {
                "total_proxies": total,
                "healthy_proxies": healthy,
                "blacklisted_proxies": blacklisted,
                "total_requests": total_success + total_failure,
                "total_success": total_success,
                "total_failure": total_failure,
                "success_rate": total_success / (total_success + total_failure) if (total_success + total_failure) > 0 else 1.0,
                "pools": pool_stats,
            }

    def reset_health(self):
        """Reset all health counters (use after monthly IP rotation)."""
        with self._lock:
            for proxy in self.proxies:
                proxy.success_count = 0
                proxy.failure_count = 0
                proxy.blacklisted = False
                proxy.blacklist_until = None

            self._save_config()
            logger.info("Reset health counters for all proxies")


# Convenience function for getting the singleton instance
def get_residential_proxy_manager() -> ResidentialProxyManager:
    """Get the singleton ResidentialProxyManager instance."""
    return ResidentialProxyManager()
