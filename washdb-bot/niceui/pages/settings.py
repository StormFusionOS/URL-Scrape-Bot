"""
Settings page - configure application settings with persistence.
"""

import os
import platform
import subprocess
from pathlib import Path
from nicegui import ui
from ..config_manager import config_manager


def open_directory(path: str):
    """Open directory in OS file explorer (platform-aware)."""
    path_obj = Path(path)

    # Create directory if it doesn't exist
    path_obj.mkdir(parents=True, exist_ok=True)

    system = platform.system()

    try:
        if system == 'Windows':
            os.startfile(path_obj)
        elif system == 'Darwin':  # macOS
            subprocess.run(['open', str(path_obj)])
        else:  # Linux and others
            subprocess.run(['xdg-open', str(path_obj)])

        ui.notify(f'Opened {path}', type='positive', timeout=2000)
    except Exception as e:
        ui.notify(f'Failed to open directory: {str(e)}', type='negative')


def apply_theme_settings():
    """Apply theme settings without restart."""
    mode = config_manager.get('theme', 'mode', 'dark')
    primary_color = config_manager.get('theme', 'primary_color', '#8b5cf6')
    accent_color = config_manager.get('theme', 'accent_color', '#a78bfa')

    # Update dark mode
    if mode == 'dark':
        ui.dark_mode().enable()
    elif mode == 'light':
        ui.dark_mode().disable()
    else:  # auto
        ui.dark_mode().auto()

    # Update colors
    ui.colors(primary=primary_color)

    ui.notify('Theme applied successfully', type='positive', timeout=2000)


def save_theme_settings(mode_select, primary_color_input, accent_color_input):
    """Save theme settings."""
    theme_config = {
        'mode': mode_select.value,
        'primary_color': primary_color_input.value,
        'accent_color': accent_color_input.value,
    }

    if config_manager.update_section('theme', theme_config):
        apply_theme_settings()
        ui.notify('Theme settings saved!', type='positive')
    else:
        ui.notify('Failed to save theme settings', type='negative')


def save_path_settings(log_dir_input, export_dir_input):
    """Save path settings."""
    path_config = {
        'log_dir': log_dir_input.value,
        'export_dir': export_dir_input.value,
    }

    if config_manager.update_section('paths', path_config):
        ui.notify('Path settings saved!', type='positive')
    else:
        ui.notify('Failed to save path settings', type='negative')


def save_defaults_settings(crawl_delay, pages_per_pair, stale_days, default_limit):
    """Save default settings."""
    defaults_config = {
        'crawl_delay': float(crawl_delay.value),
        'pages_per_pair': int(pages_per_pair.value),
        'stale_days': int(stale_days.value),
        'default_limit': int(default_limit.value),
    }

    if config_manager.update_section('defaults', defaults_config):
        ui.notify('Default settings saved!', type='positive')
    else:
        ui.notify('Failed to save default settings', type='negative')


def save_database_settings(host, port, database, username, password):
    """Save database settings and update .env file."""
    db_config = {
        'host': host.value,
        'port': int(port.value),
        'database': database.value,
        'username': username.value,
        'password': password.value,
    }

    # Save to config
    if config_manager.update_section('database', db_config):
        # Update .env file with DATABASE_URL
        try:
            update_env_database_url(
                host=host.value,
                port=int(port.value),
                database=database.value,
                username=username.value,
                password=password.value
            )
            ui.notify('Database settings saved! Restart the app to apply changes.', type='positive', timeout=5000)
        except Exception as e:
            ui.notify(f'Settings saved but .env update failed: {str(e)}', type='warning')
    else:
        ui.notify('Failed to save database settings', type='negative')


def update_env_database_url(host, port, database, username, password):
    """Update .env file with DATABASE_URL."""
    env_path = Path('.env')

    # Build DATABASE_URL with explicit psycopg driver (not psycopg2)
    db_url = f"postgresql+psycopg://{username}:{password}@{host}:{port}/{database}"

    # Read existing .env content
    env_lines = []
    database_url_found = False

    if env_path.exists():
        with open(env_path, 'r') as f:
            env_lines = f.readlines()

        # Update existing DATABASE_URL line
        for i, line in enumerate(env_lines):
            if line.strip().startswith('DATABASE_URL='):
                env_lines[i] = f'DATABASE_URL={db_url}\n'
                database_url_found = True
                break

    # If DATABASE_URL not found, append it
    if not database_url_found:
        env_lines.append(f'DATABASE_URL={db_url}\n')

    # Write back to .env
    with open(env_path, 'w') as f:
        f.writelines(env_lines)


def test_database_connection(host, port, database, username, password):
    """Test database connection with provided credentials."""
    try:
        import psycopg

        # Build connection string for psycopg (native format)
        conn_string = f"host={host.value} port={int(port.value)} dbname={database.value} user={username.value} password={password.value}"

        # Try to connect using psycopg directly (same as SQLAlchemy uses)
        with psycopg.connect(conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        ui.notify('✓ Database connection successful!', type='positive', timeout=3000)
        return True

    except Exception as e:
        error_msg = str(e)
        # Extract just the relevant error message
        if 'FATAL' in error_msg:
            error_msg = error_msg.split('FATAL:')[1].split('\n')[0].strip()
        ui.notify(f'✗ Connection failed: {error_msg}', type='negative', timeout=5000)
        return False


def reset_to_defaults():
    """Reset all settings to defaults."""
    if config_manager.reset_to_defaults():
        ui.notify('Settings reset to defaults! Reload the page to see changes.', type='warning', timeout=5000)
        # Reload the page after a delay
        ui.timer(2.0, lambda: ui.run_javascript('window.location.reload()'), once=True)
    else:
        ui.notify('Failed to reset settings', type='negative')


def settings_page():
    """Render settings page."""
    ui.label('Settings').classes('text-3xl font-bold mb-4')

    ui.label(
        'Configure application settings. Changes are persisted to data/config.json.'
    ).classes('text-gray-400 mb-6')

    # THEME SETTINGS
    with ui.card().classes('w-full mb-4'):
        ui.label('Theme Settings').classes('text-2xl font-bold mb-4')

        ui.label('Appearance').classes('font-semibold mb-2')

        # Theme mode selector
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Theme Mode:').classes('min-w-32')
            mode_select = ui.select(
                ['dark', 'light', 'auto'],
                value=config_manager.get('theme', 'mode', 'dark'),
                label='Mode'
            ).classes('w-48')

        ui.label(
            'Auto mode switches between light/dark based on system preferences'
        ).classes('text-sm text-gray-400 mb-4')

        # Color pickers
        ui.label('Colors').classes('font-semibold mb-2 mt-4')

        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Primary Color:').classes('min-w-32')
            primary_color_input = ui.input(
                'Primary Color',
                value=config_manager.get('theme', 'primary_color', '#8b5cf6')
            ).classes('w-48')
            ui.color_input(on_change=lambda e: setattr(primary_color_input, 'value', e.value)).bind_value(primary_color_input)

        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Accent Color:').classes('min-w-32')
            accent_color_input = ui.input(
                'Accent Color',
                value=config_manager.get('theme', 'accent_color', '#a78bfa')
            ).classes('w-48')
            ui.color_input(on_change=lambda e: setattr(accent_color_input, 'value', e.value)).bind_value(accent_color_input)

        ui.label(
            'Default purple theme: Primary #8b5cf6, Accent #a78bfa'
        ).classes('text-sm text-gray-400 mb-4')

        # Save button
        with ui.row().classes('gap-2'):
            ui.button(
                'Apply Theme',
                icon='palette',
                color='primary',
                on_click=lambda: save_theme_settings(mode_select, primary_color_input, accent_color_input)
            )

            ui.button(
                'Apply Now (Live)',
                icon='bolt',
                color='positive',
                on_click=lambda: apply_theme_settings()
            ).props('outline').tooltip('Apply current settings without saving')

    # PATH SETTINGS
    with ui.card().classes('w-full mb-4'):
        ui.label('Path Settings').classes('text-2xl font-bold mb-4')

        # Log directory
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Log Directory:').classes('min-w-32')
            log_dir_input = ui.input(
                'Log Directory',
                value=config_manager.get('paths', 'log_dir', 'logs')
            ).classes('flex-1')

            ui.button(
                'Open in OS',
                icon='folder_open',
                on_click=lambda: open_directory(log_dir_input.value)
            ).props('outline')

        # Export directory
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Export Directory:').classes('min-w-32')
            export_dir_input = ui.input(
                'Export Directory',
                value=config_manager.get('paths', 'export_dir', 'exports')
            ).classes('flex-1')

            ui.button(
                'Open in OS',
                icon='folder_open',
                on_click=lambda: open_directory(export_dir_input.value)
            ).props('outline')

        ui.label(
            f'Platform: {platform.system()} - Directories will be created if they don\'t exist'
        ).classes('text-sm text-gray-400 mb-4')

        # Save button
        ui.button(
            'Save Paths',
            icon='save',
            color='primary',
            on_click=lambda: save_path_settings(log_dir_input, export_dir_input)
        )

    # DATABASE SETTINGS
    with ui.card().classes('w-full mb-4'):
        ui.label('Database Settings').classes('text-2xl font-bold mb-4')

        ui.label(
            'PostgreSQL database connection settings. Changes require app restart.'
        ).classes('text-sm text-gray-400 mb-4')

        # Host
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Host:').classes('min-w-32')
            db_host = ui.input(
                'Host',
                value=config_manager.get('database', 'host', '127.0.0.1')
            ).classes('w-64')

        # Port
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Port:').classes('min-w-32')
            db_port = ui.number(
                'Port',
                value=config_manager.get('database', 'port', 5432),
                min=1,
                max=65535,
                format='%.0f'
            ).classes('w-64')

        # Database Name
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Database Name:').classes('min-w-32')
            db_name = ui.input(
                'Database',
                value=config_manager.get('database', 'database', 'washbot_db')
            ).classes('w-64')

        # Username
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Username:').classes('min-w-32')
            db_username = ui.input(
                'Username',
                value=config_manager.get('database', 'username', 'washbot')
            ).classes('w-64')

        # Password
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Password:').classes('min-w-32')
            db_password = ui.input(
                'Password',
                value=config_manager.get('database', 'password', ''),
                password=True,
                password_toggle_button=True
            ).classes('w-64')

        ui.label(
            'Connection string format: postgresql://username:password@host:port/database'
        ).classes('text-xs text-gray-500 mb-4')

        # Buttons
        with ui.row().classes('gap-2'):
            ui.button(
                'Test Connection',
                icon='cloud_done',
                color='primary',
                on_click=lambda: test_database_connection(db_host, db_port, db_name, db_username, db_password)
            ).props('outline')

            ui.button(
                'Save Database Settings',
                icon='save',
                color='primary',
                on_click=lambda: save_database_settings(db_host, db_port, db_name, db_username, db_password)
            )

    # DEFAULT VALUES
    with ui.card().classes('w-full mb-4'):
        ui.label('Default Values').classes('text-2xl font-bold mb-4')

        ui.label(
            'These values are used as defaults in discovery and scraping operations.'
        ).classes('text-sm text-gray-400 mb-4')

        # Crawl delay
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Crawl Delay (seconds):').classes('min-w-48')
            crawl_delay = ui.number(
                'Crawl Delay',
                value=config_manager.get('defaults', 'crawl_delay', 1.0),
                min=0.1,
                max=10.0,
                step=0.1,
                format='%.1f'
            ).classes('w-48')

        ui.label('Delay between requests to avoid overwhelming servers').classes(
            'text-xs text-gray-500 ml-48 mb-4'
        )

        # Pages per pair
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Pages per Pair:').classes('min-w-48')
            pages_per_pair = ui.number(
                'Pages per Pair',
                value=config_manager.get('defaults', 'pages_per_pair', 1),
                min=1,
                max=10,
                format='%.0f'
            ).classes('w-48')

        ui.label('Number of pages to crawl per category-state combination').classes(
            'text-xs text-gray-500 ml-48 mb-4'
        )

        # Stale days
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Stale Days:').classes('min-w-48')
            stale_days = ui.number(
                'Stale Days',
                value=config_manager.get('defaults', 'stale_days', 30),
                min=1,
                max=365,
                format='%.0f'
            ).classes('w-48')

        ui.label('Companies not updated in this many days are considered stale').classes(
            'text-xs text-gray-500 ml-48 mb-4'
        )

        # Default limit
        with ui.row().classes('w-full items-center gap-4 mb-4'):
            ui.label('Default Limit:').classes('min-w-48')
            default_limit = ui.number(
                'Default Limit',
                value=config_manager.get('defaults', 'default_limit', 100),
                min=1,
                max=10000,
                format='%.0f'
            ).classes('w-48')

        ui.label('Default number of records to process in batch operations').classes(
            'text-xs text-gray-500 ml-48 mb-4'
        )

        # Save button
        ui.button(
            'Save Defaults',
            icon='save',
            color='primary',
            on_click=lambda: save_defaults_settings(
                crawl_delay, pages_per_pair, stale_days, default_limit
            )
        )

    # DANGER ZONE
    with ui.card().classes('w-full').style('border: 1px solid rgba(239, 68, 68, 0.5)'):
        ui.label('Danger Zone').classes('text-2xl font-bold mb-4 text-red-500')

        ui.label(
            'Reset all settings to factory defaults. This action cannot be undone.'
        ).classes('text-sm text-gray-400 mb-4')

        ui.button(
            'Reset to Defaults',
            icon='restore',
            color='negative',
            on_click=lambda: reset_to_defaults()
        ).props('outline')

    # Current configuration display
    with ui.expansion('View Current Configuration', icon='code').classes('w-full mt-4'):
        with ui.card().classes('w-full bg-gray-900'):
            ui.label('data/config.json').classes('text-sm font-mono text-gray-400 mb-2')

            import json
            config_json = json.dumps(config_manager.config, indent=2)
            ui.code(config_json, language='json').classes('w-full')
