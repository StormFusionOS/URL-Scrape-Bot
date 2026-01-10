"""
System Monitor Page - comprehensive error monitoring, self-healing, and system health dashboard.

Features:
- Service status grid with start/stop/restart controls
- Real-time error feed with AI copy functionality
- System resource gauges (CPU, RAM, Swap, Disk, GPU)
- Self-healing actions panel with history
- Live log streaming
"""

import asyncio
from datetime import datetime
from typing import Optional
from nicegui import ui

from ..widgets.service_status_card import ServiceStatusCard, ServiceStatus, check_process_running
from ..widgets.error_feed import error_feed_card, get_error_stats
from ..widgets.resource_gauges import resource_gauges_card
from ..widgets.self_healing_panel import self_healing_card
from ..widgets.live_log_viewer import LiveLogViewer


class SystemMonitorState:
    """State for the system monitor page."""

    def __init__(self):
        self.service_cards = []
        self.error_feed = None
        self.resource_panel = None
        self.healing_panel = None
        self.log_viewer = None
        self.update_timer = None
        self.overall_status = ServiceStatus.HEALTHY


state = SystemMonitorState()


# Service definitions
SERVICES = [
    {
        'name': 'SEO Worker',
        'service_name': 'seo-job-worker',
        'icon': 'work',
        'check_type': 'systemd',
    },
    {
        'name': 'YP Scraper',
        'service_name': 'washbot-yp-scraper',
        'icon': 'menu_book',
        'check_type': 'systemd',
    },
    {
        'name': 'YP State Workers',
        'service_name': 'yp-state-workers',
        'icon': 'groups',
        'check_type': 'systemd',
    },
    {
        'name': 'Google Scraper',
        'service_name': 'google-state-workers',
        'icon': 'travel_explore',
        'check_type': 'systemd',
    },
    {
        'name': 'Verification',
        'service_name': 'washdb-verification',
        'icon': 'verified',
        'check_type': 'systemd',
    },
    {
        'name': 'Standardization',
        'service_name': 'washdb-standardization-browser',
        'icon': 'auto_fix_high',
        'check_type': 'systemd',
    },
    {
        'name': 'Browser Pool',
        'process_name': 'chromium|headless_shell',
        'icon': 'web',
        'check_type': 'process',
    },
    {
        'name': 'Xvfb',
        'process_name': 'Xvfb',
        'icon': 'monitor',
        'check_type': 'process',
    },
    {
        'name': 'Database',
        'icon': 'storage',
        'check_type': 'database',
    },
]


def get_overall_system_status() -> ServiceStatus:
    """Calculate overall system status from all services."""
    has_error = False
    has_warning = False

    for card in state.service_cards:
        status_info = card.get_status()
        status = status_info.get('status', ServiceStatus.UNKNOWN)

        if status == ServiceStatus.ERROR:
            has_error = True
        elif status in (ServiceStatus.WARNING, ServiceStatus.STOPPED):
            has_warning = True

    # Check for unresolved critical errors
    try:
        stats = get_error_stats()
        if stats.get('critical_unresolved', 0) > 0:
            has_error = True
        elif stats.get('error_unresolved', 0) > 5:
            has_warning = True
    except:
        pass

    if has_error:
        return ServiceStatus.ERROR
    elif has_warning:
        return ServiceStatus.WARNING
    return ServiceStatus.HEALTHY


def update_services():
    """Update all service status cards."""
    for card in state.service_cards:
        card.update()

    # Update overall status
    state.overall_status = get_overall_system_status()


def system_monitor_page():
    """Render the system monitor page."""
    ui.label('System Monitor').classes('text-3xl font-bold mb-4')

    # Overall status banner
    with ui.row().classes('w-full mb-4 items-center gap-4'):
        status = get_overall_system_status()
        if status == ServiceStatus.HEALTHY:
            ui.badge('SYSTEM HEALTHY', color='positive').classes('text-lg px-4 py-2')
            ui.icon('check_circle', color='positive').classes('text-3xl')
        elif status == ServiceStatus.WARNING:
            ui.badge('SYSTEM WARNING', color='warning').classes('text-lg px-4 py-2')
            ui.icon('warning', color='warning').classes('text-3xl')
        else:
            ui.badge('SYSTEM ERROR', color='negative').classes('text-lg px-4 py-2')
            ui.icon('error', color='negative').classes('text-3xl')

        ui.space()

        ui.label(f"Last updated: {datetime.now().strftime('%H:%M:%S')}").classes('text-sm text-gray-400')
        ui.button(icon='refresh', on_click=update_services).props('flat').tooltip('Refresh all')

    # Create tabs for organization
    with ui.tabs().classes('w-full') as tabs:
        tab_overview = ui.tab('Overview', icon='dashboard')
        tab_errors = ui.tab('Errors', icon='error_outline')
        tab_healing = ui.tab('Self-Healing', icon='healing')
        tab_logs = ui.tab('Logs', icon='article')

    with ui.tab_panels(tabs, value=tab_overview).classes('w-full'):
        # ======================
        # TAB 1: OVERVIEW
        # ======================
        with ui.tab_panel(tab_overview):
            # Service status grid
            ui.label('Service Status').classes('text-xl font-bold mb-3')

            with ui.grid(columns=4).classes('w-full gap-4 mb-6'):
                for svc in SERVICES:
                    card = ServiceStatusCard(
                        name=svc['name'],
                        service_name=svc.get('service_name'),
                        process_name=svc.get('process_name'),
                        icon=svc.get('icon', 'memory'),
                        check_type=svc.get('check_type', 'systemd'),
                    )
                    state.service_cards.append(card)
                    card.render()

            # Resource gauges
            resource_gauges_card(refresh_interval=5.0)

            # Quick error summary
            ui.label('Recent Errors Summary').classes('text-xl font-bold mt-6 mb-3')
            with ui.card().classes('w-full p-4'):
                try:
                    stats = get_error_stats()
                    with ui.row().classes('w-full gap-4'):
                        with ui.column().classes('flex-1'):
                            ui.label("Last 24 Hours").classes('text-sm text-gray-400')
                            ui.label(str(stats.get('total_24h', 0))).classes('text-2xl font-bold')
                            ui.label("total errors").classes('text-xs text-gray-400')

                        with ui.column().classes('flex-1'):
                            critical = stats.get('critical_unresolved', 0)
                            color = 'text-red-500' if critical > 0 else ''
                            ui.label("Critical Unresolved").classes(f'text-sm text-gray-400')
                            ui.label(str(critical)).classes(f'text-2xl font-bold {color}')

                        with ui.column().classes('flex-1'):
                            ui.label("Auto-Healed").classes('text-sm text-gray-400')
                            ui.label(str(stats.get('auto_resolved', 0))).classes('text-2xl font-bold text-green-500')

                        ui.button('View All Errors', icon='arrow_forward', on_click=lambda: tabs.set_value(tab_errors)).props('outline')
                except Exception as e:
                    ui.label(f"Error loading stats: {e}").classes('text-red-500')

        # ======================
        # TAB 2: ERRORS
        # ======================
        with ui.tab_panel(tab_errors):
            error_feed_card(refresh_interval=10.0)

        # ======================
        # TAB 3: SELF-HEALING
        # ======================
        with ui.tab_panel(tab_healing):
            self_healing_card(refresh_interval=30.0)

            # Add healing patterns documentation
            ui.label('Active Healing Patterns').classes('text-xl font-bold mt-6 mb-3')
            with ui.card().classes('w-full p-4'):
                patterns = [
                    ('Chrome Overflow', '3+ Chrome crash errors in 10 min', 'chrome_cleanup'),
                    ('Xvfb Failure', '1 Xvfb error in 5 min', 'xvfb_restart'),
                    ('Service Stale', '2 stale heartbeat errors in 10 min', 'restart_service'),
                    ('Stuck Jobs', '5 stuck job errors in 30 min', 'clear_stuck_jobs'),
                    ('CAPTCHA Storm', '10 CAPTCHA errors in 15 min', 'browser_pool_drain'),
                ]

                with ui.grid(columns=3).classes('w-full gap-4'):
                    for pattern_name, trigger, action in patterns:
                        with ui.card().classes('p-3'):
                            ui.label(pattern_name).classes('font-bold')
                            ui.label(trigger).classes('text-xs text-gray-400')
                            ui.badge(action, color='primary').classes('mt-2')

        # ======================
        # TAB 4: LOGS
        # ======================
        with ui.tab_panel(tab_logs):
            ui.label('Live Log Viewer').classes('text-xl font-bold mb-3')

            # Log file selector and controls
            with ui.card().classes('w-full p-4 mb-4'):
                with ui.row().classes('w-full items-center gap-4'):
                    log_files = [
                        'seo_jobs.log',
                        'seo_jobs_error.log',
                        'google_worker_1.log',
                        'yp_worker_1.log',
                        'verification.log',
                        'browser_pool.log',
                        'serp_session_pool.log',
                    ]

                    log_select = ui.select(
                        log_files,
                        value='seo_jobs.log',
                        label='Log File'
                    ).classes('w-64')

                    level_select = ui.select(
                        ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        value='ALL',
                        label='Level'
                    ).classes('w-32')

                    search_input = ui.input('Search...').classes('flex-1')

                    ui.button('Refresh', icon='refresh').props('outline')
                    ui.button('Clear', icon='clear_all').props('outline')

            # Log viewer
            with ui.card().classes('w-full p-4'):
                log_element = ui.log(max_lines=500).classes('w-full h-96')

                # Try to load initial log content
                try:
                    from pathlib import Path
                    log_path = Path('logs') / 'seo_jobs.log'
                    if log_path.exists():
                        with open(log_path, 'r') as f:
                            lines = f.readlines()[-200:]
                            for line in lines:
                                log_element.push(line.rstrip())
                except Exception as e:
                    log_element.push(f"Error loading log: {e}")

    # Start update timer
    state.update_timer = ui.timer(5.0, update_services)
