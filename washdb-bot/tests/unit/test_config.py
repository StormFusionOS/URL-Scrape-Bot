#!/usr/bin/env python3
"""
Test script to validate config manager functionality.
"""

import sys
sys.path.insert(0, '/home/rivercityscrape/URL-Scrape-Bot/washdb-bot')

from niceui.config_manager import config_manager
import json

print("=" * 60)
print("CONFIG MANAGER TEST")
print("=" * 60)

# Test 1: Read current config
print("\n1. Current configuration:")
print(json.dumps(config_manager.config, indent=2))

# Test 2: Get specific values
print("\n2. Get specific values:")
print(f"   Theme mode: {config_manager.get('theme', 'mode')}")
print(f"   Primary color: {config_manager.get('theme', 'primary_color')}")
print(f"   Log directory: {config_manager.get('paths', 'log_dir')}")
print(f"   Crawl delay: {config_manager.get('defaults', 'crawl_delay')}")

# Test 3: Update a section (test theme change)
print("\n3. Testing theme update (changing to blue theme)...")
test_theme = {
    'mode': 'dark',
    'primary_color': '#3b82f6',  # Blue instead of purple
    'accent_color': '#60a5fa',   # Light blue
}
success = config_manager.update_section('theme', test_theme)
print(f"   Update successful: {success}")
print(f"   New primary color: {config_manager.get('theme', 'primary_color')}")

# Test 4: Verify persistence by reloading
print("\n4. Testing persistence (reload config from file)...")
config_manager.config = config_manager.load()
print(f"   Primary color after reload: {config_manager.get('theme', 'primary_color')}")
print(f"   ✓ Theme persisted correctly!" if config_manager.get('theme', 'primary_color') == '#3b82f6' else "   ✗ Persistence failed")

# Test 5: Update default values
print("\n5. Testing default values update...")
test_defaults = {
    'crawl_delay': 2.0,
    'pages_per_pair': 3,
    'stale_days': 45,
    'default_limit': 200,
}
success = config_manager.update_section('defaults', test_defaults)
print(f"   Update successful: {success}")
print(f"   New crawl delay: {config_manager.get('defaults', 'crawl_delay')}")
print(f"   New default limit: {config_manager.get('defaults', 'default_limit')}")

# Test 6: Reset to defaults
print("\n6. Testing reset to defaults...")
success = config_manager.reset_to_defaults()
print(f"   Reset successful: {success}")
print(f"   Primary color after reset: {config_manager.get('theme', 'primary_color')}")
print(f"   Crawl delay after reset: {config_manager.get('defaults', 'crawl_delay')}")
print(f"   ✓ Reset to purple theme!" if config_manager.get('theme', 'primary_color') == '#8b5cf6' else "   ✗ Reset failed")

print("\n" + "=" * 60)
print("ALL TESTS COMPLETED")
print("=" * 60)
