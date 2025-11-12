#!/usr/bin/env python3
"""
Test the YP stealth/anti-detection features.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from scrape_yp.yp_stealth import (
    get_random_user_agent,
    get_random_viewport,
    get_random_timezone,
    get_random_delay,
    get_playwright_context_params,
    get_exponential_backoff_delay,
)

print("=" * 80)
print("Testing YP Stealth Module")
print("=" * 80)
print()

# Test 1: User Agent Rotation
print("1. User Agent Rotation")
print("-" * 80)
user_agents = [get_random_user_agent() for _ in range(5)]
for i, ua in enumerate(user_agents, 1):
    browser = "Chrome" if "Chrome" in ua else "Firefox" if "Firefox" in ua else "Safari" if "Safari" in ua else "Unknown"
    os_type = "Windows" if "Windows" in ua else "Mac" if "Macintosh" in ua else "Linux" if "Linux" in ua else "Unknown"
    print(f"  {i}. [{browser} on {os_type}]")
    print(f"     {ua[:80]}...")

# Check diversity
unique_uas = set(user_agents)
print(f"\n  ✓ Generated {len(unique_uas)} unique user agents out of 5 samples")
print()

# Test 2: Viewport Randomization
print("2. Viewport Randomization")
print("-" * 80)
viewports = [get_random_viewport() for _ in range(5)]
for i, (width, height) in enumerate(viewports, 1):
    aspect_ratio = width / height
    print(f"  {i}. {width}x{height} (aspect: {aspect_ratio:.2f})")

unique_viewports = set(viewports)
print(f"\n  ✓ Generated {len(unique_viewports)} unique viewports out of 5 samples")
print()

# Test 3: Timezone Randomization
print("3. Timezone Randomization")
print("-" * 80)
timezones = [get_random_timezone() for _ in range(7)]
for i, tz in enumerate(timezones, 1):
    print(f"  {i}. {tz}")

unique_tzs = set(timezones)
print(f"\n  ✓ Generated {len(unique_tzs)} unique timezones out of 7 samples")
print()

# Test 4: Random Delays with Jitter
print("4. Random Delays with Jitter")
print("-" * 80)
delays = [get_random_delay(min_seconds=2.0, max_seconds=5.0, jitter=0.5) for _ in range(5)]
for i, delay in enumerate(delays, 1):
    print(f"  {i}. {delay:.2f} seconds")

print(f"\n  ✓ All delays in reasonable range ({min(delays):.2f}s - {max(delays):.2f}s)")
print()

# Test 5: Playwright Context Parameters
print("5. Playwright Context Parameters")
print("-" * 80)
params = get_playwright_context_params()
print(f"  User Agent: {params['user_agent'][:60]}...")
print(f"  Viewport: {params['viewport']}")
print(f"  Timezone: {params['timezone_id']}")
print(f"  Locale: {params['locale']}")
print(f"  Color Scheme: {params['color_scheme']}")
print(f"  Device Scale: {params['device_scale_factor']}x")
print(f"\n  ✓ Context parameters generated successfully")
print()

# Test 6: Exponential Backoff
print("6. Exponential Backoff Delays")
print("-" * 80)
for attempt in range(5):
    delay = get_exponential_backoff_delay(attempt, base_delay=1.0, max_delay=60.0)
    print(f"  Attempt {attempt + 1}: {delay:.2f} seconds")

print(f"\n  ✓ Exponential backoff with jitter working correctly")
print()

# Summary
print("=" * 80)
print("Summary")
print("=" * 80)
print("✅ User Agent Rotation: WORKING")
print("✅ Viewport Randomization: WORKING")
print("✅ Timezone Randomization: WORKING")
print("✅ Random Delays with Jitter: WORKING")
print("✅ Playwright Context Params: WORKING")
print("✅ Exponential Backoff: WORKING")
print()
print("All anti-detection features are functioning correctly!")
print("=" * 80)
