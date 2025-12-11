/**
 * Dashboard Controller
 * Manages the admin interface for queue and settings
 */

class DashboardController {
    constructor() {
        this.apiBase = '/api';

        this.elements = {
            connectionStatus: document.getElementById('connection-status'),
            statusText: document.querySelector('.status-text'),
            nowPlayingCard: document.getElementById('now-playing-card'),
            songTitle: document.getElementById('dash-song-title'),
            artist: document.getElementById('dash-artist'),
            requester: document.getElementById('dash-requester'),
            likes: document.getElementById('dash-likes'),
            skips: document.getElementById('dash-skips'),
            skipBtn: document.getElementById('skip-btn'),
            queueList: document.getElementById('queue-list'),
            queueCount: document.getElementById('queue-count'),
            clearQueueBtn: document.getElementById('clear-queue-btn'),
            settingsForm: document.getElementById('settings-form'),
            skipThreshold: document.getElementById('skip-threshold'),
            requestCooldown: document.getElementById('request-cooldown'),
            maxQueueSize: document.getElementById('max-queue-size'),
            blocklistInput: document.getElementById('blocklist-input'),
            addBlocklistBtn: document.getElementById('add-blocklist-btn'),
            blocklist: document.getElementById('blocklist'),
        };

        // Placeholder album art
        this.placeholderArt = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80' viewBox='0 0 80 80'%3E%3Crect fill='%231a1a2e' width='80' height='80' rx='8'/%3E%3Ctext x='50%25' y='50%25' fill='%23666' font-size='30' text-anchor='middle' dy='.35em'%3E%E2%99%AA%3C/text%3E%3C/svg%3E";

        this.bindEvents();
        this.loadInitialData();
    }

    bindEvents() {
        const ws = window.songRequestWS;

        // WebSocket events
        ws.on('connected', () => {
            this.updateConnectionStatus(true);
            this.loadInitialData();  // Reload data when WebSocket connects
        });
        ws.on('disconnected', () => this.updateConnectionStatus(false));
        ws.on('song_change', (data) => this.updateNowPlaying(data));
        ws.on('queue_update', (data) => this.updateQueue(data.queue || []));
        ws.on('vote_update', (data) => this.updateVotes(data));

        // UI events
        this.elements.skipBtn.addEventListener('click', () => this.skipSong());
        this.elements.clearQueueBtn.addEventListener('click', () => this.clearQueue());
        this.elements.settingsForm.addEventListener('submit', (e) => this.saveSettings(e));
        this.elements.addBlocklistBtn.addEventListener('click', () => this.addToBlocklist());

        // Enter key for blocklist input
        this.elements.blocklistInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.addToBlocklist();
            }
        });
    }

    async loadInitialData() {
        try {
            const [queueData, currentSong, settings, blocklist] = await Promise.all([
                this.apiGet('/queue'),
                this.apiGet('/current'),
                this.apiGet('/settings'),
                this.apiGet('/blocklist'),
            ]);

            // Update queue
            if (queueData.queue) {
                this.updateQueue(queueData.queue);
            }

            // Update now playing - prefer current_request from queue, fallback to current endpoint
            if (queueData.current_request) {
                this.updateNowPlaying({
                    ...queueData.current_request.song,
                    requester: queueData.current_request.requester,
                    likes: queueData.current_request.likes || 0,
                    skips: queueData.current_request.skips || 0,
                    is_request: true,
                });
            } else if (currentSong && currentSong.playing) {
                this.updateNowPlaying(currentSong);
            }

            // Update settings form
            if (settings) {
                this.updateSettingsForm(settings);
            }

            // Update blocklist
            if (blocklist) {
                this.updateBlocklist(blocklist);
            }

        } catch (e) {
            console.error('Failed to load initial data:', e);
            this.showAlert('Failed to load data. Is the server running?', 'error');
        }
    }

    async apiGet(endpoint) {
        const response = await fetch(`${this.apiBase}${endpoint}`);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    }

    async apiPost(endpoint, data = {}) {
        const response = await fetch(`${this.apiBase}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    }

    async apiPatch(endpoint, data) {
        const response = await fetch(`${this.apiBase}${endpoint}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    }

    async apiDelete(endpoint) {
        const response = await fetch(`${this.apiBase}${endpoint}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    }

    updateConnectionStatus(connected) {
        this.elements.connectionStatus.className = `status ${connected ? 'connected' : ''}`;
        this.elements.statusText.textContent = connected ? 'Connected' : 'Disconnected';
    }

    updateNowPlaying(data) {
        // Update album art
        const existingImg = this.elements.nowPlayingCard.querySelector('img');
        const existingPlaceholder = this.elements.nowPlayingCard.querySelector('.placeholder-art');

        if (data.album_art_url) {
            if (existingPlaceholder) {
                const img = document.createElement('img');
                img.src = data.album_art_url;
                img.alt = 'Album art';
                existingPlaceholder.replaceWith(img);
            } else if (existingImg) {
                existingImg.src = data.album_art_url;
            }
        }

        // Update text
        this.elements.songTitle.textContent = data.title || 'No song playing';
        this.elements.artist.textContent = data.artist || '-';

        if (data.is_request && data.requester) {
            this.elements.requester.textContent = `Requested by ${data.requester}`;
            this.elements.requester.style.display = 'block';
        } else {
            this.elements.requester.style.display = 'none';
        }
    }

    updateVotes(data) {
        this.elements.likes.textContent = data.likes || 0;
        this.elements.skips.textContent = data.skips || 0;
    }

    updateQueue(queue) {
        this.elements.queueCount.textContent = queue.length;

        if (queue.length === 0) {
            this.elements.queueList.innerHTML = `
                <div class="queue-empty-message">No songs in queue</div>
            `;
            return;
        }

        this.elements.queueList.innerHTML = queue.map((item, index) => `
            <div class="queue-item" data-id="${item.spotify_id}">
                <span class="position">${index + 1}</span>
                <img src="${item.album_art_url || this.placeholderArt}" alt="Album">
                <div class="queue-item-info">
                    <div class="title">${this.escapeHtml(item.title)}</div>
                    <div class="artist">${this.escapeHtml(item.artist)}</div>
                    <div class="requester">${this.escapeHtml(item.requester)}</div>
                </div>
                <button class="btn-icon" onclick="dashboard.removeFromQueue(${index})" title="Remove">×</button>
            </div>
        `).join('');
    }

    updateSettingsForm(settings) {
        this.elements.skipThreshold.value = settings.skip_threshold || 5;
        this.elements.requestCooldown.value = settings.cooldown_seconds || 300;
        this.elements.maxQueueSize.value = settings.max_queue_size || 10;
    }

    updateBlocklist(blocklist) {
        const artists = blocklist.blocklist_artists || [];
        const songs = blocklist.blocklist_song_ids || [];
        const allItems = [...artists.map(a => ({ value: a, type: 'artist' })),
                         ...songs.map(s => ({ value: s, type: 'song' }))];

        if (allItems.length === 0) {
            this.elements.blocklist.innerHTML = `
                <li style="color: var(--text-muted); font-style: italic;">
                    No items blocked
                </li>
            `;
            return;
        }

        this.elements.blocklist.innerHTML = allItems.map(item => `
            <li>
                <span>${this.escapeHtml(item.value)} <small style="color: var(--text-muted);">(${item.type})</small></span>
                <button class="btn-icon" onclick="dashboard.removeFromBlocklist('${this.escapeHtml(item.value)}')" title="Remove">×</button>
            </li>
        `).join('');
    }

    async skipSong() {
        try {
            await this.apiPost('/skip');
            this.showAlert('Song skipped!', 'success');
        } catch (e) {
            console.error('Skip failed:', e);
            this.showAlert('Failed to skip song', 'error');
        }
    }

    async clearQueue() {
        if (!confirm('Clear all songs from the queue?')) {
            return;
        }

        try {
            const result = await this.apiDelete('/queue');
            this.showAlert(`Queue cleared (${result.removed_count} songs removed)`, 'success');
            this.updateQueue([]);
        } catch (e) {
            console.error('Clear queue failed:', e);
            this.showAlert('Failed to clear queue', 'error');
        }
    }

    async removeFromQueue(index) {
        try {
            await this.apiDelete(`/queue/${index}`);
            // Queue will update via WebSocket
        } catch (e) {
            console.error('Remove failed:', e);
            this.showAlert('Failed to remove song', 'error');
        }
    }

    async saveSettings(e) {
        e.preventDefault();

        try {
            const settings = {
                skip_threshold: parseInt(this.elements.skipThreshold.value),
                cooldown_seconds: parseInt(this.elements.requestCooldown.value),
                max_queue_size: parseInt(this.elements.maxQueueSize.value),
            };

            await this.apiPatch('/settings', settings);
            this.showAlert('Settings saved!', 'success');
        } catch (e) {
            console.error('Save settings failed:', e);
            this.showAlert('Failed to save settings', 'error');
        }
    }

    async addToBlocklist() {
        const value = this.elements.blocklistInput.value.trim();
        if (!value) return;

        // Determine if it's a Spotify ID (looks like a track ID) or artist name
        const isSpotifyId = /^[a-zA-Z0-9]{22}$/.test(value);

        try {
            await this.apiPost('/blocklist', {
                item: value,
                is_artist: !isSpotifyId,
            });

            this.elements.blocklistInput.value = '';
            this.showAlert(`Added "${value}" to blocklist`, 'success');

            // Reload blocklist
            const blocklist = await this.apiGet('/blocklist');
            this.updateBlocklist(blocklist);
        } catch (e) {
            console.error('Add to blocklist failed:', e);
            this.showAlert('Failed to add to blocklist', 'error');
        }
    }

    async removeFromBlocklist(item) {
        try {
            await this.apiDelete(`/blocklist/${encodeURIComponent(item)}`);

            // Reload blocklist
            const blocklist = await this.apiGet('/blocklist');
            this.updateBlocklist(blocklist);
        } catch (e) {
            console.error('Remove from blocklist failed:', e);
            this.showAlert('Failed to remove from blocklist', 'error');
        }
    }

    showAlert(message, type = 'success') {
        // Remove existing alerts
        document.querySelectorAll('.alert').forEach(a => a.remove());

        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.textContent = message;

        const header = document.querySelector('.header');
        header.insertAdjacentElement('afterend', alert);

        // Auto-remove after 3 seconds
        setTimeout(() => {
            alert.remove();
        }, 3000);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new DashboardController();
});
