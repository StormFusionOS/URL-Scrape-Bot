"""
History manager for tracking scraping runs.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


class HistoryManager:
    """Manages run history in a JSONL file."""

    def __init__(self, history_file: str = "data/history.jsonl"):
        self.history_file = Path(history_file)
        self._ensure_file()

    def _ensure_file(self):
        """Ensure history file and directory exist."""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            self.history_file.touch()

    def add_run(
        self,
        job_type: str,
        args: Dict,
        duration_sec: float,
        exit_code: int,
        counts: Optional[Dict] = None,
        log_path: Optional[str] = None,
        notes: Optional[str] = None
    ):
        """
        Add a run to history.

        Args:
            job_type: Type of job (Discover/Scrape/Single URL)
            args: Job arguments dict
            duration_sec: Duration in seconds
            exit_code: Process exit code
            counts: Dict with found, updated, errors counts
            log_path: Path to log file
            notes: Additional notes
        """
        entry = {
            'timestamp': datetime.now().isoformat(),
            'job_type': job_type,
            'args': args,
            'duration_sec': round(duration_sec, 2),
            'exit_code': exit_code,
            'counts': counts or {},
            'log_path': log_path,
            'notes': notes
        }

        # Append to file
        with open(self.history_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def get_all_runs(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Get all runs from history.

        Args:
            limit: Maximum number of runs to return (most recent first)

        Returns:
            List of run dicts
        """
        runs = []

        if not self.history_file.exists():
            return runs

        with open(self.history_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        runs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Most recent first
        runs.reverse()

        if limit:
            runs = runs[:limit]

        return runs

    def filter_runs(
        self,
        job_type: Optional[str] = None,
        search: Optional[str] = None,
        limit: Optional[int] = 100
    ) -> List[Dict]:
        """
        Filter runs by criteria.

        Args:
            job_type: Filter by job type
            search: Search in args/notes
            limit: Maximum results

        Returns:
            Filtered list of runs
        """
        runs = self.get_all_runs()

        if job_type:
            runs = [r for r in runs if r.get('job_type') == job_type]

        if search:
            search_lower = search.lower()
            runs = [
                r for r in runs
                if search_lower in str(r.get('args', '')).lower()
                or search_lower in str(r.get('notes', '')).lower()
            ]

        return runs[:limit] if limit else runs

    def clear_history(self):
        """Clear all history."""
        if self.history_file.exists():
            self.history_file.unlink()
        self._ensure_file()

    def export_csv(self, output_path: str):
        """Export history to CSV."""
        import csv

        runs = self.get_all_runs()
        if not runs:
            return

        with open(output_path, 'w', newline='') as f:
            fieldnames = ['timestamp', 'job_type', 'duration_sec', 'exit_code',
                          'found', 'updated', 'errors', 'args', 'log_path', 'notes']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for run in runs:
                counts = run.get('counts', {})
                row = {
                    'timestamp': run.get('timestamp', ''),
                    'job_type': run.get('job_type', ''),
                    'duration_sec': run.get('duration_sec', 0),
                    'exit_code': run.get('exit_code', -1),
                    'found': counts.get('found', 0),
                    'updated': counts.get('updated', 0),
                    'errors': counts.get('errors', 0),
                    'args': json.dumps(run.get('args', {})),
                    'log_path': run.get('log_path', ''),
                    'notes': run.get('notes', '')
                }
                writer.writerow(row)

    def get_stats(self) -> Dict:
        """Get summary statistics."""
        runs = self.get_all_runs()

        if not runs:
            return {
                'total_runs': 0,
                'success_count': 0,
                'error_count': 0,
                'total_duration': 0,
                'avg_duration': 0
            }

        success_count = sum(1 for r in runs if r.get('exit_code') == 0)
        error_count = len(runs) - success_count
        total_duration = sum(r.get('duration_sec', 0) for r in runs)

        return {
            'total_runs': len(runs),
            'success_count': success_count,
            'error_count': error_count,
            'total_duration': round(total_duration, 2),
            'avg_duration': round(total_duration / len(runs), 2) if runs else 0
        }


# Global history manager instance
history_manager = HistoryManager()
