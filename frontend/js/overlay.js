/**
 * Overlay Controller
 * Manages UI updates based on WebSocket events
 */

class OverlayController {
    constructor() {
        this.elements = {
            container: document.getElementById('overlay-container'),
            nowPlaying: document.getElementById('now-playing'),
            albumArt: document.getElementById('album-art'),
            songTitle: document.getElementById('song-title'),
            artistName: document.getElementById('artist-name'),
            requester: document.getElementById('requester'),
            requesterName: document.getElementById('requester-name'),
            progressFill: document.getElementById('progress-fill'),
            timeCurrent: document.getElementById('time-current'),
            timeRemaining: document.getElementById('time-remaining'),
            votes: document.getElementById('votes'),
            likeCount: document.getElementById('like-count'),
            skipCount: document.getElementById('skip-count'),
            upNext: document.getElementById('up-next'),
            nextSongTitle: document.getElementById('next-song-title'),
            nextArtist: document.getElementById('next-artist'),
            nextRequester: document.getElementById('next-requester'),
            playButton: document.querySelector('.play-button'),
        };

        this.currentSong = null;
        this.progressInterval = null;
        this.currentProgress = 0;
        this.duration = 0;

        // Default album art placeholder
        this.placeholderArt = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Crect fill='%23333' width='120' height='120'/%3E%3Ctext x='50%25' y='50%25' fill='%23666' font-size='40' text-anchor='middle' dy='.35em'%3E%E2%99%AA%3C/text%3E%3C/svg%3E";

        this.bindEvents();
    }

    bindEvents() {
        const ws = window.songRequestWS;

        ws.on('song_change', (data) => this.handleSongChange(data));
        ws.on('queue_update', (data) => this.handleQueueUpdate(data));
        ws.on('vote_update', (data) => this.handleVoteUpdate(data));
        ws.on('playback_progress', (data) => this.handleProgress(data));
        ws.on('connected', () => this.onConnected());
        ws.on('disconnected', () => this.onDisconnected());
    }

    handleSongChange(data) {
        // Animate transition
        this.animateSongTransition(() => {
            this.currentSong = data;

            // Update state class
            if (data.is_request) {
                this.elements.container.className = 'state-active-request';
            } else {
                this.elements.container.className = 'state-no-requests';
            }

            // Update album art
            if (data.album_art_url) {
                this.elements.albumArt.src = data.album_art_url;
            } else {
                this.elements.albumArt.src = this.placeholderArt;
            }

            // Update text
            this.elements.songTitle.textContent = data.title || 'No Song Playing';
            this.elements.artistName.textContent = data.artist || '-';

            // Update requester
            if (data.requester) {
                this.elements.requesterName.textContent = data.requester;
            }

            // Update votes
            this.elements.likeCount.textContent = data.likes || 0;
            this.elements.skipCount.textContent = data.skips || 0;

            // Start progress tracking
            this.duration = data.duration_ms || 0;
            this.currentProgress = data.progress_ms || 0;
            this.startProgressTracking();
        });
    }

    handleQueueUpdate(data) {
        const queue = data.queue || [];
        const nextSong = data.next_song;

        if (nextSong || queue.length > 0) {
            const next = nextSong || queue[0];
            this.elements.nextSongTitle.textContent = next.title || '-';
            this.elements.nextArtist.textContent = next.artist || '-';
            this.elements.nextRequester.textContent = next.requester ? `by ${next.requester}` : '';
            this.elements.upNext.classList.remove('hidden');
        } else {
            this.elements.upNext.classList.add('hidden');
        }
    }

    handleVoteUpdate(data) {
        const prevLikes = parseInt(this.elements.likeCount.textContent) || 0;
        const prevSkips = parseInt(this.elements.skipCount.textContent) || 0;

        const newLikes = data.likes || 0;
        const newSkips = data.skips || 0;

        // Update counts
        this.elements.likeCount.textContent = newLikes;
        this.elements.skipCount.textContent = newSkips;

        // Animate if changed
        if (newLikes !== prevLikes) {
            this.animateVoteChange(this.elements.likeCount);
        }
        if (newSkips !== prevSkips) {
            this.animateVoteChange(this.elements.skipCount);
        }

        // Pulse album art on any vote
        if (newLikes !== prevLikes || newSkips !== prevSkips) {
            this.pulseAlbumArt();
        }
    }

    handleProgress(data) {
        this.currentProgress = data.progress_ms || 0;
        this.duration = data.duration_ms || this.duration;
        this.updateProgressBar();
    }

    animateSongTransition(callback) {
        // Exit animation
        this.elements.nowPlaying.classList.add('exiting');

        setTimeout(() => {
            this.elements.nowPlaying.classList.remove('exiting');

            // Execute the update
            callback();

            // Enter animation
            this.elements.nowPlaying.classList.add('entering');
            setTimeout(() => {
                this.elements.nowPlaying.classList.remove('entering');
            }, 600);

        }, 400);
    }

    animateVoteChange(element) {
        element.classList.add('pop');
        setTimeout(() => {
            element.classList.remove('pop');
        }, 300);
    }

    pulseAlbumArt() {
        this.elements.albumArt.classList.add('pulse');
        setTimeout(() => {
            this.elements.albumArt.classList.remove('pulse');
        }, 300);
    }

    startProgressTracking() {
        // Clear existing interval
        if (this.progressInterval) {
            clearInterval(this.progressInterval);
        }

        this.updateProgressBar();

        // Update every second
        this.progressInterval = setInterval(() => {
            this.currentProgress += 1000;
            if (this.currentProgress >= this.duration) {
                this.currentProgress = this.duration;
            }
            this.updateProgressBar();
        }, 1000);
    }

    updateProgressBar() {
        if (this.duration <= 0) {
            this.elements.progressFill.style.width = '0%';
            this.elements.timeCurrent.textContent = '0:00';
            this.elements.timeRemaining.textContent = '0:00';
            return;
        }

        const percent = Math.min((this.currentProgress / this.duration) * 100, 100);
        this.elements.progressFill.style.width = `${percent}%`;

        // Update current time (left side)
        this.elements.timeCurrent.textContent = this.formatTime(this.currentProgress);

        // Update remaining time (right side)
        const remaining = Math.max(0, this.duration - this.currentProgress);
        this.elements.timeRemaining.textContent = this.formatTime(remaining);
    }

    formatTime(ms) {
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }

    onConnected() {
        console.log('Overlay connected to backend');
        this.elements.container.classList.remove('state-disconnected');
        this.loadInitialData();
    }

    async loadInitialData() {
        try {
            // Fetch current song and queue data
            const [currentSong, queueData] = await Promise.all([
                fetch('/api/current').then(r => r.json()),
                fetch('/api/queue').then(r => r.json()),
            ]);

            // Update current song display
            if (currentSong && currentSong.playing !== false) {
                this.handleSongChange({
                    title: currentSong.title,
                    artist: currentSong.artist,
                    album_art_url: currentSong.album_art_url,
                    requester: currentSong.requester,
                    is_request: currentSong.is_request,
                    likes: currentSong.likes || 0,
                    skips: currentSong.skips || 0,
                    duration_ms: currentSong.duration_ms || 0,
                    progress_ms: currentSong.progress_ms || 0,
                });
            }

            // Update queue/up next display
            if (queueData) {
                this.handleQueueUpdate({
                    queue: queueData.queue || [],
                    next_song: queueData.next_song,
                });
            }
        } catch (e) {
            console.error('Failed to load initial data:', e);
        }
    }

    onDisconnected() {
        console.log('Overlay disconnected from backend');
        this.elements.container.classList.add('state-disconnected');
        this.elements.songTitle.textContent = 'Connecting...';
        this.elements.artistName.textContent = '-';

        // Stop progress updates
        if (this.progressInterval) {
            clearInterval(this.progressInterval);
        }
    }
}

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    window.overlayController = new OverlayController();
});
