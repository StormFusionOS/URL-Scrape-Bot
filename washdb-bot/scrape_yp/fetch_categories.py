#!/usr/bin/env python3
"""
Fetch Yellow Pages category list using Playwright.
"""

from playwright.sync_api import sync_playwright
import json
import time


def fetch_yp_categories():
    """Fetch Yellow Pages categories from their browse page."""

    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )

        # Create context with realistic settings
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            locale='en-US',
            timezone_id='America/New_York',
        )

        # Create page
        page = context.new_page()

        # Try to fetch the browse/categories page
        urls_to_try = [
            'https://www.yellowpages.com/browse',
            'https://www.yellowpages.com/categories',
            'https://www.yellowpages.com',
        ]

        categories = []

        for url in urls_to_try:
            print(f"\nTrying: {url}")
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                time.sleep(2)  # Wait for dynamic content

                # Get page content
                content = page.content()

                # Look for category links
                # Try multiple selectors
                selectors = [
                    'a[href*="/browse/"]',
                    'a[href*="search_terms"]',
                    '.category a',
                    '.categories a',
                    'nav a',
                ]

                for selector in selectors:
                    try:
                        elements = page.query_selector_all(selector)
                        print(f"  Found {len(elements)} elements with selector: {selector}")

                        for elem in elements[:50]:  # Limit to first 50
                            text = elem.text_content()
                            href = elem.get_attribute('href')
                            if text and text.strip():
                                categories.append({
                                    'name': text.strip(),
                                    'href': href
                                })
                    except Exception as e:
                        print(f"  Error with selector {selector}: {e}")
                        continue

                if categories:
                    break

            except Exception as e:
                print(f"  Error: {e}")
                continue

        browser.close()

        # Deduplicate by name
        seen = set()
        unique_categories = []
        for cat in categories:
            name_lower = cat['name'].lower()
            if name_lower not in seen and len(name_lower) > 2:
                seen.add(name_lower)
                unique_categories.append(cat)

        return unique_categories


if __name__ == '__main__':
    print("=" * 60)
    print("Yellow Pages Category Fetcher")
    print("=" * 60)

    categories = fetch_yp_categories()

    print(f"\nFound {len(categories)} unique categories:")
    print("=" * 60)

    # Filter for relevant service categories
    service_keywords = [
        'wash', 'clean', 'pressure', 'power', 'window',
        'deck', 'fence', 'paint', 'restore', 'stain',
        'roof', 'gutter', 'house', 'home', 'maintenance',
        'exterior', 'concrete', 'driveway', 'siding'
    ]

    relevant = []
    for cat in categories:
        name_lower = cat['name'].lower()
        if any(keyword in name_lower for keyword in service_keywords):
            relevant.append(cat['name'])

    if relevant:
        print("\nRelevant categories found:")
        for name in sorted(relevant)[:30]:
            print(f"  - {name}")

    # Save all categories to file
    with open('data/yp_categories.json', 'w') as f:
        json.dump(categories, f, indent=2)

    print(f"\nAll categories saved to: data/yp_categories.json")
    print("=" * 60)
