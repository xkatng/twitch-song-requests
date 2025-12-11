"""
Spotify API integration service.
Handles OAuth, playback control, search, and device management.
"""

import re
import logging
from typing import Optional, List
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from models.song import Song
from config.settings import Settings

logger = logging.getLogger(__name__)


class SpotifyService:
    """
    Wrapper for Spotify Web API using Spotipy.
    Handles authentication, playback, and search operations.
    """

    # Regex patterns for parsing Spotify links/URIs
    SPOTIFY_LINK_PATTERN = re.compile(
        r"https?://open\.spotify\.com/track/([a-zA-Z0-9]+)"
    )
    SPOTIFY_URI_PATTERN = re.compile(r"spotify:track:([a-zA-Z0-9]+)")

    # Patterns for detecting non-track links
    SPOTIFY_ALBUM_PATTERN = re.compile(
        r"https?://open\.spotify\.com/album/([a-zA-Z0-9]+)"
    )
    SPOTIFY_PLAYLIST_PATTERN = re.compile(
        r"https?://open\.spotify\.com/playlist/([a-zA-Z0-9]+)"
    )
    SPOTIFY_ARTIST_PATTERN = re.compile(
        r"https?://open\.spotify\.com/artist/([a-zA-Z0-9]+)"
    )

    # Required OAuth scopes
    SCOPES = " ".join([
        "user-modify-playback-state",
        "user-read-playback-state",
        "user-read-currently-playing",
    ])

    def __init__(self, settings: Settings):
        """
        Initialize Spotify service.

        Args:
            settings: Application settings containing Spotify credentials
        """
        self.settings = settings
        self.sp: Optional[spotipy.Spotify] = None
        self.previous_context: Optional[str] = None
        self.previous_track_uri: Optional[str] = None
        self._setup_client()

    def _setup_client(self) -> None:
        """Set up Spotipy client with OAuth."""
        auth_manager = SpotifyOAuth(
            client_id=self.settings.spotify_client_id,
            client_secret=self.settings.spotify_client_secret,
            redirect_uri=self.settings.spotify_redirect_uri,
            scope=self.SCOPES,
            cache_path=".spotify_cache",
            open_browser=True,
        )
        self.sp = spotipy.Spotify(auth_manager=auth_manager)
        logger.info("Spotify client initialized")

    def is_authenticated(self) -> bool:
        """Check if Spotify client is authenticated."""
        try:
            self.sp.current_user()
            return True
        except Exception:
            return False

    def get_auth_url(self) -> str:
        """Get the Spotify authorization URL for manual auth."""
        auth_manager = self.sp.auth_manager
        return auth_manager.get_authorize_url()

    # -------------------------------------------------------------------------
    # Track Parsing and Search
    # -------------------------------------------------------------------------

    def detect_link_type(self, input_str: str) -> Optional[str]:
        """
        Detect what type of Spotify link this is.

        Args:
            input_str: Spotify link or URI

        Returns:
            'track', 'album', 'playlist', 'artist', or None if not a Spotify link
        """
        input_str = input_str.strip()

        # Check for track links/URIs first
        if self.SPOTIFY_LINK_PATTERN.search(input_str) or self.SPOTIFY_URI_PATTERN.search(input_str):
            return 'track'

        # Check for album links
        if self.SPOTIFY_ALBUM_PATTERN.search(input_str):
            logger.info(f"Detected album link: {input_str[:50]}...")
            return 'album'

        # Check for playlist links
        if self.SPOTIFY_PLAYLIST_PATTERN.search(input_str):
            logger.info(f"Detected playlist link: {input_str[:50]}...")
            return 'playlist'

        # Check for artist links
        if self.SPOTIFY_ARTIST_PATTERN.search(input_str):
            logger.info(f"Detected artist link: {input_str[:50]}...")
            return 'artist'

        # Also check with simpler pattern (in case URL format varies)
        if 'spotify.com/album/' in input_str or 'spotify.com/album?' in input_str:
            logger.info(f"Detected album link (fallback): {input_str[:50]}...")
            return 'album'
        if 'spotify.com/playlist/' in input_str or 'spotify.com/playlist?' in input_str:
            logger.info(f"Detected playlist link (fallback): {input_str[:50]}...")
            return 'playlist'
        if 'spotify.com/artist/' in input_str or 'spotify.com/artist?' in input_str:
            logger.info(f"Detected artist link (fallback): {input_str[:50]}...")
            return 'artist'

        return None

    def parse_track_id(self, input_str: str) -> Optional[str]:
        """
        Extract Spotify track ID from a link or URI.

        Args:
            input_str: Spotify link, URI, or search query

        Returns:
            Track ID if found, None if input is a search query
        """
        input_str = input_str.strip()

        # Try URL pattern (https://open.spotify.com/track/...)
        match = self.SPOTIFY_LINK_PATTERN.search(input_str)
        if match:
            return match.group(1)

        # Try URI pattern (spotify:track:...)
        match = self.SPOTIFY_URI_PATTERN.search(input_str)
        if match:
            return match.group(1)

        return None

    def search_track(self, query: str, limit: int = 1) -> Optional[Song]:
        """
        Search Spotify for a track.

        Args:
            query: Search query (song name, artist, etc.)
            limit: Maximum results to return

        Returns:
            First matching Song or None
        """
        try:
            results = self.sp.search(q=query, type="track", limit=limit)
            tracks = results.get("tracks", {}).get("items", [])

            if not tracks:
                logger.info(f"No tracks found for query: {query}")
                return None

            return self._track_to_song(tracks[0])

        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            return None

    def get_track(self, track_id: str) -> Optional[Song]:
        """
        Get track details by Spotify ID.

        Args:
            track_id: Spotify track ID

        Returns:
            Song object or None if not found
        """
        try:
            track = self.sp.track(track_id)
            return self._track_to_song(track)
        except Exception as e:
            logger.error(f"Failed to get track {track_id}: {e}")
            return None

    def get_song_from_input(self, user_input: str) -> Optional[Song]:
        """
        Get a Song from user input (link or search query).

        Args:
            user_input: Spotify link/URI or search terms

        Returns:
            Song object or None if not found
        """
        # First, try to parse as a Spotify link/URI
        track_id = self.parse_track_id(user_input)

        if track_id:
            # It's a direct link - get the track
            return self.get_track(track_id)
        else:
            # It's a search query - search for it
            return self.search_track(user_input)

    def _track_to_song(self, track: dict) -> Song:
        """Convert Spotify API track object to Song model."""
        # Get album art (first/largest image)
        album_art_url = None
        if track.get("album", {}).get("images"):
            album_art_url = track["album"]["images"][0]["url"]

        # Combine artist names
        artist = ", ".join(a["name"] for a in track.get("artists", []))

        return Song(
            spotify_id=track["id"],
            title=track["name"],
            artist=artist,
            album=track.get("album", {}).get("name", ""),
            duration_ms=track.get("duration_ms", 0),
            album_art_url=album_art_url,
        )

    # -------------------------------------------------------------------------
    # Device Management
    # -------------------------------------------------------------------------

    def get_devices(self) -> List[dict]:
        """Get list of available Spotify devices."""
        try:
            result = self.sp.devices()
            return result.get("devices", [])
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return []

    def get_active_device(self) -> Optional[dict]:
        """
        Get the currently active device, preferring Desktop.

        Returns:
            Device dict or None if no devices available
        """
        devices = self.get_devices()

        if not devices:
            return None

        # First, look for an active device
        for device in devices:
            if device.get("is_active"):
                return device

        # If no active device, prefer Computer type
        for device in devices:
            if device.get("type") == "Computer":
                return device

        # Return first available device
        return devices[0] if devices else None

    def transfer_playback(self, device_id: str, start_playing: bool = False) -> bool:
        """
        Transfer playback to a specific device.

        Args:
            device_id: Target device ID
            start_playing: Whether to start playback after transfer

        Returns:
            True if successful
        """
        try:
            self.sp.transfer_playback(device_id=device_id, force_play=start_playing)
            logger.info(f"Transferred playback to device: {device_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to transfer playback: {e}")
            return False

    def ensure_active_device(self) -> Optional[str]:
        """
        Ensure there's an active device for playback.

        Returns:
            Active device ID or None if no devices available
        """
        device = self.get_active_device()

        if not device:
            logger.warning("No Spotify devices found")
            return None

        if not device.get("is_active"):
            # Transfer to this device
            self.transfer_playback(device["id"])

        return device["id"]

    # -------------------------------------------------------------------------
    # Playback Control
    # -------------------------------------------------------------------------

    def store_current_context(self) -> None:
        """Store the current playback context for later resume."""
        try:
            playback = self.sp.current_playback()
            if playback:
                # Store playlist/album context
                if playback.get("context"):
                    self.previous_context = playback["context"]["uri"]
                    logger.info(f"Stored context: {self.previous_context}")

                # Store current track position
                if playback.get("item"):
                    self.previous_track_uri = playback["item"]["uri"]

        except Exception as e:
            logger.error(f"Failed to store playback context: {e}")

    def play_track(self, song: Song, device_id: Optional[str] = None) -> bool:
        """
        Play a specific track.

        Args:
            song: Song to play
            device_id: Optional target device ID

        Returns:
            True if playback started successfully
        """
        try:
            # Ensure we have an active device
            if not device_id:
                device_id = self.ensure_active_device()

            if not device_id:
                logger.error("No active device for playback")
                return False

            self.sp.start_playback(
                device_id=device_id,
                uris=[song.spotify_uri]
            )
            logger.info(f"Playing: {song.title} by {song.artist}")
            return True

        except Exception as e:
            logger.error(f"Failed to play track: {e}")
            return False

    def resume_previous_context(self) -> bool:
        """
        Resume the previously playing playlist/album.

        Returns:
            True if resumed successfully
        """
        if not self.previous_context:
            logger.info("No previous context to resume")
            return False

        try:
            device_id = self.ensure_active_device()
            if not device_id:
                return False

            self.sp.start_playback(
                device_id=device_id,
                context_uri=self.previous_context
            )
            logger.info(f"Resumed context: {self.previous_context}")
            return True

        except Exception as e:
            logger.error(f"Failed to resume context: {e}")
            return False

    def add_to_queue(self, song: Song) -> bool:
        """
        Add a song to Spotify's playback queue.

        Args:
            song: Song to add to queue

        Returns:
            True if added successfully
        """
        try:
            device_id = self.ensure_active_device()
            if not device_id:
                logger.error("No active device to add to queue")
                return False

            self.sp.add_to_queue(uri=song.spotify_uri, device_id=device_id)
            logger.info(f"Added to Spotify queue: {song.title} by {song.artist}")
            return True
        except Exception as e:
            logger.error(f"Failed to add to queue: {e}")
            return False

    def skip_track(self) -> bool:
        """Skip to the next track."""
        try:
            self.sp.next_track()
            logger.info("Skipped to next track")
            return True
        except Exception as e:
            logger.error(f"Failed to skip track: {e}")
            return False

    def pause(self) -> bool:
        """Pause playback."""
        try:
            self.sp.pause_playback()
            return True
        except Exception as e:
            logger.error(f"Failed to pause: {e}")
            return False

    def resume(self) -> bool:
        """Resume playback."""
        try:
            self.sp.start_playback()
            return True
        except Exception as e:
            logger.error(f"Failed to resume: {e}")
            return False

    # -------------------------------------------------------------------------
    # Playback State
    # -------------------------------------------------------------------------

    def get_current_playback(self) -> Optional[dict]:
        """
        Get current playback state.

        Returns:
            Playback state dict or None if nothing playing
        """
        try:
            return self.sp.current_playback()
        except Exception as e:
            logger.error(f"Failed to get playback state: {e}")
            return None

    def get_current_track(self) -> Optional[dict]:
        """
        Get currently playing track.

        Returns:
            Track dict or None
        """
        try:
            result = self.sp.current_user_playing_track()
            if result and result.get("item"):
                return result["item"]
            return None
        except Exception as e:
            logger.error(f"Failed to get current track: {e}")
            return None

    def get_playback_progress(self) -> tuple[int, int, bool]:
        """
        Get current playback progress.

        Returns:
            Tuple of (progress_ms, duration_ms, is_playing)
        """
        try:
            playback = self.sp.current_playback()
            if playback and playback.get("item"):
                return (
                    playback.get("progress_ms", 0),
                    playback["item"].get("duration_ms", 0),
                    playback.get("is_playing", False),
                )
            return 0, 0, False
        except Exception as e:
            logger.error(f"Failed to get progress: {e}")
            return 0, 0, False

    def is_track_finished(self, threshold_ms: int = 2000) -> bool:
        """
        Check if current track has finished (within threshold).

        Args:
            threshold_ms: Milliseconds from end to consider "finished"

        Returns:
            True if track is at or near the end
        """
        progress, duration, is_playing = self.get_playback_progress()

        if duration == 0:
            return False

        remaining = duration - progress
        return remaining <= threshold_ms and not is_playing

    def get_next_in_queue(self) -> Optional[dict]:
        """
        Get the next song in Spotify's playback queue.

        Returns:
            Dict with title, artist, album_art_url or None if queue is empty
        """
        try:
            queue = self.sp.queue()
            if queue and queue.get("queue"):
                next_track = queue["queue"][0]

                # Get album art
                album_art_url = None
                if next_track.get("album", {}).get("images"):
                    album_art_url = next_track["album"]["images"][0]["url"]

                # Combine artist names
                artist = ", ".join(a["name"] for a in next_track.get("artists", []))

                return {
                    "title": next_track.get("name", "Unknown"),
                    "artist": artist,
                    "album_art_url": album_art_url,
                    "requester": None,  # Not a request, from Spotify queue
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get queue: {e}")
            return None
