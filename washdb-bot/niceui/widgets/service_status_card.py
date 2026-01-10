"""
Service Status Card widget - displays status and controls for a single service.
"""

import subprocess
from datetime import datetime
from typing import Optional, Callable
from nicegui import ui


class ServiceStatus:
    """Represents the status of a service."""
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


def get_service_status(service_name: str) -> dict:
    """
    Get the status of a systemd service.

    Returns:
        Dict with keys: status, active, running, last_heartbeat
    """
    try:
        # Check if service is active
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        is_active = result.stdout.strip() == "active"

        # Get more details
        result = subprocess.run(
            ["systemctl", "show", service_name, "--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp"],
            capture_output=True,
            text=True,
            timeout=5
        )

        props = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                props[key] = value

        active_state = props.get('ActiveState', 'unknown')
        sub_state = props.get('SubState', 'unknown')
        main_pid = props.get('MainPID', '0')
        start_time = props.get('ExecMainStartTimestamp', '')

        # Determine status
        if active_state == 'active' and sub_state == 'running':
            status = ServiceStatus.HEALTHY
        elif active_state == 'active':
            status = ServiceStatus.WARNING
        elif active_state in ('inactive', 'dead'):
            status = ServiceStatus.STOPPED
        elif active_state == 'failed':
            status = ServiceStatus.ERROR
        else:
            status = ServiceStatus.UNKNOWN

        return {
            'status': status,
            'active': is_active,
            'running': sub_state == 'running',
            'pid': main_pid if main_pid != '0' else None,
            'start_time': start_time if start_time else None,
            'active_state': active_state,
            'sub_state': sub_state,
        }

    except subprocess.TimeoutExpired:
        return {'status': ServiceStatus.UNKNOWN, 'active': False, 'running': False, 'error': 'Timeout'}
    except Exception as e:
        return {'status': ServiceStatus.UNKNOWN, 'active': False, 'running': False, 'error': str(e)}


def check_process_running(process_name: str) -> dict:
    """
    Check if a process is running by name.

    Returns:
        Dict with keys: running, count, pids
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", process_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
        return {
            'running': len(pids) > 0,
            'count': len(pids),
            'pids': pids,
            'status': ServiceStatus.HEALTHY if pids else ServiceStatus.STOPPED
        }
    except Exception as e:
        return {'running': False, 'count': 0, 'pids': [], 'error': str(e), 'status': ServiceStatus.UNKNOWN}


def check_database_connection() -> dict:
    """Check if database is accessible."""
    try:
        import os
        from sqlalchemy import create_engine, text

        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return {'status': ServiceStatus.ERROR, 'connected': False, 'error': 'DATABASE_URL not set'}

        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {'status': ServiceStatus.HEALTHY, 'connected': True}
    except Exception as e:
        return {'status': ServiceStatus.ERROR, 'connected': False, 'error': str(e)}


STATUS_COLORS = {
    ServiceStatus.HEALTHY: 'positive',
    ServiceStatus.WARNING: 'warning',
    ServiceStatus.ERROR: 'negative',
    ServiceStatus.STOPPED: 'grey',
    ServiceStatus.UNKNOWN: 'grey',
}

STATUS_ICONS = {
    ServiceStatus.HEALTHY: 'check_circle',
    ServiceStatus.WARNING: 'warning',
    ServiceStatus.ERROR: 'error',
    ServiceStatus.STOPPED: 'stop_circle',
    ServiceStatus.UNKNOWN: 'help',
}


class ServiceStatusCard:
    """
    A card widget showing service status with controls.

    Usage:
        card = ServiceStatusCard(
            name="SEO Worker",
            service_name="seo-job-worker",
            icon="work"
        )
        card.render()
    """

    def __init__(
        self,
        name: str,
        service_name: Optional[str] = None,
        process_name: Optional[str] = None,
        icon: str = "memory",
        check_type: str = "systemd",  # "systemd", "process", "database", "custom"
        custom_check: Optional[Callable[[], dict]] = None,
        on_restart: Optional[Callable] = None,
    ):
        self.name = name
        self.service_name = service_name
        self.process_name = process_name
        self.icon = icon
        self.check_type = check_type
        self.custom_check = custom_check
        self.on_restart = on_restart

        self.status_badge = None
        self.status_label = None
        self.detail_label = None

    def get_status(self) -> dict:
        """Get current status based on check type."""
        if self.check_type == "systemd" and self.service_name:
            return get_service_status(self.service_name)
        elif self.check_type == "process" and self.process_name:
            return check_process_running(self.process_name)
        elif self.check_type == "database":
            return check_database_connection()
        elif self.check_type == "custom" and self.custom_check:
            return self.custom_check()
        else:
            return {'status': ServiceStatus.UNKNOWN, 'error': 'Invalid check type'}

    def update(self):
        """Update the card with current status."""
        status_info = self.get_status()
        status = status_info.get('status', ServiceStatus.UNKNOWN)

        if self.status_badge:
            self.status_badge.props(f'color={STATUS_COLORS[status]}')
            self.status_badge.set_text(status.upper())

        if self.status_label:
            if status == ServiceStatus.HEALTHY:
                self.status_label.set_text("Running")
            elif status == ServiceStatus.WARNING:
                self.status_label.set_text("Degraded")
            elif status == ServiceStatus.ERROR:
                self.status_label.set_text("Failed")
            elif status == ServiceStatus.STOPPED:
                self.status_label.set_text("Stopped")
            else:
                self.status_label.set_text("Unknown")

        if self.detail_label:
            details = []
            if status_info.get('pid'):
                details.append(f"PID: {status_info['pid']}")
            if status_info.get('count'):
                details.append(f"Processes: {status_info['count']}")
            if status_info.get('error'):
                details.append(f"Error: {status_info['error'][:30]}")
            self.detail_label.set_text(" | ".join(details) if details else "")

    async def restart_service(self):
        """Restart the service."""
        if self.on_restart:
            self.on_restart()
            return

        if self.check_type == "systemd" and self.service_name:
            try:
                ui.notify(f"Restarting {self.name}...", type="info")
                result = subprocess.run(
                    ["sudo", "systemctl", "restart", self.service_name],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    ui.notify(f"{self.name} restarted successfully", type="positive")
                else:
                    ui.notify(f"Failed to restart: {result.stderr}", type="negative")
                self.update()
            except Exception as e:
                ui.notify(f"Restart failed: {e}", type="negative")
        else:
            ui.notify("Restart not available for this service type", type="warning")

    async def stop_service(self):
        """Stop the service."""
        if self.check_type == "systemd" and self.service_name:
            try:
                ui.notify(f"Stopping {self.name}...", type="warning")
                result = subprocess.run(
                    ["sudo", "systemctl", "stop", self.service_name],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    ui.notify(f"{self.name} stopped", type="positive")
                else:
                    ui.notify(f"Failed to stop: {result.stderr}", type="negative")
                self.update()
            except Exception as e:
                ui.notify(f"Stop failed: {e}", type="negative")

    async def start_service(self):
        """Start the service."""
        if self.check_type == "systemd" and self.service_name:
            try:
                ui.notify(f"Starting {self.name}...", type="info")
                result = subprocess.run(
                    ["sudo", "systemctl", "start", self.service_name],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    ui.notify(f"{self.name} started", type="positive")
                else:
                    ui.notify(f"Failed to start: {result.stderr}", type="negative")
                self.update()
            except Exception as e:
                ui.notify(f"Start failed: {e}", type="negative")

    def render(self) -> ui.card:
        """Render the service status card."""
        status_info = self.get_status()
        status = status_info.get('status', ServiceStatus.UNKNOWN)

        with ui.card().classes('w-full p-3') as card:
            # Header row
            with ui.row().classes('w-full items-center gap-2'):
                ui.icon(self.icon).classes('text-2xl')
                ui.label(self.name).classes('text-lg font-bold flex-1')
                self.status_badge = ui.badge(
                    status.upper(),
                    color=STATUS_COLORS[status]
                )

            # Status details
            with ui.row().classes('w-full items-center mt-2'):
                ui.icon(STATUS_ICONS[status]).classes('text-lg')
                self.status_label = ui.label(
                    "Running" if status == ServiceStatus.HEALTHY else status.capitalize()
                ).classes('text-sm')

            # Detail line
            self.detail_label = ui.label("").classes('text-xs text-gray-400 mt-1')
            self.update()  # Populate details

            # Control buttons
            with ui.row().classes('w-full gap-2 mt-3'):
                if self.check_type == "systemd":
                    ui.button(icon='play_arrow', on_click=self.start_service).props('flat dense color=positive').tooltip("Start")
                    ui.button(icon='stop', on_click=self.stop_service).props('flat dense color=warning').tooltip("Stop")
                    ui.button(icon='refresh', on_click=self.restart_service).props('flat dense color=primary').tooltip("Restart")
                else:
                    ui.button(icon='refresh', on_click=self.update).props('flat dense').tooltip("Refresh")

        return card


def service_status_grid(services: list, columns: int = 3) -> ui.element:
    """
    Create a grid of service status cards.

    Args:
        services: List of dicts with keys: name, service_name or process_name, icon, check_type
        columns: Number of columns in grid

    Returns:
        UI element containing the grid
    """
    cards = []

    with ui.grid(columns=columns).classes('w-full gap-4') as grid:
        for svc in services:
            card = ServiceStatusCard(
                name=svc['name'],
                service_name=svc.get('service_name'),
                process_name=svc.get('process_name'),
                icon=svc.get('icon', 'memory'),
                check_type=svc.get('check_type', 'systemd'),
                custom_check=svc.get('custom_check'),
            )
            cards.append(card)
            card.render()

    # Return both grid and cards for external refresh
    grid.cards = cards
    return grid
