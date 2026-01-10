#!/bin/bash
# Cron job wrapper with timeout, nice, and ionice support
# Usage: cron_wrapper.sh <timeout_minutes> <nice_level> <command...>
#
# Examples:
#   cron_wrapper.sh 30 10 python script.py
#   cron_wrapper.sh 60 0 /path/to/script.sh  # nice=0 means no nice

TIMEOUT_MINS="${1:-30}"
NICE_LEVEL="${2:-10}"
shift 2

# Validate inputs
if [[ ! "$TIMEOUT_MINS" =~ ^[0-9]+$ ]]; then
    echo "Error: timeout must be a number" >&2
    exit 1
fi

if [[ ! "$NICE_LEVEL" =~ ^[0-9]+$ ]] || [ "$NICE_LEVEL" -gt 19 ]; then
    echo "Error: nice level must be 0-19" >&2
    exit 1
fi

# Build command with optional nice/ionice
CMD=""
if [ "$NICE_LEVEL" -gt 0 ]; then
    CMD="nice -n $NICE_LEVEL ionice -c 3 "
fi

# Execute with timeout
exec timeout --kill-after=5m "${TIMEOUT_MINS}m" $CMD "$@"
