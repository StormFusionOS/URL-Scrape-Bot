# Scripts Documentation

This document describes all operational scripts in the washdb-bot project.

## Service Management Scripts

### install_services.sh

**Location:** `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/scripts/install_services.sh`

**Purpose:** Initial installation of systemd services for worker pools

**What it does:**
1. Stops old services (yp-5workers.service, google-5workers.service)
2. Stops manually running workers
3. Disables old services
4. Copies new service files to /etc/systemd/system/
5. Sets correct permissions (644)
6. Reloads systemd daemon
7. Enables new services for auto-start
8. Starts new services
9. Displays service status

**Usage:**
```bash
./scripts/install_services.sh
```

**When to use:**
- First-time setup of worker services
- Upgrading from old worker pool services
- After major service file changes

**Service files installed:**
- `yp-state-workers.service` - YP 5-worker pool with browser pooling
- `google-state-workers.service` - Google 5-worker pool with browser pooling

---

### reload_services.sh

**Location:** `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/scripts/reload_services.sh`

**Purpose:** Reload services with updated configuration or logging settings

**What it does:**
1. Copies updated service files from `systemd/` to `/etc/systemd/system/`
2. Reloads systemd daemon
3. Restarts both worker services

**Usage:**
```bash
./scripts/reload_services.sh
```

**When to use:**
- After modifying service files in `systemd/` directory
- After updating logging configuration
- After changing environment variables in service files
- To apply configuration changes without full reinstall

**Note:** This script does NOT stop or disable services, it just restarts them with new config.

---

## Database Management Scripts

### manual_db_setup.sh

**Location:** `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/scripts/manual_db_setup.sh`

**Purpose:** Manual PostgreSQL database setup

**What it does:**
1. Creates PostgreSQL database `washdb`
2. Creates user `washbot` with password
3. Grants privileges to washbot user
4. Initializes database schema

**Usage:**
```bash
./scripts/manual_db_setup.sh
```

**When to use:**
- First-time database setup
- Database recreation after corruption
- Setting up on new server

**Prerequisites:**
- PostgreSQL 14+ installed
- Access to postgres superuser

---

### setup_database.sh

**Location:** `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/setup_database.sh`

**Purpose:** Automated database setup and migration

**Usage:**
```bash
./scripts/setup_database.sh
```

---

## Dashboard Management Scripts

### start_dashboard.sh

**Location:** `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/start_dashboard.sh`

**Purpose:** Start the NiceGUI web dashboard

**What it does:**
1. Activates virtual environment
2. Starts NiceGUI dashboard on port 8080
3. Makes it accessible at http://localhost:8080

**Usage:**
```bash
./scripts/start_dashboard.sh
```

**When to use:**
- Manual dashboard startup
- Development and testing
- Accessing GUI for monitoring

**Alternative:** Can also run directly with `python niceui/main.py`

---

## Log Management Scripts

### install_logrotate.sh

**Location:** `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/install_logrotate.sh`

**Purpose:** Install logrotate configuration for automatic log rotation

**What it does:**
1. Installs logrotate configuration
2. Sets up automatic rotation for worker logs
3. Prevents log files from growing too large

**Usage:**
```bash
sudo ./scripts/install_logrotate.sh
```

**When to use:**
- Initial system setup
- Preventing disk space issues from large log files

---

## Service Monitoring

### Checking Service Status

**YP Workers:**
```bash
sudo systemctl status yp-state-workers.service
```

**Google Workers:**
```bash
sudo systemctl status google-state-workers.service
```

**View Real-time Logs:**
```bash
# YP workers
sudo journalctl -u yp-state-workers.service -f

# Google workers
sudo journalctl -u google-state-workers.service -f

# Or view log files directly
tail -f logs/yp_workers.log
tail -f logs/google_workers.log
```

---

## Service Management Commands

### Starting Services
```bash
sudo systemctl start yp-state-workers.service
sudo systemctl start google-state-workers.service
```

### Stopping Services
```bash
sudo systemctl stop yp-state-workers.service
sudo systemctl stop google-state-workers.service
```

### Restarting Services
```bash
sudo systemctl restart yp-state-workers.service
sudo systemctl restart google-state-workers.service

# Or use reload script
./scripts/reload_services.sh
```

### Enabling Auto-start on Boot
```bash
sudo systemctl enable yp-state-workers.service
sudo systemctl enable google-state-workers.service
```

### Disabling Auto-start
```bash
sudo systemctl disable yp-state-workers.service
sudo systemctl disable google-state-workers.service
```

---

## Troubleshooting Scripts

### Check Running Workers
```bash
ps aux | grep "state_worker_pool"
```

### Kill Stuck Workers
```bash
pkill -f "scrape_yp.state_worker_pool"
pkill -f "scrape_google.state_worker_pool"
```

### Check System Resources
```bash
# Memory usage
free -h

# CPU and process info
top

# Disk usage
df -h
```

---

## Script Execution Order (Initial Setup)

For a fresh system setup, run scripts in this order:

1. **Database Setup**
   ```bash
   ./scripts/manual_db_setup.sh
   ```

2. **Install Services**
   ```bash
   ./scripts/install_services.sh
   ```

3. **Install Logrotate** (optional but recommended)
   ```bash
   sudo ./scripts/install_logrotate.sh
   ```

4. **Start Dashboard** (optional, for monitoring)
   ```bash
   ./scripts/start_dashboard.sh
   ```

---

## Configuration Files

All service scripts reference these systemd service files:

### systemd/yp-state-workers.service
- **Description:** YP State Worker Pool (5 workers, browser pooling)
- **Working Directory:** `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot`
- **Command:** `python -m scrape_yp.state_worker_pool`
- **Log Output:** `logs/yp_workers.log`
- **Restart Policy:** Always restart with 10-second delay

### systemd/google-state-workers.service
- **Description:** Google Maps State Worker Pool (5 workers, browser pooling)
- **Working Directory:** `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot`
- **Command:** `python -m scrape_google.state_worker_pool`
- **Log Output:** `logs/google_workers.log`
- **Restart Policy:** Always restart with 10-second delay

---

## Common Issues

### Service Won't Start
```bash
# Check service status
sudo systemctl status yp-state-workers.service

# Check logs
sudo journalctl -u yp-state-workers.service -n 50

# Verify service file syntax
sudo systemctl daemon-reload
```

### Workers Not Processing
```bash
# Check if workers are running
ps aux | grep "state_worker_pool"

# Restart services
./reload_services.sh

# Check database connectivity
psql -U washbot -d washdb -c "SELECT 1;"
```

### High Memory Usage
```bash
# Check memory
free -h

# Check process memory
ps aux --sort=-%mem | head -20

# Restart services to free memory
./scripts/reload_services.sh
```

### Log Files Growing Too Large
```bash
# Install logrotate
sudo ./scripts/install_logrotate.sh

# Manually rotate logs
sudo logrotate -f /etc/logrotate.d/washdb-bot

# Check log sizes
du -sh logs/*.log
```

---

## Best Practices

1. **Always use scripts/reload_services.sh** for configuration changes instead of manual systemctl commands
2. **Monitor logs** regularly using `tail -f logs/yp_workers.log`
3. **Check service status** after any script execution
4. **Use the dashboard** at http://localhost:8080 for easy monitoring
5. **Keep backups** before making major changes
6. **Test configuration** changes on development system first

---

## See Also

- [OPERATIONS.md](OPERATIONS.md) - Operational procedures
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [LOGS.md](LOGS.md) - Log file locations and debugging
- [QUICKSTART-dev.md](QUICKSTART-dev.md) - Development setup guide
