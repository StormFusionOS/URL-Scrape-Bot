"""
WebSocket Manager for Real-Time Updates
Handles Socket.IO connections and event broadcasting
"""

import socketio
import logging
from typing import Dict, Any, List
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and real-time event broadcasting"""

    def __init__(self):
        self.sio = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins='*',  # Adjust for production
            logger=True,
            engineio_logger=False
        )

        self.connected_clients: Dict[str, Any] = {}
        self.event_buffer: List[Dict[str, Any]] = []  # Buffer last 100 events
        self.max_buffer_size = 100

        self._setup_handlers()

    def _setup_handlers(self):
        """Set up Socket.IO event handlers"""

        @self.sio.event
        async def connect(sid, environ):
            """Handle client connection"""
            logger.info(f"Client connected: {sid}")
            self.connected_clients[sid] = {
                'connected_at': datetime.now(),
                'subscriptions': []
            }

            # Send buffered events to newly connected client
            for event in self.event_buffer:
                await self.sio.emit(
                    event['type'],
                    event['data'],
                    room=sid
                )

            await self.sio.emit('connection_established', {
                'sid': sid,
                'timestamp': datetime.now().isoformat(),
                'buffered_events': len(self.event_buffer)
            }, room=sid)

        @self.sio.event
        async def disconnect(sid):
            """Handle client disconnection"""
            logger.info(f"Client disconnected: {sid}")
            if sid in self.connected_clients:
                del self.connected_clients[sid]

        @self.sio.event
        async def subscribe(sid, data):
            """Handle subscription to specific event types"""
            event_types = data.get('events', [])
            if sid in self.connected_clients:
                self.connected_clients[sid]['subscriptions'] = event_types
                logger.info(f"Client {sid} subscribed to: {event_types}")
                await self.sio.emit('subscribed', {
                    'events': event_types
                }, room=sid)

        @self.sio.event
        async def ping(sid):
            """Handle ping for connection health check"""
            await self.sio.emit('pong', {'timestamp': datetime.now().isoformat()}, room=sid)

    async def broadcast(self, event_type: str, data: Dict[str, Any], to_subscribed_only: bool = False):
        """
        Broadcast event to all connected clients

        Args:
            event_type: Type of event (job_started, job_completed, new_error, etc.)
            data: Event data
            to_subscribed_only: Only send to clients subscribed to this event type
        """
        event = {
            'type': event_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }

        # Add to buffer
        self.event_buffer.append(event)
        if len(self.event_buffer) > self.max_buffer_size:
            self.event_buffer.pop(0)

        # Broadcast to clients
        if to_subscribed_only:
            # Send only to subscribed clients
            for sid, client_info in self.connected_clients.items():
                if event_type in client_info.get('subscriptions', []):
                    await self.sio.emit(event_type, data, room=sid)
        else:
            # Broadcast to all
            await self.sio.emit(event_type, data)

        logger.debug(f"Broadcasted {event_type} to {len(self.connected_clients)} clients")

    async def emit_to_client(self, sid: str, event_type: str, data: Dict[str, Any]):
        """Send event to specific client"""
        if sid in self.connected_clients:
            await self.sio.emit(event_type, data, room=sid)

    def get_connected_count(self) -> int:
        """Get number of connected clients"""
        return len(self.connected_clients)

    def get_asgi_app(self):
        """Get ASGI app for Socket.IO"""
        return socketio.ASGIApp(
            self.sio,
            socketio_path='/socket.io'
        )


# Singleton instance
_websocket_manager: WebSocketManager = None


def get_websocket_manager() -> WebSocketManager:
    """Get or create WebSocket manager singleton"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
