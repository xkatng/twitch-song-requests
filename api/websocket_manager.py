"""
WebSocket connection manager for real-time overlay updates.
"""

import asyncio
import logging
from typing import List, Set
from fastapi import WebSocket

from models.events import (
    WebSocketEvent,
    ConnectionEvent,
    SongChangeEvent,
    VoteUpdateEvent,
    QueueUpdateEvent,
    PlaybackProgressEvent,
)

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts events to all clients.
    Used for real-time overlay and dashboard updates.
    """

    def __init__(self):
        """Initialize the WebSocket manager."""
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept
        """
        await websocket.accept()

        async with self._lock:
            self.active_connections.append(websocket)

        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove
        """
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal(self, websocket: WebSocket, event: WebSocketEvent) -> bool:
        """
        Send an event to a specific client.

        Args:
            websocket: Target WebSocket connection
            event: Event to send

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            await websocket.send_text(event.to_json())
            return True
        except Exception as e:
            logger.error(f"Failed to send to client: {e}")
            return False

    async def broadcast(self, event: WebSocketEvent) -> int:
        """
        Send an event to all connected clients.

        Args:
            event: Event to broadcast

        Returns:
            Number of clients that received the message
        """
        if not self.active_connections:
            return 0

        message = event.to_json()
        disconnected: List[WebSocket] = []
        sent_count = 0

        for connection in self.active_connections:
            try:
                await connection.send_text(message)
                sent_count += 1
            except Exception as e:
                logger.debug(f"Client disconnected during broadcast: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        async with self._lock:
            for conn in disconnected:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)

        if disconnected:
            logger.info(f"Cleaned up {len(disconnected)} disconnected clients")

        return sent_count

    async def broadcast_song_change(
        self,
        title: str,
        artist: str,
        album: str = "",
        album_art_url: str = "",
        requester: str = None,
        duration_ms: int = 0,
        progress_ms: int = 0,
        likes: int = 0,
        skips: int = 0,
        is_request: bool = False,
    ) -> int:
        """
        Broadcast a song change event.

        Returns:
            Number of clients notified
        """
        event = SongChangeEvent(
            title=title,
            artist=artist,
            album=album,
            album_art_url=album_art_url,
            requester=requester,
            duration_ms=duration_ms,
            progress_ms=progress_ms,
            likes=likes,
            skips=skips,
            is_request=is_request,
        )
        return await self.broadcast(event)

    async def broadcast_vote_update(
        self,
        likes: int,
        skips: int,
        skip_threshold: int = 5,
    ) -> int:
        """
        Broadcast a vote update event.

        Returns:
            Number of clients notified
        """
        event = VoteUpdateEvent(
            likes=likes,
            skips=skips,
            skip_threshold=skip_threshold,
        )
        return await self.broadcast(event)

    async def broadcast_queue_update(
        self,
        queue: list,
        max_queue_size: int = 10,
        next_song: dict = None,
    ) -> int:
        """
        Broadcast a queue update event.

        Returns:
            Number of clients notified
        """
        event = QueueUpdateEvent(
            queue=queue,
            queue_length=len(queue),
            max_queue_size=max_queue_size,
            next_song=next_song,
        )
        return await self.broadcast(event)

    async def broadcast_progress(
        self,
        progress_ms: int,
        duration_ms: int,
        is_playing: bool = True,
    ) -> int:
        """
        Broadcast a playback progress event.

        Returns:
            Number of clients notified
        """
        event = PlaybackProgressEvent(
            progress_ms=progress_ms,
            duration_ms=duration_ms,
            is_playing=is_playing,
        )
        return await self.broadcast(event)

    async def send_welcome(
        self,
        websocket: WebSocket,
        queue_length: int = 0,
        is_playing_requests: bool = False,
    ) -> bool:
        """
        Send welcome message to a newly connected client.

        Args:
            websocket: The new client
            queue_length: Current queue length
            is_playing_requests: Whether playing from request queue

        Returns:
            True if sent successfully
        """
        event = ConnectionEvent(
            queue_length=queue_length,
            is_playing_requests=is_playing_requests,
        )
        return await self.send_personal(websocket, event)

    @property
    def connection_count(self) -> int:
        """Get the number of active connections."""
        return len(self.active_connections)

    @property
    def has_connections(self) -> bool:
        """Check if there are any active connections."""
        return len(self.active_connections) > 0
