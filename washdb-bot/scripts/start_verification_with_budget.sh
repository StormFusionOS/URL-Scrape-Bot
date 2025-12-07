#!/bin/bash
# Start verification workers with API credit monitoring
# This will automatically stop when credits are depleted

BUDGET=${1:-50}
MIN_RESERVE=${2:-5}

echo "======================================================================"
echo "STARTING VERIFICATION WITH BUDGET MONITORING"
echo "======================================================================"
echo "Budget: \$$BUDGET"
echo "Min Reserve: \$$MIN_RESERVE"
echo "======================================================================"
echo ""

# Check if API key is set
if ! grep -q "^ANTHROPIC_API_KEY=sk-ant-" .env; then
    echo "❌ ERROR: ANTHROPIC_API_KEY not set in .env"
    echo ""
    echo "Please edit .env and add your API key:"
    echo "  nano .env"
    echo "  # Change line 111 to: ANTHROPIC_API_KEY=sk-ant-your-key-here"
    exit 1
fi

echo "✓ API key configured"

# Start verification workers
echo ""
echo "Starting verification workers..."
systemctl start washdb-verification-orchestrator
for i in {1..5}; do
    systemctl start washdb-verification-worker@$i
done

echo "✓ All workers started"

# Wait a moment for workers to initialize
sleep 5

# Check worker status
echo ""
echo "Worker status:"
systemctl is-active washdb-verification-orchestrator && echo "  ✓ Orchestrator: running" || echo "  ✗ Orchestrator: not running"
for i in {1..5}; do
    systemctl is-active washdb-verification-worker@$i && echo "  ✓ Worker $i: running" || echo "  ✗ Worker $i: not running"
done

# Start credit monitor
echo ""
echo "Starting credit monitor..."
echo "This will track API usage and automatically stop workers when budget is reached."
echo ""
echo "Press Ctrl+C to stop monitoring (workers will keep running)"
echo ""

sleep 2

./venv/bin/python scripts/monitor_api_credits.py \
    --budget $BUDGET \
    --min-reserve $MIN_RESERVE \
    --check-interval 30
