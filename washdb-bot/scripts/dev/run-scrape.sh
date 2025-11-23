#!/bin/bash
# Development Scraper Runner
# Runs a single test scrape with safe development settings

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default values
TARGET="yp"
CITY=""
CATEGORY="pressure washing"
MAX_TARGETS=10
STATES=""

# Usage function
usage() {
    echo "Usage: $0 --target [yp|google|bing] [options]"
    echo ""
    echo "Options:"
    echo "  --target      Scraper target: yp, google, or bing (default: yp)"
    echo "  --city        City to scrape (e.g., 'Peoria, IL')"
    echo "  --states      State abbreviation (e.g., RI, TX)"
    echo "  --category    Business category (default: 'pressure washing')"
    echo "  --max-targets Max targets to scrape (default: 10)"
    echo "  --help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --target yp --city 'Peoria, IL'"
    echo "  $0 --target google --states RI --max-targets 20"
    echo "  $0 --target yp --states TX --category 'window cleaning'"
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --target)
            TARGET="$2"
            shift 2
            ;;
        --city)
            CITY="$2"
            shift 2
            ;;
        --states)
            STATES="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --max-targets)
            MAX_TARGETS="$2"
            shift 2
            ;;
        --help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate target
if [[ ! "$TARGET" =~ ^(yp|google|bing)$ ]]; then
    echo "❌ Error: Invalid target '$TARGET'. Must be: yp, google, or bing"
    usage
fi

echo "========================================="
echo "Dev Scraper Runner - $TARGET"
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

# Set PYTHONPATH
export PYTHONPATH="$PROJECT_ROOT"

# Load .env.dev if it exists (overrides .env for development)
if [ -f ".env.dev" ]; then
    echo "Loading development environment (.env.dev)..."
    export $(grep -v '^#' .env.dev | xargs)
elif [ -f ".env" ]; then
    echo "Loading environment (.env)..."
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ Error: No .env or .env.dev file found"
    exit 1
fi

# Show configuration
echo ""
echo "Configuration:"
echo "  Target: $TARGET"
echo "  City: ${CITY:-N/A}"
echo "  States: ${STATES:-N/A}"
echo "  Category: $CATEGORY"
echo "  Max Targets: $MAX_TARGETS"
echo "  Worker Count: ${WORKER_COUNT:-2}"
echo "  Crawl Delay: ${CRAWL_DELAY_SECONDS:-15}s"
echo ""

# Build command based on target
case $TARGET in
    yp)
        CMD="python cli_crawl_yp.py --categories '$CATEGORY' --max-targets $MAX_TARGETS"

        if [ -n "$STATES" ]; then
            CMD="$CMD --states $STATES"
        fi

        if [ -n "$CITY" ]; then
            echo "⚠ Warning: YP scraper uses --states, not --city. Using state from city if possible."
            # Extract state from "City, ST" format
            STATE=$(echo "$CITY" | grep -oP '(?<=, )[A-Z]{2}')
            if [ -n "$STATE" ]; then
                CMD="$CMD --states $STATE"
            fi
        fi
        ;;

    google)
        CMD="python cli_crawl_google_city_first.py --max-workers 2"

        if [ -n "$STATES" ]; then
            CMD="$CMD --states $STATES"
        fi

        if [ -n "$CITY" ]; then
            echo "⚠ Note: Google scraper uses --states. Extracting state from city."
            STATE=$(echo "$CITY" | grep -oP '(?<=, )[A-Z]{2}')
            if [ -n "$STATE" ]; then
                CMD="$CMD --states $STATE"
            fi
        fi
        ;;

    bing)
        echo "❌ Error: Bing scraper CLI not yet implemented"
        echo "Use the GUI dashboard (Discover tab) to run Bing scrapes"
        exit 1
        ;;
esac

# Run the scraper
echo "Running command:"
echo "  $CMD"
echo ""
echo "Logs will be written to logs/${TARGET}_*.log"
echo "Press Ctrl+C to stop the scraper"
echo "========================================="
echo ""

eval $CMD
