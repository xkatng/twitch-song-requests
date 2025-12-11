"""
Queue management service.
Handles song requests, voting, cooldowns, and blocklist.
"""

import logging
from typing import Optional, Tuple, List
from datetime import datetime

from models.song import Song, SongRequest
from models.queue import QueueState, CooldownTracker
from config.settings import RuntimeSettings

logger = logging.getLogger(__name__)


class QueueError(Exception):
    """Base exception for queue-related errors."""

    def __init__(self, message: str, user_message: str, code: str):
        super().__init__(message)
        self.user_message = user_message
        self.code = code


class QueueFullError(QueueError):
    """Raised when queue is at max capacity."""

    def __init__(self, max_size: int):
        super().__init__(
            f"Queue full ({max_size} songs)",
            f"Queue is full! (max {max_size} songs)",
            "QUEUE_FULL"
        )


class DuplicateSongError(QueueError):
    """Raised when song was already played/queued this session."""

    def __init__(self):
        super().__init__(
            "Song already played/queued this session",
            "That song was already played this session!",
            "DUPLICATE_SONG"
        )


class SongBlockedError(QueueError):
    """Raised when song or artist is in blocklist."""

    def __init__(self):
        super().__init__(
            "Song or artist is blocked",
            "Sorry, that song/artist is blocked.",
            "SONG_BLOCKED"
        )


class UserCooldownError(QueueError):
    """Raised when user is on cooldown."""

    def __init__(self, remaining_seconds: int):
        super().__init__(
            f"User on cooldown for {remaining_seconds}s",
            f"Please wait {remaining_seconds}s before requesting again.",
            "USER_ON_COOLDOWN"
        )
        self.remaining_seconds = remaining_seconds


class InvalidLinkError(QueueError):
    """Raised when user sends an album/playlist/artist link instead of a track."""

    def __init__(self, link_type: str):
        messages = {
            'album': "Please send a song link, not an album link!",
            'playlist': "Please send a song link, not a playlist link!",
            'artist': "Please send a song link, not an artist link!",
        }
        user_msg = messages.get(link_type, "Please send a song link, not an album/playlist link!")
        super().__init__(
            f"Invalid link type: {link_type}",
            user_msg,
            "INVALID_LINK_TYPE"
        )
        self.link_type = link_type


class QueueService:
    """
    Manages the song request queue.
    Handles adding requests, voting, and queue operations.
    """

    def __init__(self, settings: RuntimeSettings):
        """
        Initialize queue service.

        Args:
            settings: Runtime settings (modifiable via dashboard)
        """
        self.settings = settings
        self.state = QueueState()
        self.cooldowns = CooldownTracker()

        # Standalone vote tracking for non-request songs
        self._standalone_likes: set = set()  # usernames
        self._standalone_skips: set = set()  # usernames

    # -------------------------------------------------------------------------
    # Request Management
    # -------------------------------------------------------------------------

    def add_request(
        self,
        song: Song,
        requester: str,
        bypass_cooldown: bool = False,
    ) -> Tuple[SongRequest, int]:
        """
        Add a song request to the queue.

        Args:
            song: Song to add
            requester: Twitch username of requester
            bypass_cooldown: Skip cooldown check (for mods)

        Returns:
            Tuple of (SongRequest, queue_position)

        Raises:
            QueueFullError: Queue is at max capacity
            DuplicateSongError: Song already played this session
            SongBlockedError: Song or artist is blocked
            UserCooldownError: User is on cooldown
        """
        # Check queue capacity
        if not self.state.can_add(self.settings.max_queue_size):
            raise QueueFullError(self.settings.max_queue_size)

        # Check for duplicates (already played or in queue)
        if self.state.is_duplicate(song):
            raise DuplicateSongError()

        if self.state.is_in_queue(song):
            raise DuplicateSongError()

        # Check blocklist
        if self._is_blocked(song):
            raise SongBlockedError()

        # Check cooldown
        if not bypass_cooldown:
            allowed, remaining = self.cooldowns.check_cooldown(
                requester,
                self.settings.cooldown_seconds
            )
            if not allowed:
                raise UserCooldownError(remaining)

        # Create and add request
        request = SongRequest(
            song=song,
            requester=requester,
            source="channel_points"
        )

        position = self.state.add_request(request)
        self.cooldowns.record_request(requester)

        logger.info(
            f"Added request: '{song.title}' by {song.artist} "
            f"(requested by {requester}, position {position})"
        )

        return request, position

    def _is_blocked(self, song: Song) -> bool:
        """Check if song or artist is in blocklist."""
        # Check song ID blocklist
        if song.spotify_id in self.settings.blocklist_song_ids:
            return True

        # Check artist blocklist (case-insensitive partial match)
        artist_lower = song.artist.lower()
        for blocked_artist in self.settings.blocklist_artists:
            if blocked_artist.lower() in artist_lower:
                return True

        return False

    # -------------------------------------------------------------------------
    # Queue Operations
    # -------------------------------------------------------------------------

    def get_next(self) -> Optional[SongRequest]:
        """
        Get and remove the next song from queue.

        Returns:
            Next SongRequest or None if queue empty
        """
        request = self.state.get_next()
        if request:
            self.state.set_current(request)
            logger.info(f"Now playing: '{request.song.title}' requested by {request.requester}")
        return request

    def set_current(self, request: Optional[SongRequest]) -> None:
        """Set the currently playing request."""
        self.state.set_current(request)

    def clear_current(self) -> None:
        """Clear the current request (song ended)."""
        self.state.set_current(None)

    def get_current(self) -> Optional[SongRequest]:
        """Get the currently playing request."""
        return self.state.current_request

    def remove_at(self, index: int) -> Optional[SongRequest]:
        """
        Remove request at specific queue index.

        Args:
            index: 0-based index in queue

        Returns:
            Removed request or None if index invalid
        """
        request = self.state.remove_at(index)
        if request:
            logger.info(f"Removed from queue: '{request.song.title}'")
        return request

    def remove_by_id(self, spotify_id: str) -> Optional[SongRequest]:
        """
        Remove request by Spotify track ID.

        Returns:
            Removed request or None if not found
        """
        request = self.state.remove_by_id(spotify_id)
        if request:
            logger.info(f"Removed from queue: '{request.song.title}'")
        return request

    def find_and_remove_by_spotify_id(self, spotify_id: str) -> Optional[SongRequest]:
        """
        Find a request in the queue by Spotify ID and remove it.
        Used when Spotify starts playing a track to check if it was requested.

        Args:
            spotify_id: Spotify track ID

        Returns:
            The matching SongRequest or None if not found
        """
        # Search through the queue for matching track
        for i, request in enumerate(self.state.queue):
            if request.song.spotify_id == spotify_id:
                # Found it - remove and return
                removed = self.state.queue.pop(i)
                # Mark as played so it can't be requested again
                self.state.played_song_ids.add(spotify_id)
                logger.info(f"Found request in queue: '{removed.song.title}' by {removed.requester}")
                return removed
        return None

    def clear_queue(self) -> int:
        """
        Clear all songs from queue.

        Returns:
            Number of songs removed
        """
        count = self.state.clear_queue()
        logger.info(f"Cleared queue ({count} songs removed)")
        return count

    # -------------------------------------------------------------------------
    # Voting
    # -------------------------------------------------------------------------

    def add_like(self, username: str) -> bool:
        """
        Add a like to the current song (works for both requests and regular playback).

        Args:
            username: Twitch username

        Returns:
            True if like was added, False if already liked
        """
        username = username.lower()
        current = self.state.current_request

        if current:
            # Use request's vote tracking
            added = current.add_like(username)
            if added:
                logger.debug(f"{username} liked '{current.song.title}'")
            return added
        else:
            # Use standalone vote tracking for non-request songs
            if username in self._standalone_likes:
                return False
            self._standalone_likes.add(username)
            logger.debug(f"{username} liked the current song")
            return True

    def add_skip_vote(self, username: str) -> Tuple[bool, bool]:
        """
        Add a skip vote to the current song (works for both requests and regular playback).

        Args:
            username: Twitch username

        Returns:
            Tuple of (vote_added, should_skip)
        """
        username = username.lower()
        current = self.state.current_request

        if current:
            # Use request's vote tracking
            added = current.add_skip_vote(username)
            if added:
                logger.debug(
                    f"{username} voted to skip '{current.song.title}' "
                    f"({current.skip_count}/{self.settings.skip_threshold})"
                )
            should_skip = current.should_skip(self.settings.skip_threshold)
            return added, should_skip
        else:
            # Use standalone vote tracking for non-request songs
            if username in self._standalone_skips:
                return False, False
            self._standalone_skips.add(username)
            skip_count = len(self._standalone_skips)
            logger.debug(f"{username} voted to skip ({skip_count}/{self.settings.skip_threshold})")
            should_skip = skip_count >= self.settings.skip_threshold
            return True, should_skip

    def get_vote_counts(self) -> Tuple[int, int]:
        """
        Get current song's vote counts (works for both requests and regular playback).

        Returns:
            Tuple of (likes, skips)
        """
        current = self.state.current_request
        if current:
            return current.like_count, current.skip_count
        else:
            return len(self._standalone_likes), len(self._standalone_skips)

    def reset_votes(self) -> None:
        """
        Reset likes and skip votes for the current song.
        Called when a new song starts playing.
        """
        current = self.state.current_request
        if current:
            current.reset_votes()
            logger.info(f"Reset votes for '{current.song.title}'")

        # Always reset standalone votes on song change
        self._standalone_likes.clear()
        self._standalone_skips.clear()
        logger.debug("Reset standalone votes")

    # -------------------------------------------------------------------------
    # Queue Info
    # -------------------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return self.state.is_empty

    @property
    def queue_length(self) -> int:
        """Get number of songs in queue."""
        return self.state.queue_length

    @property
    def has_current(self) -> bool:
        """Check if there's a current request."""
        return self.state.has_current

    @property
    def is_playing_requests(self) -> bool:
        """Check if playing from request queue."""
        return self.state.is_playing_requests

    def get_queue_snapshot(self) -> List[dict]:
        """Get simplified queue for display."""
        return self.state.get_queue_snapshot()

    def get_next_preview(self) -> Optional[dict]:
        """Get preview of next song."""
        return self.state.get_next_preview()

    def get_full_state(self) -> dict:
        """Get complete queue state."""
        return self.state.to_dict()

    # -------------------------------------------------------------------------
    # Context Management
    # -------------------------------------------------------------------------

    def set_previous_context(self, context_uri: Optional[str]) -> None:
        """Store the previous Spotify context for resume."""
        self.state.previous_context_uri = context_uri

    def get_previous_context(self) -> Optional[str]:
        """Get the stored previous context."""
        return self.state.previous_context_uri

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def reset_session(self) -> None:
        """Reset queue for a new session."""
        self.state.reset_session()
        self.cooldowns.clear()
        logger.info("Queue session reset")

    def get_session_start(self) -> datetime:
        """Get session start time."""
        return self.state.session_start
