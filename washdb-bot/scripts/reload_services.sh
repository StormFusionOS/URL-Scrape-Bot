#!/bin/bash
# Reload services with updated logging configuration

set -e

echo "============================================"
echo "Reloading Worker Services with File Logging"
echo "============================================"
echo ""

echo "1. Copying updated service files..."
sudo cp systemd/yp-state-workers.service /etc/systemd/system/
sudo cp systemd/google-state-workers.service /etc/systemd/system/

echo ""
echo "2. Reloading systemd daemon..."
sudo systemctl daemon-reload

echo ""
echo "3. Restarting services..."
sudo systemctl restart yp-state-workers.service
sudo systemctl restart google-state-workers.service

echo ""
echo "============================================"
echo "Services Reloaded!"
echo "============================================"
echo ""
echo "Logs are now being written to:"
echo "  - logs/yp_workers.log (for GUI live output)"
echo "  - logs/google_workers.log (for GUI live output)"
echo ""
echo "Check status:"
echo "  sudo systemctl status yp-state-workers.service"
echo "  sudo systemctl status google-state-workers.service"
echo ""
