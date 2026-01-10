"""
Error Feed widget - displays recent errors with AI copy functionality.
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from nicegui import ui

from ..components.ai_copy_button import ai_copy_button, format_error_for_ai


# Severity colors
SEVERITY_COLORS = {
    'critical': 'negative',
    'error': 'negative',
    'warning': 'warning',
    'info': 'info',
}

SEVERITY_ICONS = {
    'critical': 'error',
    'error': 'error_outline',
    'warning': 'warning',
    'info': 'info',
}


class ErrorFeedState:
    """State for the error feed."""

    def __init__(self):
        self.errors: List[Dict[str, Any]] = []
        self.expanded_error_id: Optional[int] = None
        self.filter_service: Optional[str] = None
        self.filter_severity: Optional[str] = None
        self.container = None


def get_recent_errors(
    hours: int = 24,
    limit: int = 50,
    service_filter: Optional[str] = None,
    severity_filter: Optional[str] = None,
    unresolved_only: bool = False
) -> List[Dict[str, Any]]:
    """
    Fetch recent errors from database.

    Returns list of error dicts.
    """
    try:
        from sqlalchemy import text
        from db.database_manager import get_db_manager

        db_manager = get_db_manager()

        query = """
            SELECT
                error_id,
                timestamp,
                service_name,
                component,
                error_code,
                severity,
                message,
                error_type,
                stack_trace,
                context,
                system_state,
                resolved,
                auto_resolved,
                occurrence_count,
                resolution_action,
                resolution_notes
            FROM system_errors
            WHERE timestamp > NOW() - INTERVAL '%s hours'
        """ % hours

        conditions = []
        if service_filter:
            conditions.append(f"AND service_name = '{service_filter}'")
        if severity_filter:
            conditions.append(f"AND severity = '{severity_filter}'")
        if unresolved_only:
            conditions.append("AND resolved = FALSE")

        query += " ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT %s" % limit

        with db_manager.get_session() as session:
            result = session.execute(text(query))
            rows = result.fetchall()

        errors = []
        for row in rows:
            errors.append({
                'error_id': row[0],
                'timestamp': row[1].isoformat() if row[1] else None,
                'service_name': row[2],
                'component': row[3],
                'error_code': row[4],
                'severity': row[5],
                'message': row[6],
                'error_type': row[7],
                'stack_trace': row[8],
                'context': row[9] or {},
                'system_state': row[10] or {},
                'resolved': row[11],
                'auto_resolved': row[12],
                'occurrence_count': row[13],
                'resolution_action': row[14],
                'resolution_notes': row[15],
            })

        return errors

    except Exception as e:
        print(f"Error fetching errors: {e}")
        return []


def get_error_stats() -> Dict[str, Any]:
    """Get error statistics for display."""
    try:
        from sqlalchemy import text
        from db.database_manager import get_db_manager

        db_manager = get_db_manager()

        query = """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE severity = 'critical' AND resolved = FALSE) as critical_unresolved,
                COUNT(*) FILTER (WHERE severity = 'error' AND resolved = FALSE) as error_unresolved,
                COUNT(*) FILTER (WHERE severity = 'warning' AND resolved = FALSE) as warning_unresolved,
                COUNT(*) FILTER (WHERE auto_resolved = TRUE) as auto_resolved
            FROM system_errors
            WHERE timestamp > NOW() - INTERVAL '24 hours'
        """

        with db_manager.get_session() as session:
            result = session.execute(text(query))
            row = result.fetchone()

        if row:
            return {
                'total_24h': row[0],
                'critical_unresolved': row[1],
                'error_unresolved': row[2],
                'warning_unresolved': row[3],
                'auto_resolved': row[4],
            }
        return {}

    except Exception as e:
        print(f"Error fetching stats: {e}")
        return {}


def format_timestamp(ts: str) -> str:
    """Format timestamp for display."""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime('%H:%M:%S')
    except:
        return ts[:19] if ts else ""


class ErrorCard:
    """A single error card with expandable details."""

    def __init__(self, error: Dict[str, Any], on_resolve=None):
        self.error = error
        self.on_resolve = on_resolve
        self.expanded = False
        self.details_container = None

    def toggle_expand(self):
        """Toggle expanded state."""
        self.expanded = not self.expanded
        if self.details_container:
            self.details_container.visible = self.expanded

    def get_ai_content(self) -> str:
        """Get AI-formatted content for this error."""
        return format_error_for_ai(
            error_id=self.error['error_id'],
            timestamp=self.error['timestamp'],
            service_name=self.error['service_name'],
            severity=self.error['severity'],
            error_code=self.error.get('error_code'),
            message=self.error['message'],
            error_type=self.error.get('error_type'),
            stack_trace=self.error.get('stack_trace'),
            context=self.error.get('context'),
            system_state=self.error.get('system_state'),
        )

    def resolve_error(self):
        """Mark error as resolved."""
        if self.on_resolve:
            self.on_resolve(self.error['error_id'])

    def render(self) -> ui.element:
        """Render the error card."""
        severity = self.error.get('severity', 'error')
        resolved = self.error.get('resolved', False)

        border_color = 'border-red-500' if severity == 'critical' else (
            'border-orange-500' if severity == 'error' else 'border-yellow-500'
        )

        with ui.card().classes(f'w-full p-3 border-l-4 {border_color}') as card:
            if resolved:
                card.classes('opacity-60')

            # Header row
            with ui.row().classes('w-full items-center gap-2'):
                ui.icon(SEVERITY_ICONS.get(severity, 'info')).classes('text-lg')
                ui.badge(severity.upper(), color=SEVERITY_COLORS.get(severity, 'grey'))

                ui.label(self.error.get('service_name', 'Unknown')).classes('text-sm font-semibold')

                if self.error.get('component'):
                    ui.label(f"/ {self.error['component']}").classes('text-xs text-gray-400')

                ui.space()

                ui.label(format_timestamp(self.error.get('timestamp', ''))).classes('text-xs text-gray-400')

                if self.error.get('occurrence_count', 1) > 1:
                    ui.badge(f"x{self.error['occurrence_count']}", color='accent')

            # Message
            ui.label(self.error.get('message', 'No message')[:200]).classes('text-sm mt-2')

            # Action buttons
            with ui.row().classes('w-full gap-2 mt-2'):
                ui.button(icon='expand_more', on_click=self.toggle_expand).props('flat dense').tooltip("Show details")

                ai_copy_button(
                    content_provider=self.get_ai_content,
                    label="",
                    icon="content_copy",
                    tooltip="Copy for AI troubleshooting"
                )

                if not resolved:
                    ui.button(icon='check', on_click=self.resolve_error).props('flat dense color=positive').tooltip("Mark resolved")

                if self.error.get('auto_resolved'):
                    ui.badge("Auto-resolved", color='positive')

            # Expandable details
            with ui.column().classes('w-full mt-3') as details:
                self.details_container = details
                details.visible = False

                # Error type and code
                if self.error.get('error_type') or self.error.get('error_code'):
                    with ui.row().classes('gap-4'):
                        if self.error.get('error_type'):
                            ui.label(f"Type: {self.error['error_type']}").classes('text-xs')
                        if self.error.get('error_code'):
                            ui.label(f"Code: {self.error['error_code']}").classes('text-xs')

                # Stack trace
                if self.error.get('stack_trace'):
                    ui.label("Stack Trace:").classes('text-xs font-semibold mt-2')
                    trace = self.error['stack_trace'][:1000]
                    ui.code(trace, language='python').classes('w-full text-xs')

                # Context
                if self.error.get('context'):
                    ui.label("Context:").classes('text-xs font-semibold mt-2')
                    ctx = json.dumps(self.error['context'], indent=2, default=str)
                    ui.code(ctx, language='json').classes('w-full text-xs')

                # System state
                if self.error.get('system_state'):
                    ui.label("System State:").classes('text-xs font-semibold mt-2')
                    state = json.dumps(self.error['system_state'], indent=2, default=str)
                    ui.code(state, language='json').classes('w-full text-xs')

        return card


class ErrorFeed:
    """Error feed panel with filtering and refresh."""

    def __init__(self, refresh_interval: float = 10.0):
        self.state = ErrorFeedState()
        self.refresh_interval = refresh_interval
        self.container = None
        self.stats_container = None

    def refresh(self):
        """Refresh the error feed."""
        self.state.errors = get_recent_errors(
            hours=24,
            limit=50,
            service_filter=self.state.filter_service,
            severity_filter=self.state.filter_severity,
        )
        self._render_errors()
        self._render_stats()

    def _render_stats(self):
        """Render error statistics."""
        if not self.stats_container:
            return

        self.stats_container.clear()
        stats = get_error_stats()

        with self.stats_container:
            with ui.row().classes('gap-4'):
                with ui.card().classes('p-2 bg-red-900'):
                    ui.label("Critical").classes('text-xs')
                    ui.label(str(stats.get('critical_unresolved', 0))).classes('text-xl font-bold')

                with ui.card().classes('p-2 bg-orange-900'):
                    ui.label("Errors").classes('text-xs')
                    ui.label(str(stats.get('error_unresolved', 0))).classes('text-xl font-bold')

                with ui.card().classes('p-2 bg-yellow-900'):
                    ui.label("Warnings").classes('text-xs')
                    ui.label(str(stats.get('warning_unresolved', 0))).classes('text-xl font-bold')

                with ui.card().classes('p-2 bg-green-900'):
                    ui.label("Auto-Healed").classes('text-xs')
                    ui.label(str(stats.get('auto_resolved', 0))).classes('text-xl font-bold')

    def _render_errors(self):
        """Render error list."""
        if not self.container:
            return

        self.container.clear()

        with self.container:
            if not self.state.errors:
                ui.label("No errors in the last 24 hours").classes('text-gray-400 italic')
            else:
                for error in self.state.errors:
                    ErrorCard(error, on_resolve=self._mark_resolved).render()

    def _mark_resolved(self, error_id: int):
        """Mark an error as resolved."""
        try:
            from sqlalchemy import text
            from db.database_manager import get_db_manager

            db_manager = get_db_manager()
            with db_manager.get_session() as session:
                session.execute(text("""
                    UPDATE system_errors
                    SET resolved = TRUE, resolved_at = NOW(), resolution_action = 'manual'
                    WHERE error_id = :id
                """), {"id": error_id})
                session.commit()

            ui.notify(f"Error #{error_id} marked as resolved", type="positive")
            self.refresh()

        except Exception as e:
            ui.notify(f"Failed to resolve: {e}", type="negative")

    def _export_all_for_ai(self) -> str:
        """Export all visible errors for AI."""
        lines = ["# Error Export for AI Troubleshooting", ""]
        for error in self.state.errors[:20]:  # Limit to 20
            lines.append(format_error_for_ai(
                error_id=error['error_id'],
                timestamp=error['timestamp'],
                service_name=error['service_name'],
                severity=error['severity'],
                error_code=error.get('error_code'),
                message=error['message'],
                error_type=error.get('error_type'),
                stack_trace=error.get('stack_trace'),
                context=error.get('context'),
                system_state=error.get('system_state'),
            ))
            lines.append("")
        return "\n".join(lines)

    def render(self) -> ui.card:
        """Render the error feed panel."""
        with ui.card().classes('w-full p-4') as card:
            # Header
            with ui.row().classes('w-full items-center mb-3'):
                ui.label("Error Feed").classes('text-lg font-bold')
                ui.space()
                ui.button(icon='refresh', on_click=self.refresh).props('flat dense').tooltip("Refresh")
                ai_copy_button(
                    content_provider=self._export_all_for_ai,
                    label="Export All",
                    icon="file_copy",
                    tooltip="Export all errors for AI"
                )

            # Stats row
            self.stats_container = ui.row().classes('w-full mb-3')
            self._render_stats()

            # Filter row
            with ui.row().classes('w-full gap-2 mb-3'):
                service_select = ui.select(
                    ['All', 'seo_worker', 'yp_scraper', 'google_scraper', 'verification', 'browser_pool', 'system'],
                    value='All',
                    label='Service',
                    on_change=lambda e: self._set_filter('service', e.value)
                ).classes('w-40')

                severity_select = ui.select(
                    ['All', 'critical', 'error', 'warning', 'info'],
                    value='All',
                    label='Severity',
                    on_change=lambda e: self._set_filter('severity', e.value)
                ).classes('w-32')

            # Error list
            self.container = ui.scroll_area().classes('w-full h-96')

            # Initial load
            self.refresh()

            # Auto-refresh timer
            ui.timer(self.refresh_interval, self.refresh)

        return card

    def _set_filter(self, filter_type: str, value: str):
        """Set a filter value."""
        if value == 'All':
            value = None
        if filter_type == 'service':
            self.state.filter_service = value
        elif filter_type == 'severity':
            self.state.filter_severity = value
        self.refresh()


def error_feed_card(refresh_interval: float = 10.0) -> ui.card:
    """Create an error feed card."""
    feed = ErrorFeed(refresh_interval=refresh_interval)
    return feed.render()
