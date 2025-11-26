#!/bin/bash
#
# Stop all Yelp discovery workers
#

set -e

echo "========================================="
echo "Stopping Yelp Discovery Workers"
echo "========================================="

# Find all cli_crawl_yelp.py processes
YELP_PIDS=$(pgrep -f "cli_crawl_yelp.py" || true)

if [ -z "$YELP_PIDS" ]; then
    echo "No Yelp workers running"
    exit 0
fi

echo "Found Yelp worker processes:"
echo "$YELP_PIDS" | while read pid; do
    echo "  PID: $pid"
done

echo ""
echo "Stopping workers..."

# Send SIGTERM first (graceful shutdown)
echo "$YELP_PIDS" | xargs kill -TERM 2>/dev/null || true

# Wait a few seconds
sleep 3

# Check if any are still running
REMAINING=$(pgrep -f "cli_crawl_yelp.py" || true)

if [ -n "$REMAINING" ]; then
    echo "Some workers didn't stop gracefully. Forcing shutdown..."
    echo "$REMAINING" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# Final check
FINAL_CHECK=$(pgrep -f "cli_crawl_yelp.py" || true)

if [ -z "$FINAL_CHECK" ]; then
    echo ""
    echo "========================================="
    echo "✓ All Yelp workers stopped successfully"
    echo "========================================="
else
    echo ""
    echo "========================================="
    echo "⚠️  Warning: Some workers may still be running"
    echo "========================================="
    exit 1
fi
