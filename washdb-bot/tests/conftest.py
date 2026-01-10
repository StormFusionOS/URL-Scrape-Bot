"""
Pytest configuration and shared fixtures for scraper tests.

Provides database connections, test data cleanup, and common utilities.
"""

import pytest
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from db import create_session
from seo_intelligence.services import (
    get_url_canonicalizer,
    get_domain_quarantine,
    get_robots_checker,
    get_change_manager,
)


# Test markers
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "safety: marks tests as safety/compliance tests"
    )
    config.addinivalue_line(
        "markers", "acceptance: marks tests as acceptance tests"
    )


# Database fixtures
@pytest.fixture(scope="session")
def db_session_factory():
    """Create database session factory for tests."""
    return create_session


@pytest.fixture(scope="function")
def db_session(db_session_factory):
    """Provide a database session for a test function."""
    session = next(db_session_factory())
    yield session
    session.close()


@pytest.fixture(scope="function")
def db_connection():
    """Provide raw database connection for SQL queries."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set")

    engine = create_engine(database_url)
    conn = engine.connect()
    yield conn
    conn.close()
    engine.dispose()


# Service fixtures
@pytest.fixture(scope="function")
def url_canonicalizer():
    """Provide URL canonicalizer service."""
    canon = get_url_canonicalizer()
    # Clear cache for clean test state
    canon._canonical_cache.clear()
    return canon


@pytest.fixture(scope="function")
def domain_quarantine():
    """Provide domain quarantine service with clean state."""
    # Create a fresh instance for each test to avoid singleton lock contention
    from seo_intelligence.services.domain_quarantine import DomainQuarantine
    quar = DomainQuarantine()
    return quar


@pytest.fixture(scope="function")
def robots_checker():
    """Provide robots.txt checker service."""
    checker = get_robots_checker()
    # Clear cache for clean test state
    if hasattr(checker, '_cache'):
        checker._cache.clear()
    return checker


@pytest.fixture(scope="function")
def change_manager():
    """Provide change manager service."""
    return get_change_manager()


# Test data fixtures
@pytest.fixture(scope="function")
def test_business_info():
    """Provide sample business info for testing."""
    from seo_intelligence.scrapers import BusinessInfo

    return BusinessInfo(
        name="Test Pressure Washing Co",
        address="123 Test St",
        city="Austin",
        state="TX",
        zip_code="78701",
        phone="512-555-0100",
        website="https://testbusiness.com"
    )


@pytest.fixture(scope="function")
def test_query_text():
    """Provide unique test query text."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"test_query_{timestamp}"


@pytest.fixture(scope="function")
def test_domain():
    """Provide test domain name."""
    return "test-competitor-example.com"


# Cleanup fixtures
@pytest.fixture(scope="function")
def cleanup_test_queries(db_connection, test_query_text):
    """Clean up test search queries after test."""
    yield
    # Cleanup after test
    try:
        db_connection.execute(text("""
            DELETE FROM serp_results WHERE snapshot_id IN (
                SELECT snapshot_id FROM serp_snapshots WHERE query_id IN (
                    SELECT query_id FROM search_queries WHERE query_text LIKE :pattern
                )
            )
        """), {"pattern": "test_query_%"})

        db_connection.execute(text("""
            DELETE FROM serp_snapshots WHERE query_id IN (
                SELECT query_id FROM search_queries WHERE query_text LIKE :pattern
            )
        """), {"pattern": "test_query_%"})

        db_connection.execute(text("""
            DELETE FROM search_queries WHERE query_text LIKE :pattern
        """), {"pattern": "test_query_%"})

        db_connection.commit()
    except Exception as e:
        print(f"Cleanup error: {e}")
        db_connection.rollback()


@pytest.fixture(scope="function")
def cleanup_test_competitors(db_connection, test_domain):
    """Clean up test competitors after test."""
    yield
    # Cleanup after test
    try:
        db_connection.execute(text("""
            DELETE FROM competitor_pages WHERE competitor_id IN (
                SELECT competitor_id FROM competitors WHERE domain LIKE :pattern
            )
        """), {"pattern": "test-%"})

        db_connection.execute(text("""
            DELETE FROM competitors WHERE domain LIKE :pattern
        """), {"pattern": "test-%"})

        db_connection.commit()
    except Exception as e:
        print(f"Cleanup error: {e}")
        db_connection.rollback()


@pytest.fixture(scope="function")
def cleanup_test_citations(db_connection):
    """Clean up test citations after test."""
    yield
    # Cleanup after test
    try:
        db_connection.execute(text("""
            DELETE FROM citations WHERE business_name LIKE :pattern
        """), {"pattern": "Test %"})

        db_connection.commit()
    except Exception as e:
        print(f"Cleanup error: {e}")
        db_connection.rollback()


@pytest.fixture(scope="function")
def cleanup_test_change_log(db_connection):
    """Clean up test change_log entries after test."""
    yield
    # Cleanup after test
    try:
        db_connection.execute(text("""
            DELETE FROM change_log
            WHERE metadata->>'test_scenario' IS NOT NULL
        """))

        db_connection.commit()
    except Exception as e:
        print(f"Cleanup error: {e}")
        db_connection.rollback()


# Utility fixtures
@pytest.fixture
def assert_sql_count():
    """Helper to assert SQL query returns expected row count."""
    def _assert_count(connection, query, expected_count, params=None):
        result = connection.execute(text(query), params or {})
        actual_count = result.fetchone()[0]
        assert actual_count == expected_count, \
            f"Expected {expected_count} rows, got {actual_count}"
    return _assert_count


@pytest.fixture
def wait_for_task():
    """Helper to wait for task_logs entry to complete."""
    import time

    def _wait(connection, task_name, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            result = connection.execute(text("""
                SELECT status FROM task_logs
                WHERE task_name = :task_name
                ORDER BY started_at DESC LIMIT 1
            """), {"task_name": task_name})

            row = result.fetchone()
            if row and row[0] in ('success', 'failed'):
                return row[0]

            time.sleep(1)

        raise TimeoutError(f"Task {task_name} did not complete in {timeout}s")

    return _wait
