#!/usr/bin/env python3
"""
Test script to verify HomeAdvisor integration.

This tests that the HA scraper modules can be imported and basic functionality works.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all HomeAdvisor modules can be imported."""
    print("=" * 70)
    print("Testing HomeAdvisor Integration")
    print("=" * 70)
    print()

    print("1. Testing imports...")
    try:
        from scrape_ha.ha_client import build_search_url, fetch_url, parse_list_page, parse_profile_for_company
        print("   ✓ ha_client imports successful")
    except Exception as e:
        print(f"   ✗ ha_client import failed: {e}")
        return False

    try:
        from scrape_ha.ha_crawl import crawl_category_state, crawl_all_states, CATEGORIES_HA
        print("   ✓ ha_crawl imports successful")
    except Exception as e:
        print(f"   ✗ ha_crawl import failed: {e}")
        return False

    try:
        from niceui.backend_facade import backend
        print("   ✓ backend_facade imports successful")
    except Exception as e:
        print(f"   ✗ backend_facade import failed: {e}")
        return False

    print()
    print("2. Testing database model...")
    try:
        from db.models import Company
        # Check if rating_ha and reviews_ha attributes exist
        company = Company.__table__.columns
        has_rating_ha = 'rating_ha' in company
        has_reviews_ha = 'reviews_ha' in company

        if has_rating_ha and has_reviews_ha:
            print("   ✓ Company model has rating_ha and reviews_ha columns")
        else:
            print(f"   ✗ Missing columns: rating_ha={has_rating_ha}, reviews_ha={has_reviews_ha}")
            return False
    except Exception as e:
        print(f"   ✗ Database model check failed: {e}")
        return False

    print()
    print("3. Testing URL building...")
    try:
        from scrape_ha.ha_client import build_search_url
        url = build_search_url("pressure washing", "WA", 1)
        print(f"   ✓ Built search URL: {url}")
    except Exception as e:
        print(f"   ✗ URL building failed: {e}")
        return False

    print()
    print("4. Testing backend discover method signature...")
    try:
        import inspect
        sig = inspect.signature(backend.discover)
        params = list(sig.parameters.keys())
        has_providers = 'providers' in params

        if has_providers:
            print(f"   ✓ backend.discover has 'providers' parameter")
            print(f"   Parameters: {', '.join(params)}")
        else:
            print(f"   ✗ backend.discover missing 'providers' parameter")
            print(f"   Parameters: {', '.join(params)}")
            return False
    except Exception as e:
        print(f"   ✗ Backend signature check failed: {e}")
        return False

    print()
    print("5. Checking HA categories...")
    try:
        from scrape_ha.ha_crawl import CATEGORIES_HA
        print(f"   ✓ HA Categories: {', '.join(CATEGORIES_HA)}")
    except Exception as e:
        print(f"   ✗ Category check failed: {e}")
        return False

    print()
    print("=" * 70)
    print("All integration tests passed!")
    print("=" * 70)
    print()
    print("NEXT STEPS:")
    print("1. The UI in niceui/pages/discover.py calls backend.discover_yellow_pages")
    print("   which doesn't exist. Update it to call backend.discover with providers=['YP']")
    print("2. Add a provider selector UI (checkboxes for YP and HA)")
    print("3. Test end-to-end by running: python -m niceui.main")
    print()

    return True


if __name__ == '__main__':
    try:
        success = test_imports()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
