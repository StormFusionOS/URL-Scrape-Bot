# washdb-bot

A local web-scraping tool for collecting and storing business data from multiple sources including Yellow Pages, Bing Search, and individual business websites.

## Features

- Scrape business listings from Yellow Pages
- Discover businesses via Bing web search (HTML scraping and API modes)
- Scrape individual business websites
- Store data in PostgreSQL database
- GUI interface for managing scrapes and discoveries
- Configurable crawl delays and concurrency limits
- Multi-source discovery with de-duplication

## Project Structure

```
washdb-bot/
├── db/                 # Database models and connection management
├── scrape_yp/          # Yellow Pages scraper module
├── scrape_bing/        # Bing Search discovery module (HTML + API)
├── scrape_site/        # Individual website scraper module
├── niceui/             # NiceGUI web-based dashboard interface
├── runner/             # Bootstrap and runner scripts
├── tests/              # Unit and integration tests
├── data/               # Downloaded/cached data
├── logs/               # Application logs
├── .env.example        # Environment variables template
├── requirements.txt    # Python dependencies
├── pyproject.toml      # Project configuration
└── README.md           # This file
```

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

### Run the GUI

```bash
# To be implemented
python gui/main.py
```

### Run Discovery and Scraping

Use the CLI runner for discovery and scraping operations:

```bash
# Discover businesses from Yellow Pages only
python runner/main.py --discover-only --source yp --states TX,IL --pages-per-pair 3

# Discover businesses from Bing Search only
python runner/main.py --discover-only --source bing --states TX,IL --pages-per-pair 5

# Discover from both Yellow Pages and Bing
python runner/main.py --discover-only --source both --states TX,CA --pages-per-pair 3

# Run full workflow: discover + scrape websites
python runner/main.py --auto --source yp --states TX --update-limit 50

# Scrape existing businesses only
python runner/main.py --scrape-only --update-limit 100 --stale-days 30

# Update businesses missing email addresses
python runner/main.py --scrape-only --only-missing-email --update-limit 200
```

## Development

### Run Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black .
ruff check .
```

## Configuration

All configuration is done through environment variables in the `.env` file:

### Database & Logging
- `DATABASE_URL`: PostgreSQL connection string
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

### Yellow Pages Configuration
- `YP_BASE`: Yellow Pages base URL

### Bing Discovery Configuration
- `BING_API_KEY`: Optional Bing Web Search API v7 key (leave blank for HTML scraping mode)
- `BING_MODE`: Mode selection - `api` (requires key), `html` (scraping), or `auto` (uses API if key present, default: `auto`)
- `BING_CRAWL_DELAY_SECONDS`: Rate limiting delay between Bing requests in seconds (default: `3.0`)
- `BING_PAGES_PER_PAIR`: Default number of pages to crawl per category/state pair (default: `5`)

### General Scraping Settings
- `CRAWL_DELAY_SECONDS`: Delay between general requests (seconds)
- `MAX_CONCURRENT_SITE_SCRAPES`: Maximum concurrent scraping threads

## Database Schema

Database tables will be automatically created on first run using SQLAlchemy ORM.

## Logging

Logs are stored in the `logs/` directory with rotating file handlers.

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Support

For issues and questions, please open a GitHub issue.
