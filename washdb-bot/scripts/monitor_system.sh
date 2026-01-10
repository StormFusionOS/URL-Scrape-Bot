#!/bin/bash
# System monitoring script - runs for 1 hour, collecting data every 2 minutes

LOGDIR="/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/monitoring"
mkdir -p "$LOGDIR"

START_TIME=$(date +%s)
END_TIME=$((START_TIME + 3600))  # 1 hour
INTERVAL=120  # 2 minutes

# Initialize log files
echo "timestamp,verified_providers,non_providers,pending_verification,standardized,pending_standardization" > "$LOGDIR/db_metrics.csv"
echo "timestamp,cpu_percent,memory_percent,memory_used_gb,gpu_util,gpu_memory_used_mb" > "$LOGDIR/system_metrics.csv"
echo "timestamp,service,status,memory_mb" > "$LOGDIR/service_status.csv"
echo "timestamp,worker,processed,success_rate" > "$LOGDIR/verification_progress.csv"
echo "timestamp,standardized_count,blocked_count,error_count" > "$LOGDIR/standardization_progress.csv"

echo "Monitoring started at $(date)"
echo "Will run until $(date -d @$END_TIME)"

collect_metrics() {
    TS=$(date '+%Y-%m-%d %H:%M:%S')

    # Database metrics
    DB_METRICS=$(PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db -t -A -F',' -c "
        SELECT
            COUNT(*) FILTER (WHERE provider_status = 'provider'),
            COUNT(*) FILTER (WHERE provider_status = 'non_provider'),
            COUNT(*) FILTER (WHERE provider_status = 'pending'),
            COUNT(*) FILTER (WHERE standardized_name IS NOT NULL),
            COUNT(*) FILTER (WHERE standardized_name IS NULL AND (verified = true OR llm_verified = true) AND website IS NOT NULL)
        FROM companies;
    " 2>/dev/null)
    echo "$TS,$DB_METRICS" >> "$LOGDIR/db_metrics.csv"

    # System metrics
    CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
    MEM_INFO=$(free -g | awk '/Mem:/ {printf "%.1f,%.1f", ($3/$2)*100, $3}')
    GPU_INFO=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
    if [ -z "$GPU_INFO" ]; then
        GPU_INFO="0,0"
    fi
    echo "$TS,$CPU,$MEM_INFO,$GPU_INFO" >> "$LOGDIR/system_metrics.csv"

    # Service status
    for SVC in washdb-verification washdb-standardization-browser; do
        STATUS=$(systemctl is-active $SVC 2>/dev/null || echo "unknown")
        MEM=$(systemctl show $SVC --property=MemoryCurrent 2>/dev/null | cut -d= -f2)
        MEM_MB=$((${MEM:-0} / 1024 / 1024))
        echo "$TS,$SVC,$STATUS,$MEM_MB" >> "$LOGDIR/service_status.csv"
    done

    # Verification worker progress (parse last line from each worker log)
    for i in 0 1 2 3; do
        LOG="/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/verify_worker_$i.log"
        if [ -f "$LOG" ]; then
            PROGRESS=$(grep "Progress:" "$LOG" 2>/dev/null | tail -1 | grep -oP 'Processed=\K\d+|Rate=\K[\d.]+' | tr '\n' ',' | sed 's/,$//')
            if [ -n "$PROGRESS" ]; then
                echo "$TS,worker_$i,$PROGRESS" >> "$LOGDIR/verification_progress.csv"
            fi
        fi
    done

    # Standardization progress
    STD_LOG="/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/standardization_browser.log"
    if [ -f "$STD_LOG" ]; then
        # Count recent standardizations, blocks, and errors in last interval
        SINCE=$(date -d "$INTERVAL seconds ago" '+%Y-%m-%d %H:%M')
        STD_COUNT=$(grep -c "Standardized:" "$STD_LOG" 2>/dev/null || echo 0)
        BLOCK_COUNT=$(grep -c "blocked\|CAPTCHA" "$STD_LOG" 2>/dev/null || echo 0)
        ERR_COUNT=$(grep -c "ERROR\|Failed" "$STD_LOG" 2>/dev/null || echo 0)
        echo "$TS,$STD_COUNT,$BLOCK_COUNT,$ERR_COUNT" >> "$LOGDIR/standardization_progress.csv"
    fi

    echo "[$TS] Metrics collected"
}

# Initial collection
collect_metrics

# Main loop
while [ $(date +%s) -lt $END_TIME ]; do
    sleep $INTERVAL
    collect_metrics
done

echo "Monitoring completed at $(date)"
echo "Data saved to $LOGDIR"
