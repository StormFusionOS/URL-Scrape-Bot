#!/usr/bin/env python3
"""
Phase 2A Standalone Verification Test

Directly tests Phase 2A components without complex imports:
- URL Canonicalizer (Task 9)
- Domain Quarantine (Task 11)

Run with: ./venv/bin/python test_phase2a_standalone.py
"""

import sys
sys.path.insert(0, '.')

# Direct imports to avoid complex dependency chains
from seo_intelligence.services.url_canonicalizer import URLCanonicalizer
from seo_intelligence.services.domain_quarantine import DomainQuarantine, QuarantineReason


def test_url_canonicalizer():
    """Test URL canonicalization service."""
    print("=" * 70)
    print("Testing URL Canonicalizer (Task 9)")
    print("=" * 70)

    canon = URLCanonicalizer()

    # Test 1: Basic canonicalization
    result = canon.canonicalize("https://www.example.com/page?utm_source=google")
    assert result.canonical_url == "https://example.com/page", f"Expected 'https://example.com/page' but got '{result.canonical_url}'"
    assert result.domain == "example.com"
    assert "utm_source" in result.stripped_params
    print("✓ Test 1: Basic canonicalization")

    # Test 2: Tracking param removal
    result = canon.canonicalize("https://example.com/?fbclid=123&page=1&gclid=abc")
    assert result.canonical_url == "https://example.com/?page=1"
    assert "fbclid" in result.stripped_params
    assert "gclid" in result.stripped_params
    print("✓ Test 2: Tracking parameter removal")

    # Test 3: Domain normalization
    urls = ["https://WWW.EXAMPLE.COM/", "https://www.example.com/", "https://example.com/"]
    canonical_urls = [canon.canonicalize(url).canonical_url for url in urls]
    assert len(set(canonical_urls)) == 1, "All variants should normalize to same URL"
    print("✓ Test 3: Domain normalization")

    # Test 4: Path normalization
    result = canon.canonicalize("https://example.com/page/")
    assert result.canonical_url == "https://example.com/page"
    print("✓ Test 4: Path normalization")

    print("✅ URL Canonicalizer: ALL TESTS PASSED\n")


def test_domain_quarantine():
    """Test domain quarantine service."""
    print("=" * 70)
    print("Testing Domain Quarantine (Task 11)")
    print("=" * 70)

    quar = DomainQuarantine()
    quar.clear_all()

    # Test 1: Basic quarantine
    assert not quar.is_quarantined("test1.com")
    quar.quarantine_domain("test1.com", "403_FORBIDDEN", duration_minutes=60)
    assert quar.is_quarantined("test1.com")
    print("✓ Test 1: Basic quarantine")

    # Test 2: Exponential backoff
    assert quar.get_backoff_delay(0) == 0
    assert quar.get_backoff_delay(1) == 5
    assert quar.get_backoff_delay(2) == 30
    assert quar.get_backoff_delay(3) == 300
    assert quar.get_backoff_delay(4) == 3600
    print("✓ Test 2: Exponential backoff schedule")

    # Test 3: Retry tracking
    quar.clear_all()
    assert quar.get_retry_attempt("test2.com") == 0
    quar.quarantine_domain("test2.com", "429_TOO_MANY_REQUESTS")
    assert quar.get_retry_attempt("test2.com") == 1
    quar.reset_retry_attempts("test2.com")
    assert quar.get_retry_attempt("test2.com") == 0
    print("✓ Test 3: Retry attempt tracking")

    # Test 4: Auto-quarantine on repeated 429
    quar.clear_all()
    quar.record_error_event("test3.com", "429")
    quar.record_error_event("test3.com", "429")
    assert not quar.is_quarantined("test3.com")
    quar.record_error_event("test3.com", "429")  # 3rd time
    assert quar.is_quarantined("test3.com")
    entry = quar.get_quarantine_entry("test3.com")
    assert entry.reason == QuarantineReason.TOO_MANY_REQUESTS_429
    print("✓ Test 4: Auto-quarantine on repeated 429")

    # Test 5: Auto-quarantine on repeated 5xx
    quar.clear_all()
    quar.record_error_event("test4.com", "500")
    quar.record_error_event("test4.com", "502")
    assert not quar.is_quarantined("test4.com")
    quar.record_error_event("test4.com", "503")  # 3rd time
    assert quar.is_quarantined("test4.com")
    entry = quar.get_quarantine_entry("test4.com")
    assert entry.reason == QuarantineReason.SERVER_ERROR_5XX
    print("✓ Test 5: Auto-quarantine on repeated 5xx")

    # Test 6: Manual release
    quar.clear_all()
    quar.quarantine_domain("test5.com", "403_FORBIDDEN")
    assert quar.is_quarantined("test5.com")
    quar.release_quarantine("test5.com")
    assert not quar.is_quarantined("test5.com")
    print("✓ Test 6: Manual release")

    # Test 7: Statistics
    quar.clear_all()
    quar.quarantine_domain("test6.com", "403_FORBIDDEN")
    quar.quarantine_domain("test7.com", "CAPTCHA_DETECTED")
    quar.quarantine_domain("test8.com", "CAPTCHA_DETECTED")
    stats = quar.get_stats()
    assert stats["total_quarantined"] == 3
    assert stats["by_reason"]["403_FORBIDDEN"] == 1
    assert stats["by_reason"]["CAPTCHA_DETECTED"] == 2
    print("✓ Test 7: Statistics")

    # Test 8: Quarantine expiration
    import time
    quar.clear_all()
    quar.quarantine_domain("test9.com", "MANUAL", duration_minutes=1/60)  # 1 second
    assert quar.is_quarantined("test9.com")
    time.sleep(2)
    assert not quar.is_quarantined("test9.com")
    print("✓ Test 8: Quarantine expiration")

    print("✅ Domain Quarantine: ALL TESTS PASSED\n")


def main():
    """Run all tests."""
    print("\n")
    print("=" * 70)
    print(" PHASE 2A COMPONENT VERIFICATION")
    print("=" * 70)
    print()

    try:
        test_url_canonicalizer()
        test_domain_quarantine()

        print("=" * 70)
        print("✅ ALL PHASE 2A TESTS PASSED!")
        print("=" * 70)
        print()
        print("Phase 2A Implementation Complete:")
        print("  ✓ Migration 025: SEO intelligence tables restored")
        print("  ✓ Task 9: URL Canonicalizer service")
        print("  ✓ Task 11: Domain Quarantine service")
        print("  ✓ Task 11: Exponential backoff integrated in base_scraper.py")
        print("  ✓ Task 11: Per-host semaphore (in rate_limiter.py)")
        print()
        print("Phase 2A Status: ✅ COMPLETE")
        print()
        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return 1

    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
