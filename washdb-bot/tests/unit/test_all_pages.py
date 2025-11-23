#!/usr/bin/env python3
"""
Comprehensive test to validate all pages can be imported and don't have obvious errors.
"""

import sys
sys.path.insert(0, '/home/rivercityscrape/URL-Scrape-Bot/washdb-bot')

print("=" * 70)
print("TESTING ALL PAGES AND FEATURES")
print("=" * 70)

# Test 1: Import all modules
print("\n1. Testing module imports...")
try:
    from niceui import pages
    from niceui.router import router, event_bus
    from niceui.layout import layout
    from niceui.config_manager import config_manager
    from niceui.backend_facade import backend
    print("   ✓ All modules imported successfully")
except Exception as e:
    print(f"   ✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Check event bus functionality
print("\n2. Testing SimpleEventBus...")
try:
    test_called = []
    def test_callback(data=None):
        test_called.append(data)

    event_bus.subscribe('test_event', test_callback)
    event_bus.publish('test_event', 'test_data')
    event_bus.publish('test_event')  # Without data

    assert len(test_called) == 2
    assert test_called[0] == 'test_data'
    print("   ✓ EventBus publish/subscribe works")
except Exception as e:
    print(f"   ✗ EventBus test failed: {e}")

# Test 3: Check router
print("\n3. Testing Router...")
try:
    assert 'dashboard' in router.pages
    assert 'discover' in router.pages
    assert 'scrape' in router.pages
    assert 'single_url' in router.pages
    assert 'database' in router.pages
    assert 'logs' in router.pages
    assert 'settings' in router.pages
    print("   ✓ All pages registered with router")
except Exception as e:
    print(f"   ✗ Router test failed: {e}")

# Test 4: Check config manager
print("\n4. Testing ConfigManager...")
try:
    theme_mode = config_manager.get('theme', 'mode')
    primary_color = config_manager.get('theme', 'primary_color')
    log_dir = config_manager.get('paths', 'log_dir')
    crawl_delay = config_manager.get('defaults', 'crawl_delay')

    print(f"   Theme mode: {theme_mode}")
    print(f"   Primary color: {primary_color}")
    print(f"   Log directory: {log_dir}")
    print(f"   Crawl delay: {crawl_delay}")
    print("   ✓ ConfigManager working")
except Exception as e:
    print(f"   ✗ ConfigManager test failed: {e}")

# Test 5: Check backend facade methods exist
print("\n5. Testing Backend Facade...")
try:
    methods = [
        'kpis', 'check_database_connection', 'get_scrape_status',
        'discover_categories_states', 'scrape_batch', 'stop_scrape',
        'scrape_one_preview', 'upsert_from_scrape', 'get_companies',
        'get_recent_logs'
    ]
    for method in methods:
        assert hasattr(backend, method), f"Missing method: {method}"
    print(f"   ✓ All {len(methods)} backend methods present")
except Exception as e:
    print(f"   ✗ Backend facade test failed: {e}")

# Test 6: Check layout components
print("\n6. Testing Layout Components...")
try:
    assert hasattr(layout, 'show_busy'), "Missing show_busy method"
    assert hasattr(layout, 'hide_busy'), "Missing hide_busy method"
    assert layout.version is not None, "Version not set"
    print(f"   Version: {layout.version}")
    print("   ✓ Layout components present")
except Exception as e:
    print(f"   ✗ Layout test failed: {e}")

# Test 7: Check static files exist
print("\n7. Testing Static Files...")
try:
    import os
    static_files = [
        'niceui/static/css/custom.css',
        'niceui/static/favicon.svg'
    ]
    for file in static_files:
        assert os.path.exists(file), f"Missing: {file}"
    print(f"   ✓ All {len(static_files)} static files present")
except Exception as e:
    print(f"   ✗ Static files test failed: {e}")

# Test 8: Check custom.css has purple theme
print("\n8. Testing Custom CSS...")
try:
    with open('niceui/static/css/custom.css') as f:
        css_content = f.read()
    assert '#8b5cf6' in css_content, "Purple color not found"
    assert 'nav-item-active' in css_content, "Active nav style not found"
    assert 'busy-overlay' in css_content, "Busy overlay not found"
    assert 'busy-spinner' in css_content, "Busy spinner not found"
    print("   ✓ Custom CSS contains all required styles")
except Exception as e:
    print(f"   ✗ CSS test failed: {e}")

# Test 9: Check main.py has favicon
print("\n9. Testing Main Configuration...")
try:
    with open('niceui/main.py') as f:
        main_content = f.read()
    assert 'favicon' in main_content, "Favicon not configured"
    print("   ✓ Main.py configured with favicon")
except Exception as e:
    print(f"   ✗ Main.py test failed: {e}")

# Test 10: Check GUI is running
print("\n10. Testing GUI Status...")
try:
    import subprocess
    result = subprocess.run(['lsof', '-i', ':8080'], capture_output=True, text=True)
    if result.returncode == 0:
        print("   ✓ GUI is running on port 8080")
        print(f"   URL: http://127.0.0.1:8080")
    else:
        print("   ✗ GUI not detected on port 8080")
except Exception as e:
    print(f"   ✗ GUI status check failed: {e}")

print("\n" + "=" * 70)
print("ALL TESTS COMPLETED")
print("=" * 70)
print("\nManual Testing Required:")
print("  1. Open http://127.0.0.1:8080 in browser")
print("  2. Check purple theme and active nav highlighting")
print("  3. Test Run/Stop buttons (should show notifications)")
print("  4. Navigate through all pages")
print("  5. Check favicon in browser tab")
print("=" * 70)
