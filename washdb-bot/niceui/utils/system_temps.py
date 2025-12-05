"""
System temperature monitoring utilities.
"""
import subprocess
import re
from typing import Dict, Optional


def get_system_temps() -> Dict[str, Optional[float]]:
    """
    Get system temperatures from sensors and nvidia-smi.

    Returns:
        dict: Temperature data with keys:
            - cpu_package: CPU package temperature (°C)
            - gpu: GPU temperature (°C)
            - nvme_max: Highest NVMe drive temperature (°C)
            - nvme_avg: Average NVMe drive temperature (°C)
    """
    temps = {
        'cpu_package': None,
        'gpu': None,
        'nvme_max': None,
        'nvme_avg': None,
    }

    try:
        # Get CPU and NVMe temps from sensors
        result = subprocess.run(
            ['sensors'],
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            output = result.stdout

            # Extract CPU package temp
            cpu_match = re.search(r'Package id 0:\s+\+(\d+\.\d+)°C', output)
            if cpu_match:
                temps['cpu_package'] = float(cpu_match.group(1))

            # Extract NVMe temps
            nvme_temps = []
            for match in re.finditer(r'Composite:\s+\+(\d+\.\d+)°C', output):
                nvme_temps.append(float(match.group(1)))

            if nvme_temps:
                temps['nvme_max'] = max(nvme_temps)
                temps['nvme_avg'] = sum(nvme_temps) / len(nvme_temps)

    except Exception:
        pass

    try:
        # Get GPU temp from nvidia-smi
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'],
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            gpu_temp = result.stdout.strip()
            if gpu_temp:
                temps['gpu'] = float(gpu_temp)

    except Exception:
        pass

    return temps


def format_temp(temp: Optional[float]) -> str:
    """
    Format temperature for display.

    Args:
        temp: Temperature in Celsius or None

    Returns:
        str: Formatted temperature string
    """
    if temp is None:
        return 'N/A'
    return f'{temp:.1f}°C'


def get_temp_color(temp: Optional[float], warn_threshold: float = 70.0, critical_threshold: float = 85.0) -> str:
    """
    Get color class for temperature based on thresholds.

    Args:
        temp: Temperature in Celsius
        warn_threshold: Warning temperature threshold
        critical_threshold: Critical temperature threshold

    Returns:
        str: Tailwind color class
    """
    if temp is None:
        return 'text-gray-400'

    if temp >= critical_threshold:
        return 'text-red-500'
    elif temp >= warn_threshold:
        return 'text-yellow-500'
    else:
        return 'text-green-400'
