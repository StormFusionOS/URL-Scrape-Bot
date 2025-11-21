# ⚠️ DEPRECATED: Washdb-Bot GUI Backend

> **This module is deprecated and no longer maintained.**
>
> The Flask-based backend has been replaced by the **NiceGUI** web interface located in `niceui/`.
>
> This folder is kept for reference only and is not included in the project packaging.
>
> **Use `python -m niceui.main` to start the active web interface instead.**

---

## Original Documentation (for reference)

Backend API server for controlling and monitoring the washdb-bot scraper.

## Architecture

```
gui_backend/
├── app.py                  # Main Flask application
├── config.py               # Configuration management
├── requirements.txt        # Python dependencies
├── api/                    # API route blueprints
│   ├── scraper_routes.py   # Scraper control endpoints
│   ├── data_routes.py      # Data access endpoints
│   └── stats_routes.py     # Statistics endpoints
├── models/                 # Database models
│   └── db_manager.py       # Database connection manager
├── templates/              # HTML templates
│   └── index.html          # Landing page
└── static/                 # Static assets (CSS, JS)
```

## Setup

### 1. Install Dependencies

```bash
cd ~/URL-Scrape-Bot/washdb-bot/gui_backend
pip install -r requirements.txt
```

Or use the parent venv:

```bash
cd ~/URL-Scrape-Bot/washdb-bot
source venv/bin/activate
pip install -r gui_backend/requirements.txt
```

### 2. Environment Configuration

The backend uses the parent `.env` file:

```bash
# ~/URL-Scrape-Bot/washdb-bot/.env
DATABASE_URL=postgresql+psycopg://washbot:ScraperPass123@localhost:5432/washdb
GUI_PORT=5001
GUI_HOST=127.0.0.1
DEBUG=True
```

### 3. Start the Backend

```bash
cd ~/URL-Scrape-Bot/washdb-bot/gui_backend
python app.py
```

The backend will be available at: `http://127.0.0.1:5001`

## API Endpoints

### General

- **GET** `/health` - Health check
- **GET** `/api/info` - API information

### Scraper Control (`/api/scraper`)

- **GET** `/api/scraper/status` - Get scraper status
- **POST** `/api/scraper/start` - Start scraper
- **POST** `/api/scraper/stop` - Stop scraper
- **GET** `/api/scraper/logs?lines=100` - Get recent logs
- **GET** `/api/scraper/config` - Get configuration
- **POST** `/api/scraper/config` - Update configuration

### Data Access (`/api/data`)

- **GET** `/api/data/companies?page=1&per_page=50` - List companies
- **GET** `/api/data/companies/<id>` - Get single company
- **GET** `/api/data/discovery-runs?limit=20` - List discovery runs
- **POST** `/api/data/export` - Export data (CSV/JSON)

### Statistics (`/api/stats`)

- **GET** `/api/stats/overview` - Overview statistics
- **GET** `/api/stats/recent-activity` - Recent scraping activity
- **GET** `/api/stats/performance` - Performance metrics
- **GET** `/api/stats/database` - Database statistics

## Example API Calls

### Check Health

```bash
curl http://127.0.0.1:5001/health
```

### Get Companies

```bash
curl "http://127.0.0.1:5001/api/data/companies?page=1&per_page=10"
```

### Get Statistics

```bash
curl http://127.0.0.1:5001/api/stats/overview
```

### Start Scraper

```bash
curl -X POST http://127.0.0.1:5001/api/scraper/start \
  -H "Content-Type: application/json" \
  -d '{"mode": "yp"}'
```

## Database Access

The backend connects **ONLY** to the washdb PostgreSQL database:

```python
from models.db_manager import DatabaseManager

db_manager = DatabaseManager("postgresql+psycopg://washbot:pass@localhost:5432/washdb")

# Get companies
companies = db_manager.get_companies(limit=50)

# Get stats
stats = db_manager.get_stats()
```

## Development Status

### ✅ Implemented

- Flask app structure
- Database connection to washdb
- API route structure
- Basic endpoints (placeholders)
- Configuration management
- Logging setup
- Health checks

### 🚧 To Be Implemented (as needed)

- Actual scraper start/stop logic
- Real-time scraper status monitoring
- Process management (subprocess control)
- WebSocket for live updates
- Authentication/authorization
- Frontend UI (separate build)
- Data export functionality
- Advanced filtering
- Search functionality

## Running in Production

### Using systemd (recommended)

Create `/etc/systemd/system/washdb-gui.service`:

```ini
[Unit]
Description=Washdb-Bot GUI Backend
After=network.target postgresql.service

[Service]
Type=simple
User=rivercityscrape
WorkingDirectory=/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/gui_backend
Environment="PATH=/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/venv/bin"
ExecStart=/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/venv/bin/python app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable washdb-gui
sudo systemctl start washdb-gui
sudo systemctl status washdb-gui
```

### Using Gunicorn

```bash
gunicorn -w 4 -b 127.0.0.1:5001 app:app
```

## Security Notes

- Currently configured for **localhost only** (127.0.0.1)
- No authentication implemented yet
- SSL/TLS not configured
- **Do not expose to internet without proper security**

## Logging

Logs are written to:
- `../logs/gui_backend.log` - Application logs
- Console output (when DEBUG=True)

## Troubleshooting

### Port Already in Use

```bash
# Check what's using port 5001
sudo lsof -i :5001

# Change port in .env
GUI_PORT=5002
```

### Database Connection Error

```bash
# Test database connection
psql -U washbot -d washdb -h localhost

# Check DATABASE_URL in .env
DATABASE_URL=postgresql+psycopg://washbot:password@localhost:5432/washdb
```

### Import Errors

```bash
# Ensure parent db module is accessible
cd ~/URL-Scrape-Bot/washdb-bot
source venv/bin/activate
pip install -e .
```

## Next Steps

1. **Build Frontend** - Create React/Vue/Vanilla JS frontend
2. **Implement Scraper Control** - Add actual start/stop logic
3. **Add Authentication** - Secure the API
4. **Real-time Updates** - WebSocket for live status
5. **Advanced Features** - Search, filtering, export

## Contributing

When adding new features:
1. Add routes to appropriate blueprint in `api/`
2. Add database methods to `models/db_manager.py`
3. Update this README with new endpoints
