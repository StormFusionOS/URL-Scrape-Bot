#!/bin/bash
# Install washdb-bot systemd service

set -e

echo "============================================================"
echo "Washdb-Bot Systemd Service Installation"
echo "============================================================"
echo ""

SERVICE_FILE="washdb-bot.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_FILE"

if [ ! -f "$SERVICE_FILE" ]; then
    echo "ERROR: $SERVICE_FILE not found in current directory"
    exit 1
fi

echo "This script will:"
echo "  1. Copy $SERVICE_FILE to $SERVICE_PATH"
echo "  2. Reload systemd daemon"
echo "  3. Enable washdb-bot service to start on boot"
echo "  4. Start washdb-bot service"
echo ""
echo "Note: This requires sudo access"
echo ""

# Stop any existing service
if systemctl is-active --quiet washdb-bot.service; then
    echo "Stopping existing washdb-bot service..."
    sudo systemctl stop washdb-bot.service
fi

# Copy service file
echo "Installing service file..."
sudo cp $SERVICE_FILE $SERVICE_PATH
echo "✓ Service file copied to $SERVICE_PATH"

# Reload systemd
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload
echo "✓ Systemd daemon reloaded"

# Enable service
echo "Enabling washdb-bot service..."
sudo systemctl enable washdb-bot.service
echo "✓ Service enabled (will start on boot)"

# Start service
echo "Starting washdb-bot service..."
sudo systemctl start washdb-bot.service
echo "✓ Service started"

# Wait a moment for service to start
sleep 2

# Show status
echo ""
echo "============================================================"
echo "Service Status:"
echo "============================================================"
sudo systemctl status washdb-bot.service --no-pager -l

echo ""
echo "============================================================"
echo "Installation Complete!"
echo "============================================================"
echo ""
echo "Useful commands:"
echo "  Check status:   sudo systemctl status washdb-bot"
echo "  Stop service:   sudo systemctl stop washdb-bot"
echo "  Start service:  sudo systemctl start washdb-bot"
echo "  Restart:        sudo systemctl restart washdb-bot"
echo "  View logs:      sudo journalctl -u washdb-bot -f"
echo "  Disable:        sudo systemctl disable washdb-bot"
echo ""
echo "The GUI is now accessible at: http://127.0.0.1:8080"
echo ""
