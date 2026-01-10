#!/usr/bin/env python3
"""
Sync and Enrich Webshare Proxies

This script:
1. Fetches proxies from Webshare API
2. Enriches them with timezone and GPS coordinates via IP geolocation
3. Saves to data/residential_proxies.json

Run after:
- Initial proxy purchase
- Monthly IP rotation by Webshare

Usage:
    python scripts/sync_webshare_proxies.py
    python scripts/sync_webshare_proxies.py --skip-geolocation  # Skip slow geolocation
    python scripts/sync_webshare_proxies.py --test-proxy 0      # Test first proxy

Author: WashDB Bot
"""

import os
import sys
import json
import time
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

import requests

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from seo_intelligence.services.webshare_client import WebshareClient


# State to timezone mapping
STATE_TIMEZONES = {
    # Eastern Time
    'CT': 'America/New_York', 'DE': 'America/New_York', 'FL': 'America/New_York',
    'GA': 'America/New_York', 'IN': 'America/Indiana/Indianapolis', 'KY': 'America/New_York',
    'ME': 'America/New_York', 'MD': 'America/New_York', 'MA': 'America/New_York',
    'MI': 'America/Detroit', 'NH': 'America/New_York', 'NJ': 'America/New_York',
    'NY': 'America/New_York', 'NC': 'America/New_York', 'OH': 'America/New_York',
    'PA': 'America/New_York', 'RI': 'America/New_York', 'SC': 'America/New_York',
    'VT': 'America/New_York', 'VA': 'America/New_York', 'WV': 'America/New_York',
    'DC': 'America/New_York',
    # Central Time
    'AL': 'America/Chicago', 'AR': 'America/Chicago', 'IL': 'America/Chicago',
    'IA': 'America/Chicago', 'KS': 'America/Chicago', 'LA': 'America/Chicago',
    'MN': 'America/Chicago', 'MS': 'America/Chicago', 'MO': 'America/Chicago',
    'NE': 'America/Chicago', 'ND': 'America/Chicago', 'OK': 'America/Chicago',
    'SD': 'America/Chicago', 'TN': 'America/Chicago', 'TX': 'America/Chicago',
    'WI': 'America/Chicago',
    # Mountain Time
    'AZ': 'America/Phoenix', 'CO': 'America/Denver', 'ID': 'America/Boise',
    'MT': 'America/Denver', 'NM': 'America/Denver', 'UT': 'America/Denver',
    'WY': 'America/Denver', 'NV': 'America/Los_Angeles',
    # Pacific Time
    'CA': 'America/Los_Angeles', 'OR': 'America/Los_Angeles', 'WA': 'America/Los_Angeles',
    # Other
    'AK': 'America/Anchorage', 'HI': 'Pacific/Honolulu',
}

# Timezone to offset (minutes from UTC, standard time)
TIMEZONE_OFFSETS = {
    'America/New_York': -300,      # EST: UTC-5
    'America/Chicago': -360,       # CST: UTC-6
    'America/Denver': -420,        # MST: UTC-7
    'America/Los_Angeles': -480,   # PST: UTC-8
    'America/Phoenix': -420,       # MST (no DST)
    'America/Anchorage': -540,     # AKST: UTC-9
    'Pacific/Honolulu': -600,      # HST: UTC-10
    'America/Detroit': -300,
    'America/Indiana/Indianapolis': -300,
    'America/Boise': -420,
}

# City to state mapping (for common cities from Webshare)
CITY_STATE_MAP = {
    'Ashburn': 'VA',
    'Boston': 'MA',
    'Sacramento': 'CA',
    'Verona': 'NJ',  # Verona, NJ is common for ISP proxies
    'Los Angeles': 'CA',
    'New York': 'NY',
    'Chicago': 'IL',
    'Houston': 'TX',
    'Phoenix': 'AZ',
    'Philadelphia': 'PA',
    'San Antonio': 'TX',
    'San Diego': 'CA',
    'Dallas': 'TX',
    'San Jose': 'CA',
    'Austin': 'TX',
    'Jacksonville': 'FL',
    'Fort Worth': 'TX',
    'Columbus': 'OH',
    'Charlotte': 'NC',
    'Indianapolis': 'IN',
    'Seattle': 'WA',
    'Denver': 'CO',
    'Washington': 'DC',
    'El Paso': 'TX',
    'Nashville': 'TN',
    'Detroit': 'MI',
    'Oklahoma City': 'OK',
    'Portland': 'OR',
    'Las Vegas': 'NV',
    'Memphis': 'TN',
    'Louisville': 'KY',
    'Baltimore': 'MD',
    'Milwaukee': 'WI',
    'Albuquerque': 'NM',
    'Tucson': 'AZ',
    'Fresno': 'CA',
    'Mesa': 'AZ',
    'Atlanta': 'GA',
    'Kansas City': 'MO',
    'Colorado Springs': 'CO',
    'Miami': 'FL',
    'Raleigh': 'NC',
    'Omaha': 'NE',
    'Long Beach': 'CA',
    'Virginia Beach': 'VA',
    'Oakland': 'CA',
    'Minneapolis': 'MN',
    'Tulsa': 'OK',
    'Tampa': 'FL',
    'Arlington': 'TX',
    'New Orleans': 'LA',
}


def infer_state_from_city(city_name: str) -> Optional[str]:
    """Try to infer state from city name."""
    return CITY_STATE_MAP.get(city_name)


def get_timezone_for_state(state: str) -> tuple:
    """Get timezone and offset for a state code."""
    timezone = STATE_TIMEZONES.get(state, 'America/New_York')
    offset = TIMEZONE_OFFSETS.get(timezone, -300)
    return timezone, offset


def geolocate_via_proxy(proxy_host: str, proxy_port: int, username: str, password: str) -> Dict:
    """
    Get geolocation by making a request through the proxy to ipapi.co.

    Returns dict with: timezone, state, latitude, longitude
    """
    proxy_url = f"http://{username}:{password}@{proxy_host}:{proxy_port}"
    proxies = {
        "http": proxy_url,
        "https": proxy_url
    }

    try:
        response = requests.get(
            "https://ipapi.co/json/",
            proxies=proxies,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        return {
            "timezone": data.get("timezone", ""),
            "state": data.get("region_code", ""),
            "latitude": data.get("latitude", 0.0),
            "longitude": data.get("longitude", 0.0),
            "city": data.get("city", ""),
            "country": data.get("country_code", "US"),
        }
    except Exception as e:
        print(f"  Geolocation failed for {proxy_host}: {e}")
        return {}


def enrich_proxy(proxy_data: Dict, use_api_geolocation: bool = True) -> Dict:
    """
    Enrich a proxy entry with timezone and GPS data.

    Args:
        proxy_data: Proxy dict from residential_proxies.json
        use_api_geolocation: If True, call ipapi.co through proxy (slow but accurate)

    Returns:
        Updated proxy_data with timezone, state, latitude, longitude
    """
    city = proxy_data.get("city_name", "")
    state = proxy_data.get("state", "")

    # Try to infer state from city if not set
    if not state and city:
        state = infer_state_from_city(city)
        if state:
            proxy_data["state"] = state
            print(f"  Inferred state {state} from city {city}")

    # If we have state, set timezone from lookup table
    if state:
        timezone, offset = get_timezone_for_state(state)
        proxy_data["timezone"] = timezone
        proxy_data["timezone_offset"] = offset

    # Use API geolocation for accurate lat/lon (and to verify timezone)
    if use_api_geolocation:
        geo = geolocate_via_proxy(
            proxy_data["host"],
            proxy_data["port"],
            proxy_data["username"],
            proxy_data["password"]
        )
        if geo:
            proxy_data["latitude"] = geo.get("latitude", 0.0)
            proxy_data["longitude"] = geo.get("longitude", 0.0)
            # Use API timezone if available (more accurate)
            if geo.get("timezone"):
                proxy_data["timezone"] = geo["timezone"]
                proxy_data["timezone_offset"] = TIMEZONE_OFFSETS.get(
                    geo["timezone"],
                    proxy_data.get("timezone_offset", -300)
                )
            # Use API state if we didn't have one
            if not state and geo.get("state"):
                proxy_data["state"] = geo["state"]

    return proxy_data


def main():
    parser = argparse.ArgumentParser(description="Sync and enrich Webshare proxies")
    parser.add_argument("--skip-geolocation", action="store_true",
                       help="Skip slow IP geolocation API calls")
    parser.add_argument("--test-proxy", type=int, default=None,
                       help="Test a specific proxy by index (0-based)")
    parser.add_argument("--output", default="data/residential_proxies.json",
                       help="Output file path")
    parser.add_argument("--sync-only", action="store_true",
                       help="Only sync from API, don't enrich")

    args = parser.parse_args()

    print("=" * 60)
    print("Webshare Proxy Sync & Enrich")
    print("=" * 60)

    # Step 1: Sync from Webshare API
    print("\n[1/3] Syncing proxies from Webshare API...")
    try:
        client = WebshareClient()
        count = client.sync_to_file(args.output)
        print(f"  Synced {count} proxies")
    except Exception as e:
        print(f"  ERROR: Failed to sync from API: {e}")
        return 1

    if args.sync_only:
        print("\nDone (sync only mode)")
        return 0

    # Step 2: Load and enrich
    print(f"\n[2/3] Loading proxies from {args.output}...")
    with open(args.output) as f:
        data = json.load(f)

    proxies = data.get("proxies", [])
    print(f"  Loaded {len(proxies)} proxies")

    # Step 3: Enrich with geolocation
    print(f"\n[3/3] Enriching proxies with location data...")
    use_api = not args.skip_geolocation

    if args.test_proxy is not None:
        # Test single proxy
        idx = args.test_proxy
        if 0 <= idx < len(proxies):
            print(f"\n  Testing proxy {idx}: {proxies[idx]['host']}:{proxies[idx]['port']}")
            proxies[idx] = enrich_proxy(proxies[idx], use_api_geolocation=True)
            print(f"  Result: {proxies[idx].get('city_name')} {proxies[idx].get('state')} "
                  f"TZ={proxies[idx].get('timezone')} "
                  f"lat={proxies[idx].get('latitude'):.4f} lon={proxies[idx].get('longitude'):.4f}")
        else:
            print(f"  ERROR: Invalid proxy index {idx}")
            return 1
    else:
        # Enrich all proxies
        for i, proxy in enumerate(proxies):
            print(f"  [{i+1}/{len(proxies)}] {proxy['host']}:{proxy['port']} ({proxy.get('city_name', 'unknown')})")
            proxies[i] = enrich_proxy(proxy, use_api_geolocation=use_api)

            if use_api:
                # Rate limit for ipapi.co (free tier: 1000/day, ~45/hour)
                time.sleep(2)

    # Update metadata
    data["proxies"] = proxies
    data["last_geolocation_run"] = datetime.now().isoformat()

    # Save
    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Done! Saved {len(proxies)} proxies to {args.output}")

    # Summary
    states = {}
    for p in proxies:
        s = p.get("state", "unknown")
        states[s] = states.get(s, 0) + 1

    print("\nProxy distribution by state:")
    for state, count in sorted(states.items(), key=lambda x: -x[1])[:10]:
        print(f"  {state}: {count}")

    return 0


if __name__ == "__main__":
    exit(main())
