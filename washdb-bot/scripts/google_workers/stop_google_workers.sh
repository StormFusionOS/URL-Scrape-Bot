#!/bin/bash
###############################################################################
# Google Maps City-First Crawler - Stop All Workers Script
###############################################################################
# This script gracefully stops all running Google Maps workers.
#
# Usage:
#   ./scripts/google_workers/stop_google_workers.sh
###############################################################################

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================================================"
echo "Google Maps City-First Crawler - Stopping All Workers"
echo "========================================================================"

# Change to project root
cd "$PROJECT_ROOT" || exit 1

PID_FILE="logs/google_workers.pid"

# Check if PID file exists
if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found at $PID_FILE"
    echo "Searching for Google worker processes..."

    # Find and kill any running cli_crawl_google_city_first processes
    PIDS=$(ps aux | grep -i "cli_crawl_google_city_first" | grep -v grep | awk '{print $2}')

    if [ -z "$PIDS" ]; then
        echo "No Google worker processes found."
        exit 0
    fi

    echo "Found the following Google worker processes:"
    for PID in $PIDS; do
        echo "  - PID: $PID"
    done

    echo ""
    echo "Stopping workers..."
    for PID in $PIDS; do
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "  → Killing PID $PID..."
            kill "$PID" 2>/dev/null
        fi
    done

    # Wait for processes to terminate
    sleep 2

    # Force kill if still running
    for PID in $PIDS; do
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "  → Force killing PID $PID..."
            kill -9 "$PID" 2>/dev/null
        fi
    done

    echo ""
    echo "All Google workers stopped."
    exit 0
fi

# Read PIDs from file
echo "Reading PIDs from $PID_FILE..."
PIDS=$(cat "$PID_FILE")

if [ -z "$PIDS" ]; then
    echo "PID file is empty."
    rm -f "$PID_FILE"
    exit 0
fi

echo "Stopping workers..."
STOPPED_COUNT=0
RUNNING_COUNT=0

for PID in $PIDS; do
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "  → Stopping worker with PID $PID..."
        kill "$PID" 2>/dev/null
        RUNNING_COUNT=$((RUNNING_COUNT + 1))
    else
        echo "  → Worker with PID $PID is not running"
    fi
done

# Wait for graceful shutdown
if [ $RUNNING_COUNT -gt 0 ]; then
    echo ""
    echo "Waiting for workers to terminate gracefully (5 seconds)..."
    sleep 5

    # Force kill any that didn't terminate
    echo ""
    echo "Checking for remaining processes..."
    for PID in $PIDS; do
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "  → Force killing worker with PID $PID..."
            kill -9 "$PID" 2>/dev/null
        else
            STOPPED_COUNT=$((STOPPED_COUNT + 1))
        fi
    done
fi

# Verify all workers are stopped
echo ""
echo "Verifying all workers are stopped..."
ALL_STOPPED=true
for PID in $PIDS; do
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "  ✗ Worker with PID $PID is still running"
        ALL_STOPPED=false
    fi
done

if [ "$ALL_STOPPED" = true ]; then
    echo "  ✓ All workers stopped successfully"
    rm -f "$PID_FILE"
    echo ""
    echo "========================================================================"
    echo "All Google Workers Stopped"
    echo "========================================================================"
else
    echo "  ⚠ Some workers could not be stopped. Manual intervention may be required."
    echo ""
    echo "To manually kill remaining processes:"
    echo "  ps aux | grep cli_crawl_google_city_first"
    echo "  kill -9 <PID>"
fi

echo ""
