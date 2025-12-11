"""
Song and SongRequest data models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Set


@dataclass
class Song:
    """Represents a Spotify track."""

    spotify_id: str
    title: str
    artist: str
    album: str
    duration_ms: int
    album_art_url: Optional[str] = None

    @property
    def spotify_uri(self) -> str:
        """Get the Spotify URI for this track."""
        return f"spotify:track:{self.spotify_id}"

    @property
    def duration_seconds(self) -> int:
        """Get duration in seconds."""
        return self.duration_ms // 1000

    @property
    def duration_formatted(self) -> str:
        """Get duration as M:SS string."""
        total_seconds = self.duration_seconds
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "spotify_id": self.spotify_id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration_ms": self.duration_ms,
            "album_art_url": self.album_art_url,
            "spotify_uri": self.spotify_uri,
            "duration_formatted": self.duration_formatted,
        }

    def __hash__(self) -> int:
        """Hash by Spotify ID for set operations."""
        return hash(self.spotify_id)

    def __eq__(self, other: object) -> bool:
        """Compare by Spotify ID."""
        if isinstance(other, Song):
            return self.spotify_id == other.spotify_id
        return False


@dataclass
class SongRequest:
    """Represents a song request from a viewer."""

    song: Song
    requester: str  # Twitch username
    requested_at: datetime = field(default_factory=datetime.now)
    likes: Set[str] = field(default_factory=set)  # Usernames who liked
    skip_votes: Set[str] = field(default_factory=set)  # Usernames who voted skip
    source: str = "channel_points"  # Always channel_points per requirements

    @property
    def like_count(self) -> int:
        """Number of likes."""
        return len(self.likes)

    @property
    def skip_count(self) -> int:
        """Number of skip votes."""
        return len(self.skip_votes)

    def add_like(self, username: str) -> bool:
        """
        Add a like from a user.
        Returns True if this is a new like, False if already liked.
        """
        username = username.lower()
        if username in self.likes:
            return False
        self.likes.add(username)
        return True

    def add_skip_vote(self, username: str) -> bool:
        """
        Add a skip vote from a user.
        Returns True if this is a new vote, False if already voted.
        """
        username = username.lower()
        if username in self.skip_votes:
            return False
        self.skip_votes.add(username)
        return True

    def should_skip(self, threshold: int) -> bool:
        """Check if skip votes have reached the threshold."""
        return self.skip_count >= threshold

    def reset_votes(self) -> None:
        """Reset all likes and skip votes for this request."""
        self.likes.clear()
        self.skip_votes.clear()

    def to_dict(self, include_votes: bool = True) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "song": self.song.to_dict(),
            "requester": self.requester,
            "requested_at": self.requested_at.isoformat(),
            "source": self.source,
        }
        if include_votes:
            result["likes"] = self.like_count
            result["skips"] = self.skip_count
        return result

    def to_queue_item(self, position: int) -> dict:
        """Convert to simplified queue item for display."""
        return {
            "position": position,
            "spotify_id": self.song.spotify_id,
            "title": self.song.title,
            "artist": self.song.artist,
            "album_art_url": self.song.album_art_url,
            "requester": self.requester,
            "duration_formatted": self.song.duration_formatted,
        }
