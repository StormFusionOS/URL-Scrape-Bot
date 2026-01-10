#!/usr/bin/env python3
"""
Test Bing search with Canadian proxy + browser warmup.
"""

import os
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# Target proxy
TARGET_PROXY_IP = "82.23.102.236"

def main():
    print("=" * 60)
    print("BING TEST WITH CANADIAN PROXY + WARMUP")
    print("=" * 60)

    # Import after path setup
    from seo_intelligence.services.residential_proxy_manager import get_residential_proxy_manager
    from seo_intelligence.drivers.seleniumbase_drivers import (
        create_proxy_auth_extension,
        configure_browser_for_proxy,
        set_browser_timezone,
        logger,
    )
    from seleniumbase import SB

    # Get the Canadian proxy
    proxy_manager = get_residential_proxy_manager()

    # Find the Canadian proxy
    canadian_proxy = None
    for proxy in proxy_manager.proxies:
        if proxy.host == TARGET_PROXY_IP:
            canadian_proxy = proxy
            break

    if not canadian_proxy:
        print(f"ERROR: Canadian proxy {TARGET_PROXY_IP} not found in proxy manager!")
        print("Available proxies:")
        for p in proxy_manager.proxies[:5]:
            print(f"  {p.host}:{p.port} - {p.city_name}, {p.state}")
        return

    print(f"\nFound Canadian proxy: {canadian_proxy.host}:{canadian_proxy.port}")
    print(f"  Location: {canadian_proxy.city_name}, {canadian_proxy.state}")
    print(f"  Timezone: {canadian_proxy.timezone}")

    # Create proxy auth extension
    print("\n--- Creating proxy auth extension ---")
    proxy_ext_path = create_proxy_auth_extension(
        canadian_proxy.host,
        canadian_proxy.port,
        canadian_proxy.username,
        canadian_proxy.password
    )
    print(f"Extension created: {proxy_ext_path}")

    # Use SB context manager for clean browser handling
    print("\n--- Starting browser with Canadian proxy ---")

    with SB(uc=True, headless=False, extension_dir=proxy_ext_path) as sb:
        driver = sb.driver

        print("Browser started successfully!")

        # Configure timezone
        try:
            set_browser_timezone(driver, canadian_proxy.timezone)
            print(f"Timezone set to: {canadian_proxy.timezone}")
        except Exception as e:
            print(f"Warning: Could not set timezone: {e}")

        # WARMUP PHASE
        print("\n--- WARMUP PHASE ---")
        warmup_sites = [
            "https://www.wikipedia.org",
            "https://www.reddit.com",
            "https://www.amazon.ca",
            "https://www.cbc.ca",
            "https://weather.gc.ca",
        ]

        for i, site in enumerate(warmup_sites, 1):
            print(f"  [{i}/{len(warmup_sites)}] Warming up: {site}")
            try:
                sb.open(site)
                wait_time = random.uniform(3, 6)
                print(f"      Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                sb.scroll_down(300)
                time.sleep(random.uniform(1, 2))
                print(f"      OK - Title: {sb.get_title()[:50]}...")
            except Exception as e:
                print(f"      WARN: {e}")

        print("\nWarmup complete!")

        # Wait before Bing
        pre_bing_wait = random.uniform(10, 20)
        print(f"\n--- Waiting {pre_bing_wait:.1f}s before Bing test ---")
        time.sleep(pre_bing_wait)

        # BING TEST
        print("\n--- BING SEARCH TEST ---")
        test_query = "weather toronto"
        bing_url = f"https://www.bing.com/search?q={test_query.replace(' ', '+')}"

        print(f"Searching: {bing_url}")
        sb.open(bing_url)
        time.sleep(random.uniform(5, 8))

        html = sb.get_page_source().lower()

        # Check for CAPTCHA
        captcha_indicators = [
            'captcha', 'g-recaptcha', 'hcaptcha', 'cf-challenge',
            'verify you are human', 'unusual traffic'
        ]

        is_blocked = any(ind in html for ind in captcha_indicators)

        if is_blocked:
            print("\n❌ BLOCKED - CAPTCHA detected!")
            sb.save_screenshot("/tmp/bing_blocked.png")
            print("Screenshot saved to /tmp/bing_blocked.png")
        else:
            if 'class="b_algo"' in sb.get_page_source():
                print("\n✅ SUCCESS - Bing search worked!")
                print(f"Page title: {sb.get_title()}")

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(sb.get_page_source(), 'html.parser')
                results = soup.find_all('li', class_='b_algo')
                print(f"Found {len(results)} search results")

                sb.save_screenshot("/tmp/bing_success.png")
                print("Screenshot saved to /tmp/bing_success.png")
            else:
                print("\n⚠️ UNCLEAR - No CAPTCHA but no clear results either")
                sb.save_screenshot("/tmp/bing_unclear.png")
                print("Screenshot saved to /tmp/bing_unclear.png")

        # Try backlink-style query
        print("\n--- TESTING BACKLINK-STYLE QUERY ---")
        time.sleep(random.uniform(15, 25))

        backlink_query = '"example.com"'
        bing_url2 = f"https://www.bing.com/search?q={backlink_query.replace(' ', '+').replace('\"', '%22')}"

        print(f"Searching: {backlink_query}")
        sb.open(bing_url2)
        time.sleep(random.uniform(5, 8))

        html2 = sb.get_page_source().lower()
        is_blocked2 = any(ind in html2 for ind in captcha_indicators)

        if is_blocked2:
            print("❌ BLOCKED on backlink query")
            sb.save_screenshot("/tmp/bing_backlink_blocked.png")
        else:
            print("✅ Backlink-style query worked!")
            sb.save_screenshot("/tmp/bing_backlink_success.png")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
