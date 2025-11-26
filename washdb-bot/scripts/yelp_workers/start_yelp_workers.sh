#!/bin/bash
#
# Start 5 Yelp discovery workers in parallel
#
# Each worker handles 10 states (50 states total / 5 workers)
#
# Worker assignments:
# - Worker 0: AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA
# - Worker 1: HI, ID, IL, IN, IA, KS, KY, LA, ME, MD
# - Worker 2: MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ
# - Worker 3: NM, NY, NC, ND, OH, OK, OR, PA, RI, SC
# - Worker 4: SD, TN, TX, UT, VT, VA, WA, WV, WI, WY

set -e

# Get project root (2 levels up from scripts/yelp_workers/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Create logs directory if it doesn't exist
mkdir -p logs/yelp_workers

echo "========================================="
echo "Starting 5 Yelp Discovery Workers"
echo "========================================="
echo "Project root: $PROJECT_ROOT"
echo "Logs: $PROJECT_ROOT/logs/yelp_workers/"
echo ""

# Worker 0: AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA
echo "Starting Worker 0 (AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA)..."
nohup python3 cli_crawl_yelp.py \
    --states AL,AK,AZ,AR,CA,CO,CT,DE,FL,GA \
    --scrape-details \
    > logs/yelp_workers/worker_0.log 2>&1 &
WORKER_0_PID=$!
echo "  ✓ Worker 0 started (PID: $WORKER_0_PID)"

# Worker 1: HI, ID, IL, IN, IA, KS, KY, LA, ME, MD
echo "Starting Worker 1 (HI, ID, IL, IN, IA, KS, KY, LA, ME, MD)..."
nohup python3 cli_crawl_yelp.py \
    --states HI,ID,IL,IN,IA,KS,KY,LA,ME,MD \
    --scrape-details \
    > logs/yelp_workers/worker_1.log 2>&1 &
WORKER_1_PID=$!
echo "  ✓ Worker 1 started (PID: $WORKER_1_PID)"

# Worker 2: MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ
echo "Starting Worker 2 (MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ)..."
nohup python3 cli_crawl_yelp.py \
    --states MA,MI,MN,MS,MO,MT,NE,NV,NH,NJ \
    --scrape-details \
    > logs/yelp_workers/worker_2.log 2>&1 &
WORKER_2_PID=$!
echo "  ✓ Worker 2 started (PID: $WORKER_2_PID)"

# Worker 3: NM, NY, NC, ND, OH, OK, OR, PA, RI, SC
echo "Starting Worker 3 (NM, NY, NC, ND, OH, OK, OR, PA, RI, SC)..."
nohup python3 cli_crawl_yelp.py \
    --states NM,NY,NC,ND,OH,OK,OR,PA,RI,SC \
    --scrape-details \
    > logs/yelp_workers/worker_3.log 2>&1 &
WORKER_3_PID=$!
echo "  ✓ Worker 3 started (PID: $WORKER_3_PID)"

# Worker 4: SD, TN, TX, UT, VT, VA, WA, WV, WI, WY
echo "Starting Worker 4 (SD, TN, TX, UT, VT, VA, WA, WV, WI, WY)..."
nohup python3 cli_crawl_yelp.py \
    --states SD,TN,TX,UT,VT,VA,WA,WV,WI,WY \
    --scrape-details \
    > logs/yelp_workers/worker_4.log 2>&1 &
WORKER_4_PID=$!
echo "  ✓ Worker 4 started (PID: $WORKER_4_PID)"

echo ""
echo "========================================="
echo "All 5 workers started successfully!"
echo "========================================="
echo "Worker 0 PID: $WORKER_0_PID"
echo "Worker 1 PID: $WORKER_1_PID"
echo "Worker 2 PID: $WORKER_2_PID"
echo "Worker 3 PID: $WORKER_3_PID"
echo "Worker 4 PID: $WORKER_4_PID"
echo ""
echo "Monitor logs with:"
echo "  tail -f logs/yelp_workers/worker_0.log"
echo "  tail -f logs/yelp_workers/worker_1.log"
echo "  tail -f logs/yelp_workers/worker_2.log"
echo "  tail -f logs/yelp_workers/worker_3.log"
echo "  tail -f logs/yelp_workers/worker_4.log"
echo ""
echo "Stop all workers with:"
echo "  ./scripts/yelp_workers/stop_yelp_workers.sh"
echo "========================================="
