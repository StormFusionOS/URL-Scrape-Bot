#!/usr/bin/env python3
"""
1-hour system monitoring script for watchdog validation.
Collects metrics every 5 minutes and writes to a log file.
"""

import os
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

LOG_FILE = "logs/monitor_1hour.log"
INTERVAL_SECONDS = 300  # 5 minutes
DURATION_SECONDS = 3600  # 1 hour

def log(msg):
    """Write timestamped message to log file and stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def get_chrome_count():
    """Get Chrome process count."""
    try:
        result = subprocess.run(['pgrep', '-c', '-f', 'chrom'],
                              capture_output=True, text=True, timeout=5)
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except:
        return 0

def get_memory_usage():
    """Get memory usage percentage."""
    try:
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
        mem_total = int([l for l in lines if 'MemTotal' in l][0].split()[1])
        mem_avail = int([l for l in lines if 'MemAvailable' in l][0].split()[1])
        return round((1 - mem_avail / mem_total) * 100, 1)
    except:
        return 0

def get_heartbeat_status():
    """Get heartbeat status from database."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="127.0.0.1",
            database="washbot_db",
            user="washbot",
            password=os.getenv("WASHDB_PASSWORD", "Washdb123")
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT worker_name, worker_type, jobs_completed, jobs_failed,
                   ROUND(EXTRACT(EPOCH FROM (NOW() - last_heartbeat))/60, 1) AS mins_ago
            FROM job_heartbeats
            WHERE status = 'running'
            ORDER BY last_heartbeat DESC
        """)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        return []

def get_watchdog_stats():
    """Get watchdog event counts."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="127.0.0.1",
            database="washbot_db",
            user="washbot",
            password=os.getenv("WASHDB_PASSWORD", "Washdb123")
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE event_type = 'stale_detected') as stale,
                COUNT(*) FILTER (WHERE event_type = 'resource_warning') as resource_warnings,
                COUNT(*) FILTER (WHERE event_type = 'healing_triggered') as healing
            FROM watchdog_events
            WHERE timestamp > NOW() - INTERVAL '1 hour'
        """)
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as e:
        return (0, 0, 0)

def get_healing_actions():
    """Get healing action count."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="127.0.0.1",
            database="washbot_db",
            user="washbot",
            password=os.getenv("WASHDB_PASSWORD", "Washdb123")
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM healing_actions
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """)
        row = cur.fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception as e:
        return 0

def collect_metrics():
    """Collect all metrics."""
    log("=" * 60)
    log("METRICS COLLECTION")
    log("=" * 60)

    # System resources
    chrome_count = get_chrome_count()
    mem_usage = get_memory_usage()
    log(f"Chrome processes: {chrome_count}")
    log(f"Memory usage: {mem_usage}%")

    # Heartbeat status
    heartbeats = get_heartbeat_status()
    log(f"Active workers: {len(heartbeats)}")
    for hb in heartbeats:
        name, wtype, completed, failed, mins = hb
        log(f"  {name}: {completed} ok, {failed} fail, {mins} min ago")

    # Watchdog stats
    stale, resource_warn, healing = get_watchdog_stats()
    healing_actions = get_healing_actions()
    log(f"Watchdog (1h): stale={stale}, warnings={resource_warn}, healing={healing}")
    log(f"Healing actions (1h): {healing_actions}")

    # Check for issues
    issues = []
    if chrome_count > 500:
        issues.append(f"HIGH CHROME COUNT: {chrome_count}")
    if mem_usage > 90:
        issues.append(f"HIGH MEMORY: {mem_usage}%")
    for hb in heartbeats:
        name, wtype, completed, failed, mins = hb
        if mins > 5:
            issues.append(f"STALE HEARTBEAT: {name} ({mins} min)")
        if failed > 0 and completed == 0:
            issues.append(f"ALL FAILING: {name} ({failed} failures)")

    if issues:
        log("ISSUES DETECTED:")
        for issue in issues:
            log(f"  ⚠️  {issue}")
    else:
        log("✓ No issues detected")

    log("")

def main():
    log("=" * 60)
    log("1-HOUR MONITORING STARTED")
    log(f"Interval: {INTERVAL_SECONDS}s, Duration: {DURATION_SECONDS}s")
    log("=" * 60)

    start_time = time.time()
    iteration = 0

    while time.time() - start_time < DURATION_SECONDS:
        iteration += 1
        elapsed = int(time.time() - start_time)
        log(f"Iteration {iteration} (elapsed: {elapsed}s / {DURATION_SECONDS}s)")

        collect_metrics()

        # Sleep until next interval
        remaining = DURATION_SECONDS - (time.time() - start_time)
        if remaining > INTERVAL_SECONDS:
            time.sleep(INTERVAL_SECONDS)
        elif remaining > 0:
            time.sleep(remaining)

    log("=" * 60)
    log("1-HOUR MONITORING COMPLETE")
    log("=" * 60)

if __name__ == "__main__":
    main()
