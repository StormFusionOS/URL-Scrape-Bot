#!/bin/bash
# Install logrotate configuration for washdb-bot

set -e

echo "============================================================"
echo "Washdb-Bot Logrotate Configuration Installation"
echo "============================================================"
echo ""

CONFIG_FILE="washdb-bot-logrotate"
LOGROTATE_PATH="/etc/logrotate.d/washdb-bot"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: $CONFIG_FILE not found in current directory"
    exit 1
fi

echo "This script will:"
echo "  1. Copy $CONFIG_FILE to $LOGROTATE_PATH"
echo "  2. Set proper permissions"
echo "  3. Test logrotate configuration"
echo ""
echo "Note: This requires sudo access"
echo ""

# Copy logrotate config
echo "Installing logrotate configuration..."
sudo cp $CONFIG_FILE $LOGROTATE_PATH
sudo chmod 644 $LOGROTATE_PATH
echo "✓ Logrotate config copied to $LOGROTATE_PATH"

# Test configuration
echo ""
echo "Testing logrotate configuration..."
sudo logrotate -d $LOGROTATE_PATH 2>&1 | tail -10

echo ""
echo "============================================================"
echo "Installation Complete!"
echo "============================================================"
echo ""
echo "Logrotate will:"
echo "  - Rotate logs daily"
echo "  - Keep 14 days of logs"
echo "  - Compress old logs"
echo "  - Run automatically via cron"
echo ""
echo "Test manually: sudo logrotate -f $LOGROTATE_PATH"
echo ""
