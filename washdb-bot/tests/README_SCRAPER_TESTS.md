# Scraper Bot Subsystem - Automated Test Suite

Comprehensive automated test suite for the AI SEO Automation System scraper bot subsystem.

## Overview

This test suite provides automated verification of:
- ✅ Database schema and environment setup
- ✅ Core scraper functionality (SERP, Competitor, Citation, Backlink, Technical)
- ✅ Safety and ethical crawling (robots.txt, rate limiting, quarantine)
- ✅ Data quality and normalization
- ✅ Governance and review-mode workflows
- ✅ Observability and health monitoring

## Test Files

### `conftest.py`
Shared fixtures and configuration for all tests. Provides:
- Database session management
- Service initialization (URL canonicalizer, domain quarantine, robots checker)
- Test data cleanup fixtures
- Utility helpers for assertions

### `test_scraper_environment.py` - Phase 1: Environment Validation
**Purpose:** Verify system is ready for scraper tests

**Test Classes:**
- `TestDatabaseSchema` - Verify all tables, columns, indexes, views exist
- `TestServicesHealth` - Verify all 17 service modules load without errors
- `TestBasicConnectivity` - Verify DNS, HTTP, Playwright, robots.txt fetching work
- `TestEnvironmentConfiguration` - Verify DATABASE_URL and config

**Run:** `pytest tests/test_scraper_environment.py -v`

**Expected:** All tests pass before running other test suites

---

### `test_scraper_acceptance.py` - Phase 2: Acceptance Tests
**Purpose:** Integration tests that run actual scrapers and verify database writes

**Test Classes:**
- `TestSERPModule` - SERP scraper creates snapshots, results, with correct ranks and is_ours flag
- `TestCompetitorCrawler` - Competitor crawler creates pages with hashes, JSON-LD, no duplicates
- `TestCitationsCrawler` - Citations crawler checks directories, handles NAP matching, respects robots
- `TestErrorHandling` - DNS failures, robots blocks, quarantine reason codes
- `TestReviewModeWorkflow` - Changes go to change_log with status=pending

**Run:**
```bash
# Run all acceptance tests (SLOW - makes real network requests)
pytest tests/test_scraper_acceptance.py -v

# Skip slow tests
pytest tests/test_scraper_acceptance.py -m "not slow" -v

# Run only SERP tests
pytest tests/test_scraper_acceptance.py::TestSERPModule -v
```

**⚠️ WARNING:** These tests make real network requests to Google, example.com, and citation directories. They may be slow (1-5 minutes) and could be rate-limited. Not recommended for CI/CD without mocking.

---

### `test_scraper_safety.py` - Phase 3: Safety & Smokescreen Tests
**Purpose:** Verify ethical crawling, anti-blocking, and safety mechanisms

**Test Classes:**
- `TestRobotsTxtCompliance` - Robots.txt disallow detection, user-agent rules, caching
- `TestRateLimitingAnd429` - Exponential backoff schedule, 429 auto-quarantine, retry tracking
- `TestHTTP403Quarantine` - 403 immediate quarantine, no retries
- `TestCAPTCHADetection` - CAPTCHA keyword detection, quarantine trigger, no false positives
- `TestServerErrors` - 5xx auto-quarantine after 3 failures
- `TestQuarantineExpiration` - Quarantine expiration, manual release
- `TestQuarantineStatistics` - Statistics reporting, active quarantine listing
- `TestBotDetection` - Bot detection keyword triggers
- `TestEthicalCrawling` - No bypass attempts, transparent user agent

**Run:** `pytest tests/test_scraper_safety.py -v`

**Expected:** All pass - demonstrates ethical crawling compliance

---

## Running Tests

### Prerequisites

1. **Database Setup:**
   ```bash
   # Ensure DATABASE_URL is set
   export DATABASE_URL="postgresql://washbot:Washdb123@127.0.0.1/washbot_db"

   # Run migration 025 to restore SEO intelligence tables
   PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db \
       -f db/migrations/025_restore_seo_intelligence_tables.sql
   ```

2. **Python Environment:**
   ```bash
   # Activate virtualenv
   source ./venv/bin/activate

   # Install test dependencies
   pip install pytest pytest-asyncio httpx
   ```

3. **Playwright (for browser tests):**
   ```bash
   playwright install chromium
   ```

### Quick Test Commands

```bash
# Run all tests (SLOW - includes integration tests)
pytest tests/ -v

# Run only fast tests (skip slow integration tests)
pytest tests/ -m "not slow" -v

# Run only safety tests
pytest tests/test_scraper_safety.py -v

# Run only environment validation
pytest tests/test_scraper_environment.py -v

# Run with coverage
pytest tests/ --cov=seo_intelligence --cov-report=html

# Run specific test class
pytest tests/test_scraper_acceptance.py::TestSERPModule -v

# Run specific test method
pytest tests/test_scraper_safety.py::TestRobotsTxtCompliance::test_robots_disallow_detection -v

# Verbose output with print statements
pytest tests/ -v -s

# Stop on first failure
pytest tests/ -x

# Show 10 slowest tests
pytest tests/ --durations=10
```

### Test Markers

Tests are marked with pytest markers for selective running:

- `@pytest.mark.acceptance` - Core acceptance tests (must pass for production)
- `@pytest.mark.safety` - Safety and compliance tests (must pass for ethical crawling)
- `@pytest.mark.integration` - Integration tests (make network requests)
- `@pytest.mark.slow` - Slow tests (>10 seconds, makes real scraper calls)

```bash
# Run only acceptance tests
pytest tests/ -m "acceptance" -v

# Run only safety tests
pytest tests/ -m "safety" -v

# Skip slow tests
pytest tests/ -m "not slow" -v

# Run acceptance tests but skip slow ones
pytest tests/ -m "acceptance and not slow" -v
```

### Continuous Integration

For CI/CD pipelines, run fast tests only:

```bash
# CI-friendly test run (no slow integration tests)
pytest tests/ -m "not slow" --tb=short --maxfail=5
```

For comprehensive testing before release:

```bash
# Full test suite with detailed output
pytest tests/ -v --tb=long --durations=20
```

---

## Test Coverage

### Minimum Production-Ready Tests (Priority 1)

These 13 tests **MUST PASS** before deploying to production:

1. ✅ **test_core_tables_exist** - Database schema valid
2. ✅ **test_all_services_import** - All services load
3. ✅ **test_dns_resolution** - Network connectivity
4. ✅ **test_robots_disallow_detection** - Robots.txt compliance
5. ✅ **test_429_auto_quarantine** - Rate limit handling
6. ✅ **test_403_immediate_quarantine** - Forbidden handling
7. ✅ **test_captcha_html_detection** - CAPTCHA detection
8. ✅ **test_exponential_backoff_schedule** - Backoff implemented
9. ✅ **test_url_canonicalizer_basic** - URL normalization works
10. ✅ **test_domain_quarantine_basic** - Quarantine works
11. ✅ **test_no_bypass_attempts** - Ethical crawling verified
12. ✅ **test_change_log_creation** - Review mode works
13. ✅ **test_database_connectivity** - DB accessible

Run priority 1 tests:
```bash
pytest tests/test_scraper_environment.py tests/test_scraper_safety.py \
    -m "acceptance" -v
```

### Integration Tests (Priority 2)

Run these before major releases (requires ~5-10 minutes):

```bash
pytest tests/test_scraper_acceptance.py -v
```

---

## Troubleshooting

### Test Failures

**Issue:** `test_core_tables_exist` fails with "Missing tables"
- **Fix:** Run migration 025: `PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db -f db/migrations/025_restore_seo_intelligence_tables.sql`

**Issue:** `test_playwright_browser_launch` fails
- **Fix:** Install Playwright browsers: `playwright install chromium`

**Issue:** `test_serp_scraper_basic` returns no results
- **Cause:** Google rate limiting or CAPTCHA
- **Fix:** Skip slow tests in CI: `pytest -m "not slow"`, or use mocks

**Issue:** `test_database_connectivity` fails
- **Cause:** DATABASE_URL not set or database not running
- **Fix:** Verify PostgreSQL is running and DATABASE_URL is correct

**Issue:** `ModuleNotFoundError` for seo_intelligence modules
- **Fix:** Run from washdb-bot directory with: `PYTHONPATH=. pytest tests/`

### Cleanup

Tests include automatic cleanup fixtures, but if test data persists:

```sql
-- Manual cleanup
DELETE FROM serp_results WHERE snapshot_id IN (
    SELECT snapshot_id FROM serp_snapshots WHERE query_id IN (
        SELECT query_id FROM search_queries WHERE query_text LIKE 'test_%'
    )
);
DELETE FROM serp_snapshots WHERE query_id IN (
    SELECT query_id FROM search_queries WHERE query_text LIKE 'test_%'
);
DELETE FROM search_queries WHERE query_text LIKE 'test_%';

DELETE FROM competitor_pages WHERE competitor_id IN (
    SELECT competitor_id FROM competitors WHERE domain LIKE 'test-%'
);
DELETE FROM competitors WHERE domain LIKE 'test-%';

DELETE FROM citations WHERE business_name LIKE 'Test %';

DELETE FROM change_log WHERE metadata->>'test_scenario' IS NOT NULL;
```

---

## Extending Tests

### Adding New Tests

1. **Create test class:**
   ```python
   class TestNewFeature:
       @pytest.mark.acceptance
       def test_new_functionality(self, db_connection):
           # Test implementation
           assert True
   ```

2. **Use fixtures from conftest.py:**
   ```python
   def test_with_fixtures(
       self,
       db_connection,
       url_canonicalizer,
       domain_quarantine,
       test_query_text
   ):
       # Fixtures provide clean state
       pass
   ```

3. **Add cleanup fixture if needed:**
   ```python
   @pytest.fixture(scope="function")
   def cleanup_my_test_data(db_connection):
       yield
       # Cleanup after test
       db_connection.execute(text("DELETE FROM my_table WHERE ..."))
       db_connection.commit()
   ```

### Custom Markers

Add custom markers to pytest.ini or conftest.py:

```python
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "my_marker: description"
    )
```

---

## Test Results Interpretation

### All Tests Pass ✅
- System is production-ready
- Scrapers are ethical and safe
- Database writes are correct
- Review mode is functional

### Some Tests Fail ⚠️
- **Environment tests fail:** Setup issue (DB, network, dependencies)
- **Safety tests fail:** Ethical crawling at risk - DO NOT DEPLOY
- **Acceptance tests fail:** Core functionality broken - investigate logs
- **Integration tests fail:** May be transient (rate limiting, network) - retry or mock

### Slow Test Performance
- Integration tests make real network requests (1-5 min expected)
- Skip with `-m "not slow"` for fast feedback
- Consider mocking for CI/CD pipelines

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Scraper Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: testpass
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio httpx
          playwright install chromium

      - name: Run database migrations
        run: |
          PGPASSWORD=testpass psql -h localhost -U postgres -d postgres \
              -f db/migrations/025_restore_seo_intelligence_tables.sql

      - name: Run fast tests
        env:
          DATABASE_URL: postgresql://postgres:testpass@localhost/postgres
        run: |
          pytest tests/ -m "not slow" -v --tb=short

      - name: Run safety tests
        env:
          DATABASE_URL: postgresql://postgres:testpass@localhost/postgres
        run: |
          pytest tests/test_scraper_safety.py -v
```

---

## Summary

This automated test suite provides:
- **116+ test cases** covering environment, acceptance, safety, data quality
- **Selective execution** with markers (skip slow tests, run only safety, etc.)
- **Automatic cleanup** via fixtures (no test data pollution)
- **Clear pass/fail criteria** for production readiness
- **CI/CD friendly** (fast tests complete in <30 seconds)

**Next Steps:**
1. Run `pytest tests/test_scraper_environment.py -v` to verify setup
2. Run `pytest tests/test_scraper_safety.py -v` to verify ethical crawling
3. Run `pytest tests/ -m "not slow" -v` for fast comprehensive test
4. Run `pytest tests/ -v` for full integration test before release

For questions or issues, see troubleshooting section above.
