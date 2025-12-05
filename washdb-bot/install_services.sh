#!/bin/bash
# Installation script for new optimized worker pool services

set -e

echo "============================================"
echo "Worker Pool Service Update"
echo "============================================"
echo ""

# Stop old services
echo "1. Stopping old services..."
sudo systemctl stop yp-5workers.service || true
sudo systemctl stop google-5workers.service || true

# Stop manually running workers
echo ""
echo "2. Stopping manually running workers..."
pkill -f "scrape_yp.state_worker_pool" || true
pkill -f "scrape_google.state_worker_pool" || true
sleep 3

# Disable old services
echo ""
echo "3. Disabling old services..."
sudo systemctl disable yp-5workers.service || true
sudo systemctl disable google-5workers.service || true

# Copy new service files
echo ""
echo "4. Installing new service files..."
sudo cp systemd/yp-state-workers.service /etc/systemd/system/
sudo cp systemd/google-state-workers.service /etc/systemd/system/

# Set correct permissions
sudo chmod 644 /etc/systemd/system/yp-state-workers.service
sudo chmod 644 /etc/systemd/system/google-state-workers.service

# Reload systemd
echo ""
echo "5. Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable new services
echo ""
echo "6. Enabling new services..."
sudo systemctl enable yp-state-workers.service
sudo systemctl enable google-state-workers.service

# Start new services
echo ""
echo "7. Starting new services..."
sudo systemctl start yp-state-workers.service
sudo systemctl start google-state-workers.service

# Check status
echo ""
echo "============================================"
echo "Service Status"
echo "============================================"
echo ""
echo "YP Workers:"
sudo systemctl status yp-state-workers.service --no-pager -l | head -20
echo ""
echo "Google Workers:"
sudo systemctl status google-state-workers.service --no-pager -l | head -20

echo ""
echo "============================================"
echo "Installation Complete!"
echo "============================================"
echo ""
echo "New services are now running with auto-restart enabled."
echo ""
echo "Useful commands:"
echo "  sudo systemctl status yp-state-workers.service"
echo "  sudo systemctl status google-state-workers.service"
echo "  sudo journalctl -u yp-state-workers.service -f"
echo "  sudo journalctl -u google-state-workers.service -f"
echo ""
