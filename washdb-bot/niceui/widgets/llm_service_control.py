"""
LLM Service control widget for NiceGUI dashboard.

Displays status and provides start/stop controls for the shared LLM service.
"""

import subprocess
import os
import signal
from nicegui import ui
from typing import Optional
from pathlib import Path


# Service configuration
LLM_SERVICE_SOCKET = "/tmp/llm_service.sock"
LLM_SERVICE_PID_FILE = "/tmp/llm_service.pid"
PROJECT_ROOT = Path(__file__).parent.parent.parent


def is_service_running() -> bool:
    """Check if LLM service is running."""
    return os.path.exists(LLM_SERVICE_SOCKET)


def get_service_pid() -> Optional[int]:
    """Get the PID of the running LLM service."""
    try:
        # Check PID file
        if os.path.exists(LLM_SERVICE_PID_FILE):
            with open(LLM_SERVICE_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
                # Verify process exists
                os.kill(pid, 0)
                return pid
    except (ValueError, ProcessLookupError, PermissionError):
        pass

    # Try to find by process name
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'llm_service.py'],
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
    """Start the LLM service."""
    if is_service_running():
        return True, "Service already running"

    try:
        # Start service in background
        venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
        service_script = PROJECT_ROOT / "verification" / "llm_service.py"

        process = subprocess.Popen(
            [str(venv_python), str(service_script)],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Save PID
        with open(LLM_SERVICE_PID_FILE, 'w') as f:
            f.write(str(process.pid))

        # Wait a moment for service to start
        import time
        time.sleep(1)

        if is_service_running():
            return True, f"Service started (PID: {process.pid})"
        else:
            return False, "Service failed to start"

    except Exception as e:
        return False, f"Error starting service: {e}"


def stop_service() -> tuple[bool, str]:
    """Stop the LLM service."""
    pid = get_service_pid()

    if not pid:
        # Clean up socket if orphaned
        if os.path.exists(LLM_SERVICE_SOCKET):
            try:
                os.unlink(LLM_SERVICE_SOCKET)
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
                os.kill(pid, 0)  # Check if still running
            except ProcessLookupError:
                break
        else:
            # Force kill if still running
            os.kill(pid, signal.SIGKILL)

        # Clean up files
        for f in [LLM_SERVICE_SOCKET, LLM_SERVICE_PID_FILE]:
            if os.path.exists(f):
                try:
                    os.unlink(f)
                except:
                    pass

        return True, "Service stopped"

    except Exception as e:
        return False, f"Error stopping service: {e}"


class LLMServiceWidget:
    """LLM Service control widget with auto-refresh."""

    def __init__(self, refresh_interval: float = 2.0):
        self.refresh_interval = refresh_interval
        self.status_badge = None
        self.status_label = None
        self.start_btn = None
        self.stop_btn = None
        self.timer = None

    def render(self):
        """Render the LLM service control widget."""
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center mb-2'):
                ui.icon('hub', size='md').classes('text-purple-400')
                ui.label('LLM Service').classes('text-lg font-bold')
                ui.space()
                self.status_badge = ui.badge('CHECKING', color='grey').classes('text-xs')

            # Status info
            self.status_label = ui.label('Checking service status...').classes('text-sm text-gray-400 mb-3')

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
                ui.label('Shared LLM queue for steady GPU usage').classes('text-xs text-gray-500')

        # Start auto-refresh timer
        self.timer = ui.timer(self.refresh_interval, self._update_status)

        # Initial update
        self._update_status()

    def _update_status(self):
        """Update service status display."""
        running = is_service_running()
        pid = get_service_pid()

        if running:
            if self.status_badge:
                self.status_badge.set_text('RUNNING')
                self.status_badge.props('color=positive')
            if self.status_label:
                self.status_label.set_text(f'Service running (PID: {pid or "?"}) - GPU queue active')
            if self.start_btn:
                self.start_btn.disable()
            if self.stop_btn:
                self.stop_btn.enable()
        else:
            if self.status_badge:
                self.status_badge.set_text('STOPPED')
                self.status_badge.props('color=negative')
            if self.status_label:
                self.status_label.set_text('Service not running - workers using direct Ollama calls')
            if self.start_btn:
                self.start_btn.enable()
            if self.stop_btn:
                self.stop_btn.disable()

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


def llm_service_card(refresh_interval: float = 2.0) -> LLMServiceWidget:
    """
    Create and render an LLM service control card.

    Args:
        refresh_interval: Seconds between status checks

    Returns:
        LLMServiceWidget instance
    """
    widget = LLMServiceWidget(refresh_interval=refresh_interval)
    widget.render()
    return widget
