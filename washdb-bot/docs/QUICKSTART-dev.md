# Quick Start Guide for Developers

Get the URL Scrape Bot up and running on your local machine in less than 10 minutes.

## Prerequisites

Before you begin, ensure you have:

- **Python 3.11+** installed
- **PostgreSQL 14+** installed and running
- **Git** installed
- Basic command line knowledge

## Step 1: Clone the Repository

```bash
git clone <repository-url>
cd URL-Scrape-Bot/washdb-bot
```

## Step 2: Set Up Python Environment

### Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

You should see `(venv)` in your terminal prompt.

### Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- SQLAlchemy (database ORM)
- NiceGUI (web dashboard)
- Playwright (browser automation)
- BeautifulSoup4 (HTML parsing)
- And all other dependencies

### Install Playwright Browsers

```bash
playwright install
```

This downloads the Chromium browser needed for scraping.

## Step 3: Set Up PostgreSQL Database

### Option A: Quick Setup (Default Credentials)

```bash
# Connect to PostgreSQL as superuser
psql -U postgres

# Run these SQL commands:
CREATE DATABASE washbot_db;
CREATE USER washbot WITH ENCRYPTED PASSWORD 'Washdb123';
GRANT ALL PRIVILEGES ON DATABASE washbot_db TO washbot;
\q
```

### Option B: Custom Credentials

```sql
-- Use your own database name and password
CREATE DATABASE your_db_name;
CREATE USER your_user WITH ENCRYPTED PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE your_db_name TO your_user;
\q
```

## Step 4: Configure Environment

### Copy Environment Template

```bash
cp .env.example .env
```

### Edit .env File

Open `.env` in your text editor and update these key settings:

```bash
# Database (update if you used custom credentials)
DATABASE_URL=postgresql+psycopg://washbot:Washdb123@127.0.0.1:5432/washbot_db

# Dashboard port
NICEGUI_PORT=8080

# Development settings (conservative for local testing)
WORKER_COUNT=2
CRAWL_DELAY_SECONDS=15
MAX_CONCURRENT_SITE_SCRAPES=2
```

**For development, you can also use `.env.dev`** (once created) for development-specific settings.

## Step 5: Initialize the Database

Run the database initialization script:

```bash
python db/init_db.py
```

You should see output indicating that tables are being created:
```
Creating tables...
Tables created successfully!
```

### Load City Registry (Optional but Recommended)

The scraper uses a registry of ~31,000 US cities. Load it with:

```bash
python db/populate_city_registry.py
```

This takes a minute or two. You'll see progress as cities are loaded.

## Step 6: Verify Installation

Run the bootstrap script to check everything is configured correctly:

```bash
python runner/bootstrap.py
```

Expected output:
```
Bootstrap OK
Database connection: OK
Logging setup: OK
```

## Step 7: Start the Dashboard

Launch the NiceGUI web dashboard:

```bash
python niceui/main.py
# Or: python -m niceui
```

You should see:
```
NiceGUI ready to go on http://localhost:8080
```

Open your browser and navigate to: **http://localhost:8080**

## Step 8: Run Your First Scrape

### Via Dashboard (Recommended)

1. Navigate to the **Discover** tab
2. Select **Yellow Pages** as the source
3. Enter:
   - State: `RI` (Rhode Island is small, good for testing)
   - Category: `pressure washing`
   - Max Targets: `10` (keep it small for first test)
4. Click **Start Discovery**
5. Go to the **Logs** tab to watch progress in real-time
6. Check the **Dashboard** tab to see stats

### Via CLI (Alternative)

**Optimized Multi-Worker (Recommended)**:
```bash
# Run 5-worker pool with persistent browsers (2-3x faster)
python -m scrape_yp.state_worker_pool
```

**Legacy Single Worker**:
```bash
# Deprecated - use state_worker_pool for better performance
python cli_crawl_yp.py --states RI --categories "pressure washing" --max-targets 10
```

Watch the logs in real-time:
```bash
# New workers
tail -f logs/state_worker_*.log

# Or main pool log
tail -f logs/yp_workers.log
```

## Step 9: View Results

### In the Dashboard

1. Go to the **Database** tab
2. Browse the `companies` table
3. Filter by `data_source = 'yp'`
4. You should see the businesses that were discovered

### Via PostgreSQL

```bash
psql -U washbot -d washbot_db

SELECT name, phone, city, state, website
FROM companies
WHERE data_source = 'yp'
LIMIT 10;
```

## Common Issues & Solutions

### Database Connection Error

**Error**: `psycopg.OperationalError: connection refused`

**Solution**:
- Make sure PostgreSQL is running: `sudo systemctl status postgresql`
- Check your `DATABASE_URL` in `.env` matches your database credentials
- Verify you can connect manually: `psql -U washbot -d washbot_db`

### Playwright Browser Not Found

**Error**: `playwright._impl._errors.Error: Executable doesn't exist`

**Solution**:
```bash
playwright install
```

### Import Errors

**Error**: `ModuleNotFoundError: No module named 'xxx'`

**Solution**:
- Make sure virtual environment is activated: `source venv/bin/activate`
- Reinstall dependencies: `pip install -r requirements.txt`

### Port Already in Use

**Error**: `Address already in use: 8080`

**Solution**:
- Change `NICEGUI_PORT` in `.env` to a different port (e.g., 8081)
- Or kill the process using port 8080: `lsof -ti:8080 | xargs kill -9`

## What to Explore Next

Now that you have the system running, try:

1. **Read the Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md) - Understand how the system works
2. **Explore Logs**: [LOGS.md](LOGS.md) - Learn where to find logs when debugging
3. **Run Tests**: `pytest tests/` - Execute the test suite
4. **Try Other Scrapers**: Google Maps, Bing Local Search
5. **Website Enrichment**: Scrape individual websites for more details

## Development Workflow

### Daily Development

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Pull latest changes
git pull origin main

# 3. Install any new dependencies
pip install -r requirements.txt

# 4. Run the dashboard
python niceui/main.py
```

### Making Changes

```bash
# 1. Create a feature branch
git checkout -b feature/my-feature

# 2. Make your changes
# ... edit files ...

# 3. Run tests
pytest tests/

# 4. Format code
black .

# 5. Lint code
ruff check .

# 6. Commit and push
git add .
git commit -m "Add my feature"
git push origin feature/my-feature
```

## Dev Scripts (Coming Soon)

Once the dev scripts are implemented, you'll be able to:

```bash
# One-command setup
./scripts/dev/setup.sh

# Run dashboard with dev config
./scripts/dev/run-gui.sh

# Run a test scrape
./scripts/dev/run-scrape.sh --target yp --city "Peoria, IL"

# Run all checks before committing
./scripts/dev/check.sh
```

## Getting Help

- **Documentation**: See [index.md](index.md) for all documentation
- **Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md) for system design
- **Logs**: [LOGS.md](LOGS.md) for debugging
- **Issues**: Open a GitHub issue with detailed information

## Next Steps

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Deep dive into system design
- **[docs/index.md](index.md)** - Browse all documentation
- **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Contributing guidelines
- **[docs/scrapers/yp/](scrapers/yp/)** - Yellow Pages scraper details
- **[docs/gui/](gui/)** - NiceGUI dashboard documentation

---

**Congratulations!** You now have a fully functional local development environment for the URL Scrape Bot. Happy coding!
