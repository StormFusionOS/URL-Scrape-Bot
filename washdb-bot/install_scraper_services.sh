#!/bin/bash
#
# Install YP and Google scraper services as systemd units
#
# This script:
# 1. Copies service files to /etc/systemd/system/
# 2. Reloads systemd daemon
# 3. Enables services to start on boot
# 4. Optionally starts the services
#
# Usage:
#   ./install_scraper_services.sh [--start]
#
# Options:
#   --start    Start the services immediately after installation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
START_SERVICES=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --start)
            START_SERVICES=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "Installing Washbot Scraper Services"
echo "========================================"
echo ""

# Check if running as root or with sudo
if [[ $EUID -ne 0 ]]; then
    echo "This script requires root privileges."
    echo "Please run with: sudo ./install_scraper_services.sh"
    exit 1
fi

# Check if service files exist
if [[ ! -f "$SCRIPT_DIR/washbot-yp-scraper.service" ]]; then
    echo "ERROR: washbot-yp-scraper.service not found in $SCRIPT_DIR"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/washbot-google-scraper.service" ]]; then
    echo "ERROR: washbot-google-scraper.service not found in $SCRIPT_DIR"
    exit 1
fi

# Create log files if they don't exist
echo "Creating log files..."
touch "$SCRIPT_DIR/logs/yp_service.log"
touch "$SCRIPT_DIR/logs/yp_service_error.log"
touch "$SCRIPT_DIR/logs/google_service.log"
touch "$SCRIPT_DIR/logs/google_service_error.log"
chown rivercityscrape:rivercityscrape "$SCRIPT_DIR/logs/"*_service*.log

# Copy service files
echo "Copying service files to /etc/systemd/system/..."
cp "$SCRIPT_DIR/washbot-yp-scraper.service" /etc/systemd/system/
cp "$SCRIPT_DIR/washbot-google-scraper.service" /etc/systemd/system/

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable services (start on boot)
echo "Enabling services to start on boot..."
systemctl enable washbot-yp-scraper.service
systemctl enable washbot-google-scraper.service

echo ""
echo "========================================"
echo "Installation Complete!"
echo "========================================"
echo ""

if [[ "$START_SERVICES" == true ]]; then
    echo "Starting services..."
    systemctl start washbot-yp-scraper.service
    systemctl start washbot-google-scraper.service
    echo ""
    echo "Services started."
else
    echo "Services are installed but NOT started."
    echo ""
    echo "To start services manually:"
    echo "  sudo systemctl start washbot-yp-scraper"
    echo "  sudo systemctl start washbot-google-scraper"
fi

echo ""
echo "Useful commands:"
echo "========================================"
echo ""
echo "Check status:"
echo "  sudo systemctl status washbot-yp-scraper"
echo "  sudo systemctl status washbot-google-scraper"
echo ""
echo "View logs (live):"
echo "  journalctl -u washbot-yp-scraper -f"
echo "  journalctl -u washbot-google-scraper -f"
echo ""
echo "View log files:"
echo "  tail -f $SCRIPT_DIR/logs/yp_service.log"
echo "  tail -f $SCRIPT_DIR/logs/google_service.log"
echo ""
echo "Stop services:"
echo "  sudo systemctl stop washbot-yp-scraper"
echo "  sudo systemctl stop washbot-google-scraper"
echo ""
echo "Restart services:"
echo "  sudo systemctl restart washbot-yp-scraper"
echo "  sudo systemctl restart washbot-google-scraper"
echo ""
echo "Disable services (won't start on boot):"
echo "  sudo systemctl disable washbot-yp-scraper"
echo "  sudo systemctl disable washbot-google-scraper"
echo ""
echo "========================================"
