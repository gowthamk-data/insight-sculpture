/**
 * Insight Sculpture - API Client Module
 * 
 * This module is responsible for all HTTP communication with the backend.
 * It provides a clean interface for uploading datasets, analyzing data,
 * and streaming analysis results via Server-Sent Events.
 * 
 * Responsibilities:
 * - HTTP request handling (upload, analyze, stream, health)
 * - Server-Sent Events (SSE) streaming
 * - Error handling and retry logic
 * - Request cancellation and timeout management
 * - Event emission for request lifecycle
 * 
 * @module api
 */

// ============================================================
// Custom Error Classes
// ============================================================

/**
 * Base API error class.
 * All API errors extend this class.
 * 
 * @class ApiError
 * @extends Error
 */
class ApiError extends Error {
    /**
     * Create an API error.
     * 
     * @param {string} message - Human-readable error message
     * @param {string} code - Error code for programmatic handling
     * @param {number} [statusCode] - HTTP status code if applicable
     * @param {Object} [details] - Additional error details
     */
    constructor(message, code, statusCode = null, details = null) {
        super(message);
        this.name = 'ApiError';
        this.code = code;
        this.statusCode = statusCode;
        this.details = details;
    }
}

/**
 * Network error (connection failure, timeout, etc.).
 * 
 * @class NetworkError
 * @extends ApiError
 */
class NetworkError extends ApiError {
    constructor(message, details = null) {
        super(message, 'NETWORK_ERROR', null, details);
        this.name = 'NetworkError';
    }
}

/**
 * HTTP error (4xx, 5xx responses).
 * 
 * @class HttpError
 * @extends ApiError
 */
class HttpError extends ApiError {
    /**
     * Create an HTTP error.
     * 
     * @param {string} message - Error message
     * @param {number} statusCode - HTTP status code
     * @param {Object} [details] - Additional details
     */
    constructor(message, statusCode, details = null) {
        super(message, 'HTTP_ERROR', statusCode, details);
        this.name = 'HttpError';
    }
}

/**
 * Validation error (400, 422 responses).
 * 
 * @class ValidationError
 * @extends ApiError
 */
class ValidationError extends ApiError {
    constructor(message, details = null) {
        super(message, 'VALIDATION_ERROR', 400, details);
        this.name = 'ValidationError';
    }
}

/**
 * Authentication error (401 response).
 * 
 * @class AuthenticationError
 * @extends ApiError
 */
class AuthenticationError extends ApiError {
    constructor(message = 'Authentication failed') {
        super(message, 'AUTHENTICATION_ERROR', 401);
        this.name = 'AuthenticationError';
    }
}

/**
 * Rate limit error (429 response).
 * 
 * @class RateLimitError
 * @extends ApiError
 */
class RateLimitError extends ApiError {
    constructor(message = 'Rate limit exceeded') {
        super(message, 'RATE_LIMIT_ERROR', 429);
        this.name = 'RateLimitError';
    }
}

/**
 * Timeout error.
 * 
 * @class TimeoutError
 * @extends ApiError
 */
class TimeoutError extends ApiError {
    constructor(message = 'Request timeout') {
        super(message, 'TIMEOUT_ERROR', null);
        this.name = 'TimeoutError';
    }
}

/**
 * Abort error (request cancelled).
 * 
 * @class AbortError
 * @extends ApiError
 */
class AbortError extends ApiError {
    constructor(message = 'Request cancelled') {
        super(message, 'ABORT_ERROR', null);
        this.name = 'AbortError';
    }
}

// ============================================================
// API Client Class
// ============================================================

/**
 * API Client for communicating with the Insight Sculpture backend.
 * 
 * @class ApiClient
 */
class ApiClient extends EventTarget {
    /**
     * Create an API client instance.
     * 
     * @param {Object} config - Configuration object
     * @param {string} [config.baseURL='http://localhost:8000'] - Base URL for API requests
     * @param {number} [config.timeout=30000] - Request timeout in milliseconds
     * @param {number} [config.retryAttempts=3] - Number of retry attempts for retryable errors
     * @param {number} [config.retryDelay=1000] - Initial retry delay in milliseconds
     * @param {Object} [config.headers] - Default headers to include in all requests
     */
    constructor(config = {}) {
        super();
        
        this.config = {
            baseURL: config.baseURL || 'http://localhost:8000',
            timeout: config.timeout || 30000,
            retryAttempts: config.retryAttempts || 3,
            retryDelay: config.retryDelay || 1000,
            headers: config.headers || {}
        };
        
        // Active AbortControllers for cancellation
        this._abortControllers = new Map();
        
        // Active SSE connections
        this._eventSources = new Map();
    }
    
    // ============================================================
    // Public Methods - Upload
    // ============================================================
    
    /**
     * Upload a dataset file to the backend.
     * 
     * @param {File} file - The file to upload (CSV or Excel)
     * @param {Function} [onProgress] - Optional progress callback (future implementation)
     * @returns {Promise<Object>} Upload response with session_id, filename, rows, columns, profile
     * @throws {ValidationError} If file is invalid
     * @throws {NetworkError} If network request fails
     * @throws {HttpError} If server returns error status
     * @throws {TimeoutError} If request times out
     * @throws {AbortError} If request is cancelled
     */
    async uploadDataset(file, onProgress = null) {
        this._validateFile(file);
        
        const formData = new FormData();
        formData.append('file', file);
        
        const requestId = this._generateRequestId();
        the abortController = new AbortController();
        this._abortControllers.set(requestId, abortController);
        
        try {
            this._emitEvent('requestStarted', { type: 'upload', requestId });
            
            const response = await this._request('/api/upload', {
                method: 'POST',
                body: formData,
                signal: abortController.signal,
                timeout: this.config.timeout * 2 // Longer timeout for uploads
            });
            
            this._emitEvent('requestCompleted', { type: 'upload', requestId });
            
            return response;
        } catch (error) {
            this._emitEvent('requestFailed', { type: 'upload', requestId, error });
            throw error;
        } finally {
            this._abortControllers.delete(requestId);
        }
    }
    
    /**
     * Validate the file before upload.
     * 
     * @private
     * @param {File} file 
     * @throws {ValidationError}
     */
    _validateFile(file) {
        if (!file) {
            throw new ValidationError('No file provided');
        }
        
        const validExtensions = ['.csv', '.xlsx', '.xls'];
        const fileExtension = '.' + file.name.split('.').pop().toLowerCase();
        
        if (!validExtensions.includes(fileExtension)) {
            throw new ValidationError(
                `Invalid file type. Supported formats: ${validExtensions.join(', ')}`,
                { allowedExtensions: validExtensions, providedExtension: fileExtension }
            );
        }
        
        const maxSize = 50 * 1024 * 1024; // 50MB
        if (file.size > maxSize) {
            throw new ValidationError(
                'File size exceeds maximum allowed size of 50MB',
                { maxSize, providedSize: file.size }
            );
        }
    }
    
    // ============================================================
    // Public Methods - Analyze
    // ============================================================
    
    /**
     * Analyze a dataset using AI.
     * 
     * @param {string} sessionId - The session ID from upload
     * @param {string} question - The natural language question
     * @param {Array<Object>} [conversationHistory] - Optional conversation history for context
     * @returns {Promise<Object>} Analyze response with plan, execution result, chart, explanation
     * @throws {ValidationError} If parameters are invalid
     * @throws {NetworkError} If network request fails
     * @throws {HttpError} If server returns error status
     * @throws {TimeoutError} If request times out
     * @throws {AbortError} If request is cancelled
     */
    async analyze(sessionId, question, conversationHistory = null) {
        if (!sessionId) {
            throw new ValidationError('Session ID is required');
        }
        
        if (!question || question.trim().length === 0) {
            throw new ValidationError('Question is required');
        }
        
        const requestBody = {
            session_id: sessionId,
            question: question.trim(),
            conversation_history: conversationHistory || null
        };
        
        const requestId = this._generateRequestId();
        const abortController = new AbortController();
        this._abortControllers.set(requestId, abortController);
        
        try {
            this._emitEvent('requestStarted', { type: 'analyze', requestId });
            
            const response = await this._request('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
                signal: abortController.signal
            });
            
            this._emitEvent('requestCompleted', { type: 'analyze', requestId });
            
            return response;
        } catch (error) {
            this._emitEvent('requestFailed', { type: 'analyze', requestId, error });
            throw error;
        } finally {
            this._abortControllers.delete(requestId);
        }
    }
    
    // ============================================================
    // Public Methods - Stream
    // ============================================================
    
    /**
     * Stream analysis results using Server-Sent Events.
     * 
     * @param {string} sessionId - The session ID from upload
     * @param {string} question - The natural language question
     * @param {Array<Object>} [conversationHistory] - Optional conversation history for context
     * @param {Object} callbacks - Event callbacks
     * @param {Function} [callbacks.onOpen] - Called when connection opens
     * @param {Function} [callbacks.onMessage] - Called for each SSE event
     * @param {Function} [callbacks.onError] - Called on error
     * @param {Function} [callbacks.onClose] - Called when connection closes
     * @returns {Object} Stream controller with disconnect() method
     * @throws {ValidationError} If parameters are invalid
     */
    streamAnalysis(sessionId, question, conversationHistory = null, callbacks = {}) {
        if (!sessionId) {
            throw new ValidationError('Session ID is required');
        }
        
        if (!question || question.trim().length === 0) {
            throw new ValidationError('Question is required');
        }
        
        const streamId = this._generateRequestId();
        
        // Build request body
        const requestBody = {
            session_id: sessionId,
            question: question.trim(),
            conversation_history: conversationHistory || null
        };
        
        // Build URL with query parameters
        const url = this._buildURL('/api/stream');
        
        // Store callbacks
        const streamCallbacks = {
            onOpen: callbacks.onOpen || (() => {}),
            onMessage: callbacks.onMessage || (() => {}),
            onError: callbacks.onError || (() => {}),
            onClose: callbacks.onClose || (() => {})
        };
        
        // Initiate stream using fetch with streaming response
        this._initiateStream(url, requestBody, streamCallbacks, streamId);
        
        // Return controller
        return {
            streamId,
            disconnect: () => this._disconnectStream(streamId),
            reconnect: () => this._reconnectStream(sessionId, question, conversationHistory, callbacks, streamId)
        };
    }
    
    /**
     * Initiate the stream by sending POST request.
     * 
     * @private
     * @param {string} url - Stream endpoint URL
     * @param {Object} body - Request body
     * @param {Object} callbacks - Event callbacks
     * @param {string} streamId - Stream identifier
     */
    async _initiateStream(url, body, callbacks, streamId) {
        const abortController = new AbortController();
        this._abortControllers.set(streamId, abortController);
        
        try {
            this._emitEvent('streamConnected', { streamId });
            callbacks.onOpen();
            
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: abortController.signal
            });
            
            if (!response.ok) {
                throw new HttpError(
                    `Stream request failed: ${response.statusText}`,
                    response.status
                );
            }
            
            // Handle streaming response
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            while (true) {
                const { done, value } = await reader.read();
                
                if (done) {
                    callbacks.onClose();
                    break;
                }
                
                const chunk = decoder.decode(value);
                this._parseSSEChunk(chunk, callbacks);
            }
            
        } catch (error) {
            if (error.name === 'AbortError') {
                // Stream was cancelled
                callbacks.onClose();
            } else {
                callbacks.onError(error);
            }
        } finally {
            this._abortControllers.delete(streamId);
            this._emitEvent('streamDisconnected', { streamId });
        }
    }
    
    /**
     * Parse SSE chunk and call appropriate callbacks.
     * 
     * @private
     * @param {string} chunk - SSE data chunk
     * @param {Object} callbacks - Event callbacks
     */
    _parseSSEChunk(chunk, callbacks) {
        const lines = chunk.split('\n');
        let currentEvent = 'message';
        
        for (const line of lines) {
            const trimmedLine = line.trim();
            
            if (trimmedLine.startsWith('event:')) {
                currentEvent = trimmedLine.substring(6).trim();
            } else if (trimmedLine.startsWith('data:')) {
                const data = trimmedLine.substring(5).trim();
                try {
                    const parsedData = JSON.parse(data);
                    callbacks.onMessage({
                        event: currentEvent,
                        data: parsedData
                    });
                } catch (e) {
                    // If not JSON, pass as string
                    callbacks.onMessage({
                        event: currentEvent,
                        data: data
                    });
                }
            }
        }
    }
    
    /**
     * Disconnect a stream.
     * 
     * @private
     * @param {string} streamId 
     */
    _disconnectStream(streamId) {
        const controller = this._abortControllers.get(streamId);
        if (controller) {
            controller.abort();
            this._abortControllers.delete(streamId);
        }
    }
    
    /**
     * Reconnect a stream.
     * 
     * @private
     * @param {string} sessionId 
     * @param {string} question 
     * @param {Array} conversationHistory 
     * @param {Object} callbacks 
     * @param {string} streamId 
     */
    _reconnectStream(sessionId, question, conversationHistory, callbacks, streamId) {
        this._disconnectStream(streamId);
        return this.streamAnalysis(sessionId, question, conversationHistory, callbacks);
    }
    
    // ============================================================
    // Public Methods - Health
    // ============================================================
    
    /**
     * Check backend health status.
     * 
     * @returns {Promise<Object>} Health status response
     * @throws {NetworkError} If network request fails
     * @throws {HttpError} If server returns error status
     */
    async health() {
        const requestId = this._generateRequestId();
        const abortController = new AbortController();
        this._abortControllers.set(requestId, abortController);
        
        try {
            this._emitEvent('requestStarted', { type: 'health', requestId });
            
            const response = await this._request('/health', {
                method: 'GET',
                signal: abortController.signal
            });
            
            this._emitEvent('requestCompleted', { type: 'health', requestId });
            
            return response;
        } catch (error) {
            this._emitEvent('requestFailed', { type: 'health', requestId, error });
            throw error;
        } finally {
            this._abortControllers.delete(requestId);
        }
    }
    
    // ============================================================
    // Private Methods - Request Handling
    // ============================================================
    
    /**
     * Make an HTTP request with retry logic.
     * 
     * @private
     * @param {string} endpoint - API endpoint path
     * @param {Object} options - Fetch options
     * @param {string} [options.method='GET'] - HTTP method
     * @param {Object} [options.headers] - Request headers
     * @param {BodyInit} [options.body] - Request body
     * @param {AbortSignal} [options.signal] - Abort signal
     * @param {number} [options.timeout] - Request timeout in milliseconds
     * @param {number} [attempt=0] - Current retry attempt
     * @returns {Promise<Object>} Parsed JSON response
     * @throws {NetworkError} If network fails after retries
     * @throws {HttpError} If HTTP error occurs
     * @throws {TimeoutError} If request times out
     * @throws {AbortError} If request is cancelled
     */
    async _request(endpoint, options = {}, attempt = 0) {
        const url = this._buildURL(endpoint);
        const headers = this._buildHeaders(options.headers);
        const timeout = options.timeout || this.config.timeout;
        
        // Create abort controller for timeout
        const timeoutController = new AbortController();
        const timeoutId = setTimeout(() => timeoutController.abort(), timeout);
        
        // Combine abort signals
        const combinedSignal = this._combineAbortSignals([
            options.signal,
            timeoutController.signal
        ]);
        
        try {
            const response = await fetch(url, {
                ...options,
                headers,
                signal: combinedSignal
            });
            
            clearTimeout(timeoutId);
            
            return await this._handleResponse(response);
            
        } catch (error) {
            clearTimeout(timeoutId);
            
            // Check if error is due to abort
            if (error.name === 'AbortError') {
                if (timeoutController.signal.aborted) {
                    throw new TimeoutError();
                }
                throw new AbortError();
            }
            
            // Retry logic for retryable errors
            if (this._shouldRetry(error, attempt)) {
                const delay = this._calculateRetryDelay(attempt);
                await this._delay(delay);
                return this._request(endpoint, options, attempt + 1);
            }
            
            // Convert to appropriate error type
            throw this._handleError(error);
        }
    }
    
    /**
     * Build full URL from endpoint.
     * 
     * @private
     * @param {string} endpoint 
     * @returns {string}
     */
    _buildURL(endpoint) {
        const baseURL = this.config.baseURL.replace(/\/$/, '');
        const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
        return `${baseURL}${path}`;
    }
    
    /**
     * Build request headers with defaults.
     * 
     * @private
     * @param {Object} [customHeaders] 
     * @returns {Object}
     */
    _buildHeaders(customHeaders = {}) {
        return {
            'Accept': 'application/json',
            ...this.config.headers,
            ...customHeaders
        };
    }
    
    /**
     * Handle HTTP response.
     * 
     * @private
     * @param {Response} response 
     * @returns {Promise<Object>} Parsed JSON response
     * @throws {HttpError} If response indicates error
     */
    async _handleResponse(response) {
        const contentType = response.headers.get('content-type');
        
        // Parse JSON response
        if (contentType && contentType.includes('application/json')) {
            const data = await response.json();
            
            if (!response.ok) {
                // Handle error response from backend
                const errorData = data.error || {};
                throw new HttpError(
                    errorData.message || 'Request failed',
                    response.status,
                    errorData.details || null
                );
            }
            
            return data;
        }
        
        // Handle non-JSON response
        if (!response.ok) {
            throw new HttpError(
                response.statusText || 'Request failed',
                response.status
            );
        }
        
        // Return text response
        return await response.text();
    }
    
    /**
     * Convert fetch error to appropriate error type.
     * 
     * @private
     * @param {Error} error 
     * @returns {ApiError}
     */
    _handleError(error) {
        // Network errors
        if (error instanceof TypeError && error.message.includes('fetch')) {
            return new NetworkError('Network connection failed');
        }
        
        if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
            return new NetworkError('Failed to connect to server');
        }
        
        // Already an API error
        if (error instanceof ApiError) {
            return error;
        }
        
        // Generic error
        return new NetworkError(error.message || 'An unexpected error occurred');
    }
    
    /**
     * Determine if request should be retried.
     * 
     * @private
     * @param {Error} error 
     * @param {number} attempt 
     * @returns {boolean}
     */
    _shouldRetry(error, attempt) {
        // Don't retry if max attempts reached
        if (attempt >= this.config.retryAttempts) {
            return false;
        }
        
        // Don't retry client errors (4xx)
        if (error instanceof HttpError && error.statusCode >= 400 && error.statusCode < 500) {
            // Retry rate limit errors (429)
            if (error.statusCode === 429) {
                return true;
            }
            return false;
        }
        
        // Retry network errors
        if (error instanceof NetworkError) {
            return true;
        }
        
        // Retry server errors (5xx)
        if (error instanceof HttpError && error.statusCode >= 500) {
            return true;
        }
        
        return false;
    }
    
    /**
     * Calculate retry delay with exponential backoff.
     * 
     * @private
     * @param {number} attempt 
     * @returns {number} Delay in milliseconds
     */
    _calculateRetryDelay(attempt) {
        return this.config.retryDelay * Math.pow(2, attempt);
    }
    
    /**
     * Delay for specified milliseconds.
     * 
     * @private
     * @param {number} ms 
     * @returns {Promise<void>}
     */
    _delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
    
    /**
     * Combine multiple abort signals.
     * 
     * @private
     * @param {Array<AbortSignal>} signals 
     * @returns {AbortSignal}
     */
    _combineAbortSignals(signals) {
        const controller = new AbortController();
        
        for (const signal of signals) {
            if (signal) {
                signal.addEventListener('abort', () => controller.abort());
            }
        }
        
        return controller.signal;
    }
    
    /**
     * Generate unique request ID.
     * 
     * @private
     * @returns {string}
     */
    _generateRequestId() {
        return `req_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }
    
    // ============================================================
    // Event Emission
    // ============================================================
    
    /**
     * Emit an event.
     * 
     * @private
     * @param {string} eventName 
     * @param {Object} detail 
     */
    _emitEvent(eventName, detail) {
        const event = new CustomEvent(eventName, { detail });
        this.dispatchEvent(event);
    }
    
    // ============================================================
    // Public Methods - Configuration
    // ============================================================
    
    /**
     * Update API client configuration.
     * 
     * @param {Object} config - Configuration updates
     */
    updateConfig(config) {
        this.config = { ...this.config, ...config };
    }
    
    /**
     * Cancel all active requests.
     */
    cancelAllRequests() {
        for (const [requestId, controller] of this._abortControllers) {
            controller.abort();
        }
        this._abortControllers.clear();
    }
    
    /**
     * Cancel a specific request by ID.
     * 
     * @param {string} requestId 
     */
    cancelRequest(requestId) {
        const controller = this._abortControllers.get(requestId);
        if (controller) {
            controller.abort();
            this._abortControllers.delete(requestId);
        }
    }
    
    /**
     * Close all active streams.
     */
    closeAllStreams() {
        for (const [streamId, controller] of this._abortControllers) {
            controller.abort();
        }
        this._abortControllers.clear();
    }
}

// ============================================================
// Singleton Instance
// ============================================================

/**
 * Singleton API client instance.
 * Initialized with default configuration.
 * 
 * @type {ApiClient}
 */
const apiClient = new ApiClient({
    baseURL: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? 'http://localhost:8000'
        : window.location.origin,
    timeout: 30000,
    retryAttempts: 3,
    retryDelay: 1000,
    headers: {}
});

// ============================================================
// Initialization Function
// ============================================================

/**
 * Initialize the API module with custom configuration.
 * 
 * @param {Object} config - Configuration object
 * @returns {ApiClient} The configured API client instance
 */
function initializeAPI(config = {}) {
    if (config.baseURL || config.timeout || config.retryAttempts) {
        apiClient.updateConfig(config);
    }
    
    console.log('[API] API client initialized');
    return apiClient;
}

// ============================================================
// Exports
// ============================================================

// Export for ES6 modules
export {
    ApiClient,
    ApiError,
    NetworkError,
    HttpError,
    ValidationError,
    AuthenticationError,
    RateLimitError,
    TimeoutError,
    AbortError,
    apiClient,
    initializeAPI
};

// Export for global access (for non-module environments)
if (typeof window !== 'undefined') {
    window.API = {
        ApiClient,
        ApiError,
        NetworkError,
        HttpError,
        ValidationError,
        AuthenticationError,
        RateLimitError,
        TimeoutError,
        AbortError,
        client: apiClient,
        initialize: initializeAPI
    };
    
    // Also expose initializeAPI function directly
    window.initializeAPI = initializeAPI;
}

console.log('[API] API module loaded');
