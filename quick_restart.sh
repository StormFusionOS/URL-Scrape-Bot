#!/bin/bash
# Quick restart script
echo "Restarting washdb-bot service..."
sudo systemctl restart washdb-bot
sleep 2
echo "Service restarted. GUI should be accessible at http://127.0.0.1:8080"
