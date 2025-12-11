"""
Application settings using Pydantic Settings.
Loads configuration from .env file with validation.
"""

from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -------------------------------------------------------------------------
    # Spotify Configuration
    # -------------------------------------------------------------------------
    spotify_client_id: str = Field(
        ...,
        description="Spotify application client ID"
    )
    spotify_client_secret: str = Field(
        ...,
        description="Spotify application client secret"
    )
    spotify_redirect_uri: str = Field(
        default="http://127.0.0.1:5174/auth/spotify/callback",
        description="Spotify OAuth redirect URI"
    )

    # -------------------------------------------------------------------------
    # Twitch Configuration
    # -------------------------------------------------------------------------
    twitch_client_id: str = Field(
        ...,
        description="Twitch application client ID"
    )
    twitch_client_secret: str = Field(
        ...,
        description="Twitch application client secret"
    )
    twitch_channel: str = Field(
        ...,
        description="Twitch channel name to join"
    )
    twitch_redirect_uri: str = Field(
        default="http://localhost:5174/auth/twitch/callback",
        description="Twitch OAuth redirect URI"
    )

    # -------------------------------------------------------------------------
    # Bot Account (Optional)
    # -------------------------------------------------------------------------
    use_bot_account: bool = Field(
        default=False,
        description="Whether to use a separate bot account for chat"
    )
    twitch_bot_username: Optional[str] = Field(
        default=None,
        description="Bot account username (if use_bot_account is True)"
    )
    twitch_bot_oauth_token: Optional[str] = Field(
        default=None,
        description="Bot account OAuth token (if use_bot_account is True)"
    )

    # -------------------------------------------------------------------------
    # Server Configuration
    # -------------------------------------------------------------------------
    server_host: str = Field(
        default="127.0.0.1",
        description="Server bind host"
    )
    server_port: int = Field(
        default=5174,
        description="Server bind port"
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode"
    )

    # -------------------------------------------------------------------------
    # Queue Settings
    # -------------------------------------------------------------------------
    max_queue_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum songs in queue"
    )
    cooldown_seconds: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="Cooldown between requests per user (seconds)"
    )
    skip_threshold: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Skip votes needed to auto-skip"
    )
    channel_points_cost: int = Field(
        default=500,
        ge=1,
        description="Channel points cost for song request"
    )

    # -------------------------------------------------------------------------
    # Blocklist (stored as comma-separated strings in .env)
    # -------------------------------------------------------------------------
    blocklist_artists: str = Field(
        default="",
        description="Blocked artist names (comma-separated in .env)"
    )
    blocklist_song_ids: str = Field(
        default="",
        description="Blocked Spotify track IDs (comma-separated in .env)"
    )

    @property
    def blocklist_artists_list(self) -> List[str]:
        """Get blocklist artists as a list."""
        if not self.blocklist_artists:
            return []
        return [a.strip() for a in self.blocklist_artists.split(",") if a.strip()]

    @property
    def blocklist_song_ids_list(self) -> List[str]:
        """Get blocklist song IDs as a list."""
        if not self.blocklist_song_ids:
            return []
        return [s.strip() for s in self.blocklist_song_ids.split(",") if s.strip()]

    @property
    def bot_username(self) -> str:
        """Get the username to use for chat (bot or broadcaster)."""
        if self.use_bot_account and self.twitch_bot_username:
            return self.twitch_bot_username
        return self.twitch_channel

    @property
    def bot_token(self) -> Optional[str]:
        """Get the OAuth token to use for chat."""
        if self.use_bot_account and self.twitch_bot_oauth_token:
            return self.twitch_bot_oauth_token
        return None  # Will use broadcaster token from OAuth flow


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached application settings.
    Uses lru_cache to only load settings once.
    """
    return Settings()


# Runtime settings that can be modified via dashboard
class RuntimeSettings:
    """
    Settings that can be modified at runtime via the dashboard.
    These override the .env defaults during the current session.
    """

    def __init__(self, base_settings: Settings):
        self.max_queue_size = base_settings.max_queue_size
        self.cooldown_seconds = base_settings.cooldown_seconds
        self.skip_threshold = base_settings.skip_threshold
        self.blocklist_artists = list(base_settings.blocklist_artists_list)
        self.blocklist_song_ids = list(base_settings.blocklist_song_ids_list)

    def update(
        self,
        max_queue_size: Optional[int] = None,
        cooldown_seconds: Optional[int] = None,
        skip_threshold: Optional[int] = None,
    ) -> dict:
        """Update runtime settings and return the new values."""
        if max_queue_size is not None:
            self.max_queue_size = max(1, min(100, max_queue_size))
        if cooldown_seconds is not None:
            self.cooldown_seconds = max(0, min(3600, cooldown_seconds))
        if skip_threshold is not None:
            self.skip_threshold = max(1, min(100, skip_threshold))

        return self.to_dict()

    def add_to_blocklist(self, item: str, is_artist: bool = True) -> bool:
        """Add item to blocklist. Returns True if added, False if already exists."""
        target = self.blocklist_artists if is_artist else self.blocklist_song_ids
        if item not in target:
            target.append(item)
            return True
        return False

    def remove_from_blocklist(self, item: str) -> bool:
        """Remove item from blocklist. Returns True if removed."""
        if item in self.blocklist_artists:
            self.blocklist_artists.remove(item)
            return True
        if item in self.blocklist_song_ids:
            self.blocklist_song_ids.remove(item)
            return True
        return False

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "max_queue_size": self.max_queue_size,
            "cooldown_seconds": self.cooldown_seconds,
            "skip_threshold": self.skip_threshold,
            "blocklist_artists": self.blocklist_artists,
            "blocklist_song_ids": self.blocklist_song_ids,
        }
