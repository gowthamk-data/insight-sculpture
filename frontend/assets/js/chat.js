/**
 * Insight Sculpture - Chat Manager Module
 *
 * This module is responsible ONLY for the conversational user interface.
 * It validates user input, sends requests through ApiClient, renders
 * conversation messages, and dispatches events for other modules.
 *
 * Responsibilities:
 * - Chat input handling (textarea, Send button, keyboard shortcuts)
 * - Input validation with friendly error messages
 * - Message history management (frontend-only, in-memory)
 * - Conversation rendering (user, assistant, system, error messages)
 * - Loading/streaming state management
 * - Custom event dispatch for module communication
 *
 * Dependencies:
 * - ApiClient from api.js (via window.API.client or window.apiClient)
 *
 * @module chat
 */

// ============================================================
// Constants
// ============================================================

/** @const {number} Maximum allowed message length in characters. */
const MAX_MESSAGE_LENGTH = 2000;

/** @const {number} Minimum scroll threshold from bottom to treat as "at bottom". */
const SCROLL_BOTTOM_THRESHOLD = 60;

// ============================================================
// Chat States
// ============================================================

/**
 * Enum for chat UI states.
 *
 * @readonly
 * @enum {string}
 */
const ChatState = Object.freeze({
    IDLE: 'idle',
    WAITING: 'waiting',
    RECEIVING: 'receiving',
    COMPLETED: 'completed',
    FAILED: 'failed',
});

// ============================================================
// Chat Manager Class
// ============================================================

class ChatManager {
    /**
     * Create a ChatManager instance.
     *
     * @param {Object} [options] - Configuration options.
     * @param {Object} [options.apiClient] - ApiClient instance. Falls back to window.API.client.
     */
    constructor(options = {}) {
        /**
         * ApiClient instance for backend communication.
         * @private
         * @type {Object}
         */
        this._apiClient = options.apiClient || this._resolveApiClient();

        /**
         * In-memory conversation history.
         * Each entry: { role, content, timestamp }
         * @private
         * @type {Array<Object>}
         */
        this._conversationHistory = [];

        /**
         * Current UI state.
         * @private
         * @type {string}
         */
        this._state = ChatState.IDLE;

        /**
         * Whether the module has been initialized.
         * @private
         * @type {boolean}
         */
        this._initialized = false;

        /**
         * Cached DOM elements.
         * @private
         * @type {Object}
         */
        this._dom = {
            chatHistory: null,
            input: null,
            sendButton: null,
            clearButton: null,
            typingIndicator: null,
            suggestedQuestions: null,
            microphoneButton: null,
        };

        /**
         * Bound event handlers (for removal).
         * @private
         * @type {Object}
         */
        this._handlers = {};
    }

    // ============================================================
    // Initialization
    // ============================================================

    /**
     * Initialize the chat interface.
     *
     * Caches DOM elements, sets up event listeners, and returns
     * the ChatManager instance for the application to store.
     *
     * @returns {ChatManager} This instance for chaining and module storage.
     */
    init() {
        if (this._initialized) {
            console.warn('[Chat] Already initialized, skipping.');
            return this;
        }

        this._cacheDOMElements();
        this._bindEventListeners();
        this._setState(ChatState.IDLE);

        this._initialized = true;
        console.log('[Chat] ChatManager initialized');

        return this;
    }

    /**
     * Cache frequently accessed DOM elements.
     *
     * @private
     */
    _cacheDOMElements() {
        this._dom.chatHistory = document.getElementById('chat-history');
        this._dom.input = document.getElementById('question-input');
        this._dom.sendButton = document.getElementById('send-button');
        this._dom.clearButton = document.getElementById('clear-button');
        this._dom.typingIndicator = document.getElementById('typing-indicator');
        this._dom.suggestedQuestions = document.getElementById('suggested-questions');
        this._dom.microphoneButton = document.getElementById('microphone-button');
    }

    /**
     * Bind event listeners for chat interactions.
     *
     * @private
     */
    _bindEventListeners() {
        const dom = this._dom;

        // Send button click
        if (dom.sendButton) {
            this._handlers.sendClick = this._handleSendClick.bind(this);
            dom.sendButton.addEventListener('click', this._handlers.sendClick);
        }

        // Clear button click
        if (dom.clearButton) {
            this._handlers.clearClick = this._handleClearClick.bind(this);
            dom.clearButton.addEventListener('click', this._handlers.clearClick);
        }

        // Input events: Enter to send, Shift+Enter for newline
        if (dom.input) {
            this._handlers.inputKeydown = this._handleInputKeydown.bind(this);
            dom.input.addEventListener('keydown', this._handlers.inputKeydown);

            this._handlers.inputInput = this._handleInputInput.bind(this);
            dom.input.addEventListener('input', this._handlers.inputInput);
        }

        // Suggested question chips (delegated)
        if (dom.suggestedQuestions) {
            this._handlers.suggestedClick = this._handleSuggestedClick.bind(this);
            dom.suggestedQuestions.addEventListener('click', this._handlers.suggestedClick);
        }

        // Application keyboard shortcuts
        this._handlers.shortcutSend = this._handleShortcutSend.bind(this);
        document.addEventListener('shortcut:send', this._handlers.shortcutSend);

        this._handlers.shortcutClear = this._handleShortcutClear.bind(this);
        document.addEventListener('shortcut:clear', this._handlers.shortcutClear);

        // Application pause/resume (visibility change)
        this._handlers.appPause = this._handleAppPause.bind(this);
        document.addEventListener('app:pause', this._handlers.appPause);
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
            '[Chat] ApiClient not found. Ensure api.js is loaded before chat.js.'
        );
    }

    // ============================================================
    // Public API — Streaming Support
    // ============================================================

    /**
     * Begin a new assistant response message for streaming.
     *
     * Creates an empty assistant message bubble and returns a
     * reference that can be used to append chunks.
     *
     * @returns {Object} Stream context with { element, id }.
     */
    beginStreamedResponse() {
        const messageId = this._generateMessageId();
        const bubble = this._createAssistantBubble('', messageId);
        const messageElement = bubble.querySelector('.chat-bubble');

        this._appendMessage(bubble);

        return {
            id: messageId,
            element: messageElement,
        };
    }

    /**
     * Append a text chunk to an ongoing streamed response.
     *
     * @param {Object} streamContext - Context from beginStreamedResponse().
     * @param {string} textChunk - The chunk of text to append.
     */
    appendStreamChunk(streamContext, textChunk) {
        if (!streamContext || !streamContext.element) {
            return;
        }

        const element = streamContext.element;
        const currentText = element.textContent || '';
        element.textContent = currentText + textChunk;

        this._scrollToBottomIfNeeded();
    }

    /**
     * Finalize a streamed response after all chunks are received.
     *
     * Updates the conversation history and dispatches completion event.
     *
     * @param {Object} streamContext - Context from beginStreamedResponse().
     * @param {string} [finalText] - Optional final text to set (if not already appended).
     */
    finishStreamedResponse(streamContext, finalText) {
        if (!streamContext || !streamContext.element) {
            return;
        }

        if (finalText !== undefined) {
            streamContext.element.textContent = finalText;
        }

        const text = streamContext.element.textContent || '';
        this._addToHistory('assistant', text);

        this._setState(ChatState.COMPLETED);
        this._hideTypingIndicator();
        this._enableInput();

        this._dispatchEvent('chatResponseCompleted', {
            messageId: streamContext.id,
            content: text,
        });
    }

    // ============================================================
    // Public API — State & History
    // ============================================================

    /**
     * Get a copy of the current conversation history.
     *
     * @returns {Array<Object>} Array of { role, content, timestamp } entries.
     */
    getConversationHistory() {
        return this._conversationHistory.map((entry) => ({ ...entry }));
    }

    /**
     * Get the current chat state.
     *
     * @returns {string} Current ChatState value.
     */
    getState() {
        return this._state;
    }

    /**
     * Clear all conversation history and reset the UI.
     *
     * Preserves the welcome message. Dispatches a chat:cleared event.
     */
    clearConversation() {
        this._conversationHistory = [];

        const dom = this._dom;
        if (dom.chatHistory) {
            // Remove all messages except the welcome message
            const messages = dom.chatHistory.querySelectorAll('.chat-message');
            messages.forEach((msg) => msg.remove());
        }

        this._hideSuggestedQuestions();
        this._setState(ChatState.IDLE);
        this._enableInput();
        this._hideTypingIndicator();
        this._focusInput();

        this._dispatchEvent('chat:cleared', {});
    }

    // ============================================================
    // Core Chat Flow
    // ============================================================

    /**
     * Process a user question through the full chat flow.
     *
     * 1. Validates the input
     * 2. Renders the user message
     * 3. Dispatches event
     * 4. Sends to backend via ApiClient
     * 5. Renders the assistant response
     *
     * @param {string} question - The user's question text.
     * @returns {Promise<void>}
     */
    async sendMessage(question) {
        const trimmed = (question || '').trim();

        try {
            this._validateMessage(trimmed);
        } catch (validationError) {
            this._showValidationError(validationError.message);
            return;
        }

        this._renderUserMessage(trimmed);
        this._addToHistory('user', trimmed);
        this._clearInput();

        this._dispatchEvent('chatMessageSent', {
            content: trimmed,
            history: this.getConversationHistory(),
        });

        this._setState(ChatState.WAITING);
        this._disableInput();
        this._showTypingIndicator();
        this._hideSuggestedQuestions();

        try {
            const sessionId = this._resolveSessionId();

            if (!sessionId) {
                this._showSystemMessage(
                    'Please upload a dataset first before asking questions.'
                );
                this._setState(ChatState.FAILED);
                this._enableInput();
                this._hideTypingIndicator();
                return;
            }

            this._dispatchEvent('chatResponseStarted', {
                question: trimmed,
            });

            const response = await this._apiClient.analyze(
                sessionId,
                trimmed,
                this.getConversationHistory()
            );

            this._hideTypingIndicator();

            const explanation = this._extractExplanation(response);

            this._renderAssistantMessage(explanation);
            this._addToHistory('assistant', explanation);

            this._setState(ChatState.COMPLETED);

            this._dispatchEvent('chatResponseReceived', {
                question: trimmed,
                response: response,
                explanation: explanation,
            });

            if (response && response.chart) {
                this._dispatchEvent('analysisChartReady', {
                    chart: response.chart,
                    source: 'analyze',
                });
            }

            this._dispatchEvent('chatResponseCompleted', {
                content: explanation,
            });

            this._showSuggestedQuestions();
        } catch (error) {
            this._handleSendError(error);
        } finally {
            this._enableInput();
            this._hideTypingIndicator();
        }
    }

    // ============================================================
    // Input Validation
    // ============================================================

    /**
     * Validate user message before sending.
     *
     * @param {string} message - The trimmed message to validate.
     * @returns {boolean} True if valid.
     * @throws {Error} With a user-friendly message if invalid.
     * @private
     */
    _validateMessage(message) {
        if (!message) {
            throw new Error('Please enter a question before sending.');
        }

        if (message.length > MAX_MESSAGE_LENGTH) {
            throw new Error(
                `Your question is too long. Please keep it under ${MAX_MESSAGE_LENGTH.toLocaleString()} characters.`
            );
        }

        return true;
    }

    // ============================================================
    // Message Rendering
    // ============================================================

    /**
     * Render a user message bubble in the chat history.
     *
     * @param {string} text - The message text.
     * @private
     */
    _renderUserMessage(text) {
        const bubble = this._createUserBubble(text);
        this._appendMessage(bubble);
    }

    /**
     * Render an assistant message bubble in the chat history.
     *
     * @param {string} text - The message text.
     * @private
     */
    _renderAssistantMessage(text) {
        const bubble = this._createAssistantBubble(text);
        this._appendMessage(bubble);
    }

    /**
     * Show a system status message in the chat.
     *
     * @param {string} text - The system message text.
     * @private
     */
    _showSystemMessage(text) {
        const bubble = document.createElement('div');
        bubble.className = 'flex items-start space-x-3 chat-message';

        bubble.innerHTML = `
            <div class="w-8 h-8 bg-slate-400 rounded-lg flex items-center justify-center flex-shrink-0">
                <i class="fa-solid fa-circle-info text-white text-sm" aria-hidden="true"></i>
            </div>
            <div class="bg-slate-100 rounded-2xl rounded-tl-none px-4 py-3 max-w-2xl">
                <p class="text-slate-600 text-sm italic">${this._escapeHtml(text)}</p>
            </div>
        `;

        this._appendMessage(bubble);
    }

    /**
     * Show an error message in the chat.
     *
     * @param {string} text - The error message text.
     * @private
     */
    _showErrorMessage(text) {
        const bubble = document.createElement('div');
        bubble.className = 'flex items-start space-x-3 chat-message';

        bubble.innerHTML = `
            <div class="w-8 h-8 bg-red-400 rounded-lg flex items-center justify-center flex-shrink-0">
                <i class="fa-solid fa-circle-exclamation text-white text-sm" aria-hidden="true"></i>
            </div>
            <div class="bg-red-50 border border-red-200 rounded-2xl rounded-tl-none px-4 py-3 max-w-2xl">
                <p class="text-red-700 text-sm">${this._escapeHtml(text)}</p>
            </div>
        `;

        this._appendMessage(bubble);
    }

    /**
     * Show a validation error as a status message.
     *
     * @param {string} message - Validation error message.
     * @private
     */
    _showValidationError(message) {
        // Briefly highlight the input with a shake effect
        const input = this._dom.input;
        if (input) {
            input.classList.add('border-red-400', 'ring-2', 'ring-red-200');
            setTimeout(() => {
                input.classList.remove('border-red-400', 'ring-2', 'ring-red-200');
            }, 1500);
        }

        // Show the error as a system message
        this._showSystemMessage(message);
    }

    /**
     * Create a user message bubble element.
     *
     * @param {string} text - Message content.
     * @returns {HTMLElement} The message row element.
     * @private
     */
    _createUserBubble(text) {
        const wrapper = document.createElement('div');
        wrapper.className = 'flex items-start space-x-3 chat-message user flex-row-reverse';
        wrapper.setAttribute('role', 'article');
        wrapper.setAttribute('aria-label', 'Your message');

        const safeText = this._escapeHtml(text);

        wrapper.innerHTML = `
            <div class="w-8 h-8 bg-slate-600 rounded-lg flex items-center justify-center flex-shrink-0">
                <i class="fa-solid fa-user text-white text-sm" aria-hidden="true"></i>
            </div>
            <div class="bg-primary-500 text-white rounded-2xl rounded-tr-none px-4 py-3 max-w-2xl">
                <p class="text-sm">${safeText}</p>
            </div>
        `;

        return wrapper;
    }

    /**
     * Create an assistant message bubble element.
     *
     * @param {string} text - Message content.
     * @param {string} [messageId] - Optional unique message ID.
     * @returns {HTMLElement} The message row element.
     * @private
     */
    _createAssistantBubble(text, messageId) {
        const wrapper = document.createElement('div');
        wrapper.className = 'flex items-start space-x-3 chat-message';
        wrapper.setAttribute('role', 'article');
        wrapper.setAttribute('aria-label', 'Assistant message');
        if (messageId) {
            wrapper.dataset.messageId = messageId;
        }

        const safeText = this._escapeHtml(text);

        wrapper.innerHTML = `
            <div class="w-8 h-8 bg-gradient-to-br from-primary-500 to-primary-600 rounded-lg flex items-center justify-center flex-shrink-0">
                <i class="fa-solid fa-robot text-white text-sm" aria-hidden="true"></i>
            </div>
            <div class="bg-slate-100 rounded-2xl rounded-tl-none px-4 py-3 max-w-2xl">
                <p class="text-slate-700 text-sm">${safeText}</p>
            </div>
        `;

        return wrapper;
    }

    /**
     * Append a message element to the chat history and scroll down.
     *
     * @param {HTMLElement} element - The message element to append.
     * @private
     */
    _appendMessage(element) {
        const chatHistory = this._dom.chatHistory;
        if (!chatHistory) {
            return;
        }

        chatHistory.appendChild(element);
        this._scrollToBottom();
    }

    // ============================================================
    // Conversation History
    // ============================================================

    /**
     * Add an entry to the in-memory conversation history.
     *
     * @param {string} role - Message role ('user', 'assistant', 'system').
     * @param {string} content - Message content.
     * @private
     */
    _addToHistory(role, content) {
        this._conversationHistory.push({
            role: role,
            content: content,
            timestamp: new Date().toISOString(),
        });
    }

    // ============================================================
    // Error Handling
    // ============================================================

    /**
     * Handle errors that occur during sendMessage.
     *
     * @param {Error} error - The error that occurred.
     * @private
     */
    _handleSendError(error) {
        this._setState(ChatState.FAILED);
        this._hideTypingIndicator();
        this._enableInput();

        const friendlyMessage = this._getFriendlyErrorMessage(error);

        this._showErrorMessage(friendlyMessage);

        this._dispatchEvent('chatError', {
            error: error,
            friendlyMessage: friendlyMessage,
        });

        console.error('[Chat] Send error:', error.message || error);
    }

    /**
     * Convert an error to a user-friendly message.
     *
     * @param {Error} error - The original error.
     * @returns {string} User-friendly error message.
     * @private
     */
    _getFriendlyErrorMessage(error) {
        if (!error) {
            return 'An unexpected error occurred. Please try again.';
        }

        const code = error.code || error.name || '';
        const message = error.message || String(error);

        // ApiClient error classes
        if (code === 'NETWORK_ERROR' || message.includes('NetworkError')) {
            return 'Unable to connect to the server. Please check your network connection and try again.';
        }
        if (code === 'TIMEOUT_ERROR') {
            return 'The request took too long. Please try again with a simpler question.';
        }
        if (code === 'VALIDATION_ERROR') {
            return 'Your request could not be processed. Please rephrase your question.';
        }
        if (code === 'AUTHENTICATION_ERROR') {
            return 'Authentication failed. The server configuration may need to be updated.';
        }
        if (code === 'RATE_LIMIT_ERROR') {
            return 'Too many requests. Please wait a moment and try again.';
        }
        if (code === 'HTTP_ERROR') {
            const status = error.statusCode;
            if (status === 404) {
                return 'The dataset session was not found. Please upload your dataset again.';
            }
            if (status === 422) {
                return 'Unable to process your request. Please rephrase your question.';
            }
            if (status === 503 || status === 504) {
                return 'The server is temporarily unavailable. Please try again in a moment.';
            }
        }

        // Generic fallback
        return 'An error occurred while processing your question. Please try again.';
    }

    // ============================================================
    // Typing Indicator
    // ============================================================

    /**
     * Show the typing indicator in the chat.
     *
     * @private
     */
    _showTypingIndicator() {
        const indicator = this._dom.typingIndicator;
        if (indicator) {
            indicator.classList.remove('hidden');
            this._scrollToBottom();
        }
    }

    /**
     * Hide the typing indicator.
     *
     * @private
     */
    _hideTypingIndicator() {
        const indicator = this._dom.typingIndicator;
        if (indicator) {
            indicator.classList.add('hidden');
        }
    }

    // ============================================================
    // Suggested Questions
    // ============================================================

    /**
     * Show the suggested questions area.
     *
     * @private
     */
    _showSuggestedQuestions() {
        const el = this._dom.suggestedQuestions;
        if (el) {
            el.classList.remove('hidden');
        }
    }

    /**
     * Hide the suggested questions area.
     *
     * @private
     */
    _hideSuggestedQuestions() {
        const el = this._dom.suggestedQuestions;
        if (el) {
            el.classList.add('hidden');
        }
    }

    /**
     * Handle a suggested question chip click.
     *
     * @param {Event} event - Click event.
     * @private
     */
    _handleSuggestedClick(event) {
        const chip = event.target.closest('.suggested-chip');
        if (!chip) {
            return;
        }

        const text = chip.textContent.trim();
        if (text) {
            this._setInputValue(text);
            this.sendMessage(text);
        }
    }

    // ============================================================
    // Input Management
    // ============================================================

    /**
     * Clear the input textarea.
     *
     * @private
     */
    _clearInput() {
        const input = this._dom.input;
        if (input) {
            input.value = '';
            this._updateSendButton();
        }
    }

    /**
     * Set the input textarea value.
     *
     * @param {string} text - Text to set.
     * @private
     */
    _setInputValue(text) {
        const input = this._dom.input;
        if (input) {
            input.value = text;
            this._updateSendButton();
            input.focus();
        }
    }

    /**
     * Focus the input textarea.
     *
     * @private
     */
    _focusInput() {
        const input = this._dom.input;
        if (input) {
            input.focus();
        }
    }

    /**
     * Enable the input and send button.
     *
     * @private
     */
    _enableInput() {
        const input = this._dom.input;
        const button = this._dom.sendButton;

        if (input) {
            input.disabled = false;
        }
        if (button) {
            button.disabled = false;
        }
    }

    /**
     * Disable the input and send button during processing.
     *
     * @private
     */
    _disableInput() {
        const input = this._dom.input;
        const button = this._dom.sendButton;

        if (input) {
            input.disabled = true;
        }
        if (button) {
            button.disabled = true;
        }
    }

    /**
     * Update the send button disabled state based on input content.
     *
     * Called on every input event to enable/disable the button.
     *
     * @private
     */
    _updateSendButton() {
        const input = this._dom.input;
        const button = this._dom.sendButton;
        if (!input || !button) {
            return;
        }

        const hasText = input.value.trim().length > 0;
        const isWaiting = this._state === ChatState.WAITING || this._state === ChatState.RECEIVING;

        button.disabled = !hasText || isWaiting;
    }

    // ============================================================
    // Session ID Resolution
    // ============================================================

    /**
     * Resolve the current session ID from application state.
     *
     * Reads from window.InsightSculptureApp if available, otherwise
     * checks window.AppState.
     *
     * @returns {string|null} Current session ID or null.
     * @private
     */
    _resolveSessionId() {
        if (
            window.InsightSculptureApp &&
            typeof window.InsightSculptureApp.getAppState === 'function'
        ) {
            const state = window.InsightSculptureApp.getAppState();
            return state.currentSessionId || null;
        }

        if (window.AppState && window.AppState.currentSessionId) {
            return window.AppState.currentSessionId;
        }

        return null;
    }

    // ============================================================
    // Response Parsing
    // ============================================================

    /**
     * Extract the explanation text from an analyze response.
     *
     * Handles both the full analyze response and partial responses.
     *
     * @param {Object} response - The response from ApiClient.analyze().
     * @returns {string} Extracted explanation text.
     * @private
     */
    _extractExplanation(response) {
        if (!response) {
            return 'No response received.';
        }

        // Analyze endpoint returns { explanation: { explanation: "..." } }
        if (response.explanation && response.explanation.explanation) {
            return response.explanation.explanation;
        }

        // Direct explanation string
        if (response.explanation && typeof response.explanation === 'string') {
            return response.explanation;
        }

        // Fallback: use summary if available
        if (response.explanation && response.explanation.summary) {
            return response.explanation.summary;
        }

        // Generic fallback
        return 'Analysis complete. The results are displayed above.';
    }

    // ============================================================
    // State Management
    // ============================================================

    /**
     * Set the current chat state.
     *
     * @param {string} newState - One of ChatState values.
     * @private
     */
    _setState(newState) {
        const previousState = this._state;
        this._state = newState;

        this._dispatchEvent('chat:stateChanged', {
            previousState: previousState,
            currentState: newState,
        });
    }

    // ============================================================
    // Scrolling
    // ============================================================

    /**
     * Scroll the chat history to the bottom.
     *
     * @private
     */
    _scrollToBottom() {
        const chatHistory = this._dom.chatHistory;
        if (chatHistory) {
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }
    }

    /**
     * Scroll to the bottom only if the user is already near the bottom.
     *
     * This prevents interrupting the user when they are reading
     * earlier parts of the conversation during streaming.
     *
     * @private
     */
    _scrollToBottomIfNeeded() {
        const chatHistory = this._dom.chatHistory;
        if (!chatHistory) {
            return;
        }

        const distanceFromBottom =
            chatHistory.scrollHeight - chatHistory.scrollTop - chatHistory.clientHeight;

        if (distanceFromBottom <= SCROLL_BOTTOM_THRESHOLD) {
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }
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
    // Event Handlers
    // ============================================================

    /**
     * Handle Send button click.
     *
     * @private
     */
    _handleSendClick() {
        const input = this._dom.input;
        if (!input) {
            return;
        }

        const text = input.value;
        if (text.trim()) {
            this.sendMessage(text);
        }
    }

    /**
     * Handle Clear button click.
     *
     * @private
     */
    _handleClearClick() {
        this.clearConversation();
    }

    /**
     * Handle keyboard events on the input textarea.
     *
     * Enter sends the message. Shift+Enter inserts a newline.
     *
     * @param {KeyboardEvent} event - Keyboard event.
     * @private
     */
    _handleInputKeydown(event) {
        // Enter without Shift sends the message
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();

            if (this._state === ChatState.WAITING || this._state === ChatState.RECEIVING) {
                return;
            }

            const text = event.target.value;
            if (text.trim()) {
                this.sendMessage(text);
            }
        }
    }

    /**
     * Handle input event on the textarea (update send button).
     *
     * @param {Event} event - Input event.
     * @private
     */
    _handleInputInput() {
        this._updateSendButton();
    }

    /**
     * Handle global shortcut:send event from app.js (Ctrl+Enter).
     *
     * @private
     */
    _handleShortcutSend() {
        if (this._state === ChatState.WAITING || this._state === ChatState.RECEIVING) {
            return;
        }

        const input = this._dom.input;
        if (input && input.value.trim()) {
            this.sendMessage(input.value);
        }
    }

    /**
     * Handle global shortcut:clear event from app.js (Ctrl+L).
     *
     * @private
     */
    _handleShortcutClear() {
        this.clearConversation();
    }

    /**
     * Handle app:pause event (page hidden).
     *
     * @private
     */
    _handleAppPause() {
        // Future: pause any active streaming if implemented
    }

    // ============================================================
    // Utility Methods
    // ============================================================

    /**
     * Generate a unique message ID.
     *
     * @returns {string} A unique message identifier.
     * @private
     */
    _generateMessageId() {
        return `msg_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    }

    /**
     * Escape HTML special characters to prevent XSS.
     *
     * @param {string} text - The text to escape.
     * @returns {string} Escaped text safe for DOM insertion.
     * @private
     */
    _escapeHtml(text) {
        if (typeof text !== 'string') {
            return '';
        }

        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ============================================================
    // Cleanup
    // ============================================================

    /**
     * Remove event listeners and clean up resources.
     *
     * Called by app.js during shutdown.
     */
    destroy() {
        const dom = this._dom;

        if (dom.sendButton && this._handlers.sendClick) {
            dom.sendButton.removeEventListener('click', this._handlers.sendClick);
        }
        if (dom.clearButton && this._handlers.clearClick) {
            dom.clearButton.removeEventListener('click', this._handlers.clearClick);
        }
        if (dom.input) {
            if (this._handlers.inputKeydown) {
                dom.input.removeEventListener('keydown', this._handlers.inputKeydown);
            }
            if (this._handlers.inputInput) {
                dom.input.removeEventListener('input', this._handlers.inputInput);
            }
        }
        if (dom.suggestedQuestions && this._handlers.suggestedClick) {
            dom.suggestedQuestions.removeEventListener('click', this._handlers.suggestedClick);
        }

        document.removeEventListener('shortcut:send', this._handlers.shortcutSend);
        document.removeEventListener('shortcut:clear', this._handlers.shortcutClear);
        document.removeEventListener('app:pause', this._handlers.appPause);

        this._initialized = false;
        console.log('[Chat] ChatManager destroyed');
    }
}

// ============================================================
// Initialization Function
// ============================================================

/**
 * Initialize the chat module.
 *
 * Creates a ChatManager instance, initializes it, and returns it
 * for storage by the application module (app.js).
 *
 * The function is exposed on window for discovery by app.js,
 * which checks for `typeof window.initializeChat === 'function'`.
 *
 * @async
 * @param {Object} [config] - Optional configuration.
 * @returns {Promise<ChatManager>} The initialized ChatManager instance.
 */
async function initializeChat(config = {}) {
    const manager = new ChatManager(config);
    manager.init();
    return manager;
}

// ============================================================
// Global Exports
// ============================================================

// Expose for app.js initialization discovery
window.initializeChat = initializeChat;

// Expose ChatManager class for testing and direct access
window.ChatManager = ChatManager;

console.log('[Chat] Chat module loaded');