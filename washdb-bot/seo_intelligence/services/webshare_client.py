"""
Webshare.io API Client

Manages static residential proxy list via Webshare API.
- Fetches proxy list with location data
- Checks proxy pool status
- Triggers refresh after monthly rotation

API Rate Limits:
- General: 180 requests/minute
- Proxy list: 20 requests/minute

Author: WashDB Bot
"""

import os
import json
import requests
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from runner.logging_setup import get_logger

logger = get_logger("webshare_client")


@dataclass
class WebshareProxy:
    """Proxy data from Webshare API."""
    proxy_address: str
    port: int
    username: str
    password: str
    country_code: str = "US"
    city_name: str = ""
    # Additional fields we'll enrich later
    state: str = ""
    timezone: str = ""
    timezone_offset: int = 0
    latitude: float = 0.0
    longitude: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def host(self) -> str:
        """Alias for proxy_address."""
        return self.proxy_address

    def to_connection_string(self) -> str:
        """Format: user:pass@host:port"""
        return f"{self.username}:{self.password}@{self.proxy_address}:{self.port}"

    def to_playwright_format(self) -> Dict[str, str]:
        """Format for Playwright browser context."""
        return {
            "server": f"http://{self.proxy_address}:{self.port}",
            "username": self.username,
            "password": self.password
        }


class WebshareClient:
    """Client for Webshare.io API - manages static residential proxies.

    Usage:
        client = WebshareClient()
        proxies = client.list_proxies()
        status = client.get_proxy_config()
    """

    BASE_URL = "https://proxy.webshare.io/api/v2"

    def __init__(self, api_token: str = None):
        """Initialize Webshare client.

        Args:
            api_token: Webshare API token. If not provided, reads from WEBSHARE_API_TOKEN env var.
        """
        self.api_token = api_token or os.getenv("WEBSHARE_API_TOKEN")
        if not self.api_token:
            raise ValueError("WEBSHARE_API_TOKEN not set")

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {self.api_token}",
            "Content-Type": "application/json"
        })

        logger.info("WebshareClient initialized")

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated request to Webshare API."""
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                logger.warning("Webshare API rate limit hit")
            logger.error(f"Webshare API error: {e}")
            raise

    def list_proxies(self, page: int = 1, page_size: int = 100) -> List[WebshareProxy]:
        """Fetch proxy list from Webshare API.

        Args:
            page: Page number (1-indexed)
            page_size: Number of proxies per page (max 100)

        Returns:
            List of WebshareProxy objects
        """
        all_proxies = []

        while True:
            response = self._request(
                "GET",
                "/proxy/list/",
                params={"mode": "direct", "page": page, "page_size": page_size}
            )
            data = response.json()

            results = data.get("results", [])
            if not results:
                break

            for proxy_data in results:
                proxy = WebshareProxy(
                    proxy_address=proxy_data.get("proxy_address", ""),
                    port=proxy_data.get("port", 0),
                    username=proxy_data.get("username", ""),
                    password=proxy_data.get("password", ""),
                    country_code=proxy_data.get("country_code", "US"),
                    city_name=proxy_data.get("city_name", ""),
                )
                all_proxies.append(proxy)

            # Check if there are more pages
            if not data.get("next"):
                break
            page += 1

        logger.info(f"Fetched {len(all_proxies)} proxies from Webshare API")
        return all_proxies

    def get_proxy_config(self) -> Dict[str, Any]:
        """Get proxy pool configuration and status.

        Returns:
            Dict with proxy config including:
            - proxy_count: Total proxies in pool
            - bandwidth_limit: Monthly bandwidth limit
            - bandwidth_used: Bandwidth used this month
            - etc.
        """
        response = self._request("GET", "/proxy/config/")
        config = response.json()
        logger.info(f"Proxy config: {config.get('proxy_count', 0)} proxies, "
                   f"bandwidth: {config.get('bandwidth_used', 0)}/{config.get('bandwidth_limit', 0)} bytes")
        return config

    def refresh_proxy_list(self) -> bool:
        """Trigger on-demand proxy list refresh.

        Use after monthly IP rotation to get new proxy IPs.

        Returns:
            True if refresh was triggered successfully
        """
        try:
            response = self._request("POST", "/proxy/list/refresh/")
            logger.info("Proxy list refresh triggered")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh proxy list: {e}")
            return False

    def get_proxy_stats(self) -> Dict[str, Any]:
        """Get usage statistics for the proxy pool.

        Returns:
            Dict with usage stats
        """
        try:
            response = self._request("GET", "/proxy/stats/")
            return response.json()
        except Exception as e:
            logger.warning(f"Could not get proxy stats: {e}")
            return {}

    def sync_to_file(self, output_path: str = "data/residential_proxies.json") -> int:
        """Sync proxies from API to local JSON file.

        Args:
            output_path: Path to save proxy data

        Returns:
            Number of proxies synced
        """
        proxies = self.list_proxies()
        config = self.get_proxy_config()

        # Build output structure
        output = {
            "provider": "webshare",
            "proxy_type": "static_residential",
            "last_api_sync": datetime.now().isoformat(),
            "last_geolocation_run": None,
            "api_config": {
                "proxy_count": config.get("proxy_count", 0),
                "bandwidth_limit": config.get("bandwidth_limit", 0),
                "bandwidth_used": config.get("bandwidth_used", 0),
            },
            "proxies": []
        }

        for proxy in proxies:
            proxy_entry = {
                "host": proxy.proxy_address,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
                "country_code": proxy.country_code,
                "city_name": proxy.city_name,
                # These will be filled in by geolocation enrichment
                "state": "",
                "timezone": "",
                "timezone_offset": 0,
                "latitude": 0.0,
                "longitude": 0.0,
                # Health tracking
                "health": {
                    "success_count": 0,
                    "failure_count": 0,
                    "last_used": None,
                    "blacklisted": False,
                    "blacklist_until": None
                },
                # Pool assignment (will be set by manager)
                "assigned_pool": None
            }
            output["proxies"].append(proxy_entry)

        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Write to file
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)

        logger.info(f"Synced {len(proxies)} proxies to {output_path}")
        return len(proxies)


def main():
    """CLI for testing Webshare client."""
    import argparse

    parser = argparse.ArgumentParser(description="Webshare API Client")
    parser.add_argument("--list", action="store_true", help="List all proxies")
    parser.add_argument("--config", action="store_true", help="Show proxy config")
    parser.add_argument("--stats", action="store_true", help="Show usage stats")
    parser.add_argument("--sync", action="store_true", help="Sync to local file")
    parser.add_argument("--output", default="data/residential_proxies.json", help="Output file path")

    args = parser.parse_args()

    try:
        client = WebshareClient()

        if args.list:
            proxies = client.list_proxies()
            print(f"\n{len(proxies)} Proxies:")
            for i, proxy in enumerate(proxies[:10], 1):
                print(f"  {i}. {proxy.proxy_address}:{proxy.port} ({proxy.city_name}, {proxy.country_code})")
            if len(proxies) > 10:
                print(f"  ... and {len(proxies) - 10} more")

        if args.config:
            config = client.get_proxy_config()
            print(f"\nProxy Config:")
            for key, value in config.items():
                print(f"  {key}: {value}")

        if args.stats:
            stats = client.get_proxy_stats()
            print(f"\nProxy Stats:")
            for key, value in stats.items():
                print(f"  {key}: {value}")

        if args.sync:
            count = client.sync_to_file(args.output)
            print(f"\nSynced {count} proxies to {args.output}")

        if not any([args.list, args.config, args.stats, args.sync]):
            # Default: show summary
            config = client.get_proxy_config()
            print(f"\nWebshare Proxy Pool Summary:")
            print(f"  Total proxies: {config.get('proxy_count', 'N/A')}")
            print(f"  Bandwidth used: {config.get('bandwidth_used', 0) / (1024**3):.2f} GB")
            print(f"  Bandwidth limit: {config.get('bandwidth_limit', 0) / (1024**3):.2f} GB")

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
