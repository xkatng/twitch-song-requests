"""
WebSocket event models for real-time overlay updates.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any
import json


@dataclass
class WebSocketEvent:
    """Base class for WebSocket events."""

    event_type: str

    def to_json(self) -> str:
        """Serialize event to JSON string."""
        return json.dumps(asdict(self))

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class SongChangeEvent(WebSocketEvent):
    """
    Sent when the current song changes.
    Used by overlay to update display.
    """

    event_type: str = "song_change"
    title: str = ""
    artist: str = ""
    album: str = ""
    album_art_url: str = ""
    requester: Optional[str] = None  # None if not a request (regular playback)
    duration_ms: int = 0
    progress_ms: int = 0
    likes: int = 0
    skips: int = 0
    is_request: bool = False  # True if from request queue

    @classmethod
    def from_request(cls, request: Any, progress_ms: int = 0) -> "SongChangeEvent":
        """Create event from a SongRequest object."""
        return cls(
            title=request.song.title,
            artist=request.song.artist,
            album=request.song.album,
            album_art_url=request.song.album_art_url or "",
            requester=request.requester,
            duration_ms=request.song.duration_ms,
            progress_ms=progress_ms,
            likes=request.like_count,
            skips=request.skip_count,
            is_request=True,
        )

    @classmethod
    def from_spotify_track(cls, track: dict, progress_ms: int = 0) -> "SongChangeEvent":
        """Create event from Spotify API track data (non-request)."""
        album_art = ""
        if track.get("album", {}).get("images"):
            album_art = track["album"]["images"][0]["url"]

        artists = ", ".join(a["name"] for a in track.get("artists", []))

        return cls(
            title=track.get("name", "Unknown"),
            artist=artists,
            album=track.get("album", {}).get("name", ""),
            album_art_url=album_art,
            requester=None,
            duration_ms=track.get("duration_ms", 0),
            progress_ms=progress_ms,
            likes=0,
            skips=0,
            is_request=False,
        )


@dataclass
class VoteUpdateEvent(WebSocketEvent):
    """
    Sent when vote counts change.
    Used by overlay to update vote display.
    """

    event_type: str = "vote_update"
    likes: int = 0
    skips: int = 0
    skip_threshold: int = 5


@dataclass
class QueueUpdateEvent(WebSocketEvent):
    """
    Sent when the queue changes.
    Used by overlay for "up next" and dashboard for queue list.
    """

    event_type: str = "queue_update"
    queue: List[dict] = field(default_factory=list)
    queue_length: int = 0
    max_queue_size: int = 10
    next_song: Optional[dict] = None  # Preview of next song

    @classmethod
    def from_queue_state(
        cls,
        queue_snapshot: List[dict],
        max_size: int,
        next_preview: Optional[dict] = None
    ) -> "QueueUpdateEvent":
        """Create event from queue state."""
        return cls(
            queue=queue_snapshot,
            queue_length=len(queue_snapshot),
            max_queue_size=max_size,
            next_song=next_preview,
        )


@dataclass
class PlaybackProgressEvent(WebSocketEvent):
    """
    Sent periodically to sync playback progress.
    Used by overlay for progress bar.
    """

    event_type: str = "playback_progress"
    progress_ms: int = 0
    duration_ms: int = 0
    is_playing: bool = True

    @property
    def progress_percent(self) -> float:
        """Calculate progress as percentage."""
        if self.duration_ms <= 0:
            return 0.0
        return min(100.0, (self.progress_ms / self.duration_ms) * 100)

    @property
    def remaining_ms(self) -> int:
        """Calculate remaining time in ms."""
        return max(0, self.duration_ms - self.progress_ms)


@dataclass
class ErrorEvent(WebSocketEvent):
    """
    Sent when an error occurs.
    Used for debugging and user feedback.
    """

    event_type: str = "error"
    message: str = ""
    code: str = ""
    details: Optional[str] = None


@dataclass
class ConnectionEvent(WebSocketEvent):
    """
    Sent when a client connects.
    Provides initial state.
    """

    event_type: str = "connected"
    queue_length: int = 0
    is_playing_requests: bool = False
    server_version: str = "1.0.0"


@dataclass
class SettingsUpdateEvent(WebSocketEvent):
    """
    Sent when settings are updated via dashboard.
    """

    event_type: str = "settings_update"
    skip_threshold: int = 5
    cooldown_seconds: int = 300
    max_queue_size: int = 10
