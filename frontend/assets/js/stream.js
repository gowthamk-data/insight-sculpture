/**
 * Insight Sculpture - Stream Manager Module
 *
 * This module is responsible ONLY for managing real-time streaming
 * communication between the frontend and backend using Server-Sent Events.
 *
 * Responsibilities:
 * - EventSource lifecycle management
 * - Connection, reconnection, disconnection
 * - SSE event parsing and dispatch
 * - Heartbeat monitoring
 * - Error handling with exponential backoff
 * - Cleanup and resource management
 *
 * Dependencies:
 * - ApiClient from api.js (via window.API.client or window.apiClient)
 *
 * @module stream
 */

// ============================================================
// Constants
// ============================================================

/** @const {number} Default initial retry delay in milliseconds. */
const DEFAULT_RETRY_DELAY_MS = 1000;

/** @const {number} Maximum retry delay in milliseconds (capped at 30s). */
const MAX_RETRY_DELAY_MS = 30000;

/** @const {number} Default maximum number of reconnection attempts. */
const DEFAULT_MAX_RETRIES = 5;

/** @const {number} Default heartbeat timeout in milliseconds (no event for 30s → stale). */
const DEFAULT_HEARTBEAT_TIMEOUT_MS = 30000;

/** @const {number} Backoff multiplier for exponential retry delay. */
const RETRY_BACKOFF_MULTIPLIER = 2;

/** @const {number} Jitter factor added to retry delay (±25%). */
const RETRY_JITTER_FACTOR = 0.25;

// ============================================================
// Stream States
// ============================================================

/**
 * Enum for stream connection states.
 *
 * @readonly
 * @enum {string}
 */
const StreamState = Object.freeze({
    IDLE: 'idle',
    CONNECTING: 'connecting',
    CONNECTED: 'connected',
    RECEIVING: 'receiving',
    COMPLETED: 'completed',
    DISCONNECTED: 'disconnected',
    FAILED: 'failed',
});

// ============================================================
// Stream Manager Class
// ============================================================

class StreamManager {
    /**
     * Create a StreamManager instance.
     *
     * @param {Object} [options] - Configuration options.
     * @param {Object} [options.apiClient] - ApiClient instance. Falls back to window.API.client.
     * @param {number} [options.retryDelayMs=1000] - Initial retry delay in milliseconds.
     * @param {number} [options.maxRetries=5] - Maximum reconnection attempts.
     * @param {number} [options.heartbeatTimeoutMs=30000] - Heartbeat timeout in milliseconds.
     */
    constructor(options = {}) {
        /**
         * ApiClient instance for backend communication.
         * @private
         * @type {Object}
         */
        this._apiClient = options.apiClient || this._resolveApiClient();

        /**
         * Current stream state.
         * @private
         * @type {string}
         */
        this._state = StreamState.IDLE;

        /**
         * Whether the module has been initialized.
         * @private
         * @type {boolean}
         */
        this._initialized = false;

        /**
         * Configuration with defaults.
         * @private
         * @type {Object}
         */
        this._config = {
            retryDelayMs: options.retryDelayMs || DEFAULT_RETRY_DELAY_MS,
            maxRetries: options.maxRetries || DEFAULT_MAX_RETRIES,
            heartbeatTimeoutMs: options.heartbeatTimeoutMs || DEFAULT_HEARTBEAT_TIMEOUT_MS,
        };

        /**
         * Active abort controller for the current stream.
         * @private
         * @type {AbortController|null}
         */
        this._abortController = null;

        /**
         * Current retry attempt count.
         * @private
         * @type {number}
         */
        this._retryCount = 0;

        /**
         * Whether the last disconnect was intentional.
         * @private
         * @type {boolean}
         */
        this._intentionalDisconnect = false;

        /**
         * Heartbeat timer reference.
         * @private
         * @type {number|null}
         */
        this._heartbeatTimer = null;

        /**
         * Timestamp of the last received event.
         * @private
         * @type {number}
         */
        this._lastEventTime = 0;

        /**
         * Current stream session ID.
         * @private
         * @type {string|null}
         */
        this._sessionId = null;

        /**
         * Current stream ID for tracking.
         * @private
         * @type {string|null}
         */
        this._streamId = null;

        /**
         * Last question used for reconnection.
         * @private
         * @type {string|null}
         */
        this._question = null;

        /**
         * Last conversation history used for reconnection.
         * @private
         * @type {Array<Object>|null}
         */
        this._conversationHistory = null;
    }

    // ============================================================
    // Initialization
    // ============================================================

    /**
     * Initialize the stream manager.
     *
     * Prepares the module for streaming but does not connect.
     * Call connect() to start a stream.
     *
     * @returns {StreamManager} This instance for chaining and module storage.
     */
    init() {
        if (this._initialized) {
            console.warn('[Stream] Already initialized, skipping.');
            return this;
        }

        this._setState(StreamState.IDLE);
        this._initialized = true;

        console.log('[Stream] StreamManager initialized');

        return this;
    }

    /**
     * Resolve the ApiClient instance from global scope.
     *
     * @private
     * @returns {Object} ApiClient instance.
     * @throws {Error} If no ApiClient is found.
     */
    _resolveApiClient() {
        if (window.API && window.API.client) {
            return window.API.client;
        }
        if (window.apiClient) {
            return window.apiClient;
        }
        throw new Error(
            '[Stream] ApiClient not found. Ensure api.js is loaded before stream.js.'
        );
    }

    // ============================================================
    // Public API — Connection Lifecycle
    // ============================================================

    /**
     * Start a new stream for analysis.
     *
     * @param {string} sessionId - The active session ID.
     * @param {string} question - The natural language question.
     * @param {Array<Object>} [conversationHistory] - Optional conversation history.
     * @returns {Object} Stream controller with { streamId, disconnect }.
     * @throws {Error} If already connected and not intentionally disconnected.
     */
    connect(sessionId, question, conversationHistory = null) {
        if (!sessionId) {
            throw new Error('Session ID is required to start a stream.');
        }

        if (!question || question.trim().length === 0) {
            throw new Error('Question is required to start a stream.');
        }

        // If already connected, disconnect first
        if (this._state === StreamState.CONNECTED || this._state === StreamState.RECEIVING) {
            this._intentionalDisconnect = true;
            this._cleanupStream();
        }

        // Reset retry state for new connection
        this._retryCount = 0;
        this._intentionalDisconnect = false;
        this._sessionId = sessionId;
        this._question = question;
        this._conversationHistory = conversationHistory;

        this._setState(StreamState.CONNECTING);

        this._dispatchEvent('streamStarted', {
            sessionId: sessionId,
            question: question,
        });

        // Start the stream via ApiClient
        this._initiateStream(sessionId, question, conversationHistory);

        return {
            streamId: this._streamId,
            disconnect: () => this.disconnect(),
            reconnect: () => this.reconnect(sessionId, question, conversationHistory),
        };
    }

    /**
     * Disconnect the current stream intentionally.
     *
     * This will NOT trigger reconnection.
     */
    disconnect() {
        this._intentionalDisconnect = true;
        this._cleanupStream();
        this._setState(StreamState.DISCONNECTED);

        this._dispatchEvent('streamDisconnected', {
            streamId: this._streamId,
            intentional: true,
        });
    }

    /**
     * Attempt to reconnect to the last stream.
     *
     * @param {string} sessionId - The session ID.
     * @param {string} question - The question text.
     * @param {Array<Object>} [conversationHistory] - Optional conversation history.
     */
    reconnect(sessionId, question, conversationHistory = null) {
        this._intentionalDisconnect = false;
        this._retryCount = 0;

        this._initiateStream(sessionId, question, conversationHistory);
    }

    /**
     * Check if the stream is currently connected.
     *
     * @returns {boolean} True if in CONNECTED or RECEIVING state.
     */
    isConnected() {
        return (
            this._state === StreamState.CONNECTED ||
            this._state === StreamState.RECEIVING
        );
    }

    /**
     * Get the current stream state.
     *
     * @returns {string} Current StreamState value.
     */
    getState() {
        return this._state;
    }

    /**
     * Get the current stream ID.
     *
     * @returns {string|null} Stream ID or null if no active stream.
     */
    getStreamId() {
        return this._streamId;
    }

    // ============================================================
    // Stream Initiation
    // ============================================================

    /**
     * Initiate a stream via ApiClient.
     *
     * @param {string} sessionId - The session ID.
     * @param {string} question - The question text.
     * @param {Array<Object>|null} conversationHistory - Optional history.
     * @private
     */
    _initiateStream(sessionId, question, conversationHistory) {
        this._streamId = `stream_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

        this._setState(StreamState.CONNECTING);

        // Notify app.js of stream status
        this._dispatchEvent('stream:status', { status: 'connecting' });

        // Use ApiClient.streamAnalysis() which handles SSE via fetch
        const streamController = this._apiClient.streamAnalysis(
            sessionId,
            question,
            conversationHistory || null,
            {
                onOpen: () => this._handleStreamOpen(),
                onMessage: (event) => this._handleStreamEvent(event),
                onError: (error) => this._handleStreamError(error),
                onClose: () => this._handleStreamClose(),
            }
        );

        // Store the stream controller for disconnect
        this._streamController = streamController;
    }

    // ============================================================
    // Event Handlers
    // ============================================================

    /**
     * Handle stream open event.
     *
     * @private
     */
    _handleStreamOpen() {
        this._setState(StreamState.CONNECTED);
        this._retryCount = 0;
        this._lastEventTime = Date.now();
        this._startHeartbeat();

        this._dispatchEvent('streamConnected', {
            streamId: this._streamId,
        });

        this._dispatchEvent('stream:status', { status: 'connected' });
    }

    /**
     * Handle an incoming SSE event from the stream.
     *
     * @param {Object} sseEvent - Parsed SSE event from ApiClient.
     * @param {string} sseEvent.event - The event type name.
     * @param {*} sseEvent.data - The parsed event data.
     * @private
     */
    _handleStreamEvent(sseEvent) {
        // Update heartbeat
        this._lastEventTime = Date.now();

        const eventName = sseEvent.event || 'message';
        const data = sseEvent.data;

        // Set state to receiving on first data event
        if (this._state === StreamState.CONNECTED) {
            this._setState(StreamState.RECEIVING);
        }

        switch (eventName) {
            case 'connected':
                this._handleConnectedEvent(data);
                break;

            case 'planning_started':
                this._dispatchEvent('streamProgress', {
                    stage: 'planning',
                    status: 'started',
                    message: 'Analyzing your question...',
                });
                break;

            case 'planning_completed':
                this._dispatchEvent('streamProgress', {
                    stage: 'planning',
                    status: 'completed',
                    operation: data && data.operation,
                    chartType: data && data.chart_type,
                });
                break;

            case 'execution_started':
                this._dispatchEvent('streamProgress', {
                    stage: 'execution',
                    status: 'started',
                    message: 'Running analysis on your data...',
                    operation: data && data.operation,
                });
                break;

            case 'execution_completed':
                this._dispatchEvent('streamProgress', {
                    stage: 'execution',
                    status: 'completed',
                    rowsReturned: data && data.rows_returned,
                    columnsReturned: data && data.columns_returned,
                    executionTimeMs: data && data.execution_time_ms,
                });
                break;

            case 'chart_started':
                this._dispatchEvent('streamChart', {
                    status: 'generating',
                    chartType: data && data.chart_type,
                });
                break;

            case 'chart_completed':
                this._dispatchEvent('streamChart', {
                    status: 'completed',
                    chartGenerated: data && data.chart_generated,
                    chartData: data && data.chart_data,
                });
                break;

            case 'explanation_started':
                this._dispatchEvent('streamProgress', {
                    stage: 'explanation',
                    status: 'started',
                    message: 'Generating explanation...',
                });
                break;

            case 'token':
                this._handleTokenEvent(data);
                break;

            case 'completed':
                this._handleCompletedEvent(data);
                break;

            case 'error':
                this._handleErrorEvent(data);
                break;

            default:
                // Ignore unknown events gracefully
                if (eventName !== 'message') {
                    console.debug('[Stream] Unknown event type:', eventName);
                }
                break;
        }
    }

    /**
     * Handle stream error.
     *
     * @param {Error} error - The error from the stream.
     * @private
     */
    _handleStreamError(error) {
        console.error('[Stream] Stream error:', error && error.message);

        this._stopHeartbeat();

        if (this._intentionalDisconnect) {
            return;
        }

        this._dispatchEvent('streamError', {
            streamId: this._streamId,
            error: error,
            friendlyMessage: this._getFriendlyErrorMessage(error),
            retryAttempt: this._retryCount,
        });

        this._attemptReconnection();
    }

    /**
     * Handle stream close.
     *
     * @private
     */
    _handleStreamClose() {
        this._stopHeartbeat();

        if (this._intentionalDisconnect) {
            this._setState(StreamState.DISCONNECTED);
            this._dispatchEvent('streamDisconnected', {
                streamId: this._streamId,
                intentional: true,
            });
            return;
        }

        // Unexpected close — attempt reconnection
        this._dispatchEvent('streamDisconnected', {
            streamId: this._streamId,
            intentional: false,
        });

        this._attemptReconnection();
    }

    // ============================================================
    // Event Type Handlers
    // ============================================================

    /**
     * Handle 'connected' event from the backend.
     *
     * @param {Object} data - Event data.
     * @private
     */
    _handleConnectedEvent(data) {
        this._dispatchEvent('streamConnected', {
            streamId: this._streamId,
            sessionId: data && data.session_id,
        });
    }

    /**
     * Handle 'token' event from the backend (streamed text chunk).
     *
     * @param {Object} data - Event data with { token }.
     * @private
     */
    _handleTokenEvent(data) {
        const token = data && data.token;

        if (typeof token !== 'string') {
            return;
        }

        this._dispatchEvent('streamToken', {
            streamId: this._streamId,
            token: token,
        });
    }

    /**
     * Handle 'completed' event from the backend.
     *
     * @param {Object} data - Completion event data.
     * @private
     */
    _handleCompletedEvent(data) {
        this._stopHeartbeat();
        this._setState(StreamState.COMPLETED);

        this._dispatchEvent('streamCompleted', {
            streamId: this._streamId,
            explanation: data && data.explanation,
            rowsReturned: data && data.rows_returned,
            columnsReturned: data && data.columns_returned,
            chartGenerated: data && data.chart_generated,
            processingTimestamp: data && data.processing_timestamp,
        });

        this._dispatchEvent('stream:status', { status: 'completed' });
    }

    /**
     * Handle 'error' event from the backend (server-side error).
     *
     * @param {Object} data - Error event data.
     * @private
     */
    _handleErrorEvent(data) {
        const message = (data && data.message) || 'An error occurred during analysis.';

        this._setState(StreamState.FAILED);

        this._dispatchEvent('streamError', {
            streamId: this._streamId,
            error: new Error(message),
            friendlyMessage: message,
            fromServer: true,
        });
    }

    // ============================================================
    // Reconnection Logic
    // ============================================================

    /**
     * Attempt to reconnect with exponential backoff.
     *
     * @private
     */
    _attemptReconnection() {
        if (this._intentionalDisconnect) {
            return;
        }

        this._retryCount += 1;

        if (this._retryCount > this._config.maxRetries) {
            this._setState(StreamState.FAILED);

            this._dispatchEvent('streamError', {
                streamId: this._streamId,
                error: new Error('Max reconnection attempts reached.'),
                friendlyMessage:
                    'Unable to maintain a connection to the server. Please try again later.',
                retryAttempt: this._retryCount - 1,
                maxRetries: this._config.maxRetries,
                final: true,
            });

            this._dispatchEvent('stream:status', { status: 'failed' });

            return;
        }

        const delay = this._calculateRetryDelay();

        this._setState(StreamState.CONNECTING);

        this._dispatchEvent('streamProgress', {
            stage: 'reconnection',
            status: 'attempting',
            retryAttempt: this._retryCount,
            maxRetries: this._config.maxRetries,
            delayMs: delay,
            message: `Reconnecting (attempt ${this._retryCount}/${this._config.maxRetries})...`,
        });

        console.log(
            `[Stream] Reconnecting in ${delay}ms (attempt ${this._retryCount}/${this._config.maxRetries})`
        );

        setTimeout(() => {
            if (!this._intentionalDisconnect && this._sessionId && this._question) {
                this._initiateStream(
                    this._sessionId,
                    this._question,
                    this._conversationHistory
                );
            }
        }, delay);
    }

    /**
     * Calculate retry delay with exponential backoff and jitter.
     *
     * @returns {number} Delay in milliseconds.
     * @private
     */
    _calculateRetryDelay() {
        const exponentialDelay = this._config.retryDelayMs *
            Math.pow(RETRY_BACKOFF_MULTIPLIER, this._retryCount - 1);

        const cappedDelay = Math.min(exponentialDelay, MAX_RETRY_DELAY_MS);

        // Add jitter: ±25%
        const jitter = cappedDelay * RETRY_JITTER_FACTOR;
        const jitteredDelay = cappedDelay + (Math.random() * jitter * 2 - jitter);

        return Math.round(jitteredDelay);
    }

    // ============================================================
    // Heartbeat
    // ============================================================

    /**
     * Start the heartbeat timer to detect stale connections.
     *
     * @private
     */
    _startHeartbeat() {
        this._stopHeartbeat();
        this._lastEventTime = Date.now();

        this._heartbeatTimer = setInterval(() => {
            const elapsed = Date.now() - this._lastEventTime;

            if (elapsed > this._config.heartbeatTimeoutMs) {
                console.warn(
                    `[Stream] Heartbeat timeout: no event for ${elapsed}ms`
                );

                this._dispatchEvent('streamError', {
                    streamId: this._streamId,
                    error: new Error('Connection timed out.'),
                    friendlyMessage:
                        'The connection timed out. Please try again.',
                    heartbeatTimeout: true,
                });

                this._cleanupStream();

                this._attemptReconnection();
            }
        }, Math.min(this._config.heartbeatTimeoutMs / 2, 15000));
    }

    /**
     * Stop the heartbeat timer.
     *
     * @private
     */
    _stopHeartbeat() {
        if (this._heartbeatTimer !== null) {
            clearInterval(this._heartbeatTimer);
            this._heartbeatTimer = null;
        }
    }

    // ============================================================
    // Cleanup
    // ============================================================

    /**
     * Clean up the current stream and abort any pending requests.
     *
     * @private
     */
    _cleanupStream() {
        this._stopHeartbeat();

        if (this._streamController && typeof this._streamController.disconnect === 'function') {
            try {
                this._streamController.disconnect();
            } catch (e) {
                // Ignore cleanup errors
            }
        }

        this._streamController = null;
    }

    // ============================================================
    // Error Handling
    // ============================================================

    /**
     * Convert an error to a user-friendly message.
     *
     * @param {Error} error - The original error.
     * @returns {string} User-friendly error message.
     * @private
     */
    _getFriendlyErrorMessage(error) {
        if (!error) {
            return 'An unexpected error occurred during streaming.';
        }

        const code = error.code || error.name || '';
        const message = error.message || String(error);

        // ApiClient error classes
        if (code === 'NETWORK_ERROR') {
            return 'Connection lost. Please check your network.';
        }
        if (code === 'TIMEOUT_ERROR') {
            return 'The analysis is taking longer than expected. Please try again.';
        }
        if (code === 'ABORT_ERROR') {
            return 'The stream was interrupted.';
        }

        // Check for specific message patterns
        if (message.includes('Session not found')) {
            return 'Your session has expired. Please upload the dataset again.';
        }
        if (message.includes('rate limit') || message.includes('RateLimit')) {
            return 'Too many requests. Please wait a moment before trying again.';
        }
        if (message.includes('authentication') || message.includes('Authentication')) {
            return 'Server authentication failed. Please contact support.';
        }

        // Generic fallback
        return 'An error occurred during streaming. Please try again.';
    }

    // ============================================================
    // State Management
    // ============================================================

    /**
     * Set the current stream state.
     *
     * @param {string} newState - One of StreamState values.
     * @private
     */
    _setState(newState) {
        const previousState = this._state;
        this._state = newState;

        this._dispatchEvent('stream:stateChanged', {
            previousState: previousState,
            currentState: newState,
        });
    }

    // ============================================================
    // Event Dispatch
    // ============================================================

    /**
     * Dispatch a custom event on the document.
     *
     * @param {string} eventName - The event name.
     * @param {Object} detail - Event detail payload.
     * @private
     */
    _dispatchEvent(eventName, detail) {
        const event = new CustomEvent(eventName, {
            bubbles: true,
            cancelable: true,
            detail: detail,
        });
        document.dispatchEvent(event);
    }

    // ============================================================
    // Public API — Cleanup & Destroy
    // ============================================================

    /**
     * Clean up all resources.
     *
     * Disconnects any active stream, stops heartbeat, and
     * resets state. Safe to call multiple times.
     */
    cleanup() {
        this._intentionalDisconnect = true;
        this._cleanupStream();
        this._stopHeartbeat();

        this._streamId = null;
        this._sessionId = null;
        this._question = null;
        this._conversationHistory = null;
        this._retryCount = 0;
        this._streamController = null;

        this._setState(StreamState.DISCONNECTED);

        this._dispatchEvent('streamDisconnected', {
            streamId: this._streamId,
            intentional: true,
        });
    }

    /**
     * Remove event listeners and clean up resources.
     *
     * Called by app.js during shutdown.
     */
    destroy() {
        this.cleanup();
        this._initialized = false;

        console.log('[Stream] StreamManager destroyed');
    }
}

// ============================================================
// Initialization Function
// ============================================================

/**
 * Initialize the streaming module.
 *
 * Creates a StreamManager instance, initializes it, and returns it
 * for storage by the application module (app.js).
 *
 * The function is exposed on window for discovery by app.js,
 * which checks for `typeof window.initializeStream === 'function'`.
 *
 * @async
 * @param {Object} [config] - Optional configuration.
 * @param {Object} [config.apiClient] - ApiClient instance.
 * @param {number} [config.retryDelayMs=1000] - Initial retry delay.
 * @param {number} [config.maxRetries=5] - Maximum reconnection attempts.
 * @param {number} [config.heartbeatTimeoutMs=30000] - Heartbeat timeout.
 * @returns {Promise<StreamManager>} The initialized StreamManager instance.
 */
async function initializeStreaming(config = {}) {
    const manager = new StreamManager(config);
    manager.init();
    return manager;
}

// ============================================================
// Global Exports
// ============================================================

// Expose for app.js initialization discovery
window.initializeStream = initializeStreaming;

// Expose StreamManager class for testing and direct access
window.StreamManager = StreamManager;

console.log('[Stream] Stream module loaded');