# Washbot Integrated Dashboard Guide

## Quick Start
```bash
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot
./start_dashboard.sh
```
Access at: **http://127.0.0.1:8080**

## Features Overview

### Washbot (Original)
- Dashboard, Discover, Database, Scheduler, Status, Settings

### SEO Intelligence (New)
- SEO Database, Run Scraper, Scraped Data, DB Sync, Competitors

## Auto-Start on Boot
```bash
sudo cp washbot-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable washbot-dashboard
sudo systemctl start washbot-dashboard
```

## Troubleshooting
- **Check logs**: `tail -f logs/dashboard.log`
- **Port in use**: `lsof -i :8080`
- **Stop dashboard**: `pkill -f "python -m niceui.main"`

## Independent Systems
- **Port 8080**: Integrated Washbot (Washbot + SEO Intelligence)  
- **Port 8082**: SEO Intelligence (independent, unchanged)
