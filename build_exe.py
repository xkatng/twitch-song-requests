"""
Build script for creating standalone executable.
Run with: python build_exe.py
"""

import PyInstaller.__main__
import shutil
import os
from pathlib import Path

# Paths
PROJECT_DIR = Path(__file__).parent
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"

def build():
    print("=" * 60)
    print("Building Twitch Song Request System Executable...")
    print("=" * 60)

    # PyInstaller arguments
    args = [
        str(PROJECT_DIR / "main.py"),
        "--name=TwitchSongRequests",
        "--onedir",  # Create a directory with exe and dependencies
        "--console",  # Show console for debugging
        "--noconfirm",  # Overwrite without asking

        # Add data files
        f"--add-data={PROJECT_DIR / 'frontend'};frontend",
        f"--add-data={PROJECT_DIR / 'config'};config",

        # Hidden imports that PyInstaller might miss
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=twitchio",
        "--hidden-import=twitchio.ext.commands",
        "--hidden-import=twitchio.eventsub",
        "--hidden-import=spotipy",
        "--hidden-import=spotipy.oauth2",
        "--hidden-import=aiofiles",
        "--hidden-import=httpx",
        "--hidden-import=websockets",
        "--hidden-import=pydantic",
        "--hidden-import=pydantic_settings",

        # Output directory
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
    ]

    PyInstaller.__main__.run(args)

    # Copy additional files to dist folder
    output_dir = DIST_DIR / "TwitchSongRequests"

    # Copy .env.example
    env_example = PROJECT_DIR / ".env.example"
    if env_example.exists():
        shutil.copy(env_example, output_dir / ".env.example")

    # Copy .env if exists (for convenience, but user should configure their own)
    env_file = PROJECT_DIR / ".env"
    if env_file.exists():
        shutil.copy(env_file, output_dir / ".env")

    # Create logs directory
    (output_dir / "logs" / "sessions").mkdir(parents=True, exist_ok=True)

    # Create a simple start script
    start_bat = output_dir / "START.bat"
    start_bat.write_text('''@echo off
echo ============================================================
echo    Twitch Song Request System
echo ============================================================
echo.
echo Starting server...
echo.
echo Dashboard: http://localhost:5174/dashboard
echo Overlay:   http://localhost:5174/overlay
echo.
echo The dashboard will open in your browser automatically.
echo Press Ctrl+C to stop the server.
echo ============================================================
echo.
start "" /min cmd /c "timeout /t 6 /nobreak >nul & start "" http://localhost:5174/dashboard"
TwitchSongRequests.exe
pause
''')

    # Create README
    readme = output_dir / "README.txt"
    readme.write_text('''============================================================
   TWITCH SONG REQUEST SYSTEM
============================================================

FIRST TIME SETUP:
-----------------
1. Edit the .env file with your credentials:
   - TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET from https://dev.twitch.tv/console
   - SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET from https://developer.spotify.com/dashboard
   - TWITCH_CHANNEL = your Twitch username

2. Double-click START.bat to run the application

3. Browser windows will open for Spotify and Twitch login - complete both

4. Add OBS Browser Source:
   - URL: http://localhost:5174/overlay
   - Width: 580
   - Height: 220

CHAT COMMANDS:
--------------
Everyone (votes are counted silently - no chat replies):
  !like          - Like the current song
  !pass          - Vote to skip the current song
  !song          - Show current song info
  !lastsong      - Show the previous song
  !queue         - Show the song queue
  !cancel        - Cancel your own request (wrong song? changed your mind?)
  !musicrats     - Top 5 most praised requesters (all-time likes)

Mods Only:
  !skip          - Force skip the current song (also !forceskip, !fs)
  !clearqueue    - Clear the entire queue
  !request       - Queue a song without channel points (testing)

SKIP POLLS:
-----------
30 seconds into every requested song (POLL_AUTO_START_SECONDS), the
bot creates a native Twitch poll: "Skip: Song?" with Keep it /
Skip it choices. Poll votes are anonymous.

Skipping requires BOTH a majority AND at least POLL_MIN_SKIP_VOTES
(default 4) Skip votes - quiet polls mean the song plays on.
The moment Skip reaches POLL_INSTANT_SKIP_VOTES (default 6), the
poll ends and the song skips immediately - no percentage needed.
If Skip reaches POLL_LANDSLIDE_PERCENT (default 70%) of votes with
the minimum met, the poll also ends early.
All poll settings are adjustable live from the Dashboard.

A moderator's !pass counts as MOD_PASS_WEIGHT (default 3) votes in
the internal tally (never announced in chat). Polls only ever run
for requested songs - playlist songs use the !pass threshold.
Requires Twitch Affiliate/Partner. Configure in .env:
POLL_ENABLED, POLL_DURATION_SECONDS, POLL_TRIGGER_VOTES,
POLL_AUTO_START_SECONDS, POLL_MIN_SKIP_VOTES,
POLL_LANDSLIDE_PERCENT, MOD_PASS_WEIGHT

SONG LIMITS:
------------
Requests longer than 5 minutes (MAX_SONG_DURATION_SECONDS) are
rejected with a chat message and the points are refunded when
possible. Set to 0 for no limit.

NOTE: The first launch after adding polls opens the Twitch
authorization page once - approve it to grant poll permissions.

CHANNEL POINTS:
---------------
Create a Channel Point reward with one of these names:
  - SongRedeem (recommended)
  - Song Request
  - Song

Make sure to enable "Require Viewer to Enter Text" so they can enter
a song name or Spotify link.

TROUBLESHOOTING:
----------------
- If Channel Points don't work:
  1. Delete .twitch_cache file
  2. Restart the application
  3. Re-authenticate with Twitch when prompted

- If authentication fails, delete .twitch_cache and .spotify_cache files
- Make sure Spotify Desktop app is running
- Check the console window for error messages

============================================================
''')

    print()
    print("=" * 60)
    print("BUILD COMPLETE!")
    print("=" * 60)
    print()
    print(f"Output folder: {output_dir}")
    print()
    print("Files to copy to the other computer:")
    print(f"  - The entire '{output_dir.name}' folder")
    print()
    print("On the other computer:")
    print("  1. Edit .env with your credentials")
    print("  2. Run START.bat")
    print()

if __name__ == "__main__":
    build()
