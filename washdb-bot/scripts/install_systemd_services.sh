#!/bin/bash
# Install WashDB-Bot systemd services
#
# This script:
# 1. Creates /etc/washdb-bot directory for config
# 2. Copies environment config template
# 3. Copies service files to /etc/systemd/system
# 4. Reloads systemd daemon
#
# Usage:
#   sudo ./scripts/install_systemd_services.sh
#
# After running:
#   1. Edit /etc/washdb-bot/washdb-bot.env with your paths
#   2. Enable services: sudo systemctl enable washdb-bot
#   3. Start services: sudo systemctl start washdb-bot

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "WashDB-Bot Systemd Service Installer"
echo "=========================================="
echo "Project directory: $PROJECT_DIR"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Create config directory
echo ""
echo "Creating /etc/washdb-bot..."
mkdir -p /etc/washdb-bot

# Copy environment config
echo "Copying environment config..."
cp "$PROJECT_DIR/config/washdb-bot.env" /etc/washdb-bot/
chmod 600 /etc/washdb-bot/washdb-bot.env

# Copy service files
echo "Copying service files to /etc/systemd/system/..."

# Main UI service
if [ -f "$PROJECT_DIR/washdb-bot.service" ]; then
    cp "$PROJECT_DIR/washdb-bot.service" /etc/systemd/system/
    echo "  - washdb-bot.service"
fi

# YP scraper service
if [ -f "$PROJECT_DIR/washbot-yp-scraper.service" ]; then
    cp "$PROJECT_DIR/washbot-yp-scraper.service" /etc/systemd/system/
    echo "  - washbot-yp-scraper.service"
fi

# Google scraper service
if [ -f "$PROJECT_DIR/washbot-google-scraper.service" ]; then
    cp "$PROJECT_DIR/washbot-google-scraper.service" /etc/systemd/system/
    echo "  - washbot-google-scraper.service"
fi

# Worker pool services
if [ -f "$PROJECT_DIR/systemd/yp-state-workers.service" ]; then
    cp "$PROJECT_DIR/systemd/yp-state-workers.service" /etc/systemd/system/
    echo "  - yp-state-workers.service"
fi

if [ -f "$PROJECT_DIR/systemd/google-state-workers.service" ]; then
    cp "$PROJECT_DIR/systemd/google-state-workers.service" /etc/systemd/system/
    echo "  - google-state-workers.service"
fi

# Reload systemd
echo ""
echo "Reloading systemd daemon..."
systemctl daemon-reload

echo ""
echo "=========================================="
echo "Installation complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit /etc/washdb-bot/washdb-bot.env with your paths"
echo "2. Enable services you want to run:"
echo "   sudo systemctl enable washdb-bot"
echo "   sudo systemctl enable yp-state-workers"
echo "   sudo systemctl enable google-state-workers"
echo "3. Start services:"
echo "   sudo systemctl start washdb-bot"
echo ""
echo "Check status:"
echo "   sudo systemctl status washdb-bot"
echo ""
