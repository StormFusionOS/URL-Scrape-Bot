"""
Phase 2A Component Tests

Quick verification tests for Phase 2A components:
- Migration 025 (SEO intelligence tables restored)
- URL Canonicalizer (Task 9)
- Domain Quarantine (Task 11)

Run with: python3 -m pytest tests/test_phase2a_components.py -v
"""

import pytest
from datetime import datetime, timedelta

# URL Canonicalizer tests
from seo_intelligence.services.url_canonicalizer import (
    get_url_canonicalizer,
    is_same_domain,
    extract_domain,
    urls_are_equivalent
)

# Domain Quarantine tests
from seo_intelligence.services.domain_quarantine import (
    get_domain_quarantine,
    QuarantineReason
)


class TestURLCanonicalizer:
    """Test URL canonicalization service (Task 9)."""

    def test_basic_canonicalization(self):
        """Test basic URL canonicalization."""
        canonicalizer = get_url_canonicalizer()

        result = canonicalizer.canonicalize("https://www.example.com/page?utm_source=google")

        assert result.canonical_url == "https://example.com/page"
        assert result.domain == "example.com"
        assert result.path == "/page"
        assert result.query is None
        assert "utm_source" in result.stripped_params
        assert result.is_normalized is True

    def test_tracking_param_removal(self):
        """Test that all tracking parameters are removed."""
        canonicalizer = get_url_canonicalizer()

        test_cases = [
            ("https://example.com/?utm_source=google&utm_medium=cpc", "https://example.com/"),
            ("https://example.com/?fbclid=12345", "https://example.com/"),
            ("https://example.com/?gclid=abc123", "https://example.com/"),
            ("https://example.com/?page=1&utm_source=email", "https://example.com/?page=1"),
        ]

        for original, expected in test_cases:
            result = canonicalizer.canonicalize(original)
            assert result.canonical_url == expected

    def test_domain_normalization(self):
        """Test domain normalization (www removal, lowercase)."""
        canonicalizer = get_url_canonicalizer()

        test_cases = [
            "https://WWW.EXAMPLE.COM/",
            "https://www.example.com/",
            "https://example.com/",
        ]

        canonical_urls = [canonicalizer.canonicalize(url).canonical_url for url in test_cases]

        # All should normalize to same URL
        assert len(set(canonical_urls)) == 1
        assert canonical_urls[0] == "https://example.com/"

    def test_path_normalization(self):
        """Test path normalization (trailing slash removal, percent-decoding)."""
        canonicalizer = get_url_canonicalizer()

        test_cases = [
            ("https://example.com/page/", "https://example.com/page"),
            ("https://example.com/page%20test", "https://example.com/page test"),
            ("https://example.com/", "https://example.com/"),  # Root keeps slash
        ]

        for original, expected in test_cases:
            result = canonicalizer.canonicalize(original)
            assert result.canonical_url == expected

    def test_utility_functions(self):
        """Test utility functions."""
        # Test is_same_domain
        assert is_same_domain("https://example.com/page1", "https://example.com/page2")
        assert is_same_domain("https://www.example.com/", "https://example.com/")
        assert not is_same_domain("https://example.com/", "https://other.com/")

        # Test extract_domain
        assert extract_domain("https://www.example.com/page") == "example.com"
        assert extract_domain("https://sub.example.com/") == "sub.example.com"

        # Test urls_are_equivalent
        assert urls_are_equivalent(
            "https://example.com/page?utm_source=google",
            "https://www.example.com/page/"
        )


class TestDomainQuarantine:
    """Test domain quarantine service (Task 11)."""

    def setup_method(self):
        """Clear quarantine before each test."""
        quarantine = get_domain_quarantine()
        quarantine.clear_all()

    def test_quarantine_and_check(self):
        """Test basic quarantine operations."""
        quarantine = get_domain_quarantine()

        # Domain should not be quarantined initially
        assert not quarantine.is_quarantined("example.com")

        # Quarantine domain
        quarantine.quarantine_domain(
            domain="example.com",
            reason="403_FORBIDDEN",
            duration_minutes=1
        )

        # Domain should now be quarantined
        assert quarantine.is_quarantined("example.com")

        # Check quarantine details
        entry = quarantine.get_quarantine_entry("example.com")
        assert entry is not None
        assert entry.domain == "example.com"
        assert entry.reason == QuarantineReason.FORBIDDEN_403

    def test_quarantine_expiration(self):
        """Test that quarantines expire after duration."""
        import time
        quarantine = get_domain_quarantine()

        # Quarantine for 1 second
        quarantine.quarantine_domain(
            domain="example.com",
            reason="MANUAL",
            duration_minutes=1/60  # 1 second
        )

        assert quarantine.is_quarantined("example.com")

        # Wait for expiration
        time.sleep(2)

        # Should no longer be quarantined
        assert not quarantine.is_quarantined("example.com")

    def test_exponential_backoff(self):
        """Test exponential backoff delay calculation."""
        quarantine = get_domain_quarantine()

        # Test backoff schedule: 0s, 5s, 30s, 300s, 3600s
        assert quarantine.get_backoff_delay(0) == 0  # First attempt
        assert quarantine.get_backoff_delay(1) == 5  # First retry
        assert quarantine.get_backoff_delay(2) == 30  # Second retry
        assert quarantine.get_backoff_delay(3) == 300  # Third retry
        assert quarantine.get_backoff_delay(4) == 3600  # Fourth+ retry

    def test_retry_attempt_tracking(self):
        """Test retry attempt counter."""
        quarantine = get_domain_quarantine()

        assert quarantine.get_retry_attempt("example.com") == 0

        # Quarantine increases retry attempt
        quarantine.quarantine_domain("example.com", "429_TOO_MANY_REQUESTS")
        assert quarantine.get_retry_attempt("example.com") == 1

        quarantine.quarantine_domain("example.com", "429_TOO_MANY_REQUESTS")
        assert quarantine.get_retry_attempt("example.com") == 2

        # Reset attempts
        quarantine.reset_retry_attempts("example.com")
        assert quarantine.get_retry_attempt("example.com") == 0

    def test_repeated_429_auto_quarantine(self):
        """Test that repeated 429s trigger automatic quarantine."""
        quarantine = get_domain_quarantine()

        # Record 2 429s - should not quarantine yet
        quarantine.record_error_event("example.com", "429")
        quarantine.record_error_event("example.com", "429")
        assert not quarantine.is_quarantined("example.com")

        # Record 3rd 429 - should auto-quarantine
        quarantine.record_error_event("example.com", "429")
        assert quarantine.is_quarantined("example.com")

        entry = quarantine.get_quarantine_entry("example.com")
        assert entry.reason == QuarantineReason.TOO_MANY_REQUESTS_429

    def test_repeated_5xx_auto_quarantine(self):
        """Test that repeated 5xxs trigger automatic quarantine."""
        quarantine = get_domain_quarantine()

        # Record 2 5xxs - should not quarantine yet
        quarantine.record_error_event("example.com", "500")
        quarantine.record_error_event("example.com", "503")
        assert not quarantine.is_quarantined("example.com")

        # Record 3rd 5xx - should auto-quarantine
        quarantine.record_error_event("example.com", "502")
        assert quarantine.is_quarantined("example.com")

        entry = quarantine.get_quarantine_entry("example.com")
        assert entry.reason == QuarantineReason.SERVER_ERROR_5XX

    def test_manual_release(self):
        """Test manual quarantine release."""
        quarantine = get_domain_quarantine()

        quarantine.quarantine_domain("example.com", "403_FORBIDDEN")
        assert quarantine.is_quarantined("example.com")

        quarantine.release_quarantine("example.com")
        assert not quarantine.is_quarantined("example.com")

    def test_quarantine_stats(self):
        """Test quarantine statistics."""
        quarantine = get_domain_quarantine()

        quarantine.quarantine_domain("example1.com", "403_FORBIDDEN")
        quarantine.quarantine_domain("example2.com", "CAPTCHA_DETECTED")
        quarantine.quarantine_domain("example3.com", "CAPTCHA_DETECTED")

        stats = quarantine.get_stats()

        assert stats["total_quarantined"] == 3
        assert stats["by_reason"]["403_FORBIDDEN"] == 1
        assert stats["by_reason"]["CAPTCHA_DETECTED"] == 2


def test_migration_025_tables_exist():
    """Test that Migration 025 restored required tables."""
    from db.models import Base, engine
    from sqlalchemy import inspect

    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    # Check that all required Phase 2 tables exist
    required_tables = [
        "task_logs",  # Task 12: Telemetry
        "backlinks",  # Task 8: Link Graph
        "referring_domains",  # Task 8: Link Graph
        "page_audits",  # Task 10: Render Parity
        "audit_issues",  # Task 10: Render Parity
        "search_queries",  # Task 13: SERP
        "serp_snapshots",  # Task 13: SERP
        "competitors",  # Competitor analysis
    ]

    for table in required_tables:
        assert table in table_names, f"Table {table} not found in database"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
