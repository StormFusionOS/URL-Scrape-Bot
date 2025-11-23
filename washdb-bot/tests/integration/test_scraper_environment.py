"""
Phase 1: Environment & Schema Validation Tests

Tests database schema, service imports, and basic connectivity.
These must pass before running any other scraper tests.
"""

import pytest
import socket
import httpx
from sqlalchemy import text, inspect
from playwright.sync_api import sync_playwright

from seo_intelligence.services import (
    get_rate_limiter,
    get_robots_checker,
    get_user_agent_rotator,
    get_task_logger,
    get_content_hasher,
    get_url_canonicalizer,
    get_domain_quarantine,
    get_change_manager,
    get_nap_validator,
    get_entity_matcher,
)


class TestDatabaseSchema:
    """Test 1.1: Database Schema Validation"""

    @pytest.mark.acceptance
    def test_core_tables_exist(self, db_connection):
        """Verify all core scraper tables exist."""
        required_tables = [
            'search_queries', 'serp_snapshots', 'serp_results', 'serp_paa',
            'competitors', 'competitor_pages',
            'backlinks', 'referring_domains',
            'citations',
            'page_audits', 'audit_issues',
            'task_logs', 'change_log'
        ]

        inspector = inspect(db_connection)
        existing_tables = inspector.get_table_names()

        missing_tables = [t for t in required_tables if t not in existing_tables]

        assert not missing_tables, \
            f"Missing tables: {missing_tables}. Run migration 025 first."

    @pytest.mark.acceptance
    def test_serp_snapshots_schema(self, db_connection):
        """Verify serp_snapshots table has correct columns."""
        inspector = inspect(db_connection)
        columns = {col['name']: col for col in inspector.get_columns('serp_snapshots')}

        required_columns = [
            'snapshot_id', 'query_id', 'captured_at', 'result_count',
            'snapshot_hash', 'raw_html', 'metadata'
        ]

        missing = [c for c in required_columns if c not in columns]
        assert not missing, f"Missing columns in serp_snapshots: {missing}"

        # Check foreign key to search_queries
        fks = inspector.get_foreign_keys('serp_snapshots')
        assert any(fk['referred_table'] == 'search_queries' for fk in fks), \
            "Missing foreign key to search_queries"

    @pytest.mark.acceptance
    def test_serp_results_schema(self, db_connection):
        """Verify serp_results table has correct columns."""
        inspector = inspect(db_connection)
        columns = {col['name']: col for col in inspector.get_columns('serp_results')}

        required_columns = [
            'result_id', 'snapshot_id', 'position', 'url', 'title',
            'description', 'domain', 'is_our_company', 'is_competitor',
            'metadata', 'embedding_version', 'embedded_at'
        ]

        missing = [c for c in required_columns if c not in columns]
        assert not missing, f"Missing columns in serp_results: {missing}"

    @pytest.mark.acceptance
    def test_competitor_pages_schema(self, db_connection):
        """Verify competitor_pages table has correct columns."""
        inspector = inspect(db_connection)
        columns = {col['name']: col for col in inspector.get_columns('competitor_pages')}

        required_columns = [
            'page_id', 'competitor_id', 'url', 'page_type', 'title',
            'content_hash', 'word_count', 'crawled_at', 'status_code',
            'schema_markup', 'links', 'metadata', 'embedding_version'
        ]

        missing = [c for c in required_columns if c not in columns]
        assert not missing, f"Missing columns in competitor_pages: {missing}"

    @pytest.mark.acceptance
    def test_task_logs_views_exist(self, db_connection):
        """Verify task_logs monitoring views exist."""
        inspector = inspect(db_connection)
        views = inspector.get_view_names()

        required_views = [
            'v_task_stats_by_name',
            'v_recent_task_failures',
            'v_task_health_24h'
        ]

        missing = [v for v in required_views if v not in views]
        assert not missing, f"Missing views: {missing}"

    @pytest.mark.acceptance
    def test_health_monitoring_functions(self, db_connection):
        """Verify health monitoring functions exist."""
        result = db_connection.execute(text("""
            SELECT routine_name
            FROM information_schema.routines
            WHERE routine_schema = 'public'
            AND routine_name IN ('detect_error_spikes', 'detect_missing_runs')
        """))

        functions = [row[0] for row in result]

        assert 'detect_error_spikes' in functions, \
            "Missing function: detect_error_spikes"
        assert 'detect_missing_runs' in functions, \
            "Missing function: detect_missing_runs"


class TestServicesHealth:
    """Test 1.2: Services Health Check"""

    @pytest.mark.acceptance
    def test_all_services_import(self):
        """Verify all service modules can be imported."""
        services = [
            get_rate_limiter,
            get_robots_checker,
            get_user_agent_rotator,
            get_task_logger,
            get_content_hasher,
            get_url_canonicalizer,
            get_domain_quarantine,
            get_change_manager,
            get_nap_validator,
            get_entity_matcher,
        ]

        for service_func in services:
            try:
                service = service_func()
                assert service is not None, f"Service {service_func.__name__} returned None"
            except Exception as e:
                pytest.fail(f"Failed to import {service_func.__name__}: {e}")

    @pytest.mark.acceptance
    def test_url_canonicalizer_basic(self, url_canonicalizer):
        """Test URL canonicalizer basic functionality."""
        result = url_canonicalizer.canonicalize('https://www.example.com/page?utm_source=google')

        assert result.canonical_url == 'https://example.com/page', \
            f"Expected canonical URL without www and utm params, got {result.canonical_url}"
        assert 'utm_source' in result.stripped_params, \
            "utm_source should be in stripped_params"
        assert len(result.url_hash) == 64, \
            "URL hash should be 64 characters (SHA-256)"

    @pytest.mark.acceptance
    def test_domain_quarantine_basic(self, domain_quarantine):
        """Test domain quarantine basic functionality."""
        test_domain = 'test-quarantine.example.com'

        # Should not be quarantined initially
        assert not domain_quarantine.is_quarantined(test_domain)

        # Quarantine domain
        domain_quarantine.quarantine_domain(test_domain, '403_FORBIDDEN', 60)

        # Should now be quarantined
        assert domain_quarantine.is_quarantined(test_domain), \
            "Domain should be quarantined after quarantine_domain() call"

        # Check entry details
        entry = domain_quarantine.get_quarantine_entry(test_domain)
        assert entry is not None, "Should have quarantine entry"
        # Reason may be enum or string, check if it contains the expected value
        reason_str = str(entry.reason) if hasattr(entry.reason, 'value') else entry.reason
        assert '403' in reason_str or 'FORBIDDEN' in reason_str, \
            f"Reason should contain 403 or FORBIDDEN, got {entry.reason}"


class TestBasicConnectivity:
    """Test 1.3: Basic Connectivity Smoke Test"""

    @pytest.mark.acceptance
    def test_dns_resolution(self):
        """Test DNS resolution works."""
        try:
            ip = socket.gethostbyname('google.com')
            assert ip, "DNS resolution returned no IP"
        except socket.gaierror as e:
            pytest.fail(f"DNS resolution failed: {e}")

    @pytest.mark.acceptance
    def test_http_connectivity(self):
        """Test basic HTTP requests work."""
        try:
            response = httpx.get('https://example.com', timeout=10, follow_redirects=True)
            assert response.status_code == 200, \
                f"Expected status 200, got {response.status_code}"
        except Exception as e:
            pytest.fail(f"HTTP request failed: {e}")

    @pytest.mark.acceptance
    @pytest.mark.slow
    def test_playwright_browser_launch(self):
        """Test Playwright can launch and load pages."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto('https://example.com', wait_until='domcontentloaded', timeout=10000)

                title = page.title()
                assert title, "Page should have a title"
                assert len(title) > 0, "Title should not be empty"

                browser.close()
        except Exception as e:
            pytest.fail(f"Playwright browser test failed: {e}")

    @pytest.mark.acceptance
    def test_robots_txt_fetching(self, robots_checker):
        """Test robots.txt can be fetched and parsed."""
        try:
            # Test with a known accessible robots.txt
            allowed = robots_checker.is_allowed(
                'https://example.com/',
                'WashdbBot/1.0'
            )

            # We don't care if it's allowed or not, just that it doesn't crash
            assert isinstance(allowed, bool), \
                "Robots checker should return boolean"

        except Exception as e:
            pytest.fail(f"Robots.txt checking failed: {e}")

    @pytest.mark.acceptance
    def test_database_connectivity(self, db_connection):
        """Test database connection works."""
        result = db_connection.execute(text("SELECT 1 as test"))
        row = result.fetchone()

        assert row is not None, "Database query should return result"
        assert row[0] == 1, "Query should return 1"


class TestEnvironmentConfiguration:
    """Test environment variables and configuration."""

    def test_database_url_set(self):
        """Test DATABASE_URL environment variable is set."""
        import os
        assert os.getenv('DATABASE_URL'), \
            "DATABASE_URL environment variable must be set"

    def test_database_connection_params(self):
        """Test database URL has correct format."""
        import os
        db_url = os.getenv('DATABASE_URL')

        # Accept both postgresql:// and postgresql+psycopg:// (SQLAlchemy 2.0)
        assert db_url.startswith('postgresql://') or db_url.startswith('postgresql+'), \
            f"DATABASE_URL should start with postgresql://, got {db_url[:30]}"
        assert 'washbot_db' in db_url, \
            "DATABASE_URL should reference washbot_db database"
