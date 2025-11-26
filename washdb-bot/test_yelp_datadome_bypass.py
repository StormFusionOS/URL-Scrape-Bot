#!/usr/bin/env python3
"""
Test script for enhanced DataDome bypass on Yelp.
This uses all the new anti-detection measures to test if we can bypass DataDome.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from scrape_yelp.yelp_stealth import StealthConfig, get_enhanced_playwright_init_scripts
from scrape_yelp.yelp_datadome_bypass import MouseSimulator, DataDomeBypass


async def test_datadome_bypass():
    """Test enhanced DataDome bypass techniques."""

    # Test URL - searching for pressure washing in Los Angeles
    test_url = "https://www.yelp.com/search?find_desc=pressure+washing&find_loc=Los+Angeles%2C+CA"

    print("=" * 80)
    print("Testing ENHANCED DataDome Bypass")
    print("=" * 80)
    print(f"URL: {test_url}")
    print()
    print("Enhancements:")
    print("  ✓ Using real Chrome (not Chromium)")
    print("  ✓ Enhanced browser arguments")
    print("  ✓ Improved HTTP headers")
    print("  ✓ Mouse movement simulation")
    print("  ✓ Human-like behavior patterns")
    print("  ✓ DataDome-specific evasion scripts")
    print()

    async with async_playwright() as p:
        # Use stealth configuration
        stealth_config = StealthConfig()

        # Launch browser with ENHANCED DataDome evasion
        print("Launching Chrome with enhanced arguments...")
        try:
            browser = await p.chromium.launch(
                channel="chrome",  # Try to use real Chrome
                headless=False,  # Set to False to watch
                args=DataDomeBypass.get_enhanced_chrome_args()
            )
            print("✓ Successfully launched real Chrome")
        except Exception as e:
            print(f"⚠️  Could not launch Chrome, using Chromium: {e}")
            browser = await p.chromium.launch(
                headless=False,
                args=DataDomeBypass.get_enhanced_chrome_args()
            )

        # Create context with enhanced headers
        enhanced_headers = DataDomeBypass.get_enhanced_headers()

        context = await browser.new_context(
            viewport=stealth_config.viewport,
            user_agent=stealth_config.user_agent,
            locale='en-US',
            timezone_id=stealth_config.timezone,
            permissions=[],
            extra_http_headers=enhanced_headers
        )

        # Add stealth scripts
        init_scripts = get_enhanced_playwright_init_scripts()
        for script in init_scripts:
            await context.add_init_script(script)

        # Add DataDome-specific evasion scripts
        await DataDomeBypass.inject_datadome_evasion_scripts(context)

        page = await context.new_page()

        try:
            print("\n" + "=" * 80)
            print("STEP 1: Navigating to Yelp...")
            print("=" * 80)

            await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
            print("✓ Page loaded")

            print("\n" + "=" * 80)
            print("STEP 2: Simulating human-like page load behavior...")
            print("=" * 80)

            await DataDomeBypass.simulate_human_page_load(page)
            print("✓ Page load simulation complete")

            print("\n" + "=" * 80)
            print("STEP 3: Checking for DataDome challenge...")
            print("=" * 80)

            challenge_passed = await DataDomeBypass.handle_datadome_challenge(page, max_wait=30)

            if challenge_passed:
                print("✓ No DataDome challenge detected or challenge resolved!")
            else:
                print("✗ DataDome challenge still present")

            # Wait a bit more
            await asyncio.sleep(2)

            print("\n" + "=" * 80)
            print("STEP 4: Analyzing page content...")
            print("=" * 80)

            # Check page title
            title = await page.title()
            print(f"Page Title: {title}")

            # Check for blocking indicators
            html_content = await page.content()

            is_blocked = False
            if "captcha" in html_content.lower() or "datadome" in html_content.lower():
                print("⚠️  WARNING: Still showing CAPTCHA/DataDome page")
                is_blocked = True
            else:
                print("✓ No obvious blocking indicators found")

            # Test selectors
            print("\n" + "-" * 80)
            print("Testing Business Selectors:")
            print("-" * 80)

            biz_links = await page.query_selector_all('a[href*="/biz/"]')
            print(f"Business links found: {len(biz_links)}")

            if len(biz_links) > 0:
                print("\n✓✓✓ SUCCESS! Found business links ✓✓✓")
                print("\nFirst 3 businesses:")
                for idx, link in enumerate(biz_links[:3]):
                    try:
                        name = await link.inner_text()
                        href = await link.get_attribute('href')
                        print(f"  {idx+1}. {name}")
                        print(f"     URL: https://www.yelp.com{href}")
                    except:
                        pass
            else:
                print("✗ No business links found")

            # Save HTML for analysis
            html_path = "debug_datadome_test.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"\n✓ HTML saved to: {html_path}")

            # Save screenshot
            screenshot_path = "debug_datadome_test.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"✓ Screenshot saved to: {screenshot_path}")

            print("\n" + "=" * 80)
            print("STEP 5: Simulating extended human behavior...")
            print("=" * 80)

            if not is_blocked:
                await DataDomeBypass.simulate_reading_page(page, duration=5.0)
                print("✓ Simulated reading behavior")

            print("\n" + "=" * 80)
            print("TEST COMPLETE")
            print("=" * 80)

            if len(biz_links) > 0:
                print("\n✓✓✓ DataDome bypass SUCCESSFUL! ✓✓✓")
                print("The enhanced techniques are working!")
            elif not is_blocked:
                print("\n⚠️  Partial success - page loaded but no results found")
                print("May need to adjust selectors or wait longer")
            else:
                print("\n✗ DataDome bypass FAILED")
                print("Still being blocked - may need additional measures")

            print("\nBrowser will stay open for 30 seconds for inspection...")
            await asyncio.sleep(30)

        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("ENHANCED YELP DATADOME BYPASS TEST")
    print("=" * 80)
    print("\nThis will test all new anti-detection measures:")
    print("- Real Chrome browser")
    print("- Enhanced browser arguments")
    print("- Improved headers")
    print("- Mouse movement simulation")
    print("- Human-like behavior patterns")
    print("- DataDome-specific evasion")
    print("\n" + "=" * 80 + "\n")

    asyncio.run(test_datadome_bypass())

    print("\n✓ Test complete!")
    print("\nNext steps based on results:")
    print("1. If successful → Run full Yelp workers")
    print("2. If partial → Adjust timing/selectors")
    print("3. If failed → Consider residential proxies")
