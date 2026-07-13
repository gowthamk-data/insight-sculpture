/**
 * Insight Sculpture - UI Manager Module
 *
 * This module is responsible ONLY for managing the application's user interface.
 * It does NOT communicate with the backend, call fetch(), upload files, manage
 * SSE, render Plotly charts, execute analytics, perform business logic, generate
 * prompts, or manipulate non-UI application state.
 *
 * Data flow:
 *   Receive Frontend Events  ->  Update UI  ->  Manage Visual State  ->  User Feedback
 *
 * All information is received exclusively through CustomEvents (never by importing
 * ApiClient or touching the network). Outgoing signals are also CustomEvents.
 *
 * @module ui
 */

// ============================================================
// Constants
// ============================================================

/** @const {string} localStorage key for the persisted theme. */
const UI_THEME_KEY = 'theme';

/** @const {Object} Accent colors per notification type (inline, no CSS dependency). */
const NOTIFICATION_COLORS = {
    success: '#10b981',
    info: '#0ea5e9',
    warning: '#f59e0b',
    error: '#ef4444',
};

/** @const {number} Default notification auto-dismiss time (ms). */
const NOTIFICATION_DEFAULT_DURATION = 5000;

/** @const {number} Error notifications stay longer. */
const NOTIFICATION_ERROR_DURATION = 8000;

/** @const {number} Debounce window (ms) for window resize handling. */
const RESIZE_DEBOUNCE_MS = 200;

/** @const {string} Selector for focusable elements (focus trap). */
const FOCUSABLE_SELECTOR =
    'a[href], button:not([disabled]), input:not([disabled]), ' +
    'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// ============================================================
// UI Manager
// ============================================================

/**
 * Manages all purely-presentational UI: loading indicators, notifications,
 * progress, the dataset info panel, connection status, empty states, modals,
 * theme, responsive layout, and accessibility helpers.
 */
class UIManager {
    /**
     * @param {Object} [options]
     * @param {Object} [options.dom] - Optional DOM overrides for testing.
     */
    constructor(options = {}) {
        /**
         * Resolved DOM references (cached).
         * @private
         * @type {Object}
         */
        this._dom = options.dom || null;

        /**
         * Active loading states (prevents overlapping spinners).
         * @private
         * @type {Set<string>}
         */
        this._loadingStates = new Set();

        /**
         * Most recently requested loading label.
         * @private
         * @type {string}
         */
        this._loadingLabel = '';

        /**
         * Current theme: 'light' | 'dark' | 'auto'.
         * @private
         * @type {string}
         */
        this._theme = 'light';

        /**
         * Current connection status.
         * @private
         * @type {string}
         */
        this._connectionStatus = 'online';

        /**
         * Modal open state, keyed by modal name.
         * @private
         * @type {Object}
         */
        this._modalStates = {};

        /**
         * Stack of currently open modal names (for Escape / focus restore).
         * @private
         * @type {string[]}
         */
        this._openModals = [];

        /**
         * Element focused before a modal opened (for focus restore).
         * @private
         * @type {HTMLElement|null}
         */
        this._lastFocused = null;

        /**
         * Whether the manager has been initialized.
         * @private
         * @type {boolean}
         */
        this._initialized = false;

        /**
         * Bound handlers (kept for clean removal).
         * @private
         * @type {Object}
         */
        this._handlers = {};

        /**
         * Pending resize timer.
         * @private
         * @type {number|null}
         */
        this._resizeTimer = null;

        /**
         * Reduced-motion preference.
         * @private
         * @type {boolean}
         */
        this._reducedMotion = false;
    }

    // ============================================================
    // Initialization
    // ============================================================

    /**
     * Initialize the UI manager: cache DOM, build overlay regions, wire events,
     * and apply initial visual state. Safe to call once.
     *
     * @returns {UIManager} This instance.
     */
    init() {
        if (this._initialized) {
            console.warn('[UI] Already initialized, skipping.');
            return this;
        }

        this._cacheDOMElements();
        this._reducedMotion = this._prefersReducedMotion();

        this._buildOverlayRegions();
        this._initTheme();
        this._bindModalInfrastructure();
        this._bindSettingsControls();
        this._bindGlobalEvents();
        this._applyEmptyStates();

        this._initialized = true;
        console.log('[UI] UIManager initialized');

        return this;
    }

    /**
     * Cache frequently used DOM elements.
     *
     * @private
     */
    _cacheDOMElements() {
        const $ = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

        this._dom = {
            themeToggle: $('theme-toggle'),
            aboutButton: $('about-button'),
            datasetInfo: $('dataset-info'),
            datasetName: $('dataset-name'),
            datasetRows: $('dataset-rows'),
            datasetColumns: $('dataset-columns'),
            sessionId: $('session-id'),
            errorModal: $('error-modal'),
            errorModalTitle: $('error-modal-title'),
            errorModalMessage: $('error-modal-message'),
            settingsModal: $('settings-modal'),
            settingsModalSave: $('settings-modal-save'),
            themeSelect: $('theme-select'),
            aboutModal: $('about-modal'),
            modals: [
                $('error-modal'),
                $('settings-modal'),
                $('about-modal'),
            ].filter(Boolean),
        };

        // Drop nulls defensively.
        this._dom.modals = this._dom.modals.filter(Boolean);
    }

    /**
     * Create reusable overlay regions appended to <body>:
     *   - loading bar (top)
     *   - notification stack (top-right)
     *   - connection status pill (bottom-left)
     *   - aria-live announcer (visually hidden)
     *
     * @private
     */
    _buildOverlayRegions() {
        if (typeof document === 'undefined') {
            return;
        }

        if (!document.getElementById('ui-loading-bar')) {
            const bar = document.createElement('div');
            bar.id = 'ui-loading-bar';
            bar.className = 'ui-loading-bar';
            bar.setAttribute('role', 'progressbar');
            bar.setAttribute('aria-label', 'Loading');
            bar.style.position = 'fixed';
            bar.style.top = '0';
            bar.style.left = '0';
            bar.style.height = '3px';
            bar.style.width = '0';
            bar.style.zIndex = '9998';
            bar.style.background = 'linear-gradient(90deg, #0ea5e9, #38bdf8)';
            bar.style.transition = this._reducedMotion ? 'none' : 'width 200ms ease';
            bar.style.display = 'none';
            document.body.appendChild(bar);
            this._dom.loadingBar = bar;
        } else {
            this._dom.loadingBar = document.getElementById('ui-loading-bar');
        }

        if (!document.getElementById('ui-loading-label')) {
            const label = document.createElement('div');
            label.id = 'ui-loading-label';
            label.className = 'ui-loading-label';
            label.style.position = 'fixed';
            label.style.top = '8px';
            label.style.left = '50%';
            label.style.transform = 'translateX(-50%)';
            label.style.zIndex = '9998';
            label.style.padding = '4px 10px';
            label.style.borderRadius = '9999px';
            label.style.background = 'rgba(15,23,42,0.85)';
            label.style.color = '#fff';
            label.style.fontSize = '12px';
            label.style.fontFamily = 'Inter, system-ui, sans-serif';
            label.style.display = 'none';
            document.body.appendChild(label);
            this._dom.loadingLabel = label;
        } else {
            this._dom.loadingLabel = document.getElementById('ui-loading-label');
        }

        if (!document.getElementById('ui-notifications')) {
            const stack = document.createElement('div');
            stack.id = 'ui-notifications';
            stack.setAttribute('aria-live', 'polite');
            stack.setAttribute('aria-atomic', 'false');
            stack.style.position = 'fixed';
            stack.style.top = '1rem';
            stack.style.right = '1rem';
            stack.style.zIndex = '9999';
            stack.style.display = 'flex';
            stack.style.flexDirection = 'column';
            stack.style.gap = '0.5rem';
            stack.style.maxWidth = '380px';
            document.body.appendChild(stack);
            this._dom.notifications = stack;
        } else {
            this._dom.notifications = document.getElementById('ui-notifications');
        }

        if (!document.getElementById('ui-connection-status')) {
            const badge = document.createElement('div');
            badge.id = 'ui-connection-status';
            badge.setAttribute('role', 'status');
            badge.setAttribute('aria-live', 'polite');
            badge.style.position = 'fixed';
            badge.style.bottom = '1rem';
            badge.style.left = '1rem';
            badge.style.zIndex = '9997';
            badge.style.padding = '4px 10px';
            badge.style.borderRadius = '9999px';
            badge.style.fontSize = '12px';
            badge.style.fontFamily = 'Inter, system-ui, sans-serif';
            badge.style.color = '#fff';
            badge.style.background = '#10b981';
            badge.style.display = 'none';
            document.body.appendChild(badge);
            this._dom.connection = badge;
        } else {
            this._dom.connection = document.getElementById('ui-connection-status');
        }

        if (!document.getElementById('ui-live-region')) {
            const live = document.createElement('div');
            live.id = 'ui-live-region';
            live.setAttribute('aria-live', 'polite');
            live.setAttribute('aria-atomic', 'true');
            live.style.position = 'absolute';
            live.style.width = '1px';
            live.style.height = '1px';
            live.style.overflow = 'hidden';
            live.style.clip = 'rect(0 0 0 0)';
            document.body.appendChild(live);
            this._dom.live = live;
        } else {
            this._dom.live = document.getElementById('ui-live-region');
        }
    }

    // ============================================================
    // Public API — Notifications
    // ============================================================

    /**
     * Show a dismissible toast notification.
     *
     * @param {string} message - User-facing message (escaped; never raw HTML).
     * @param {string} [type='info'] - 'success' | 'info' | 'warning' | 'error'.
     * @param {Object} [options]
     * @param {number} [options.duration] - Auto-dismiss ms (0 = sticky).
     * @param {string} [options.title] - Optional heading.
     * @returns {string} Notification id (for manual dismissal).
     */
    showNotification(message, type = 'info', options = {}) {
        if (!this._dom || !this._dom.notifications || typeof document === 'undefined') {
            return '';
        }

        const safeType = NOTIFICATION_COLORS[type] ? type : 'info';
        const id = `notif_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;

        const toast = document.createElement('div');
        toast.id = id;
        toast.setAttribute('role', safeType === 'error' ? 'alert' : 'status');
        toast.style.background = '#fff';
        toast.style.color = '#0f172a';
        toast.style.borderLeft = `4px solid ${NOTIFICATION_COLORS[safeType]}`;
        toast.style.borderRadius = '0.5rem';
        toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
        toast.style.padding = '0.75rem 0.75rem 0.75rem 0.9rem';
        toast.style.display = 'flex';
        toast.style.alignItems = 'flex-start';
        toast.style.gap = '0.5rem';
        toast.style.fontFamily = 'Inter, system-ui, sans-serif';
        toast.style.fontSize = '14px';
        if (!this._reducedMotion) {
            toast.style.animation = 'ui-fade-in 0.2s ease-out';
        }

        const textWrap = document.createElement('div');
        textWrap.style.flex = '1';

        if (options.title) {
            const titleEl = document.createElement('div');
            titleEl.textContent = options.title; // textContent => safe
            titleEl.style.fontWeight = '600';
            titleEl.style.marginBottom = '2px';
            textWrap.appendChild(titleEl);
        }

        const msgEl = document.createElement('div');
        msgEl.textContent = message; // textContent => safe (no HTML injection)
        textWrap.appendChild(msgEl);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Dismiss notification');
        closeBtn.textContent = '×';
        closeBtn.style.background = 'transparent';
        closeBtn.style.border = 'none';
        closeBtn.style.cursor = 'pointer';
        closeBtn.style.fontSize = '18px';
        closeBtn.style.lineHeight = '1';
        closeBtn.style.color = '#64748b';
        closeBtn.addEventListener('click', () => this.hideNotification(id));

        toast.appendChild(textWrap);
        toast.appendChild(closeBtn);
        this._dom.notifications.appendChild(toast);

        const duration =
            options.duration != null
                ? options.duration
                : safeType === 'error'
                ? NOTIFICATION_ERROR_DURATION
                : NOTIFICATION_DEFAULT_DURATION;

        if (duration > 0) {
            setTimeout(() => this.hideNotification(id), duration);
        }

        this._emit('notificationShown', { id, type: safeType, message });
        return id;
    }

    /**
     * Hide (and remove) a notification by id.
     *
     * @param {string} id
     */
    hideNotification(id) {
        if (!this._dom || !this._dom.notifications || !id) {
            return;
        }
        const el = document.getElementById(id);
        if (!el) {
            return;
        }
        if (el.parentNode) {
            el.parentNode.removeChild(el);
        }
        this._emit('notificationHidden', { id });
    }

    // ============================================================
    // Public API — Loading States
    // ============================================================

    /**
     * Register a loading state. Multiple states can be active; the indicator shows
     * while at least one is active, preventing overlapping spinners.
     *
     * @param {string} state - One of: 'uploading' | 'thinking' | 'streaming' |
     *   'rendering' | 'general'.
     * @param {string} [label] - Human-readable label for the indicator.
     */
    showLoading(state = 'general', label) {
        this._loadingStates.add(state);
        if (label) {
            this._loadingLabel = label;
        } else if (!this._loadingLabel) {
            this._loadingLabel = this._stateLabel(state);
        }
        this._renderLoading();
    }

    /**
     * Clear a loading state. Hides the indicator when none remain.
     *
     * @param {string} state
     */
    hideLoading(state = 'general') {
        this._loadingStates.delete(state);
        if (!this._loadingStates.size) {
            this._loadingLabel = '';
        }
        this._renderLoading();
    }

    /**
     * Update the loading indicator DOM from the current state set.
     *
     * @private
     */
    _renderLoading() {
        if (!this._dom || !this._dom.loadingBar) {
            return;
        }
        const active = this._loadingStates.size > 0;

        this._dom.loadingBar.style.display = active ? 'block' : 'none';
        this._dom.loadingBar.style.width = active ? '70%' : '0';

        if (this._dom.loadingLabel) {
            this._dom.loadingLabel.textContent = this._loadingLabel;
            this._dom.loadingLabel.style.display = active && this._loadingLabel ? 'block' : 'none';
        }
    }

    /**
     * Map a loading state to a friendly label.
     *
     * @param {string} state
     * @returns {string}
     * @private
     */
    _stateLabel(state) {
        const labels = {
            uploading: 'Uploading dataset…',
            thinking: 'Analyzing your question…',
            streaming: 'Streaming response…',
            rendering: 'Rendering chart…',
            general: 'Loading…',
        };
        return labels[state] || labels.general;
    }

    // ============================================================
    // Public API — Dataset Panel
    // ============================================================

    /**
     * Update the dataset information panel from an upload payload.
     *
     * @param {Object} detail - Typically a `datasetUploaded` event detail:
     *   { filename, rows, columns, sessionId, metadata: { uploadedAt } }.
     */
    updateDatasetInfo(detail) {
        if (!this._dom || !detail) {
            return;
        }

        const filename = detail.filename != null ? String(detail.filename) : '';
        const rows = detail.rows != null ? detail.rows : null;
        const columns = detail.columns != null ? detail.columns : null;
        const sessionId = detail.sessionId != null ? String(detail.sessionId) : '';
        const uploadedAt =
            detail.metadata && detail.metadata.uploadedAt
                ? detail.metadata.uploadedAt
                : null;

        if (this._dom.datasetName) {
            this._dom.datasetName.textContent = filename; // textContent => safe
        }
        if (this._dom.datasetRows) {
            this._dom.datasetRows.textContent = rows != null ? String(rows) : '';
        }
        if (this._dom.datasetColumns) {
            this._dom.datasetColumns.textContent = columns != null ? String(columns) : '';
        }
        if (this._dom.sessionId) {
            this._dom.sessionId.textContent = sessionId;
        }

        if (uploadedAt && this._dom.datasetInfo) {
            // Append an "uploaded at" line if not already present.
            let timeEl = document.getElementById('dataset-uploaded-at');
            if (!timeEl) {
                timeEl = document.createElement('p');
                timeEl.id = 'dataset-uploaded-at';
                timeEl.className = 'text-xs text-slate-500 mt-1';
                this._dom.datasetInfo.appendChild(timeEl);
            }
            timeEl.textContent = `Uploaded at ${uploadedAt}`;
        }

        if (this._dom.datasetInfo) {
            this._dom.datasetInfo.classList.remove('hidden');
        }

        this._emit('datasetInfoUpdated', { filename, rows, columns, sessionId });
    }

    // ============================================================
    // Public API — Theme
    // ============================================================

    /**
     * Toggle between light and dark (programmatic / future settings use).
     * Does NOT bind the nav toggle button (app.js owns that) to avoid double-toggle.
     */
    toggleTheme() {
        const next = this._theme === 'dark' ? 'light' : 'dark';
        this.setTheme(next);
    }

    /**
     * Set the theme.
     *
     * @param {string} value - 'light' | 'dark' | 'auto'.
     * @param {boolean} [silent=false] - When true, do not re-dispatch themeChanged
     *   (used when syncing from app.js's theme:changed event).
     */
    setTheme(value, silent = false) {
        const theme = value === 'auto' ? 'auto' : value === 'dark' ? 'dark' : 'light';
        this._theme = theme;

        const resolved = this._resolveTheme(theme);
        if (typeof document !== 'undefined') {
            document.documentElement.setAttribute('data-theme', resolved);
        }
        try {
            if (typeof localStorage !== 'undefined') {
                localStorage.setItem(UI_THEME_KEY, theme);
            }
        } catch (e) {
            // localStorage may be unavailable (private mode); ignore.
        }

        if (this._dom && this._dom.themeSelect && this._dom.themeSelect.value !== theme) {
            this._dom.themeSelect.value = theme;
        }

        if (!silent) {
            this._emit('themeChanged', { theme, resolved });
        }
    }

    /**
     * Resolve 'auto' to an explicit light/dark using system preference.
     *
     * @param {string} theme
     * @returns {string}
     * @private
     */
    _resolveTheme(theme) {
        if (theme !== 'auto') {
            return theme;
        }
        if (typeof window !== 'undefined' && window.matchMedia) {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return 'light';
    }

    /**
     * Initialize theme from persisted preference or system setting.
     *
     * @private
     */
    _initTheme() {
        let saved = null;
        try {
            if (typeof localStorage !== 'undefined') {
                saved = localStorage.getItem(UI_THEME_KEY);
            }
        } catch (e) {
            saved = null;
        }

        const initial =
            saved === 'dark' || saved === 'light' || saved === 'auto'
                ? saved
                : 'auto';

        // Apply without dispatching (this is the initial state).
        this.setTheme(initial, true);

        // Keep in sync if app.js changes the theme via the nav button.
        if (typeof document !== 'undefined') {
            document.addEventListener('theme:changed', (e) => {
                const t = e && e.detail && e.detail.theme;
                if (t && t !== this._theme) {
                    this._theme = t;
                    const resolved = this._resolveTheme(t);
                    if (typeof document !== 'undefined') {
                        document.documentElement.setAttribute('data-theme', resolved);
                    }
                    if (this._dom && this._dom.themeSelect) {
                        this._dom.themeSelect.value = t;
                    }
                }
            });
        }
    }

    /**
     * @returns {boolean} True if the user prefers reduced motion.
     * @private
     */
    _prefersReducedMotion() {
        if (typeof window !== 'undefined' && window.matchMedia) {
            return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        }
        return false;
    }

    // ============================================================
    // Public API — Modals
    // ============================================================

    /**
     * Open a modal by name.
     *
     * @param {string} name - e.g. 'settings' or 'settings-modal'.
     */
    openModal(name) {
        const modal = this._resolveModal(name);
        if (!modal) {
            return;
        }
        modal.classList.remove('hidden');
        // Visibility change is detected by the MutationObserver -> modalOpened.
    }

    /**
     * Close a modal by name.
     *
     * @param {string} name
     */
    closeModal(name) {
        const modal = this._resolveModal(name);
        if (!modal) {
            return;
        }
        modal.classList.add('hidden');
        // Visibility change is detected by the MutationObserver -> modalClosed.
    }

    /**
     * Resolve a modal name to its DOM element.
     *
     * @param {string} name
     * @returns {HTMLElement|null}
     * @private
     */
    _resolveModal(name) {
        if (!name || typeof document === 'undefined') {
            return null;
        }
        const id = name.endsWith('-modal') ? name : `${name}-modal`;
        return document.getElementById(id);
    }

    /**
     * Wire close buttons, backdrop clicks, and the MutationObserver that emits
     * modalOpened / modalClosed and manages focus trapping.
     *
     * @private
     */
    _bindModalInfrastructure() {
        if (typeof document === 'undefined' || !this._dom) {
            return;
        }

        // Close buttons (id ending in "-modal-close") within each modal.
        this._dom.modals.forEach((modal) => {
            const closeBtn = modal.querySelector('[id$="-modal-close"]');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.closeModal(this._modalName(modal)));
            }

            // Backdrop click: only when the click target is the modal root itself
            // (i.e. outside the inner card).
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeModal(this._modalName(modal));
                }
            });

            // Observe visibility changes to drive open/close events + focus.
            if (typeof MutationObserver !== 'undefined') {
                const observer = new MutationObserver(() => {
                    const isOpen = !modal.classList.contains('hidden');
                    const wasOpen = Boolean(this._modalStates[this._modalName(modal)]);
                    if (isOpen !== wasOpen) {
                        this._modalStates[this._modalName(modal)] = isOpen;
                        if (isOpen) {
                            this._onModalOpened(this._modalName(modal), modal);
                        } else {
                            this._onModalClosed(this._modalName(modal));
                        }
                    }
                });
                observer.observe(modal, { attributes: true, attributeFilter: ['class'] });
            }
        });

        // Global Escape closes the topmost open modal.
        this._handlers.escapeKey = this._handleEscapeKey.bind(this);
        document.addEventListener('keydown', this._handlers.escapeKey);

        // Tab focus trap while any modal is open.
        this._handlers.tabTrap = this._handleTabTrap.bind(this);
        document.addEventListener('keydown', this._handlers.tabTrap);
    }

    /**
     * @param {HTMLElement} modal
     * @returns {string} Modal name (without '-modal').
     * @private
     */
    _modalName(modal) {
        return modal.id.replace(/-modal$/, '');
    }

    /**
     * Handle a modal becoming visible.
     *
     * @param {string} name
     * @param {HTMLElement} modal
     * @private
     */
    _onModalOpened(name, modal) {
        this._openModals = this._openModals.filter((n) => n !== name);
        this._openModals.push(name);

        // Save focus to restore on close.
        this._lastFocused = typeof document !== 'undefined' ? document.activeElement : null;

        // Move focus into the modal.
        const focusable = modal.querySelectorAll(FOCUSABLE_SELECTOR);
        if (focusable.length) {
            focusable[0].focus();
        } else {
            modal.setAttribute('tabindex', '-1');
            modal.focus();
        }

        this._emit('modalOpened', { modal: name });
    }

    /**
     * Handle a modal becoming hidden.
     *
     * @param {string} name
     * @private
     */
    _onModalClosed(name) {
        this._openModals = this._openModals.filter((n) => n !== name);

        // Restore focus to the previously focused element.
        if (this._lastFocused && typeof this._lastFocused.focus === 'function') {
            try {
                this._lastFocused.focus();
            } catch (e) {
                // Ignore if the element is no longer in the document.
            }
            this._lastFocused = null;
        }

        this._emit('modalClosed', { modal: name });
    }

    /**
     * Escape key closes the topmost open modal.
     *
     * @param {KeyboardEvent} event
     * @private
     */
    _handleEscapeKey(event) {
        if (event.key !== 'Escape' || !this._openModals.length) {
            return;
        }
        const top = this._openModals[this._openModals.length - 1];
        this.closeModal(top);
    }

    /**
     * Trap Tab focus inside the topmost open modal.
     *
     * @param {KeyboardEvent} event
     * @private
     */
    _handleTabTrap(event) {
        if (event.key !== 'Tab' || !this._openModals.length) {
            return;
        }
        const top = this._openModals[this._openModals.length - 1];
        const modal = this._resolveModal(top);
        if (!modal) {
            return;
        }

        const focusable = Array.prototype.slice.call(modal.querySelectorAll(FOCUSABLE_SELECTOR));
        if (!focusable.length) {
            event.preventDefault();
            return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    // ============================================================
    // Public API — Connection Status
    // ============================================================

    /**
     * Update the connection status indicator.
     *
     * @param {string} status - 'online' | 'offline' | 'connecting' | 'disconnected'.
     * @param {string} [message] - Optional human-readable detail.
     */
    setConnectionStatus(status, message) {
        const valid = ['online', 'offline', 'connecting', 'disconnected'];
        this._connectionStatus = valid.indexOf(status) >= 0 ? status : 'online';

        if (this._dom && this._dom.connection) {
            const badge = this._dom.connection;
            const colors = {
                online: '#10b981',
                connecting: '#f59e0b',
                offline: '#64748b',
                disconnected: '#ef4444',
            };
            badge.style.background = colors[this._connectionStatus] || colors.online;
            badge.textContent = message || this._connectionLabel(this._connectionStatus);
            badge.style.display = this._connectionStatus === 'online' ? 'none' : 'block';
        }

        this._emit('connectionStatusChanged', {
            status: this._connectionStatus,
            message: message || '',
        });
    }

    /**
     * @param {string} status
     * @returns {string}
     * @private
     */
    _connectionLabel(status) {
        const labels = {
            online: 'Connected',
            connecting: 'Connecting…',
            offline: 'Offline',
            disconnected: 'Disconnected',
        };
        return labels[status] || labels.online;
    }

    // ============================================================
    // Public API — Reset
    // ============================================================

    /**
     * Reset all UI to its initial empty state (e.g. on session end).
     */
    clearUI() {
        // Hide dataset panel.
        if (this._dom && this._dom.datasetInfo) {
            this._dom.datasetInfo.classList.add('hidden');
            const timeEl = document.getElementById('dataset-uploaded-at');
            if (timeEl && timeEl.parentNode) {
                timeEl.parentNode.removeChild(timeEl);
            }
        }

        // Clear loading.
        this._loadingStates.clear();
        this._loadingLabel = '';
        this._renderLoading();

        // Close any open modals.
        this._openModals.slice().forEach((name) => this.closeModal(name));

        // Clear notifications.
        if (this._dom && this._dom.notifications) {
            this._dom.notifications.innerHTML = '';
        }

        // Reset connection status.
        this.setConnectionStatus('online');

        this._emit('uiCleared', {});
    }

    // ============================================================
    // Empty States
    // ============================================================

    /**
     * Ensure initial empty-state visibility (no dataset shown, etc.).
     *
     * @private
     */
    _applyEmptyStates() {
        if (this._dom && this._dom.datasetInfo) {
            this._dom.datasetInfo.classList.add('hidden');
        }
        // The chart and chat empty states are owned by their respective modules.
    }

    // ============================================================
    // Event Wiring (incoming frontend events)
    // ============================================================

    /**
     * Bind all incoming event listeners and global UI events.
     *
     * @private
     */
    _bindGlobalEvents() {
        if (typeof document === 'undefined') {
            return;
        }

        const on = (name, fn) => {
            const handler = fn.bind(this);
            this._handlers[name] = handler;
            document.addEventListener(name, handler);
        };

        // Upload lifecycle.
        on('datasetUploadStarted', (e) => {
            const d = (e && e.detail) || {};
            this.showLoading('uploading', 'Uploading dataset…');
            if (d.filename) {
                this._announce(`Upload started for ${d.filename}`);
            }
        });
        on('datasetUploadProgress', () => {
            this.showLoading('uploading', 'Uploading dataset…');
        });
        on('datasetUploaded', (e) => {
            const d = (e && e.detail) || {};
            this.hideLoading('uploading');
            this.updateDatasetInfo(d);
            this.showNotification('Dataset uploaded successfully.', 'success');
        });
        on('datasetUploadFailed', (e) => {
            const d = (e && e.detail) || {};
            this.hideLoading('uploading');
            const msg =
                (d.friendlyMessage) ||
                (d.error && d.error.message) ||
                'Failed to upload the dataset.';
            this.showNotification(msg, 'error');
            this._announce(`Upload failed: ${msg}`);
        });

        // Chat lifecycle.
        on('chatMessageSent', () => {
            // Chat module shows its own typing indicator; nothing extra required.
        });
        on('chatResponseStarted', () => {
            this.showLoading('thinking', 'Analyzing your question…');
        });
        on('chatResponseReceived', () => {
            // Keep thinking until completed.
        });
        on('chatResponseCompleted', () => {
            this.hideLoading('thinking');
        });
        on('chatError', (e) => {
            const d = (e && e.detail) || {};
            this.hideLoading('thinking');
            const msg = (d.friendlyMessage) || (d.error && d.error.message) || 'Chat error occurred.';
            this.showNotification(msg, 'error');
        });

        // Stream lifecycle.
        on('streamStarted', () => {
            this.showLoading('streaming', 'Streaming response…');
            this.setConnectionStatus('connecting');
        });
        on('streamConnected', () => {
            this.setConnectionStatus('online');
        });
        on('streamProgress', (e) => {
            const d = (e && e.detail) || {};
            if (d.stage) {
                this.showLoading('streaming', this._streamLabel(d));
            }
        });
        on('streamCompleted', () => {
            this.hideLoading('streaming');
            this.setConnectionStatus('online');
        });
        on('streamDisconnected', (e) => {
            const d = (e && e.detail) || {};
            this.hideLoading('streaming');
            if (!d.intentional) {
                this.setConnectionStatus('disconnected');
            }
        });
        on('streamError', (e) => {
            const d = (e && e.detail) || {};
            this.hideLoading('streaming');
            this.setConnectionStatus('disconnected');
            const msg = (d.friendlyMessage) || (d.error && d.error.message) || 'Stream error occurred.';
            this.showNotification(msg, 'error');
        });

        // Chart lifecycle.
        on('chartRendered', (e) => {
            const d = (e && e.detail) || {};
            this.hideLoading('rendering');
            if (d.chartType) {
                this._announce(`Chart rendered: ${d.chartType}`);
            }
        });
        on('chartUpdated', () => {
            this.hideLoading('rendering');
        });
        on('chartCleared', () => {
            this.hideLoading('rendering');
        });
        on('chartExported', (e) => {
            const d = (e && e.detail) || {};
            this.showNotification(`Chart exported as ${d.format || 'image'}.`, 'success');
        });
        on('chartError', (e) => {
            const d = (e && e.detail) || {};
            const msg = (d.message) || 'Unable to display the chart.';
            this.showNotification(msg, 'error');
        });

        // Responsive layout.
        if (typeof window !== 'undefined') {
            this._handlers.windowResize = this._handleWindowResize.bind(this);
            window.addEventListener('resize', this._handlers.windowResize);
        }
    }

    /**
     * Build a friendly streaming label from a progress event.
     *
     * @param {Object} detail
     * @returns {string}
     * @private
     */
    _streamLabel(detail) {
        const stage = detail.stage || 'stream';
        const status = detail.status || '';
        const labels = {
            planning: 'Planning analysis…',
            execution: 'Running analysis…',
            explanation: 'Generating explanation…',
            reconnection: 'Reconnecting…',
        };
        if (labels[stage]) {
            return labels[stage];
        }
        return status ? `Streaming (${stage}: ${status})…` : 'Streaming response…';
    }

    /**
     * Window resize handler (debounced). Updates a viewport hint for CSS hooks.
     *
     * @private
     */
    _handleWindowResize() {
        if (typeof clearTimeout === 'function') {
            clearTimeout(this._resizeTimer);
        }
        this._resizeTimer = setTimeout(() => {
            if (typeof document === 'undefined') {
                return;
            }
            const w = window.innerWidth || 0;
            let viewport = 'desktop';
            if (w < 640) {
                viewport = 'mobile';
            } else if (w < 1024) {
                viewport = 'tablet';
            }
            document.body.dataset.viewport = viewport;
            this._emit('viewportChanged', { viewport, width: w });
        }, RESIZE_DEBOUNCE_MS);
    }

    /**
     * Bind settings modal controls (theme select + save button).
     *
     * @private
     */
    _bindSettingsControls() {
        if (!this._dom) {
            return;
        }

        if (this._dom.themeSelect) {
            this._dom.themeSelect.addEventListener('change', (e) => {
                const value = e.target.value;
                if (value) {
                    this.setTheme(value);
                }
            });
        }

        if (this._dom.settingsModalSave) {
            this._dom.settingsModalSave.addEventListener('click', () => {
                this.closeModal('settings');
            });
        }
    }

    // ============================================================
    // Accessibility Helpers
    // ============================================================

    /**
     * Announce a message to screen readers via the aria-live region.
     *
     * @param {string} message
     * @private
     */
    _announce(message) {
        if (this._dom && this._dom.live) {
            this._dom.live.textContent = message;
        }
    }

    // ============================================================
    // Event Dispatch
    // ============================================================

    /**
     * Dispatch a CustomEvent on the document.
     *
     * @param {string} eventName
     * @param {Object} detail
     * @private
     */
    _emit(eventName, detail) {
        if (typeof document === 'undefined') {
            return;
        }
        const event = new CustomEvent(eventName, {
            bubbles: true,
            cancelable: true,
            detail,
        });
        document.dispatchEvent(event);
    }

    // ============================================================
    // Cleanup
    // ============================================================

    /**
     * Remove listeners and release references. Safe to call multiple times.
     */
    destroy() {
        if (typeof document !== 'undefined') {
            Object.keys(this._handlers).forEach((key) => {
                const name = key.replace(/Handler$/, '');
                // Best-effort removal; not all keys map 1:1 to event names.
            });

            if (this._handlers.escapeKey) {
                document.removeEventListener('keydown', this._handlers.escapeKey);
            }
            if (this._handlers.tabTrap) {
                document.removeEventListener('keydown', this._handlers.tabTrap);
            }
            if (this._handlers.windowResize && typeof window !== 'undefined') {
                window.removeEventListener('resize', this._handlers.windowResize);
            }
        }

        this._loadingStates.clear();
        this._openModals = [];
        this._initialized = false;
        console.log('[UI] UIManager destroyed');
    }
}

// ============================================================
// Initialization Function
// ============================================================

/**
 * Initialize the UI module.
 *
 * Creates a UIManager instance, initializes it, and returns it for storage by the
 * application module (app.js), which calls `await window.initializeUI()`.
 *
 * @param {Object} [config] - Optional configuration (e.g. { dom } for tests).
 * @returns {UIManager} The initialized UIManager instance.
 */
function initializeUI(config = {}) {
    const manager = new UIManager(config);
    manager.init();
    return manager;
}

// ============================================================
// Global Exports
// ============================================================

if (typeof window !== 'undefined') {
    // Expose for app.js initialization discovery.
    window.initializeUI = initializeUI;

    // Expose the class for testing and direct access.
    window.UIManager = UIManager;
}

console.log('[UI] UI module loaded');
