"""
REST API and WebSocket routes for the Song Request system.
"""

import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Request/Response Models
# -------------------------------------------------------------------------

class SettingsUpdate(BaseModel):
    """Request model for updating settings."""
    max_queue_size: Optional[int] = None
    cooldown_seconds: Optional[int] = None
    skip_threshold: Optional[int] = None


class BlocklistItem(BaseModel):
    """Request model for adding to blocklist."""
    item: str
    is_artist: bool = True


class SkipRequest(BaseModel):
    """Request model for skipping (empty, just for documentation)."""
    pass


class TestVoteRequest(BaseModel):
    """Request model for testing votes."""
    username: str = "testuser"


# -------------------------------------------------------------------------
# Router Factory
# -------------------------------------------------------------------------

def create_router(
    ws_manager: WebSocketManager,
    get_queue_state: callable,
    get_current_song: callable,
    skip_song: callable,
    remove_from_queue: callable,
    clear_queue: callable,
    get_settings: callable,
    update_settings: callable,
    get_blocklist: callable,
    add_to_blocklist: callable,
    remove_from_blocklist: callable,
    get_session_logs: callable,
    add_like: callable = None,
    add_skip_vote: callable = None,
    add_test_request: callable = None,
) -> APIRouter:
    """
    Create the API router with all routes.

    Args:
        ws_manager: WebSocket connection manager
        get_queue_state: Callback to get queue state
        get_current_song: Callback to get current song
        skip_song: Callback to skip current song
        remove_from_queue: Callback to remove song from queue
        clear_queue: Callback to clear queue
        get_settings: Callback to get current settings
        update_settings: Callback to update settings
        get_blocklist: Callback to get blocklist
        add_to_blocklist: Callback to add to blocklist
        remove_from_blocklist: Callback to remove from blocklist
        get_session_logs: Callback to get session log entries

    Returns:
        Configured APIRouter
    """
    router = APIRouter(prefix="/api")

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    @router.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok", "connections": ws_manager.connection_count}

    # -------------------------------------------------------------------------
    # Queue Endpoints
    # -------------------------------------------------------------------------

    @router.get("/queue")
    async def get_queue():
        """Get current queue state."""
        try:
            state = await get_queue_state()
            return state
        except Exception as e:
            logger.error(f"Error getting queue: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/current")
    async def get_current():
        """Get currently playing song."""
        try:
            song = await get_current_song()
            return song or {"playing": False}
        except Exception as e:
            logger.error(f"Error getting current song: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/skip")
    async def skip_current():
        """Skip the current song."""
        try:
            result = await skip_song()
            return {"success": result}
        except Exception as e:
            logger.error(f"Error skipping song: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/queue/{index}")
    async def remove_song(index: int):
        """Remove a song from the queue by index."""
        try:
            removed = await remove_from_queue(index)
            if removed:
                return {"success": True, "removed": removed}
            raise HTTPException(status_code=404, detail="Song not found at index")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error removing song: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/queue")
    async def clear_all():
        """Clear the entire queue."""
        try:
            count = await clear_queue()
            return {"success": True, "removed_count": count}
        except Exception as e:
            logger.error(f"Error clearing queue: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # Settings Endpoints
    # -------------------------------------------------------------------------

    @router.get("/settings")
    async def get_current_settings():
        """Get current runtime settings."""
        try:
            settings = await get_settings()
            return settings
        except Exception as e:
            logger.error(f"Error getting settings: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.patch("/settings")
    async def update_current_settings(update: SettingsUpdate):
        """Update runtime settings."""
        try:
            new_settings = await update_settings(
                max_queue_size=update.max_queue_size,
                cooldown_seconds=update.cooldown_seconds,
                skip_threshold=update.skip_threshold,
            )
            return new_settings
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # Blocklist Endpoints
    # -------------------------------------------------------------------------

    @router.get("/blocklist")
    async def get_blocklist_items():
        """Get current blocklist."""
        try:
            blocklist = await get_blocklist()
            return blocklist
        except Exception as e:
            logger.error(f"Error getting blocklist: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/blocklist")
    async def add_blocklist_item(item: BlocklistItem):
        """Add item to blocklist."""
        try:
            added = await add_to_blocklist(item.item, item.is_artist)
            return {"success": added, "item": item.item}
        except Exception as e:
            logger.error(f"Error adding to blocklist: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/blocklist/{item}")
    async def remove_blocklist_item(item: str):
        """Remove item from blocklist."""
        try:
            removed = await remove_from_blocklist(item)
            return {"success": removed, "item": item}
        except Exception as e:
            logger.error(f"Error removing from blocklist: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # Session Log Endpoints
    # -------------------------------------------------------------------------

    @router.get("/session/logs")
    async def get_logs():
        """Get recent session log entries."""
        try:
            logs = await get_session_logs()
            return logs
        except Exception as e:
            logger.error(f"Error getting logs: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # -------------------------------------------------------------------------
    # WebSocket Endpoint
    # -------------------------------------------------------------------------

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await ws_manager.connect(websocket)

        try:
            # Send welcome message with current state
            state = await get_queue_state()
            await ws_manager.send_welcome(
                websocket,
                queue_length=state.get("queue_length", 0),
                is_playing_requests=state.get("is_playing_requests", False),
            )

            # Keep connection alive
            while True:
                # Wait for messages (mainly for ping/pong)
                data = await websocket.receive_text()
                # Echo back for keepalive
                await websocket.send_text('{"event_type": "pong"}')

        except WebSocketDisconnect:
            await ws_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await ws_manager.disconnect(websocket)

    # -------------------------------------------------------------------------
    # Test Endpoints (for testing without Twitch)
    # -------------------------------------------------------------------------

    @router.post("/test/like")
    async def test_like(vote: TestVoteRequest):
        """Test endpoint: Simulate a like vote."""
        if add_like:
            try:
                result = await add_like(vote.username)
                return {"success": result, "username": vote.username, "action": "like"}
            except Exception as e:
                logger.error(f"Test like error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=501, detail="Like callback not configured")

    @router.post("/test/skip-vote")
    async def test_skip_vote(vote: TestVoteRequest):
        """Test endpoint: Simulate a skip vote."""
        if add_skip_vote:
            try:
                added, should_skip = await add_skip_vote(vote.username)
                return {
                    "success": added,
                    "username": vote.username,
                    "action": "skip_vote",
                    "triggered_skip": should_skip
                }
            except Exception as e:
                logger.error(f"Test skip vote error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=501, detail="Skip vote callback not configured")

    @router.post("/test/request")
    async def test_request(song_query: str = "Never Gonna Give You Up"):
        """Test endpoint: Simulate a song request."""
        if add_test_request:
            try:
                result = await add_test_request("TestUser", song_query)
                return {"success": result, "query": song_query}
            except Exception as e:
                logger.error(f"Test request error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=501, detail="Test request callback not configured")

    return router


# -------------------------------------------------------------------------
# Localhost-only Middleware
# -------------------------------------------------------------------------

def localhost_only_middleware(request: Request):
    """
    Check if request is from localhost.
    Used to restrict dashboard access.
    """
    client_host = request.client.host if request.client else None

    allowed_hosts = ["127.0.0.1", "localhost", "::1"]

    if client_host not in allowed_hosts:
        raise HTTPException(
            status_code=403,
            detail="Dashboard only accessible from localhost"
        )
