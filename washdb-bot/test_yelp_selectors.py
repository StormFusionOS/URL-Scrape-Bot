#!/usr/bin/env python3
"""
Test script to check current Yelp HTML structure and selectors.
This will help us identify the correct selectors for scraping Yelp search results.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from scrape_yelp.yelp_stealth import StealthConfig, get_enhanced_playwright_init_scripts


async def test_yelp_search():
    """Test Yelp search page and identify correct selectors."""

    # Test URL - searching for pressure washing in Los Angeles
    test_url = "https://www.yelp.com/search?find_desc=pressure+washing&find_loc=Los+Angeles%2C+CA"

    print("=" * 80)
    print("Testing Yelp Search Page Selectors")
    print("=" * 80)
    print(f"URL: {test_url}")
    print()

    async with async_playwright() as p:
        # Use stealth configuration
        stealth_config = StealthConfig()

        # Launch browser with stealth settings
        browser = await p.chromium.launch(
            headless=False,  # Set to False to see what's happening
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                f'--window-size={stealth_config.viewport["width"]},{stealth_config.viewport["height"]}',
            ]
        )

        # Create context with stealth settings
        context = await browser.new_context(
            viewport=stealth_config.viewport,
            user_agent=stealth_config.user_agent,
            locale='en-US',
            timezone_id=stealth_config.timezone,
            permissions=[],
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        )

        # Add anti-detection scripts
        init_scripts = get_enhanced_playwright_init_scripts()
        for script in init_scripts:
            await context.add_init_script(script)

        page = await context.new_page()

        try:
            print("Navigating to Yelp search page...")
            await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)

            # Wait a bit for page to fully load
            await asyncio.sleep(3)

            print("\n" + "=" * 80)
            print("PAGE ANALYSIS")
            print("=" * 80)

            # Check page title
            title = await page.title()
            print(f"\nPage Title: {title}")

            # Check if we're being blocked or shown a CAPTCHA
            html_content = await page.content()

            if "captcha" in html_content.lower() or "robot" in html_content.lower():
                print("\n⚠️  WARNING: Possible CAPTCHA or bot detection page!")

            if "challenge" in html_content.lower():
                print("\n⚠️  WARNING: Challenge page detected!")

            # Test various selectors
            print("\n" + "-" * 80)
            print("Testing Selectors:")
            print("-" * 80)

            selectors_to_test = [
                # Current selector
                ('[data-testid="serp-ia-card"]', "Current: data-testid=serp-ia-card"),

                # Alternative Yelp selectors
                ('li[data-testid*="serp"]', "Alternative: li with serp testid"),
                ('div[data-testid*="serp"]', "Alternative: div with serp testid"),
                ('[data-testid*="card"]', "Alternative: any element with card testid"),

                # Common Yelp patterns
                ('li[data-id]', "Yelp pattern: li with data-id"),
                ('article', "Generic: article tags"),
                ('div[class*="container"]', "Generic: container divs"),
                ('[class*="result"]', "Generic: result class"),
                ('[class*="business"]', "Generic: business class"),

                # Link patterns
                ('a[href*="/biz/"]', "Link pattern: /biz/ hrefs"),
            ]

            for selector, description in selectors_to_test:
                try:
                    elements = await page.query_selector_all(selector)
                    count = len(elements)
                    status = "✓" if count > 0 else "✗"
                    print(f"{status} {description:50s} Found: {count:3d} elements")

                    # If we found business links, show a sample
                    if selector == 'a[href*="/biz/"]' and count > 0:
                        first_elem = elements[0]
                        text = await first_elem.inner_text()
                        href = await first_elem.get_attribute('href')
                        print(f"  Sample: '{text[:50]}...' -> {href[:60]}...")

                except Exception as e:
                    print(f"✗ {description:50s} Error: {e}")

            # Save HTML for manual inspection
            html_path = "debug_yelp_search.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"\n✓ Full HTML saved to: {html_path}")

            # Take a screenshot
            screenshot_path = "debug_yelp_search.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"✓ Screenshot saved to: {screenshot_path}")

            # Try to extract business cards with various methods
            print("\n" + "-" * 80)
            print("Attempting to Extract Business Information:")
            print("-" * 80)

            # Method 1: Look for links with /biz/
            biz_links = await page.query_selector_all('a[href*="/biz/"]')
            print(f"\nFound {len(biz_links)} business links")

            if biz_links:
                print("\nFirst 3 businesses:")
                for idx, link in enumerate(biz_links[:3]):
                    try:
                        name = await link.inner_text()
                        href = await link.get_attribute('href')
                        print(f"  {idx+1}. {name}")
                        print(f"     URL: https://www.yelp.com{href}")
                    except:
                        pass

            print("\n" + "=" * 80)
            print("RECOMMENDATIONS:")
            print("=" * 80)

            # Analyze and provide recommendations
            if len(biz_links) > 0:
                print("\n✓ Business links found! The page loaded successfully.")
                print("  → We need to find the correct parent container selector")
                print("  → Try inspecting the HTML structure around business links")
            else:
                print("\n✗ No business links found!")
                print("  → Yelp may be blocking or showing a different page")
                print("  → Check the saved HTML and screenshot")

            # Wait for user to inspect browser
            print("\n" + "=" * 80)
            print("Browser will stay open for 30 seconds for manual inspection...")
            print("Check the browser window to see what Yelp is showing")
            print("=" * 80)
            await asyncio.sleep(30)

        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


if __name__ == "__main__":
    print("\nStarting Yelp selector test...")
    print("This will open a browser window to test Yelp search page\n")

    asyncio.run(test_yelp_search())

    print("\n✓ Test complete!")
    print("\nNext steps:")
    print("1. Check debug_yelp_search.html for the actual HTML structure")
    print("2. Check debug_yelp_search.png for visual confirmation")
    print("3. Update selectors in scrape_yelp/yelp_parse.py based on findings")
