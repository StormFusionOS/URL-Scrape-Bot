"""
Main layout components: header, drawer, footer, and content area.
"""

from nicegui import ui
from .theme import COLORS
from .router import router, event_bus
from .backend_facade import backend
from .config_manager import config_manager
import os


# Apply theme settings from config at startup
def apply_startup_theme():
    """Apply theme settings from config file."""
    mode = config_manager.get('theme', 'mode', 'dark')
    primary_color = config_manager.get('theme', 'primary_color', '#8b5cf6')

    # Update dark mode
    if mode == 'dark':
        ui.dark_mode().enable()
    elif mode == 'light':
        ui.dark_mode().disable()
    else:  # auto
        ui.dark_mode().auto()

    # Update colors
    ui.colors(primary=primary_color)


# Apply theme on module import
apply_startup_theme()


class AppLayout:
    """Main application layout manager."""

    def __init__(self):
        self.header_element = None
        self.drawer = None
        self.content_area = None
        self.footer_element = None
        self.progress_bar = None
        self.busy_overlay = None
        self.version = self._get_version()

    def _get_version(self) -> str:
        """Get version from git or VERSION file."""
        try:
            # Try reading VERSION file
            version_file = os.path.join(os.path.dirname(__file__), '..', 'VERSION')
            if os.path.exists(version_file):
                with open(version_file) as f:
                    return f.read().strip()
        except:
            pass
        return "1.0.0"

    def create_header(self):
        """Create application header."""
        with ui.header().classes('items-center').style(
            f'background-color: {COLORS["primary"]}; padding: 0.5rem 1rem;'
        ) as self.header_element:

            # Menu button for drawer
            ui.button(icon='menu', on_click=lambda: self.drawer.toggle()).props('flat color=white')

            # App title
            ui.label('Washdb-Bot Dashboard').classes('text-xl font-bold ml-2')

            # Environment badge
            ui.badge('DEV', color='accent').classes('ml-2')

            # Spacer
            ui.space()

            # Progress bar (initially hidden)
            self.progress_bar = ui.linear_progress(value=0, show_value=False).props('instant-feedback').classes('w-32')
            self.progress_bar.visible = False

            # Control buttons
            ui.button('Run', icon='play_arrow', color='positive', on_click=self._on_run).props('outline')
            ui.button('Stop', icon='stop', color='negative', on_click=self._on_stop).props('outline').classes('ml-2')

            # Theme toggle (dark mode is default, but allow toggle)
            ui.button(icon='brightness_6', on_click=ui.dark_mode().toggle).props('flat color=white').classes('ml-2')

    def create_drawer(self):
        """Create left navigation drawer."""
        with ui.left_drawer(value=True, elevated=True).style(
            f'background-color: {COLORS["dark"]};'
        ).classes('q-pa-md') as self.drawer:

            ui.label('Navigation').classes('text-lg font-bold mb-4')

            # Navigation items
            nav_items = [
                {'name': 'Dashboard', 'icon': 'dashboard', 'page': 'dashboard'},
                {'name': 'Discover', 'icon': 'search', 'page': 'discover'},
                {'name': 'Scrape', 'icon': 'data_usage', 'page': 'scrape'},
                {'name': 'Single URL', 'icon': 'link', 'page': 'single_url'},
                {'name': 'Database', 'icon': 'storage', 'page': 'database'},
                {'name': 'Logs', 'icon': 'article', 'page': 'logs'},
                {'name': 'Status', 'icon': 'timeline', 'page': 'status'},
                {'name': 'Settings', 'icon': 'settings', 'page': 'settings'},
            ]

            for item in nav_items:
                self._create_nav_item(item['name'], item['icon'], item['page'])

    def _create_nav_item(self, name: str, icon: str, page: str):
        """Create a navigation item."""
        is_active = router.current_page == page

        btn = ui.button(
            name,
            icon=icon,
            on_click=lambda p=page: self._navigate(p)
        ).props('flat align=left').classes('w-full')

        if is_active:
            btn.classes('nav-item-active')

        return btn

    def _navigate(self, page: str):
        """Navigate to a page and update active state."""
        router.navigate(page, self.content_area)
        # Refresh drawer to update active states
        self.drawer.clear()
        with self.drawer:
            self.create_drawer_content()

    def create_drawer_content(self):
        """Create drawer content (called when refreshing)."""
        ui.label('Navigation').classes('text-lg font-bold mb-4')

        nav_items = [
            {'name': 'Dashboard', 'icon': 'dashboard', 'page': 'dashboard'},
            {'name': 'Discover', 'icon': 'search', 'page': 'discover'},
            {'name': 'Scrape', 'icon': 'data_usage', 'page': 'scrape'},
            {'name': 'Single URL', 'icon': 'link', 'page': 'single_url'},
            {'name': 'Database', 'icon': 'storage', 'page': 'database'},
            {'name': 'Logs', 'icon': 'article', 'page': 'logs'},
            {'name': 'Status', 'icon': 'timeline', 'page': 'status'},
            {'name': 'Settings', 'icon': 'settings', 'page': 'settings'},
        ]

        for item in nav_items:
            self._create_nav_item(item['name'], item['icon'], item['page'])

    def create_content_area(self):
        """Create main content area."""
        self.content_area = ui.column().classes('w-full p-4')
        return self.content_area

    def create_footer(self):
        """Create application footer."""
        with ui.footer().style(
            f'background-color: {COLORS["dark"]}; padding: 0.5rem 1rem;'
        ) as self.footer_element:

            # Version info
            ui.label(f'Washdb-Bot v{self.version} | Powered by NiceGUI').classes('text-sm text-gray-400')

            ui.space()

            # Database status
            db_status = backend.check_database_connection()
            if db_status['connected']:
                ui.badge('DB: Connected', color='positive').classes('mr-2')
            else:
                ui.badge('DB: Error', color='negative').classes('mr-2')

            # Last run stats
            status = backend.get_scrape_status()
            if status['last_run']:
                ui.label(f"Last run: {status['last_run'][:19]}").classes('text-sm text-gray-400')

    def _on_run(self):
        """Handle run button click - broadcast event."""
        event_bus.publish('request_run')
        ui.notify('Run requested', type='info', position='top')

    def _on_stop(self):
        """Handle stop button click - broadcast event."""
        event_bus.publish('request_stop')
        ui.notify('Stop requested', type='warning', position='top')

    def create_busy_overlay(self):
        """Create busy overlay (initially hidden)."""
        with ui.element('div').classes('busy-overlay').style('display: none;') as self.busy_overlay:
            ui.element('div').classes('busy-spinner')

    def show_busy(self):
        """Show busy overlay."""
        if self.busy_overlay:
            self.busy_overlay.style('display: flex;')
            self.busy_overlay.classes(add='active')

    def hide_busy(self):
        """Hide busy overlay."""
        if self.busy_overlay:
            self.busy_overlay.style('display: none;')
            self.busy_overlay.classes(remove='active')

    def setup(self):
        """Setup the complete layout."""
        self.create_header()
        self.create_drawer()
        content = self.create_content_area()
        self.create_footer()
        self.create_busy_overlay()
        return content


# Global layout instance
layout = AppLayout()
