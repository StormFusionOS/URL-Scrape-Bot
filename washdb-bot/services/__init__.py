"""
Services module for Washbot.

Contains shared services like email alerts, notifications, etc.
"""

from .email_alerts import EmailAlertService

__all__ = ['EmailAlertService']
