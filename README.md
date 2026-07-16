# Twitch Song Request System

A complete song request system for Twitch streams with Spotify integration, Channel Points support, and a transparent OBS overlay.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)

## Features

- **Channel Points Integration** - Viewers redeem "SongRedeem" to request songs (with automatic refund attempts on failed requests)
- **Spotify Integration** - Search by song name or paste Spotify track links
- **Anonymous Skip Polls** - A native Twitch poll opens 30s into every requested song; the audience decides Keep/Skip without anyone's vote being visible
- **Smart Skip Thresholds** - Skipping needs a majority AND a minimum vote count; an instant-skip count and landslide percentage end one-sided polls early
- **Queue Position + ETA** - Requesters are told their position and an estimate of when their song will play
- **`!cancel`** - Requesters can cancel their own song (wrong song? changed your mind?) with cooldown reset
- **Music Rats Leaderboard** - `!musicrats` shows the all-time most praised requesters, tracked across streams
- **Song Length Limit** - Requests over a configurable duration (default 5 min) are rejected with a friendly message
- **Silent Voting** - `!like`/`!pass` are counted without chat replies; totals show on the overlay
- **Real-time OBS Overlay** - Compact overlay with album art, progress bar, and vote counts
- **Web Dashboard** - Manage queue, poll settings (with sliders), and blocklist live from your browser
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
| `!like` | Like the current song (silent; credits the requester's Music Rats score) |
| `!pass` | Vote to skip (silent; enough votes bring up the skip poll early) |
| `!queue` or `!q` | View the song request queue |
| `!song` or `!np` | Show the current song |
| `!lastsong` | Show the previously played song |
| `!cancel` | Cancel your own request; resets your cooldown so you can request again |
| `!musicrats` | Top 5 most praised requesters + most liked song (also `!musicrat`, `!ratmusic`; 60s cooldown) |

Viewers request songs by redeeming the Channel Points reward - typing `!request`/`!sr` in chat gets a polite redirect to Channel Points.

### For Moderators & Broadcaster

| Command | Description |
|---------|-------------|
| `!skip`, `!forceskip`, or `!fs` | Force skip the current song |
| `!clearqueue` or `!cq` | Clear the entire queue |
| `!request <song>` or `!sr <song>` | Add a song directly without Channel Points (testing / on-the-fly) |

## Skip Polls

30 seconds into every requested song (configurable), the bot creates a native
Twitch poll: **"Skip: Song?"** with *Keep it / Skip it* choices. Poll votes are
completely anonymous - nobody, including the broadcaster, can see who voted.

The song is skipped only when **both** hold at the poll's end:

- Skip has the **majority**, and
- Skip has at least `POLL_MIN_SKIP_VOTES` votes (quiet polls = song plays on)

Two rules end a decided poll early so bad songs die fast:

- **Instant skip:** Skip reaches `POLL_INSTANT_SKIP_VOTES` (pure count - useful
  because viewers who like a song rarely bother voting Keep)
- **Landslide:** Skip has the minimum votes and `POLL_LANDSLIDE_PERCENT` of all
  votes cast

Polls only ever run for requested songs. The streamer's own playlist never gets
polled; `!pass` votes on playlist songs fall back to the hard `SKIP_THRESHOLD`.
Requires Twitch Affiliate/Partner (`channel:manage:polls` scope - delete
`.twitch_cache` and re-authenticate after upgrading from an older version).

## Settings

Configure via the dashboard (live sliders, no restart) or `.env` file (startup defaults):

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_QUEUE_SIZE` | 10 | Maximum songs in queue |
| `COOLDOWN_SECONDS` | 300 | Cooldown between requests per user (5 min) |
| `MAX_SONG_DURATION_SECONDS` | 300 | Longest allowed request (0 = no limit) |
| `SKIP_THRESHOLD` | 5 | Skip votes for the non-poll fallback skip |
| `CHANNEL_POINTS_COST` | 500 | Cost of song request reward |
| `POLL_ENABLED` | true | Use anonymous Twitch polls to decide skips |
| `POLL_AUTO_START_SECONDS` | 30 | Seconds into a requested song before the poll opens (0 = only `!pass` triggers it) |
| `POLL_DURATION_SECONDS` | 60 | How long the poll runs |
| `POLL_TRIGGER_VOTES` | 2 | `!pass` votes that open the poll early |
| `POLL_MIN_SKIP_VOTES` | 4 | Minimum Skip votes required to actually skip |
| `POLL_INSTANT_SKIP_VOTES` | 6 | Skip count that ends the poll and skips immediately (0 = off) |
| `POLL_LANDSLIDE_PERCENT` | 70 | Skip % that ends the poll early once the minimum is met (0 = off) |
| `MOD_PASS_WEIGHT` | 1 | How many votes a moderator's `!pass` counts for |

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

The `!request`/`!sr` command is available to the broadcaster and mods as a fallback.

### Skip polls not appearing

1. Polls require Twitch **Affiliate or Partner**
2. If upgrading from an older version, delete `.twitch_cache` and re-authenticate
   so the token gains the `channel:manage:polls` scope (the console logs a clear
   error if the scope is missing)
3. Check `POLL_ENABLED=true` and that the playing song is a *request* - playlist
   songs are never polled

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
│   ├── twitch_service.py   # Twitch chat, Channel Points, and polls
│   ├── twitch_auth.py      # Twitch OAuth handling
│   ├── queue_service.py    # Request queue management
│   ├── likes_tracker.py    # Persistent !musicrats leaderboard
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
