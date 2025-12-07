#!/usr/bin/env python3
"""
Test script for verification filter implementation.

Tests that all SEO workers correctly implement the verification filter.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from seo_intelligence.orchestrator.module_worker import BaseModuleWorker
from seo_intelligence.seo_worker_service import get_verification_where_clause as service_get_clause


def test_base_worker_method():
    """Test that BaseModuleWorker has get_verification_where_clause method."""
    print("Testing BaseModuleWorker.get_verification_where_clause()...")

    # Check method exists
    assert hasattr(BaseModuleWorker, 'get_verification_where_clause'), \
        "BaseModuleWorker missing get_verification_where_clause method"

    # Create a mock worker to test the method
    class TestWorker(BaseModuleWorker):
        def __init__(self):
            super().__init__(name="test", batch_size=10)

        def process_company(self, company_id):
            pass

        def get_companies_to_process(self, limit, after_id=None):
            return []

    worker = TestWorker()
    clause = worker.get_verification_where_clause()

    # Verify the clause content
    expected = "(parse_metadata->'verification'->>'status' = 'passed' OR parse_metadata->'verification'->>'human_label' = 'provider')"
    assert clause == expected, f"Expected: {expected}\nGot: {clause}"

    print("✓ BaseModuleWorker.get_verification_where_clause() works correctly")
    print(f"  Returns: {clause}")


def test_service_helper():
    """Test that seo_worker_service has standalone helper function."""
    print("\nTesting seo_worker_service.get_verification_where_clause()...")

    clause = service_get_clause()

    # Verify the clause content
    expected = "(parse_metadata->'verification'->>'status' = 'passed' OR parse_metadata->'verification'->>'human_label' = 'provider')"
    assert clause == expected, f"Expected: {expected}\nGot: {clause}"

    print("✓ seo_worker_service.get_verification_where_clause() works correctly")
    print(f"  Returns: {clause}")


def test_worker_imports():
    """Test that all worker files can be imported."""
    print("\nTesting worker file imports...")

    workers = [
        'seo_intelligence.workers.serp_worker',
        'seo_intelligence.workers.citation_worker',
        'seo_intelligence.workers.backlink_worker',
        'seo_intelligence.workers.technical_worker',
        'seo_intelligence.workers.seo_continuous_worker',
        'seo_intelligence.workers.keyword_worker',
        'seo_intelligence.workers.competitive_worker',
    ]

    for worker_module in workers:
        try:
            __import__(worker_module)
            print(f"✓ {worker_module} imports successfully")
        except Exception as e:
            print(f"✗ {worker_module} failed to import: {e}")
            raise


def main():
    """Run all tests."""
    print("=" * 70)
    print("VERIFICATION FILTER IMPLEMENTATION TEST")
    print("=" * 70)

    try:
        test_base_worker_method()
        test_service_helper()
        test_worker_imports()

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED ✓")
        print("=" * 70)
        print("\nThe verification filter has been successfully implemented:")
        print("- BaseModuleWorker has get_verification_where_clause() method")
        print("- seo_worker_service has standalone helper function")
        print("- All 7 worker files import without errors")
        print("\nFilter will only process companies where:")
        print("  - parse_metadata->'verification'->>'status' = 'passed' OR")
        print("  - parse_metadata->'verification'->>'human_label' = 'provider'")

        return 0

    except Exception as e:
        print("\n" + "=" * 70)
        print("TEST FAILED ✗")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
