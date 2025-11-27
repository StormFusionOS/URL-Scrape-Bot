"""
GPU monitoring widget for NiceGUI dashboard.

Displays real-time NVIDIA GPU stats:
- GPU utilization
- Memory usage
- Temperature
- Running processes (Ollama model)
"""

import subprocess
from nicegui import ui
from typing import Dict, Optional


def get_gpu_stats() -> Optional[Dict]:
    """
    Get GPU statistics using nvidia-smi.

    Returns:
        Dict with GPU stats or None if nvidia-smi fails
    """
    try:
        result = subprocess.run(
            [
                'nvidia-smi',
                '--query-gpu=name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,power.limit',
                '--format=csv,noheader,nounits'
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return None

        parts = result.stdout.strip().split(', ')
        if len(parts) < 8:
            return None

        return {
            'name': parts[0].strip(),
            'gpu_util': int(parts[1].strip()),
            'mem_util': int(parts[2].strip()),
            'mem_used': int(parts[3].strip()),
            'mem_total': int(parts[4].strip()),
            'temperature': int(parts[5].strip()),
            'power_draw': float(parts[6].strip()) if parts[6].strip() != '[N/A]' else 0,
            'power_limit': float(parts[7].strip()) if parts[7].strip() != '[N/A]' else 0,
        }
    except Exception as e:
        return None


def get_ollama_status() -> Optional[Dict]:
    """
    Get Ollama model status.

    Returns:
        Dict with model info or None
    """
    try:
        result = subprocess.run(
            ['ollama', 'ps'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return None

        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            return {'loaded': False, 'model': None}

        # Parse second line (first is header)
        parts = lines[1].split()
        if len(parts) >= 4:
            return {
                'loaded': True,
                'model': parts[0],
                'size': parts[2] + ' ' + parts[3] if len(parts) > 3 else parts[2],
                'processor': parts[4] if len(parts) > 4 else 'N/A'
            }
        return {'loaded': False, 'model': None}
    except Exception:
        return None


class GPUMonitorWidget:
    """GPU monitoring widget with auto-refresh."""

    def __init__(self, refresh_interval: float = 2.0):
        self.refresh_interval = refresh_interval
        self.gpu_util_label = None
        self.mem_label = None
        self.temp_label = None
        self.power_label = None
        self.model_label = None
        self.gpu_bar = None
        self.mem_bar = None
        self.timer = None

    def render(self):
        """Render the GPU monitor widget."""
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center mb-2'):
                ui.icon('memory', size='md').classes('text-green-400')
                ui.label('GPU Monitor').classes('text-lg font-bold')
                ui.space()
                ui.badge('LIVE', color='green').classes('animate-pulse')

            # GPU name
            stats = get_gpu_stats()
            gpu_name = stats['name'] if stats else 'GPU Not Detected'
            ui.label(gpu_name).classes('text-sm text-gray-400 mb-3')

            # Stats grid
            with ui.grid(columns=2).classes('w-full gap-3'):
                # GPU Utilization
                with ui.card().classes('bg-gray-800 p-3'):
                    ui.label('GPU Usage').classes('text-xs text-gray-400')
                    self.gpu_util_label = ui.label('0%').classes('text-xl font-bold text-green-400')
                    self.gpu_bar = ui.linear_progress(value=0, show_value=False).classes('mt-1').props('color=green')

                # Memory Usage
                with ui.card().classes('bg-gray-800 p-3'):
                    ui.label('VRAM').classes('text-xs text-gray-400')
                    self.mem_label = ui.label('0 / 0 GB').classes('text-xl font-bold text-blue-400')
                    self.mem_bar = ui.linear_progress(value=0, show_value=False).classes('mt-1').props('color=blue')

                # Temperature
                with ui.card().classes('bg-gray-800 p-3'):
                    ui.label('Temperature').classes('text-xs text-gray-400')
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('thermostat', size='sm').classes('text-orange-400')
                        self.temp_label = ui.label('0°C').classes('text-xl font-bold text-orange-400')

                # Power
                with ui.card().classes('bg-gray-800 p-3'):
                    ui.label('Power').classes('text-xs text-gray-400')
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('bolt', size='sm').classes('text-yellow-400')
                        self.power_label = ui.label('0W').classes('text-xl font-bold text-yellow-400')

            # Ollama Model Status
            ui.separator().classes('my-3')
            with ui.row().classes('w-full items-center'):
                ui.icon('smart_toy', size='sm').classes('text-purple-400')
                ui.label('LLM Model:').classes('text-sm text-gray-400')
                self.model_label = ui.label('Checking...').classes('text-sm font-semibold text-purple-400')

        # Start auto-refresh timer
        self.timer = ui.timer(self.refresh_interval, self._update_stats)

        # Initial update
        self._update_stats()

    def _update_stats(self):
        """Update GPU statistics."""
        stats = get_gpu_stats()

        if stats:
            # Update GPU utilization
            if self.gpu_util_label:
                self.gpu_util_label.set_text(f"{stats['gpu_util']}%")
            if self.gpu_bar:
                self.gpu_bar.value = stats['gpu_util'] / 100

            # Update memory
            mem_used_gb = stats['mem_used'] / 1024
            mem_total_gb = stats['mem_total'] / 1024
            if self.mem_label:
                self.mem_label.set_text(f"{mem_used_gb:.1f} / {mem_total_gb:.1f} GB")
            if self.mem_bar:
                self.mem_bar.value = stats['mem_used'] / stats['mem_total']

            # Update temperature with color coding
            temp = stats['temperature']
            if self.temp_label:
                self.temp_label.set_text(f"{temp}°C")
                if temp > 80:
                    self.temp_label.classes(replace='text-xl font-bold text-red-400')
                elif temp > 70:
                    self.temp_label.classes(replace='text-xl font-bold text-orange-400')
                else:
                    self.temp_label.classes(replace='text-xl font-bold text-green-400')

            # Update power
            if self.power_label and stats['power_draw'] > 0:
                self.power_label.set_text(f"{stats['power_draw']:.0f}W")
        else:
            # GPU not available
            if self.gpu_util_label:
                self.gpu_util_label.set_text('N/A')
            if self.mem_label:
                self.mem_label.set_text('N/A')
            if self.temp_label:
                self.temp_label.set_text('N/A')
            if self.power_label:
                self.power_label.set_text('N/A')

        # Update Ollama status
        ollama = get_ollama_status()
        if self.model_label:
            if ollama and ollama.get('loaded'):
                self.model_label.set_text(f"{ollama['model']} ({ollama.get('size', 'N/A')})")
                self.model_label.classes(replace='text-sm font-semibold text-green-400')
            elif ollama:
                self.model_label.set_text('No model loaded')
                self.model_label.classes(replace='text-sm font-semibold text-yellow-400')
            else:
                self.model_label.set_text('Ollama not running')
                self.model_label.classes(replace='text-sm font-semibold text-red-400')


def gpu_monitor_card(refresh_interval: float = 2.0) -> GPUMonitorWidget:
    """
    Create and render a GPU monitor card.

    Args:
        refresh_interval: Seconds between stat updates

    Returns:
        GPUMonitorWidget instance
    """
    widget = GPUMonitorWidget(refresh_interval=refresh_interval)
    widget.render()
    return widget
