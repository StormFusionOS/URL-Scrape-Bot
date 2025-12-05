#!/usr/bin/env python3
"""
Memory Monitoring Service for WashDB Scraper

Tracks memory usage across all components:
- Browser pool (Playwright browsers)
- HTML parsing cache
- Database connection pools
- Worker processes
- System-wide memory

Provides real-time stats for dashboard and performance tuning.
"""

import os
import psutil
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional
from runner.logging_setup import get_logger

logger = get_logger("memory_monitor")


class MemoryMonitor:
    """
    Monitors memory usage across all system components.

    Tracks:
    - Total system memory (used/available)
    - Process-level memory (worker processes)
    - Component-level memory (browser pool, cache, etc.)
    - Memory trends over time
    """

    def __init__(self, update_interval: float = 10.0):
        """
        Initialize memory monitor.

        Args:
            update_interval: How often to update stats (seconds)
        """
        self.update_interval = update_interval
        self.running = False
        self.thread: Optional[threading.Thread] = None

        # Current stats
        self.stats = {
            'system': {},
            'processes': {},
            'components': {},
            'last_updated': None,
        }

        # Historical stats (last 100 samples)
        self.history: List[Dict] = []
        self.max_history = 100

        logger.info(f"MemoryMonitor initialized: update_interval={update_interval}s")

    def get_system_memory(self) -> Dict:
        """
        Get system-wide memory statistics.

        Returns:
            dict: System memory info
        """
        mem = psutil.virtual_memory()

        return {
            'total_gb': mem.total / (1024 ** 3),
            'used_gb': mem.used / (1024 ** 3),
            'available_gb': mem.available / (1024 ** 3),
            'percent': mem.percent,
            'free_gb': mem.free / (1024 ** 3),
        }

    def get_process_memory(self, process_name_filter: Optional[str] = None) -> Dict:
        """
        Get memory usage for specific processes.

        Args:
            process_name_filter: Filter processes by name (e.g., "python", "chromium")

        Returns:
            dict: Process memory info
        """
        processes = {}
        total_memory_mb = 0

        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                pinfo = proc.info
                if process_name_filter and process_name_filter not in pinfo['name'].lower():
                    continue

                mem_mb = pinfo['memory_info'].rss / (1024 ** 2)
                processes[f"{pinfo['name']}_{pinfo['pid']}"] = {
                    'pid': pinfo['pid'],
                    'name': pinfo['name'],
                    'memory_mb': mem_mb,
                }
                total_memory_mb += mem_mb

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            'total_mb': total_memory_mb,
            'total_gb': total_memory_mb / 1024,
            'count': len(processes),
            'processes': processes,
        }

    def get_component_memory(self) -> Dict:
        """
        Get memory usage for system components.

        Returns:
            dict: Component memory info
        """
        components = {}

        # Browser pool
        try:
            from scrape_yp.browser_pool import get_browser_pool
            pool = get_browser_pool()
            pool_stats = pool.get_stats()

            # Estimate: ~200 MB per browser
            browser_memory_mb = pool_stats['active_browsers'] * 200

            components['browser_pool'] = {
                'active_browsers': pool_stats['active_browsers'],
                'total_pages_served': pool_stats['total_pages_served'],
                'estimated_memory_mb': browser_memory_mb,
                'estimated_memory_gb': browser_memory_mb / 1024,
            }
        except Exception as e:
            logger.debug(f"Browser pool stats unavailable: {e}")
            components['browser_pool'] = {'error': str(e)}

        # HTML cache
        try:
            from scrape_yp.html_cache import get_html_cache
            cache = get_html_cache()
            cache_stats = cache.get_stats()

            # Estimate: ~500 KB per cached page
            cache_memory_mb = cache_stats['size'] * 0.5

            components['html_cache'] = {
                'size': cache_stats['size'],
                'max_size': cache_stats['max_size'],
                'hit_rate_pct': cache_stats['hit_rate_pct'],
                'estimated_memory_mb': cache_memory_mb,
                'estimated_memory_gb': cache_memory_mb / 1024,
            }
        except Exception as e:
            logger.debug(f"HTML cache stats unavailable: {e}")
            components['html_cache'] = {'error': str(e)}

        # Database connection pools (if available)
        try:
            from db import engine
            pool = engine.pool

            components['db_pool'] = {
                'pool_size': pool.size(),
                'checked_out': pool.checkedout(),
                'overflow': pool.overflow(),
            }
        except Exception as e:
            logger.debug(f"DB pool stats unavailable: {e}")
            components['db_pool'] = {'error': str(e)}

        return components

    def get_worker_processes(self) -> Dict:
        """
        Get memory usage for scraper worker processes.

        Returns:
            dict: Worker process memory info
        """
        workers = {
            'yp_workers': [],
            'google_workers': [],
            'verification_workers': [],
            'total_memory_mb': 0,
        }

        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
            try:
                pinfo = proc.info
                cmdline = ' '.join(pinfo['cmdline'] or [])

                mem_mb = pinfo['memory_info'].rss / (1024 ** 2)

                # Identify worker type
                if 'state_worker_pool' in cmdline or 'yp_crawl' in cmdline:
                    workers['yp_workers'].append({
                        'pid': pinfo['pid'],
                        'memory_mb': mem_mb,
                    })
                    workers['total_memory_mb'] += mem_mb

                elif 'google_worker' in cmdline:
                    workers['google_workers'].append({
                        'pid': pinfo['pid'],
                        'memory_mb': mem_mb,
                    })
                    workers['total_memory_mb'] += mem_mb

                elif 'verification_worker' in cmdline:
                    workers['verification_workers'].append({
                        'pid': pinfo['pid'],
                        'memory_mb': mem_mb,
                    })
                    workers['total_memory_mb'] += mem_mb

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        workers['total_memory_gb'] = workers['total_memory_mb'] / 1024
        workers['total_workers'] = (
            len(workers['yp_workers']) +
            len(workers['google_workers']) +
            len(workers['verification_workers'])
        )

        return workers

    def update_stats(self):
        """Update all memory statistics."""
        try:
            # System memory
            self.stats['system'] = self.get_system_memory()

            # Process memory (Python processes)
            self.stats['processes'] = self.get_process_memory('python')

            # Component memory
            self.stats['components'] = self.get_component_memory()

            # Worker processes
            self.stats['workers'] = self.get_worker_processes()

            # Timestamp
            self.stats['last_updated'] = datetime.now().isoformat()

            # Add to history
            self.history.append({
                'timestamp': self.stats['last_updated'],
                'system_used_gb': self.stats['system']['used_gb'],
                'system_percent': self.stats['system']['percent'],
                'processes_total_gb': self.stats['processes']['total_gb'],
            })

            # Trim history
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]

        except Exception as e:
            logger.error(f"Error updating memory stats: {e}", exc_info=True)

    def get_stats(self) -> Dict:
        """
        Get current memory statistics.

        Returns:
            dict: Memory stats
        """
        # Update if stats are stale (> 2x update interval)
        if not self.stats.get('last_updated'):
            self.update_stats()

        return self.stats

    def get_history(self) -> List[Dict]:
        """
        Get historical memory statistics.

        Returns:
            list: Historical stats
        """
        return self.history

    def start_monitoring(self):
        """Start background monitoring thread."""
        if self.running:
            logger.warning("Memory monitor already running")
            return

        self.running = True

        def monitor_loop():
            logger.info("Memory monitoring thread started")
            while self.running:
                self.update_stats()
                time.sleep(self.update_interval)
            logger.info("Memory monitoring thread stopped")

        self.thread = threading.Thread(target=monitor_loop, daemon=True)
        self.thread.start()

        logger.info("Memory monitoring started")

    def stop_monitoring(self):
        """Stop background monitoring thread."""
        if not self.running:
            return

        self.running = False

        if self.thread:
            self.thread.join(timeout=5)

        logger.info("Memory monitoring stopped")

    def print_summary(self):
        """Print memory summary to console."""
        stats = self.get_stats()

        print("\n" + "=" * 70)
        print("MEMORY MONITOR SUMMARY")
        print("=" * 70)

        # System
        sys_stats = stats.get('system', {})
        print(f"\nSystem Memory:")
        print(f"  Total:     {sys_stats.get('total_gb', 0):.1f} GB")
        print(f"  Used:      {sys_stats.get('used_gb', 0):.1f} GB ({sys_stats.get('percent', 0):.1f}%)")
        print(f"  Available: {sys_stats.get('available_gb', 0):.1f} GB")

        # Processes
        proc_stats = stats.get('processes', {})
        print(f"\nPython Processes:")
        print(f"  Count:     {proc_stats.get('count', 0)}")
        print(f"  Total:     {proc_stats.get('total_gb', 0):.2f} GB")

        # Components
        comp_stats = stats.get('components', {})
        print(f"\nComponents:")

        if 'browser_pool' in comp_stats and 'error' not in comp_stats['browser_pool']:
            bp = comp_stats['browser_pool']
            print(f"  Browser Pool:")
            print(f"    Browsers:  {bp.get('active_browsers', 0)}")
            print(f"    Memory:    ~{bp.get('estimated_memory_gb', 0):.2f} GB")

        if 'html_cache' in comp_stats and 'error' not in comp_stats['html_cache']:
            hc = comp_stats['html_cache']
            print(f"  HTML Cache:")
            print(f"    Size:      {hc.get('size', 0)}/{hc.get('max_size', 0)}")
            print(f"    Hit Rate:  {hc.get('hit_rate_pct', 0):.1f}%")
            print(f"    Memory:    ~{hc.get('estimated_memory_gb', 0):.2f} GB")

        # Workers
        worker_stats = stats.get('workers', {})
        print(f"\nWorker Processes:")
        print(f"  YP Workers:            {len(worker_stats.get('yp_workers', []))}")
        print(f"  Google Workers:        {len(worker_stats.get('google_workers', []))}")
        print(f"  Verification Workers:  {len(worker_stats.get('verification_workers', []))}")
        print(f"  Total Memory:          {worker_stats.get('total_memory_gb', 0):.2f} GB")

        print("\n" + "=" * 70 + "\n")


# Global singleton instance
_memory_monitor: Optional[MemoryMonitor] = None
_monitor_lock = threading.Lock()


def get_memory_monitor() -> MemoryMonitor:
    """
    Get or create global memory monitor singleton.

    Returns:
        MemoryMonitor: Global monitor instance
    """
    global _memory_monitor

    if _memory_monitor is None:
        with _monitor_lock:
            if _memory_monitor is None:
                # Read config from environment
                update_interval = float(os.getenv("MEMORY_MONITOR_INTERVAL", "10.0"))

                _memory_monitor = MemoryMonitor(update_interval=update_interval)
                logger.info(f"Global memory monitor created: update_interval={update_interval}s")

    return _memory_monitor


# Example usage
if __name__ == "__main__":
    monitor = get_memory_monitor()

    # Print initial stats
    monitor.update_stats()
    monitor.print_summary()

    # Start monitoring
    print("Starting background monitoring for 30 seconds...")
    monitor.start_monitoring()

    time.sleep(30)

    # Print final stats
    monitor.print_summary()

    # Stop monitoring
    monitor.stop_monitoring()
