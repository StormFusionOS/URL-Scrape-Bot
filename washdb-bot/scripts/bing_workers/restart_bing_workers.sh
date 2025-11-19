#!/bin/bash
###############################################################################
# Bing Local Search City-First Crawler - Restart All Workers Script
###############################################################################
# This script gracefully restarts all Bing Local Search workers.
#
# Usage:
#   ./scripts/bing_workers/restart_bing_workers.sh
###############################################################################

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================================================"
echo "Bing Local Search City-First Crawler - Restarting All Workers"
echo "========================================================================"

# Change to project root
cd "$PROJECT_ROOT" || exit 1

# Stop all workers
echo "Stopping workers..."
bash scripts/bing_workers/stop_bing_workers.sh

# Wait for shutdown
sleep 3

# Start all workers
echo ""
echo "Starting workers..."
bash scripts/bing_workers/start_bing_workers.sh

echo ""
echo "========================================================================"
echo "Restart Complete"
echo "========================================================================"
echo "Check worker status:"
echo "  ./scripts/bing_workers/check_bing_workers.sh"
echo "========================================================================"
echo ""
