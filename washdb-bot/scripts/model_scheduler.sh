#!/bin/bash
# Model Scheduler - Switches between verification and standardization services
# Verification: 6am-6pm (daytime) - 12 hours
# Standardization: 6pm-6am (nighttime) - 12 hours  (uses headed browser!)
# Runs via cron every 5 minutes to check and switch if needed

HOUR=$(date +%H)
WASHDB_DIR="/home/rivercityscrape/URL-Scrape-Bot/washdb-bot"
LOG_FILE="$WASHDB_DIR/logs/model_scheduler.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

# Ensure Xvfb virtual display is running (needed for browser-based standardization)
ensure_xvfb() {
    if ! xdpyinfo -display :99 >/dev/null 2>&1; then
        log "Starting Xvfb virtual display :99..."
        Xvfb :99 -screen 0 1920x1080x24 -ac &
        sleep 2
    fi
}

# Determine which mode we should be in
# Verification: 6am (06) to 6pm (18)
# Standardization: 6pm (18) to 6am (06)
if [ "$HOUR" -ge 6 ] && [ "$HOUR" -lt 18 ]; then
    MODE="verification"
else
    MODE="standardization"
fi

log "Hour: $HOUR, Mode should be: $MODE"

# Check what's currently running via systemctl
VERIF_ACTIVE=$(systemctl is-active washdb-verification 2>/dev/null)
STANDARD_ACTIVE=$(systemctl is-active washdb-standardization-browser 2>/dev/null)

log "Verification service: $VERIF_ACTIVE, Standardization (browser) service: $STANDARD_ACTIVE"

if [ "$MODE" == "verification" ]; then
    # Should be running verification
    if [ "$VERIF_ACTIVE" != "active" ]; then
        log "SWITCHING TO VERIFICATION MODE"

        # Stop browser-based standardization service
        if [ "$STANDARD_ACTIVE" == "active" ]; then
            log "Stopping browser-based standardization service..."
            systemctl stop washdb-standardization-browser 2>/dev/null
            sleep 3
        fi

        # Also stop old standardization service if running
        systemctl stop washdb-standardization 2>/dev/null

        # Unload standardization model from Ollama to free GPU memory
        log "Unloading standardization models..."
        ollama stop standardization-llama3b 2>/dev/null
        ollama stop standardization-mistral7b 2>/dev/null
        sleep 2

        # Start verification service
        log "Starting verification service..."
        systemctl start washdb-verification 2>/dev/null

        log "Verification service started"
    else
        log "Verification service already running"
    fi

elif [ "$MODE" == "standardization" ]; then
    # Should be running browser-based standardization
    if [ "$STANDARD_ACTIVE" != "active" ]; then
        log "SWITCHING TO STANDARDIZATION MODE (BROWSER-BASED)"

        # Stop verification service
        if [ "$VERIF_ACTIVE" == "active" ]; then
            log "Stopping verification service..."
            systemctl stop washdb-verification 2>/dev/null
            sleep 3
        fi

        # Unload verification model from Ollama to free GPU memory
        log "Unloading verification model..."
        ollama stop verification-mistral-proper 2>/dev/null
        sleep 2

        # Ensure Xvfb is running for headed browser
        ensure_xvfb

        # Start browser-based standardization service
        log "Starting browser-based standardization service..."
        systemctl start washdb-standardization-browser 2>/dev/null

        log "Browser-based standardization service started"
    else
        log "Browser-based standardization service already running"
    fi
fi

log "Scheduler check complete"
