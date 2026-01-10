#!/usr/bin/env python3
"""
SEO Worker Health Check & System Cleanup Script.

Checks the health of SEO workers, manages Chrome processes, and can restart stale workers.
Also provides comprehensive system cleanup for temp files, logs, caches, and data archival.
Can be run as a cron job or systemd timer.

Usage:
    python scripts/seo_health_check.py              # Check status
    python scripts/seo_health_check.py --restart    # Restart stale workers
    python scripts/seo_health_check.py --cleanup    # Force Chrome cleanup
    python scripts/seo_health_check.py --system-cleanup  # Full system cleanup
    python scripts/seo_health_check.py --report     # Disk usage report
    python scripts/seo_health_check.py --dry-run    # Preview cleanup without changes
"""

import argparse
import glob
import gzip
import os
import shutil
import subprocess
import sys
import signal
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database_manager import get_db_manager
from sqlalchemy import text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# System monitor for centralized error logging
try:
    from services.system_monitor import get_system_monitor, ErrorSeverity, ServiceName
    SYSTEM_MONITOR_AVAILABLE = True
except ImportError:
    SYSTEM_MONITOR_AVAILABLE = False

STALE_THRESHOLD_MINUTES = 5

# Chrome thresholds - calculated based on pool size
# Each browser spawns ~12 child processes
CHROME_PROCESSES_PER_BROWSER = 12
POOL_MIN_SESSIONS = int(os.getenv("BROWSER_POOL_MIN_SESSIONS", "18"))
POOL_MAX_SESSIONS = int(os.getenv("BROWSER_POOL_MAX_SESSIONS", "24"))

# Expected Chrome = pool size * 12, with 50% buffer for warmup/transitions
EXPECTED_CHROME_PROCESSES = POOL_MAX_SESSIONS * CHROME_PROCESSES_PER_BROWSER
MAX_CHROME_PROCESSES = int(EXPECTED_CHROME_PROCESSES * 1.5)  # 50% over expected = warning
CRITICAL_CHROME_PROCESSES = int(EXPECTED_CHROME_PROCESSES * 2.5)  # 150% over = critical

# ============================================================================
# SYSTEM CLEANUP CONFIGURATION
# ============================================================================

# User home directory
HOME_DIR = os.path.expanduser("~")

# Temp file cleanup settings
TEMP_MAX_AGE_DAYS = int(os.getenv("TEMP_CLEANUP_MAX_AGE_DAYS", "3"))
TEMP_DIRS = ["/tmp"]
TEMP_EXCLUDE_PATTERNS = ["playwright*", "systemd-*", "snap.*", ".X*", "ssh-*"]

# Log cleanup settings
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "7"))
LOG_DIRS = [
    "/opt/ai-seo/logs/integration",
    "/opt/ai-seo/logs/scrape-bot-ai",
    "/opt/ai-seo/logs/url-scrape-bot",
    os.path.join(HOME_DIR, "URL-Scrape-Bot/washdb-bot/logs"),
]
LOG_ARCHIVE_DIR = "/mnt/backup/log_archives"

# Cache cleanup settings
CACHE_DIRS = {
    "camoufox": os.path.join(HOME_DIR, ".cache/camoufox"),
    "playwright": os.path.join(HOME_DIR, ".cache/ms-playwright"),
    "pip": os.path.join(HOME_DIR, ".cache/pip"),
    "npm": os.path.join(HOME_DIR, ".npm/_cacache"),
}
CACHE_MAX_AGE_DAYS = 7
CACHE_MIN_SIZE_MB = 500  # Only clean if cache is larger than this

# Claude versions cleanup
CLAUDE_VERSIONS_DIR = os.path.join(HOME_DIR, ".local/share/claude/versions")
CLAUDE_KEEP_VERSIONS = 2

# Pycache cleanup directories
PYCACHE_SEARCH_DIRS = [
    HOME_DIR,
    "/opt/ai-seo",
]

# Systemd journal settings
JOURNAL_MAX_SIZE_GB = 1

# Data archival settings
ARCHIVE_SOURCE_DIR = "/opt/ai-seo/archives"
ARCHIVE_DEST_DIR = "/mnt/backup/archives"
ARCHIVE_AGE_DAYS = 90

# Cleanup log file
CLEANUP_LOG_FILE = "/opt/ai-seo/logs/system_cleanup.log"

# Trash cleanup settings
TRASH_DIR = os.path.join(HOME_DIR, ".local/share/Trash")

# Downloads cleanup settings
DOWNLOADS_DIR = os.path.join(HOME_DIR, "Downloads")

# Disk alerting thresholds
DISK_WARNING_PERCENT = int(os.getenv("DISK_WARNING_PERCENT", "85"))
DISK_CRITICAL_PERCENT = int(os.getenv("DISK_CRITICAL_PERCENT", "95"))
DISK_ALERT_MOUNTS = ["/", "/mnt/database", "/mnt/work", "/mnt/scratch", "/opt/ai-seo"]
DOWNLOADS_MAX_AGE_DAYS = 30

# Speech dispatcher log (can grow large)
SPEECH_DISPATCHER_LOG = os.path.join(HOME_DIR, ".cache/speech-dispatcher/log/speech-dispatcher.log")
SPEECH_DISPATCHER_MAX_SIZE_MB = 10

# Scratch tier cleanup
SCRATCH_DIR = "/mnt/scratch"
SCRATCH_MAX_AGE_DAYS = 7


def check_workers(db_manager=None):
    """Check status of all SEO workers."""
    db_manager = db_manager or get_db_manager()
    stale_threshold = datetime.now() - timedelta(minutes=STALE_THRESHOLD_MINUTES)

    with db_manager.get_session() as session:
        # Mark stale workers
        mark_stale = text("""
            UPDATE job_heartbeats
            SET status = 'stale'
            WHERE status = 'running'
              AND last_heartbeat < :threshold
            RETURNING worker_name
        """)
        result = session.execute(mark_stale, {'threshold': stale_threshold})
        stale_workers = [row[0] for row in result.fetchall()]
        session.commit()

        if stale_workers:
            print(f"Marked {len(stale_workers)} workers as stale: {stale_workers}")

            # Log stale worker error to system monitor
            if SYSTEM_MONITOR_AVAILABLE:
                try:
                    monitor = get_system_monitor()
                    monitor.log_error(
                        service=ServiceName.SEO_WORKER,
                        message=f"Stale workers detected: {', '.join(stale_workers)}",
                        severity=ErrorSeverity.WARNING,
                        error_code="STALE_WORKERS",
                        component="health_check",
                        context={
                            'stale_workers': stale_workers,
                            'stale_threshold_minutes': STALE_THRESHOLD_MINUTES,
                        }
                    )
                except Exception:
                    pass

        # Get all workers
        query = text("""
            SELECT worker_name, worker_type, status, last_heartbeat,
                   pid, companies_processed, jobs_completed, jobs_failed,
                   current_module, last_error
            FROM job_heartbeats
            WHERE worker_type = 'seo_orchestrator'
            ORDER BY last_heartbeat DESC
        """)
        result = session.execute(query)
        workers = result.fetchall()

        return workers, stale_workers


def restart_stale_workers():
    """Restart systemd services for stale workers."""
    print("Restarting seo-job-worker service...")
    try:
        subprocess.run(
            ['sudo', 'systemctl', 'restart', 'seo-job-worker'],
            check=True,
            capture_output=True,
            text=True
        )
        print("Service restarted successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to restart service: {e.stderr}")
        return False


def get_chrome_processes():
    """Get list of Chrome-related processes with their info."""
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True,
            check=True
        )

        chrome_procs = []
        for line in result.stdout.split('\n'):
            if any(x in line.lower() for x in ['chromium', 'chrome', 'chromedriver']):
                if 'grep' not in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            chrome_procs.append({
                                'pid': pid,
                                'user': parts[0],
                                'cpu': parts[2] if len(parts) > 2 else '0',
                                'mem': parts[3] if len(parts) > 3 else '0',
                                'cmd': ' '.join(parts[10:]) if len(parts) > 10 else ''
                            })
                        except (ValueError, IndexError):
                            pass

        return chrome_procs
    except subprocess.CalledProcessError:
        return []


def get_orphan_chrome_pids():
    """Find Chrome processes not owned by the SEO worker."""
    try:
        # Get SEO worker PID
        result = subprocess.run(
            ['pgrep', '-f', 'seo_job_orchestrator'],
            capture_output=True,
            text=True
        )
        worker_pids = set(result.stdout.strip().split('\n')) if result.stdout.strip() else set()

        # Get all Chrome PIDs and their parent PIDs
        chrome_procs = get_chrome_processes()
        orphan_pids = []

        for proc in chrome_procs:
            pid = proc['pid']
            # Check if this process's parent chain includes the worker
            try:
                # Get parent PID
                with open(f'/proc/{pid}/stat', 'r') as f:
                    stat = f.read().split()
                    ppid = stat[3] if len(stat) > 3 else None

                # If parent is init (1) or not the worker, it might be orphaned
                if ppid == '1':
                    orphan_pids.append(pid)
            except (FileNotFoundError, PermissionError, IndexError):
                pass

        return orphan_pids
    except Exception:
        return []


def get_stale_chrome_pids(max_age_seconds=3600):
    """
    Find Chrome processes that have been running longer than expected.

    Browser pool sessions should be recycled regularly. Chrome processes
    running for more than max_age_seconds are likely leaked from failed
    direct driver cleanups.

    Args:
        max_age_seconds: Maximum expected age of a Chrome process (default 1 hour)

    Returns:
        List of PIDs for stale Chrome processes
    """
    stale_pids = []
    try:
        # Get Chrome PIDs
        result = subprocess.run(
            ['pgrep', '-f', 'chromium'],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return []

        for pid_str in result.stdout.strip().split('\n'):
            if not pid_str:
                continue
            try:
                pid = int(pid_str)
                # Check process start time
                with open(f'/proc/{pid}/stat', 'r') as f:
                    stat = f.read().split()
                    # stat[21] is starttime in clock ticks since boot
                    starttime_ticks = int(stat[21])

                # Get system uptime
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = float(f.read().split()[0])

                # Calculate process age
                # Clock ticks per second (usually 100 on Linux)
                clk_tck = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
                starttime_seconds = starttime_ticks / clk_tck
                process_age_seconds = uptime_seconds - starttime_seconds

                if process_age_seconds > max_age_seconds:
                    stale_pids.append(pid)

            except (FileNotFoundError, PermissionError, ValueError, IndexError, KeyError):
                pass

        return stale_pids
    except Exception:
        return []


def get_excess_chrome_pids():
    """
    Find excess Chrome processes beyond expected pool capacity.

    Calculates how many Chrome processes should exist based on pool size,
    then identifies the oldest processes to kill.

    Returns:
        List of PIDs for excess Chrome processes (oldest ones)
    """
    chrome_procs = get_chrome_processes()
    current_count = len(chrome_procs)

    # Expected Chrome count based on pool size
    expected = EXPECTED_CHROME_PROCESSES

    if current_count <= expected:
        return []

    # Sort by PID (older processes have lower PIDs)
    chrome_procs.sort(key=lambda x: x['pid'])

    # Calculate excess with some headroom for transitions
    headroom = 50  # Allow 50 extra processes for warmup/recycling
    excess_count = max(0, current_count - expected - headroom)

    if excess_count == 0:
        return []

    # Return oldest PIDs (those to be killed)
    return [proc['pid'] for proc in chrome_procs[:excess_count]]


def cleanup_chrome_processes(force=False, quiet=False):
    """Clean up excess Chrome processes.

    This function performs multi-tier cleanup:
    1. Critical threshold: Kill ALL Chrome and restart worker
    2. Stale cleanup: Kill Chrome older than 1 hour (leaked from direct drivers)
    3. Orphan cleanup: Kill Chrome with parent=init (orphaned)
    4. Excess cleanup: Kill oldest Chrome beyond expected pool size

    Args:
        force: Kill all problematic Chrome regardless of count thresholds
        quiet: Suppress output

    Returns:
        Tuple of (chrome_count, killed_count, needs_restart)
    """
    chrome_procs = get_chrome_processes()
    chrome_count = len(chrome_procs)
    killed = 0
    needs_restart = False

    if not quiet:
        print(f"Chrome processes: {chrome_count} (expected: {EXPECTED_CHROME_PROCESSES}, warning: {MAX_CHROME_PROCESSES})")

    # Critical threshold - need full restart
    if chrome_count >= CRITICAL_CHROME_PROCESSES:
        if not quiet:
            print(f"[CRITICAL] {chrome_count} Chrome processes - exceeds critical threshold ({CRITICAL_CHROME_PROCESSES})")
            print("Killing all Chrome processes and restarting worker...")

        # Log critical error to system monitor
        if SYSTEM_MONITOR_AVAILABLE:
            try:
                monitor = get_system_monitor()
                monitor.log_error(
                    service=ServiceName.BROWSER_POOL,
                    message=f"Chrome process overflow: {chrome_count} processes (critical: {CRITICAL_CHROME_PROCESSES})",
                    severity=ErrorSeverity.CRITICAL,
                    error_code="CHROME_OVERFLOW",
                    component="health_check",
                    context={
                        'chrome_count': chrome_count,
                        'critical_threshold': CRITICAL_CHROME_PROCESSES,
                        'action': 'kill_all_chrome'
                    }
                )
            except Exception:
                pass

        # Kill all Chrome processes
        for proc in chrome_procs:
            try:
                os.kill(proc['pid'], signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, PermissionError):
                pass

        needs_restart = True
        if not quiet:
            print(f"Killed {killed} Chrome processes")

        return chrome_count, killed, needs_restart

    # === Tier 1: Always clean stale Chrome (older than 1 hour) ===
    # These are likely leaked from failed direct driver cleanups
    stale_pids = get_stale_chrome_pids(max_age_seconds=3600)
    if stale_pids:
        if not quiet:
            print(f"Found {len(stale_pids)} stale Chrome processes (>1 hour old)")

        for pid in stale_pids:
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, PermissionError):
                pass

        if not quiet:
            print(f"Killed {killed} stale Chrome processes")

    # === Tier 2: Clean orphaned Chrome (parent=init) ===
    orphan_pids = get_orphan_chrome_pids()
    if orphan_pids:
        # Filter out already-killed PIDs
        orphan_pids = [p for p in orphan_pids if p not in stale_pids]
        if orphan_pids:
            if not quiet:
                print(f"Found {len(orphan_pids)} orphaned Chrome processes")

            orphan_killed = 0
            for pid in orphan_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                    orphan_killed += 1
                except (ProcessLookupError, PermissionError):
                    pass

            if not quiet:
                print(f"Killed {orphan_killed} orphaned Chrome processes")

    # === Tier 3: Clean excess Chrome beyond pool capacity ===
    # Only if still above warning threshold or force mode
    remaining_count = chrome_count - killed
    if remaining_count > MAX_CHROME_PROCESSES or force:
        if not quiet and remaining_count > MAX_CHROME_PROCESSES:
            print(f"[WARNING] {remaining_count} Chrome processes remaining - exceeds threshold ({MAX_CHROME_PROCESSES})")

        excess_pids = get_excess_chrome_pids()
        if excess_pids:
            if not quiet:
                print(f"Found {len(excess_pids)} excess Chrome processes beyond pool capacity")

            excess_killed = 0
            for pid in excess_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                    excess_killed += 1
                except (ProcessLookupError, PermissionError):
                    pass

            if not quiet:
                print(f"Killed {excess_killed} excess Chrome processes (oldest)")

    if not quiet:
        final_count = len(get_chrome_processes())
        print(f"Cleanup complete: {chrome_count} -> {final_count} Chrome processes (killed {killed})")

    return chrome_count, killed, needs_restart


def coordinated_pool_cleanup(quiet=False):
    """
    Perform coordinated cleanup through the browser pool.

    This uses the pool's drain mode, session invalidation, and recovery mode
    for a clean, safe cleanup without disrupting active work.

    Returns:
        Dict with cleanup results, or None if pool unavailable
    """
    try:
        from seo_intelligence.drivers.browser_pool import get_browser_pool

        pool = get_browser_pool()

        if not quiet:
            print("Starting coordinated pool cleanup...")
            status = pool.get_pool_health_status()
            print(f"  Current state: {status['chrome_processes']} Chrome, "
                  f"{status['active_sessions']} sessions, {status['active_leases']} leases")

        # Run coordinated cleanup (drain → invalidate → staggered kill → recovery)
        result = pool.coordinated_cleanup(batch_size=15, batch_delay=5.0)

        if not quiet:
            print(f"  Drain completed: {result['drain_success']}")
            print(f"  Sessions invalidated: {result['sessions_invalidated']}")
            print(f"  Chrome killed: {result['chrome_killed']}")
            print(f"  Recovery mode: {'enabled' if result['recovery_entered'] else 'disabled'}")

        return result

    except ImportError:
        if not quiet:
            print("Browser pool not available - falling back to direct cleanup")
        return None
    except Exception as e:
        if not quiet:
            print(f"Coordinated cleanup failed: {e}")
        return None


def get_pool_status(quiet=False):
    """Get browser pool health status."""
    try:
        from seo_intelligence.drivers.browser_pool import get_browser_pool
        pool = get_browser_pool()
        return pool.get_pool_health_status()
    except Exception:
        return None


def check_xvfb():
    """Check if Xvfb is running and accepting connections."""
    try:
        result = subprocess.run(
            ['pgrep', 'Xvfb'],
            capture_output=True,
            text=True
        )
        if not result.stdout.strip():
            print("[WARNING] Xvfb not running!")
            return False

        # Check if display is accessible
        env = os.environ.copy()
        env['DISPLAY'] = ':99'
        result = subprocess.run(
            ['xdpyinfo'],
            capture_output=True,
            text=True,
            env=env,
            timeout=5
        )
        if 'unable to open display' in result.stderr or 'Maximum number of clients' in result.stderr:
            print("[WARNING] Xvfb display :99 not accessible - may need restart")
            return False

        return True
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"[WARNING] Xvfb check failed: {e}")
        return False


def restart_xvfb():
    """Restart Xvfb display server."""
    print("Restarting Xvfb...")
    try:
        # Kill existing
        subprocess.run(['pkill', '-9', 'Xvfb'], capture_output=True)
        time.sleep(2)

        # Start new
        subprocess.Popen(
            ['/usr/bin/Xvfb', ':99', '-screen', '0', '1920x1080x24'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(2)

        if check_xvfb():
            print("Xvfb restarted successfully")
            return True
        else:
            print("Xvfb restart may have failed")
            return False
    except Exception as e:
        print(f"Failed to restart Xvfb: {e}")
        return False


# ============================================================================
# SYSTEM CLEANUP FUNCTIONS
# ============================================================================

def log_cleanup_action(action: str, details: str = ""):
    """Log cleanup action to the cleanup log file."""
    try:
        os.makedirs(os.path.dirname(CLEANUP_LOG_FILE), exist_ok=True)
        with open(CLEANUP_LOG_FILE, "a") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {action}: {details}\n")
    except Exception:
        pass  # Don't fail on logging errors


def get_dir_size(path: str) -> int:
    """Get total size of a directory in bytes."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except (OSError, FileNotFoundError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def cleanup_temp_files(max_age_days: int = None, dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Clean temporary files older than max_age_days.

    Excludes playwright files (handled by separate cron job) and system directories.

    Returns:
        Dict with cleanup results: files_removed, bytes_freed, errors
    """
    max_age_days = max_age_days or TEMP_MAX_AGE_DAYS
    cutoff_time = time.time() - (max_age_days * 86400)

    results = {"files_removed": 0, "bytes_freed": 0, "errors": []}

    if not quiet:
        print(f"\n--- Temp File Cleanup (files older than {max_age_days} days) ---")

    for temp_dir in TEMP_DIRS:
        if not os.path.exists(temp_dir):
            continue

        try:
            for entry in os.scandir(temp_dir):
                # Skip excluded patterns
                should_skip = False
                for pattern in TEMP_EXCLUDE_PATTERNS:
                    if glob.fnmatch.fnmatch(entry.name, pattern):
                        should_skip = True
                        break

                if should_skip:
                    continue

                try:
                    # Check modification time
                    stat_info = entry.stat(follow_symlinks=False)
                    if stat_info.st_mtime < cutoff_time:
                        if entry.is_dir(follow_symlinks=False):
                            size = get_dir_size(entry.path)
                            if not dry_run:
                                shutil.rmtree(entry.path, ignore_errors=True)
                            if not quiet:
                                print(f"  {'[DRY RUN] Would remove' if dry_run else 'Removed'} dir: {entry.name} ({format_size(size)})")
                        else:
                            size = stat_info.st_size
                            if not dry_run:
                                os.remove(entry.path)
                            if not quiet:
                                print(f"  {'[DRY RUN] Would remove' if dry_run else 'Removed'} file: {entry.name} ({format_size(size)})")

                        results["files_removed"] += 1
                        results["bytes_freed"] += size

                except (PermissionError, OSError) as e:
                    results["errors"].append(f"{entry.path}: {e}")

        except (PermissionError, OSError) as e:
            results["errors"].append(f"{temp_dir}: {e}")

    if not quiet:
        print(f"  Total: {results['files_removed']} items, {format_size(results['bytes_freed'])} freed")

    log_cleanup_action("temp_cleanup", f"Removed {results['files_removed']} items, freed {format_size(results['bytes_freed'])}")

    return results


def cleanup_production_logs(retention_days: int = None, dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Rotate and archive production logs.

    Compresses logs older than retention_days and moves them to HDD backup.

    Returns:
        Dict with cleanup results: files_processed, bytes_archived, errors
    """
    retention_days = retention_days or LOG_RETENTION_DAYS
    cutoff_time = time.time() - (retention_days * 86400)

    results = {"files_processed": 0, "bytes_archived": 0, "errors": []}

    if not quiet:
        print(f"\n--- Log Rotation & Archival (logs older than {retention_days} days) ---")

    # Ensure archive directory exists
    if not dry_run:
        os.makedirs(LOG_ARCHIVE_DIR, exist_ok=True)

    for log_dir in LOG_DIRS:
        if not os.path.exists(log_dir):
            continue

        if not quiet:
            print(f"  Processing: {log_dir}")

        try:
            for entry in os.scandir(log_dir):
                if not entry.is_file():
                    continue

                # Only process log files
                if not entry.name.endswith('.log'):
                    continue

                try:
                    stat_info = entry.stat()

                    # Check if file is older than retention period
                    if stat_info.st_mtime < cutoff_time:
                        file_size = stat_info.st_size

                        # Create dated archive filename
                        file_date = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y%m%d")
                        archive_name = f"{entry.name}.{file_date}.gz"
                        archive_path = os.path.join(LOG_ARCHIVE_DIR, archive_name)

                        if not dry_run:
                            # Compress and move to archive
                            with open(entry.path, 'rb') as f_in:
                                with gzip.open(archive_path, 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)

                            # Remove original
                            os.remove(entry.path)

                        if not quiet:
                            print(f"    {'[DRY RUN] Would archive' if dry_run else 'Archived'}: {entry.name} ({format_size(file_size)})")

                        results["files_processed"] += 1
                        results["bytes_archived"] += file_size

                    # For current logs, check if they're too large (>100MB) and rotate
                    elif stat_info.st_size > 100 * 1024 * 1024:
                        if not dry_run:
                            # Rotate: move to .1, compress
                            rotated_path = entry.path + ".1"
                            shutil.move(entry.path, rotated_path)

                            # Compress the rotated file
                            with open(rotated_path, 'rb') as f_in:
                                with gzip.open(rotated_path + ".gz", 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)
                            os.remove(rotated_path)

                            # Create empty new log file
                            open(entry.path, 'a').close()

                        if not quiet:
                            print(f"    {'[DRY RUN] Would rotate' if dry_run else 'Rotated'}: {entry.name} ({format_size(stat_info.st_size)})")

                        results["files_processed"] += 1

                except (PermissionError, OSError) as e:
                    results["errors"].append(f"{entry.path}: {e}")

        except (PermissionError, OSError) as e:
            results["errors"].append(f"{log_dir}: {e}")

    if not quiet:
        print(f"  Total: {results['files_processed']} files, {format_size(results['bytes_archived'])} archived")

    log_cleanup_action("log_cleanup", f"Processed {results['files_processed']} files, archived {format_size(results['bytes_archived'])}")

    return results


def cleanup_caches(dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Clean browser and package caches.

    Only cleans caches larger than CACHE_MIN_SIZE_MB and files older than CACHE_MAX_AGE_DAYS.

    Returns:
        Dict with cleanup results per cache type
    """
    results = {"total_freed": 0, "caches_cleaned": {}}

    if not quiet:
        print(f"\n--- Cache Cleanup (caches > {CACHE_MIN_SIZE_MB}MB, files > {CACHE_MAX_AGE_DAYS} days) ---")

    cutoff_time = time.time() - (CACHE_MAX_AGE_DAYS * 86400)
    min_size_bytes = CACHE_MIN_SIZE_MB * 1024 * 1024

    for cache_name, cache_path in CACHE_DIRS.items():
        if not os.path.exists(cache_path):
            if not quiet:
                print(f"  {cache_name}: not found, skipping")
            continue

        cache_size = get_dir_size(cache_path)

        if cache_size < min_size_bytes:
            if not quiet:
                print(f"  {cache_name}: {format_size(cache_size)} (below threshold, skipping)")
            continue

        if not quiet:
            print(f"  {cache_name}: {format_size(cache_size)}")

        freed = 0

        # For browser caches, we can be aggressive - remove old cached data
        if cache_name in ["camoufox", "playwright"]:
            try:
                # Find and remove old cache files
                for root, dirs, files in os.walk(cache_path):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            stat_info = os.stat(fp)
                            if stat_info.st_mtime < cutoff_time:
                                size = stat_info.st_size
                                if not dry_run:
                                    os.remove(fp)
                                freed += size
                        except (OSError, FileNotFoundError):
                            pass

            except (PermissionError, OSError):
                pass

        # For pip cache, use pip's cache purge
        elif cache_name == "pip":
            try:
                if not dry_run:
                    subprocess.run(
                        [sys.executable, "-m", "pip", "cache", "purge"],
                        capture_output=True,
                        timeout=60
                    )
                freed = cache_size  # Approximate
            except Exception:
                pass

        # For npm cache, use npm cache clean
        elif cache_name == "npm":
            try:
                if not dry_run:
                    subprocess.run(
                        ["npm", "cache", "clean", "--force"],
                        capture_output=True,
                        timeout=60
                    )
                freed = cache_size  # Approximate
            except Exception:
                pass

        if freed > 0:
            if not quiet:
                print(f"    {'[DRY RUN] Would free' if dry_run else 'Freed'}: {format_size(freed)}")
            results["total_freed"] += freed
            results["caches_cleaned"][cache_name] = freed

    if not quiet:
        print(f"  Total freed: {format_size(results['total_freed'])}")

    log_cleanup_action("cache_cleanup", f"Freed {format_size(results['total_freed'])}")

    return results


def cleanup_old_claude_versions(keep_latest: int = None, dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Remove old Claude Code versions, keeping only the latest N versions.

    Returns:
        Dict with cleanup results: versions_removed, bytes_freed
    """
    keep_latest = keep_latest or CLAUDE_KEEP_VERSIONS
    results = {"versions_removed": 0, "bytes_freed": 0}

    if not quiet:
        print(f"\n--- Claude Versions Cleanup (keeping latest {keep_latest}) ---")

    if not os.path.exists(CLAUDE_VERSIONS_DIR):
        if not quiet:
            print(f"  Claude versions directory not found: {CLAUDE_VERSIONS_DIR}")
        return results

    try:
        # List all version directories and sort by modification time (newest first)
        versions = []
        for entry in os.scandir(CLAUDE_VERSIONS_DIR):
            if entry.is_dir():
                try:
                    stat_info = entry.stat()
                    versions.append((entry.path, entry.name, stat_info.st_mtime))
                except OSError:
                    pass

        # Sort by mtime, newest first
        versions.sort(key=lambda x: x[2], reverse=True)

        if not quiet:
            print(f"  Found {len(versions)} versions")

        # Remove all but the latest N
        for path, name, _ in versions[keep_latest:]:
            size = get_dir_size(path)

            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)

            if not quiet:
                print(f"    {'[DRY RUN] Would remove' if dry_run else 'Removed'}: {name} ({format_size(size)})")

            results["versions_removed"] += 1
            results["bytes_freed"] += size

    except (PermissionError, OSError) as e:
        if not quiet:
            print(f"  Error: {e}")

    if not quiet:
        print(f"  Total: {results['versions_removed']} versions, {format_size(results['bytes_freed'])} freed")

    log_cleanup_action("claude_cleanup", f"Removed {results['versions_removed']} versions, freed {format_size(results['bytes_freed'])}")

    return results


def cleanup_pycache(dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Remove __pycache__ directories from project folders.

    Returns:
        Dict with cleanup results: dirs_removed, bytes_freed
    """
    results = {"dirs_removed": 0, "bytes_freed": 0}

    if not quiet:
        print(f"\n--- Python Cache Cleanup (__pycache__ directories) ---")

    for search_dir in PYCACHE_SEARCH_DIRS:
        if not os.path.exists(search_dir):
            continue

        try:
            # Use find command for efficiency
            result = subprocess.run(
                ["find", search_dir, "-type", "d", "-name", "__pycache__", "-maxdepth", "10"],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                for cache_dir in result.stdout.strip().split('\n'):
                    if not cache_dir:
                        continue

                    try:
                        size = get_dir_size(cache_dir)

                        if not dry_run:
                            shutil.rmtree(cache_dir, ignore_errors=True)

                        results["dirs_removed"] += 1
                        results["bytes_freed"] += size

                    except (PermissionError, OSError):
                        pass

        except (subprocess.TimeoutExpired, Exception):
            pass

    if not quiet:
        print(f"  Total: {results['dirs_removed']} directories, {format_size(results['bytes_freed'])} freed")

    log_cleanup_action("pycache_cleanup", f"Removed {results['dirs_removed']} dirs, freed {format_size(results['bytes_freed'])}")

    return results


def limit_systemd_journal(max_size_gb: int = None, dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Vacuum systemd journal to limit its size.

    Returns:
        Dict with cleanup results
    """
    max_size_gb = max_size_gb or JOURNAL_MAX_SIZE_GB
    results = {"success": False, "message": ""}

    if not quiet:
        print(f"\n--- Systemd Journal Cleanup (limiting to {max_size_gb}GB) ---")

    try:
        # Get current journal size
        result = subprocess.run(
            ["journalctl", "--disk-usage"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            if not quiet:
                print(f"  Current: {result.stdout.strip()}")

        if not dry_run:
            # Vacuum the journal
            result = subprocess.run(
                ["sudo", "journalctl", f"--vacuum-size={max_size_gb}G"],
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                results["success"] = True
                results["message"] = result.stdout.strip()
                if not quiet:
                    print(f"  Result: {result.stdout.strip()}")
            else:
                results["message"] = result.stderr.strip()
                if not quiet:
                    print(f"  Error: {result.stderr.strip()}")
        else:
            if not quiet:
                print(f"  [DRY RUN] Would vacuum to {max_size_gb}GB")
            results["success"] = True

    except subprocess.TimeoutExpired:
        results["message"] = "Timeout during journal vacuum"
        if not quiet:
            print(f"  Error: Timeout")
    except Exception as e:
        results["message"] = str(e)
        if not quiet:
            print(f"  Error: {e}")

    log_cleanup_action("journal_cleanup", results["message"])

    return results


def archive_old_data(age_days: int = None, dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Archive old data from NVMe to HDD backup.

    Moves files older than age_days from ARCHIVE_SOURCE_DIR to ARCHIVE_DEST_DIR.

    Returns:
        Dict with archive results
    """
    age_days = age_days or ARCHIVE_AGE_DAYS
    cutoff_time = time.time() - (age_days * 86400)

    results = {"files_archived": 0, "bytes_moved": 0, "errors": []}

    if not quiet:
        print(f"\n--- Data Archival (files older than {age_days} days) ---")
        print(f"  Source: {ARCHIVE_SOURCE_DIR}")
        print(f"  Destination: {ARCHIVE_DEST_DIR}")

    if not os.path.exists(ARCHIVE_SOURCE_DIR):
        if not quiet:
            print(f"  Source directory not found")
        return results

    # Ensure destination exists
    if not dry_run:
        os.makedirs(ARCHIVE_DEST_DIR, exist_ok=True)

    try:
        for root, dirs, files in os.walk(ARCHIVE_SOURCE_DIR):
            for f in files:
                fp = os.path.join(root, f)

                try:
                    stat_info = os.stat(fp)

                    if stat_info.st_mtime < cutoff_time:
                        # Calculate relative path for destination
                        rel_path = os.path.relpath(fp, ARCHIVE_SOURCE_DIR)
                        dest_path = os.path.join(ARCHIVE_DEST_DIR, rel_path)

                        if not dry_run:
                            # Ensure destination directory exists
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                            # Move file (copy then delete for cross-filesystem)
                            shutil.copy2(fp, dest_path)
                            os.remove(fp)

                        results["files_archived"] += 1
                        results["bytes_moved"] += stat_info.st_size

                except (PermissionError, OSError) as e:
                    results["errors"].append(f"{fp}: {e}")

    except (PermissionError, OSError) as e:
        results["errors"].append(f"Walk error: {e}")

    if not quiet:
        action = "[DRY RUN] Would archive" if dry_run else "Archived"
        print(f"  {action}: {results['files_archived']} files, {format_size(results['bytes_moved'])}")

    log_cleanup_action("data_archival", f"Archived {results['files_archived']} files, {format_size(results['bytes_moved'])}")

    return results


def cleanup_trash(dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Empty the user's trash directory.

    Returns:
        Dict with cleanup results: items_removed, bytes_freed
    """
    results = {"items_removed": 0, "bytes_freed": 0}

    if not quiet:
        print(f"\n--- Trash Cleanup ---")

    if not os.path.exists(TRASH_DIR):
        if not quiet:
            print(f"  Trash directory not found: {TRASH_DIR}")
        return results

    # Check subdirectories: files, info, expunged
    trash_subdirs = ["files", "info", "expunged"]

    for subdir in trash_subdirs:
        subdir_path = os.path.join(TRASH_DIR, subdir)
        if not os.path.exists(subdir_path):
            continue

        try:
            for entry in os.scandir(subdir_path):
                try:
                    if entry.is_dir(follow_symlinks=False):
                        size = get_dir_size(entry.path)
                        if not dry_run:
                            shutil.rmtree(entry.path, ignore_errors=True)
                    else:
                        size = entry.stat(follow_symlinks=False).st_size
                        if not dry_run:
                            os.remove(entry.path)

                    results["items_removed"] += 1
                    results["bytes_freed"] += size

                except (PermissionError, OSError):
                    pass

        except (PermissionError, OSError):
            pass

    if not quiet:
        action = "[DRY RUN] Would free" if dry_run else "Freed"
        print(f"  {action}: {results['items_removed']} items, {format_size(results['bytes_freed'])}")

    log_cleanup_action("trash_cleanup", f"Removed {results['items_removed']} items, freed {format_size(results['bytes_freed'])}")

    return results


def cleanup_downloads(max_age_days: int = None, dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Clean old files from Downloads directory.

    Only removes files older than max_age_days. Does not touch directories.

    Returns:
        Dict with cleanup results: files_removed, bytes_freed
    """
    max_age_days = max_age_days or DOWNLOADS_MAX_AGE_DAYS
    cutoff_time = time.time() - (max_age_days * 86400)

    results = {"files_removed": 0, "bytes_freed": 0}

    if not quiet:
        print(f"\n--- Downloads Cleanup (files older than {max_age_days} days) ---")

    # Downloads is now a symlink to /mnt/work/downloads
    downloads_path = DOWNLOADS_DIR
    if os.path.islink(downloads_path):
        downloads_path = os.path.realpath(downloads_path)

    if not os.path.exists(downloads_path):
        if not quiet:
            print(f"  Downloads directory not found: {downloads_path}")
        return results

    try:
        for entry in os.scandir(downloads_path):
            if not entry.is_file(follow_symlinks=False):
                continue

            try:
                stat_info = entry.stat(follow_symlinks=False)
                if stat_info.st_mtime < cutoff_time:
                    size = stat_info.st_size

                    if not dry_run:
                        os.remove(entry.path)

                    if not quiet:
                        print(f"  {'[DRY RUN] Would remove' if dry_run else 'Removed'}: {entry.name} ({format_size(size)})")

                    results["files_removed"] += 1
                    results["bytes_freed"] += size

            except (PermissionError, OSError):
                pass

    except (PermissionError, OSError) as e:
        if not quiet:
            print(f"  Error: {e}")

    if not quiet:
        print(f"  Total: {results['files_removed']} files, {format_size(results['bytes_freed'])} freed")

    log_cleanup_action("downloads_cleanup", f"Removed {results['files_removed']} files, freed {format_size(results['bytes_freed'])}")

    return results


def cleanup_speech_dispatcher(dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Truncate the speech-dispatcher log if it exceeds the max size.

    Returns:
        Dict with cleanup results
    """
    results = {"truncated": False, "bytes_freed": 0}

    if not quiet:
        print(f"\n--- Speech Dispatcher Log Cleanup ---")

    if not os.path.exists(SPEECH_DISPATCHER_LOG):
        if not quiet:
            print(f"  Log file not found (OK)")
        return results

    try:
        stat_info = os.stat(SPEECH_DISPATCHER_LOG)
        size = stat_info.st_size
        max_size = SPEECH_DISPATCHER_MAX_SIZE_MB * 1024 * 1024

        if size > max_size:
            if not dry_run:
                # Truncate the file
                with open(SPEECH_DISPATCHER_LOG, 'w') as f:
                    f.write(f"# Log truncated by cleanup at {datetime.now()}\n")

            results["truncated"] = True
            results["bytes_freed"] = size

            if not quiet:
                action = "[DRY RUN] Would truncate" if dry_run else "Truncated"
                print(f"  {action}: {format_size(size)}")
        else:
            if not quiet:
                print(f"  Size OK: {format_size(size)} (max: {SPEECH_DISPATCHER_MAX_SIZE_MB}MB)")

    except (PermissionError, OSError) as e:
        if not quiet:
            print(f"  Error: {e}")

    return results


def cleanup_scratch_tier(max_age_days: int = None, dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Clean old files from the scratch tier.

    The scratch tier is designed for ephemeral data. Files older than
    max_age_days are removed.

    Returns:
        Dict with cleanup results
    """
    max_age_days = max_age_days or SCRATCH_MAX_AGE_DAYS
    cutoff_time = time.time() - (max_age_days * 86400)

    results = {"files_removed": 0, "bytes_freed": 0, "dirs_cleaned": []}

    if not quiet:
        print(f"\n--- Scratch Tier Cleanup (files older than {max_age_days} days) ---")

    if not os.path.exists(SCRATCH_DIR):
        if not quiet:
            print(f"  Scratch directory not found: {SCRATCH_DIR}")
        return results

    # Clean washdb-bot scratch subdirectories
    scratch_subdirs = [
        os.path.join(SCRATCH_DIR, "washdb-bot", "temp"),
        os.path.join(SCRATCH_DIR, "washdb-bot", "render"),
        os.path.join(SCRATCH_DIR, "washdb-bot", "serp_sessions"),
    ]

    for subdir in scratch_subdirs:
        if not os.path.exists(subdir):
            continue

        dir_freed = 0
        dir_count = 0

        try:
            for root, dirs, files in os.walk(subdir):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        stat_info = os.stat(fp)
                        if stat_info.st_mtime < cutoff_time:
                            size = stat_info.st_size
                            if not dry_run:
                                os.remove(fp)
                            dir_freed += size
                            dir_count += 1
                    except (PermissionError, OSError):
                        pass

        except (PermissionError, OSError):
            pass

        if dir_count > 0:
            results["files_removed"] += dir_count
            results["bytes_freed"] += dir_freed
            results["dirs_cleaned"].append(subdir)

            if not quiet:
                action = "[DRY RUN] Would clean" if dry_run else "Cleaned"
                print(f"  {action} {subdir}: {dir_count} files, {format_size(dir_freed)}")

    if not quiet:
        print(f"  Total: {results['files_removed']} files, {format_size(results['bytes_freed'])} freed")

    log_cleanup_action("scratch_cleanup", f"Removed {results['files_removed']} files, freed {format_size(results['bytes_freed'])}")

    return results


def generate_disk_report(quiet: bool = False) -> Dict:
    """
    Generate a comprehensive disk usage report.

    Returns:
        Dict with disk usage information
    """
    report = {
        "timestamp": datetime.now().isoformat(),
        "filesystems": [],
        "cleanup_candidates": [],
    }

    if not quiet:
        print("\n" + "=" * 60)
        print("DISK USAGE REPORT")
        print("=" * 60)

    # Get filesystem usage
    try:
        result = subprocess.run(["df", "-h"], capture_output=True, text=True)
        if result.returncode == 0:
            if not quiet:
                print("\n--- Filesystem Usage ---")
                print(result.stdout)

            for line in result.stdout.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 6:
                    report["filesystems"].append({
                        "device": parts[0],
                        "size": parts[1],
                        "used": parts[2],
                        "avail": parts[3],
                        "use_percent": parts[4],
                        "mount": parts[5],
                    })
    except Exception:
        pass

    # Check cleanup candidates
    cleanup_checks = [
        ("/tmp", "Temp files"),
        (os.path.join(HOME_DIR, ".cache"), "User cache"),
        ("/var/log/journal", "Systemd journal"),
        (CLAUDE_VERSIONS_DIR, "Claude versions"),
        ("/opt/ai-seo/logs", "Application logs"),
    ]

    if not quiet:
        print("--- Cleanup Candidates ---")

    for path, name in cleanup_checks:
        if os.path.exists(path):
            size = get_dir_size(path)
            if not quiet:
                print(f"  {name}: {format_size(size)} ({path})")
            report["cleanup_candidates"].append({
                "name": name,
                "path": path,
                "size": size,
                "size_formatted": format_size(size),
            })

    if not quiet:
        print("\n" + "=" * 60)

    return report


def check_disk_alerts(quiet: bool = False, log_to_db: bool = True) -> Dict:
    """
    Check disk usage against thresholds and generate alerts.

    Args:
        quiet: Suppress normal output
        log_to_db: Log alerts to task_logs table

    Returns:
        Dict with alert status and details
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "status": "ok",
        "warnings": [],
        "criticals": [],
        "filesystems": [],
    }

    if not quiet:
        print("\n" + "=" * 60)
        print("DISK USAGE ALERT CHECK")
        print(f"Warning threshold: {DISK_WARNING_PERCENT}%")
        print(f"Critical threshold: {DISK_CRITICAL_PERCENT}%")
        print("=" * 60)

    try:
        df_result = subprocess.run(["df", "-h"], capture_output=True, text=True)
        if df_result.returncode != 0:
            result["status"] = "error"
            result["error"] = "Failed to run df command"
            return result

        for line in df_result.stdout.strip().split('\n')[1:]:
            parts = line.split()
            if len(parts) >= 6:
                mount = parts[5]
                use_str = parts[4].rstrip('%')

                # Only check configured mount points
                if mount not in DISK_ALERT_MOUNTS:
                    continue

                try:
                    use_percent = int(use_str)
                except ValueError:
                    continue

                fs_info = {
                    "mount": mount,
                    "device": parts[0],
                    "size": parts[1],
                    "used": parts[2],
                    "avail": parts[3],
                    "use_percent": use_percent,
                }
                result["filesystems"].append(fs_info)

                if use_percent >= DISK_CRITICAL_PERCENT:
                    result["criticals"].append(fs_info)
                    result["status"] = "critical"
                    if not quiet:
                        print(f"[CRITICAL] {mount}: {use_percent}% used ({parts[2]} of {parts[1]})")
                elif use_percent >= DISK_WARNING_PERCENT:
                    result["warnings"].append(fs_info)
                    if result["status"] == "ok":
                        result["status"] = "warning"
                    if not quiet:
                        print(f"[WARNING] {mount}: {use_percent}% used ({parts[2]} of {parts[1]})")
                else:
                    if not quiet:
                        print(f"[OK] {mount}: {use_percent}% used")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        if not quiet:
            print(f"[ERROR] Failed to check disk usage: {e}")

    # Log to database if there are alerts
    if log_to_db and (result["warnings"] or result["criticals"]):
        try:
            db = get_db_manager()
            with db.get_session() as session:
                alert_data = {
                    "status": result["status"],
                    "warnings": [f"{w['mount']}: {w['use_percent']}%" for w in result["warnings"]],
                    "criticals": [f"{c['mount']}: {c['use_percent']}%" for c in result["criticals"]],
                }

                session.execute(
                    text("""
                        INSERT INTO task_logs (task_name, task_type, status, started_at, completed_at, message, metadata)
                        VALUES (:name, :type, :status, NOW(), NOW(), :message, :metadata::jsonb)
                    """),
                    {
                        "name": "disk_alert_check",
                        "type": "monitoring",
                        "status": "warning" if result["status"] == "warning" else "error",
                        "message": f"Disk usage alert: {len(result['criticals'])} critical, {len(result['warnings'])} warning",
                        "metadata": str(alert_data).replace("'", '"'),
                    }
                )
                session.commit()
                if not quiet:
                    print("\nAlert logged to task_logs")
        except Exception as e:
            if not quiet:
                print(f"[WARNING] Failed to log alert to database: {e}")

    # Log to system monitor if available
    if SYSTEM_MONITOR_AVAILABLE and result["criticals"]:
        try:
            monitor = get_system_monitor()
            for critical in result["criticals"]:
                monitor.log_error(
                    service=ServiceName.SEO_JOB_WORKER,
                    error_type="disk_critical",
                    message=f"Critical disk usage on {critical['mount']}: {critical['use_percent']}%",
                    severity=ErrorSeverity.CRITICAL,
                    metadata=critical,
                )
        except Exception:
            pass

    if not quiet:
        print("\n" + "=" * 60)
        if result["status"] == "ok":
            print("All monitored filesystems within normal limits")
        elif result["status"] == "warning":
            print(f"WARNING: {len(result['warnings'])} filesystem(s) above {DISK_WARNING_PERCENT}%")
        else:
            print(f"CRITICAL: {len(result['criticals'])} filesystem(s) above {DISK_CRITICAL_PERCENT}%")
        print("=" * 60)

    return result


def run_system_cleanup(dry_run: bool = False, quiet: bool = False) -> Dict:
    """
    Run all system cleanup tasks.

    Returns:
        Dict with combined cleanup results
    """
    if not quiet:
        print("\n" + "=" * 60)
        print(f"SYSTEM CLEANUP {'(DRY RUN)' if dry_run else ''}")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

    results = {
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
        "trash_cleanup": None,
        "temp_cleanup": None,
        "downloads_cleanup": None,
        "log_cleanup": None,
        "cache_cleanup": None,
        "claude_cleanup": None,
        "pycache_cleanup": None,
        "speech_dispatcher_cleanup": None,
        "scratch_cleanup": None,
        "journal_cleanup": None,
        "data_archival": None,
        "total_freed": 0,
    }

    # Run all cleanup tasks
    results["trash_cleanup"] = cleanup_trash(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["trash_cleanup"].get("bytes_freed", 0)

    results["temp_cleanup"] = cleanup_temp_files(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["temp_cleanup"].get("bytes_freed", 0)

    results["downloads_cleanup"] = cleanup_downloads(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["downloads_cleanup"].get("bytes_freed", 0)

    results["log_cleanup"] = cleanup_production_logs(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["log_cleanup"].get("bytes_archived", 0)

    results["cache_cleanup"] = cleanup_caches(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["cache_cleanup"].get("total_freed", 0)

    results["claude_cleanup"] = cleanup_old_claude_versions(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["claude_cleanup"].get("bytes_freed", 0)

    results["pycache_cleanup"] = cleanup_pycache(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["pycache_cleanup"].get("bytes_freed", 0)

    results["speech_dispatcher_cleanup"] = cleanup_speech_dispatcher(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["speech_dispatcher_cleanup"].get("bytes_freed", 0)

    results["scratch_cleanup"] = cleanup_scratch_tier(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["scratch_cleanup"].get("bytes_freed", 0)

    results["journal_cleanup"] = limit_systemd_journal(dry_run=dry_run, quiet=quiet)

    results["data_archival"] = archive_old_data(dry_run=dry_run, quiet=quiet)
    results["total_freed"] += results["data_archival"].get("bytes_moved", 0)

    if not quiet:
        print("\n" + "=" * 60)
        print("CLEANUP SUMMARY")
        print("=" * 60)
        print(f"  Total space freed/archived: {format_size(results['total_freed'])}")
        print(f"  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

    log_cleanup_action("system_cleanup_complete", f"Total freed: {format_size(results['total_freed'])}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description='SEO Worker Health Check & System Cleanup',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                      # Check worker and Chrome status
  %(prog)s --cleanup            # Force Chrome process cleanup
  %(prog)s --system-cleanup     # Full system cleanup (temp, logs, caches, archives)
  %(prog)s --system-cleanup --dry-run  # Preview cleanup without changes
  %(prog)s --report             # Generate disk usage report
  %(prog)s --temp-cleanup       # Clean only temp files
  %(prog)s --log-cleanup        # Clean only logs
        """
    )

    # Original arguments
    parser.add_argument('--restart', action='store_true', help='Restart stale workers')
    parser.add_argument('--cleanup', action='store_true', help='Force Chrome process cleanup')
    parser.add_argument('--coordinated', action='store_true', help='Use coordinated pool cleanup (drain, invalidate, recover)')
    parser.add_argument('--quiet', '-q', action='store_true', help='Only output on issues')

    # New system cleanup arguments
    parser.add_argument('--system-cleanup', action='store_true', help='Run full system cleanup (temp, logs, caches, archives)')
    parser.add_argument('--trash-cleanup', action='store_true', help='Empty user trash only')
    parser.add_argument('--temp-cleanup', action='store_true', help='Clean temp files only')
    parser.add_argument('--downloads-cleanup', action='store_true', help='Clean old downloads only')
    parser.add_argument('--log-cleanup', action='store_true', help='Rotate and archive logs only')
    parser.add_argument('--cache-cleanup', action='store_true', help='Clean browser/package caches only')
    parser.add_argument('--scratch-cleanup', action='store_true', help='Clean scratch tier data')
    parser.add_argument('--archive-data', action='store_true', help='Archive old data to HDD')
    parser.add_argument('--dry-run', action='store_true', help='Preview cleanup without making changes')
    parser.add_argument('--report', action='store_true', help='Generate disk usage report')
    parser.add_argument('--disk-alert', action='store_true', help='Check disk usage against thresholds and alert')

    args = parser.parse_args()

    # Handle system cleanup modes first
    if args.report:
        generate_disk_report(quiet=args.quiet)
        return 0

    if args.disk_alert:
        result = check_disk_alerts(quiet=args.quiet)
        # Return non-zero exit code if there are alerts
        if result["status"] == "critical":
            return 2
        elif result["status"] == "warning":
            return 1
        return 0

    if args.system_cleanup:
        run_system_cleanup(dry_run=args.dry_run, quiet=args.quiet)
        return 0

    if args.trash_cleanup:
        cleanup_trash(dry_run=args.dry_run, quiet=args.quiet)
        return 0

    if args.temp_cleanup:
        cleanup_temp_files(dry_run=args.dry_run, quiet=args.quiet)
        return 0

    if args.downloads_cleanup:
        cleanup_downloads(dry_run=args.dry_run, quiet=args.quiet)
        return 0

    if args.log_cleanup:
        cleanup_production_logs(dry_run=args.dry_run, quiet=args.quiet)
        return 0

    if args.cache_cleanup:
        cleanup_caches(dry_run=args.dry_run, quiet=args.quiet)
        return 0

    if args.scratch_cleanup:
        cleanup_scratch_tier(dry_run=args.dry_run, quiet=args.quiet)
        return 0

    if args.archive_data:
        archive_old_data(dry_run=args.dry_run, quiet=args.quiet)
        return 0

    # Original health check logic follows...

    has_issues = False
    needs_restart = False
    used_coordinated = False
    chrome_needs_restart = False

    # 1. Check Chrome processes
    chrome_procs = get_chrome_processes()
    chrome_count = len(chrome_procs)

    if not args.quiet:
        print(f"Chrome processes: {chrome_count}")

    # 2. Use coordinated cleanup if requested or if Chrome count is high
    if args.coordinated or chrome_count >= MAX_CHROME_PROCESSES:
        if not args.quiet:
            print("\nUsing coordinated pool cleanup...")

        result = coordinated_pool_cleanup(quiet=args.quiet)

        if result:
            used_coordinated = True
            killed = result.get('chrome_killed', 0)
            if chrome_count >= CRITICAL_CHROME_PROCESSES:
                needs_restart = True
                has_issues = True
        else:
            # Fallback to direct cleanup if pool not available
            if not args.quiet:
                print("Falling back to direct cleanup...")
            _, killed, chrome_needs_restart = cleanup_chrome_processes(
                force=True,
                quiet=args.quiet
            )
            if chrome_needs_restart:
                needs_restart = True
                has_issues = True
    elif args.cleanup:
        # Direct cleanup requested
        _, killed, chrome_needs_restart = cleanup_chrome_processes(
            force=True,
            quiet=args.quiet
        )
        if chrome_needs_restart:
            needs_restart = True
            has_issues = True
    else:
        killed = 0
        # Just check thresholds
        if chrome_count >= CRITICAL_CHROME_PROCESSES:
            print(f"[CRITICAL] {chrome_count} Chrome processes - exceeds critical threshold")
            has_issues = True
            needs_restart = True
        elif chrome_count >= MAX_CHROME_PROCESSES:
            print(f"[WARNING] {chrome_count} Chrome processes - exceeds threshold")
            has_issues = True

    # 2. Check Xvfb display
    if not args.quiet:
        print("\nChecking Xvfb display...")
    xvfb_ok = check_xvfb()
    if not xvfb_ok:
        has_issues = True
        if args.restart or chrome_needs_restart:
            restart_xvfb()

    # 3. Check SEO workers
    if not args.quiet:
        print("\nChecking SEO workers...")
    workers, stale_workers = check_workers()

    if not workers:
        if not args.quiet:
            print("No SEO workers registered")
    else:
        running_count = 0

        for w in workers:
            worker_name, worker_type, status, last_heartbeat, pid, companies, jobs_ok, jobs_fail, current_module, last_error = w

            if status == 'running':
                running_count += 1
                if not args.quiet:
                    seconds_ago = (datetime.now() - last_heartbeat).total_seconds() if last_heartbeat else 999
                    print(f"[OK] {worker_name}: running (heartbeat {seconds_ago:.0f}s ago)")
                    print(f"     Companies: {companies}, Jobs: {jobs_ok} ok / {jobs_fail} failed")
                    if current_module:
                        print(f"     Current: {current_module}")
            elif status == 'stale':
                has_issues = True
                print(f"[STALE] {worker_name}: no heartbeat for {STALE_THRESHOLD_MINUTES}+ minutes")
                if last_error:
                    print(f"        Last error: {last_error[:80]}...")
            elif status == 'stopped':
                if not args.quiet:
                    print(f"[STOPPED] {worker_name}")
            elif status == 'failed':
                has_issues = True
                print(f"[FAILED] {worker_name}")
                if last_error:
                    print(f"         Last error: {last_error[:80]}...")

        if running_count == 0 and not stale_workers:
            print("\nNo running SEO workers!")
            has_issues = True

    # 4. Restart if needed
    if needs_restart or (stale_workers and args.restart):
        reason = []
        if needs_restart:
            reason.append("Chrome process overflow")
        if stale_workers:
            reason.append(f"stale workers: {stale_workers}")
        print(f"\nRestarting due to: {', '.join(reason)}")
        restart_stale_workers()

    # Summary
    if not args.quiet:
        print(f"\n--- Summary ---")
        print(f"Chrome processes: {chrome_count} (killed {killed})")
        print(f"Xvfb: {'OK' if xvfb_ok else 'ISSUE'}")

        # Show pool status if available
        pool_status = get_pool_status(quiet=True)
        if pool_status:
            print(f"Pool: {'draining' if pool_status['drain_mode'] else 'recovering' if pool_status['recovery_mode'] else 'healthy'}")
            if pool_status['recovery_mode']:
                print(f"  Recovery progress: {pool_status['recovery_progress']}")

        if used_coordinated:
            print(f"Cleanup: coordinated (drain→invalidate→kill→recover)")

        print(f"Status: {'ISSUES FOUND' if has_issues else 'OK'}")

    return 1 if has_issues else 0


if __name__ == '__main__':
    sys.exit(main())
