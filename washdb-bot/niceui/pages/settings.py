"""
Settings page - configure application settings with persistence.
"""

from pathlib import Path
from nicegui import ui
from ..config_manager import config_manager
from ..widgets.keyword_editor import create_keyword_editor
from ..widgets.filter_preview import create_filter_preview
from ..widgets.keyword_stats import create_keyword_stats
from ..widgets.category_editor import create_category_editor
from ..utils.keyword_manager import keyword_manager


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


def build_keyword_management_section():
    """Build the keyword management dashboard section."""
    with ui.card().classes('w-full mb-4'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-4'):
            with ui.column().classes('gap-1'):
                ui.label('Keyword Management').classes('text-2xl font-bold')
                ui.label('Control filtering keywords for all discovery sources').classes('text-sm text-gray-400')

            # Reload all button
            ui.button(
                'Reload All',
                icon='refresh',
                on_click=lambda: reload_all_keywords()
            ).props('flat').tooltip('Reload all keyword files from disk')

        # Statistics summary
        files_by_source = keyword_manager.get_all_files_by_source()
        total_keywords = sum(f['count'] for source_files in files_by_source.values() for f in source_files)

        with ui.row().classes('w-full gap-4 mb-6'):
            with ui.card().classes('flex-1 bg-blue-900/20'):
                ui.label('Total Keywords').classes('text-sm text-gray-400')
                ui.label(str(total_keywords)).classes('text-3xl font-bold text-blue-400')

            with ui.card().classes('flex-1 bg-green-900/20'):
                ui.label('Shared Files').classes('text-sm text-gray-400')
                ui.label(str(len(files_by_source['shared']))).classes('text-3xl font-bold text-green-400')

            with ui.card().classes('flex-1 bg-purple-900/20'):
                ui.label('Source-Specific').classes('text-sm text-gray-400')
                ui.label(str(len(files_by_source['yp']))).classes('text-3xl font-bold text-purple-400')

        # Filter Preview Tool
        with ui.expansion('🧪 Filter Preview & Testing', icon='science').classes('w-full mb-4'):
            create_filter_preview()

        # Statistics Dashboard
        with ui.expansion('📊 Statistics & Analytics', icon='analytics').classes('w-full mb-4'):
            create_keyword_stats(keyword_manager)

        # Tabbed interface for each source
        with ui.tabs().classes('w-full') as tabs:
            shared_tab = ui.tab('Shared', icon='public')
            google_tab = ui.tab('Google', icon='map')
            yp_tab = ui.tab('Yellow Pages', icon='menu_book')
            bing_tab = ui.tab('Bing', icon='search')

        with ui.tab_panels(tabs, value=shared_tab).classes('w-full'):
            # SHARED KEYWORDS TAB
            with ui.tab_panel(shared_tab):
                ui.label('Shared Keywords').classes('text-xl font-bold mb-4')
                ui.label('These keywords are used by all discovery sources for filtering.').classes(
                    'text-sm text-gray-400 mb-6'
                )

                with ui.row().classes('w-full gap-4'):
                    # Anti-Keywords column
                    with ui.column().classes('flex-1'):
                        create_keyword_editor(
                            file_id='shared_anti_keywords',
                            title='Anti-Keywords',
                            description='Filter out unwanted businesses (equipment, training, franchises, etc.)',
                            color='red'
                        )

                    # Positive Hints column
                    with ui.column().classes('flex-1'):
                        create_keyword_editor(
                            file_id='shared_positive_hints',
                            title='Positive Hints',
                            description='Boost confidence for target businesses (pressure washing, soft wash, etc.)',
                            color='green'
                        )

            # GOOGLE TAB
            with ui.tab_panel(google_tab):
                ui.label('Google Maps Discovery').classes('text-xl font-bold mb-4')
                ui.label('Control what categories Google Maps searches for').classes(
                    'text-sm text-gray-400 mb-6'
                )

                # Category editor
                create_category_editor()

                # Info about shared keywords
                ui.label('Keywords & Domains').classes('text-lg font-semibold mt-6 mb-3')
                with ui.card().classes('w-full bg-blue-900/10'):
                    ui.label('ℹ Info').classes('text-sm font-semibold mb-2')
                    ui.label(
                        'Google Maps also uses the shared anti-keywords and positive hints from the Shared tab. '
                        'Blocked domains (Amazon, eBay, etc.) are configured in scrape_google/google_filter.py.'
                    ).classes('text-sm text-gray-400')

            # YELLOW PAGES TAB
            with ui.tab_panel(yp_tab):
                ui.label('Yellow Pages Discovery').classes('text-xl font-bold mb-4')
                ui.label('YP uses categories and keywords for precise filtering.').classes(
                    'text-sm text-gray-400 mb-6'
                )

                # Category management
                with ui.row().classes('w-full gap-4 mb-6'):
                    with ui.column().classes('flex-1'):
                        create_keyword_editor(
                            file_id='yp_category_allowlist',
                            title='Category Allowlist',
                            description='YP categories to INCLUDE in results',
                            color='green'
                        )

                    with ui.column().classes('flex-1'):
                        create_keyword_editor(
                            file_id='yp_category_blocklist',
                            title='Category Blocklist',
                            description='YP categories to EXCLUDE from results',
                            color='red'
                        )

                # YP-specific anti-keywords
                ui.label('YP-Specific Keywords').classes('text-lg font-bold mt-6 mb-4')

                create_keyword_editor(
                    file_id='yp_anti_keywords',
                    title='YP Anti-Keywords',
                    description='Additional anti-keywords specific to Yellow Pages (currently unused in code)',
                    color='orange'
                )

            # BING TAB
            with ui.tab_panel(bing_tab):
                ui.label('Bing Local Discovery').classes('text-xl font-bold mb-4')
                ui.label('Bing uses shared keywords only.').classes(
                    'text-sm text-gray-400 mb-6'
                )

                with ui.card().classes('w-full bg-blue-900/10'):
                    ui.label('ℹ Info').classes('text-lg font-bold mb-2')
                    ui.label(
                        'Bing Local discovery inherits all filtering logic from Google Maps, '
                        'using the shared anti-keywords and positive hints above.'
                    ).classes('text-sm text-gray-400')


def reload_all_keywords():
    """Reload all keyword files from disk."""
    keyword_manager.reload_all()
    ui.notify('All keyword files reloaded!', type='positive')


def settings_page():
    """Render settings page."""
    ui.label('Settings').classes('text-3xl font-bold mb-4')

    ui.label(
        'Configure application settings. Changes are persisted to data/config.json.'
    ).classes('text-gray-400 mb-6')

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

    # KEYWORD MANAGEMENT
    build_keyword_management_section()

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
