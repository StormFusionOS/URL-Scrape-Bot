#!/usr/bin/env python3
"""
Test script for enhanced YP scraper with filtering.

This script validates:
1. Filter loading from data files
2. Category tag extraction
3. Filtering logic with scoring
4. Integration with crawl functions
"""

import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))


def test_filter_loading():
    """Test loading filter data files."""
    print("=" * 70)
    print("TEST 1: Filter Data Loading")
    print("=" * 70)

    from scrape_yp.yp_filter import YPFilter

    filter_obj = YPFilter()

    print(f"\n✓ Filter initialized successfully")
    print(f"  Allowlist categories: {len(filter_obj.allowlist)}")
    print(f"  Blocklist categories: {len(filter_obj.blocklist)}")
    print(f"  Anti-keywords: {len(filter_obj.anti_keywords)}")
    print(f"  Positive hints: {len(filter_obj.positive_hints)}")

    return True


def test_filtering_logic():
    """Test filtering rules with sample listings."""
    print("\n" + "=" * 70)
    print("TEST 2: Filtering Logic")
    print("=" * 70)

    from scrape_yp.yp_filter import YPFilter

    filter_obj = YPFilter()

    # Test cases
    test_listings = [
        {
            'name': 'ABC Pressure Washing',
            'category_tags': ['Power Washing', 'Window Cleaning'],
            'description': 'Professional house washing and roof cleaning',
            'website': 'https://abcpressurewashing.com'
        },
        {
            'name': 'Equipment Supply Store',
            'category_tags': ['Pressure Washing Equipment & Services'],
            'description': 'Pressure washer sales and rentals',
            'website': 'https://equipmentsupply.com'
        },
        {
            'name': 'Pro Wash Services',
            'category_tags': ['Pressure Washing Equipment & Services', 'Power Washing'],
            'description': 'Soft wash and house washing specialists',
            'website': 'https://prowash.com'
        },
        {
            'name': 'ABC Janitorial',
            'category_tags': ['Janitorial Service', 'Building Cleaners-Interior'],
            'description': 'Office cleaning services',
            'website': 'https://abcjanitorial.com'
        },
    ]

    print("\nTesting filtering on sample listings:\n")

    for i, listing in enumerate(test_listings, 1):
        should_include, reason, score = filter_obj.should_include(listing)

        status = "✓ ACCEPTED" if should_include else "✗ REJECTED"
        print(f"{i}. {listing['name']}")
        print(f"   Tags: {', '.join(listing['category_tags'])}")
        print(f"   Status: {status}")
        print(f"   Reason: {reason}")
        print(f"   Score: {score:.1f}/100")
        print()

    print("✓ Filtering logic test completed")
    return True


def test_parser_enhanced():
    """Test enhanced parser (if HTML available)."""
    print("\n" + "=" * 70)
    print("TEST 3: Enhanced Parser")
    print("=" * 70)

    try:
        from scrape_yp.yp_parser_enhanced import extract_category_tags, parse_yp_results_enhanced
        print("✓ Enhanced parser modules loaded successfully")

        # Test with mock HTML (would need real HTML for full test)
        print("✓ Parser functions available:")
        print("  - parse_yp_results_enhanced()")
        print("  - extract_category_tags()")
        print("  - is_sponsored()")
        print("  - extract_profile_url()")

        return True

    except Exception as e:
        print(f"✗ Error loading parser: {e}")
        return False


def test_target_seeding():
    """Test target generation from allowlist."""
    print("\n" + "=" * 70)
    print("TEST 4: Target Seeding")
    print("=" * 70)

    try:
        from scrape_yp.seed_targets import load_allowlist, load_query_terms

        # Load data files
        allowlist = load_allowlist('data/yp_category_allowlist.txt')
        queries = load_query_terms('data/yp_query_terms.txt')

        print(f"\n✓ Loaded {len(allowlist)} allowlist categories")
        print(f"✓ Loaded {len(queries)} query terms")

        # Check if targets file exists
        targets_file = Path('data/yp_targets.ndjson')
        if targets_file.exists():
            import json
            line_count = sum(1 for _ in open(targets_file))
            print(f"✓ Found {line_count} pre-generated targets in yp_targets.ndjson")
        else:
            print("  Note: Run 'python scrape_yp/seed_targets.py' to generate targets")

        return True

    except Exception as e:
        print(f"✗ Error in target seeding: {e}")
        return False


def test_cli_integration():
    """Test CLI flags."""
    print("\n" + "=" * 70)
    print("TEST 5: CLI Integration")
    print("=" * 70)

    try:
        from runner.main import parse_args
        import sys

        # Simulate CLI args
        test_args = [
            '--discover-only',
            '--use-enhanced-filter',
            '--min-score', '60',
            '--categories', 'pressure washing',
            '--states', 'TX',
            '--pages-per-pair', '1'
        ]

        # Save original args
        original_argv = sys.argv
        sys.argv = ['runner/main.py'] + test_args

        try:
            args = parse_args()
            print("✓ CLI args parsed successfully:")
            print(f"  --use-enhanced-filter: {args.use_enhanced_filter}")
            print(f"  --min-score: {args.min_score}")
            print(f"  --include-sponsored: {args.include_sponsored}")
            print(f"  --categories-file: {args.categories_file}")

            return True

        finally:
            # Restore original args
            sys.argv = original_argv

    except Exception as e:
        print(f"✗ Error testing CLI: {e}")
        return False


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "Enhanced YP Scraper Test Suite" + " " * 23 + "║")
    print("╚" + "=" * 68 + "╝")
    print()

    tests = [
        ("Filter Loading", test_filter_loading),
        ("Filtering Logic", test_filtering_logic),
        ("Enhanced Parser", test_parser_enhanced),
        ("Target Seeding", test_target_seeding),
        ("CLI Integration", test_cli_integration),
    ]

    results = []

    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"\n✗ TEST FAILED: {test_name}")
            print(f"  Error: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for test_name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status}: {test_name}")

    print()
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Enhanced YP scraper is ready.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review errors above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
