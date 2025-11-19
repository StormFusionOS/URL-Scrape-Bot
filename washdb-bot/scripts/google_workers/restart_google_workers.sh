#!/bin/bash
###############################################################################
# Google Maps City-First Crawler - Restart All Workers Script
###############################################################################
# This script stops all running workers and starts fresh 5-worker deployment.
#
# Usage:
#   ./scripts/google_workers/restart_google_workers.sh
###############################################################################

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================================================"
echo "Google Maps City-First Crawler - Restarting All Workers"
echo "========================================================================"
echo ""

# Stop workers
echo "Step 1: Stopping all workers..."
echo "------------------------------------------------------------------------"
bash "$SCRIPT_DIR/stop_google_workers.sh"

# Wait a moment
echo ""
echo "Waiting 3 seconds before restart..."
sleep 3

# Start workers
echo ""
echo "Step 2: Starting 5 workers..."
echo "------------------------------------------------------------------------"
bash "$SCRIPT_DIR/start_google_workers.sh"

echo ""
echo "Restart complete!"
echo ""
