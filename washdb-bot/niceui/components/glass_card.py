"""
Glass Card Component
Reusable glassmorphism card component with customizable styling
"""

from nicegui import ui
from contextlib import contextmanager
from typing import Optional, Callable


@contextmanager
def glass_card(
    title: Optional[str] = None,
    icon: Optional[str] = None,
    classes: str = '',
    animate: bool = True
):
    """
    Create a glassmorphism card with optional title and icon

    Args:
        title: Optional card title
        icon: Optional Material Symbol icon name
        classes: Additional CSS classes
        animate: Whether to add fade-in animation

    Example:
        with glass_card(title='System Status', icon='health_and_safety'):
            ui.label('Content goes here')
    """
    animation_class = 'fade-in-up' if animate else ''
    card_classes = f'glass-card {animation_class} {classes}'.strip()

    with ui.card().classes(card_classes):
        if title or icon:
            with ui.row().classes('items-center w-full mb-4'):
                if icon:
                    ui.icon(icon, size='md').classes('text-white')
                if title:
                    ui.label(title).classes('text-xl font-bold glass-text-primary ml-2')

        yield


@contextmanager
def kpi_card(
    title: str,
    value: str,
    change: Optional[str] = None,
    icon: Optional[str] = None,
    classes: str = '',
    value_ref: Optional[dict] = None
):
    """
    Create a KPI card showing a metric with optional change indicator

    Args:
        title: KPI title
        value: Current value
        change: Change indicator (e.g., '+12%' or '-5%')
        icon: Optional icon name
        classes: Additional CSS classes
        value_ref: Optional dict to store reference to value label for updates

    Example:
        refs = {}
        with kpi_card(title='Total Sites', value='47', change='+3', icon='public', value_ref=refs):
            pass  # Card auto-renders
        # Later: refs['value_label'].set_text('50')
    """
    card_classes = f'kpi-card {classes}'.strip()

    with ui.card().classes(card_classes):
        with ui.column().classes('gap-2 w-full'):
            # Header row with icon and title
            with ui.row().classes('items-center'):
                if icon:
                    ui.icon(icon, size='sm').classes('text-white/70')
                ui.label(title).classes('text-sm glass-text-secondary uppercase tracking-wide')

            # Value row
            with ui.row().classes('items-baseline'):
                value_label = ui.label(value).classes('stat-number')

                # Store reference if requested
                if value_ref is not None:
                    value_ref['value_label'] = value_label

                # Change indicator
                if change:
                    change_class = 'change-positive' if change.startswith('+') else 'change-negative'
                    with ui.row().classes(f'items-center ml-3 {change_class}'):
                        icon_name = 'trending_up' if change.startswith('+') else 'trending_down'
                        ui.icon(icon_name, size='sm')
                        ui.label(change).classes('text-sm font-semibold')

        yield


def status_badge(status: str, label: Optional[str] = None) -> ui.html:
    """
    Create a status badge with appropriate styling

    Args:
        status: Status type ('running', 'idle', 'error', 'success', 'warning')
        label: Optional custom label (defaults to status)

    Returns:
        ui.html element with styled badge
    """
    status_lower = status.lower()
    display_label = label or status.upper()

    badge_html = f'''
    <div class="status-badge {status_lower}">
        {display_label}
    </div>
    '''

    return ui.html(badge_html)


@contextmanager
def stat_row(label: str, value: str, classes: str = ''):
    """
    Create a row showing a statistic label and value

    Args:
        label: Statistic label
        value: Statistic value
        classes: Additional CSS classes
    """
    with ui.row().classes(f'items-center justify-between w-full {classes}'):
        ui.label(label).classes('glass-text-secondary')
        ui.label(value).classes('glass-text-primary font-semibold')
        yield


def divider(classes: str = ''):
    """Create a subtle divider line"""
    ui.separator().classes(f'bg-white/10 {classes}')


def section_title(title: str, icon: Optional[str] = None, classes: str = ''):
    """
    Create a section title with optional icon

    Args:
        title: Section title text
        icon: Optional Material Symbol icon
        classes: Additional CSS classes
    """
    with ui.row().classes(f'items-center gap-2 mb-4 {classes}'):
        if icon:
            ui.icon(icon, size='md').classes('text-white/90')
        ui.label(title).classes('text-2xl font-bold glass-text-primary')
