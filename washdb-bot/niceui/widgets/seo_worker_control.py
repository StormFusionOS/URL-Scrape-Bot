"""
SEO Worker Service control widget for NiceGUI dashboard.

Displays status and provides start/stop controls for the SEO worker service.
Shows live statistics via heartbeat updates.
"""

import subprocess
import os
import signal
import json
import socket
from nicegui import ui
from typing import Optional, Dict
from pathlib import Path


# Service configuration
SEO_SERVICE_SOCKET = "/tmp/seo_worker.sock"
SEO_SERVICE_PID_FILE = "/tmp/seo_worker.pid"
PROJECT_ROOT = Path(__file__).parent.parent.parent


def is_service_running() -> bool:
    """Check if SEO worker service is running."""
    return os.path.exists(SEO_SERVICE_SOCKET)


def get_service_status() -> Optional[Dict]:
    """Get current service status via socket."""
    if not is_service_running():
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(SEO_SERVICE_SOCKET)

        # Read one status update
        data = b""
        while True:
            chunk = sock.recv(1)
            if not chunk or chunk == b"\n":
                break
            data += chunk

        sock.close()
        return json.loads(data.decode('utf-8'))
    except:
        return None


def get_service_pid() -> Optional[int]:
    """Get the PID of the running SEO service."""
    try:
        if os.path.exists(SEO_SERVICE_PID_FILE):
            with open(SEO_SERVICE_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
                # Verify process exists
                os.kill(pid, 0)
                return pid
    except (ValueError, ProcessLookupError, PermissionError):
        pass

    # Try to find by process name
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'seo_worker_service.py'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except Exception:
        pass

    return None


def start_service() -> tuple[bool, str]:
    """Start the SEO worker service."""
    if is_service_running():
        return True, "Service already running"

    try:
        venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
        service_script = PROJECT_ROOT / "seo_intelligence" / "seo_worker_service.py"

        # Set PYTHONPATH
        env = os.environ.copy()
        env['PYTHONPATH'] = str(PROJECT_ROOT)

        process = subprocess.Popen(
            [str(venv_python), str(service_script)],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Wait for service to start
        import time
        time.sleep(2)

        if is_service_running():
            return True, f"Service started (PID: {process.pid})"
        else:
            return False, "Service failed to start"

    except Exception as e:
        return False, f"Error starting service: {e}"


def stop_service() -> tuple[bool, str]:
    """Stop the SEO worker service."""
    pid = get_service_pid()

    if not pid:
        # Clean up socket if orphaned
        if os.path.exists(SEO_SERVICE_SOCKET):
            try:
                os.unlink(SEO_SERVICE_SOCKET)
            except:
                pass
        return True, "Service not running"

    try:
        # Send SIGTERM
        os.kill(pid, signal.SIGTERM)

        # Wait for graceful shutdown
        import time
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            # Force kill if still running
            os.kill(pid, signal.SIGKILL)

        # Clean up files
        for f in [SEO_SERVICE_SOCKET, SEO_SERVICE_PID_FILE]:
            if os.path.exists(f):
                try:
                    os.unlink(f)
                except:
                    pass

        return True, "Service stopped"

    except Exception as e:
        return False, f"Error stopping service: {e}"


class SEOWorkerWidget:
    """SEO Worker control widget with live stats."""

    def __init__(self, refresh_interval: float = 5.0):
        self.refresh_interval = refresh_interval
        self.status_badge = None
        self.status_label = None
        self.stats_container = None
        self.start_btn = None
        self.stop_btn = None
        self.timer = None

    def render(self):
        """Render the SEO worker control widget."""
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center mb-2'):
                ui.icon('search', size='md').classes('text-blue-400')
                ui.label('SEO Worker').classes('text-lg font-bold')
                ui.space()
                self.status_badge = ui.badge('CHECKING', color='grey').classes('text-xs')

            # Status info
            self.status_label = ui.label('Checking service status...').classes('text-sm text-gray-400 mb-2')

            # Live stats container
            self.stats_container = ui.column().classes('w-full gap-1 mb-3')

            # Control buttons
            with ui.row().classes('w-full gap-2'):
                self.start_btn = ui.button(
                    'Start Service',
                    icon='play_arrow',
                    color='positive',
                    on_click=self._on_start
                ).classes('flex-1')

                self.stop_btn = ui.button(
                    'Stop Service',
                    icon='stop',
                    color='negative',
                    on_click=self._on_stop
                ).classes('flex-1')

            # Info text
            ui.separator().classes('my-3')
            with ui.row().classes('w-full items-center'):
                ui.icon('info', size='sm').classes('text-gray-500')
                ui.label('Continuous SEO audits on company websites').classes('text-xs text-gray-500')

        # Start auto-refresh timer
        self.timer = ui.timer(self.refresh_interval, self._update_status)

        # Initial update
        self._update_status()

    def _update_status(self):
        """Update service status display."""
        running = is_service_running()
        status = get_service_status() if running else None

        if running and status:
            if self.status_badge:
                self.status_badge.set_text('RUNNING')
                self.status_badge.props('color=positive')

            # Update stats
            self._update_stats(status)

            if self.start_btn:
                self.start_btn.disable()
            if self.stop_btn:
                self.stop_btn.enable()

        elif running:
            if self.status_badge:
                self.status_badge.set_text('STARTING')
                self.status_badge.props('color=warning')
            if self.status_label:
                self.status_label.set_text('Service starting up...')
            if self.start_btn:
                self.start_btn.disable()
            if self.stop_btn:
                self.stop_btn.enable()
        else:
            if self.status_badge:
                self.status_badge.set_text('STOPPED')
                self.status_badge.props('color=negative')
            if self.status_label:
                self.status_label.set_text('Service not running')
            if self.stats_container:
                self.stats_container.clear()
            if self.start_btn:
                self.start_btn.enable()
            if self.stop_btn:
                self.stop_btn.disable()

    def _update_stats(self, status: Dict):
        """Update stats display."""
        if not self.stats_container:
            return

        try:
            self.stats_container.clear()

            with self.stats_container:
                # Current activity
                current = status.get('current_company', 'Idle')
                if current:
                    ui.label(f'📍 Current: {current[:40]}...').classes('text-xs text-green-400')
                else:
                    ui.label('📍 Idle - waiting for work').classes('text-xs text-gray-400')

                # Stats row
                with ui.row().classes('gap-4'):
                    ui.label(f"✓ {status.get('audits_completed', 0)} audits").classes('text-xs text-blue-300')
                    ui.label(f"⚡ {status.get('companies_processed', 0)} processed").classes('text-xs text-gray-300')
                    ui.label(f"⚠ {status.get('errors', 0)} errors").classes('text-xs text-red-300')

                # Queue and uptime
                with ui.row().classes('gap-4'):
                    ui.label(f"📦 Queue: {status.get('queue_size', 0)}").classes('text-xs text-gray-400')
                    uptime_min = status.get('uptime_seconds', 0) // 60
                    ui.label(f"⏱ Uptime: {uptime_min}m").classes('text-xs text-gray-400')

            if self.status_label:
                self.status_label.set_text(f"Running - {status.get('audits_completed', 0)} audits complete")

        except Exception:
            pass

    async def _on_start(self):
        """Handle start button click."""
        self.start_btn.disable()
        self.status_label.set_text('Starting service...')

        success, message = start_service()

        if success:
            ui.notify(message, type='positive')
        else:
            ui.notify(message, type='negative')

        self._update_status()

    async def _on_stop(self):
        """Handle stop button click."""
        self.stop_btn.disable()
        self.status_label.set_text('Stopping service...')

        success, message = stop_service()

        if success:
            ui.notify(message, type='info')
        else:
            ui.notify(message, type='negative')

        self._update_status()


def seo_worker_card(refresh_interval: float = 5.0) -> SEOWorkerWidget:
    """
    Create and render an SEO worker control card.

    Args:
        refresh_interval: Seconds between status checks

    Returns:
        SEOWorkerWidget instance
    """
    widget = SEOWorkerWidget(refresh_interval=refresh_interval)
    widget.render()
    return widget
