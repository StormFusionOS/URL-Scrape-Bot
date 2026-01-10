"""
Resource Gauges widget - displays CPU, RAM, Swap, Disk, GPU usage.
"""

import subprocess
from typing import Optional, Tuple
from nicegui import ui


def get_cpu_usage() -> float:
    """Get CPU usage percentage."""
    try:
        # Use /proc/stat for accurate CPU reading
        with open('/proc/stat', 'r') as f:
            line = f.readline()
        parts = line.split()
        if parts[0] == 'cpu':
            # cpu user nice system idle iowait irq softirq steal guest guest_nice
            user = int(parts[1])
            nice = int(parts[2])
            system = int(parts[3])
            idle = int(parts[4])
            iowait = int(parts[5]) if len(parts) > 5 else 0

            total = user + nice + system + idle + iowait
            active = user + nice + system

            # Simple approximation
            return (active / total * 100) if total > 0 else 0.0
    except:
        pass

    # Fallback to top
    try:
        result = subprocess.run(
            ["top", "-bn1"],
            capture_output=True,
            text=True,
            timeout=5
        )
        for line in result.stdout.split('\n'):
            if '%Cpu' in line or 'Cpu(s)' in line:
                # Parse CPU line
                parts = line.replace(',', ' ').split()
                for i, part in enumerate(parts):
                    if part in ('us', 'user'):
                        return float(parts[i - 1])
    except:
        pass

    return 0.0


def get_memory_usage() -> Tuple[float, float, float]:
    """
    Get memory usage.

    Returns:
        Tuple of (used_percent, used_gb, total_gb)
    """
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(':')] = int(parts[1])

        total = meminfo.get('MemTotal', 0) / 1024 / 1024  # GB
        free = meminfo.get('MemFree', 0) / 1024 / 1024
        buffers = meminfo.get('Buffers', 0) / 1024 / 1024
        cached = meminfo.get('Cached', 0) / 1024 / 1024

        used = total - free - buffers - cached
        percent = (used / total * 100) if total > 0 else 0

        return percent, used, total
    except:
        return 0.0, 0.0, 0.0


def get_swap_usage() -> Tuple[float, float, float]:
    """
    Get swap usage.

    Returns:
        Tuple of (used_percent, used_gb, total_gb)
    """
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(':')] = int(parts[1])

        total = meminfo.get('SwapTotal', 0) / 1024 / 1024  # GB
        free = meminfo.get('SwapFree', 0) / 1024 / 1024

        used = total - free
        percent = (used / total * 100) if total > 0 else 0

        return percent, used, total
    except:
        return 0.0, 0.0, 0.0


def get_disk_usage(path: str = '/') -> Tuple[float, float, float]:
    """
    Get disk usage for a path.

    Returns:
        Tuple of (used_percent, used_gb, total_gb)
    """
    try:
        result = subprocess.run(
            ["df", "-BG", path],
            capture_output=True,
            text=True,
            timeout=5
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 5:
                total = float(parts[1].rstrip('G'))
                used = float(parts[2].rstrip('G'))
                percent = float(parts[4].rstrip('%'))
                return percent, used, total
    except:
        pass
    return 0.0, 0.0, 0.0


def get_gpu_info() -> dict:
    """
    Get NVIDIA GPU info.

    Returns:
        Dict with: temp, memory_used, memory_total, utilization, name
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,memory.used,memory.total,utilization.gpu,name",
             "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(',')
            if len(parts) >= 5:
                return {
                    'temp': float(parts[0].strip()),
                    'memory_used': float(parts[1].strip()) / 1024,  # GB
                    'memory_total': float(parts[2].strip()) / 1024,  # GB
                    'utilization': float(parts[3].strip()),
                    'name': parts[4].strip(),
                    'available': True
                }
    except:
        pass
    return {'available': False}


def get_chrome_process_count() -> int:
    """Get count of Chrome/Chromium processes."""
    try:
        result = subprocess.run(
            ["pgrep", "-c", "-f", "chromium|chrome|headless_shell"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return int(result.stdout.strip()) if result.stdout.strip() else 0
    except:
        return 0


def get_gauge_color(percent: float) -> str:
    """Get color based on percentage threshold."""
    if percent >= 90:
        return 'negative'
    elif percent >= 70:
        return 'warning'
    return 'positive'


class ResourceGauge:
    """A single resource gauge with label and progress bar."""

    def __init__(self, name: str, icon: str, unit: str = "%"):
        self.name = name
        self.icon = icon
        self.unit = unit
        self.progress = None
        self.value_label = None
        self.detail_label = None

    def update(self, percent: float, detail: str = ""):
        """Update the gauge values."""
        if self.progress:
            self.progress.value = percent / 100
            self.progress.props(f'color={get_gauge_color(percent)}')
        if self.value_label:
            self.value_label.set_text(f"{percent:.1f}{self.unit}")
        if self.detail_label:
            self.detail_label.set_text(detail)

    def render(self) -> ui.element:
        """Render the gauge."""
        with ui.column().classes('w-full gap-1') as col:
            with ui.row().classes('w-full items-center'):
                ui.icon(self.icon).classes('text-lg')
                ui.label(self.name).classes('text-sm font-semibold flex-1')
                self.value_label = ui.label("0%").classes('text-sm font-mono')

            self.progress = ui.linear_progress(value=0, show_value=False).classes('w-full')
            self.detail_label = ui.label("").classes('text-xs text-gray-400')

        return col


class ResourceGaugesPanel:
    """Panel containing all resource gauges."""

    def __init__(self):
        self.cpu_gauge = ResourceGauge("CPU", "memory", "%")
        self.ram_gauge = ResourceGauge("RAM", "data_usage", "%")
        self.swap_gauge = ResourceGauge("Swap", "swap_horiz", "%")
        self.disk_gauge = ResourceGauge("Disk", "storage", "%")
        self.gpu_gauge = ResourceGauge("GPU", "developer_board", "%")
        self.chrome_label = None

    def update(self):
        """Update all gauges."""
        # CPU
        cpu = get_cpu_usage()
        self.cpu_gauge.update(cpu)

        # RAM
        ram_pct, ram_used, ram_total = get_memory_usage()
        self.ram_gauge.update(ram_pct, f"{ram_used:.1f}GB / {ram_total:.1f}GB")

        # Swap
        swap_pct, swap_used, swap_total = get_swap_usage()
        if swap_total > 0:
            self.swap_gauge.update(swap_pct, f"{swap_used:.1f}GB / {swap_total:.1f}GB")
        else:
            self.swap_gauge.update(0, "No swap")

        # Disk
        disk_pct, disk_used, disk_total = get_disk_usage('/')
        self.disk_gauge.update(disk_pct, f"{disk_used:.0f}GB / {disk_total:.0f}GB")

        # GPU
        gpu = get_gpu_info()
        if gpu.get('available'):
            self.gpu_gauge.update(
                gpu['utilization'],
                f"{gpu['memory_used']:.1f}GB / {gpu['memory_total']:.1f}GB | {gpu['temp']:.0f}C"
            )
        else:
            self.gpu_gauge.update(0, "Not available")

        # Chrome count
        chrome_count = get_chrome_process_count()
        if self.chrome_label:
            color = 'red' if chrome_count > 100 else ('yellow' if chrome_count > 50 else 'green')
            self.chrome_label.set_text(f"Chrome Processes: {chrome_count}")
            self.chrome_label.style(f'color: {color};')

    def render(self) -> ui.card:
        """Render the resource gauges panel."""
        with ui.card().classes('w-full p-4') as card:
            ui.label("System Resources").classes('text-lg font-bold mb-3')

            with ui.grid(columns=5).classes('w-full gap-4'):
                self.cpu_gauge.render()
                self.ram_gauge.render()
                self.swap_gauge.render()
                self.disk_gauge.render()
                self.gpu_gauge.render()

            # Chrome process counter
            with ui.row().classes('w-full mt-3 items-center gap-4'):
                ui.icon("web").classes('text-lg')
                self.chrome_label = ui.label("Chrome Processes: 0").classes('text-sm font-mono')

            # Initial update
            self.update()

        return card


def resource_gauges_card(refresh_interval: float = 5.0) -> ui.card:
    """
    Create a resource gauges card with auto-refresh.

    Args:
        refresh_interval: How often to refresh in seconds

    Returns:
        The card element
    """
    panel = ResourceGaugesPanel()
    card = panel.render()

    # Add timer for auto-refresh
    ui.timer(refresh_interval, panel.update)

    return card
