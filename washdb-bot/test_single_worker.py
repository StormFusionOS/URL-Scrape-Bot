#!/usr/bin/env python3
"""
Test a single YP worker with browser pool and cache.

Processes 5 targets to verify:
- Browser persistence across targets
- Cache hit rates
- Memory usage
- Performance improvements
"""

import os
import sys
import time
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from scrape_yp.state_worker_pool import worker_main
from scrape_yp.state_assignments import get_states_for_worker, get_proxy_assignments
from scrape_yp.browser_pool import get_browser_pool
from scrape_yp.html_cache import get_html_cache
from runner.memory_monitor import get_memory_monitor
from runner.logging_setup import get_logger
import multiprocessing

logger = get_logger("test_single_worker")


def test_single_worker_targets(max_targets: int = 5):
    """
    Test single worker processing a few targets.

    Args:
        max_targets: Maximum number of targets to process
    """
    print("\n" + "=" * 70)
    print(f"SINGLE WORKER TEST ({max_targets} targets)")
    print("=" * 70)

    # Configuration
    worker_id = 0
    state_ids = get_states_for_worker(worker_id)
    proxy_indices = get_proxy_assignments(worker_id)

    config = {
        "proxy_file": os.getenv("PROXY_FILE", "data/webshare_proxies.txt"),
        "min_delay_seconds": 2.0,  # Faster for testing
        "max_delay_seconds": 5.0,
        "max_targets_per_browser": int(os.getenv("MAX_TARGETS_PER_BROWSER", "100")),
        "blacklist_threshold": int(os.getenv("PROXY_BLACKLIST_THRESHOLD", "10")),
        "blacklist_duration_minutes": int(os.getenv("PROXY_BLACKLIST_DURATION_MINUTES", "60")),
        "headless": True,
        "min_confidence_score": 40.0,
        "include_sponsored": False,
        "enable_monitor": False,
        "max_targets": max_targets,  # Limit targets for testing
    }

    print(f"\nWorker Configuration:")
    print(f"  Worker ID: {worker_id}")
    print(f"  States: {state_ids}")
    print(f"  Proxy indices: {proxy_indices}")
    print(f"  Max targets: {max_targets}")
    print(f"  Headless: {config['headless']}")

    # Get initial stats
    print(f"\nInitial State:")
    pool = get_browser_pool()
    cache = get_html_cache()
    monitor = get_memory_monitor()

    pool_stats = pool.get_stats()
    cache_stats = cache.get_stats()

    print(f"  Browser pool: {pool_stats['active_browsers']} browsers, {pool_stats['total_pages_served']} pages served")
    print(f"  HTML cache: {cache_stats['size']} entries, {cache_stats['hit_rate_pct']:.1f}% hit rate")

    monitor.update_stats()
    mem_stats = monitor.get_stats()
    sys_mem = mem_stats['system']
    print(f"  Memory: {sys_mem['used_gb']:.1f} GB / {sys_mem['total_gb']:.1f} GB ({sys_mem['percent']:.1f}%)")

    # Create modified worker function that respects max_targets
    def limited_worker_main(worker_id, state_ids, proxy_indices, shutdown_event, config):
        """Modified worker that stops after max_targets."""
        import random
        from datetime import datetime
        from scrape_yp.yp_filter import YPFilter
        from scrape_yp.yp_crawl_city_first import crawl_single_target
        from scrape_yp.state_worker_pool import (
            acquire_target_for_worker,
            save_companies_to_db,
            mark_target_failed
        )
        from db.models import YPTarget
        from db import create_session

        # Set WORKER_ID environment variable
        os.environ["WORKER_ID"] = str(worker_id)

        worker_logger = get_logger(f"worker_{worker_id}")
        worker_logger.info(f"Worker {worker_id} starting (max {config['max_targets']} targets)")

        yp_filter = YPFilter()
        targets_processed = 0
        max_targets = config.get('max_targets', 999999)

        while not shutdown_event.is_set() and targets_processed < max_targets:
            try:
                target_id = acquire_target_for_worker(state_ids, worker_logger)

                if not target_id:
                    worker_logger.info("No pending targets found")
                    break

                session = create_session()

                try:
                    target = session.query(YPTarget).filter(YPTarget.id == target_id).first()

                    if not target:
                        worker_logger.error(f"Target {target_id} not found")
                        continue

                    worker_logger.info(
                        f"[{targets_processed + 1}/{max_targets}] Processing: "
                        f"{target.city}, {target.state_id} - {target.category_label}"
                    )

                    accepted_results, stats = crawl_single_target(
                        target=target,
                        session=session,
                        yp_filter=yp_filter,
                        min_score=config.get("min_confidence_score", 40.0),
                        include_sponsored=config.get("include_sponsored", False),
                        use_fallback_on_404=True,
                        monitor=None,
                        worker_id=worker_id
                    )

                    if accepted_results:
                        new_count, updated_count = save_companies_to_db(accepted_results, session, worker_logger)
                        worker_logger.info(
                            f"✓ Target {target.id}: {len(accepted_results)} accepted, "
                            f"{stats.get('total_filtered_out', 0)} filtered | "
                            f"DB: {new_count} new, {updated_count} updated"
                        )
                    else:
                        worker_logger.info(
                            f"✓ Target {target.id}: 0 accepted, {stats.get('total_filtered_out', 0)} filtered"
                        )

                    targets_processed += 1

                except Exception as e:
                    worker_logger.error(f"✗ Target {target_id} failed: {e}", exc_info=True)
                    mark_target_failed(target_id, str(e), worker_logger)

                finally:
                    session.close()

                # Short delay between targets
                if targets_processed < max_targets:
                    delay = random.uniform(config['min_delay_seconds'], config['max_delay_seconds'])
                    time.sleep(delay)

            except Exception as e:
                worker_logger.error(f"Error in worker loop: {e}", exc_info=True)
                break

        worker_logger.info(f"Worker {worker_id} finished: {targets_processed} targets processed")

    # Run worker in subprocess
    print(f"\n" + "-" * 70)
    print("Starting worker...")
    print("-" * 70 + "\n")

    shutdown_event = multiprocessing.Event()
    worker_process = multiprocessing.Process(
        target=limited_worker_main,
        args=(worker_id, state_ids, proxy_indices, shutdown_event, config),
        name=f"TestWorker-{worker_id}"
    )

    start_time = time.time()
    worker_process.start()

    # Wait for worker to complete
    worker_process.join(timeout=300)  # 5 minute timeout

    if worker_process.is_alive():
        print("\n⚠ Worker timeout - terminating...")
        shutdown_event.set()
        worker_process.terminate()
        worker_process.join(timeout=10)

    elapsed = time.time() - start_time

    # Get final stats
    print("\n" + "-" * 70)
    print("Final State:")
    print("-" * 70)

    pool_stats = pool.get_stats()
    cache_stats = cache.get_stats()

    print(f"\nBrowser Pool:")
    print(f"  Active browsers: {pool_stats['active_browsers']}")
    print(f"  Total pages served: {pool_stats['total_pages_served']}")
    print(f"  Worker 0 usage: {pool_stats['usage_counts'].get(0, 0)}/{pool_stats['max_uses_per_browser']}")

    print(f"\nHTML Cache:")
    print(f"  Size: {cache_stats['size']}/{cache_stats['max_size']}")
    print(f"  Total requests: {cache_stats['total_requests']}")
    print(f"  Hits: {cache_stats['hits']}")
    print(f"  Misses: {cache_stats['misses']}")
    print(f"  Hit rate: {cache_stats['hit_rate_pct']:.1f}%")

    monitor.update_stats()
    mem_stats = monitor.get_stats()
    sys_mem = mem_stats['system']

    print(f"\nMemory:")
    print(f"  System: {sys_mem['used_gb']:.1f} GB / {sys_mem['total_gb']:.1f} GB ({sys_mem['percent']:.1f}%)")

    comp_mem = mem_stats['components']
    if 'browser_pool' in comp_mem and 'error' not in comp_mem['browser_pool']:
        bp = comp_mem['browser_pool']
        print(f"  Browser pool: {bp['active_browsers']} browsers (~{bp['estimated_memory_gb']:.2f} GB)")

    print(f"\nPerformance:")
    print(f"  Total time: {elapsed:.1f}s")
    print(f"  Targets processed: {max_targets}")
    print(f"  Avg time per target: {elapsed / max_targets:.1f}s")

    print("\n" + "=" * 70)
    print("SINGLE WORKER TEST COMPLETE ✓")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    test_single_worker_targets(max_targets=5)
