"""
Shared UI form controls and input widgets.
"""

from nicegui import ui
from ..theme import COLORS


def create_state_multiselect():
    """Create a multi-select for US states."""
    states = [
        'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado',
        'Connecticut', 'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho',
        'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana',
        'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota',
        'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada',
        'New Hampshire', 'New Jersey', 'New Mexico', 'New York',
        'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon',
        'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota',
        'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington',
        'West Virginia', 'Wisconsin', 'Wyoming'
    ]

    return ui.select(
        states,
        multiple=True,
        label='Select States',
        with_input=True
    ).classes('w-full')


def create_category_chips(categories: list[str]):
    """
    Create selectable category chips.

    Args:
        categories: List of category names
    """
    selected_categories = []

    with ui.row().classes('gap-2 flex-wrap'):
        for category in categories:
            chip = ui.chip(
                category,
                icon='label',
                selectable=True,
                on_click=lambda c=category: toggle_category(c, selected_categories)
            ).props(f'color={COLORS["accent"]} text-color=white')

    return selected_categories


def toggle_category(category: str, selected: list):
    """Toggle category selection."""
    if category in selected:
        selected.remove(category)
    else:
        selected.append(category)
