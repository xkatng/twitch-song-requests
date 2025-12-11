/**
 * WebSocket Connection Manager
 * Handles connection, reconnection, and event dispatching
 * Shared between overlay and dashboard
 */

class SongRequestWebSocket {
    constructor(url = null) {
        // Auto-detect URL based on current page
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host || 'localhost:5174';
        this.url = url || `${protocol}//${host}/api/ws`;

        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.eventHandlers = {};
        this.isConnected = false;
        this.pingInterval = null;

        this.connect();
    }

    connect() {
        try {
            console.log('[WS] Connecting to:', this.url);
            this.ws = new WebSocket(this.url);

            this.ws.onopen = () => {
                console.log('[WS] Connected to server');
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.startPing();
                this.emit('connected', {});
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (e) {
                    console.error('[WS] Failed to parse message:', e);
                }
            };

            this.ws.onclose = (event) => {
                console.log('[WS] Connection closed:', event.code, event.reason);
                this.isConnected = false;
                this.stopPing();
                this.emit('disconnected', {});
                this.attemptReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('[WS] Error:', error);
                this.emit('error', { error });
            };

        } catch (e) {
            console.error('[WS] Connection failed:', e);
            this.attemptReconnect();
        }
    }

    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = Math.min(
                this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1),
                30000
            );
            console.log(`[WS] Reconnecting in ${Math.round(delay/1000)}s (attempt ${this.reconnectAttempts})`);
            setTimeout(() => this.connect(), delay);
        } else {
            console.error('[WS] Max reconnection attempts reached');
            this.emit('maxReconnectFailed', {});
        }
    }

    handleMessage(data) {
        const eventType = data.event_type;
        if (eventType) {
            console.log(`[WS] Received: ${eventType}`, data);
            this.emit(eventType, data);
        }
    }

    on(eventType, handler) {
        if (!this.eventHandlers[eventType]) {
            this.eventHandlers[eventType] = [];
        }
        this.eventHandlers[eventType].push(handler);
        return this; // Allow chaining
    }

    off(eventType, handler) {
        if (this.eventHandlers[eventType]) {
            this.eventHandlers[eventType] = this.eventHandlers[eventType]
                .filter(h => h !== handler);
        }
        return this;
    }

    emit(eventType, payload) {
        const handlers = this.eventHandlers[eventType] || [];
        handlers.forEach(handler => {
            try {
                handler(payload);
            } catch (e) {
                console.error(`[WS] Handler error for ${eventType}:`, e);
            }
        });

        // Also emit to 'all' handlers
        const allHandlers = this.eventHandlers['*'] || [];
        allHandlers.forEach(handler => {
            try {
                handler(eventType, payload);
            } catch (e) {
                console.error(`[WS] All-handler error:`, e);
            }
        });
    }

    send(type, payload = {}) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, ...payload }));
            return true;
        } else {
            console.warn('[WS] Cannot send - not connected');
            return false;
        }
    }

    startPing() {
        this.stopPing();
        this.pingInterval = setInterval(() => {
            if (this.isConnected) {
                this.send('ping');
            }
        }, 30000); // Ping every 30 seconds
    }

    stopPing() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    close() {
        this.stopPing();
        if (this.ws) {
            this.ws.close();
        }
    }
}

// Create global instance
window.songRequestWS = new SongRequestWebSocket();
