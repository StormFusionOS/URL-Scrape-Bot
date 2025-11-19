#!/usr/bin/env python3
"""
Test script to capture current Bing Local Search HTML structure.
Saves HTML and screenshot for analysis.
"""

import asyncio
from playwright.async_api import async_playwright
from pathlib import Path
from datetime import datetime

async def test_bing_search():
    """Test a live Bing Local Search and capture HTML/screenshot."""

    # Test query
    search_query = "window cleaning near Providence, RI"

    print(f"Testing Bing search: {search_query}")
    print("=" * 70)

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-web-security',
                '--no-sandbox',
            ]
        )

        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        page = await context.new_page()

        # Navigate to Bing Local Search
        import urllib.parse
        encoded_query = urllib.parse.quote_plus(search_query)
        url = f"https://www.bing.com/local?q={encoded_query}"

        print(f"URL: {url}")
        print("Navigating...")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait a bit for results to load
        await asyncio.sleep(5)

        # Save screenshot
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"logs/bing_test_{timestamp}.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"✓ Screenshot saved: {screenshot_path}")

        # Save HTML
        html = await page.content()
        html_path = f"logs/bing_test_{timestamp}.html"
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"✓ HTML saved: {html_path}")
        print(f"  HTML size: {len(html):,} characters")

        # Try to find business listings with various selectors
        print("\n" + "=" * 70)
        print("Testing selectors:")
        print("=" * 70)

        selectors_to_test = [
            'li.b_algo',
            'div.bm_box',
            'div.localEntityCard',
            'div[data-businessid]',
            'li[data-bm]',
            'div.b_ans',
            'div#local_content',
            'div.lc_content',
            'li.mapscard',
            'div.lclcard',
            'article',
            'div[role="article"]',
            'div.b_tpcn',
            'div.b_factrow',
        ]

        for selector in selectors_to_test:
            try:
                elements = await page.query_selector_all(selector)
                count = len(elements)
                if count > 0:
                    print(f"✓ {selector:40s} → {count} elements")
                    # Get sample text from first element
                    if count > 0:
                        first_elem = elements[0]
                        text = await first_elem.text_content()
                        if text:
                            sample = text.strip()[:100]
                            print(f"  Sample: {sample}...")
                else:
                    print(f"✗ {selector:40s} → 0 elements")
            except Exception as e:
                print(f"✗ {selector:40s} → Error: {e}")

        # Check page title
        title = await page.title()
        print(f"\nPage title: {title}")

        # Check if there's any indication of results
        print("\n" + "=" * 70)
        print("Searching for key content...")
        print("=" * 70)

        keywords = [
            'window cleaning',
            'business',
            'phone',
            'address',
            'website',
            'hours',
            'reviews',
            'No results',
            'Did you mean'
        ]

        for keyword in keywords:
            if keyword.lower() in html.lower():
                count = html.lower().count(keyword.lower())
                print(f"✓ Found '{keyword}': {count} occurrences")
            else:
                print(f"✗ '{keyword}' not found")

        await browser.close()

        print("\n" + "=" * 70)
        print("Test complete!")
        print(f"Files saved in logs/ directory:")
        print(f"  - {screenshot_path}")
        print(f"  - {html_path}")
        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_bing_search())
