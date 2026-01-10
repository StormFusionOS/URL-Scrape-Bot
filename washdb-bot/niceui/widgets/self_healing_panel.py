"""
Self-Healing Panel widget - displays healing actions and manual controls.
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from nicegui import ui


def get_healing_history(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Fetch recent healing actions from database.

    Returns list of healing action dicts.
    """
    try:
        import os
        from sqlalchemy import create_engine, text

        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return []

        engine = create_engine(db_url)

        query = """
            SELECT
                action_id,
                timestamp,
                action_type,
                target_service,
                trigger_type,
                trigger_reason,
                triggered_by_pattern,
                success,
                result_message,
                duration_seconds
            FROM healing_actions
            ORDER BY timestamp DESC
            LIMIT %s
        """ % limit

        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()

        actions = []
        for row in rows:
            actions.append({
                'action_id': row[0],
                'timestamp': row[1].isoformat() if row[1] else None,
                'action_type': row[2],
                'target_service': row[3],
                'trigger_type': row[4],
                'trigger_reason': row[5],
                'triggered_by_pattern': row[6],
                'success': row[7],
                'result_message': row[8],
                'duration_seconds': row[9],
            })

        return actions

    except Exception as e:
        print(f"Error fetching healing history: {e}")
        return []


def format_timestamp(ts: str) -> str:
    """Format timestamp for display."""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime('%H:%M:%S')
    except:
        return ts[:19] if ts else ""


# Action configurations for manual triggers
HEALING_ACTIONS = [
    {
        'id': 'chrome_cleanup',
        'name': 'Clean Chrome',
        'icon': 'cleaning_services',
        'description': 'Kill orphan Chrome processes',
        'color': 'primary',
        'dangerous': False,
    },
    {
        'id': 'chrome_kill_all',
        'name': 'Kill All Chrome',
        'icon': 'delete_sweep',
        'description': 'Force kill ALL Chrome processes',
        'color': 'warning',
        'dangerous': True,
    },
    {
        'id': 'xvfb_restart',
        'name': 'Restart Xvfb',
        'icon': 'monitor',
        'description': 'Restart virtual display',
        'color': 'primary',
        'dangerous': False,
    },
    {
        'id': 'browser_pool_drain',
        'name': 'Drain Pool',
        'icon': 'water_drop',
        'description': 'Drain and recreate browser pool',
        'color': 'warning',
        'dangerous': True,
    },
    {
        'id': 'clear_stuck_jobs',
        'name': 'Clear Stuck Jobs',
        'icon': 'playlist_remove',
        'description': 'Reset stuck/stale jobs',
        'color': 'warning',
        'dangerous': True,
    },
    {
        'id': 'restart_seo_worker',
        'name': 'Restart SEO',
        'icon': 'restart_alt',
        'description': 'Restart SEO job worker service',
        'color': 'negative',
        'dangerous': True,
        'service': 'seo-job-worker',
    },
]


class SelfHealingPanel:
    """Panel for self-healing controls and history."""

    def __init__(self, refresh_interval: float = 30.0):
        self.refresh_interval = refresh_interval
        self.history_container = None

    def _get_system_monitor(self):
        """Get the system monitor instance."""
        try:
            from services.system_monitor import get_system_monitor
            return get_system_monitor()
        except Exception as e:
            print(f"Failed to get system monitor: {e}")
            return None

    async def trigger_action(self, action_id: str, target_service: Optional[str] = None):
        """Trigger a healing action."""
        monitor = self._get_system_monitor()
        if not monitor:
            ui.notify("System monitor not available", type="negative")
            return

        try:
            from services.system_monitor import HealingAction

            # Map action_id to HealingAction enum
            action_map = {
                'chrome_cleanup': HealingAction.CHROME_CLEANUP,
                'chrome_kill_all': HealingAction.CHROME_KILL_ALL,
                'xvfb_restart': HealingAction.XVFB_RESTART,
                'browser_pool_drain': HealingAction.BROWSER_POOL_DRAIN,
                'clear_stuck_jobs': HealingAction.CLEAR_STUCK_JOBS,
                'restart_seo_worker': HealingAction.RESTART_SERVICE,
            }

            action = action_map.get(action_id)
            if not action:
                ui.notify(f"Unknown action: {action_id}", type="negative")
                return

            ui.notify(f"Triggering {action_id}...", type="info")
            success, message = monitor.trigger_action_manual(action, target_service)

            if success:
                ui.notify(f"Action completed: {message}", type="positive")
            else:
                ui.notify(f"Action failed: {message}", type="negative")

            # Refresh history
            self.refresh_history()

        except Exception as e:
            ui.notify(f"Failed to trigger action: {e}", type="negative")

    def refresh_history(self):
        """Refresh the healing history."""
        if not self.history_container:
            return

        self.history_container.clear()
        history = get_healing_history(limit=15)

        with self.history_container:
            if not history:
                ui.label("No healing actions recorded").classes('text-gray-400 italic')
            else:
                for action in history:
                    self._render_history_item(action)

    def _render_history_item(self, action: Dict[str, Any]):
        """Render a single history item."""
        success = action.get('success', False)
        trigger_type = action.get('trigger_type', 'unknown')

        with ui.row().classes('w-full items-center gap-2 p-2 rounded hover:bg-gray-700'):
            # Status icon
            if success:
                ui.icon('check_circle', color='positive').classes('text-lg')
            else:
                ui.icon('error', color='negative').classes('text-lg')

            # Action type
            ui.label(action.get('action_type', 'Unknown')).classes('text-sm font-semibold')

            # Trigger badge
            badge_color = 'primary' if trigger_type == 'auto' else 'accent'
            ui.badge(trigger_type.upper(), color=badge_color)

            ui.space()

            # Target service
            if action.get('target_service'):
                ui.label(action['target_service']).classes('text-xs text-gray-400')

            # Duration
            if action.get('duration_seconds'):
                ui.label(f"{action['duration_seconds']:.1f}s").classes('text-xs text-gray-400')

            # Timestamp
            ui.label(format_timestamp(action.get('timestamp', ''))).classes('text-xs text-gray-400')

    def _confirm_dangerous_action(self, action: Dict[str, Any]):
        """Show confirmation dialog for dangerous actions."""
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Confirm: {action['name']}").classes('text-lg font-bold')
            ui.label(action['description']).classes('text-sm text-gray-400')
            ui.label("This action may interrupt running jobs.").classes('text-sm text-warning mt-2')

            with ui.row().classes('w-full gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button(
                    'Confirm',
                    on_click=lambda: (dialog.close(), self.trigger_action(action['id'], action.get('service'))),
                    color='negative'
                )

        dialog.open()

    def render(self) -> ui.card:
        """Render the self-healing panel."""
        with ui.card().classes('w-full p-4') as card:
            # Header
            ui.label("Self-Healing Actions").classes('text-lg font-bold mb-3')

            # Manual action buttons
            ui.label("Manual Triggers").classes('text-sm font-semibold text-gray-400 mb-2')

            with ui.grid(columns=3).classes('w-full gap-2 mb-4'):
                for action in HEALING_ACTIONS:
                    btn = ui.button(
                        action['name'],
                        icon=action['icon'],
                        color=action['color'],
                        on_click=lambda a=action: (
                            self._confirm_dangerous_action(a) if a['dangerous']
                            else self.trigger_action(a['id'], a.get('service'))
                        )
                    ).props('outline dense')
                    btn.tooltip(action['description'])

            # History section
            ui.separator().classes('my-3')

            with ui.row().classes('w-full items-center mb-2'):
                ui.label("Recent Actions").classes('text-sm font-semibold text-gray-400')
                ui.space()
                ui.button(icon='refresh', on_click=self.refresh_history).props('flat dense').tooltip("Refresh")

            # History list
            self.history_container = ui.scroll_area().classes('w-full h-64')

            # Initial load
            self.refresh_history()

            # Auto-refresh timer
            ui.timer(self.refresh_interval, self.refresh_history)

        return card


def self_healing_card(refresh_interval: float = 30.0) -> ui.card:
    """Create a self-healing panel card."""
    panel = SelfHealingPanel(refresh_interval=refresh_interval)
    return panel.render()
