# washdb-bot

A local web-scraping tool for collecting and storing business data from Yellow Pages, Google Maps, Bing Local Search, and individual business websites.

> **Status**: Currently in **local development phase**. Not deployed to production.

## Features

- **Multi-Source Discovery**: Scrape from Yellow Pages, Google Maps, and Bing Local Search
- **Website Enrichment**: Deep scrape individual business websites for emails, phones, and services
- **Modern Web Dashboard**: NiceGUI-based interface with real-time monitoring
- **Crash Recovery**: Automatic resume from interruptions with write-ahead logging
- **Anti-Detection**: Stealth features including user agent rotation, realistic delays, and proxy support
- **SEO Intelligence**: SERP tracking, competitor analysis, citation validation
- **PostgreSQL Storage**: Robust database with multi-source NAP tracking
- **Parallel Processing**: Multi-worker scraping for high throughput
- **Job Scheduling**: APScheduler-based cron jobs
- **Comprehensive Testing**: Unit, integration, and acceptance tests

## Quick Links

- **[Quick Start Guide](docs/QUICKSTART-dev.md)** - Get up and running in 5 minutes
- **[Architecture Overview](docs/ARCHITECTURE.md)** - Understand the system design
- **[Documentation Index](docs/index.md)** - Complete documentation hub
- **[Log Reference](docs/LOGS.md)** - Where to find logs when debugging

## Project Structure

```
washdb-bot/
├── niceui/             # NiceGUI web interface (primary UI)
├── scrape_yp/          # Yellow Pages scraper module
├── scrape_google/      # Google Maps scraper module
├── scrape_bing/        # Bing Local Search scraper module
├── scrape_site/        # Website enrichment scraper
├── seo_intelligence/   # SEO analysis and tracking
├── db/                 # Database models and migrations
├── scheduler/          # Job scheduling system
├── runner/             # Bootstrap and CLI runner
├── scripts/            # Utility and dev scripts
│   └── dev/           # Development scripts (setup, run, lint)
├── tests/              # Test suite
│   ├── unit/          # Unit tests
│   ├── integration/   # Integration tests
│   └── acceptance/    # End-to-end tests
├── docs/               # Documentation
│   ├── architecture/  # Architecture docs
│   ├── scrapers/      # Scraper-specific docs
│   ├── gui/           # Dashboard docs
│   └── ...
├── data/               # Data and artifacts
│   └── backups/       # Database backups
├── logs/               # Application logs
├── legacy/             # Deprecated code (archived)
│   └── gui_backend/   # Old Flask backend (DO NOT USE)
├── .env.example        # Environment variables template
├── requirements.txt    # Python dependencies
├── pyproject.toml      # Project configuration
└── README.md           # This file
```

### Legacy/Deprecated Components

- **legacy/gui_backend/**: Deprecated Flask-based backend. Replaced by `niceui/`. See [legacy/README.md](legacy/README.md) for details. **DO NOT USE**.

## Local Dev Setup

> **New to the project?** See the **[Quick Start Guide](docs/QUICKSTART-dev.md)** for step-by-step setup instructions.

**One-command setup** (once dev scripts are complete):
```bash
./scripts/dev/setup.sh    # Set up venv, install deps, verify DB
./scripts/dev/run-gui.sh   # Start the dashboard
```

**Manual setup**:
1. Python 3.11+ and PostgreSQL 14+ required
2. Create venv: `python3 -m venv venv && source venv/bin/activate`
3. Install deps: `pip install -r requirements.txt`
4. Install Playwright: `playwright install`
5. Configure `.env` (copy from `.env.example`)
6. Initialize DB: `python db/init_db.py`
7. Run dashboard: `python niceui/main.py`
8. Access at: http://localhost:8080

See [QUICKSTART-dev.md](docs/QUICKSTART-dev.md) for detailed instructions.

## Things We Are NOT Doing Yet

This project is currently in **local development mode**. The following production features are **not yet implemented**:

- ❌ **No production deployment** - Runs only on local machine
- ❌ **No system-wide cron** - Jobs scheduled manually via GUI
- ❌ **No remote access** - Dashboard binds to 127.0.0.1 only
- ❌ **No automated backups** - Manual backups only
- ❌ **No external alerting** - No email/Slack notifications yet
- ❌ **No auto-changes to external systems** - All actions are manual

**What we ARE doing:**
- ✅ Local PostgreSQL database
- ✅ Manual scraper runs (GUI or CLI)
- ✅ Crash recovery and resilience
- ✅ Comprehensive logging
- ✅ Testing infrastructure
- ✅ Code quality tooling

When ready, we'll add production hardening (cron, auth, TLS, remote access, etc.).

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- pip or pipx

## Setup Instructions

### 1. Clone the Repository

```bash
git clone <repository-url>
cd URL-Scrape-Bot/washdb-bot
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

Or install in editable mode:

```bash
pip install -e .
```

### 4. Set Up Database

Create the PostgreSQL database and user:

```bash
psql -U postgres
```

```sql
CREATE DATABASE washdb;
CREATE USER washbot WITH ENCRYPTED PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE washdb TO washbot;
\q
```

### 5. Configure Environment

Copy the example environment file and update with your credentials:

```bash
cp .env.example .env
```

Edit `.env` and update the `DATABASE_URL` with your actual password:

```
DATABASE_URL=postgresql+psycopg://washbot:your_secure_password@localhost:5432/washdb
```

### 6. Bootstrap the Application

Run the bootstrap script to verify setup:

```bash
python runner/bootstrap.py
```

You should see "Bootstrap OK" if everything is configured correctly.

## Running the Application

### Run the Dashboard (Recommended)

```bash
python niceui/main.py
# Or: python -m niceui
# Access at: http://localhost:8080
```

**Dashboard Features**:
- **Discover** - Trigger YP/Google/Bing scrapers
- **Scrape** - Website enrichment
- **Dashboard** - Stats and KPIs
- **Logs** - Real-time log viewer
- **Scheduler** - Manage cron jobs
- **Database** - Browse companies
- **Testing** - Run test suite

### Run Scrapers via CLI

**Yellow Pages Discovery**:
```bash
python cli_crawl_yp.py --states RI --max-targets 500 --categories "pressure washing"
```

**Google Maps Discovery**:
```bash
python cli_crawl_google_city_first.py --states RI --max-workers 2
```

**Website Enrichment**:
```bash
# Typically triggered from GUI or via db/update_details.py
python scrape_site/site_scraper.py
```

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for complete entry point documentation.

## Development

### Dev Scripts (Once Complete)

```bash
./scripts/dev/setup.sh     # One-command environment setup
./scripts/dev/run-gui.sh   # Run dashboard with dev config
./scripts/dev/run-scrape.sh --target yp --city "Peoria, IL"  # Run single test scrape
./scripts/dev/format.sh    # Format code with black
./scripts/dev/lint.sh      # Lint code with ruff
./scripts/dev/check.sh     # Run all checks (format + lint + tests)
```

### Run Tests

```bash
# Run all tests
pytest tests/

# Run specific test categories
pytest tests/unit/          # Unit tests only
pytest tests/integration/   # Integration tests
pytest tests/acceptance/    # End-to-end tests

# Run tests with coverage
pytest --cov=scrape_yp --cov=scrape_google --cov=niceui tests/
```

### Code Formatting & Linting

```bash
# Format code
black .

# Lint code
ruff check .

# Fix auto-fixable issues
ruff check --fix .
```

### Pre-commit Hooks (Optional)

```bash
# Install pre-commit hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## Configuration

Configuration is managed through environment variables in `.env` (or `.env.dev` for development).

**Key Settings**:
- `DATABASE_URL` - PostgreSQL connection string
- `NICEGUI_PORT` - Dashboard port (default: 8080)
- `WORKER_COUNT` - Parallel workers (default: 5, dev: 2)
- `CRAWL_DELAY_SECONDS` - Request delay (default: 10, dev: 15)
- `USE_PLAYWRIGHT` - Use headless browser (default: true)
- `ANTI_DETECTION_ENABLED` - Enable stealth (default: true)
- `PROXY_ROTATION_ENABLED` - Proxy rotation (default: true)
- `LOG_LEVEL` - Logging level (default: INFO)

See `.env.example` for full configuration template.
See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed configuration documentation.

## Database Schema

The database uses PostgreSQL with SQLAlchemy ORM. Key tables:

- `companies` - Main business data
- `yp_targets / google_targets / bing_targets` - Scraping targets with crash recovery
- `business_sources` - Multi-source NAP tracking
- `job_execution_logs` - Job history and governance
- `scheduled_jobs` - Cron job definitions

See [docs/SCHEMA_REFERENCE.md](docs/SCHEMA_REFERENCE.md) for complete schema documentation.

## Logging

Logs use rotating file handlers (10MB, 5 backups) in the `logs/` directory:

- `yp_crawl_city_first.log` - Yellow Pages scraper
- `google_crawl.log` - Google Maps scraper
- `site_scraper.log` - Website enrichment
- `backend_facade.log` - GUI backend

See [docs/LOGS.md](docs/LOGS.md) for log locations and common error patterns.

## License

MIT

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

**Quick workflow**:
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests and linting: `./scripts/dev/check.sh`
5. Commit your changes: `git commit -m "Add my feature"`
6. Push to your fork: `git push origin feature/my-feature`
7. Submit a pull request

## Documentation

- **[Quick Start Guide](docs/QUICKSTART-dev.md)** - Get up and running
- **[Architecture Overview](docs/ARCHITECTURE.md)** - System design
- **[Documentation Index](docs/index.md)** - Complete documentation
- **[Log Reference](docs/LOGS.md)** - Debugging guide
- **[Schema Reference](docs/SCHEMA_REFERENCE.md)** - Database schema

## Support

For issues and questions:
- Check the [documentation](docs/index.md) first
- Search existing GitHub issues
- Open a new issue with detailed information

## Roadmap

**Current Phase**: Local development (in progress)
- ✅ Multi-source scrapers (YP, Google, Bing)
- ✅ Modern NiceGUI dashboard
- ✅ Crash recovery
- 🔄 Dev experience improvements (this plan)

**Next Phase**: Production hardening
- System-wide cron scheduling
- Remote access with authentication
- Automated backups and monitoring
- Email/Slack alerting
- Integration with AI SEO system
