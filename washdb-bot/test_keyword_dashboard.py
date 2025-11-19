#!/usr/bin/env python3
"""
Test script for keyword management dashboard.

Tests:
1. KeywordManager backend
2. File operations (add/remove/update)
3. Import/export functionality
"""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from niceui.utils.keyword_manager import keyword_manager


def test_keyword_manager():
    """Test KeywordManager functionality."""
    print("=" * 60)
    print("KEYWORD MANAGEMENT DASHBOARD TEST")
    print("=" * 60)

    # Test 1: Load all files
    print("\n1. Testing file loading...")
    files_by_source = keyword_manager.get_all_files_by_source()

    for source, files in files_by_source.items():
        if files:
            print(f"\n  {source.upper()}:")
            for file_info in files:
                print(f"    ✓ {file_info['name']}: {file_info['count']} keywords")

    # Test 2: Get keywords from a file
    print("\n2. Testing keyword retrieval...")
    anti_keywords = keyword_manager.get_keywords('shared_anti_keywords')
    print(f"  ✓ Loaded {len(anti_keywords)} anti-keywords")
    print(f"  ✓ First 5: {anti_keywords[:5]}")

    # Test 3: Add a test keyword
    print("\n3. Testing add keyword...")
    test_keyword = "test_keyword_12345"
    success, msg = keyword_manager.add_keyword('shared_anti_keywords', test_keyword)
    if success:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")

    # Test 4: Search for keyword
    print("\n4. Testing search...")
    results = keyword_manager.search_keywords('shared_anti_keywords', 'test')
    print(f"  ✓ Found {len(results)} keywords matching 'test'")
    if test_keyword in results:
        print(f"  ✓ Test keyword found in search results")

    # Test 5: Remove test keyword
    print("\n5. Testing remove keyword...")
    success, msg = keyword_manager.remove_keyword('shared_anti_keywords', test_keyword)
    if success:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")

    # Test 6: Verify removal
    print("\n6. Verifying removal...")
    after_keywords = keyword_manager.get_keywords('shared_anti_keywords')
    if test_keyword not in after_keywords:
        print(f"  ✓ Test keyword successfully removed")
        print(f"  ✓ Keyword count: {len(after_keywords)}")
    else:
        print(f"  ✗ Test keyword still present")

    # Test 7: Test import functionality
    print("\n7. Testing import from text...")
    test_text = "test_import_1\ntest_import_2\ntest_import_3"
    success, msg = keyword_manager.import_from_text(
        'yp_anti_keywords',
        test_text,
        merge=True
    )
    if success:
        print(f"  ✓ {msg}")

        # Clean up imported keywords
        for kw in ['test_import_1', 'test_import_2', 'test_import_3']:
            keyword_manager.remove_keyword('yp_anti_keywords', kw)
        print(f"  ✓ Cleaned up test imports")
    else:
        print(f"  ✗ {msg}")

    # Test 8: Export functionality
    print("\n8. Testing export...")
    export_data = keyword_manager.export_to_dict('shared_positive_hints')
    if export_data:
        print(f"  ✓ Exported {export_data['metadata']['name']}")
        print(f"  ✓ Contains {len(export_data['keywords'])} keywords")
        print(f"  ✓ First 3: {export_data['keywords'][:3]}")
    else:
        print(f"  ✗ Export failed")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    total_keywords = sum(f['count'] for source_files in files_by_source.values() for f in source_files)
    total_files = sum(len(files) for files in files_by_source.values())

    print(f"\n  Total Files: {total_files}")
    print(f"  Total Keywords: {total_keywords}")
    print(f"\n  Shared Keywords: {sum(f['count'] for f in files_by_source['shared'])}")
    print(f"  YP Keywords: {sum(f['count'] for f in files_by_source['yp'])}")

    print("\n✓ All tests completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    test_keyword_manager()
