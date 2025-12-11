"""
Twitch OAuth authentication handler.
Manages token acquisition, storage, and refresh.
"""

import json
import logging
import secrets
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import httpx

logger = logging.getLogger(__name__)

# Twitch OAuth endpoints
TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"

# Required scopes for the bot
# channel:read:redemptions is REQUIRED for Channel Points EventSub to work
TWITCH_SCOPES = [
    "chat:read",
    "chat:edit",
    "channel:read:redemptions",
    "channel:manage:redemptions",
    "user:read:chat",
    "user:write:chat",
    "user:bot",
    "channel:bot",
]

# For checking if token has required scopes
REQUIRED_SCOPES_FOR_CHANNEL_POINTS = ["channel:read:redemptions"]

# Token cache file
TOKEN_CACHE_FILE = ".twitch_cache"


class TwitchAuth:
    """Handles Twitch OAuth authentication."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        """
        Initialize Twitch auth handler.

        Args:
            client_id: Twitch application client ID
            client_secret: Twitch application client secret
            redirect_uri: OAuth redirect URI
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._user_id: Optional[str] = None
        self._username: Optional[str] = None
        self._state: Optional[str] = None

        # Try to load cached token
        self._load_cached_token()

    def _load_cached_token(self) -> bool:
        """Load token from cache file."""
        cache_path = Path(TOKEN_CACHE_FILE)
        if not cache_path.exists():
            return False

        try:
            with open(cache_path, "r") as f:
                data = json.load(f)

            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._user_id = data.get("user_id")
            self._username = data.get("username")

            expires_at = data.get("expires_at")
            if expires_at:
                self._expires_at = datetime.fromisoformat(expires_at)

            logger.info(f"Loaded cached Twitch token for {self._username}")
            return True

        except Exception as e:
            logger.error(f"Failed to load cached token: {e}")
            return False

    def _save_token(self) -> None:
        """Save token to cache file."""
        try:
            data = {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "user_id": self._user_id,
                "username": self._username,
                "expires_at": self._expires_at.isoformat() if self._expires_at else None,
            }
            with open(TOKEN_CACHE_FILE, "w") as f:
                json.dump(data, f)
            logger.info("Saved Twitch token to cache")
        except Exception as e:
            logger.error(f"Failed to save token: {e}")

    def is_authenticated(self) -> bool:
        """Check if we have a valid token."""
        if not self._access_token:
            return False

        # Check if token is expired
        if self._expires_at and datetime.now() >= self._expires_at:
            # Try to refresh
            if self._refresh_token:
                return self.refresh_access_token()
            return False

        return True

    async def validate_token_scopes(self) -> tuple[bool, list]:
        """
        Validate the token has required scopes for Channel Points.

        Returns:
            Tuple of (has_required_scopes, list_of_scopes)
        """
        if not self._access_token:
            return False, []

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    TWITCH_VALIDATE_URL,
                    headers={"Authorization": f"OAuth {self._access_token}"},
                )

                if response.status_code != 200:
                    logger.warning(f"Token validation failed: {response.status_code}")
                    return False, []

                data = response.json()
                scopes = data.get("scopes", [])

                logger.info(f"Token scopes: {scopes}")

                # Check for required scopes
                has_required = all(scope in scopes for scope in REQUIRED_SCOPES_FOR_CHANNEL_POINTS)

                if not has_required:
                    logger.warning(f"Token missing required scopes for Channel Points!")
                    logger.warning(f"Required: {REQUIRED_SCOPES_FOR_CHANNEL_POINTS}")
                    logger.warning(f"Has: {scopes}")
                    logger.warning("Delete .twitch_cache and restart to re-authenticate with correct scopes")

                return has_required, scopes

        except Exception as e:
            logger.error(f"Failed to validate token: {e}")
            return False, []

    def get_auth_url(self) -> str:
        """
        Get the Twitch authorization URL.

        Returns:
            URL to redirect user to for authorization
        """
        self._state = secrets.token_urlsafe(32)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(TWITCH_SCOPES),
            "state": self._state,
        }

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{TWITCH_AUTH_URL}?{query}"

    async def handle_callback(self, code: str, state: str) -> bool:
        """
        Handle OAuth callback with authorization code.

        Args:
            code: Authorization code from callback
            state: State parameter for verification

        Returns:
            True if authentication successful
        """
        # Verify state
        if state != self._state:
            logger.error(f"OAuth state mismatch: expected {self._state}, got {state}")
            return False

        # Exchange code for token
        try:
            logger.info(f"Exchanging code for token with redirect_uri: {self.redirect_uri}")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    TWITCH_TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": self.redirect_uri,
                    },
                )

                if response.status_code != 200:
                    logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                    return False

                data = response.json()

            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token")

            expires_in = data.get("expires_in", 3600)
            self._expires_at = datetime.now() + timedelta(seconds=expires_in)

            # Get user info
            await self._fetch_user_info()

            # Save to cache
            self._save_token()

            logger.info(f"Twitch authentication successful for {self._username}")
            return True

        except Exception as e:
            logger.error(f"Failed to exchange code for token: {e}")
            return False

    async def _fetch_user_info(self) -> None:
        """Fetch user info from Twitch API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.twitch.tv/helix/users",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Client-Id": self.client_id,
                    },
                )
                response.raise_for_status()
                data = response.json()

            if data.get("data"):
                user = data["data"][0]
                self._user_id = user["id"]
                self._username = user["login"]

        except Exception as e:
            logger.error(f"Failed to fetch user info: {e}")

    def refresh_access_token(self) -> bool:
        """
        Refresh the access token using refresh token.

        Returns:
            True if refresh successful
        """
        if not self._refresh_token:
            return False

        try:
            # Use sync request for simplicity
            import requests
            response = requests.post(
                TWITCH_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()

            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", self._refresh_token)

            expires_in = data.get("expires_in", 3600)
            self._expires_at = datetime.now() + timedelta(seconds=expires_in)

            self._save_token()
            logger.info("Twitch token refreshed")
            return True

        except Exception as e:
            logger.error(f"Failed to refresh token: {e}")
            return False

    @property
    def access_token(self) -> Optional[str]:
        """Get the current access token."""
        return self._access_token

    @property
    def refresh_token(self) -> Optional[str]:
        """Get the current refresh token."""
        return self._refresh_token

    @property
    def user_id(self) -> Optional[str]:
        """Get the authenticated user's ID."""
        return self._user_id

    @property
    def username(self) -> Optional[str]:
        """Get the authenticated user's username."""
        return self._username
