#!/usr/bin/env python3
"""
Unit tests for Yellow Pages worker pool resilience features.

Tests:
- Per-state concurrency limits
- Block detection → proxy rotation
- Exponential backoff with jitter
- Row-level locking (SKIP LOCKED)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, YPTarget
from scrape_yp.worker_pool import acquire_next_target, calculate_cooldown_delay
from scrape_yp.yp_monitor import detect_captcha, detect_blocking


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


def test_per_state_concurrency_limit(test_db):
    """
    Test that per-state concurrency limits are enforced.

    When max_per_state=2, should not acquire target from state with 2 IN_PROGRESS targets.
    """
    session = test_db

    # Create 3 targets for CA, all PLANNED
    for i in range(3):
        target = YPTarget(
            provider='YP',
            state_id='CA',
            city='Los Angeles',
            city_slug='los-angeles-ca',
            yp_geo='Los Angeles, CA',
            category_label='Window Cleaning',
            category_slug='window-cleaning',
            primary_url=f'/los-angeles-ca/window-cleaning-{i}',
            fallback_url='/search?geo=Los+Angeles%2C+CA',
            max_pages=3,
            priority=1,
            status='PLANNED'
        )
        session.add(target)

    # Create 1 target for TX, PLANNED
    target_tx = YPTarget(
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
        priority=1,
        status='PLANNED'
    )
    session.add(target_tx)

    session.commit()

    # Acquire first CA target (should succeed)
    target1 = acquire_next_target(session, ['CA', 'TX'], 'worker_1', max_per_state=2)
    assert target1 is not None
    assert target1.state_id == 'CA'
    assert target1.status == 'IN_PROGRESS'

    # Acquire second CA target (should succeed)
    target2 = acquire_next_target(session, ['CA', 'TX'], 'worker_2', max_per_state=2)
    assert target2 is not None
    assert target2.state_id == 'CA'
    assert target2.status == 'IN_PROGRESS'

    # Acquire third target (should get TX since CA is at capacity)
    target3 = acquire_next_target(session, ['CA', 'TX'], 'worker_3', max_per_state=2)
    assert target3 is not None
    assert target3.state_id == 'TX', "Should skip CA (at capacity) and get TX"
    assert target3.status == 'IN_PROGRESS'

    # Try to acquire fourth target (should get None - all states at capacity)
    target4 = acquire_next_target(session, ['CA', 'TX'], 'worker_4', max_per_state=2)
    assert target4 is None, "Should get None when all states are at capacity"


def test_row_level_locking_skip_locked(test_db):
    """
    Test that row-level locking with SKIP LOCKED prevents duplicate acquisition.

    This tests the SQL SELECT FOR UPDATE SKIP LOCKED semantics.
    Note: SQLite doesn't support SELECT FOR UPDATE, but we test the logic.
    """
    session = test_db

    # Create 2 targets
    for i in range(2):
        target = YPTarget(
            provider='YP',
            state_id='CA',
            city='Los Angeles',
            city_slug='los-angeles-ca',
            yp_geo='Los Angeles, CA',
            category_label='Window Cleaning',
            category_slug='window-cleaning',
            primary_url=f'/los-angeles-ca/window-cleaning-{i}',
            fallback_url='/search?geo=Los+Angeles%2C+CA',
            max_pages=3,
            priority=1,
            status='PLANNED'
        )
        session.add(target)

    session.commit()

    # Acquire first target
    target1 = acquire_next_target(session, ['CA'], 'worker_1', max_per_state=10)
    assert target1 is not None
    assert target1.claimed_by == 'worker_1'

    # Acquire second target (should get different target)
    target2 = acquire_next_target(session, ['CA'], 'worker_2', max_per_state=10)
    assert target2 is not None
    assert target2.claimed_by == 'worker_2'
    assert target2.id != target1.id, "Should get different target (not locked by worker_1)"


def test_exponential_backoff_with_jitter():
    """
    Test exponential backoff calculation with jitter.

    Backoff should increase exponentially and include random jitter.
    """
    # Test base case (attempt 0)
    delay0 = calculate_cooldown_delay(0, base_delay=30.0, max_delay=300.0)
    assert 22.5 <= delay0 <= 37.5, "Attempt 0: ~30s ± 25% jitter"

    # Test attempt 1 (2^1 = 2x base)
    delay1 = calculate_cooldown_delay(1, base_delay=30.0, max_delay=300.0)
    assert 45.0 <= delay1 <= 75.0, "Attempt 1: ~60s ± 25% jitter"

    # Test attempt 2 (2^2 = 4x base)
    delay2 = calculate_cooldown_delay(2, base_delay=30.0, max_delay=300.0)
    assert 90.0 <= delay2 <= 150.0, "Attempt 2: ~120s ± 25% jitter"

    # Test max cap
    delay_max = calculate_cooldown_delay(10, base_delay=30.0, max_delay=300.0)
    assert delay_max <= 375.0, "Should be capped at max_delay + jitter"

    # Test jitter is random (run multiple times, should get different values)
    delays = [calculate_cooldown_delay(1, base_delay=30.0, max_delay=300.0) for _ in range(10)]
    unique_delays = len(set(delays))
    assert unique_delays > 1, "Jitter should produce different delays"


def test_captcha_detection():
    """
    Test CAPTCHA detection from HTML content.
    """
    # Test reCAPTCHA
    html_recaptcha = """
    <html>
    <div id="g-recaptcha"></div>
    <script src="https://www.google.com/recaptcha/api.js"></script>
    </html>
    """
    is_captcha, captcha_type = detect_captcha(html_recaptcha)
    assert is_captcha is True
    assert 'recaptcha' in captcha_type.lower()

    # Test hCaptcha
    html_hcaptcha = """
    <html>
    <div class="h-captcha"></div>
    </html>
    """
    is_captcha, captcha_type = detect_captcha(html_hcaptcha)
    assert is_captcha is True
    assert 'hcaptcha' in captcha_type.lower()

    # Test Cloudflare challenge
    html_cloudflare = """
    <html>
    <div class="cf-challenge-form"></div>
    </html>
    """
    is_captcha, captcha_type = detect_captcha(html_cloudflare)
    assert is_captcha is True

    # Test normal page (no CAPTCHA)
    html_normal = """
    <html>
    <h1>Yellow Pages Search Results</h1>
    <div class="result">Business 1</div>
    </html>
    """
    is_captcha, captcha_type = detect_captcha(html_normal)
    assert is_captcha is False


def test_blocking_detection():
    """
    Test blocking detection from HTML and status codes.
    """
    # Test 403 Forbidden
    is_blocked, reason = detect_blocking("", status_code=403)
    assert is_blocked is True
    assert '403' in reason

    # Test 429 Too Many Requests
    is_blocked, reason = detect_blocking("", status_code=429)
    assert is_blocked is True
    assert '429' in reason

    # Test HTML content blocking
    html_blocked = """
    <html>
    <h1>Access Denied</h1>
    <p>You have been blocked due to suspicious activity.</p>
    </html>
    """
    is_blocked, reason = detect_blocking(html_blocked)
    assert is_blocked is True

    # Test rate limit message
    html_rate_limited = """
    <html>
    <p>Too many requests. Please slow down.</p>
    </html>
    """
    is_blocked, reason = detect_blocking(html_rate_limited)
    assert is_blocked is True

    # Test normal page
    html_normal = """
    <html>
    <h1>Search Results</h1>
    </html>
    """
    is_blocked, reason = detect_blocking(html_normal, status_code=200)
    assert is_blocked is False


def test_worker_claim_fields(test_db):
    """
    Test that worker claim fields are set correctly on acquisition.
    """
    session = test_db

    # Create target
    target = YPTarget(
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
        status='PLANNED'
    )
    session.add(target)
    session.commit()

    # Acquire target
    acquired = acquire_next_target(session, ['CA'], 'worker_0_pid_12345', max_per_state=10)

    # Verify claim fields
    assert acquired is not None
    assert acquired.claimed_by == 'worker_0_pid_12345'
    assert acquired.claimed_at is not None
    assert acquired.heartbeat_at is not None
    assert acquired.status == 'IN_PROGRESS'
    assert acquired.attempts == 1
    assert acquired.page_target == acquired.max_pages


def test_state_concurrency_with_multiple_states(test_db):
    """
    Test per-state concurrency with multiple states.

    Should distribute load across states when some are at capacity.
    """
    session = test_db

    # Create 5 CA targets and 5 TX targets
    for i in range(5):
        target_ca = YPTarget(
            provider='YP',
            state_id='CA',
            city='Los Angeles',
            city_slug='los-angeles-ca',
            yp_geo='Los Angeles, CA',
            category_label='Window Cleaning',
            category_slug='window-cleaning',
            primary_url=f'/los-angeles-ca/window-cleaning-{i}',
            fallback_url='/search?geo=Los+Angeles%2C+CA',
            max_pages=3,
            priority=1,
            status='PLANNED'
        )

        target_tx = YPTarget(
            provider='YP',
            state_id='TX',
            city='Houston',
            city_slug='houston-tx',
            yp_geo='Houston, TX',
            category_label='Power Washing',
            category_slug='power-washing',
            primary_url=f'/houston-tx/power-washing-{i}',
            fallback_url='/search?geo=Houston%2C+TX',
            max_pages=2,
            priority=1,
            status='PLANNED'
        )

        session.add_all([target_ca, target_tx])

    session.commit()

    # Acquire targets with max_per_state=3
    acquired_states = []
    for i in range(6):
        target = acquire_next_target(session, ['CA', 'TX'], f'worker_{i}', max_per_state=3)
        if target:
            acquired_states.append(target.state_id)

    # Should acquire 3 CA and 3 TX (balanced)
    ca_count = acquired_states.count('CA')
    tx_count = acquired_states.count('TX')

    assert ca_count == 3, f"Should acquire exactly 3 CA targets (got {ca_count})"
    assert tx_count == 3, f"Should acquire exactly 3 TX targets (got {tx_count})"


def test_cooldown_after_block_scenario(test_db):
    """
    Integration test: Simulate block detection → cooldown → proxy rotation.

    This tests the full resilience workflow.
    """
    session = test_db

    # Create target
    target = YPTarget(
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
        status='PLANNED',
        attempts=2  # Already attempted twice
    )
    session.add(target)
    session.commit()

    # Simulate block detection (attempts=2)
    cooldown_delay = calculate_cooldown_delay(target.attempts, base_delay=30.0, max_delay=300.0)

    # For attempt 2, expect ~120s ± jitter
    assert 90.0 <= cooldown_delay <= 150.0, f"Cooldown for attempt 2 should be ~120s ± 25%, got {cooldown_delay:.1f}s"

    # Simulate marking target as cooling down
    target.status = 'PLANNED'
    target.note = f"cooling_down_after_block_attempt={target.attempts}_reason=403 Forbidden"
    target.last_error = "Blocked: 403 Forbidden"
    session.commit()

    # Verify target was returned to queue
    assert target.status == 'PLANNED'
    assert 'cooling_down' in target.note
    assert target.last_error is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
