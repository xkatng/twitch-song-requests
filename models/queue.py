"""
Queue state and cooldown tracking models.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .song import Song, SongRequest


@dataclass
class CooldownTracker:
    """Tracks per-user cooldowns for song requests."""

    # Maps username (lowercase) to their last request time
    last_request_times: Dict[str, datetime] = field(default_factory=dict)

    def check_cooldown(self, username: str, cooldown_seconds: int) -> tuple[bool, int]:
        """
        Check if a user can make a request.

        Args:
            username: Twitch username
            cooldown_seconds: Required seconds between requests

        Returns:
            Tuple of (can_request, seconds_remaining)
        """
        username = username.lower()

        if username not in self.last_request_times:
            return True, 0

        last_request = self.last_request_times[username]
        elapsed = (datetime.now() - last_request).total_seconds()

        if elapsed >= cooldown_seconds:
            return True, 0

        remaining = int(cooldown_seconds - elapsed)
        return False, remaining

    def record_request(self, username: str) -> None:
        """Record that a user made a request."""
        self.last_request_times[username.lower()] = datetime.now()

    def clear(self) -> None:
        """Clear all cooldowns (e.g., for new session)."""
        self.last_request_times.clear()


@dataclass
class QueueState:
    """
    Manages the song request queue state.
    This is an in-memory queue that resets each session.
    """

    # Current song being played (if from queue)
    current_request: Optional[SongRequest] = None

    # Songs waiting to be played
    queue: List[SongRequest] = field(default_factory=list)

    # Track Spotify IDs that have been played/queued this session (no duplicates)
    played_song_ids: set = field(default_factory=set)

    # Session start time
    session_start: datetime = field(default_factory=datetime.now)

    # Previous Spotify context to resume when queue empties
    previous_context_uri: Optional[str] = None

    # Whether we're currently playing from the request queue
    is_playing_requests: bool = False

    @property
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self.queue) == 0

    @property
    def queue_length(self) -> int:
        """Get number of songs in queue."""
        return len(self.queue)

    @property
    def has_current(self) -> bool:
        """Check if there's a current request playing."""
        return self.current_request is not None

    def can_add(self, max_size: int) -> bool:
        """Check if queue has room for more songs."""
        return len(self.queue) < max_size

    def is_duplicate(self, song: Song) -> bool:
        """Check if song was already played/queued this session."""
        return song.spotify_id in self.played_song_ids

    def is_in_queue(self, song: Song) -> bool:
        """Check if song is currently in the queue."""
        return any(r.song.spotify_id == song.spotify_id for r in self.queue)

    def add_request(self, request: SongRequest) -> int:
        """
        Add a request to the queue.
        Returns the position in queue (1-indexed).
        """
        self.queue.append(request)
        self.played_song_ids.add(request.song.spotify_id)
        return len(self.queue)

    def get_next(self) -> Optional[SongRequest]:
        """
        Pop and return the next request from queue.
        Returns None if queue is empty.
        """
        if self.queue:
            return self.queue.pop(0)
        return None

    def set_current(self, request: Optional[SongRequest]) -> None:
        """Set the currently playing request."""
        self.current_request = request
        self.is_playing_requests = request is not None

    def remove_at(self, index: int) -> Optional[SongRequest]:
        """
        Remove request at specific index.
        Returns the removed request or None if index invalid.
        """
        if 0 <= index < len(self.queue):
            return self.queue.pop(index)
        return None

    def remove_by_id(self, spotify_id: str) -> Optional[SongRequest]:
        """
        Remove request by Spotify track ID.
        Returns the removed request or None if not found.
        """
        for i, request in enumerate(self.queue):
            if request.song.spotify_id == spotify_id:
                return self.queue.pop(i)
        return None

    def clear_queue(self) -> int:
        """Clear all songs from queue. Returns number of songs removed."""
        count = len(self.queue)
        self.queue.clear()
        return count

    def reset_session(self) -> None:
        """Reset for a new session."""
        self.current_request = None
        self.queue.clear()
        self.played_song_ids.clear()
        self.session_start = datetime.now()
        self.previous_context_uri = None
        self.is_playing_requests = False

    def get_queue_snapshot(self) -> List[dict]:
        """Get simplified queue state for API/WebSocket."""
        return [
            request.to_queue_item(i + 1)
            for i, request in enumerate(self.queue)
        ]

    def get_next_preview(self) -> Optional[dict]:
        """Get preview of next song in queue."""
        if self.queue:
            next_request = self.queue[0]
            return {
                "title": next_request.song.title,
                "artist": next_request.song.artist,
                "requester": next_request.requester,
            }
        return None

    def to_dict(self) -> dict:
        """Convert full state to dictionary."""
        return {
            "current_request": (
                self.current_request.to_dict() if self.current_request else None
            ),
            "queue": self.get_queue_snapshot(),
            "queue_length": self.queue_length,
            "is_playing_requests": self.is_playing_requests,
            "session_start": self.session_start.isoformat(),
            "next_song": self.get_next_preview(),
        }
