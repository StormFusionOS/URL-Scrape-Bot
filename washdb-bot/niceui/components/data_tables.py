"""
Data Table Components
Reusable table components for displaying scraped data
"""

from nicegui import ui
from typing import List, Dict, Any
from datetime import datetime


def format_datetime(dt):
    """Format datetime for display"""
    if dt is None:
        return 'Never'
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except:
            return dt
    return dt.strftime('%Y-%m-%d %H:%M')


def format_date(dt):
    """Format date only"""
    if dt is None:
        return 'Never'
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except:
            return dt
    return dt.strftime('%Y-%m-%d')


def status_badge(status: str) -> str:
    """Get color for status badge"""
    status_colors = {
        'completed': 'positive',
        'running': 'info',
        'pending': 'warning',
        'failed': 'negative',
        'crawling': 'info',
        'active': 'positive',
        'paused': 'grey',
        'stopped': 'grey'
    }
    return status_colors.get(status.lower() if status else '', 'grey')


def metric_card(title: str, value: Any, subtitle: str = '', icon: str = 'analytics'):
    """
    Create a metric card for dashboard stats

    Args:
        title: Card title
        value: Main metric value
        subtitle: Optional subtitle
        icon: Material icon name
    """
    with ui.card().classes('p-4'):
        with ui.row().classes('items-center gap-3 w-full'):
            ui.icon(icon, size='lg').classes('text-primary')
            with ui.column().classes('gap-1'):
                ui.label(title).classes('text-sm glass-text-secondary')
                ui.label(str(value)).classes('text-2xl font-bold glass-text-primary')
                if subtitle:
                    ui.label(subtitle).classes('text-xs glass-text-secondary')


def competitors_table(competitors: List[Dict[str, Any]]):
    """
    Display competitors in a table

    Args:
        competitors: List of competitor dictionaries
    """
    if not competitors:
        ui.label('No competitors found').classes('text-sm glass-text-secondary p-4')
        return

    columns = [
        {'name': 'id', 'label': 'ID', 'field': 'competitor_id', 'align': 'left'},
        {'name': 'domain', 'label': 'Domain', 'field': 'competitor_domain', 'align': 'left'},
        {'name': 'name', 'label': 'Name', 'field': 'competitor_name', 'align': 'left'},
        {'name': 'category', 'label': 'Category', 'field': 'category', 'align': 'left'},
        {'name': 'priority', 'label': 'Priority', 'field': 'priority', 'align': 'left'},
        {'name': 'url_count', 'label': 'URLs', 'field': 'url_count', 'align': 'right'},
        {'name': 'last_crawl', 'label': 'Last Crawl', 'field': 'last_crawl', 'align': 'left'},
    ]

    # Format data
    rows = []
    for comp in competitors:
        row = {
            'competitor_id': comp.get('competitor_id', ''),
            'competitor_domain': comp.get('competitor_domain', ''),
            'competitor_name': comp.get('competitor_name', ''),
            'category': comp.get('category', ''),
            'priority': comp.get('priority', ''),
            'url_count': comp.get('url_count', 0),
            'last_crawl': format_datetime(comp.get('last_crawl')),
        }
        rows.append(row)

    table = ui.table(columns=columns, rows=rows, row_key='competitor_id')
    table.classes('w-full')
    table.props('dense flat')


def url_queue_table(urls: List[Dict[str, Any]]):
    """
    Display URL queue in a table

    Args:
        urls: List of URL dictionaries
    """
    if not urls:
        ui.label('No URLs found').classes('text-sm glass-text-secondary p-4')
        return

    columns = [
        {'name': 'id', 'label': 'ID', 'field': 'competitor_url_id', 'align': 'left'},
        {'name': 'url', 'label': 'URL', 'field': 'url', 'align': 'left'},
        {'name': 'domain', 'label': 'Domain', 'field': 'domain', 'align': 'left'},
        {'name': 'node_type', 'label': 'Node Type', 'field': 'node_type', 'align': 'left'},
        {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'left'},
        {'name': 'priority', 'label': 'Priority', 'field': 'priority', 'align': 'right'},
        {'name': 'crawl_count', 'label': 'Crawls', 'field': 'crawl_count', 'align': 'right'},
        {'name': 'last_crawled', 'label': 'Last Crawled', 'field': 'last_crawled', 'align': 'left'},
    ]

    rows = []
    for url in urls:
        row = {
            'competitor_url_id': url.get('competitor_url_id', ''),
            'url': url.get('url', '')[:60] + '...' if len(url.get('url', '')) > 60 else url.get('url', ''),
            'domain': url.get('domain', ''),
            'node_type': url.get('node_type', ''),
            'status': url.get('status', ''),
            'priority': url.get('priority', 0),
            'crawl_count': url.get('crawl_count', 0),
            'last_crawled': format_datetime(url.get('last_crawled')),
        }
        rows.append(row)

    table = ui.table(columns=columns, rows=rows, row_key='competitor_url_id')
    table.classes('w-full')
    table.props('dense flat')


def job_history_table(jobs: List[Dict[str, Any]]):
    """
    Display crawl job history

    Args:
        jobs: List of job dictionaries
    """
    if not jobs:
        ui.label('No crawl jobs found').classes('text-sm glass-text-secondary p-4')
        return

    columns = [
        {'name': 'id', 'label': 'Job ID', 'field': 'job_id', 'align': 'left'},
        {'name': 'url', 'label': 'URL', 'field': 'url', 'align': 'left'},
        {'name': 'type', 'label': 'Type', 'field': 'job_type', 'align': 'left'},
        {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'left'},
        {'name': 'priority', 'label': 'Priority', 'field': 'priority', 'align': 'right'},
        {'name': 'attempts', 'label': 'Attempts', 'field': 'attempts', 'align': 'right'},
        {'name': 'started', 'label': 'Started', 'field': 'started_at', 'align': 'left'},
        {'name': 'completed', 'label': 'Completed', 'field': 'completed_at', 'align': 'left'},
    ]

    rows = []
    for job in jobs:
        row = {
            'job_id': job.get('job_id', ''),
            'url': job.get('url', '')[:50] + '...' if len(job.get('url', '')) > 50 else job.get('url', ''),
            'job_type': job.get('job_type', ''),
            'status': job.get('status', ''),
            'priority': job.get('priority', 0),
            'attempts': f"{job.get('attempts', 0)}/{job.get('max_attempts', 0)}",
            'started_at': format_datetime(job.get('started_at')),
            'completed_at': format_datetime(job.get('completed_at')),
        }
        rows.append(row)

    table = ui.table(columns=columns, rows=rows, row_key='job_id')
    table.classes('w-full')
    table.props('dense flat')


def backlinks_table(backlinks: List[Dict[str, Any]]):
    """
    Display backlinks

    Args:
        backlinks: List of backlink dictionaries
    """
    if not backlinks:
        ui.label('No backlinks found').classes('text-sm glass-text-secondary p-4')
        return

    columns = [
        {'name': 'id', 'label': 'ID', 'field': 'backlink_id', 'align': 'left'},
        {'name': 'source', 'label': 'Source Domain', 'field': 'source_domain', 'align': 'left'},
        {'name': 'target', 'label': 'Target Domain', 'field': 'target_domain', 'align': 'left'},
        {'name': 'anchor', 'label': 'Anchor Text', 'field': 'anchor_text', 'align': 'left'},
        {'name': 'rel', 'label': 'Rel', 'field': 'rel_attr', 'align': 'left'},
        {'name': 'region', 'label': 'Region', 'field': 'link_region', 'align': 'left'},
        {'name': 'alive', 'label': 'Status', 'field': 'alive', 'align': 'left'},
        {'name': 'first_seen', 'label': 'First Seen', 'field': 'first_seen', 'align': 'left'},
    ]

    rows = []
    for link in backlinks:
        row = {
            'backlink_id': link.get('backlink_id', ''),
            'source_domain': link.get('source_domain', ''),
            'target_domain': link.get('target_domain', ''),
            'anchor_text': link.get('anchor_text', '')[:40] + '...' if len(link.get('anchor_text', '')) > 40 else link.get('anchor_text', ''),
            'rel_attr': link.get('rel_attr', 'dofollow') or 'dofollow',
            'link_region': link.get('link_region', ''),
            'alive': 'Active' if link.get('alive') else 'Dead',
            'first_seen': format_date(link.get('first_seen')),
        }
        rows.append(row)

    table = ui.table(columns=columns, rows=rows, row_key='backlink_id')
    table.classes('w-full')
    table.props('dense flat')


def changes_table(changes: List[Dict[str, Any]]):
    """
    Display recent content changes

    Args:
        changes: List of change dictionaries
    """
    if not changes:
        ui.label('No changes detected yet').classes('text-sm glass-text-secondary p-4')
        return

    columns = [
        {'name': 'id', 'label': 'ID', 'field': 'change_history_id', 'align': 'left'},
        {'name': 'url', 'label': 'URL', 'field': 'url', 'align': 'left'},
        {'name': 'type', 'label': 'Change Type', 'field': 'change_type', 'align': 'left'},
        {'name': 'similarity', 'label': 'Similarity', 'field': 'similarity_score', 'align': 'right'},
        {'name': 'segment_ratio', 'label': 'Segment Ratio', 'field': 'segment_change_ratio', 'align': 'right'},
        {'name': 'detected', 'label': 'Detected At', 'field': 'detected_at', 'align': 'left'},
    ]

    rows = []
    for change in changes:
        row = {
            'change_history_id': change.get('change_history_id', ''),
            'url': change.get('url', '')[:50] + '...' if len(change.get('url', '')) > 50 else change.get('url', ''),
            'change_type': change.get('change_type', ''),
            'similarity_score': f"{change.get('similarity_score', 0):.2%}" if change.get('similarity_score') else 'N/A',
            'segment_change_ratio': f"{change.get('segment_change_ratio', 0):.2%}" if change.get('segment_change_ratio') else 'N/A',
            'detected_at': format_datetime(change.get('detected_at')),
        }
        rows.append(row)

    table = ui.table(columns=columns, rows=rows, row_key='change_history_id')
    table.classes('w-full')
    table.props('dense flat')
