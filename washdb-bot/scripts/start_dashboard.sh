#!/bin/bash
# Washbot Integrated Dashboard Startup Script

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "========================================================================"
echo " Starting Washbot Integrated Dashboard"
echo "========================================================================"
echo ""

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✓ Virtual environment activated"
elif [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
else
    echo "✗ Virtual environment not found!"
    exit 1
fi

# Check if already running
if lsof -i :8080 | grep LISTEN > /dev/null; then
    echo "⚠ Port 8080 is already in use"
    read -p "Kill existing process? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pkill -f "python -m niceui.main"
        sleep 2
        echo "✓ Stopped existing process"
    else
        echo "Exiting..."
        exit 1
    fi
fi

# Start dashboard
echo ""
echo "Starting dashboard..."
echo "Dashboard will be available at: http://127.0.0.1:8080"
echo "Press Ctrl+C to stop"
echo "========================================================================"
echo ""

python -m niceui.main
