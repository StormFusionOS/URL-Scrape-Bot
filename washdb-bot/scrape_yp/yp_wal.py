#!/usr/bin/env python3
"""
Yellow Pages Write-Ahead Log (WAL) for worker visibility.

This module provides per-worker JSONL logging for operator visibility.
The WAL is NOT the source of truth (DB is), but provides a human-readable
audit trail of what each worker is doing.

Usage:
    from scrape_yp.yp_wal import WorkerWAL

    # Create WAL for worker
    wal = WorkerWAL(worker_id="worker_0_pid_12345", log_dir="logs")

    # Log page completion
    wal.log_page_complete(
        target_id=123,
        page_number=1,
        accepted_count=15,
        city="Los Angeles",
        state="CA",
        category="Window Cleaning"
    )

    # Log target completion
    wal.log_target_complete(
        target_id=123,
        total_pages=3,
        total_accepted=42
    )

    # Close WAL
    wal.close()
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class WorkerWAL:
    """
    Write-Ahead Log for worker progress visibility.

    Each worker gets its own JSONL log file in logs/yp_wal/.
    """

    def __init__(self, worker_id: str, log_dir: str = "logs"):
        """
        Initialize WAL for a worker.

        Args:
            worker_id: Unique worker identifier (e.g., 'worker_0_pid_12345')
            log_dir: Base log directory (default: 'logs')
        """
        self.worker_id = worker_id
        self.log_dir = Path(log_dir) / "yp_wal"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create log file: logs/yp_wal/worker_0_pid_12345.jsonl
        self.log_file = self.log_dir / f"{worker_id}.jsonl"
        self.file_handle = open(self.log_file, 'a', buffering=1)  # Line-buffered

    def _write_event(self, event_type: str, data: dict):
        """
        Write a single event to the WAL.

        Args:
            event_type: Event type (e.g., 'page_complete', 'target_complete', 'error')
            data: Event data dict
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'worker_id': self.worker_id,
            'event_type': event_type,
            **data
        }

        # Write as JSONL (one JSON object per line)
        self.file_handle.write(json.dumps(event) + '\n')

    def log_target_start(self, target_id: int, city: str, state: str, category: str, max_pages: int):
        """
        Log that a worker has started processing a target.

        Args:
            target_id: YP target ID
            city: City name
            state: State code
            category: Category label
            max_pages: Maximum pages to crawl
        """
        self._write_event('target_start', {
            'target_id': target_id,
            'city': city,
            'state': state,
            'category': category,
            'max_pages': max_pages
        })

    def log_page_complete(
        self,
        target_id: int,
        page_number: int,
        accepted_count: int,
        city: str,
        state: str,
        category: str,
        raw_count: Optional[int] = None
    ):
        """
        Log that a page has been successfully processed.

        Args:
            target_id: YP target ID
            page_number: Page number (1-indexed)
            accepted_count: Number of listings accepted from this page
            city: City name
            state: State code
            category: Category label
            raw_count: Total raw listings parsed (optional)
        """
        self._write_event('page_complete', {
            'target_id': target_id,
            'page_number': page_number,
            'accepted_count': accepted_count,
            'raw_count': raw_count,
            'city': city,
            'state': state,
            'category': category
        })

    def log_target_complete(self, target_id: int, total_pages: int, total_accepted: int):
        """
        Log that a target has been completed.

        Args:
            target_id: YP target ID
            total_pages: Total pages crawled
            total_accepted: Total listings accepted
        """
        self._write_event('target_complete', {
            'target_id': target_id,
            'total_pages': total_pages,
            'total_accepted': total_accepted
        })

    def log_target_error(self, target_id: int, error: str, page_number: Optional[int] = None):
        """
        Log that a target encountered an error.

        Args:
            target_id: YP target ID
            error: Error message
            page_number: Page number where error occurred (optional)
        """
        self._write_event('target_error', {
            'target_id': target_id,
            'error': error,
            'page_number': page_number
        })

    def log_heartbeat(self, target_id: Optional[int] = None):
        """
        Log a heartbeat event.

        Args:
            target_id: Current target ID (optional)
        """
        self._write_event('heartbeat', {
            'target_id': target_id
        })

    def close(self):
        """Close the WAL file handle."""
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def read_wal(log_file: str) -> list[dict]:
    """
    Read and parse a WAL file.

    Args:
        log_file: Path to WAL file (JSONL format)

    Returns:
        List of event dicts
    """
    events = []

    with open(log_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse line: {line[:50]}... ({e})")

    return events


def get_latest_wal_state(log_file: str) -> Optional[dict]:
    """
    Get the latest state from a WAL file.

    Scans the WAL and returns the last event for each target.

    Args:
        log_file: Path to WAL file (JSONL format)

    Returns:
        Dict mapping target_id to latest event
    """
    events = read_wal(log_file)

    if not events:
        return None

    # Group by target_id and keep latest event per target
    latest_by_target = {}

    for event in events:
        target_id = event.get('target_id')
        if target_id:
            latest_by_target[target_id] = event

    return {
        'worker_id': events[-1].get('worker_id'),
        'last_event_time': events[-1].get('timestamp'),
        'total_events': len(events),
        'targets': latest_by_target
    }


if __name__ == "__main__":
    """Demo: Create sample WAL and read it back."""
    import argparse

    parser = argparse.ArgumentParser(description="YP WAL Utility")
    parser.add_argument('--read', help="Read and display WAL file")
    parser.add_argument('--demo', action='store_true', help="Create demo WAL")

    args = parser.parse_args()

    if args.read:
        # Read and display WAL
        state = get_latest_wal_state(args.read)
        if state:
            print(f"Worker: {state['worker_id']}")
            print(f"Last event: {state['last_event_time']}")
            print(f"Total events: {state['total_events']}")
            print(f"\nTargets:")
            for target_id, event in state['targets'].items():
                print(f"  Target {target_id}: {event['event_type']} at {event['timestamp']}")
        else:
            print("No events in WAL")

    elif args.demo:
        # Create demo WAL
        with WorkerWAL("worker_demo_pid_99999", log_dir="logs") as wal:
            wal.log_target_start(123, "Los Angeles", "CA", "Window Cleaning", 3)
            wal.log_page_complete(123, 1, 15, "Los Angeles", "CA", "Window Cleaning", raw_count=20)
            wal.log_page_complete(123, 2, 12, "Los Angeles", "CA", "Window Cleaning", raw_count=18)
            wal.log_page_complete(123, 3, 8, "Los Angeles", "CA", "Window Cleaning", raw_count=10)
            wal.log_target_complete(123, 3, 35)

        print(f"Demo WAL created at logs/yp_wal/worker_demo_pid_99999.jsonl")

    else:
        parser.print_help()
