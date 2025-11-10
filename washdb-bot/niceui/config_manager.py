"""
Configuration manager for persistent settings.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict


# Default configuration
DEFAULT_CONFIG = {
    "theme": {
        "mode": "dark",  # dark, light, or auto
        "primary_color": "#8b5cf6",  # Purple
        "accent_color": "#a78bfa",  # Light purple
    },
    "paths": {
        "log_dir": "logs",
        "export_dir": "exports",
    },
    "defaults": {
        "crawl_delay": 1.0,
        "pages_per_pair": 1,
        "stale_days": 30,
        "default_limit": 100,
    },
    "database": {
        "host": "127.0.0.1",
        "port": 5432,
        "database": "washbot_db",
        "username": "washbot",
        "password": "",
    }
}


class ConfigManager:
    """Manages application configuration with persistence."""

    def __init__(self, config_path: str = "data/config.json"):
        self.config_path = Path(config_path)
        self.config = self.load()

    def load(self) -> Dict[str, Any]:
        """Load configuration from file or return defaults."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)
                # Merge with defaults to ensure all keys exist
                return self._merge_configs(DEFAULT_CONFIG, loaded_config)
            except Exception as e:
                print(f"Error loading config: {e}, using defaults")
                return DEFAULT_CONFIG.copy()
        else:
            # Create default config file
            self.save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()

    def save(self, config: Dict[str, Any] = None) -> bool:
        """Save configuration to file."""
        if config is None:
            config = self.config

        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Write config
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)

            self.config = config
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def get(self, section: str, key: str = None, default: Any = None) -> Any:
        """Get a configuration value."""
        if key is None:
            return self.config.get(section, default)
        return self.config.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any) -> bool:
        """Set a configuration value."""
        if section not in self.config:
            self.config[section] = {}

        self.config[section][key] = value
        return self.save()

    def update_section(self, section: str, values: Dict[str, Any]) -> bool:
        """Update an entire section."""
        if section not in self.config:
            self.config[section] = {}

        self.config[section].update(values)
        return self.save()

    def reset_to_defaults(self) -> bool:
        """Reset configuration to defaults."""
        self.config = DEFAULT_CONFIG.copy()
        return self.save()

    def _merge_configs(self, default: Dict, loaded: Dict) -> Dict:
        """Merge loaded config with defaults to ensure all keys exist."""
        result = default.copy()
        for key, value in loaded.items():
            if isinstance(value, dict) and key in result and isinstance(result[key], dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result


# Global config manager instance
config_manager = ConfigManager()
