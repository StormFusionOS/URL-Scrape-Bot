#!/bin/bash
# Development GUI Runner
# Launches the NiceGUI dashboard with development settings

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================="
echo "Starting URL Scrape Bot Dashboard (Dev)"
echo "========================================="
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Error: Virtual environment not found"
    echo "Run ./scripts/dev/setup.sh first"
    exit 1
fi

# Activate venv
source venv/bin/activate

# Check if .env exists, otherwise try .env.dev
if [ ! -f ".env" ] && [ ! -f ".env.dev" ]; then
    echo "❌ Error: No .env or .env.dev file found"
    echo "Copy .env.example to .env and configure it"
    exit 1
fi

# Set PYTHONPATH to project root
export PYTHONPATH="$PROJECT_ROOT"

# Load .env.dev if it exists (overrides .env for development)
if [ -f ".env.dev" ]; then
    echo "Loading development environment (.env.dev)..."
    export $(grep -v '^#' .env.dev | xargs)
elif [ -f ".env" ]; then
    echo "Loading environment (.env)..."
    export $(grep -v '^#' .env | xargs)
fi

# Show configuration
echo ""
echo "Configuration:"
echo "  Database: ${DATABASE_URL%%@*}@..." # Hide password
echo "  Dashboard Port: ${NICEGUI_PORT:-8080}"
echo "  Worker Count: ${WORKER_COUNT:-5}"
echo "  Crawl Delay: ${CRAWL_DELAY_SECONDS:-10}s"
echo ""

# Launch dashboard
echo "Launching NiceGUI dashboard..."
echo "Access at: http://localhost:${NICEGUI_PORT:-8080}"
echo ""
echo "Press Ctrl+C to stop the dashboard"
echo "========================================="
echo ""

python niceui/main.py
