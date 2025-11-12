#!/bin/bash
# Restart Dashboard Script
# This script properly restarts the dashboard and clears all caches

echo "=========================================="
echo "Restarting Washdb-Bot Dashboard"
echo "=========================================="

# 1. Kill any existing dashboard processes
echo "1. Stopping existing dashboard processes..."
pkill -9 -f "python -m niceui.main"
sleep 2

# 2. Clear Python cache
echo "2. Clearing Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# 3. Check port is free
echo "3. Checking port 8080..."
if lsof -ti:8080 > /dev/null 2>&1; then
    echo "   Port 8080 still in use, killing processes..."
    lsof -ti:8080 | xargs kill -9 2>/dev/null
    sleep 2
fi

# 4. Activate venv and start dashboard
echo "4. Starting dashboard..."
cd "$(dirname "$0")"
source venv/bin/activate

# Start in background and log output
nohup python -m niceui.main > /tmp/dashboard_restart.log 2>&1 &
DASHBOARD_PID=$!

# 5. Wait for startup
echo "5. Waiting for dashboard to start..."
sleep 5

# 6. Check if it's running
if ps -p $DASHBOARD_PID > /dev/null 2>&1; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/)
    if [ "$HTTP_CODE" = "200" ]; then
        echo ""
        echo "=========================================="
        echo "✅ Dashboard started successfully!"
        echo "=========================================="
        echo "PID: $DASHBOARD_PID"
        echo "URL: http://127.0.0.1:8080"
        echo "Log: /tmp/dashboard_restart.log"
        echo ""
        echo "IMPORTANT: In your browser:"
        echo "  1. Press Ctrl+Shift+R (hard refresh)"
        echo "  2. Or press Ctrl+Shift+Delete and clear cache"
        echo "  3. Then reload the page"
        echo "=========================================="
    else
        echo "❌ Dashboard started but not responding (HTTP $HTTP_CODE)"
        echo "Check logs: tail -f /tmp/dashboard_restart.log"
        exit 1
    fi
else
    echo "❌ Dashboard failed to start"
    echo "Check logs: tail -f /tmp/dashboard_restart.log"
    exit 1
fi
