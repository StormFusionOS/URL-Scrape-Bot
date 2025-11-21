#!/bin/bash
###############################################################################
# Google Maps City-First Crawler - Check Worker Status Script
###############################################################################
# This script checks the status of all Google Maps workers and displays
# recent activity from their log files.
#
# Usage:
#   ./scripts/google_workers/check_google_workers.sh
###############################################################################

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================================================"
echo "Google Maps City-First Crawler - Worker Status"
echo "========================================================================"
date
echo ""

# Change to project root
cd "$PROJECT_ROOT" || exit 1

# Database credentials from environment or defaults
export PGPASSWORD="${DATABASE_PASSWORD:-Washdb123}"
DB_HOST="${DB_HOST:-localhost}"
DB_NAME="${DB_NAME:-washbot_db}"
DB_USER="${DB_USER:-washbot}"

PID_FILE="logs/google_workers.pid"

# Check worker processes
echo "Worker Process Status:"
echo "------------------------------------------------------------------------"

if [ -f "$PID_FILE" ]; then
    RUNNING_COUNT=0
    STOPPED_COUNT=0

    worker_num=1
    for PID in $(cat "$PID_FILE"); do
        if ps -p "$PID" > /dev/null 2>&1; then
            # Get process uptime
            START_TIME=$(ps -p "$PID" -o lstart=)
            echo "  ✓ Worker $worker_num (PID: $PID) - RUNNING"
            echo "    Started: $START_TIME"
            RUNNING_COUNT=$((RUNNING_COUNT + 1))
        else
            echo "  ✗ Worker $worker_num (PID: $PID) - STOPPED"
            STOPPED_COUNT=$((STOPPED_COUNT + 1))
        fi
        worker_num=$((worker_num + 1))
    done

    echo ""
    echo "Summary: $RUNNING_COUNT running, $STOPPED_COUNT stopped"
else
    echo "  No PID file found. Checking for any running Google workers..."
    PIDS=$(ps aux | grep -i "cli_crawl_google_city_first" | grep -v grep | awk '{print $2}')

    if [ -z "$PIDS" ]; then
        echo "  No Google workers running."
    else
        echo "  Found running Google workers (not tracked in PID file):"
        for PID in $PIDS; do
            START_TIME=$(ps -p "$PID" -o lstart=)
            echo "    - PID: $PID (Started: $START_TIME)"
        done
    fi
fi

echo ""
echo "========================================================================"
echo "Recent Activity (Last 5 Lines Per Worker)"
echo "========================================================================"

for i in 1 2 3 4 5; do
    LOG_FILE="logs/google_worker_$i.log"

    echo ""
    echo "Worker $i (logs/google_worker_$i.log):"
    echo "------------------------------------------------------------------------"

    if [ -f "$LOG_FILE" ]; then
        # Get file size and last modified time
        FILE_SIZE=$(du -h "$LOG_FILE" | cut -f1)
        LAST_MODIFIED=$(stat -c %y "$LOG_FILE" 2>/dev/null || stat -f %Sm "$LOG_FILE" 2>/dev/null)

        echo "Size: $FILE_SIZE | Last Modified: $LAST_MODIFIED"
        echo ""

        # Show last 5 lines
        tail -5 "$LOG_FILE" | sed 's/^/  /'
    else
        echo "  Log file not found."
    fi
done

echo ""
echo "========================================================================"
echo "Database Statistics"
echo "========================================================================"

# Check if psql is available
if command -v psql > /dev/null 2>&1; then
    echo ""
    echo "Google Targets Status:"
    echo "------------------------------------------------------------------------"

    STATS=$(PGPASSWORD="$PGPASSWORD" psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -t -c "
        SELECT
            status,
            COUNT(*) as count
        FROM google_targets
        GROUP BY status
        ORDER BY status;
    " 2>/dev/null)

    if [ $? -eq 0 ]; then
        echo "$STATS" | sed 's/^/  /'

        # Total targets
        TOTAL=$(PGPASSWORD="$PGPASSWORD" psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -t -c "
            SELECT COUNT(*) FROM google_targets;
        " 2>/dev/null | tr -d ' ')

        echo ""
        echo "  Total Targets: $TOTAL"
    else
        echo "  Unable to query database (check credentials)"
    fi

    echo ""
    echo "Companies from Google Maps:"
    echo "------------------------------------------------------------------------"

    COMPANY_STATS=$(PGPASSWORD="$PGPASSWORD" psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -t -c "
        SELECT
            COUNT(*) FILTER (WHERE discovery_source = 'google_maps') as google_total,
            COUNT(*) FILTER (WHERE discovery_source = 'google_maps' AND updated_at > NOW() - INTERVAL '24 hours') as added_24h,
            COUNT(*) FILTER (WHERE discovery_source = 'google_maps' AND updated_at > NOW() - INTERVAL '1 hour') as added_1h
        FROM companies;
    " 2>/dev/null)

    if [ $? -eq 0 ]; then
        GOOGLE_TOTAL=$(echo "$COMPANY_STATS" | awk '{print $1}')
        ADDED_24H=$(echo "$COMPANY_STATS" | awk '{print $3}')
        ADDED_1H=$(echo "$COMPANY_STATS" | awk '{print $5}')

        echo "  Total from Google Maps: $GOOGLE_TOTAL"
        echo "  Added in last 24 hours: $ADDED_24H"
        echo "  Added in last hour: $ADDED_1H"
    else
        echo "  Unable to query database (check credentials)"
    fi
else
    echo "  psql not available - skipping database stats"
fi

echo ""
echo "========================================================================"
echo "Useful Commands:"
echo "========================================================================"
echo "  Start workers:  ./scripts/google_workers/start_google_workers.sh"
echo "  Stop workers:   ./scripts/google_workers/stop_google_workers.sh"
echo "  Restart:        ./scripts/google_workers/restart_google_workers.sh"
echo ""
echo "  View live logs:"
echo "    tail -f logs/google_worker_1.log"
echo "    tail -f logs/google_worker_2.log"
echo "    tail -f logs/google_worker_3.log"
echo "    tail -f logs/google_worker_4.log"
echo "    tail -f logs/google_worker_5.log"
echo "========================================================================"
echo ""
