"""
Twitch integration service.
Handles EventSub for chat messages, Channel Points, and commands.

TwitchIO 3.x uses EventSub instead of IRC for chat.
"""

import asyncio
import logging
import time
from typing import Optional, Callable, Awaitable, Any
from twitchio.ext import commands
from twitchio import eventsub
import twitchio
import httpx

from config.settings import Settings

logger = logging.getLogger(__name__)


def _added_message(username: str, result) -> str:
    """
    Build the 'song added' chat reply. The request callback returns a dict
    with queue position and ETA; fall back to a plain message otherwise.
    """
    if isinstance(result, dict) and result.get("position"):
        msg = f"@{username} your song has been added! Position #{result['position']}"
        if result.get("eta_text"):
            msg += f" — playing in {result['eta_text']}"
        return msg
    return f"@{username} your song has been added to the queue!"


class TwitchService(commands.Bot):
    """
    Twitch bot for chat commands and Channel Point redemptions.
    Uses TwitchIO 3.x with EventSub for chat.
    """

    def __init__(
        self,
        settings: Settings,
        on_song_request: Optional[Callable[[str, str], Awaitable[Any]]] = None,
        on_like: Optional[Callable[[str], Awaitable[Any]]] = None,
        on_skip_vote: Optional[Callable[[str], Awaitable[Any]]] = None,
        on_force_skip: Optional[Callable[[], Awaitable[Any]]] = None,
        on_clear_queue: Optional[Callable[[], Awaitable[Any]]] = None,
        on_queue_request: Optional[Callable[[], Awaitable[list]]] = None,
        on_current_song_request: Optional[Callable[[], Awaitable[dict]]] = None,
        on_poll_end: Optional[Callable[[Any], Awaitable[Any]]] = None,
        on_poll_progress: Optional[Callable[[Any], Awaitable[Any]]] = None,
        on_music_rats: Optional[Callable[[], Awaitable[str]]] = None,
        on_cancel_request: Optional[Callable[[str], Awaitable[Any]]] = None,
        oauth_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """
        Initialize Twitch service.

        Args:
            settings: Application settings
            on_song_request: Callback for song requests (username, input)
            on_like: Callback for like votes (username)
            on_skip_vote: Callback for skip votes (username)
            on_force_skip: Callback for force skip (mods only)
            on_clear_queue: Callback for clearing queue (mods only)
            on_queue_request: Callback for queue info request
            on_current_song_request: Callback for current song info
            oauth_token: OAuth access token (from OAuth flow)
            refresh_token: OAuth refresh token (from OAuth flow)
            user_id: Twitch user ID (from OAuth flow)
        """
        self.settings = settings
        self._access_token: Optional[str] = oauth_token
        self._refresh_token: Optional[str] = refresh_token
        self._user_id: Optional[str] = user_id
        self._reward_id: Optional[str] = None

        # Event callbacks
        self.on_song_request_callback = on_song_request
        self.on_like_callback = on_like
        self.on_skip_vote_callback = on_skip_vote
        self.on_force_skip_callback = on_force_skip
        self.on_clear_queue_callback = on_clear_queue
        self.on_queue_request_callback = on_queue_request
        self.on_current_song_request_callback = on_current_song_request
        self.on_poll_end_callback = on_poll_end
        self.on_poll_progress_callback = on_poll_progress
        self.on_music_rats_callback = on_music_rats
        self.on_cancel_request_callback = on_cancel_request

        # Track last song
        self._last_song: Optional[dict] = None
        self._current_song: Optional[dict] = None

        # Get token for initialization
        if oauth_token:
            initial_token = oauth_token.replace("oauth:", "")
            logger.info(f"Using OAuth token for Twitch bot (user_id: {user_id})")
        elif settings.use_bot_account and settings.twitch_bot_oauth_token:
            initial_token = settings.twitch_bot_oauth_token.replace("oauth:", "")
        elif settings.twitch_bot_oauth_token:
            initial_token = settings.twitch_bot_oauth_token.replace("oauth:", "")
        else:
            initial_token = "placeholder"
            logger.warning("No Twitch OAuth token configured - bot will not connect")

        # Initialize TwitchIO 3.x bot
        # bot_id and owner_id are both the broadcaster's numeric user ID
        super().__init__(
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret,
            bot_id=user_id or "0",
            owner_id=user_id or "0",
            prefix="!",
            token=initial_token,
        )

        self._nick = settings.twitch_channel

    async def setup_hook(self) -> None:
        """
        Called when the bot is ready to set up EventSub subscriptions.
        This is the TwitchIO 3.x way to subscribe to chat messages.
        """
        logger.info("Setting up EventSub subscriptions...")

        try:
            # Add the user token to TwitchIO's token manager
            # This is required for EventSub WebSocket which needs a User Access Token
            if self._access_token:
                logger.info("Adding user token to TwitchIO...")
                await self.add_token(self._access_token, self._refresh_token)
                logger.info("User token added successfully")

            # Subscribe to chat messages via EventSub WebSocket
            chat_sub = eventsub.ChatMessageSubscription(
                broadcaster_user_id=self._user_id,
                user_id=self._user_id,  # The bot user (same as broadcaster in this case)
            )
            await self.subscribe_websocket(payload=chat_sub)
            logger.info("Subscribed to chat messages via EventSub")

            # Subscribe to Channel Point redemptions
            # Try different subscription methods
            try:
                redemption_sub = eventsub.ChannelPointsRedeemAddSubscription(
                    broadcaster_user_id=self._user_id,
                )
                await self.subscribe_websocket(payload=redemption_sub)
                logger.info(f"Subscribed to channel.channel_points_custom_reward_redemption.add for broadcaster {self._user_id}")
            except Exception as e:
                logger.error(f"Failed to subscribe to Channel Points: {e}")

            # Subscribe to poll events (for the skip poll feature)
            try:
                poll_end_sub = eventsub.ChannelPollEndSubscription(
                    broadcaster_user_id=self._user_id,
                )
                await self.subscribe_websocket(payload=poll_end_sub)
                # Progress events power the landslide early-skip
                poll_progress_sub = eventsub.ChannelPollProgressSubscription(
                    broadcaster_user_id=self._user_id,
                )
                await self.subscribe_websocket(payload=poll_progress_sub)
                logger.info("Subscribed to channel.poll.end and channel.poll.progress")
            except Exception as e:
                logger.error(
                    f"Failed to subscribe to poll events (skip polls disabled): {e}. "
                    "If you re-used an old login, delete .twitch_cache and restart "
                    "to re-authenticate with poll permissions."
                )

            logger.info(f"Listening for song request rewards (case-insensitive): songredeem, song request, etc.")

            # Add the chat component for handling messages and commands
            await self.add_component(ChatComponent(self))
            logger.info("Added chat component")

        except Exception as e:
            logger.error(f"Failed to setup EventSub: {e}")

    async def event_ready(self) -> None:
        """Called when bot is ready and connected."""
        logger.info(f"Twitch bot connected as {self._nick}")
        logger.info(f"Bot user ID: {self._user_id}")
        logger.info("Ready to receive chat messages via EventSub")

    async def set_access_token(self, token: str, user_id: str) -> None:
        """
        Set the OAuth access token after authentication.

        Args:
            token: OAuth access token
            user_id: Broadcaster's user ID
        """
        self._access_token = token
        self._user_id = user_id

    def update_current_song(self, song: dict) -> None:
        """
        Update the current song and track the last song.
        Call this when the song changes.

        Args:
            song: Dict with 'title' and 'artist' keys
        """
        if song and song.get("title"):
            # Only update last song if we had a different song before
            if self._current_song and self._current_song.get("title") != song.get("title"):
                self._last_song = self._current_song
            self._current_song = song

    def get_last_song(self) -> Optional[dict]:
        """Get the last played song."""
        return self._last_song

    # -------------------------------------------------------------------------
    # Channel Points Integration
    # -------------------------------------------------------------------------

    async def setup_channel_points(self) -> Optional[str]:
        """
        Set up Channel Point reward for song requests.
        Creates the reward if it doesn't exist.

        Returns:
            Reward ID if successful, None otherwise
        """
        if not self._access_token or not self._user_id:
            logger.error("Cannot setup channel points: not authenticated")
            return None

        # Check for existing reward
        existing_reward = await self._find_existing_reward()
        if existing_reward:
            self._reward_id = existing_reward
            logger.info(f"Using existing Song Request reward: {existing_reward}")
            return existing_reward

        # Create new reward
        reward_id = await self._create_reward()
        if reward_id:
            self._reward_id = reward_id
            logger.info(f"Created Song Request reward: {reward_id}")
        return reward_id

    async def _find_existing_reward(self) -> Optional[str]:
        """Find existing Song Request reward."""
        url = "https://api.twitch.tv/helix/channel_points/custom_rewards"
        params = {
            "broadcaster_id": self._user_id,
            "only_manageable_rewards": "true",
        }
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Client-Id": self.settings.twitch_client_id,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()

                for reward in data.get("data", []):
                    if reward.get("title") == "Song Request":
                        return reward["id"]

        except Exception as e:
            logger.error(f"Error finding existing reward: {e}")

        return None

    async def _create_reward(self) -> Optional[str]:
        """Create the Song Request channel point reward."""
        url = f"https://api.twitch.tv/helix/channel_points/custom_rewards?broadcaster_id={self._user_id}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Client-Id": self.settings.twitch_client_id,
            "Content-Type": "application/json",
        }
        payload = {
            "title": "Song Request",
            "cost": self.settings.channel_points_cost,
            "is_enabled": True,
            "is_user_input_required": True,
            "prompt": "Enter a Spotify link or song name to request",
            "should_redemptions_skip_request_queue": False,
            "is_global_cooldown_enabled": True,
            "global_cooldown_seconds": 60,
            "background_color": "#1DB954",  # Spotify green
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                if data.get("data"):
                    return data["data"][0]["id"]

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                logger.warning("Reward may already exist with same name")
            else:
                logger.error(f"Error creating reward: {e}")
        except Exception as e:
            logger.error(f"Error creating reward: {e}")

        return None

    async def update_redemption_status(
        self,
        redemption_id: str,
        reward_id: str,
        fulfilled: bool = True
    ) -> bool:
        """
        Update a redemption's status (fulfill or cancel).

        Args:
            redemption_id: The redemption ID
            reward_id: The reward ID
            fulfilled: True to fulfill, False to cancel (refund)

        Returns:
            True if successful
        """
        if not self._access_token or not self._user_id:
            return False

        url = "https://api.twitch.tv/helix/channel_points/custom_rewards/redemptions"
        params = {
            "broadcaster_id": self._user_id,
            "reward_id": reward_id,
            "id": redemption_id,
        }
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Client-Id": self.settings.twitch_client_id,
            "Content-Type": "application/json",
        }
        payload = {
            "status": "FULFILLED" if fulfilled else "CANCELED"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    url, params=params, headers=headers, json=payload
                )
                response.raise_for_status()
                return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                # Twitch only allows the app that CREATED a reward to update
                # its redemptions. Rewards made manually in the Twitch
                # dashboard can never be fulfilled/refunded via the API.
                logger.warning(
                    "Cannot update redemption status (403): this reward was not "
                    "created by this app, so Twitch won't allow refunds for it. "
                    "To enable automatic refunds, delete the reward on Twitch and "
                    "let the app create its own reward."
                )
            else:
                logger.error(f"Error updating redemption: {e}")
            return False
        except Exception as e:
            logger.error(f"Error updating redemption: {e}")
            return False

    # -------------------------------------------------------------------------
    # Polls (skip poll feature)
    # -------------------------------------------------------------------------

    async def create_poll(self, title: str, choices: list, duration_seconds: int) -> Optional[str]:
        """
        Create a Twitch poll on the channel.

        Args:
            title: Poll question (max 60 chars, truncated if longer)
            choices: List of 2-5 choice titles (max 25 chars each)
            duration_seconds: Poll duration (15-1800)

        Returns:
            Poll ID if created, None otherwise
        """
        if not self._access_token or not self._user_id:
            return None

        url = "https://api.twitch.tv/helix/polls"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Client-Id": self.settings.twitch_client_id,
            "Content-Type": "application/json",
        }
        payload = {
            "broadcaster_id": self._user_id,
            "title": title[:60],
            "choices": [{"title": c[:25]} for c in choices],
            "duration": max(15, min(1800, duration_seconds)),
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                if data.get("data"):
                    poll_id = data["data"][0]["id"]
                    logger.info(f"Created poll '{payload['title']}' ({poll_id})")
                    return poll_id
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.warning(
                    "Cannot create poll (403): polls require Twitch Affiliate/Partner "
                    "and the channel:manage:polls permission. If you recently updated, "
                    "delete .twitch_cache and restart to re-authenticate."
                )
            elif e.response.status_code == 400 and "poll" in e.response.text.lower():
                logger.warning(f"Cannot create poll: another poll may already be active. ({e.response.text[:200]})")
            else:
                logger.error(f"Error creating poll: {e} - {e.response.text[:200]}")
        except Exception as e:
            logger.error(f"Error creating poll: {e}")

        return None

    async def end_poll(self, poll_id: str, archive: bool = False) -> bool:
        """
        End an active poll early.

        Args:
            poll_id: The poll to end
            archive: If True, hide the results (ARCHIVED); otherwise show them (TERMINATED)

        Returns:
            True if the poll was ended
        """
        if not self._access_token or not self._user_id:
            return False

        url = "https://api.twitch.tv/helix/polls"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Client-Id": self.settings.twitch_client_id,
            "Content-Type": "application/json",
        }
        payload = {
            "broadcaster_id": self._user_id,
            "id": poll_id,
            "status": "ARCHIVED" if archive else "TERMINATED",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(url, headers=headers, json=payload)
                response.raise_for_status()
                logger.info(f"Ended poll {poll_id}")
                return True
        except Exception as e:
            logger.error(f"Error ending poll: {e}")
            return False

    # -------------------------------------------------------------------------
    # Chat Messaging
    # -------------------------------------------------------------------------

    async def send_message(self, message: str) -> None:
        """
        Send a message to the channel.

        Args:
            message: Message text to send
        """
        try:
            # In TwitchIO 3.x, we need to use the API to send messages
            url = "https://api.twitch.tv/helix/chat/messages"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Client-Id": self.settings.twitch_client_id,
                "Content-Type": "application/json",
            }
            payload = {
                "broadcaster_id": self._user_id,
                "sender_id": self._user_id,
                "message": message,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                logger.debug(f"Sent message: {message}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def announce_song(self, title: str, artist: str, requester: str) -> None:
        """Announce a song is now playing (if enabled)."""
        # Per requirements, overlay only - no chat announcements
        pass

    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------

    async def connect_and_run(self) -> None:
        """Connect to Twitch and start the event loop."""
        await self.start()

    async def disconnect(self) -> None:
        """Disconnect from Twitch."""
        await self.close()
        logger.info("Twitch bot disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if bot is connected."""
        return self.connected


class ChatComponent(commands.Component):
    """
    Component that handles chat messages and commands.
    TwitchIO 3.x uses Components with listeners for EventSub events.
    """

    # Names of Channel Point rewards to listen for (case-insensitive comparison)
    SONG_REQUEST_REWARD_NAMES = [
        "songredeem",
        "song request",
        "songrequest",
        "song",
        "sr",
    ]

    # Seconds between !musicrats uses (anyone can call it - keep chat clean)
    MUSIC_RATS_COOLDOWN = 60

    def __init__(self, bot: TwitchService) -> None:
        self.bot = bot
        self._last_music_rats = 0.0
        logger.info(f"ChatComponent initialized - listening for rewards: {self.SONG_REQUEST_REWARD_NAMES}")

    @commands.Component.listener("raw_event")
    async def on_raw_event(self, event_name: str, data: dict) -> None:
        """Log ALL raw EventSub events for debugging."""
        logger.info(f"[RAW EVENT] {event_name}: {str(data)[:200]}...")

    @commands.Component.listener()
    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        """Handle incoming chat messages via EventSub."""
        # Log the message
        chatter_name = payload.chatter.name if payload.chatter else "unknown"
        logger.info(f"Chat [{payload.broadcaster.name}] {chatter_name}: {payload.text}")

        # Check if it's a command and process it manually
        text = payload.text.strip()
        if text.startswith("!"):
            await self._handle_command(payload, text)

    @commands.Component.listener()
    async def event_custom_redemption_add(self, payload: twitchio.ChannelPointsRedemptionAdd) -> None:
        """
        Handle Channel Point redemptions.

        TwitchIO 3.1 dispatches channel.channel_points_custom_reward_redemption.add
        as "custom_redemption_add", so the listener must use this exact name.
        """
        reward_title = payload.reward.title if payload.reward else "Unknown"
        user_name = payload.user.name if payload.user else "Unknown"
        user_input = payload.user_input or ""

        logger.info(f"")
        logger.info(f"╔══════════════════════════════════════════════════════════╗")
        logger.info(f"║  CHANNEL POINTS REDEMPTION RECEIVED                      ║")
        logger.info(f"╠══════════════════════════════════════════════════════════╣")
        logger.info(f"║  Reward: '{reward_title}'")
        logger.info(f"║  User: {user_name}")
        logger.info(f"║  Input: '{user_input}'")
        logger.info(f"╚══════════════════════════════════════════════════════════╝")

        # Check if this is a song request reward (case-insensitive)
        reward_lower = reward_title.lower().strip()
        is_song_request = any(name in reward_lower or reward_lower in name for name in self.SONG_REQUEST_REWARD_NAMES)

        # Also accept any reward with user input that looks like a Spotify link
        if not is_song_request and user_input:
            if "spotify.com" in user_input or "spotify:track:" in user_input:
                logger.info(f"Detected Spotify link in user input - treating as song request")
                is_song_request = True

        if is_song_request:
            logger.info(f"Song request from {user_name}: {user_input}")

            redemption_id = getattr(payload, "id", None)
            reward_id = payload.reward.id if payload.reward else None

            async def resolve_redemption(fulfilled: bool) -> bool:
                """Fulfill or cancel (refund) the redemption. Returns True on success."""
                if redemption_id and reward_id:
                    return await self.bot.update_redemption_status(
                        redemption_id, reward_id, fulfilled=fulfilled
                    )
                return False

            if not user_input:
                # Refund quietly - the "please include a song name" reply is
                # reserved for !request/!sr without arguments
                refunded = await resolve_redemption(False)
                logger.warning(
                    f"Empty redemption from {user_name} - "
                    f"{'refunded' if refunded else 'refund failed'}"
                )
                return

            if not self.bot.on_song_request_callback:
                return

            try:
                result = await self.bot.on_song_request_callback(user_name, user_input)
                if result:
                    await resolve_redemption(True)
                    await self.bot.send_message(_added_message(user_name, result))
                    logger.info(f"Song request successful for {user_name}")
                else:
                    refunded = await resolve_redemption(False)
                    msg = f"@{user_name} couldn't find that song. Try a Spotify link or different search."
                    if refunded:
                        msg += " Your points have been refunded."
                    await self.bot.send_message(msg)
                    logger.warning(f"Song request failed for {user_name}: song not found")
            except Exception as e:
                refunded = await resolve_redemption(False)
                # QueueError subclasses carry a viewer-friendly reason
                # (cooldown, queue full, duplicate, blocked, wrong link type)
                user_message = getattr(e, "user_message", None)
                if user_message:
                    msg = f"@{user_name} {user_message}"
                    logger.warning(f"Song request rejected for {user_name}: {e}")
                else:
                    msg = f"@{user_name} there was an error processing your request."
                    logger.error(f"Error processing song request: {e}")
                if refunded:
                    msg += " Your points have been refunded."
                await self.bot.send_message(msg)

    @commands.Component.listener()
    async def event_poll_end(self, payload: twitchio.ChannelPollEnd) -> None:
        """
        Handle poll end events (skip poll results).

        TwitchIO 3.1 dispatches channel.poll.end as "poll_end".
        """
        logger.info(f"Poll ended: '{payload.title}' status={payload.status}")
        if self.bot.on_poll_end_callback:
            try:
                await self.bot.on_poll_end_callback(payload)
            except Exception as e:
                logger.error(f"Error handling poll end: {e}")

    @commands.Component.listener()
    async def event_poll_progress(self, payload: twitchio.ChannelPollProgress) -> None:
        """
        Handle live poll vote updates (dispatched as "poll_progress").
        Used to end the skip poll early on a landslide.
        """
        if self.bot.on_poll_progress_callback:
            try:
                await self.bot.on_poll_progress_callback(payload)
            except Exception as e:
                logger.error(f"Error handling poll progress: {e}")

    async def _handle_command(self, payload: twitchio.ChatMessage, text: str) -> None:
        """Manually handle commands from chat messages."""
        parts = text[1:].split(maxsplit=1)  # Remove ! and split
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        chatter_name = payload.chatter.name if payload.chatter else "unknown"

        logger.info(f"Processing command: {cmd} from {chatter_name}")

        if cmd == "like":
            await self._cmd_like(payload, chatter_name)
        elif cmd == "pass":
            await self._cmd_pass(payload, chatter_name)
        elif cmd in ("queue", "q"):
            await self._cmd_queue(payload)
        elif cmd in ("forceskip", "fs", "skip"):
            await self._cmd_forceskip(payload, chatter_name)
        elif cmd in ("clearqueue", "cq"):
            await self._cmd_clearqueue(payload, chatter_name)
        elif cmd in ("song", "np", "nowplaying"):
            await self._cmd_song(payload)
        elif cmd in ("lastsong", "last", "previous"):
            await self._cmd_lastsong(payload)
        elif cmd in ("request", "sr"):
            await self._cmd_request(payload, chatter_name, args)
        elif cmd in ("musicrats", "musicrat", "ratmusic"):
            await self._cmd_music_rats(payload)
        elif cmd == "cancel":
            await self._cmd_cancel(payload, chatter_name)

    async def _cmd_like(self, payload: twitchio.ChatMessage, username: str) -> None:
        """
        Vote to like the current song.

        Votes are counted silently (the overlay shows totals)
        to keep chat clean and avoid singling out voters.
        """
        if self.bot.on_like_callback:
            try:
                result = await self.bot.on_like_callback(username)
                if result:
                    logger.info(f"Like registered for {username}")
            except Exception as e:
                logger.error(f"Like command error: {e}")

    async def _cmd_pass(self, payload: twitchio.ChatMessage, username: str) -> None:
        """
        Vote to pass/skip the current song.

        Votes are counted silently; enough votes trigger an anonymous
        Twitch poll instead of naming voters in chat.
        """
        if self.bot.on_skip_vote_callback:
            try:
                # Mod votes carry extra weight in the internal tally -
                # detected by badge, never announced in chat
                is_mod = self._is_privileged(payload)
                added, should_skip = await self.bot.on_skip_vote_callback(username, is_mod)
                if added:
                    logger.info(f"Pass vote registered for {username}" + (" (mod)" if is_mod else ""))
            except Exception as e:
                logger.error(f"Pass command error: {e}")

    async def _get_current_song_info(self) -> str:
        """Get current song title and artist as a formatted string."""
        try:
            if self.bot.on_current_song_request_callback:
                song = await self.bot.on_current_song_request_callback()
                if song and song.get("title") and song.get("artist"):
                    return f"{song['title']} - {song['artist']}"
            return ""
        except Exception:
            return ""

    async def _cmd_queue(self, payload: twitchio.ChatMessage) -> None:
        """Show the current song queue."""
        if self.bot.on_queue_request_callback:
            try:
                queue = await self.bot.on_queue_request_callback()
                if not queue:
                    await self.bot.send_message("Queue is empty! Redeem Channel Points to request songs.")
                else:
                    # Format queue message
                    queue_str = " | ".join(
                        f"{i+1}. {item['title']} - {item['artist']}"
                        for i, item in enumerate(queue[:5])  # Show first 5
                    )
                    total = len(queue)
                    msg = f"Queue ({total}): {queue_str}"
                    if total > 5:
                        msg += f" ... and {total - 5} more"
                    await self.bot.send_message(msg)
            except Exception as e:
                logger.error(f"Queue command error: {e}")

    async def _cmd_forceskip(self, payload: twitchio.ChatMessage, username: str) -> None:
        """Force skip current song (mods only)."""
        if not self._is_privileged(payload):
            return

        if self.bot.on_force_skip_callback:
            try:
                await self.bot.on_force_skip_callback()
                await self.bot.send_message(f"Song skipped by {username}")
            except Exception as e:
                logger.error(f"Force skip error: {e}")

    async def _cmd_clearqueue(self, payload: twitchio.ChatMessage, username: str) -> None:
        """Clear the entire queue (mods only)."""
        if not self._is_privileged(payload):
            return

        if self.bot.on_clear_queue_callback:
            try:
                await self.bot.on_clear_queue_callback()
                await self.bot.send_message(f"Queue cleared by {username}")
            except Exception as e:
                logger.error(f"Clear queue error: {e}")

    async def _cmd_song(self, payload: twitchio.ChatMessage) -> None:
        """Show currently playing song."""
        song_info = await self._get_current_song_info()
        if song_info:
            await self.bot.send_message(f"Now playing: {song_info}")
        else:
            await self.bot.send_message("No song currently playing.")

    async def _cmd_lastsong(self, payload: twitchio.ChatMessage) -> None:
        """Show the last played song."""
        last_song = self.bot.get_last_song()
        if last_song and last_song.get("title") and last_song.get("artist"):
            await self.bot.send_message(f"Last song: {last_song['title']} - {last_song['artist']}")
        else:
            await self.bot.send_message("No previous song recorded yet.")

    async def _cmd_request(self, payload: twitchio.ChatMessage, username: str, song_input: str) -> None:
        """
        Request a song via chat command (broadcaster/mods only, for testing).
        Viewers must use the Channel Points reward so requests always cost points.
        """
        if not self._is_privileged(payload):
            await self.bot.send_message(
                f"@{username} Please use channel points to redeem a song. Thank you!"
            )
            return

        if not song_input.strip():
            await self.bot.send_message(f"@{username} please provide a song name or Spotify link. Usage: !request [song name]")
            return

        if self.bot.on_song_request_callback:
            try:
                logger.info(f"Chat song request from {username}: {song_input}")
                result = await self.bot.on_song_request_callback(username, song_input)
                if result:
                    await self.bot.send_message(_added_message(username, result))
                else:
                    await self.bot.send_message(f"@{username} couldn't find that song. Try a Spotify link or different search.")
            except Exception as e:
                # Check if it's a queue error with a user message
                if hasattr(e, 'user_message'):
                    await self.bot.send_message(f"@{username} {e.user_message}")
                else:
                    logger.error(f"Error processing song request: {e}")
                    await self.bot.send_message(f"@{username} there was an error processing your request.")

    async def _cmd_cancel(self, payload: twitchio.ChatMessage, username: str) -> None:
        """Cancel the user's own request (queued or currently playing)."""
        if not self.bot.on_cancel_request_callback:
            return

        try:
            result = await self.bot.on_cancel_request_callback(username)
            if result:
                if result.get("was_playing"):
                    msg = f'@{username} canceled — skipping "{result["canceled"]}". You can request again right away.'
                else:
                    msg = f'@{username} your request "{result["canceled"]}" was canceled. You can request again right away.'
                await self.bot.send_message(msg)
            else:
                await self.bot.send_message(f"@{username} you don't have a request to cancel.")
        except Exception as e:
            logger.error(f"Cancel command error: {e}")

    async def _cmd_music_rats(self, payload: twitchio.ChatMessage) -> None:
        """Show the top 5 most-praised song requesters (rate-limited)."""
        if not self.bot.on_music_rats_callback:
            return

        now = time.monotonic()
        if now - self._last_music_rats < self.MUSIC_RATS_COOLDOWN:
            return  # silently ignore while on cooldown
        self._last_music_rats = now

        try:
            message = await self.bot.on_music_rats_callback()
            if message:
                await self.bot.send_message(message)
        except Exception as e:
            logger.error(f"Music rats command error: {e}")

    def _is_privileged(self, payload: twitchio.ChatMessage) -> bool:
        """Check if user is broadcaster or mod."""
        try:
            # The broadcaster is always privileged (works even without badges)
            if payload.chatter and payload.broadcaster and payload.chatter.id == payload.broadcaster.id:
                return True

            # Badge TYPE lives in set_id ("broadcaster"/"moderator");
            # badge.id is only the version number ("1")
            badges = getattr(payload, "badges", None) or []
            return any(b.set_id in ("broadcaster", "moderator") for b in badges)
        except Exception:
            return False
