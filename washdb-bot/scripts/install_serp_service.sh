#!/bin/bash
#
# Install and enable the continuous SERP scraper systemd service
#
# This script:
# 1. Installs the systemd service file
# 2. Enables the service to start on boot
# 3. Starts the service immediately
#

set -e

echo "================================"
echo "WashBot SERP Scraper Service Installer"
echo "================================"
echo ""

# Check if running as user (not root)
if [ "$EUID" -eq 0 ]; then
    echo "ERROR: Do not run this script as root. Run as rivercityscrape user."
    echo "The script will use sudo when needed."
    exit 1
fi

# Check if service file exists
if [ ! -f /tmp/washbot-serp-scraper.service ]; then
    echo "ERROR: Service file not found at /tmp/washbot-serp-scraper.service"
    exit 1
fi

# Check if script exists
if [ ! -f /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/scripts/continuous_serp_scraper.py ]; then
    echo "ERROR: Scraper script not found"
    exit 1
fi

# Make script executable
echo "Making script executable..."
chmod +x /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/scripts/continuous_serp_scraper.py

# Copy service file to systemd directory
echo "Installing service file..."
sudo cp /tmp/washbot-serp-scraper.service /etc/systemd/system/

# Reload systemd
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable service
echo "Enabling service (will start on boot)..."
sudo systemctl enable washbot-serp-scraper.service

# Ask if user wants to start now
echo ""
read -p "Start the service now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Starting service..."
    sudo systemctl start washbot-serp-scraper.service

    echo ""
    echo "Waiting for service to start..."
    sleep 3

    # Check status
    echo ""
    echo "Service status:"
    sudo systemctl status washbot-serp-scraper.service --no-pager || true

    echo ""
    echo "Recent logs:"
    sudo journalctl -u washbot-serp-scraper.service -n 20 --no-pager || true
fi

echo ""
echo "================================"
echo "Installation Complete!"
echo "================================"
echo ""
echo "Useful commands:"
echo "  Start:   sudo systemctl start washbot-serp-scraper"
echo "  Stop:    sudo systemctl stop washbot-serp-scraper"
echo "  Restart: sudo systemctl restart washbot-serp-scraper"
echo "  Status:  sudo systemctl status washbot-serp-scraper"
echo "  Logs:    sudo journalctl -u washbot-serp-scraper -f"
echo "  Disable: sudo systemctl disable washbot-serp-scraper"
echo ""
echo "Log file location:"
echo "  /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/serp_scraper_service.log"
echo ""
