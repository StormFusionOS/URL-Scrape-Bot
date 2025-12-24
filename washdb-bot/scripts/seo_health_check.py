#!/usr/bin/env python3
"""
SEO Worker Health Check Script.

Checks the health of SEO workers, manages Chrome processes, and can restart stale workers.
Can be run as a cron job or systemd timer.

Usage:
    python scripts/seo_health_check.py           # Check status
    python scripts/seo_health_check.py --restart # Restart stale workers
    python scripts/seo_health_check.py --cleanup # Force Chrome cleanup
"""

import argparse
import os
import subprocess
import sys
import signal
import re
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database_manager import get_db_manager
from sqlalchemy import text


STALE_THRESHOLD_MINUTES = 5
MAX_CHROME_PROCESSES = 100  # Alert/cleanup threshold
CRITICAL_CHROME_PROCESSES = 200  # Force restart threshold


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


def cleanup_chrome_processes(force=False, quiet=False):
    """Clean up excess Chrome processes.

    Args:
        force: Kill all orphaned Chrome processes regardless of count
        quiet: Suppress output

    Returns:
        Tuple of (chrome_count, killed_count, needs_restart)
    """
    chrome_procs = get_chrome_processes()
    chrome_count = len(chrome_procs)
    killed = 0
    needs_restart = False

    if not quiet:
        print(f"Chrome processes: {chrome_count}")

    # Critical threshold - need full restart
    if chrome_count >= CRITICAL_CHROME_PROCESSES:
        if not quiet:
            print(f"[CRITICAL] {chrome_count} Chrome processes - exceeds critical threshold ({CRITICAL_CHROME_PROCESSES})")
            print("Killing all Chrome processes and restarting worker...")

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

    # Warning threshold or force cleanup - kill orphans only
    if chrome_count >= MAX_CHROME_PROCESSES or force:
        if not quiet and chrome_count >= MAX_CHROME_PROCESSES:
            print(f"[WARNING] {chrome_count} Chrome processes - exceeds threshold ({MAX_CHROME_PROCESSES})")

        orphan_pids = get_orphan_chrome_pids()
        if orphan_pids:
            if not quiet:
                print(f"Found {len(orphan_pids)} orphaned Chrome processes")

            for pid in orphan_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                except (ProcessLookupError, PermissionError):
                    pass

            if not quiet:
                print(f"Killed {killed} orphaned Chrome processes")

        # If still too many after orphan cleanup, kill oldest ones
        if chrome_count - killed > MAX_CHROME_PROCESSES:
            remaining = get_chrome_processes()
            # Sort by PID (older processes have lower PIDs typically)
            remaining.sort(key=lambda x: x['pid'])
            excess = len(remaining) - MAX_CHROME_PROCESSES + 20  # Leave some headroom

            if excess > 0:
                for proc in remaining[:excess]:
                    try:
                        os.kill(proc['pid'], signal.SIGKILL)
                        killed += 1
                    except (ProcessLookupError, PermissionError):
                        pass

                if not quiet:
                    print(f"Killed {excess} excess Chrome processes (oldest)")

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
        import time
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


def main():
    parser = argparse.ArgumentParser(description='SEO Worker Health Check')
    parser.add_argument('--restart', action='store_true', help='Restart stale workers')
    parser.add_argument('--cleanup', action='store_true', help='Force Chrome process cleanup')
    parser.add_argument('--coordinated', action='store_true', help='Use coordinated pool cleanup (drain, invalidate, recover)')
    parser.add_argument('--quiet', '-q', action='store_true', help='Only output on issues')
    args = parser.parse_args()

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
