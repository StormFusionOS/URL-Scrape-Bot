"""
Diagnostics page - system health checks and configuration validation.

Provides comprehensive diagnostics for:
- Database connectivity
- Playwright browser availability
- Qdrant vector database status
- Environment configuration
- Dependency verification
- Disk space and performance metrics
"""

from nicegui import ui
import os
import sys
import logging
from pathlib import Path
from datetime import datetime
import asyncio
import psutil  # For system metrics


class DiagnosticsState:
    def __init__(self):
        self.last_check = None
        self.results = {}
        self.checking = False


diagnostics_state = DiagnosticsState()


def check_database():
    """Check PostgreSQL database connectivity."""
    try:
        from sqlalchemy import create_engine, text

        db_url = os.getenv('DATABASE_URL')

        if not db_url:
            return {
                'status': 'error',
                'message': 'DATABASE_URL not set in environment',
                'details': 'Set DATABASE_URL in your .env file'
            }

        # Try to connect
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            # Test query
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()

            # Count tables
            tables_result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public'
            """))
            table_count = tables_result.scalar()

            # Check companies table
            companies_result = conn.execute(text("SELECT COUNT(*) FROM companies"))
            companies_count = companies_result.scalar()

        engine.dispose()

        return {
            'status': 'success',
            'message': 'Database connected successfully',
            'details': {
                'version': version.split('\n')[0] if version else 'Unknown',
                'tables': table_count,
                'companies': companies_count,
                'url': db_url.split('@')[1] if '@' in db_url else 'localhost'
            }
        }

    except Exception as e:
        return {
            'status': 'error',
            'message': 'Database connection failed',
            'details': str(e)
        }


def check_playwright():
    """Check Playwright browser availability."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Check if chromium is installed
            try:
                browser = p.chromium.launch(headless=True)
                browser_version = browser.version
                browser.close()

                return {
                    'status': 'success',
                    'message': 'Playwright browsers available',
                    'details': {
                        'chromium_version': browser_version,
                        'installed': True
                    }
                }
            except Exception as e:
                return {
                    'status': 'warning',
                    'message': 'Playwright installed but browsers missing',
                    'details': f'Run: playwright install chromium\nError: {str(e)}'
                }

    except ImportError:
        return {
            'status': 'error',
            'message': 'Playwright not installed',
            'details': 'Install with: pip install playwright'
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': 'Playwright check failed',
            'details': str(e)
        }


def check_qdrant():
    """Check Qdrant vector database connectivity."""
    try:
        qdrant_host = os.getenv('QDRANT_HOST', 'localhost')
        qdrant_port = int(os.getenv('QDRANT_PORT', '6333'))

        from qdrant_client import QdrantClient

        client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=5)

        # Get collections
        collections = client.get_collections()
        collection_names = [c.name for c in collections.collections]

        return {
            'status': 'success',
            'message': 'Qdrant connected successfully',
            'details': {
                'host': f'{qdrant_host}:{qdrant_port}',
                'collections': len(collection_names),
                'collection_names': collection_names[:5]  # First 5
            }
        }

    except ImportError:
        return {
            'status': 'warning',
            'message': 'Qdrant client not installed',
            'details': 'Install with: pip install qdrant-client'
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': 'Qdrant connection failed',
            'details': f'Check if Qdrant is running on {qdrant_host}:{qdrant_port}\nError: {str(e)}'
        }


def check_environment():
    """Check environment configuration."""
    required_vars = {
        'DATABASE_URL': 'PostgreSQL connection string',
        'NICEGUI_PORT': 'Dashboard port',
        'WORKER_COUNT': 'Number of concurrent workers',
        'MIN_DELAY_SECONDS': 'Minimum delay between requests',
    }

    optional_vars = {
        'QDRANT_HOST': 'Qdrant host',
        'QDRANT_PORT': 'Qdrant port',
        'DEV_MAX_PAGES': 'Safety limit for max pages',
        'DEV_MAX_FAILURES': 'Safety limit for max failures',
    }

    results = {
        'required': {},
        'optional': {},
        'missing_required': []
    }

    # Check required
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if 'PASSWORD' in var or 'URL' in var:
                display_value = '***' + value[-4:] if len(value) > 4 else '***'
            else:
                display_value = value
            results['required'][var] = {'value': display_value, 'description': description}
        else:
            results['missing_required'].append(var)

    # Check optional
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if value:
            results['optional'][var] = {'value': value, 'description': description}

    if results['missing_required']:
        status = 'warning'
        message = f'{len(results["missing_required"])} required variables missing'
    else:
        status = 'success'
        message = 'All required environment variables set'

    return {
        'status': status,
        'message': message,
        'details': results
    }


def check_dependencies():
    """Check Python dependencies."""
    required_packages = [
        'sqlalchemy',
        'playwright',
        'nicegui',
        'psycopg',
        'beautifulsoup4',
        'requests',
    ]

    optional_packages = [
        'qdrant-client',
        'sentence-transformers',
        'pytest',
        'black',
        'ruff',
    ]

    import importlib.metadata

    results = {
        'required': {},
        'optional': {},
        'missing_required': []
    }

    # Check required
    for package in required_packages:
        try:
            version = importlib.metadata.version(package)
            results['required'][package] = version
        except importlib.metadata.PackageNotFoundError:
            results['missing_required'].append(package)

    # Check optional
    for package in optional_packages:
        try:
            version = importlib.metadata.version(package)
            results['optional'][package] = version
        except importlib.metadata.PackageNotFoundError:
            pass

    if results['missing_required']:
        status = 'error'
        message = f'{len(results["missing_required"])} required packages missing'
    else:
        status = 'success'
        message = 'All required packages installed'

    return {
        'status': status,
        'message': message,
        'details': results
    }


def check_system_resources():
    """Check system resources (disk, memory, CPU)."""
    try:
        # Disk usage for project directory
        project_path = Path.cwd()
        disk_usage = psutil.disk_usage(str(project_path))

        # Memory
        memory = psutil.virtual_memory()

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()

        # Log directory size
        log_dir = Path('logs')
        log_size = 0
        if log_dir.exists():
            log_size = sum(f.stat().st_size for f in log_dir.glob('**/*') if f.is_file())

        details = {
            'disk': {
                'total_gb': disk_usage.total / (1024**3),
                'used_gb': disk_usage.used / (1024**3),
                'free_gb': disk_usage.free / (1024**3),
                'percent': disk_usage.percent
            },
            'memory': {
                'total_gb': memory.total / (1024**3),
                'available_gb': memory.available / (1024**3),
                'percent': memory.percent
            },
            'cpu': {
                'percent': cpu_percent,
                'count': cpu_count
            },
            'logs': {
                'size_mb': log_size / (1024**2)
            }
        }

        # Determine status based on usage
        if disk_usage.percent > 90 or memory.percent > 90:
            status = 'warning'
            message = 'System resources running low'
        else:
            status = 'success'
            message = 'System resources healthy'

        return {
            'status': status,
            'message': message,
            'details': details
        }

    except Exception as e:
        return {
            'status': 'error',
            'message': 'System resource check failed',
            'details': str(e)
        }


async def run_all_diagnostics():
    """Run all diagnostic checks."""
    diagnostics_state.checking = True
    diagnostics_state.results = {}

    ui.notify('Running diagnostics...', type='info')

    # Run checks sequentially (could be parallel but these are fast)
    diagnostics_state.results['database'] = check_database()
    await asyncio.sleep(0.1)  # Small delay for UI update

    diagnostics_state.results['playwright'] = check_playwright()
    await asyncio.sleep(0.1)

    diagnostics_state.results['qdrant'] = check_qdrant()
    await asyncio.sleep(0.1)

    diagnostics_state.results['environment'] = check_environment()
    await asyncio.sleep(0.1)

    diagnostics_state.results['dependencies'] = check_dependencies()
    await asyncio.sleep(0.1)

    diagnostics_state.results['system'] = check_system_resources()

    diagnostics_state.last_check = datetime.now()
    diagnostics_state.checking = False

    # Count issues
    error_count = sum(1 for r in diagnostics_state.results.values() if r['status'] == 'error')
    warning_count = sum(1 for r in diagnostics_state.results.values() if r['status'] == 'warning')

    if error_count > 0:
        ui.notify(f'Diagnostics complete with {error_count} errors', type='negative')
    elif warning_count > 0:
        ui.notify(f'Diagnostics complete with {warning_count} warnings', type='warning')
    else:
        ui.notify('All diagnostics passed! ✓', type='positive')


def render_status_card(title, icon, result, check_key):
    """Render a diagnostic status card."""
    status = result.get('status', 'unknown')
    message = result.get('message', 'No information')
    details = result.get('details', {})

    # Status colors
    color_map = {
        'success': 'green',
        'warning': 'orange',
        'error': 'red',
        'unknown': 'gray'
    }

    icon_map = {
        'success': 'check_circle',
        'warning': 'warning',
        'error': 'error',
        'unknown': 'help'
    }

    color = color_map.get(status, 'gray')
    status_icon = icon_map.get(status, 'help')

    with ui.card().classes(f'w-full border-l-4 border-{color}-500'):
        with ui.row().classes('w-full items-center mb-2'):
            ui.icon(icon, size='md').classes(f'text-{color}-400')
            ui.label(title).classes('text-xl font-bold ml-2')
            ui.space()
            ui.icon(status_icon, size='sm').classes(f'text-{color}-400')
            ui.badge(status.upper(), color=color)

        ui.label(message).classes('text-sm text-gray-300 mb-3')

        # Show details based on type
        if isinstance(details, dict) and details:
            with ui.expansion('Details', icon='info').classes('w-full'):
                with ui.column().classes('w-full p-2'):
                    for key, value in details.items():
                        if isinstance(value, dict):
                            ui.label(f'{key}:').classes('font-semibold text-xs uppercase text-gray-400 mt-2')
                            for sub_key, sub_value in value.items():
                                with ui.row().classes('w-full'):
                                    ui.label(f'  {sub_key}:').classes('text-sm w-48')
                                    if isinstance(sub_value, float):
                                        ui.label(f'{sub_value:.2f}').classes('text-sm text-gray-400')
                                    elif isinstance(sub_value, list):
                                        ui.label(', '.join(str(v) for v in sub_value)).classes('text-sm text-gray-400')
                                    else:
                                        ui.label(str(sub_value)).classes('text-sm text-gray-400')
                        else:
                            with ui.row().classes('w-full'):
                                ui.label(f'{key}:').classes('text-sm font-semibold w-48')
                                if isinstance(value, list):
                                    ui.label(', '.join(str(v) for v in value)).classes('text-sm text-gray-400')
                                else:
                                    ui.label(str(value)).classes('text-sm text-gray-400')
        elif isinstance(details, str):
            ui.label(details).classes('text-sm text-gray-400 font-mono whitespace-pre-wrap')


def diagnostics_page():
    """Render diagnostics page."""
    ui.label('System Diagnostics').classes('text-3xl font-bold mb-4')
    ui.label('Health checks and configuration validation').classes('text-gray-400 mb-6')

    # Control bar
    with ui.card().classes('w-full mb-4'):
        with ui.row().classes('w-full items-center gap-4'):
            ui.button(
                'Run All Checks',
                icon='play_circle',
                color='primary',
                on_click=lambda: run_all_diagnostics()
            ).props('size=md')

            if diagnostics_state.last_check:
                ui.label(f'Last check: {diagnostics_state.last_check.strftime("%Y-%m-%d %H:%M:%S")}').classes('text-sm text-gray-400')
            else:
                ui.label('No checks run yet').classes('text-sm text-gray-400')

            ui.space()

            # Quick stats
            if diagnostics_state.results:
                success_count = sum(1 for r in diagnostics_state.results.values() if r['status'] == 'success')
                warning_count = sum(1 for r in diagnostics_state.results.values() if r['status'] == 'warning')
                error_count = sum(1 for r in diagnostics_state.results.values() if r['status'] == 'error')

                if success_count > 0:
                    ui.badge(f'{success_count} OK', color='positive').classes('mx-1')
                if warning_count > 0:
                    ui.badge(f'{warning_count} WARNINGS', color='warning').classes('mx-1')
                if error_count > 0:
                    ui.badge(f'{error_count} ERRORS', color='negative').classes('mx-1')

    # System Info Card
    with ui.card().classes('w-full mb-4'):
        ui.label('System Information').classes('text-xl font-bold mb-3')

        with ui.grid(columns=3).classes('w-full gap-4'):
            # Python version
            with ui.column():
                ui.label('Python Version').classes('text-xs text-gray-400 uppercase')
                ui.label(f'{sys.version.split()[0]}').classes('text-lg font-semibold')

            # Working directory
            with ui.column():
                ui.label('Working Directory').classes('text-xs text-gray-400 uppercase')
                ui.label(Path.cwd().name).classes('text-lg font-semibold')

            # Environment
            with ui.column():
                ui.label('Environment').classes('text-xs text-gray-400 uppercase')
                env_mode = 'Development' if os.getenv('DEV_MAX_PAGES') else 'Production'
                ui.label(env_mode).classes('text-lg font-semibold')

    # Diagnostic Results
    if diagnostics_state.results:
        # Core Services
        with ui.column().classes('w-full gap-4 mb-4'):
            ui.label('Core Services').classes('text-2xl font-bold mb-2')

            if 'database' in diagnostics_state.results:
                render_status_card(
                    'PostgreSQL Database',
                    'storage',
                    diagnostics_state.results['database'],
                    'database'
                )

            if 'playwright' in diagnostics_state.results:
                render_status_card(
                    'Playwright Browser',
                    'web',
                    diagnostics_state.results['playwright'],
                    'playwright'
                )

            if 'qdrant' in diagnostics_state.results:
                render_status_card(
                    'Qdrant Vector Database',
                    'category',
                    diagnostics_state.results['qdrant'],
                    'qdrant'
                )

        # Configuration
        with ui.column().classes('w-full gap-4 mb-4'):
            ui.label('Configuration').classes('text-2xl font-bold mb-2')

            if 'environment' in diagnostics_state.results:
                render_status_card(
                    'Environment Variables',
                    'settings',
                    diagnostics_state.results['environment'],
                    'environment'
                )

            if 'dependencies' in diagnostics_state.results:
                render_status_card(
                    'Python Dependencies',
                    'extension',
                    diagnostics_state.results['dependencies'],
                    'dependencies'
                )

        # System Resources
        with ui.column().classes('w-full gap-4'):
            ui.label('System Resources').classes('text-2xl font-bold mb-2')

            if 'system' in diagnostics_state.results:
                render_status_card(
                    'Disk, Memory, CPU',
                    'computer',
                    diagnostics_state.results['system'],
                    'system'
                )

    else:
        # No results yet - show prompt
        with ui.column().classes('w-full items-center justify-center p-12'):
            ui.icon('health_and_safety', size='64px').classes('text-gray-600 mb-4')
            ui.label('Run Diagnostics').classes('text-2xl text-gray-400 mb-2')
            ui.label('Click "Run All Checks" to verify system health').classes('text-sm text-gray-500 mb-4')
            ui.button(
                'Run All Checks',
                icon='play_circle',
                color='primary',
                on_click=lambda: run_all_diagnostics()
            ).classes('mt-2')

    # Tips Card
    with ui.card().classes('w-full mt-6 bg-blue-900 bg-opacity-30'):
        ui.label('💡 Diagnostics Tips').classes('text-lg font-bold mb-3')

        with ui.column().classes('gap-2'):
            ui.label('• Run diagnostics after setup to verify configuration').classes('text-sm')
            ui.label('• Green = OK, Orange = Warning, Red = Error').classes('text-sm')
            ui.label('• Check "Details" for specific configuration values').classes('text-sm')
            ui.label('• Missing optional packages are warnings (won\'t break core features)').classes('text-sm')
            ui.label('• System resource warnings appear when disk/memory > 90%').classes('text-sm')
