#!/bin/bash
###############################################################################
# Google Maps City-First Crawler - 5 Worker Deployment Script
###############################################################################
# This script launches 5 independent workers with state partitioning.
# Each worker processes different states and writes to its own log file.
#
# Usage:
#   ./scripts/google_workers/start_google_workers.sh
#
# State Partitioning (10 states per worker):
#   Worker 1: AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA
#   Worker 2: HI, ID, IL, IN, IA, KS, KY, LA, ME, MD
#   Worker 3: MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ
#   Worker 4: NM, NY, NC, ND, OH, OK, OR, PA, RI, SC
#   Worker 5: SD, TN, TX, UT, VT, VA, WA, WV, WI, WY
###############################################################################

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================================================"
echo "Google Maps City-First Crawler - Starting 5 Workers"
echo "========================================================================"
echo "Project Root: $PROJECT_ROOT"
echo ""

# Change to project root
cd "$PROJECT_ROOT" || exit 1

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate || {
    echo "ERROR: Failed to activate virtual environment"
    exit 1
}

# Create logs directory if it doesn't exist
mkdir -p logs

# Stop any existing Google workers
echo "Stopping any existing Google workers..."
bash scripts/google_workers/stop_google_workers.sh 2>/dev/null

# Give processes time to terminate
sleep 2

# PID file to track workers
PID_FILE="logs/google_workers.pid"
rm -f "$PID_FILE"

echo ""
echo "Starting 5 workers with state partitioning..."
echo ""

# Worker 1: AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA
echo "[1/5] Starting Worker 1 (AL-GA)..."
nohup python3 cli_crawl_google_city_first.py \
    --worker-id 1 \
    --log-file logs/google_worker_1.log \
    --states AL AK AZ AR CA CO CT DE FL GA \
    --scrape-details \
    --save \
    > /dev/null 2>&1 &
WORKER1_PID=$!
echo "$WORKER1_PID" >> "$PID_FILE"
echo "  → Worker 1 started (PID: $WORKER1_PID)"
echo "  → Log: logs/google_worker_1.log"
echo ""

# Worker 2: HI, ID, IL, IN, IA, KS, KY, LA, ME, MD
echo "[2/5] Starting Worker 2 (HI-MD)..."
nohup python3 cli_crawl_google_city_first.py \
    --worker-id 2 \
    --log-file logs/google_worker_2.log \
    --states HI ID IL IN IA KS KY LA ME MD \
    --scrape-details \
    --save \
    > /dev/null 2>&1 &
WORKER2_PID=$!
echo "$WORKER2_PID" >> "$PID_FILE"
echo "  → Worker 2 started (PID: $WORKER2_PID)"
echo "  → Log: logs/google_worker_2.log"
echo ""

# Worker 3: MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ
echo "[3/5] Starting Worker 3 (MA-NJ)..."
nohup python3 cli_crawl_google_city_first.py \
    --worker-id 3 \
    --log-file logs/google_worker_3.log \
    --states MA MI MN MS MO MT NE NV NH NJ \
    --scrape-details \
    --save \
    > /dev/null 2>&1 &
WORKER3_PID=$!
echo "$WORKER3_PID" >> "$PID_FILE"
echo "  → Worker 3 started (PID: $WORKER3_PID)"
echo "  → Log: logs/google_worker_3.log"
echo ""

# Worker 4: NM, NY, NC, ND, OH, OK, OR, PA, RI, SC
echo "[4/5] Starting Worker 4 (NM-SC)..."
nohup python3 cli_crawl_google_city_first.py \
    --worker-id 4 \
    --log-file logs/google_worker_4.log \
    --states NM NY NC ND OH OK OR PA RI SC \
    --scrape-details \
    --save \
    > /dev/null 2>&1 &
WORKER4_PID=$!
echo "$WORKER4_PID" >> "$PID_FILE"
echo "  → Worker 4 started (PID: $WORKER4_PID)"
echo "  → Log: logs/google_worker_4.log"
echo ""

# Worker 5: SD, TN, TX, UT, VT, VA, WA, WV, WI, WY
echo "[5/5] Starting Worker 5 (SD-WY)..."
nohup python3 cli_crawl_google_city_first.py \
    --worker-id 5 \
    --log-file logs/google_worker_5.log \
    --states SD TN TX UT VT VA WA WV WI WY \
    --scrape-details \
    --save \
    > /dev/null 2>&1 &
WORKER5_PID=$!
echo "$WORKER5_PID" >> "$PID_FILE"
echo "  → Worker 5 started (PID: $WORKER5_PID)"
echo "  → Log: logs/google_worker_5.log"
echo ""

# Wait a moment for workers to initialize
sleep 3

# Verify all workers are running
echo "Verifying workers..."
ALL_RUNNING=true
for PID in $(cat "$PID_FILE"); do
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "  ✗ Worker with PID $PID failed to start"
        ALL_RUNNING=false
    fi
done

if [ "$ALL_RUNNING" = true ]; then
    echo "  ✓ All 5 workers are running successfully"
else
    echo "  ⚠ Some workers failed to start. Check logs for details."
fi

echo ""
echo "========================================================================"
echo "5-Worker System Deployed Successfully"
echo "========================================================================"
echo "PIDs saved to: logs/google_workers.pid"
echo ""
echo "Monitor workers:"
echo "  ./scripts/google_workers/check_google_workers.sh"
echo ""
echo "Stop workers:"
echo "  ./scripts/google_workers/stop_google_workers.sh"
echo ""
echo "View logs:"
echo "  tail -f logs/google_worker_1.log"
echo "  tail -f logs/google_worker_2.log"
echo "  tail -f logs/google_worker_3.log"
echo "  tail -f logs/google_worker_4.log"
echo "  tail -f logs/google_worker_5.log"
echo "========================================================================"
