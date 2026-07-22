"""
Twitch Song Request System - Main Entry Point

This is the main application file that initializes all services
and starts the server.

Usage:
    python main.py

Or with uvicorn directly:
    uvicorn main:app --host 127.0.0.1 --port 5174 --reload
"""

import asyncio
import logging
import sys
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
import uvicorn

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("song-requests")

# Import our modules
from config.settings import get_settings, RuntimeSettings
from services.spotify_service import SpotifyService
from services.queue_service import QueueService, QueueError, InvalidLinkError
from services.likes_tracker import LikesTracker
from services.session_logger import SessionLogger
from services.twitch_service import TwitchService
from services.twitch_auth import TwitchAuth
from api.websocket_manager import WebSocketManager
from api.routes import create_router
from models.events import SongChangeEvent, VoteUpdateEvent, QueueUpdateEvent


# =============================================================================
# Application State
# =============================================================================

class AppState:
    """Holds all application services and state."""

    def __init__(self):
        self.settings = get_settings()
        self.runtime_settings = RuntimeSettings(self.settings)
        self.ws_manager = WebSocketManager()
        self.spotify: SpotifyService = None
        self.queue: QueueService = None
        self.session_logger: SessionLogger = None
        self.twitch: TwitchService = None
        self.twitch_auth: TwitchAuth = None
        self.playback_task: asyncio.Task = None
        self.twitch_authenticated = asyncio.Event()

        # All-time like leaderboard for !musicrats
        self.likes_tracker = LikesTracker()

        # Skip poll state: {"poll_id", "track_id", "label"} while a poll runs
        self.active_poll: dict = None
        # Tracks that already had their skip poll this session (one poll per song)
        self.polled_track_ids: set = set()


app_state = AppState()


# =============================================================================
# Service Initialization
# =============================================================================

async def initialize_spotify() -> bool:
    """Initialize Spotify service with OAuth."""
    logger.info("Initializing Spotify service...")

    try:
        app_state.spotify = SpotifyService(app_state.settings)

        # Check authentication
        if not app_state.spotify.is_authenticated():
            logger.warning("Spotify not authenticated. Opening browser for auth...")
            auth_url = app_state.spotify.get_auth_url()
            webbrowser.open(auth_url)
            logger.info("Please complete Spotify authentication in your browser.")
            logger.info("The app will automatically continue once authenticated.")
            return False

        # Store current playback context
        app_state.spotify.store_current_context()
        logger.info("Spotify initialized successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to initialize Spotify: {e}")
        return False


async def initialize_queue() -> bool:
    """Initialize queue service and session logger."""
    logger.info("Initializing queue service...")

    try:
        app_state.queue = QueueService(app_state.runtime_settings)
        app_state.session_logger = SessionLogger()
        await app_state.session_logger.start_session()
        logger.info("Queue service initialized")
        return True

    except Exception as e:
        logger.error(f"Failed to initialize queue: {e}")
        return False


async def initialize_twitch() -> bool:
    """Initialize Twitch OAuth service."""
    logger.info("Initializing Twitch authentication...")

    try:
        app_state.twitch_auth = TwitchAuth(
            client_id=app_state.settings.twitch_client_id,
            client_secret=app_state.settings.twitch_client_secret,
            redirect_uri=app_state.settings.twitch_redirect_uri,
        )

        # Check if already authenticated
        if app_state.twitch_auth.is_authenticated():
            logger.info(f"Twitch already authenticated as {app_state.twitch_auth.username}")
            await start_twitch_bot_with_token()
            return True

        # Need to authenticate - open browser
        logger.warning("Twitch not authenticated. Opening browser for auth...")
        auth_url = app_state.twitch_auth.get_auth_url()
        webbrowser.open(auth_url)
        logger.info("Please complete Twitch authentication in your browser.")
        logger.info("The bot will automatically connect once authenticated.")
        return False

    except Exception as e:
        logger.error(f"Failed to initialize Twitch: {e}")
        return False


async def start_twitch_bot_with_token() -> None:
    """Start the Twitch bot with OAuth token."""
    try:
        token = app_state.twitch_auth.access_token
        refresh_token = app_state.twitch_auth.refresh_token
        user_id = app_state.twitch_auth.user_id
        if not token:
            logger.error("No Twitch access token available")
            return

        # Validate token has required scopes for Channel Points
        has_scopes, scopes = await app_state.twitch_auth.validate_token_scopes()
        if not has_scopes:
            logger.warning("=" * 60)
            logger.warning("WARNING: Token may be missing Channel Points scopes!")
            logger.warning("If Channel Points redemptions don't work:")
            logger.warning("  1. Delete the .twitch_cache file")
            logger.warning("  2. Restart the application")
            logger.warning("  3. Re-authenticate with Twitch")
            logger.warning("=" * 60)

        app_state.twitch = TwitchService(
            settings=app_state.settings,
            on_song_request=handle_song_request,
            on_like=handle_like,
            on_skip_vote=handle_skip_vote,
            on_force_skip=handle_force_skip,
            on_clear_queue=handle_clear_queue,
            on_queue_request=handle_queue_request,
            on_current_song_request=api_get_current_song,
            on_poll_end=handle_poll_end,
            on_poll_progress=handle_poll_progress,
            on_music_rats=handle_music_rats,
            on_cancel_request=handle_cancel_request,
            oauth_token=token,
            refresh_token=refresh_token,
            user_id=user_id,
        )

        # Start the bot in background
        asyncio.create_task(start_twitch_bot())

    except Exception as e:
        logger.error(f"Failed to create Twitch service: {e}")


async def start_twitch_bot() -> None:
    """Start the Twitch bot connection."""
    try:
        logger.info("Connecting Twitch bot to chat...")
        await app_state.twitch.start()
    except Exception as e:
        logger.error(f"Twitch bot connection failed: {e}")


# =============================================================================
# Event Handlers
# =============================================================================

def estimate_wait_seconds(position: int) -> int:
    """
    Estimate seconds until the request at a 1-based queue position starts:
    time left on the current song plus the durations of queued songs ahead.
    """
    total_ms = 0
    try:
        progress, duration, _ = app_state.spotify.get_playback_progress()
        if duration:
            total_ms += max(0, duration - progress)
    except Exception:
        pass
    total_ms += app_state.queue.get_pending_duration_ms(position)
    return total_ms // 1000


def format_eta(seconds: int) -> str:
    """Format an ETA as a friendly string, e.g. '~5 min'."""
    if seconds < 90:
        return "~1 min"
    return f"~{round(seconds / 60)} min"


async def handle_song_request(username: str, user_input: str):
    """
    Handle a song request from Channel Points.

    Args:
        username: Twitch username
        user_input: Spotify link or search query

    Returns:
        On success: dict with position and an ETA string for chat replies
        (truthy). False if the song wasn't found. Raises QueueError when
        the request is rejected (cooldown, queue full, too long, ...).
    """
    try:
        # Check if it's an album/playlist/artist link instead of a track
        link_type = app_state.spotify.detect_link_type(user_input)
        logger.debug(f"Link type detected for '{user_input[:50]}...': {link_type}")
        if link_type and link_type != 'track':
            logger.warning(f"User {username} sent a {link_type} link instead of a track")
            raise InvalidLinkError(link_type)

        # Get song from Spotify
        song = app_state.spotify.get_song_from_input(user_input)

        if not song:
            logger.warning(f"Could not find song for input: {user_input}")
            return False

        # Add to internal queue (for tracking requester, votes, etc.)
        request, position = app_state.queue.add_request(song, username)

        # Estimate when it will play (before broadcast, position is 1-based)
        eta_text = format_eta(estimate_wait_seconds(position))

        # Add to Spotify's queue so it shows in the Spotify app
        app_state.spotify.add_to_queue(song)

        # Log to session
        await app_state.session_logger.log_request(request)

        # Broadcast queue update
        await broadcast_queue_update()

        logger.info(f"Added '{song.title}' by {song.artist} (requested by {username}) - added to Spotify queue")

        return {"success": True, "position": position, "eta_text": eta_text, "title": song.title}

    except QueueError as e:
        logger.warning(f"Queue error for {username}: {e.user_message}")
        # Return the error message so it can be shown in chat
        raise e
    except Exception as e:
        logger.error(f"Error handling song request: {e}")
        return False


async def handle_like(username: str) -> bool:
    """Handle a like vote. Likes on requested songs credit the requester."""
    if app_state.queue.add_like(username):
        current = app_state.queue.get_current()
        if current:
            app_state.likes_tracker.add_like(
                current.requester,
                f"{current.song.title} — {current.song.artist}",
            )
        await broadcast_vote_update()
        return True
    return False


async def handle_cancel_request(username: str):
    """
    Cancel the user's own request (queued or currently playing).

    Returns:
        Dict with the canceled title and whether it was playing, or None
        if the user has nothing to cancel.
    """
    # Currently playing their request? Skip it now.
    current = app_state.queue.get_current()
    if current and current.requester.lower() == username.lower():
        title = current.song.title
        app_state.queue.forgive_request(current)
        await skip_current_song()
        logger.info(f"{username} canceled their playing request: {title}")
        return {"canceled": title, "was_playing": True}

    # Otherwise cancel their queued request (auto-skipped when Spotify reaches it)
    removed = app_state.queue.cancel_user_request(username)
    if removed:
        await broadcast_queue_update()
        return {"canceled": removed.song.title, "was_playing": False}

    return None


async def handle_music_rats() -> str:
    """Build the !musicrats leaderboard message (top 5 most-praised requesters)."""
    top = app_state.likes_tracker.top(5)
    if not top:
        return "No liked requests yet — request a song and earn some 👍!"

    ranks = " ".join(
        f"{i + 1}) {name} {likes}👍"
        for i, (name, likes) in enumerate(top)
    )
    msg = f"🐀 Music Rats — most praised requesters: {ranks}"

    best = app_state.likes_tracker.best_song()
    if best:
        label, owner, likes = best
        msg += f' | Top banger: "{label}" ({owner}, {likes}👍)'

    return msg[:450]  # stay safely under Twitch's 500-char message limit


async def handle_skip_vote(username: str, is_mod: bool = False) -> tuple:
    """
    Handle a skip vote.

    A moderator's vote counts as mod_pass_weight votes (default 3) in the
    internal tally - identified by badge, never announced in chat.

    With polls enabled, enough !pass votes launch an anonymous Twitch poll
    that decides the skip. The hard vote threshold only applies as a
    fallback when polls are unavailable (not Affiliate, missing scope, etc.).
    """
    weight = app_state.runtime_settings.mod_pass_weight if is_mod else 1
    added, should_skip = app_state.queue.add_skip_vote(username, weight)

    if added:
        await broadcast_vote_update()
        settings = app_state.runtime_settings

        if settings.poll_enabled:
            _, skips = app_state.queue.get_vote_counts()
            if skips >= settings.poll_trigger_votes:
                started = await start_skip_poll()
                if not started and should_skip:
                    logger.info("Skip threshold reached (poll unavailable) - skipping song")
                    await skip_current_song()
        elif should_skip:
            logger.info("Skip threshold reached - skipping song")
            await skip_current_song()

    return added, should_skip


async def handle_force_skip() -> bool:
    """Handle force skip from mod."""
    return await skip_current_song()


async def handle_clear_queue() -> int:
    """Handle queue clear from mod."""
    count = app_state.queue.clear_queue()
    await broadcast_queue_update()
    return count


async def handle_queue_request() -> list:
    """Handle queue info request."""
    return app_state.queue.get_queue_snapshot()


# =============================================================================
# Skip Poll
# =============================================================================

POLL_KEEP_CHOICE = "Keep it"
POLL_SKIP_CHOICE = "Skip it"


async def start_skip_poll() -> bool:
    """
    Create an anonymous Twitch poll to decide whether to skip the current song.

    Returns True if a poll is running (newly created or already active) or the
    song was already polled; False only if a poll could not be created.
    """
    if not app_state.twitch:
        return False

    # Polls only ever run for requested songs. The streamer's own playlist
    # songs never get polled (!pass falls back to the hard vote threshold).
    if not app_state.queue.get_current():
        return False

    if app_state.active_poll:
        return True  # a skip poll is already running

    track = app_state.spotify.get_current_track()
    track_id = track.get("id") if track else None
    if not track_id:
        return False

    if track_id in app_state.polled_track_ids:
        return True  # this song already had its poll - result stands

    title = track.get("name", "this song")
    artist = ", ".join(a["name"] for a in track.get("artists", []))
    label = f"{title} — {artist}" if artist else title

    poll_id = await app_state.twitch.create_poll(
        title=f"Skip: {title}?",
        choices=[POLL_KEEP_CHOICE, POLL_SKIP_CHOICE],
        duration_seconds=app_state.runtime_settings.poll_duration_seconds,
    )
    if not poll_id:
        return False

    app_state.polled_track_ids.add(track_id)
    app_state.active_poll = {"poll_id": poll_id, "track_id": track_id, "label": label}

    await app_state.twitch.send_message(
        f'⚖️ Skip poll started for "{label}" — vote in the poll, it\'s anonymous!'
    )
    logger.info(f"Skip poll started for '{label}' (poll {poll_id})")
    return True


async def maybe_auto_start_poll(current_track_id: str, progress_ms: int, is_playing: bool) -> None:
    """
    Auto-start the skip poll partway into a requested song.

    Fires once per track: on success the track lands in polled_track_ids;
    on failure it is marked polled anyway so we don't retry every 2 seconds.
    Non-requested (playlist) songs are skipped - those can still get a poll
    via !pass votes.
    """
    settings = app_state.runtime_settings
    if not (settings.poll_enabled and settings.poll_auto_start_seconds):
        return
    if not (current_track_id and is_playing):
        return
    if app_state.active_poll or current_track_id in app_state.polled_track_ids:
        return
    if not app_state.queue.get_current():
        return  # not a requested song
    if progress_ms < settings.poll_auto_start_seconds * 1000:
        return

    started = await start_skip_poll()
    if not started:
        app_state.polled_track_ids.add(current_track_id)
        logger.warning("Auto skip poll could not be created for this song - not retrying")


async def handle_poll_end(payload) -> None:
    """
    Handle a channel.poll.end EventSub notification.

    Only acts on the bot's own skip poll (ignores polls the streamer runs
    manually) and only if the polled song is still playing.
    """
    poll = app_state.active_poll
    if not poll or payload.id != poll["poll_id"]:
        return

    app_state.active_poll = None

    if payload.status == "archived":
        return  # results hidden - treat as cancelled

    keep_votes = 0
    skip_votes = 0
    for choice in payload.choices:
        if choice.title == POLL_KEEP_CHOICE:
            keep_votes = choice.votes or 0
        elif choice.title == POLL_SKIP_CHOICE:
            skip_votes = choice.votes or 0

    # Only act if the polled song is still playing
    track = app_state.spotify.get_current_track()
    current_id = track.get("id") if track else None
    if current_id != poll["track_id"]:
        logger.info("Skip poll ended after the song - ignoring result")
        return

    # Skipping needs a majority AND a minimum number of Skip votes -
    # a 2-1 poll with three voters shouldn't kill a song. Exception:
    # reaching the instant-skip count always skips, regardless of ratio
    # (most viewers who are fine with a song never vote Keep).
    settings = app_state.runtime_settings
    min_skips = settings.poll_min_skip_votes
    instant_hit = settings.poll_instant_skip_votes and skip_votes >= settings.poll_instant_skip_votes
    # No chat message either way - the native Twitch poll already shows the
    # result, so the bot acts silently
    if instant_hit or (skip_votes > keep_votes and skip_votes >= min_skips):
        logger.info(f'Poll skip: "{poll["label"]}" ({skip_votes}-{keep_votes})')
        app_state.queue.reset_votes()
        await broadcast_vote_update()
        await skip_current_song()
    else:
        logger.info(f'Poll keep: "{poll["label"]}" ({keep_votes}-{skip_votes})')
        app_state.queue.reset_votes()
        await broadcast_vote_update()


async def handle_poll_progress(payload) -> None:
    """
    Handle live poll vote updates: end the skip poll early once the outcome
    is decided, so bad songs get skipped quickly. Two independent triggers:

    - Instant skip: Skip reaches poll_instant_skip_votes (pure count - works
      even though almost nobody bothers voting Keep)
    - Landslide: Skip has the minimum votes AND poll_landslide_percent of
      all votes cast

    The poll.end event then applies the result.
    """
    poll = app_state.active_poll
    if not poll or payload.id != poll["poll_id"] or poll.get("ending"):
        return

    settings = app_state.runtime_settings

    keep_votes = 0
    skip_votes = 0
    for choice in payload.choices:
        if choice.title == POLL_KEEP_CHOICE:
            keep_votes = choice.votes or 0
        elif choice.title == POLL_SKIP_CHOICE:
            skip_votes = choice.votes or 0

    instant = settings.poll_instant_skip_votes
    instant_hit = instant and skip_votes >= instant

    total = keep_votes + skip_votes
    landslide_hit = (
        settings.poll_landslide_percent
        and total > 0
        and skip_votes >= settings.poll_min_skip_votes
        and (skip_votes / total) * 100 >= settings.poll_landslide_percent
    )

    if not (instant_hit or landslide_hit):
        return

    poll["ending"] = True
    reason = "instant-skip count" if instant_hit else "landslide"
    logger.info(f"{reason} reached ({skip_votes}-{keep_votes}) - ending skip poll early")
    await app_state.twitch.end_poll(poll["poll_id"])


# =============================================================================
# Playback Control
# =============================================================================

async def skip_current_song() -> bool:
    """
    Skip the current song by advancing Spotify playback.

    Requested songs are already in Spotify's own queue (added at request
    time), so skipping must go through Spotify's queue too - playing the
    next request directly would leave a duplicate copy in Spotify's queue.
    The playback monitor detects the track change and updates the
    overlay/queue state.
    """
    app_state.queue.clear_current()
    return app_state.spotify.skip_track()


# =============================================================================
# WebSocket Broadcasting
# =============================================================================

async def broadcast_song_change(request) -> None:
    """Broadcast song change event."""
    event = SongChangeEvent.from_request(request)
    await app_state.ws_manager.broadcast(event)


async def broadcast_song_change_from_spotify() -> None:
    """Broadcast current Spotify track (non-request)."""
    track = app_state.spotify.get_current_track()
    if track:
        event = SongChangeEvent.from_spotify_track(track)
        await app_state.ws_manager.broadcast(event)


async def broadcast_vote_update() -> None:
    """Broadcast vote update event."""
    likes, skips = app_state.queue.get_vote_counts()
    event = VoteUpdateEvent(
        likes=likes,
        skips=skips,
        skip_threshold=app_state.runtime_settings.skip_threshold,
    )
    await app_state.ws_manager.broadcast(event)


async def broadcast_queue_update() -> None:
    """Broadcast queue update event."""
    # Get next song - prefer request queue, fallback to Spotify queue
    next_song = app_state.queue.get_next_preview()
    if not next_song and app_state.spotify:
        next_song = app_state.spotify.get_next_in_queue()

    event = QueueUpdateEvent.from_queue_state(
        app_state.queue.get_queue_snapshot(),
        app_state.runtime_settings.max_queue_size,
        next_song,
    )
    await app_state.ws_manager.broadcast(event)


# =============================================================================
# Playback Monitor
# =============================================================================

async def playback_monitor_loop():
    """Background task to monitor playback and advance queue."""
    logger.info("Starting playback monitor...")

    last_track_id = None

    while True:
        try:
            await asyncio.sleep(2)  # Check every 2 seconds

            # Skip if Spotify not initialized
            if not app_state.spotify:
                continue

            # Get current playback state
            progress, duration, is_playing = app_state.spotify.get_playback_progress()

            # Get current track to detect song changes
            current_track = app_state.spotify.get_current_track()
            current_track_id = current_track.get("id") if current_track else None

            # Detect song change
            if current_track_id and current_track_id != last_track_id:
                # Canceled request reached the front of Spotify's queue
                # (Spotify has no remove-from-queue API) - skip it silently
                if current_track_id in app_state.queue.canceled_song_ids:
                    app_state.queue.canceled_song_ids.discard(current_track_id)
                    last_track_id = current_track_id
                    logger.info("Auto-skipping canceled request")
                    app_state.spotify.skip_track()
                    continue

                # End any skip poll left over from the previous song. The
                # poll.end handler ignores it because active_poll is cleared.
                if app_state.active_poll and app_state.active_poll["track_id"] != current_track_id:
                    stale_poll = app_state.active_poll
                    app_state.active_poll = None
                    if app_state.twitch:
                        await app_state.twitch.end_poll(stale_poll["poll_id"])

                last_track_id = current_track_id
                artist_str = ", ".join(a["name"] for a in current_track.get("artists", []))
                logger.info(f"Track changed: {current_track.get('name', 'Unknown')}")

                # Update the Twitch service with the new song (for !lastsong command)
                if app_state.twitch and current_track:
                    app_state.twitch.update_current_song({
                        "title": current_track.get("name", "Unknown"),
                        "artist": artist_str,
                    })

                # Reset votes for the new song
                app_state.queue.reset_votes()
                await broadcast_vote_update()

                # Check if this track was requested (match by Spotify ID)
                request = app_state.queue.find_and_remove_by_spotify_id(current_track_id)
                if request:
                    # This is a requested song - set it as current and broadcast with requester
                    app_state.queue.set_current(request)
                    logger.info(f"Playing request from {request.requester}: {request.song.title}")
                    await broadcast_song_change(request)
                    if app_state.twitch:
                        await app_state.twitch.send_message(
                            f"🐀 Now playing: {request.song.title} — {request.song.artist} | "
                            f"Requested by @{request.requester} | !like or !pass to vote"
                        )
                else:
                    # Not a request - broadcast as regular Spotify track
                    app_state.queue.clear_current()
                    await broadcast_song_change_from_spotify()

                # Broadcast queue update to refresh "Up Next"
                await broadcast_queue_update()

            # Auto-start the skip poll partway into requested songs
            await maybe_auto_start_poll(current_track_id, progress, is_playing)

            # Skip WebSocket broadcasts if no connections
            if not app_state.ws_manager.has_connections:
                continue

            # Broadcast progress to overlay
            await app_state.ws_manager.broadcast_progress(progress, duration, is_playing)

        except asyncio.CancelledError:
            logger.info("Playback monitor stopped")
            break
        except Exception as e:
            logger.error(f"Playback monitor error: {e}")
            await asyncio.sleep(5)


# =============================================================================
# API Callbacks
# =============================================================================

async def api_get_queue_state() -> dict:
    """Get queue state for API."""
    state = app_state.queue.get_full_state()

    # If no request queue next song, get from Spotify queue
    if not state.get("next_song") and app_state.spotify:
        state["next_song"] = app_state.spotify.get_next_in_queue()

    return state


async def api_get_current_song() -> dict:
    """Get current song for API."""
    current = app_state.queue.get_current()
    if current:
        return current.to_dict()

    # Get from Spotify if not a request
    track = app_state.spotify.get_current_track()
    if track:
        # Get album art
        album_art = ""
        if track.get("album", {}).get("images"):
            album_art = track["album"]["images"][0]["url"]

        return {
            "playing": True,
            "is_request": False,
            "title": track.get("name"),
            "artist": ", ".join(a["name"] for a in track.get("artists", [])),
            "album_art_url": album_art,
        }

    return {"playing": False}


async def api_skip_song() -> bool:
    """Skip song for API."""
    return await skip_current_song()


async def api_remove_from_queue(index: int) -> dict:
    """Remove song from queue for API."""
    removed = app_state.queue.remove_at(index)
    if removed:
        await broadcast_queue_update()
        return removed.to_dict()
    return None


async def api_clear_queue() -> int:
    """Clear queue for API."""
    count = app_state.queue.clear_queue()
    await broadcast_queue_update()
    return count


async def api_get_settings() -> dict:
    """Get settings for API."""
    return app_state.runtime_settings.to_dict()


async def api_update_settings(
    max_queue_size=None,
    cooldown_seconds=None,
    skip_threshold=None,
    poll_enabled=None,
    poll_duration_seconds=None,
    poll_trigger_votes=None,
    poll_auto_start_seconds=None,
    poll_min_skip_votes=None,
    poll_landslide_percent=None,
    poll_instant_skip_votes=None,
    mod_pass_weight=None,
    max_song_duration_seconds=None,
) -> dict:
    """Update settings for API."""
    return app_state.runtime_settings.update(
        max_queue_size=max_queue_size,
        cooldown_seconds=cooldown_seconds,
        skip_threshold=skip_threshold,
        poll_enabled=poll_enabled,
        poll_duration_seconds=poll_duration_seconds,
        poll_trigger_votes=poll_trigger_votes,
        poll_auto_start_seconds=poll_auto_start_seconds,
        poll_min_skip_votes=poll_min_skip_votes,
        poll_landslide_percent=poll_landslide_percent,
        poll_instant_skip_votes=poll_instant_skip_votes,
        mod_pass_weight=mod_pass_weight,
        max_song_duration_seconds=max_song_duration_seconds,
    )


async def api_get_blocklist() -> dict:
    """Get blocklist for API."""
    return {
        "blocklist_artists": app_state.runtime_settings.blocklist_artists,
        "blocklist_song_ids": app_state.runtime_settings.blocklist_song_ids,
    }


async def api_add_to_blocklist(item: str, is_artist: bool) -> bool:
    """Add to blocklist for API."""
    return app_state.runtime_settings.add_to_blocklist(item, is_artist)


async def api_remove_from_blocklist(item: str) -> bool:
    """Remove from blocklist for API."""
    return app_state.runtime_settings.remove_from_blocklist(item)


async def api_get_session_logs() -> list:
    """Get session logs for API."""
    return await app_state.session_logger.get_recent_entries(20)


# =============================================================================
# FastAPI Application
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("=" * 60)
    logger.info("Starting Twitch Song Request System...")
    logger.info("=" * 60)

    # Initialize services
    await initialize_spotify()
    await initialize_queue()
    await initialize_twitch()

    # Start playback monitor
    app_state.playback_task = asyncio.create_task(playback_monitor_loop())

    logger.info("=" * 60)
    logger.info(f"Server running at http://{app_state.settings.server_host}:{app_state.settings.server_port}")
    logger.info(f"Dashboard: http://localhost:{app_state.settings.server_port}/dashboard")
    logger.info(f"Overlay:   http://localhost:{app_state.settings.server_port}/overlay")
    logger.info("=" * 60)

    yield

    # Cleanup
    logger.info("Shutting down...")
    if app_state.playback_task:
        app_state.playback_task.cancel()
        try:
            await app_state.playback_task
        except asyncio.CancelledError:
            pass


# Create FastAPI app
app = FastAPI(
    title="Twitch Song Request System",
    description="Song request system for Twitch streams with Spotify integration",
    version="1.0.0",
    lifespan=lifespan,
)

# Create and include API router
api_router = create_router(
    ws_manager=app_state.ws_manager,
    get_queue_state=api_get_queue_state,
    get_current_song=api_get_current_song,
    skip_song=api_skip_song,
    remove_from_queue=api_remove_from_queue,
    clear_queue=api_clear_queue,
    get_settings=api_get_settings,
    update_settings=api_update_settings,
    get_blocklist=api_get_blocklist,
    add_to_blocklist=api_add_to_blocklist,
    remove_from_blocklist=api_remove_from_blocklist,
    get_session_logs=api_get_session_logs,
    add_like=handle_like,
    add_skip_vote=handle_skip_vote,
    add_test_request=handle_song_request,
)
app.include_router(api_router)


# =============================================================================
# Static File Routes
# =============================================================================

# Get the frontend directory
FRONTEND_DIR = Path(__file__).parent / "frontend"


@app.get("/")
async def root():
    """Redirect root to dashboard."""
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard():
    """Serve dashboard HTML."""
    return FileResponse(FRONTEND_DIR / "dashboard.html")


@app.get("/overlay")
async def overlay():
    """Serve overlay HTML."""
    return FileResponse(FRONTEND_DIR / "overlay.html")


# Mount static files for CSS and JS
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


# =============================================================================
# Spotify OAuth Callback
# =============================================================================

@app.get("/auth/spotify/callback")
async def spotify_oauth_callback(code: str = None, error: str = None):
    """
    Handle Spotify OAuth callback.

    Needed for re-authentication while the server is running (e.g. after
    Spotify revokes a refresh token): spotipy's own one-shot local server
    can't bind our port, so the redirect lands here instead.
    """
    if error or not code:
        logger.error(f"Spotify OAuth error: {error or 'missing code'}")
        return HTMLResponse(f"""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Spotify Authentication Failed</h1>
                <p>Error: {error or 'missing authorization code'}</p>
                <p>Please close this window and try again.</p>
            </body></html>
        """)

    try:
        auth_manager = app_state.spotify.sp.auth_manager
        # Exchanges the code and writes .spotify_cache; the running client
        # picks the new token up on its next request automatically
        auth_manager.get_access_token(code, as_dict=False)
        app_state.spotify.store_current_context()
        logger.info("Spotify OAuth successful - token cached")
        return HTMLResponse("""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>✅ Spotify Connected!</h1>
                <p>You can close this window. The bot will resume automatically.</p>
            </body></html>
        """)
    except Exception as e:
        logger.error(f"Spotify OAuth token exchange failed: {e}")
        return HTMLResponse(f"""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Spotify Token Exchange Failed</h1>
                <p>{e}</p>
                <p>Close this window and restart the bot to retry.</p>
            </body></html>
        """)


# =============================================================================
# Twitch OAuth Callback
# =============================================================================

@app.get("/auth/twitch/callback")
async def twitch_oauth_callback(code: str = None, state: str = None, error: str = None):
    """Handle Twitch OAuth callback."""
    if error:
        logger.error(f"Twitch OAuth error: {error}")
        return HTMLResponse(f"""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Twitch Authentication Failed</h1>
                <p>Error: {error}</p>
                <p>Please close this window and try again.</p>
            </body></html>
        """)

    if not code or not state:
        return HTMLResponse("""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Invalid Callback</h1>
                <p>Missing authorization code or state.</p>
            </body></html>
        """)

    # Exchange code for token
    success = await app_state.twitch_auth.handle_callback(code, state)

    if success:
        logger.info("Twitch OAuth successful - starting bot...")
        # Start the bot with the new token
        await start_twitch_bot_with_token()

        return HTMLResponse("""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>✅ Twitch Connected!</h1>
                <p>Authentication successful. The bot is now connecting to your channel.</p>
                <p>You can close this window and return to the application.</p>
                <script>setTimeout(() => window.close(), 3000);</script>
            </body></html>
        """)
    else:
        return HTMLResponse("""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Authentication Failed</h1>
                <p>Could not complete authentication. Please try again.</p>
            </body></html>
        """)


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """Main entry point."""
    import sys
    settings = get_settings()

    # Check if running as PyInstaller executable
    if getattr(sys, 'frozen', False):
        # Running as executable - use app object directly, no reload
        uvicorn.run(
            app,
            host=settings.server_host,
            port=settings.server_port,
            log_level="info",
        )
    else:
        # Running as script - can use reload
        uvicorn.run(
            "main:app",
            host=settings.server_host,
            port=settings.server_port,
            reload=settings.debug,
            log_level="info" if not settings.debug else "debug",
        )


if __name__ == "__main__":
    main()
