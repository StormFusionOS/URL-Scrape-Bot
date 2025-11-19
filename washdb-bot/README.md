# washdb-bot

A local web-scraping tool for collecting and storing business data from Yellow Pages and individual business websites.

## Features

- Scrape business listings from Yellow Pages
- Scrape individual business websites
- Store data in PostgreSQL database
- GUI interface for managing scrapes
- Configurable crawl delays and concurrency limits

## Project Structure

```
washdb-bot/
├── db/                 # Database models and connection management
├── scrape_yp/          # Yellow Pages scraper module
├── scrape_site/        # Individual website scraper module
├── scrape_google/      # Google Business scraper module
├── niceui/             # NiceGUI web interface (ACTIVE)
├── scheduler/          # Job scheduling system
├── runner/             # Bootstrap and runner scripts
├── tests/              # Unit and integration tests
├── gui_backend/        # ⚠️ DEPRECATED - Legacy Flask backend (kept for reference)
├── data/               # Downloaded/cached data
├── logs/               # Application logs
├── .env.example        # Environment variables template
├── requirements.txt    # Python dependencies
├── pyproject.toml      # Project configuration
└── README.md           # This file
```

### Deprecated Components

- **gui_backend/**: Legacy Flask-based backend. This has been replaced by the `niceui/` module which provides a unified web interface. The folder is kept for reference but is no longer maintained or packaged.

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

### Run Scrapers Directly

```bash
# Yellow Pages scraper
python scrape_yp/main.py

# Individual site scraper
python scrape_site/main.py
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

- `DATABASE_URL`: PostgreSQL connection string
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `YP_BASE`: Yellow Pages base URL
- `CRAWL_DELAY_SECONDS`: Delay between requests (seconds)
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
