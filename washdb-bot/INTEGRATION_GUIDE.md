# Washbot Dashboard Guide

## Quick Start
```bash
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot
./start_dashboard.sh
```
Access at: **http://127.0.0.1:8080**

## Features Overview

### Washbot
- Dashboard: Main overview with KPIs and stats
- Discover: YP crawler controls and telemetry
- Database: Company data browser with CSV export
- Scheduler: Scheduled job configuration
- Status: System status and health checks
- Settings: Configuration management

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
