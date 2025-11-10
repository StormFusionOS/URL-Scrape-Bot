"""
Router and navigation helpers for NiceGUI dashboard.
"""

from typing import Callable, Dict, List
from nicegui import ui


class Router:
    """Simple router for managing pages."""

    def __init__(self):
        self.pages: Dict[str, Callable] = {}
        self.current_page = 'dashboard'

    def register(self, name: str, page_func: Callable):
        """Register a page."""
        self.pages[name] = page_func

    def navigate(self, name: str, content_area):
        """Navigate to a page."""
        if name in self.pages:
            self.current_page = name
            content_area.clear()
            with content_area:
                self.pages[name]()

    def get_current(self) -> str:
        """Get current page name."""
        return self.current_page


class SimpleEventBus:
    """Simple event bus for broadcasting events across pages."""

    def __init__(self):
        self.listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event_name: str, callback: Callable):
        """Subscribe to an event."""
        if event_name not in self.listeners:
            self.listeners[event_name] = []
        self.listeners[event_name].append(callback)

    def publish(self, event_name: str, data=None):
        """Publish an event to all subscribers."""
        if event_name in self.listeners:
            for callback in self.listeners[event_name]:
                try:
                    if data is not None:
                        callback(data)
                    else:
                        callback()
                except Exception as e:
                    print(f"Error in event listener for {event_name}: {e}")

    def unsubscribe(self, event_name: str, callback: Callable):
        """Unsubscribe from an event."""
        if event_name in self.listeners and callback in self.listeners[event_name]:
            self.listeners[event_name].remove(callback)


# Global instances
router = Router()
event_bus = SimpleEventBus()
