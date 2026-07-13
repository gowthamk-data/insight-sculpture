/**
 * Insight Sculpture - Application Entry Point
 * 
 * This module coordinates the entire frontend application.
 * It initializes all modules, manages application lifecycle,
 * and handles global events and state.
 * 
 * Responsibilities:
 * - Application startup and initialization
 * - Module coordination and initialization order
 * - Global event handling
 * - Application state management
 * - Error handling and notifications
 * - Theme management
 * - Connection status monitoring
 * - Keyboard shortcuts
 * - Cleanup and shutdown
 * 
 * @module app
 */

// ============================================================
// Application State
// ============================================================

/**
 * Lightweight application state object.
 * Stores global application state that doesn't belong to specific modules.
 * 
 * @type {Object}
 */
const AppState = {
    /** @type {string|null} Current active session ID */
    currentSessionId: null,
    
    /** @type {string|null} Uploaded filename */
    uploadedFilename: null,
    
    /** @type {Object|null} Dataset metadata from upload response */
    datasetMetadata: null,
    
    /** @type {string} Current theme ('light' or 'dark') */
    theme: 'light',
    
    /** @type {string} Streaming status ('idle', 'connecting', 'streaming', 'error') */
    streamStatus: 'idle',
    
    /** @type {string} Connection status ('online', 'offline') */
    connectionStatus: 'online',
    
    /** @type {boolean} Whether the app is fully initialized */
    isInitialized: false,
    
    /** @type {boolean} Whether a loading screen is active */
    isLoading: true
};

// ============================================================
// Module References
// ============================================================

/**
 * References to initialized modules.
 * Populated during initialization.
 * 
 * @type {Object}
 */
const Modules = {
    api: null,
    upload: null,
    chat: null,
    charts: null,
    stream: null,
    ui: null
};

// ============================================================
// DOM Element Cache
// ============================================================

/**
 * Cache of frequently accessed DOM elements.
 * Populated during initialization to avoid repeated queries.
 * 
 * @type {Object}
 */
const DOM = {
    loadingScreen: null,
    themeToggle: null,
    aboutButton: null,
    settingsButton: null,
    errorModal: null,
    settingsModal: null,
    aboutModal: null
};

// ============================================================
// Initialization Functions
// ============================================================

/**
 * Initialize the entire application.
 * Called when DOM is ready.
 * 
 * @async
 * @returns {Promise<void>}
 */
async function initializeApplication() {
    try {
        console.log('[App] Initializing Insight Sculpture...');
        
        // Cache DOM elements
        cacheDOMElements();
        
        // Initialize theme
        initializeTheme();
        
        // Initialize UI module first (needed by other modules)
        await initializeUI();
        
        // Initialize API client
        await initializeAPI();
        
        // Initialize upload functionality
        await initializeUpload();
        
        // Initialize chat functionality
        await initializeChat();
        
        // Initialize charts functionality
        await initializeCharts();
        
        // Initialize streaming functionality
        await initializeStream();
        
        // Register global event listeners
        registerGlobalEventListeners();
        
        // Register keyboard shortcuts
        registerKeyboardShortcuts();
        
        // Mark as initialized
        AppState.isInitialized = true;
        
        // Hide loading screen
        hideLoadingScreen();
        
        console.log('[App] Application initialized successfully');
        
        // Dispatch app ready event
        dispatchEvent(new CustomEvent('app:ready', { detail: AppState }));
        
    } catch (error) {
        console.error('[App] Initialization failed:', error);
        showInitializationError(error);
    }
}

/**
 * Cache frequently accessed DOM elements.
 * 
 * @private
 */
function cacheDOMElements() {
    DOM.loadingScreen = document.getElementById('loading-screen');
    DOM.themeToggle = document.getElementById('theme-toggle');
    DOM.aboutButton = document.getElementById('about-button');
    DOM.errorModal = document.getElementById('error-modal');
    DOM.settingsModal = document.getElementById('settings-modal');
    DOM.aboutModal = document.getElementById('about-modal');
}

/**
 * Initialize the UI module.
 * 
 * @async
 * @private
 * @returns {Promise<void>}
 */
async function initializeUI() {
    console.log('[App] Initializing UI module...');
    
    if (typeof initializeUI !== 'undefined' && typeof window.initializeUI === 'function') {
        Modules.ui = await window.initializeUI();
    } else if (typeof UI !== 'undefined') {
        Modules.ui = UI;
    } else {
        console.warn('[App] UI module not found, skipping...');
    }
}

/**
 * Initialize the API client module.
 * 
 * @async
 * @private
 * @returns {Promise<void>}
 */
async function initializeAPI() {
    console.log('[App] Initializing API module...');
    
    if (typeof initializeAPI !== 'undefined' && typeof window.initializeAPI === 'function') {
        Modules.api = await window.initializeAPI();
    } else if (typeof API !== 'undefined') {
        Modules.api = API;
    } else {
        console.warn('[App] API module not found, skipping...');
    }
}

/**
 * Initialize the upload module.
 * 
 * @async
 * @private
 * @returns {Promise<void>}
 */
async function initializeUpload() {
    console.log('[App] Initializing upload module...');
    
    if (typeof initializeUpload !== 'undefined' && typeof window.initializeUpload === 'function') {
        Modules.upload = await window.initializeUpload();
    } else if (typeof Upload !== 'undefined') {
        Modules.upload = Upload;
    } else {
        console.warn('[App] Upload module not found, skipping...');
    }
}

/**
 * Initialize the chat module.
 * 
 * @async
 * @private
 * @returns {Promise<void>}
 */
async function initializeChat() {
    console.log('[App] Initializing chat module...');
    
    if (typeof initializeChat !== 'undefined' && typeof window.initializeChat === 'function') {
        Modules.chat = await window.initializeChat();
    } else if (typeof Chat !== 'undefined') {
        Modules.chat = Chat;
    } else {
        console.warn('[App] Chat module not found, skipping...');
    }
}

/**
 * Initialize the charts module.
 * 
 * @async
 * @private
 * @returns {Promise<void>}
 */
async function initializeCharts() {
    console.log('[App] Initializing charts module...');
    
    if (typeof initializeCharts !== 'undefined' && typeof window.initializeCharts === 'function') {
        Modules.charts = await window.initializeCharts();
    } else if (typeof Charts !== 'undefined') {
        Modules.charts = Charts;
    } else {
        console.warn('[App] Charts module not found, skipping...');
    }
}

/**
 * Initialize the streaming module.
 * 
 * @async
 * @private
 * @returns {Promise<void>}
 */
async function initializeStream() {
    console.log('[App] Initializing stream module...');
    
    if (typeof initializeStream !== 'undefined' && typeof window.initializeStream === 'function') {
        Modules.stream = await window.initializeStream();
    } else if (typeof Stream !== 'undefined') {
        Modules.stream = Stream;
    } else {
        console.warn('[App] Stream module not found, skipping...');
    }
}

// ============================================================
// Theme Management
// ============================================================

/**
 * Initialize theme from saved preference or system preference.
 * 
 * @private
 */
function initializeTheme() {
    const savedTheme = localStorage.getItem('theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (savedTheme === 'dark' || (savedTheme === 'auto' && systemPrefersDark)) {
        setTheme('dark');
    } else {
        setTheme('light');
    }
    
    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (localStorage.getItem('theme') === 'auto') {
            setTheme(e.matches ? 'dark' : 'light');
        }
    });
}

/**
 * Set the application theme.
 * 
 * @param {string} theme - 'light' or 'dark'
 * @public
 */
function setTheme(theme) {
    AppState.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    
    // Update theme toggle icon
    if (DOM.themeToggle) {
        const icon = DOM.themeToggle.querySelector('i');
        if (icon) {
            icon.className = theme === 'dark' ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
        }
    }
    
    // Dispatch theme change event
    dispatchEvent(new CustomEvent('theme:changed', { detail: { theme } }));
}

/**
 * Toggle between light and dark theme.
 * 
 * @public
 */
function toggleTheme() {
    const newTheme = AppState.theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
}

// ============================================================
// Global Event Listeners
// ============================================================

/**
 * Register global event listeners.
 * 
 * @private
 */
function registerGlobalEventListeners() {
    // DOM content loaded (already handled by script placement)
    
    // Before unload - warn if there's unsaved work
    window.addEventListener('beforeunload', handleBeforeUnload);
    
    // Visibility change - pause/resume operations
    document.addEventListener('visibilitychange', handleVisibilityChange);
    
    // Online/offline status
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    // Window resize - debounce resize handlers
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(handleResize, 250);
    });
    
    // Theme toggle button
    if (DOM.themeToggle) {
        DOM.themeToggle.addEventListener('click', toggleTheme);
    }
    
    // About button
    if (DOM.aboutButton) {
        DOM.aboutButton.addEventListener('click', () => showModal('about'));
    }
    
    // Modal close buttons
    document.querySelectorAll('[id$="-modal-close"]').forEach(button => {
        button.addEventListener('click', (e) => {
            const modalId = e.target.closest('[id$="-modal"]').id;
            hideModal(modalId);
        });
    });
    
    // Modal backdrop clicks
    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) {
                const modalId = backdrop.querySelector('[id$="-modal"]')?.id;
                if (modalId) hideModal(modalId);
            }
        });
    });
    
    // Global error handlers
    window.addEventListener('error', handleGlobalError);
    window.addEventListener('unhandledrejection', handleUnhandledRejection);
    
    // Custom event listeners for module communication
    setupModuleEventListeners();
}

/**
 * Setup event listeners for inter-module communication.
 * 
 * @private
 */
function setupModuleEventListeners() {
    // Upload completed
    document.addEventListener('upload:completed', handleUploadCompleted);
    
    // Session changed
    document.addEventListener('session:changed', handleSessionChanged);
    
    // Stream status changed
    document.addEventListener('stream:status', handleStreamStatusChanged);
}

/**
 * Handle upload completed event.
 * 
 * @param {CustomEvent} event 
 * @private
 */
function handleUploadCompleted(event) {
    const { sessionId, filename, metadata } = event.detail;
    AppState.currentSessionId = sessionId;
    AppState.uploadedFilename = filename;
    AppState.datasetMetadata = metadata;
    
    console.log('[App] Upload completed:', { sessionId, filename });
}

/**
 * Handle session changed event.
 * 
 * @param {CustomEvent} event 
 * @private
 */
function handleSessionChanged(event) {
    const { sessionId } = event.detail;
    AppState.currentSessionId = sessionId;
    
    console.log('[App] Session changed:', sessionId);
}

/**
 * Handle stream status changed event.
 * 
 * @param {CustomEvent} event 
 * @private
 */
function handleStreamStatusChanged(event) {
    const { status } = event.detail;
    AppState.streamStatus = status;
    
    console.log('[App] Stream status changed:', status);
}

/**
 * Handle before unload event.
 * 
 * @param {Event} event 
 * @private
 */
function handleBeforeUnload(event) {
    // Check if there's active streaming or unsaved work
    if (AppState.streamStatus === 'streaming') {
        event.preventDefault();
        event.returnValue = '';
    }
}

/**
 * Handle visibility change event.
 * 
 * @private
 */
function handleVisibilityChange() {
    if (document.hidden) {
        // Page hidden - pause non-critical operations
        console.log('[App] Page hidden, pausing operations');
        dispatchEvent(new CustomEvent('app:pause'));
    } else {
        // Page visible - resume operations
        console.log('[App] Page visible, resuming operations');
        dispatchEvent(new CustomEvent('app:resume'));
    }
}

/**
 * Handle online event.
 * 
 * @private
 */
function handleOnline() {
    AppState.connectionStatus = 'online';
    console.log('[App] Connection restored');
    showNotification('Connection restored', 'success');
    dispatchEvent(new CustomEvent('connection:online'));
}

/**
 * Handle offline event.
 * 
 * @private
 */
function handleOffline() {
    AppState.connectionStatus = 'offline';
    console.log('[App] Connection lost');
    showNotification('Connection lost. Some features may be unavailable.', 'warning');
    dispatchEvent(new CustomEvent('connection:offline'));
}

/**
 * Handle window resize event.
 * 
 * @private
 */
function handleResize() {
    console.log('[App] Window resized');
    dispatchEvent(new CustomEvent('app:resized'));
}

/**
 * Handle global error event.
 * 
 * @param {ErrorEvent} event 
 * @private
 */
function handleGlobalError(event) {
    console.error('[App] Global error:', event.error);
    
    // Don't show error for script loading errors (handled by browser)
    if (event.message.includes('Loading chunk')) {
        return;
    }
    
    // Show user-friendly error notification
    showNotification('An unexpected error occurred. Please refresh the page.', 'error');
}

/**
 * Handle unhandled promise rejection.
 * 
 * @param {PromiseRejectionEvent} event 
 * @private
 */
function handleUnhandledRejection(event) {
    console.error('[App] Unhandled rejection:', event.reason);
    
    // Prevent default error logging
    event.preventDefault();
    
    // Show user-friendly error notification
    showNotification('An unexpected error occurred. Please try again.', 'error');
}

// ============================================================
// Keyboard Shortcuts
// ============================================================

/**
 * Register keyboard shortcuts.
 * 
 * @private
 */
function registerKeyboardShortcuts() {
    document.addEventListener('keydown', handleKeyboardShortcut);
}

/**
 * Handle keyboard shortcut.
 * 
 * @param {KeyboardEvent} event 
 * @private
 */
function handleKeyboardShortcut(event) {
    // Ctrl/Cmd + Enter: Send question
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        dispatchEvent(new CustomEvent('shortcut:send'));
    }
    
    // Escape: Close modals
    if (event.key === 'Escape') {
        closeAllModals();
    }
    
    // Ctrl/Cmd + L: Clear chat
    if ((event.ctrlKey || event.metaKey) && event.key === 'l') {
        event.preventDefault();
        dispatchEvent(new CustomEvent('shortcut:clear'));
    }
    
    // Ctrl/Cmd + /: Focus search/input
    if ((event.ctrlKey || event.metaKey) && event.key === '/') {
        event.preventDefault();
        const input = document.getElementById('question-input');
        if (input) input.focus();
    }
}

// ============================================================
// Modal Management
// ============================================================

/**
 * Show a modal by ID.
 * 
 * @param {string} modalId - The ID of the modal to show
 * @public
 */
function showModal(modalId) {
    const modal = document.getElementById(`${modalId}-modal`);
    if (modal) {
        modal.classList.remove('hidden');
        // Focus first focusable element
        const focusable = modal.querySelector('button, input, select, textarea');
        if (focusable) focusable.focus();
    }
}

/**
 * Hide a modal by ID.
 * 
 * @param {string} modalId - The ID of the modal to hide
 * @public
 */
function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('hidden');
    }
}

/**
 * Close all open modals.
 * 
 * @public
 */
function closeAllModals() {
    document.querySelectorAll('[id$="-modal"]').forEach(modal => {
        modal.classList.add('hidden');
    });
}

// ============================================================
// Notification System
// ============================================================

/**
 * Show a notification to the user.
 * 
 * @param {string} message - The notification message
 * @param {string} type - The notification type ('success', 'warning', 'error', 'info')
 * @param {number} duration - Duration in milliseconds (default: 5000)
 * @public
 */
function showNotification(message, type = 'info', duration = 5000) {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.setAttribute('role', 'alert');
    notification.textContent = message;
    
    // Add styles
    Object.assign(notification.style, {
        position: 'fixed',
        top: '1rem',
        right: '1rem',
        padding: '1rem',
        borderRadius: '0.5rem',
        backgroundColor: getNotificationColor(type),
        color: 'white',
        boxShadow: '0 4px 6px rgba(0, 0, 0, 0.1)',
        zIndex: '9999',
        animation: 'slideIn 0.3s ease-out',
        maxWidth: '400px',
        wordWrap: 'break-word'
    });
    
    // Add to DOM
    document.body.appendChild(notification);
    
    // Auto-remove after duration
    setTimeout(() => {
        notification.style.animation = 'fadeOut 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, duration);
    
    // Dispatch notification event
    dispatchEvent(new CustomEvent('notification:shown', { detail: { message, type } }));
}

/**
 * Get notification background color by type.
 * 
 * @param {string} type 
 * @returns {string}
 * @private
 */
function getNotificationColor(type) {
    const colors = {
        success: '#10b981',
        warning: '#f59e0b',
        error: '#ef4444',
        info: '#0ea5e9'
    };
    return colors[type] || colors.info;
}

// ============================================================
// Loading Screen
// ============================================================

/**
 * Hide the loading screen.
 * 
 * @private
 */
function hideLoadingScreen() {
    AppState.isLoading = false;
    
    const loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
        loadingScreen.style.opacity = '0';
        loadingScreen.style.transition = 'opacity 0.3s ease-out';
        setTimeout(() => loadingScreen.remove(), 300);
    }
}

/**
 * Show initialization error.
 * 
 * @param {Error} error 
 * @private
 */
function showInitializationError(error) {
    hideLoadingScreen();
    
    const errorMessage = 'Failed to initialize the application. Please refresh the page.';
    showNotification(errorMessage, 'error');
    
    // Show error modal with details
    const errorModal = document.getElementById('error-modal');
    const errorModalMessage = document.getElementById('error-modal-message');
    
    if (errorModal && errorModalMessage) {
        errorModalMessage.textContent = errorMessage;
        errorModal.classList.remove('hidden');
    }
}

// ============================================================
// Cleanup and Shutdown
// ============================================================

/**
 * Cleanup application resources.
 * Called before page unload.
 * 
 * @public
 */
function cleanup() {
    console.log('[App] Cleaning up...');
    
    // Close active streams
    if (Modules.stream && typeof Modules.stream.close === 'function') {
        Modules.stream.close();
    }
    
    // Remove event listeners
    window.removeEventListener('beforeunload', handleBeforeUnload);
    window.removeEventListener('online', handleOnline);
    window.removeEventListener('offline', handleOffline);
    window.removeEventListener('error', handleGlobalError);
    window.removeEventListener('unhandledrejection', handleUnhandledRejection);
    
    // Dispatch cleanup event for modules
    dispatchEvent(new CustomEvent('app:cleanup'));
    
    console.log('[App] Cleanup complete');
}

// ============================================================
// Public API
// ============================================================

/**
 * Get the current application state.
 * 
 * @returns {Object} A copy of the application state
 * @public
 */
function getAppState() {
    return { ...AppState };
}

/**
 * Get a module reference.
 * 
 * @param {string} moduleName - The name of the module ('api', 'upload', 'chat', 'charts', 'stream', 'ui')
 * @returns {Object|null} The module reference or null if not found
 * @public
 */
function getModule(moduleName) {
    return Modules[moduleName] || null;
}

/**
 * Update application state.
 * 
 * @param {Object} updates - State updates to apply
 * @public
 */
function updateAppState(updates) {
    Object.assign(AppState, updates);
    dispatchEvent(new CustomEvent('state:changed', { detail: AppState }));
}

// ============================================================
// Application Entry Point
// ============================================================

/**
 * Initialize the application when DOM is ready.
 */
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApplication);
} else {
    // DOM already loaded
    initializeApplication();
}

// Export public API for external access (if needed)
window.InsightSculptureApp = {
    getAppState,
    getModule,
    updateAppState,
    setTheme,
    toggleTheme,
    showModal,
    hideModal,
    closeAllModals,
    showNotification,
    cleanup
};

console.log('[App] Insight Sculpture app.js loaded');
