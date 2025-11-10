"""
KPI card widgets.
"""

from nicegui import ui
from ..theme import COLORS


def create_kpi_card(title: str, value: str | int | float, icon: str = 'analytics', color: str = 'primary'):
    """
    Create a KPI card widget.

    Args:
        title: Card title
        value: KPI value to display
        icon: Material icon name
        color: Color theme (primary, secondary, positive, negative, etc.)
    """
    color_map = {
        'primary': COLORS['primary'],
        'secondary': COLORS['secondary'],
        'accent': COLORS['accent'],
        'positive': COLORS['positive'],
        'negative': COLORS['negative'],
        'info': COLORS['info'],
        'warning': COLORS['warning'],
    }

    card_color = color_map.get(color, COLORS['primary'])

    with ui.card().classes('flex-1 stat-card p-4'):
        with ui.row().classes('items-center w-full'):
            ui.icon(icon, size='lg').style(f'color: {card_color}')
            ui.space()

        ui.label(title).classes('text-gray-400 text-sm mt-2')
        ui.label(str(value)).classes('text-3xl font-bold').style(f'color: {card_color}')
