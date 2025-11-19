"""
Real-Time Error Notification System
Toast notifications for critical errors with WebSocket support
"""

from nicegui import ui
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ErrorNotificationSystem:
    """Manages real-time error notifications"""

    def __init__(self):
        self.error_count = 0
        self.last_error_id = 0
        self.notification_badge = None

    def set_badge(self, badge):
        """Set the error badge element"""
        self.notification_badge = badge

    def show_error(self, severity: str, title: str, message: str, error_id: Optional[int] = None):
        """
        Show error toast notification

        Args:
            severity: CRITICAL, HIGH, MEDIUM, LOW
            title: Error title
            message: Error message
            error_id: Optional error ID for tracking
        """
        severity_lower = severity.lower()

        # Determine notification type and duration
        if severity in ['CRITICAL', 'HIGH']:
            notify_type = 'negative'
            duration = 0  # Stays until dismissed
            icon = 'error'
            self.error_count += 1
        elif severity == 'MEDIUM':
            notify_type = 'warning'
            duration = 10000  # 10 seconds
            icon = 'warning'
        else:
            notify_type = 'info'
            duration = 5000  # 5 seconds
            icon = 'info'

        # Create notification
        notification_message = f"**{title}**\n{message}"

        if error_id:
            notification_message += f"\n\n[View Details](/errors?id={error_id})"

        # Show toast
        ui.notify(
            notification_message,
            type=notify_type,
            close_button=True,
            timeout=duration,
            position='top-right',
            icon=icon,
            multi_line=True
        )

        # Update badge
        self._update_badge()

        logger.info(f"Error notification shown: {severity} - {title}")

    def _update_badge(self):
        """Update the error count badge"""
        if self.notification_badge:
            try:
                self.notification_badge.set_text(str(self.error_count))
                if self.error_count > 0:
                    self.notification_badge.props('color=negative')
                else:
                    self.notification_badge.props('color=grey')
            except Exception as e:
                logger.error(f"Failed to update badge: {e}")

    def clear_count(self):
        """Clear error count"""
        self.error_count = 0
        self._update_badge()

    def check_new_errors(self, db_session):
        """
        Check for new errors in database

        Args:
            db_session: Database session

        Returns:
            List of new errors
        """
        from sqlalchemy import text

        try:
            # Query for errors newer than last checked
            query = text("""
                SELECT id, error_severity, component, error_message, occurred_at
                FROM seo_analytics.seo_error_logs
                WHERE id > :last_id
                  AND error_severity IN ('CRITICAL', 'HIGH', 'MEDIUM')
                  AND occurred_at > NOW() - INTERVAL '5 minutes'
                ORDER BY id DESC
                LIMIT 10
            """)

            result = db_session.execute(query, {'last_id': self.last_error_id})
            new_errors = result.fetchall()

            # Update last error ID
            if new_errors:
                self.last_error_id = max(error[0] for error in new_errors)

                # Show notifications for new errors
                for error in new_errors:
                    error_id, severity, component, message, occurred_at = error
                    self.show_error(
                        severity=severity,
                        title=f"{component} Error",
                        message=message[:100] + ('...' if len(message) > 100 else ''),
                        error_id=error_id
                    )

            return new_errors

        except Exception as e:
            logger.error(f"Error checking for new errors: {e}")
            return []


# Global instance
error_notification_system = ErrorNotificationSystem()
