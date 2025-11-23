#!/bin/bash
# ============================================================================
# SEO Intelligence Cron Schedule Configuration
# ============================================================================
#
# This file documents the recommended cron schedule for SEO intelligence tasks.
# Add these entries to your crontab with: crontab -e
#
# Frequencies:
# - Daily tasks: Run at 2 AM daily
# - Weekly tasks: Run at 3 AM every Sunday
# - Monthly tasks: Run at 4 AM on the 1st of each month
# - Full cycle: Run at 5 AM on the 1st of each month
#
# Prerequisites:
# 1. Set correct PROJECT_DIR path below
# 2. Ensure virtual environment is activated
# 3. Ensure DATABASE_URL is set in .env
# 4. Test with --dry-run first
#
# ============================================================================

PROJECT_DIR="/home/rivercityscrape/URL-Scrape-Bot/washdb-bot"
PYTHON="$PROJECT_DIR/venv/bin/python"
CLI_SCRIPT="$PROJECT_DIR/seo_intelligence/cli_run_seo_cycle.py"
LOG_DIR="$PROJECT_DIR/logs/seo_cycles"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# ============================================================================
# CRON SCHEDULE
# ============================================================================

# Daily tasks (SERP tracking, Reviews) - Run at 2 AM daily
# 0 2 * * * cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --mode daily >> $LOG_DIR/daily_$(date +\%Y\%m\%d).log 2>&1

# Weekly tasks (Competitor analysis, Backlinks, Unlinked mentions) - Run at 3 AM every Sunday
# 0 3 * * 0 cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --mode weekly >> $LOG_DIR/weekly_$(date +\%Y\%m\%d).log 2>&1

# Monthly tasks (Citations, Technical audits) - Run at 4 AM on the 1st of each month
# 0 4 1 * * cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --mode monthly >> $LOG_DIR/monthly_$(date +\%Y\%m\%d).log 2>&1

# Full cycle (All tasks) - Run at 5 AM on the 1st of each month
# 0 5 1 * * cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --mode full >> $LOG_DIR/full_$(date +\%Y\%m\%d).log 2>&1

# ============================================================================
# INDIVIDUAL PHASE SCHEDULES (Alternative approach)
# ============================================================================
# Instead of grouping by frequency, you can schedule each phase individually:

# SERP tracking - Daily at 2:00 AM
# 0 2 * * * cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --phase serp_tracking >> $LOG_DIR/serp_$(date +\%Y\%m\%d).log 2>&1

# Reviews - Daily at 2:30 AM
# 30 2 * * * cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --phase reviews >> $LOG_DIR/reviews_$(date +\%Y\%m\%d).log 2>&1

# Competitor analysis - Weekly on Sunday at 3:00 AM
# 0 3 * * 0 cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --phase competitor_analysis >> $LOG_DIR/competitors_$(date +\%Y\%m\%d).log 2>&1

# Backlinks discovery - Weekly on Sunday at 4:00 AM
# 0 4 * * 0 cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --phase backlinks_discovery >> $LOG_DIR/backlinks_$(date +\%Y\%m\%d).log 2>&1

# Unlinked mentions - Weekly on Sunday at 5:00 AM
# 0 5 * * 0 cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --phase unlinked_mentions >> $LOG_DIR/mentions_$(date +\%Y\%m\%d).log 2>&1

# Citations crawling - Monthly on the 1st at 3:00 AM
# 0 3 1 * * cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --phase citations_crawling >> $LOG_DIR/citations_$(date +\%Y\%m\%d).log 2>&1

# Technical audits - Monthly on the 1st at 4:00 AM
# 0 4 1 * * cd $PROJECT_DIR && $PYTHON $CLI_SCRIPT --phase technical_audits >> $LOG_DIR/audits_$(date +\%Y\%m\%d).log 2>&1

# ============================================================================
# SYSTEMD TIMER (Alternative to cron)
# ============================================================================
# For systemd-based scheduling, create timer units in /etc/systemd/system/
#
# Example daily timer (seo-daily.timer):
# [Unit]
# Description=SEO Intelligence Daily Tasks Timer
#
# [Timer]
# OnCalendar=*-*-* 02:00:00
# Persistent=true
#
# [Install]
# WantedBy=timers.target
#
# Example service (seo-daily.service):
# [Unit]
# Description=SEO Intelligence Daily Tasks
#
# [Service]
# Type=oneshot
# User=rivercityscrape
# WorkingDirectory=/home/rivercityscrape/URL-Scrape-Bot/washdb-bot
# ExecStart=/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/venv/bin/python \
#           /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/seo_intelligence/cli_run_seo_cycle.py \
#           --mode daily
#
# [Install]
# WantedBy=multi-user.target
#
# Enable with: systemctl enable seo-daily.timer && systemctl start seo-daily.timer

# ============================================================================
# CLEANUP OLD LOGS (Optional)
# ============================================================================
# Remove log files older than 30 days at 1 AM daily
# 0 1 * * * find $LOG_DIR -name "*.log" -type f -mtime +30 -delete

# ============================================================================
# MONITORING AND ALERTS (Optional)
# ============================================================================
# Check if SEO cycle failed and send alert
# 15 2,3,4,5 * * * if grep -q "Failed: [1-9]" $LOG_DIR/daily_$(date +\%Y\%m\%d).log 2>/dev/null; then echo "SEO cycle failed - check logs" | mail -s "SEO Alert" admin@example.com; fi
