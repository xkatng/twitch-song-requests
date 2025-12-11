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

async def handle_song_request(username: str, user_input: str) -> bool:
    """
    Handle a song request from Channel Points.

    Args:
        username: Twitch username
        user_input: Spotify link or search query

    Returns:
        True if request was added, False otherwise
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

        # Add to Spotify's queue so it shows in the Spotify app
        app_state.spotify.add_to_queue(song)

        # Log to session
        await app_state.session_logger.log_request(request)

        # Broadcast queue update
        await broadcast_queue_update()

        logger.info(f"Added '{song.title}' by {song.artist} (requested by {username}) - added to Spotify queue")

        return True

    except QueueError as e:
        logger.warning(f"Queue error for {username}: {e.user_message}")
        # Return the error message so it can be shown in chat
        raise e
    except Exception as e:
        logger.error(f"Error handling song request: {e}")
        return False


async def handle_like(username: str) -> bool:
    """Handle a like vote."""
    if app_state.queue.add_like(username):
        await broadcast_vote_update()
        return True
    return False


async def handle_skip_vote(username: str) -> tuple:
    """Handle a skip vote."""
    added, should_skip = app_state.queue.add_skip_vote(username)

    if added:
        await broadcast_vote_update()

        if should_skip:
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
# Playback Control
# =============================================================================

async def play_next_song() -> bool:
    """Play the next song from the queue."""
    request = app_state.queue.get_next()

    if not request:
        # Queue is empty - resume previous context
        logger.info("Queue empty - resuming previous playlist")
        app_state.queue.clear_current()
        app_state.spotify.resume_previous_context()
        await broadcast_song_change_from_spotify()
        return False

    # Play the requested song
    success = app_state.spotify.play_track(request.song)

    if success:
        app_state.queue.set_current(request)
        await broadcast_song_change(request)
        await broadcast_queue_update()

    return success


async def skip_current_song() -> bool:
    """Skip the current song and play next."""
    app_state.queue.clear_current()
    return await play_next_song()


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
                last_track_id = current_track_id
                logger.info(f"Track changed: {current_track.get('name', 'Unknown')}")

                # Update the Twitch service with the new song (for !lastsong command)
                if app_state.twitch and current_track:
                    app_state.twitch.update_current_song({
                        "title": current_track.get("name", "Unknown"),
                        "artist": ", ".join(a["name"] for a in current_track.get("artists", [])),
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
                else:
                    # Not a request - broadcast as regular Spotify track
                    app_state.queue.clear_current()
                    await broadcast_song_change_from_spotify()

                # Broadcast queue update to refresh "Up Next"
                await broadcast_queue_update()

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


async def api_update_settings(max_queue_size=None, cooldown_seconds=None, skip_threshold=None) -> dict:
    """Update settings for API."""
    return app_state.runtime_settings.update(
        max_queue_size=max_queue_size,
        cooldown_seconds=cooldown_seconds,
        skip_threshold=skip_threshold,
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
