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
echo Press Ctrl+C to stop the server.
echo ============================================================
echo.
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
Everyone:
  !like          - Like the current song
  !pass          - Vote to skip the current song
  !song          - Show current song info
  !lastsong      - Show the previous song
  !queue         - Show the song queue

Mods Only:
  !forceskip     - Force skip the current song
  !clearqueue    - Clear the entire queue

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
