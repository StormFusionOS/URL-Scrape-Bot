#!/usr/bin/env python3
"""
Test different HomeAdvisor URL patterns to find which ones return actual listings.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_url_patterns():
    """Test various HomeAdvisor URL patterns."""
    print("=" * 70)
    print("Testing HomeAdvisor URL Patterns")
    print("=" * 70)
    print()

    from scrape_ha.ha_client import fetch_url, parse_list_page

    test_urls = [
        # Pattern 1: State-level directory (emc format)
        ("State Directory (WA)", "https://www.homeadvisor.com/emc.Washington.powerwashing-directory.-14980.html"),

        # Pattern 2: City-level (c. format)
        ("City - Seattle", "https://www.homeadvisor.com/c.powerwashing.Seattle.WA.-14980.html"),
        ("City - Vancouver", "https://www.homeadvisor.com/c.powerwashing.Vancouver.WA.-14980.html"),

        # Pattern 3: City-level (tloc format)
        ("City - Tacoma (tloc)", "https://www.homeadvisor.com/tloc/Tacoma-WA/Exterior-Surfaces-Powerwashing/"),

        # For comparison: Original near-me pattern (we know this doesn't work)
        ("Near-me (current)", "https://www.homeadvisor.com/near-me/pressure-washing/?state=WA&page=1"),
    ]

    results = []

    for label, url in test_urls:
        print(f"\nTesting: {label}")
        print(f"URL: {url}")
        print("-" * 70)

        try:
            html = fetch_url(url)
            if html:
                html_size = len(html)
                cards = parse_list_page(html)
                num_cards = len(cards)

                print(f"✓ HTML fetched: {html_size:,} characters")
                print(f"✓ Business cards found: {num_cards}")

                if num_cards > 0:
                    print(f"\n  First business:")
                    first = cards[0]
                    for key in ['name', 'phone', 'address', 'profile_url']:
                        value = first.get(key, 'N/A')
                        if value and len(str(value)) > 60:
                            value = str(value)[:60] + "..."
                        print(f"    {key}: {value}")

                results.append({
                    'label': label,
                    'url': url,
                    'html_size': html_size,
                    'cards': num_cards,
                    'success': num_cards > 0
                })
            else:
                print("✗ Failed to fetch HTML")
                results.append({
                    'label': label,
                    'url': url,
                    'html_size': 0,
                    'cards': 0,
                    'success': False
                })
        except Exception as e:
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'label': label,
                'url': url,
                'error': str(e),
                'success': False
            })

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        status = "✓ WORKS" if r.get('success') else "✗ FAILS"
        cards = r.get('cards', 0)
        print(f"{status:10} {r['label']:30} ({cards} cards)")

    print("=" * 70)

    # Return best working URL pattern
    working = [r for r in results if r.get('success')]
    if working:
        best = max(working, key=lambda x: x.get('cards', 0))
        print(f"\n✓ Best pattern: {best['label']} with {best['cards']} businesses")
        return True
    else:
        print("\n✗ No working patterns found")
        return False


if __name__ == '__main__':
    try:
        success = test_url_patterns()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
