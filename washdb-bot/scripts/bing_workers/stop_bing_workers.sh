#!/bin/bash
###############################################################################
# Bing Local Search City-First Crawler - Stop All Workers Script
###############################################################################
# This script gracefully stops all running Bing Local Search workers.
#
# Usage:
#   ./scripts/bing_workers/stop_bing_workers.sh
###############################################################################

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================================================"
echo "Bing Local Search City-First Crawler - Stopping All Workers"
echo "========================================================================"

# Change to project root
cd "$PROJECT_ROOT" || exit 1

PID_FILE="logs/bing_workers.pid"

# Check if PID file exists
if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found at $PID_FILE"
    echo "Searching for Bing worker processes..."

    # Find and kill any running cli_crawl_bing_city_first processes
    PIDS=$(ps aux | grep -i "cli_crawl_bing_city_first" | grep -v grep | awk '{print $2}')

    if [ -z "$PIDS" ]; then
        echo "No Bing worker processes found."
        # Don't exit - continue to final cleanup
    else

    echo "Found the following Bing worker processes:"
    for PID in $PIDS; do
        echo "  - PID: $PID"
    done

    echo ""
    echo "Stopping workers..."
    for PID in $PIDS; do
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "  → Killing PID $PID and all child processes..."
            # Kill the process and all its children
            pkill -TERM -P "$PID" 2>/dev/null || true
            kill "$PID" 2>/dev/null
        fi
    done

    # Wait for processes to terminate
    sleep 2

    # Force kill if still running
    for PID in $PIDS; do
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "  → Force killing PID $PID and all child processes..."
            pkill -9 -P "$PID" 2>/dev/null || true
            kill -9 "$PID" 2>/dev/null
        fi
    done

    # Also kill any orphaned Playwright/Chromium processes
    echo "  → Cleaning up orphaned browser processes..."
    pgrep -f "playwright/driver/node" | xargs kill -9 2>/dev/null || true
    killall -9 headless_shell 2>/dev/null || true

        echo ""
        echo "All Bing workers stopped."
    fi
fi  # End of "no PID file" branch

# Continue to final cleanup instead of exiting early

# Read PIDs from file (if it exists)
if [ -f "$PID_FILE" ]; then
    echo "Reading PIDs from $PID_FILE..."
    PIDS=$(cat "$PID_FILE")

    if [ -z "$PIDS" ]; then
        echo "PID file is empty."
        rm -f "$PID_FILE"
    else

echo "Stopping workers..."
STOPPED_COUNT=0
RUNNING_COUNT=0

for PID in $PIDS; do
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "  → Stopping worker with PID $PID and child processes..."
        # Kill child processes first
        pkill -TERM -P "$PID" 2>/dev/null || true
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
            echo "  → Force killing worker with PID $PID and child processes..."
            pkill -9 -P "$PID" 2>/dev/null || true
            kill -9 "$PID" 2>/dev/null
        else
            STOPPED_COUNT=$((STOPPED_COUNT + 1))
        fi
    done

    # Clean up any orphaned browser processes
    echo "  → Cleaning up orphaned browser processes..."
    pgrep -f "playwright/driver/node" | xargs kill -9 2>/dev/null || true
    killall -9 headless_shell 2>/dev/null || true
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
        echo "All Bing Workers Stopped"
        echo "========================================================================"
    else
        echo "  ⚠ Some workers could not be stopped. Manual intervention may be required."
        echo ""
        echo "To manually kill remaining processes:"
        echo "  ps aux | grep cli_crawl_bing_city_first"
        echo "  kill -9 <PID>"
    fi
    fi  # End of "if PIDS not empty"
fi  # End of "if PID_FILE exists"

# Final cleanup - always run to catch any orphaned processes
echo ""
echo "Final cleanup of any orphaned browser processes..."

# Count orphaned processes before cleanup
ORPHAN_COUNT=$(ps aux | egrep "(playwright|headless_shell)" | grep -v grep | wc -l)
if [ "$ORPHAN_COUNT" -gt 0 ]; then
    echo "  Found $ORPHAN_COUNT orphaned browser processes"

    # Kill processes multiple times to catch any stragglers or respawns
    for i in 1 2 3 4 5; do
        # Kill playwright node processes
        pgrep -f "playwright/driver/node" | xargs -r kill -9 2>/dev/null || true

        # Kill chromium/headless_shell processes
        killall -9 headless_shell 2>/dev/null || true

        sleep 1
    done

    # Final sleep to ensure all processes are dead
    sleep 2

    # Verify cleanup
    REMAINING=$(ps aux | egrep "(playwright|headless_shell)" | grep -v grep | wc -l)
    if [ "$REMAINING" -eq 0 ]; then
        echo "  ✓ All $ORPHAN_COUNT orphaned processes cleaned up"
    else
        echo "  ⚠ Warning: $REMAINING orphaned processes still running after cleanup"
        echo "  Run this command to manually kill them:"
        echo "    pgrep -f 'playwright/driver/node' | xargs -r kill -9 && killall -9 headless_shell"
    fi
else
    echo "  ✓ No orphaned processes found"
fi

echo ""
