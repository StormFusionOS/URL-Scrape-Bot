#!/usr/bin/env python3
"""
URL Scraper Progress Tracker

Shows real-time percentage progress for each scraper before they reset.
Displays progress bars, ETA calculations, and cycle information.
"""

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# ANSI colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


def get_scraper_stats(engine):
    """Get progress stats for all scrapers."""

    scrapers = [
        {
            'name': 'Google',
            'table': 'google_targets',
            'emoji': '🔍',
            'done_status': ['DONE', 'done'],
            'planned_status': ['PLANNED', 'planned', 'pending'],
            'in_progress_status': ['IN_PROGRESS', 'in_progress'],
            'failed_status': ['FAILED', 'failed']
        },
        {
            'name': 'YellowPages',
            'table': 'yp_targets',
            'emoji': '📒',
            'done_status': ['DONE', 'done'],
            'planned_status': ['PLANNED', 'planned', 'pending'],
            'in_progress_status': ['IN_PROGRESS', 'in_progress'],
            'failed_status': ['FAILED', 'failed']
        },
        {
            'name': 'Yelp',
            'table': 'yelp_targets',
            'emoji': '⭐',
            'done_status': ['DONE', 'done'],
            'planned_status': ['PLANNED', 'planned', 'pending'],
            'in_progress_status': ['IN_PROGRESS', 'in_progress'],
            'failed_status': ['FAILED', 'failed']
        },
        {
            'name': 'Bing',
            'table': 'bing_targets',
            'emoji': '🔷',
            'done_status': ['DONE', 'done'],
            'planned_status': ['PLANNED', 'planned', 'pending'],
            'in_progress_status': ['IN_PROGRESS', 'in_progress'],
            'failed_status': ['FAILED', 'failed']
        },
    ]

    results = []

    with engine.connect() as conn:
        for scraper in scrapers:
            # Get status distribution
            result = conn.execute(text(f"SELECT status, COUNT(*) FROM {scraper['table']} GROUP BY status"))
            status_counts = {str(r[0]).upper() if r[0] else 'NULL': r[1] for r in result}

            # Normalize status counts
            done = sum(status_counts.get(s.upper(), 0) for s in scraper['done_status'])
            planned = sum(status_counts.get(s.upper(), 0) for s in scraper['planned_status'])
            in_progress = sum(status_counts.get(s.upper(), 0) for s in scraper['in_progress_status'])
            failed = sum(status_counts.get(s.upper(), 0) for s in scraper['failed_status'])

            total = done + planned + in_progress + failed

            # Get recent activity (last 24h)
            try:
                result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM {scraper['table']}
                    WHERE finished_at > NOW() - INTERVAL '24 hours'
                """))
                last_24h = result.fetchone()[0]
            except:
                last_24h = 0

            # Get active workers
            try:
                result = conn.execute(text(f"""
                    SELECT COUNT(DISTINCT claimed_by) FROM {scraper['table']}
                    WHERE status IN ('IN_PROGRESS', 'in_progress')
                """))
                active_workers = result.fetchone()[0]
            except:
                active_workers = 0

            results.append({
                'name': scraper['name'],
                'emoji': scraper['emoji'],
                'total': total,
                'done': done,
                'planned': planned,
                'in_progress': in_progress,
                'failed': failed,
                'last_24h': last_24h,
                'active_workers': active_workers,
                'percentage': (done / total * 100) if total > 0 else 0
            })

    return results


def format_number(n):
    """Format number with commas."""
    return f"{n:,}"


def create_progress_bar(percentage, width=40):
    """Create a colored progress bar."""
    filled = int(percentage / 100 * width)
    empty = width - filled

    # Color based on percentage
    if percentage >= 75:
        color = Colors.GREEN
    elif percentage >= 50:
        color = Colors.CYAN
    elif percentage >= 25:
        color = Colors.YELLOW
    else:
        color = Colors.RED

    bar = f"{color}{'█' * filled}{Colors.DIM}{'░' * empty}{Colors.ENDC}"
    return bar


def calculate_eta(done, total, rate_per_hour):
    """Calculate ETA based on current rate."""
    if rate_per_hour <= 0 or done >= total:
        return "N/A"

    remaining = total - done
    hours = remaining / rate_per_hour

    if hours < 1:
        return f"{int(hours * 60)}m"
    elif hours < 24:
        return f"{hours:.1f}h"
    else:
        days = hours / 24
        return f"{days:.1f}d"


def display_progress(stats, clear=True):
    """Display the progress dashboard."""

    if clear:
        # Clear screen
        print('\033[2J\033[H', end='')

    # Header
    print(f"\n{Colors.BOLD}╔{'═' * 78}╗{Colors.ENDC}")
    print(f"{Colors.BOLD}║  {Colors.CYAN}URL SCRAPER PROGRESS TRACKER{Colors.ENDC}{'':>45}{Colors.BOLD}║{Colors.ENDC}")
    print(f"{Colors.BOLD}║  {Colors.DIM}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.ENDC}{'':>52}{Colors.BOLD}║{Colors.ENDC}")
    print(f"{Colors.BOLD}╠{'═' * 78}╣{Colors.ENDC}")

    for s in stats:
        pct = s['percentage']
        bar = create_progress_bar(pct, 35)

        # Color the percentage based on value
        if pct >= 75:
            pct_color = Colors.GREEN
        elif pct >= 50:
            pct_color = Colors.CYAN
        elif pct >= 25:
            pct_color = Colors.YELLOW
        else:
            pct_color = Colors.RED

        # ETA calculation (rough estimate based on 24h rate)
        eta = calculate_eta(s['done'], s['total'], s['last_24h']) if s['last_24h'] > 0 else "N/A"

        # Status indicator
        if s['in_progress'] > 0:
            status = f"{Colors.GREEN}●{Colors.ENDC}"
        elif s['done'] == s['total'] and s['total'] > 0:
            status = f"{Colors.CYAN}✓{Colors.ENDC}"
        else:
            status = f"{Colors.DIM}○{Colors.ENDC}"

        print(f"{Colors.BOLD}║{Colors.ENDC}")
        print(f"{Colors.BOLD}║{Colors.ENDC}  {s['emoji']} {status} {Colors.BOLD}{s['name']:12}{Colors.ENDC} {bar} {pct_color}{pct:5.1f}%{Colors.ENDC}")
        print(f"{Colors.BOLD}║{Colors.ENDC}     {Colors.DIM}├─{Colors.ENDC} Done: {Colors.GREEN}{format_number(s['done']):>10}{Colors.ENDC}  │  Remaining: {Colors.YELLOW}{format_number(s['planned'] + s['in_progress']):>10}{Colors.ENDC}  │  Total: {format_number(s['total']):>10}")
        print(f"{Colors.BOLD}║{Colors.ENDC}     {Colors.DIM}├─{Colors.ENDC} In Progress: {Colors.CYAN}{s['in_progress']:>5}{Colors.ENDC}  │  Failed: {Colors.RED}{s['failed']:>5}{Colors.ENDC}  │  Workers: {s['active_workers']}")
        print(f"{Colors.BOLD}║{Colors.ENDC}     {Colors.DIM}└─{Colors.ENDC} Last 24h: {Colors.BLUE}{format_number(s['last_24h']):>8}{Colors.ENDC}  │  Rate: {format_number(s['last_24h'])}/day  │  ETA: {eta}")

    print(f"{Colors.BOLD}║{Colors.ENDC}")
    print(f"{Colors.BOLD}╠{'═' * 78}╣{Colors.ENDC}")

    # Summary
    total_done = sum(s['done'] for s in stats)
    total_all = sum(s['total'] for s in stats)
    total_pct = (total_done / total_all * 100) if total_all > 0 else 0

    print(f"{Colors.BOLD}║{Colors.ENDC}  {Colors.BOLD}TOTAL PROGRESS:{Colors.ENDC} {create_progress_bar(total_pct, 30)} {total_pct:5.1f}% ({format_number(total_done)}/{format_number(total_all)})")
    print(f"{Colors.BOLD}╚{'═' * 78}╝{Colors.ENDC}")
    print(f"\n{Colors.DIM}Press Ctrl+C to exit{Colors.ENDC}")


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description='URL Scraper Progress Tracker')
    parser.add_argument('--watch', '-w', action='store_true', help='Continuously update (every 30s)')
    parser.add_argument('--interval', '-i', type=int, default=30, help='Update interval in seconds (default: 30)')
    parser.add_argument('--simple', '-s', action='store_true', help='Simple output (no colors)')
    args = parser.parse_args()

    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    engine = create_engine(DATABASE_URL)

    if args.simple:
        # Simple output for scripts/logging
        stats = get_scraper_stats(engine)
        for s in stats:
            print(f"{s['name']}: {s['percentage']:.1f}% ({s['done']}/{s['total']})")
        return

    try:
        if args.watch:
            while True:
                stats = get_scraper_stats(engine)
                display_progress(stats, clear=True)
                time.sleep(args.interval)
        else:
            stats = get_scraper_stats(engine)
            display_progress(stats, clear=False)
    except KeyboardInterrupt:
        print(f"\n{Colors.DIM}Exiting...{Colors.ENDC}")


if __name__ == '__main__':
    main()
