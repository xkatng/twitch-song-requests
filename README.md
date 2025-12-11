# Twitch Song Request System

A complete song request system for Twitch streams with Spotify integration, Channel Points support, and a beautiful OBS overlay.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)

## Features

- **Channel Points Integration** - Viewers redeem "SongRedeem" to request songs
- **Spotify Integration** - Search by song name or paste Spotify track links
- **Real-time OBS Overlay** - Compact 450x160px overlay with album art, progress bar, and vote counts
- **Vote System** - `!like` and `!pass` chat commands for viewer interaction
- **Web Dashboard** - Manage queue, settings, and blocklist from your browser
- **Auto-Resume** - Returns to your playlist when the request queue empties
- **Session Logging** - CSV logs of all song requests
- **Duplicate Prevention** - Same song can't be requested twice per stream
- **User Cooldowns** - Configurable cooldown between requests per user
- **Blocklist** - Block specific artists or songs

## Screenshots

### OBS Overlay
The overlay shows the current song, artist, album art, progress bar, like/skip votes, and the next song in queue.

### Dashboard
Web-based control panel for managing the queue, adjusting settings, and viewing request history.

## Quick Start

### Prerequisites

- **Python 3.11+** - Download from [python.org](https://www.python.org/downloads/)
- **Spotify Premium** - Required for playback control
- **Twitch Affiliate/Partner** - Required for Channel Points

### Installation

1. **Clone or download this project:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/twitch-song-requests.git
   cd twitch-song-requests
   ```

2. **Create virtual environment:**
   ```bash
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Copy and configure environment file:**
   ```bash
   # Windows
   copy .env.example .env

   # macOS/Linux
   cp .env.example .env
   ```
   Edit `.env` with your credentials (see Configuration section below).

5. **Run the application:**
   ```bash
   python main.py
   ```

6. **Complete authentication:**
   - Browser windows will open for Spotify and Twitch login
   - Authorize both applications
   - The server will start automatically

7. **Open the dashboard:**
   - Dashboard: http://localhost:5174/dashboard
   - Overlay: http://localhost:5174/overlay

## Configuration

### Spotify Setup

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Click **Create App**
3. Fill in:
   - App name: `Song Request Bot` (or any name you like)
   - Redirect URI: `http://127.0.0.1:5174/auth/spotify/callback`
   - Select **Web API**
4. Copy **Client ID** and **Client Secret** to your `.env` file

> **Important:** Use `127.0.0.1` (not `localhost`) for the Spotify redirect URI.

### Twitch Setup

1. Go to [Twitch Developer Console](https://dev.twitch.tv/console)
2. Click **Register Your Application**
3. Fill in:
   - Name: `Song Request Bot` (or any name you like)
   - OAuth Redirect URL: `http://localhost:5174/auth/twitch/callback`
   - Category: **Chat Bot**
4. Copy **Client ID** and generate a **Client Secret**
5. Add both to your `.env` file

### Channel Points Reward

Create a Channel Points reward on your Twitch channel with one of these names:
- **SongRedeem** (recommended)
- **Song Request**
- **Song**

Make sure to enable **"Require Viewer to Enter Text"** so viewers can enter the song name or Spotify link.

### Required .env Values

```ini
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
TWITCH_CLIENT_ID=your_twitch_client_id
TWITCH_CLIENT_SECRET=your_twitch_client_secret
TWITCH_CHANNEL=your_channel_name
```

## OBS Setup

1. In OBS, add a new **Browser Source**
2. Set URL to: `http://localhost:5174/overlay`
3. Set Width: `450`, Height: `160`
4. **Uncheck** "Shutdown source when not visible"
5. Position the overlay in your scene

## Chat Commands

### For Everyone

| Command | Description |
|---------|-------------|
| `!like` | Like the current song |
| `!pass` | Vote to skip the current song |
| `!queue` or `!q` | View the song request queue |
| `!song` or `!np` | Show the current song |
| `!lastsong` | Show the previously played song |
| `!sr <song>` | Request a song (fallback if Channel Points don't work) |

### For Moderators & Broadcaster

| Command | Description |
|---------|-------------|
| `!forceskip` or `!fs` | Force skip the current song |
| `!clearqueue` or `!cq` | Clear the entire queue |

## Settings

Configure via the dashboard or `.env` file:

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_QUEUE_SIZE` | 10 | Maximum songs in queue |
| `COOLDOWN_SECONDS` | 300 | Cooldown between requests per user (5 min) |
| `SKIP_THRESHOLD` | 5 | Skip votes needed to auto-skip |
| `CHANNEL_POINTS_COST` | 500 | Cost of song request reward |

## Building Standalone Executable

To create a standalone `.exe` for Windows:

```bash
python build_exe.py
```

The executable will be created in `dist/TwitchSongRequests/`.

## Troubleshooting

### Channel Points redemptions not working

This is the most common issue. Try these steps:

1. **Delete the `.twitch_cache` file** in the application folder
2. **Restart the application**
3. **Re-authenticate with Twitch** when the browser opens
4. Make sure your Channel Points reward is named "SongRedeem", "Song Request", or "Song"

The `!sr` command is available as a fallback for requesting songs.

### Spotify not playing

1. Make sure Spotify desktop app is open and playing something
2. Check that you have Spotify Premium (required for playback control)
3. Delete `.spotify_cache` and re-authenticate

### Overlay not updating

1. Check the browser console for WebSocket errors
2. Verify the server is running on port 5174
3. Try refreshing the browser source in OBS

### "No devices found" error

1. Open Spotify desktop app
2. Play any song to activate the device
3. The app will detect the active device

## Project Structure

```
twitch-song-requests/
├── main.py                 # Application entry point
├── build_exe.py            # PyInstaller build script
├── requirements.txt        # Python dependencies
├── .env.example            # Configuration template
├── config/
│   └── settings.py         # Settings management
├── models/
│   ├── song.py             # Song and SongRequest models
│   ├── queue.py            # Queue state model
│   └── events.py           # WebSocket event models
├── services/
│   ├── spotify_service.py  # Spotify API integration
│   ├── twitch_service.py   # Twitch chat and Channel Points
│   ├── twitch_auth.py      # Twitch OAuth handling
│   ├── queue_service.py    # Request queue management
│   └── session_logger.py   # CSV logging
├── api/
│   ├── routes.py           # REST API endpoints
│   └── websocket_manager.py # WebSocket connections
├── frontend/
│   ├── overlay.html        # OBS overlay
│   ├── dashboard.html      # Control panel
│   ├── css/
│   └── js/
└── logs/sessions/          # CSV session logs
```

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn
- **Twitch:** TwitchIO 3.x (EventSub WebSocket)
- **Spotify:** Spotipy
- **Frontend:** Vanilla JavaScript, CSS
- **Build:** PyInstaller

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - Feel free to use and modify for your stream!

## Acknowledgments

- [Spotipy](https://github.com/spotipy-dev/spotipy) - Spotify API wrapper
- [TwitchIO](https://github.com/TwitchIO/TwitchIO) - Twitch API wrapper
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework

---

Made with love for Twitch streamers
