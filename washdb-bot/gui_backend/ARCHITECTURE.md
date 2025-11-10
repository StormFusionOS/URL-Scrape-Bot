# Washdb-Bot GUI Backend - Architecture Overview

## Multi-Bot Server Architecture

This server runs **multiple scraping bots**, each with **separate GUI backends**:

```
Server: rivercityscrape
├── Nathan SEO Bot (ai_seo_scraper)
│   ├── Dashboard: Port 5000
│   ├── Database: Nathan SEO Bot DB
│   └── Repository: StormFusionOS/Scrape-Bot-AI
│
└── Washdb-Bot (URL-Scrape-Bot)
    ├── Dashboard: Port 5001  ← THIS BACKEND
    ├── Database: washdb (PostgreSQL)
    └── Repository: StormFusionOS/URL-Scrape-Bot
```

## Separation Strategy

### Port Separation
- **Nathan SEO Bot**: `http://127.0.0.1:5000`
- **Washdb-Bot**: `http://127.0.0.1:5001`

### Database Separation
- **Nathan SEO Bot**: Uses its own database
- **Washdb-Bot**: Uses **washdb** PostgreSQL database ONLY

### Codebase Separation
- **Nathan SEO Bot**: `~/ai_seo_scraper/Nathan SEO Bot/`
- **Washdb-Bot**: `~/URL-Scrape-Bot/washdb-bot/`

### Process Separation
- Each bot runs as separate process
- Each GUI backend runs as separate Flask app
- No shared state or dependencies

## Washdb-Bot GUI Backend Architecture

### Directory Structure

```
gui_backend/
├── app.py                      # Main Flask application
├── config.py                   # Configuration (port 5001, washdb connection)
├── requirements.txt            # Separate dependencies
├── run.sh                      # Startup script
├── README.md                   # Documentation
├── ARCHITECTURE.md            # This file
│
├── api/                        # API Routes (Blueprints)
│   ├── __init__.py
│   ├── scraper_routes.py      # /api/scraper/* - Start/stop/status
│   ├── data_routes.py         # /api/data/* - Database queries
│   └── stats_routes.py        # /api/stats/* - Statistics
│
├── models/                     # Database Layer
│   ├── __init__.py
│   └── db_manager.py          # PostgreSQL connection (washdb only)
│
├── templates/                  # HTML Templates
│   └── index.html             # Landing page
│
└── static/                     # Static Assets
    ├── css/                   # (to be created)
    ├── js/                    # (to be created)
    └── img/                   # (to be created)
```

### Technology Stack

**Backend:**
- **Framework**: Flask 3.0
- **Database**: PostgreSQL 14+ (washdb)
- **ORM**: SQLAlchemy 2.0
- **Database Driver**: psycopg 3.0

**Frontend** (to be built):
- HTML/CSS/JavaScript
- Or React/Vue/Svelte (your choice)
- Communicates via REST API

### Application Flow

```
┌─────────────┐
│   Browser   │
└──────┬──────┘
       │ HTTP Request
       ↓
┌──────────────────────────────────────┐
│         Flask App (app.py)           │
│         Port: 5001                   │
├──────────────────────────────────────┤
│  Routes:                             │
│  - GET  /                            │
│  - GET  /health                      │
│  - GET  /api/info                    │
└──────┬───────────────────────────────┘
       │
       ├─→ scraper_bp (/api/scraper/*)
       │   ├── GET  /status
       │   ├── POST /start
       │   ├── POST /stop
       │   ├── GET  /logs
       │   └── GET  /config
       │
       ├─→ data_bp (/api/data/*)
       │   ├── GET  /companies
       │   ├── GET  /companies/<id>
       │   └── GET  /discovery-runs
       │
       └─→ stats_bp (/api/stats/*)
           ├── GET  /overview
           ├── GET  /database
           └── GET  /performance
                    ↓
        ┌───────────────────────┐
        │   DatabaseManager     │
        │  (models/db_manager)  │
        └───────────┬───────────┘
                    │ SQLAlchemy
                    ↓
        ┌───────────────────────┐
        │  PostgreSQL (washdb)  │
        │  Tables:              │
        │  - companies          │
        │  - discovery_runs     │
        │  - (other tables)     │
        └───────────────────────┘
```

### Database Connection

**Connection String:**
```
postgresql+psycopg://washbot:ScraperPass123@localhost:5432/washdb
```

**Connection Management:**
- Connection pooling (10 connections, max overflow 20)
- Pre-ping to verify connections
- Automatic session management
- Context managers for safety

**Models Used:**
```python
from db.models import Company, DiscoveryRun

# Models are imported from parent washdb-bot/db/models.py
# Shared with the scraper application
```

### API Design

**RESTful Principles:**
- GET for reading data
- POST for actions/creating data
- Proper status codes (200, 404, 500)
- JSON responses

**Pagination:**
```python
GET /api/data/companies?page=1&per_page=50

Response:
{
  "companies": [...],
  "pagination": {
    "page": 1,
    "per_page": 50,
    "total": 500,
    "pages": 10
  }
}
```

**Filtering:**
```python
GET /api/data/companies?has_website=true&has_phone=true
```

**Error Handling:**
```python
{
  "error": "Description of error",
  "timestamp": "2024-11-09T16:00:00Z"
}
```

### Configuration

**Environment Variables** (from `../env`):
```bash
# Database
DATABASE_URL=postgresql+psycopg://washbot:pass@localhost:5432/washdb

# Server
GUI_PORT=5001
GUI_HOST=127.0.0.1
DEBUG=True

# App
FLASK_ENV=development
SECRET_KEY=dev-key-change-in-production
```

**Config Validation:**
- Ensures port != 5000 (conflict with Nathan SEO Bot)
- Validates database URL format
- Creates log directory
- Checks required settings

### Security Considerations

**Current State (Development):**
- ⚠️ No authentication
- ⚠️ No authorization
- ⚠️ No HTTPS
- ✅ Localhost only (127.0.0.1)
- ✅ CORS enabled for local dev

**Production Recommendations:**
- [ ] Add authentication (JWT, session-based, or OAuth)
- [ ] Add authorization/permissions
- [ ] Use HTTPS/SSL
- [ ] Rate limiting
- [ ] Input validation
- [ ] SQL injection prevention (SQLAlchemy handles this)
- [ ] XSS prevention (template escaping)

### Logging

**Log Locations:**
- `../logs/gui_backend.log` - Application logs
- Console output (when DEBUG=True)

**Log Levels:**
- INFO: Normal operations
- WARNING: Potential issues
- ERROR: Errors with details
- DEBUG: Detailed debugging info

### Deployment Options

#### Option 1: Manual Start (Development)
```bash
cd ~/URL-Scrape-Bot/washdb-bot/gui_backend
./run.sh
```

#### Option 2: systemd Service (Production)
```bash
sudo systemctl start washdb-gui
sudo systemctl enable washdb-gui
```

#### Option 3: Docker (Future)
```bash
docker-compose up washdb-gui
```

## Development Workflow

### Adding New Features

**1. Add API Endpoint:**
```python
# api/new_feature_routes.py
from flask import Blueprint

new_bp = Blueprint('new_feature', __name__)

@new_bp.route('/example')
def example():
    return jsonify({'message': 'Hello'})
```

**2. Register Blueprint:**
```python
# app.py
from api.new_feature_routes import new_bp
app.register_blueprint(new_bp, url_prefix='/api/new')
```

**3. Add Database Method:**
```python
# models/db_manager.py
def get_new_data(self):
    with self.get_session() as session:
        return session.query(Model).all()
```

**4. Update Documentation:**
- Update README.md
- Add to API endpoint list
- Update ARCHITECTURE.md if needed

### Testing

**Health Check:**
```bash
curl http://127.0.0.1:5001/health
```

**Database Connection:**
```bash
curl http://127.0.0.1:5001/api/stats/database
```

**Get Companies:**
```bash
curl http://127.0.0.1:5001/api/data/companies?page=1&per_page=10
```

## Future Enhancements

### Phase 1: Core Functionality
- [ ] Implement scraper start/stop control
- [ ] Real-time status monitoring
- [ ] Process management
- [ ] Configuration updates via API

### Phase 2: Frontend
- [ ] Build responsive UI
- [ ] Real-time updates (WebSocket)
- [ ] Data visualization
- [ ] Export functionality

### Phase 3: Advanced Features
- [ ] Authentication/authorization
- [ ] User management
- [ ] Scheduled scraping
- [ ] Email notifications
- [ ] Advanced filtering/search
- [ ] Audit logging

### Phase 4: Production Ready
- [ ] SSL/HTTPS
- [ ] Rate limiting
- [ ] Monitoring/alerting
- [ ] Backup/restore
- [ ] Performance optimization
- [ ] Docker deployment

## Comparison with Nathan SEO Bot Dashboard

| Feature | Washdb-Bot GUI | Nathan SEO Bot |
|---------|----------------|----------------|
| **Port** | 5001 | 5000 |
| **Database** | washdb (PostgreSQL) | Nathan DB |
| **Framework** | Flask (simple) | Flask (complex) |
| **Purpose** | YP + Website scraping | SEO scraping |
| **Status** | Backend ready, frontend TBD | Fully functional |
| **Features** | Basic API structure | Full dashboard |

## Questions & Support

For questions or issues:
1. Check logs: `tail -f ../logs/gui_backend.log`
2. Verify database: `psql -U washbot -d washdb`
3. Check port: `sudo lsof -i :5001`
4. Review configuration: `cat ../.env`

## Summary

The Washdb-Bot GUI Backend is:
- ✅ **Separate** from Nathan SEO Bot
- ✅ **Isolated** port (5001) and database (washdb)
- ✅ **Structured** for easy expansion
- ✅ **Ready** for frontend development
- ✅ **Documented** for future development

You can now build the frontend incrementally with prompts while the backend API is ready to serve data!
