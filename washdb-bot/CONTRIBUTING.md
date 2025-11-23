# Contributing to URL Scrape Bot

Thank you for your interest in contributing to the URL Scrape Bot! This document provides guidelines and best practices for contributing to the project.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Quality Standards](#code-quality-standards)
- [Testing Guidelines](#testing-guidelines)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Pull Request Process](#pull-request-process)
- [Project Structure](#project-structure)
- [Common Tasks](#common-tasks)

## Getting Started

### Prerequisites

- Python 3.11 or higher
- PostgreSQL 14 or higher
- Git
- Basic knowledge of web scraping and SQL

### Initial Setup

1. **Fork the repository** on GitHub

2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/URL-Scrape-Bot.git
   cd URL-Scrape-Bot/washdb-bot
   ```

3. **Run the setup script**:
   ```bash
   ./scripts/dev/setup.sh
   ```

   This will:
   - Create a virtual environment
   - Install all dependencies
   - Install Playwright browsers
   - Verify PostgreSQL connection
   - Initialize the database

4. **Configure your environment**:
   ```bash
   cp .env.dev.example .env.dev
   # Edit .env.dev with your settings
   ```

5. **Verify installation**:
   ```bash
   python runner/bootstrap.py
   ```

See [docs/QUICKSTART-dev.md](docs/QUICKSTART-dev.md) for detailed setup instructions.

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/my-feature
# Or for bug fixes:
git checkout -b fix/bug-description
```

**Branch naming conventions**:
- `feature/` - New features
- `fix/` - Bug fixes
- `refactor/` - Code refactoring
- `docs/` - Documentation updates
- `test/` - Test additions/improvements

### 2. Make Your Changes

- Write clear, self-documenting code
- Follow the existing code style
- Add tests for new functionality
- Update documentation as needed

### 3. Test Your Changes

```bash
# Run all checks before committing
./scripts/dev/check.sh

# Or run individually:
./scripts/dev/format.sh  # Format code
./scripts/dev/lint.sh    # Lint code
pytest tests/            # Run tests
```

### 4. Commit Your Changes

```bash
git add .
git commit -m "Add feature: description of what you did"
```

See [Commit Message Guidelines](#commit-message-guidelines) below.

### 5. Push to Your Fork

```bash
git push origin feature/my-feature
```

### 6. Create a Pull Request

Go to GitHub and create a pull request from your fork to the main repository.

## Code Quality Standards

### Code Formatting

We use **Black** for code formatting:

```bash
# Format all code
black .

# Or use the dev script
./scripts/dev/format.sh
```

**Black settings** (from `pyproject.toml`):
- Line length: 100 characters
- Target: Python 3.11+

### Code Linting

We use **Ruff** for linting:

```bash
# Check for linting issues
ruff check .

# Auto-fix some issues
ruff check --fix .

# Or use the dev script
./scripts/dev/lint.sh
```

**Enabled lint rules**:
- `E`, `W` - pycodestyle (PEP 8 compliance)
- `F` - pyflakes (logic errors)
- `I` - isort (import sorting)
- `UP` - pyupgrade (modern Python idioms)
- `B` - bugbear (likely bugs)
- `C4` - comprehensions
- `SIM` - simplify
- `RUF` - ruff-specific rules

### Pre-commit Hooks (Recommended)

Install pre-commit hooks to automatically check code before committing:

```bash
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

### Type Hints (Optional)

While not strictly required, type hints are encouraged for complex functions:

```python
def scrape_city(city: str, state: str, max_results: int = 100) -> list[dict]:
    """Scrape businesses from a city."""
    pass
```

## Testing Guidelines

### Test Organization

Tests are organized by type:

```
tests/
├── unit/          # Fast, isolated tests
├── integration/   # Tests requiring database
└── acceptance/    # End-to-end tests
```

### Writing Tests

**Unit tests** (fast, no external dependencies):
```python
import pytest
from scrape_yp.yp_parser import parse_phone_number

def test_parse_phone_number():
    assert parse_phone_number("(555) 123-4567") == "5551234567"
    assert parse_phone_number("555-123-4567") == "5551234567"
```

**Integration tests** (require database):
```python
@pytest.mark.integration
def test_save_company_to_database(db_session):
    company = {"name": "Test Co", "phone": "5551234567"}
    save_company(company, db_session)
    assert db_session.query(Company).count() == 1
```

**Acceptance tests** (end-to-end, may require network):
```python
@pytest.mark.acceptance
@pytest.mark.network
def test_yp_scraper_end_to_end():
    results = scrape_yp(city="Peoria", state="IL", max_results=5)
    assert len(results) > 0
    assert all("name" in r for r in results)
```

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific category
pytest tests/unit/
pytest tests/integration/
pytest -m "not slow"  # Skip slow tests

# Run with coverage
pytest --cov=scrape_yp --cov=niceui tests/

# Run specific test file
pytest tests/unit/test_yp_parser.py

# Run specific test
pytest tests/unit/test_yp_parser.py::test_parse_phone_number
```

### Test Markers

Use markers to categorize tests:

```python
@pytest.mark.slow  # Slow-running test
@pytest.mark.network  # Requires network access
@pytest.mark.integration  # Requires database
@pytest.mark.unit  # Pure unit test
```

## Commit Message Guidelines

### Format

```
<type>: <subject>

<body (optional)>
```

### Types

- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation changes
- `style` - Code style changes (formatting, no logic change)
- `refactor` - Code refactoring
- `test` - Adding or updating tests
- `chore` - Maintenance tasks

### Examples

**Good**:
```
feat: Add Google Maps city-first scraper

Implements a city-based scraping strategy for Google Maps that prioritizes
smaller cities for better targeting. Includes crash recovery and rate limiting.
```

**Good** (simple):
```
fix: Handle missing phone numbers in YP parser
```

**Bad**:
```
update stuff
```

**Bad** (too vague):
```
fix bug
```

### Best Practices

- Use imperative mood ("Add feature" not "Added feature")
- Keep subject line under 50 characters
- Capitalize subject line
- Don't end subject with period
- Separate subject from body with blank line
- Wrap body at 72 characters
- Explain **what** and **why**, not **how**

## Pull Request Process

### Before Submitting

- [ ] All tests pass: `pytest tests/`
- [ ] Code is formatted: `black .`
- [ ] No linting errors: `ruff check .`
- [ ] Documentation is updated (if applicable)
- [ ] Commit messages follow guidelines
- [ ] Branch is up to date with main

**Run all checks**:
```bash
./scripts/dev/check.sh
```

### PR Description Template

```markdown
## Summary
Brief description of what this PR does.

## Changes
- List of specific changes made
- Each change on its own line

## Testing
How was this tested?
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

## Screenshots (if applicable)
Add screenshots for UI changes

## Breaking Changes
List any breaking changes and migration steps

## Related Issues
Fixes #123
```

### Review Process

1. **Automated checks** must pass (CI/CD)
2. **Code review** by at least one maintainer
3. **Address feedback** and make requested changes
4. **Approval** from maintainer(s)
5. **Merge** (squash and merge for clean history)

## Project Structure

Understanding the codebase:

```
washdb-bot/
├── niceui/              # Web dashboard (NiceGUI)
├── scrape_yp/           # Yellow Pages scraper
├── scrape_google/       # Google Maps scraper
├── scrape_bing/         # Bing Local Search scraper
├── scrape_site/         # Website enrichment
├── seo_intelligence/    # SEO analysis
├── db/                  # Database models & migrations
├── scheduler/           # Job scheduling
├── runner/              # CLI orchestration
├── scripts/dev/         # Development scripts
├── tests/               # Test suite
├── docs/                # Documentation
└── legacy/              # Deprecated code (don't modify)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture.

## Common Tasks

### Adding a New Scraper Source

1. Create module: `scrape_newsource/`
2. Implement scraper class with standard interface
3. Add database models if needed
4. Create CLI entry point: `cli_crawl_newsource.py`
5. Integrate with NiceGUI dashboard
6. Add tests
7. Update documentation

### Adding a New Database Table

1. Define model in `db/models.py`
2. Create migration: `db/migrations/XXX_add_new_table.sql`
3. Update `db/init_db.py` if needed
4. Add to `docs/SCHEMA_REFERENCE.md`
5. Test migration on fresh database

### Adding a New Dashboard Page

1. Create page: `niceui/pages/my_page.py`
2. Register in `niceui/main.py`
3. Add navigation link
4. Test UI responsiveness
5. Document in `docs/gui/`

### Debugging Tips

1. **Enable DEBUG logging**:
   ```bash
   LOG_LEVEL=DEBUG python cli_crawl_yp.py
   ```

2. **Check logs**:
   ```bash
   tail -f logs/yp_crawl_city_first.log
   ```

3. **Use the dashboard**:
   - Logs tab for real-time monitoring
   - Database tab to inspect data
   - Diagnostics tab for health checks

4. **See log reference**: [docs/LOGS.md](docs/LOGS.md)

## Getting Help

- **Documentation**: Start with [docs/index.md](docs/index.md)
- **Architecture**: See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Logs**: Reference [docs/LOGS.md](docs/LOGS.md)
- **Issues**: Search existing GitHub issues
- **Questions**: Open a GitHub discussion

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the project
- Show empathy towards other community members

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for contributing!** Your efforts help make this project better for everyone.
