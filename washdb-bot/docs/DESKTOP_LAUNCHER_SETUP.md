# Washdb-Bot Desktop Launcher & Auto-Start Setup

## ✅ Installation Complete

The Washdb-Bot dashboard has been configured with:
1. **Desktop Launcher** - Double-click icon to open the web UI
2. **Auto-Start on Boot** - Dashboard automatically starts when system boots
3. **GUI Controls** - All services can be started from the web interface (no CLI needed)

---

## Desktop Launcher

### Location
The desktop launcher has been installed in two locations:
- **Desktop**: `~/Desktop/WashdbBot.desktop`
- **Applications Menu**: `~/.local/share/applications/WashdbBot.desktop`

### Usage
**To open the dashboard:**
- Double-click the "Washdb-Bot Dashboard" icon on your desktop, OR
- Search for "Washdb-Bot" in your applications menu

This will open your default web browser to: **http://127.0.0.1:8080**

---

## Auto-Start Service

### Service Details
- **Service Name**: `washbot-dashboard.service`
- **Status**: ✅ Enabled and Running
- **PID**: 753151
- **Port**: 8080
- **Auto-start**: Yes (starts on system boot)

### Service Management Commands

**Check service status:**
```bash
sudo systemctl status washbot-dashboard.service
```

**Stop the service:**
```bash
sudo systemctl stop washbot-dashboard.service
```

**Start the service:**
```bash
sudo systemctl start washbot-dashboard.service
```

**Restart the service:**
```bash
sudo systemctl restart washbot-dashboard.service
```

**Disable auto-start (if needed):**
```bash
sudo systemctl disable washbot-dashboard.service
```

**Re-enable auto-start:**
```bash
sudo systemctl enable washbot-dashboard.service
```

**View service logs:**
```bash
# Systemd journal
sudo journalctl -u washbot-dashboard.service -f

# Application log file
tail -f logs/dashboard.log
```

---

## Starting Services from GUI

All services can now be started directly from the web interface without using the command line:

### 1. Verification Workers (5 Workers)
**Page**: `Verification` (in WASHBOT section)
- Click "Start Worker Pool (5 Workers)" button
- Workers will verify company data using LLM
- Status and progress shown in real-time
- Stop button available to gracefully shut down workers

### 2. Google Maps Workers (5 Workers)
**Page**: `Discover` (in WASHBOT section)
- Select states from the checklist
- Click "Start Discovery" or "Start All Workers"
- 5 parallel workers scrape Google Maps for businesses
- State partitioning ensures no overlap
- Live progress monitoring

### 3. SEO Intelligence Tasks
Multiple pages in the **SEO INTELLIGENCE** section:

#### SERP Tracking
**Page**: `Run SERP`
- Monitor search engine rankings
- Track People Also Ask (PAA) questions
- Run for specific queries or all monitored sources

#### Citation Crawler
**Page**: `Run Citations`
- Scrape business directory listings
- Verify NAP (Name, Address, Phone) consistency
- Track citation completeness

#### Backlink Discovery
**Page**: `Run Backlinks`
- Find inbound links to your site
- Calculate Local Authority Score (LAS)
- Monitor referring domains

#### Competitor Analysis
**Page**: `Local Competitors`
- Crawl competitor websites
- Monitor content changes via hashing
- Track competitor strategies

---

## Database Status

The dashboard connects to PostgreSQL database:
- **Database**: washdb
- **User**: washbot
- **Status**: Check footer of web interface for connection status

**Current Data:**
- Total Companies: 53,487
- With Phone: 52,905
- Updated (30 days): 17,757
- New (7 days): 37,903

---

## System Architecture

```
System Boot
    ↓
PostgreSQL (automatically starts)
    ↓
Washbot Dashboard Service (automatically starts)
    ↓
Web UI Available at http://127.0.0.1:8080
    ↓
User starts workers from GUI as needed:
    ├── Verification Workers (5 workers)
    ├── Google Maps Workers (5 workers)
    └── SEO Intelligence Tasks (on-demand or scheduled)
```

---

## Troubleshooting

### Desktop Launcher Not Working

**Issue**: Desktop icon doesn't open browser

**Solution**:
```bash
# Make launcher executable
chmod +x ~/Desktop/WashdbBot.desktop

# Trust the launcher (GNOME)
gio set ~/Desktop/WashdbBot.desktop metadata::trusted true
```

### Service Not Starting

**Issue**: Dashboard service fails to start

**Check logs:**
```bash
sudo journalctl -u washbot-dashboard.service -n 50
```

**Common fixes:**
```bash
# Ensure .env file exists
ls -l /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/.env

# Check virtual environment
ls -l /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/venv/bin/python

# Verify PostgreSQL is running
sudo systemctl status postgresql
```

### Port 8080 Already in Use

**Issue**: Another service using port 8080

**Find process:**
```bash
lsof -i :8080
```

**Kill conflicting process:**
```bash
sudo kill -9 <PID>
sudo systemctl restart washbot-dashboard.service
```

### GUI Controls Not Starting Workers

**Issue**: Buttons don't start services

**Possible causes:**
1. Database connection issue (check footer status)
2. Permission problems with log directory
3. Virtual environment issues

**Check logs directory:**
```bash
ls -ld /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs
# Should be writable by user rivercityscrape
```

---

## Files Created/Modified

### New Files
- `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/WashdbBot.desktop` - Launcher template
- `~/Desktop/WashdbBot.desktop` - Desktop icon
- `~/.local/share/applications/WashdbBot.desktop` - Applications menu entry
- `/etc/systemd/system/washbot-dashboard.service` - Systemd service file
- `DESKTOP_LAUNCHER_SETUP.md` - This documentation

### Modified Files
None (all changes are new installations)

---

## Uninstall (if needed)

To remove the desktop launcher and auto-start:

```bash
# Remove desktop launcher
rm ~/Desktop/WashdbBot.desktop
rm ~/.local/share/applications/WashdbBot.desktop

# Disable and remove systemd service
sudo systemctl stop washbot-dashboard.service
sudo systemctl disable washbot-dashboard.service
sudo rm /etc/systemd/system/washbot-dashboard.service
sudo systemctl daemon-reload

# Dashboard can still be started manually:
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot
./venv/bin/python -m niceui.main
```

---

## Next Steps

1. **Test the Desktop Launcher**: Double-click the icon to verify it opens the browser
2. **Verify Auto-Start**: Restart your computer and check that the dashboard starts automatically
3. **Start a Service**: Open the web UI and start verification workers to test GUI controls
4. **Monitor Logs**: Watch the logs to ensure everything runs smoothly

---

## Support

For issues or questions:
- Check logs: `tail -f logs/dashboard.log`
- Service status: `sudo systemctl status washbot-dashboard.service`
- Database status: Check footer in web UI

---

**Setup Date**: 2025-11-23
**System**: Linux 6.14.0-35-generic
**User**: rivercityscrape
**Installation**: Complete ✅
