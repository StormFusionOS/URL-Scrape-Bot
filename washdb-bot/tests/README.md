# Test Suite Documentation

This directory contains the comprehensive test suite for the URL Scrape Bot. Tests are organized by type to make it easy to run specific categories.

## Test Organization

```
tests/
├── unit/          # Fast, isolated unit tests (9 tests)
├── integration/   # Tests requiring database/external services (14 tests)
├── acceptance/    # End-to-end acceptance tests (2 tests)
├── conftest.py    # Shared pytest fixtures
└── README.md      # This file
```

### Test Categories

#### Unit Tests (`tests/unit/`)

**Purpose**: Test individual functions and modules in isolation without external dependencies.

**Characteristics**:
- Fast (< 1 second each)
- No database required
- No network access
- Pure logic testing

**Files**:
- `test_yp_parsing.py` - YP HTML parsing logic
- `test_yp_filter.py` - Business filtering logic
- `test_yp_stealth.py` - Stealth feature tests
- `test_yp_advanced_stealth.py` - Advanced anti-detection
- `test_enhanced_yp.py` - Enhanced YP scraper features
- `test_config.py` - Configuration loading and validation
- `test_scrape.py` - Generic scraping utilities
- `test_state_splitting.py` - State distribution logic
- `test_all_pages.py` - Page navigation logic

#### Integration Tests (`tests/integration/`)

**Purpose**: Test components working together with external dependencies (database, scheduler, etc.).

**Characteristics**:
- Moderate speed (1-10 seconds each)
- Require database connection
- May use test fixtures
- Test data persistence and state

**Files**:
- `test_yp_crash_recovery.py` - Crash recovery mechanisms
- `test_yp_resilience.py` - Resilience and retry logic
- `test_yp_data_quality.py` - Data quality validation
- `test_yp_dedup.py` - Deduplication logic
- `test_yp_monitor.py` - Monitoring and alerts
- `test_google_crawler.py` - Google Maps crawler integration
- `test_google_scraper.py` - Google scraper integration
- `test_keyword_dashboard.py` - Dashboard integration
- `test_scheduler.py` - Job scheduling
- `test_phase2a_components.py` - Phase 2A component tests
- `test_phase2a_services_only.py` - Services-only tests
- `test_phase2a_standalone.py` - Standalone integration tests
- `test_scraper_environment.py` - Environment validation
- `test_scraper_safety.py` - Safety mechanisms

#### Acceptance Tests (`tests/acceptance/`)

**Purpose**: End-to-end tests validating complete user workflows.

**Characteristics**:
- Slow (10+ seconds each)
- Require full system (database, browser, network)
- Test real-world scenarios
- May hit actual websites (use sparingly)

**Files**:
- `test_scraper_acceptance.py` - Scraper acceptance tests
- `test_all_features.py` - Complete feature validation

## Running Tests

### Run All Tests

```bash
pytest tests/
```

### Run Specific Categories

```bash
# Unit tests only (fast)
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Acceptance tests only (slow)
pytest tests/acceptance/
```

### Run Specific Test File

```bash
pytest tests/unit/test_yp_parsing.py
```

### Run Specific Test

```bash
pytest tests/unit/test_yp_parsing.py::test_parse_phone_number
```

### Skip Slow Tests

```bash
pytest -m "not slow"
```

### Run with Coverage

```bash
# Coverage for specific modules
pytest --cov=scrape_yp --cov=scrape_google tests/

# Coverage report in HTML
pytest --cov=scrape_yp --cov-report=html tests/
open htmlcov/index.html
```

### Verbose Output

```bash
pytest -v tests/
pytest -vv tests/  # Extra verbose
```

### Stop on First Failure

```bash
pytest -x tests/
```

### Run Tests Matching Pattern

```bash
pytest -k "yp" tests/  # Run all YP-related tests
pytest -k "parsing" tests/  # Run all parsing tests
```

## Test Markers

Tests are marked with decorators to categorize them:

```python
@pytest.mark.unit  # Unit test
@pytest.mark.integration  # Integration test
@pytest.mark.acceptance  # Acceptance test
@pytest.mark.slow  # Slow-running test
@pytest.mark.network  # Requires network access
```

### Use Markers to Filter Tests

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"

# Run tests that require network
pytest -m network

# Run integration tests that are not slow
pytest -m "integration and not slow"
```

## Writing New Tests

### Unit Test Template

```python
"""Unit tests for module_name."""
import pytest


def test_function_name():
    """Test description."""
    # Arrange
    input_value = "test"

    # Act
    result = function_to_test(input_value)

    # Assert
    assert result == expected_value
```

### Integration Test Template

```python
"""Integration tests for module_name."""
import pytest


@pytest.mark.integration
def test_database_operation(db_session):
    """Test description requiring database."""
    # Use db_session fixture from conftest.py
    record = MyModel(name="test")
    db_session.add(record)
    db_session.commit()

    assert db_session.query(MyModel).count() == 1
```

### Acceptance Test Template

```python
"""Acceptance tests for complete workflows."""
import pytest


@pytest.mark.acceptance
@pytest.mark.slow
@pytest.mark.network
def test_end_to_end_scraping():
    """Test complete scraping workflow."""
    # Test full workflow from start to finish
    results = run_complete_scrape(city="Test City", max_results=5)

    assert len(results) > 0
    assert all("name" in r for r in results)
```

## Test Fixtures

Common fixtures are defined in `conftest.py`:

- `db_session` - Test database session
- `temp_dir` - Temporary directory for test files
- `mock_response` - Mocked HTTP responses
- `sample_html` - Sample HTML for parsing tests

### Using Fixtures

```python
def test_with_fixture(db_session):
    """Test using db_session fixture."""
    # db_session is automatically provided by pytest
    pass
```

## Testing Best Practices

### 1. Test Independence

Each test should be independent and not rely on other tests:

```python
# Good
def test_function_a():
    result = function_a()
    assert result == expected

def test_function_b():
    result = function_b()
    assert result == expected

# Bad - test_b depends on test_a
def test_a():
    global state
    state = setup()

def test_b():
    # Assumes test_a ran first
    result = use_state(state)
```

### 2. Descriptive Names

Use clear, descriptive test names:

```python
# Good
def test_parse_phone_number_with_dashes():
def test_save_company_creates_database_record():

# Bad
def test_1():
def test_stuff():
```

### 3. One Assert Per Test (Generally)

Focus each test on one thing:

```python
# Good
def test_phone_parsing():
    assert parse_phone("555-1234") == "5551234"

def test_phone_validation():
    assert is_valid_phone("5551234") == True

# Less ideal (but sometimes acceptable)
def test_phone_processing():
    assert parse_phone("555-1234") == "5551234"
    assert is_valid_phone("5551234") == True
    assert format_phone("5551234") == "(555) 1234"
```

### 4. Use Arrange-Act-Assert Pattern

```python
def test_example():
    # Arrange - set up test data
    input_data = {"name": "Test"}

    # Act - execute the function being tested
    result = process_data(input_data)

    # Assert - verify the result
    assert result["status"] == "success"
```

### 5. Mock External Dependencies

For unit tests, mock external services:

```python
from unittest.mock import patch, Mock

@patch('requests.get')
def test_api_call(mock_get):
    """Test API call without hitting real API."""
    mock_get.return_value = Mock(status_code=200, json=lambda: {"data": "test"})

    result = fetch_data()

    assert result == {"data": "test"}
    mock_get.assert_called_once()
```

## Continuous Integration

Tests run automatically on:
- Every commit (via pre-commit hooks - optional)
- Every pull request (via GitHub Actions)
- Before releases

### Pre-commit Hook

Install to run tests before each commit:

```bash
pre-commit install

# Run manually
pre-commit run --all-files
```

## Troubleshooting Tests

### Test Fails Locally But Passes in CI

- Check Python version (must be 3.11+)
- Ensure all dependencies installed: `pip install -r requirements.txt`
- Clear pytest cache: `rm -rf .pytest_cache`

### Database Tests Fail

- Ensure PostgreSQL is running
- Check `DATABASE_URL` in `.env`
- Initialize test database: `python db/init_db.py`

### Import Errors

- Ensure `PYTHONPATH` includes project root
- From project root: `export PYTHONPATH=$(pwd)`
- Or use: `pytest` which handles this automatically

### Slow Tests

- Use markers to skip slow tests during development
- Run full suite before committing
- Optimize slow tests or mark as `@pytest.mark.slow`

## Coverage Goals

- **Unit tests**: 80%+ coverage of core logic
- **Integration tests**: Cover critical paths
- **Acceptance tests**: Cover main user workflows

Check coverage:

```bash
pytest --cov=scrape_yp --cov=scrape_google --cov=niceui tests/
```

## Adding New Test Categories

To add a new test category:

1. Create subdirectory: `tests/my_category/`
2. Add `__init__.py`
3. Add marker in `pyproject.toml`:
   ```toml
   markers = [
       "my_category: description of category"
   ]
   ```
4. Mark tests with `@pytest.mark.my_category`
5. Update this README

## Resources

- **pytest documentation**: https://docs.pytest.org/
- **Testing best practices**: See [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Project architecture**: See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- **Troubleshooting**: See [docs/LOGS.md](../docs/LOGS.md)

---

**Happy Testing!** 🧪

Remember: Good tests are the foundation of maintainable code.
