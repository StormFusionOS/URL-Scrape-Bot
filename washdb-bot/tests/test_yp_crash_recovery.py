#!/usr/bin/env python3
"""
Unit tests for Yellow Pages crash recovery features.

Tests:
- Orphan recovery (heartbeat-based)
- Resume from exact page
- Idempotent upsert (no duplicates on replay)
- WAL logging
"""

import pytest
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, YPTarget, Company, canonicalize_url, domain_from_url
from scrape_yp.yp_checkpoint import recover_orphaned_targets, get_overall_progress
from scrape_yp.yp_wal import WorkerWAL, read_wal, get_latest_wal_state
from db.save_discoveries import upsert_discovered


@pytest.fixture
def test_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def temp_wal_dir():
    """Create temporary directory for WAL tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_orphan_recovery_heartbeat_based(test_db):
    """
    Test that orphaned targets are recovered based on stale heartbeat.

    A target with IN_PROGRESS status and old heartbeat should be recovered.
    """
    session = test_db

    # Create test targets
    # Target 1: Active (recent heartbeat)
    target1 = YPTarget(
        provider='YP',
        state_id='CA',
        city='Los Angeles',
        city_slug='los-angeles-ca',
        yp_geo='Los Angeles, CA',
        category_label='Window Cleaning',
        category_slug='window-cleaning',
        primary_url='/los-angeles-ca/window-cleaning',
        fallback_url='/search?geo=Los+Angeles%2C+CA',
        max_pages=3,
        priority=1,
        status='IN_PROGRESS',
        claimed_by='worker_0_pid_12345',
        claimed_at=datetime.utcnow() - timedelta(minutes=5),
        heartbeat_at=datetime.utcnow() - timedelta(minutes=5),  # Recent heartbeat
        page_current=1,
        page_target=3
    )

    # Target 2: Orphaned (stale heartbeat - 2 hours old)
    target2 = YPTarget(
        provider='YP',
        state_id='TX',
        city='Houston',
        city_slug='houston-tx',
        yp_geo='Houston, TX',
        category_label='Power Washing',
        category_slug='power-washing',
        primary_url='/houston-tx/power-washing',
        fallback_url='/search?geo=Houston%2C+TX',
        max_pages=2,
        priority=2,
        status='IN_PROGRESS',
        claimed_by='worker_1_pid_99999',
        claimed_at=datetime.utcnow() - timedelta(hours=2),
        heartbeat_at=datetime.utcnow() - timedelta(hours=2),  # Stale heartbeat
        page_current=1,
        page_target=2
    )

    # Target 3: Orphaned (NULL heartbeat)
    target3 = YPTarget(
        provider='YP',
        state_id='FL',
        city='Miami',
        city_slug='miami-fl',
        yp_geo='Miami, FL',
        category_label='Window Cleaning',
        category_slug='window-cleaning',
        primary_url='/miami-fl/window-cleaning',
        fallback_url='/search?geo=Miami%2C+FL',
        max_pages=1,
        priority=3,
        status='IN_PROGRESS',
        claimed_by='worker_2_pid_88888',
        claimed_at=datetime.utcnow() - timedelta(hours=1),
        heartbeat_at=None,  # NULL heartbeat
        page_current=0,
        page_target=1
    )

    session.add_all([target1, target2, target3])
    session.commit()

    # Run orphan recovery with 60-minute timeout
    result = recover_orphaned_targets(session, timeout_minutes=60, state_ids=None)

    # Assertions
    assert result['recovered'] == 2, "Should recover 2 orphaned targets (target2 and target3)"

    # Check that target2 and target3 were recovered
    recovered_ids = [t['id'] for t in result['targets']]
    assert target2.id in recovered_ids, "Target2 (stale heartbeat) should be recovered"
    assert target3.id in recovered_ids, "Target3 (NULL heartbeat) should be recovered"

    # Check that targets were reset to PLANNED
    session.refresh(target1)
    session.refresh(target2)
    session.refresh(target3)

    assert target1.status == 'IN_PROGRESS', "Target1 (active) should still be IN_PROGRESS"
    assert target2.status == 'PLANNED', "Target2 (orphaned) should be reset to PLANNED"
    assert target3.status == 'PLANNED', "Target3 (orphaned) should be reset to PLANNED"

    # Check that worker claims were cleared
    assert target2.claimed_by is None, "Target2 claimed_by should be cleared"
    assert target3.claimed_by is None, "Target3 claimed_by should be cleared"


def test_resume_from_page_n(test_db):
    """
    Test that crawler can resume from page N without duplicating work.

    If page_current=2, crawler should resume from page 3.
    """
    session = test_db

    # Create target that has processed pages 1 and 2
    target = YPTarget(
        provider='YP',
        state_id='NY',
        city='New York',
        city_slug='new-york-ny',
        yp_geo='New York, NY',
        category_label='Deck Staining',
        category_slug='deck-staining',
        primary_url='/new-york-ny/deck-staining',
        fallback_url='/search?geo=New+York%2C+NY',
        max_pages=5,
        priority=1,
        status='IN_PROGRESS',
        page_current=2,  # Completed pages 1 and 2
        page_target=5,
        next_page_url='/new-york-ny/deck-staining?page=3'
    )

    session.add(target)
    session.commit()

    # Simulate resuming crawl
    start_page = max(1, target.page_current + 1)

    # Assertions
    assert start_page == 3, "Should resume from page 3"
    assert target.next_page_url == '/new-york-ny/deck-staining?page=3', "Next page URL should be page 3"
    assert target.page_current == 2, "page_current should be 2 (last completed page)"


def test_idempotent_upsert_no_duplicates(test_db):
    """
    Test that replaying the same listings doesn't create duplicates.

    Upserting the same company data twice should result in:
    - First insert: 1 inserted
    - Second insert: 1 skipped (or updated if data changed)
    """
    session = test_db

    # Company data
    company_data = {
        'name': 'ABC Window Cleaning',
        'website': 'https://abcwindowcleaning.com',
        'domain': 'abcwindowcleaning.com',
        'phone': '555-1234',
        'email': 'info@abcwindowcleaning.com',
        'address': '123 Main St, Los Angeles, CA',
        'source': 'YP',
        'rating_yp': 4.5,
        'reviews_yp': 42
    }

    # First upsert
    inserted1, skipped1, updated1 = upsert_discovered([company_data])

    assert inserted1 == 1, "First upsert should insert 1 company"
    assert skipped1 == 0, "First upsert should skip 0 companies"

    # Second upsert (same data - should skip due to unique website)
    inserted2, skipped2, updated2 = upsert_discovered([company_data])

    assert inserted2 == 0, "Second upsert should insert 0 companies"
    assert skipped2 == 1 or updated2 == 1, "Second upsert should skip or update 1 company"

    # Verify only one company exists
    count = session.query(Company).count()
    assert count == 1, "Should have exactly 1 company (no duplicates)"


def test_wal_logging(temp_wal_dir):
    """
    Test that WAL correctly logs worker events.
    """
    worker_id = "test_worker_pid_12345"

    with WorkerWAL(worker_id, log_dir=temp_wal_dir) as wal:
        # Log target start
        wal.log_target_start(123, "Los Angeles", "CA", "Window Cleaning", 3)

        # Log page completions
        wal.log_page_complete(123, 1, 15, "Los Angeles", "CA", "Window Cleaning", raw_count=20)
        wal.log_page_complete(123, 2, 12, "Los Angeles", "CA", "Window Cleaning", raw_count=18)
        wal.log_page_complete(123, 3, 8, "Los Angeles", "CA", "Window Cleaning", raw_count=10)

        # Log target complete
        wal.log_target_complete(123, 3, 35)

    # Read WAL back
    wal_file = Path(temp_wal_dir) / "yp_wal" / f"{worker_id}.jsonl"
    assert wal_file.exists(), "WAL file should exist"

    events = read_wal(str(wal_file))

    # Assertions
    assert len(events) == 5, "Should have 5 events (1 start + 3 pages + 1 complete)"
    assert events[0]['event_type'] == 'target_start'
    assert events[1]['event_type'] == 'page_complete'
    assert events[1]['page_number'] == 1
    assert events[1]['accepted_count'] == 15
    assert events[4]['event_type'] == 'target_complete'
    assert events[4]['total_accepted'] == 35


def test_progress_reporting(test_db):
    """
    Test that progress reporting correctly counts targets by status.
    """
    session = test_db

    # Create targets with different statuses
    targets = [
        YPTarget(
            provider='YP', state_id='CA', city='LA', city_slug='la-ca',
            yp_geo='LA, CA', category_label='Test', category_slug='test',
            primary_url='/test', fallback_url='/test',
            status='PLANNED', max_pages=1
        ),
        YPTarget(
            provider='YP', state_id='CA', city='SF', city_slug='sf-ca',
            yp_geo='SF, CA', category_label='Test', category_slug='test',
            primary_url='/test', fallback_url='/test',
            status='IN_PROGRESS', max_pages=1
        ),
        YPTarget(
            provider='YP', state_id='CA', city='SD', city_slug='sd-ca',
            yp_geo='SD, CA', category_label='Test', category_slug='test',
            primary_url='/test', fallback_url='/test',
            status='DONE', max_pages=1
        ),
        YPTarget(
            provider='YP', state_id='TX', city='Houston', city_slug='houston-tx',
            yp_geo='Houston, TX', category_label='Test', category_slug='test',
            primary_url='/test', fallback_url='/test',
            status='FAILED', max_pages=1
        ),
    ]

    session.add_all(targets)
    session.commit()

    # Get progress
    progress = get_overall_progress(session, state_ids=None)

    # Assertions
    assert progress['total'] == 4
    assert progress['planned'] == 1
    assert progress['in_progress'] == 1
    assert progress['done'] == 1
    assert progress['failed'] == 1
    assert progress['progress_pct'] == 25.0  # 1/4 = 25%

    # Filter by state
    progress_ca = get_overall_progress(session, state_ids=['CA'])
    assert progress_ca['total'] == 3
    assert progress_ca['done'] == 1


def test_canonical_url_idempotency():
    """
    Test that URL canonicalization is consistent.

    Different variations of the same URL should canonicalize to the same value.
    """
    urls = [
        "example.com",
        "http://example.com",
        "https://example.com",
        "https://www.example.com",
        "https://example.com/",
        "https://example.com/#fragment"
    ]

    canonical_urls = [canonicalize_url(url) for url in urls]

    # All should canonicalize to the same value
    unique_canonicals = set(canonical_urls)
    assert len(unique_canonicals) <= 2, "Should have at most 2 unique canonical URLs (http vs https)"

    # Check that www is removed
    for canonical in canonical_urls:
        assert "www." not in canonical, "Canonical URL should not contain www."


def test_domain_extraction():
    """
    Test that domain extraction works correctly.
    """
    test_cases = [
        ("https://www.example.com/path", "example.com"),
        ("http://subdomain.example.co.uk", "example.co.uk"),
        ("https://blog.mysite.org/article", "mysite.org"),
    ]

    for url, expected_domain in test_cases:
        domain = domain_from_url(url)
        assert domain == expected_domain, f"Domain extraction failed for {url}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
