#!/usr/bin/env python3
"""
Test HomeAdvisor browser scraping.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_browser_scraping():
    """Test fetching HomeAdvisor page with browser automation."""
    print("=" * 70)
    print("Testing HomeAdvisor Browser Scraping")
    print("=" * 70)
    print()

    print("1. Testing imports...")
    try:
        from scrape_ha.ha_client import build_search_url, fetch_url, parse_list_page
        from scrape_ha.ha_browser import HomeAdvisorBrowser
        print("   ✓ Imports successful")
    except Exception as e:
        print(f"   ✗ Import failed: {e}")
        return False

    print()
    print("2. Building search URL...")
    try:
        url = build_search_url("pressure washing", "WA", 1)
        print(f"   ✓ URL: {url}")
    except Exception as e:
        print(f"   ✗ URL building failed: {e}")
        return False

    print()
    print("3. Fetching page with browser (this will take 5-10 seconds)...")
    try:
        html = fetch_url(url)
        if html:
            print(f"   ✓ Page fetched: {len(html)} characters")
        else:
            print("   ✗ No HTML returned")
            return False
    except Exception as e:
        print(f"   ✗ Fetch failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print("4. Parsing page...")
    try:
        cards = parse_list_page(html)
        print(f"   ✓ Found {len(cards)} business cards")
        if cards:
            print(f"\n   First card:")
            for key, value in list(cards[0].items())[:5]:
                print(f"      {key}: {value}")
    except Exception as e:
        print(f"   ✗ Parsing failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print("=" * 70)
    if len(cards) > 0:
        print("✓ Browser scraping test PASSED!")
        print(f"Successfully extracted {len(cards)} businesses")
    else:
        print("⚠ Test completed but found 0 businesses")
        print("This may indicate the page structure has changed")
    print("=" * 70)
    print()

    return len(cards) > 0


if __name__ == '__main__':
    try:
        success = test_browser_scraping()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
