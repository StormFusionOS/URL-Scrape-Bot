#!/usr/bin/env python3
"""
Final Yelp test with optimized settings.
Tests if enhanced measures help even with Chromium.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from scrape_yelp.yelp_stealth import StealthConfig, get_enhanced_playwright_init_scripts
from scrape_yelp.yelp_datadome_bypass import MouseSimulator, DataDomeBypass


async def test_yelp_final():
    """Final optimized test."""

    test_url = "https://www.yelp.com/search?find_desc=pressure+washing&find_loc=Los+Angeles%2C+CA"

    print("=" * 80)
    print("FINAL OPTIMIZED YELP TEST")
    print("=" * 80)
    print(f"URL: {test_url}\n")

    async with async_playwright() as p:
        stealth_config = StealthConfig()

        print("Launching Chromium with all enhancements...")
        browser = await p.chromium.launch(
            headless=True,
            args=DataDomeBypass.get_enhanced_chrome_args()
        )

        enhanced_headers = DataDomeBypass.get_enhanced_headers()

        context = await browser.new_context(
            viewport=stealth_config.viewport,
            user_agent=stealth_config.user_agent,
            locale='en-US',
            timezone_id=stealth_config.timezone,
            permissions=[],
            extra_http_headers=enhanced_headers,
            ignore_https_errors=True,  # Sometimes helps
        )

        init_scripts = get_enhanced_playwright_init_scripts()
        for script in init_scripts:
            await context.add_init_script(script)

        await DataDomeBypass.inject_datadome_evasion_scripts(context)

        page = await context.new_page()

        try:
            print("\n1. Navigating to Yelp...")
            await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
            print("   ✓ Page loaded")

            print("\n2. Simulating human behavior...")
            await DataDomeBypass.simulate_human_page_load(page)
            print("   ✓ Human simulation complete")

            # Give extra time for any redirects or JS to execute
            print("\n3. Waiting for page to stabilize...")
            await asyncio.sleep(5)
            print("   ✓ Wait complete")

            print("\n4. Analyzing page...")

            # Get page info safely
            try:
                title = await page.title()
                current_url = page.url
                print(f"   Page Title: {title}")
                print(f"   Current URL: {current_url}")
            except Exception as e:
                print(f"   ⚠️  Could not get page info: {e}")
                title = "unknown"
                current_url = "unknown"

            # Check HTML content
            try:
                html_content = await page.content()

                # Save HTML
                html_path = "yelp_final_test.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"   ✓ HTML saved to: {html_path}")

                # Check for blocking
                is_blocked = any(keyword in html_content.lower() for keyword in
                                ['datadome', 'captcha', 'challenge'])

                if is_blocked:
                    print("   ⚠️  DataDome/CAPTCHA detected in HTML")
                else:
                    print("   ✓ No obvious blocking indicators")

                # Test selectors
                biz_links = await page.query_selector_all('a[href*="/biz/"]')
                print(f"\n5. Results:")
                print(f"   Business links found: {len(biz_links)}")

                if len(biz_links) > 0:
                    print("\n   ✓✓✓ SUCCESS! Found businesses! ✓✓✓\n")
                    for idx, link in enumerate(biz_links[:5]):
                        try:
                            name = await link.inner_text()
                            print(f"   {idx+1}. {name[:50]}")
                        except:
                            pass

                    # Save screenshot of success
                    await page.screenshot(path="yelp_success.png", full_page=True)
                    print(f"\n   ✓ Screenshot saved to: yelp_success.png")

                    return True
                else:
                    print("   ✗ No business links found")

                    # Save screenshot for debugging
                    await page.screenshot(path="yelp_failed.png", full_page=True)
                    print(f"   ✓ Screenshot saved to: yelp_failed.png")

                    # Show snippet of HTML
                    print(f"\n   HTML snippet (first 500 chars):")
                    print(f"   {html_content[:500]}")

                    return False

            except Exception as e:
                print(f"   ❌ Error analyzing page: {e}")
                return False

        except Exception as e:
            print(f"\n❌ Test error: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            try:
                await browser.close()
            except:
                pass


if __name__ == "__main__":
    print("\nRunning optimized Yelp test...\n")

    success = asyncio.run(test_yelp_final())

    print("\n" + "=" * 80)
    if success:
        print("✓✓✓ TEST PASSED ✓✓✓")
        print("\nThe enhanced anti-DataDome measures are working!")
        print("You can now run the full Yelp workers.")
    else:
        print("✗ TEST FAILED")
        print("\nDataDome is still blocking despite enhancements.")
        print("\nOptions:")
        print("1. Add residential proxy support")
        print("2. Reduce to 1-2 workers with longer delays")
        print("3. Focus on Google Maps and Yellow Pages instead")
    print("=" * 80 + "\n")
