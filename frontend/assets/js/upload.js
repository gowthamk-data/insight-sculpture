/**
 * Insight Sculpture - Upload Manager Module
 *
 * This module is responsible ONLY for dataset upload functionality.
 * It handles file selection, drag-and-drop, client-side validation,
 * upload via ApiClient, and dataset metadata display.
 *
 * Responsibilities:
 * - Drag-and-drop file selection with visual feedback
 * - File input dialog via button click
 * - Client-side validation (extension, size, non-empty)
 * - Upload via ApiClient.uploadDataset()
 * - Dataset metadata display
 * - Custom event dispatch for other modules
 *
 * Dependencies:
 * - ApiClient from api.js (via window.API.client or window.apiClient)
 *
 * @module upload
 */

// ============================================================
// Constants
// ============================================================

/** @const {string[]} Allowed file extensions. */
const ALLOWED_EXTENSIONS = ['.csv', '.xlsx', '.xls'];

/** @const {string} Human-readable list of supported formats. */
const SUPPORTED_FORMATS = 'CSV, XLSX, XLS';

/** @const {number} Maximum file size in bytes (50 MB). */
const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024;

/** @const {number} Size in MB for display. */
const MAX_FILE_SIZE_MB = 50;

/** @const {string} Valid HTML accept attribute value for file input. */
const ACCEPT_ATTRIBUTE = ALLOWED_EXTENSIONS.join(',');

/** @const {number} Drag-over highlight debounce in milliseconds. */
const DRAG_DEBOUNCE_MS = 100;

// ============================================================
// Upload States
// ============================================================

/**
 * Enum for upload UI states.
 *
 * @readonly
 * @enum {string}
 */
const UploadState = Object.freeze({
    IDLE: 'idle',
    DRAGGING: 'dragging',
    UPLOADING: 'uploading',
    SUCCESS: 'success',
    FAILED: 'failed',
});

// ============================================================
// Upload Manager Class
// ============================================================

class UploadManager {
    /**
     * Create an UploadManager instance.
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
         * Current upload state.
         * @private
         * @type {string}
         */
        this._state = UploadState.IDLE;

        /**
         * Whether the module has been initialized.
         * @private
         * @type {boolean}
         */
        this._initialized = false;

        /**
         * Currently selected file (before upload).
         * @private
         * @type {File|null}
         */
        this._selectedFile = null;

        /**
         * Current session ID from successful upload.
         * @private
         * @type {string|null}
         */
        this._sessionId = null;

        /**
         * Cached DOM elements.
         * @private
         * @type {Object}
         */
        this._dom = {
            uploadArea: null,
            fileInput: null,
            uploadButton: null,
            uploadStatus: null,
            selectedFilename: null,
            uploadProgress: null,
            uploadSpinner: null,
            datasetInfo: null,
            datasetName: null,
            datasetRows: null,
            datasetColumns: null,
            sessionId: null,
        };

        /**
         * Bound event handlers (for removal).
         * @private
         * @type {Object}
         */
        this._handlers = {};

        /**
         * Drag counter for tracking nested drag enter/leave.
         * @private
         * @type {number}
         */
        this._dragCounter = 0;

        /**
         * Debounce timer for drag visual updates.
         * @private
         * @type {number|null}
         */
        this._dragTimer = null;
    }

    // ============================================================
    // Initialization
    // ============================================================

    /**
     * Initialize the upload interface.
     *
     * Caches DOM elements, sets up event listeners, and returns
     * the UploadManager instance for the application to store.
     *
     * @returns {UploadManager} This instance for chaining and module storage.
     */
    init() {
        if (this._initialized) {
            console.warn('[Upload] Already initialized, skipping.');
            return this;
        }

        this._cacheDOMElements();
        this._bindEventListeners();
        this._setState(UploadState.IDLE);

        this._initialized = true;
        console.log('[Upload] UploadManager initialized');

        return this;
    }

    /**
     * Cache frequently accessed DOM elements.
     *
     * @private
     */
    _cacheDOMElements() {
        const $ = (id) => document.getElementById(id);

        this._dom.uploadArea = $('upload-area');
        this._dom.fileInput = $('file-input');
        this._dom.uploadButton = $('upload-button');
        this._dom.uploadStatus = $('upload-status');
        this._dom.selectedFilename = $('selected-filename');
        this._dom.uploadProgress = $('upload-progress');
        this._dom.uploadSpinner = $('upload-spinner');
        this._dom.datasetInfo = $('dataset-info');
        this._dom.datasetName = $('dataset-name');
        this._dom.datasetRows = $('dataset-rows');
        this._dom.datasetColumns = $('dataset-columns');
        this._dom.sessionId = $('session-id');
    }

    /**
     * Bind event listeners for upload interactions.
     *
     * @private
     */
    _bindEventListeners() {
        const dom = this._dom;
        const area = dom.uploadArea;
        const input = dom.fileInput;
        const button = dom.uploadButton;

        // Drag and drop events on the upload area
        if (area) {
            this._handlers.dragEnter = this._handleDragEnter.bind(this);
            this._handlers.dragOver = this._handleDragOver.bind(this);
            this._handlers.dragLeave = this._handleDragLeave.bind(this);
            this._handlers.drop = this._handleDrop.bind(this);

            area.addEventListener('dragenter', this._handlers.dragEnter);
            area.addEventListener('dragover', this._handlers.dragOver);
            area.addEventListener('dragleave', this._handlers.dragLeave);
            area.addEventListener('drop', this._handlers.drop);

            // Click on upload area triggers file input
            this._handlers.areaClick = this._handleAreaClick.bind(this);
            area.addEventListener('click', this._handlers.areaClick);
        }

        // Upload button click triggers file input
        if (button) {
            this._handlers.buttonClick = this._handleButtonClick.bind(this);
            button.addEventListener('click', this._handlers.buttonClick);
        }

        // File input change (file selected via dialog)
        if (input) {
            this._handlers.inputChange = this._handleInputChange.bind(this);
            input.addEventListener('change', this._handlers.inputChange);
        }
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
            '[Upload] ApiClient not found. Ensure api.js is loaded before upload.js.'
        );
    }

    // ============================================================
    // Public API
    // ============================================================

    /**
     * Get the current upload state.
     *
     * @returns {string} Current UploadState value.
     */
    getState() {
        return this._state;
    }

    /**
     * Get the current session ID from a successful upload.
     *
     * @returns {string|null} Session ID or null if no upload completed.
     */
    getSessionId() {
        return this._sessionId;
    }

    /**
     * Reset the upload state and UI.
     *
     * Clears the selected file, hides dataset info, and returns
     * the upload area to idle state.
     */
    reset() {
        this._selectedFile = null;
        this._sessionId = null;

        this._hideUploadStatus();
        this._hideDatasetInfo();
        this._clearFileInput();
        this._removeDragStyles();
        this._setState(UploadState.IDLE);
    }

    // ============================================================
    // File Selection
    // ============================================================

    /**
     * Open the native file picker dialog.
     *
     * @private
     */
    _openFileDialog() {
        const input = this._dom.fileInput;
        if (input) {
            input.value = '';
            input.click();
        }
    }

    /**
     * Process a selected file through validation and upload.
     *
     * @param {File} file - The file to process.
     * @private
     */
    _processFile(file) {
        try {
            this._validateFile(file);
        } catch (validationError) {
            this._showValidationError(validationError.message);
            return;
        }

        this._selectedFile = file;
        this._showSelectedFile(file);
        this._startUpload(file);
    }

    /**
     * Clear the file input value to allow re-selecting the same file.
     *
     * @private
     */
    _clearFileInput() {
        const input = this._dom.fileInput;
        if (input) {
            input.value = '';
        }
    }

    // ============================================================
    // Validation
    // ============================================================

    /**
     * Validate a file before upload.
     *
     * @param {File} file - The file to validate.
     * @returns {boolean} True if the file is valid.
     * @throws {Error} With a user-friendly message if invalid.
     * @private
     */
    _validateFile(file) {
        if (!file) {
            throw new Error('No file selected. Please choose a file to upload.');
        }

        if (!file.name || file.name.trim().length === 0) {
            throw new Error('The selected file has an invalid name.');
        }

        const extension = this._getFileExtension(file.name);
        if (!extension || !ALLOWED_EXTENSIONS.includes(extension)) {
            throw new Error(
                `Unsupported file type "${extension || 'unknown'}". ` +
                `Please upload a ${SUPPORTED_FORMATS} file.`
            );
        }

        if (file.size === 0) {
            throw new Error('The selected file is empty. Please choose a file with data.');
        }

        if (file.size > MAX_FILE_SIZE_BYTES) {
            const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
            throw new Error(
                `File size (${sizeMB} MB) exceeds the maximum allowed size of ${MAX_FILE_SIZE_MB} MB.`
            );
        }

        return true;
    }

    /**
     * Extract the file extension from a filename.
     *
     * @param {string} filename - The file name.
     * @returns {string|null} Lowercase extension including dot, or null if none.
     * @private
     */
    _getFileExtension(filename) {
        if (!filename || typeof filename !== 'string') {
            return null;
        }

        const dotIndex = filename.lastIndexOf('.');
        if (dotIndex === -1) {
            return null;
        }

        return filename.substring(dotIndex).toLowerCase();
    }

    /**
     * Validate a dropped item is a file.
     *
     * @param {DataTransferItem} item - The drag data item.
     * @returns {boolean} True if the item is a file.
     * @private
     */
    _isFileItem(item) {
        return item && item.kind === 'file';
    }

    // ============================================================
    // Upload
    // ============================================================

    /**
     * Start the upload process for a validated file.
     *
     * @param {File} file - The validated file to upload.
     * @returns {Promise<void>}
     * @private
     */
    async _startUpload(file) {
        this._setState(UploadState.UPLOADING);
        this._showUploadingState(file.name);
        this._disableInput();

        this._dispatchEvent('datasetUploadStarted', {
            filename: file.name,
            fileSize: file.size,
            fileType: file.type,
        });

        try {
            const response = await this._apiClient.uploadDataset(file);

            this._sessionId = response.session_id;

            this._setState(UploadState.SUCCESS);
            this._showSuccessState(response);
            this._enableInput();

            this._dispatchEvent('datasetUploaded', {
                sessionId: response.session_id,
                filename: response.filename,
                rows: response.rows,
                columns: response.columns,
                profile: response.profile,
            });

            this._dispatchEvent('upload:completed', {
                sessionId: response.session_id,
                filename: response.filename,
                metadata: {
                    rows: response.rows,
                    columns: response.columns,
                    profile: response.profile,
                    uploadedAt: response.uploaded_at,
                },
            });

            console.log('[Upload] Upload successful:', {
                sessionId: response.session_id,
                filename: response.filename,
                rows: response.rows,
                columns: response.columns,
            });
        } catch (error) {
            this._setState(UploadState.FAILED);
            this._showUploadError(error);
            this._enableInput();

            this._dispatchEvent('datasetUploadFailed', {
                filename: file.name,
                error: error,
                friendlyMessage: this._getFriendlyErrorMessage(error),
            });

            console.error('[Upload] Upload failed:', error.message || error);
        }
    }

    // ============================================================
    // UI State: Upload Status
    // ============================================================

    /**
     * Show the selected file in the upload status area.
     *
     * @param {File} file - The selected file.
     * @private
     */
    _showSelectedFile(file) {
        const dom = this._dom;
        const status = dom.uploadStatus;
        const filename = dom.selectedFilename;
        const progress = dom.uploadProgress;

        if (status) {
            status.classList.remove('hidden');
            status.classList.remove('success', 'error');
        }

        if (filename) {
            filename.textContent = file.name;
        }

        if (progress) {
            const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
            progress.textContent = `Ready to upload (${sizeMB} MB)`;
        }

        this._hideSpinner();
    }

    /**
     * Show uploading state with spinner.
     *
     * @param {string} filename - The file being uploaded.
     * @private
     */
    _showUploadingState(filename) {
        const dom = this._dom;
        const status = dom.uploadStatus;
        const nameEl = dom.selectedFilename;
        const progress = dom.uploadProgress;

        if (status) {
            status.classList.remove('hidden');
            status.classList.remove('success', 'error');
        }

        if (nameEl) {
            nameEl.textContent = filename;
        }

        if (progress) {
            progress.textContent = 'Uploading and analyzing...';
        }

        this._showSpinner();
    }

    /**
     * Show success state after a completed upload.
     *
     * @param {Object} response - The upload response from ApiClient.
     * @private
     */
    _showSuccessState(response) {
        const dom = this._dom;

        // Update upload status
        if (dom.uploadStatus) {
            dom.uploadStatus.classList.remove('hidden', 'error');
            dom.uploadStatus.classList.add('success');
        }

        if (dom.selectedFilename) {
            dom.selectedFilename.textContent = response.filename;
        }

        if (dom.uploadProgress) {
            dom.uploadProgress.textContent = `Upload complete — ${response.rows.toLocaleString()} rows, ${response.columns} columns`;
        }

        this._hideSpinner();

        // Show dataset info card
        this._showDatasetInfo(response);
    }

    /**
     * Show an error in the upload status area.
     *
     * @param {Error} error - The error that occurred.
     * @private
     */
    _showUploadError(error) {
        const dom = this._dom;
        const friendlyMessage = this._getFriendlyErrorMessage(error);

        if (dom.uploadStatus) {
            dom.uploadStatus.classList.remove('hidden', 'success');
            dom.uploadStatus.classList.add('error');
        }

        if (dom.uploadProgress) {
            dom.uploadProgress.textContent = friendlyMessage;
        }

        this._hideSpinner();
    }

    /**
     * Show a validation error message.
     *
     * @param {string} message - The validation error message.
     * @private
     */
    _showValidationError(message) {
        const dom = this._dom;

        // Briefly highlight the upload area
        if (dom.uploadArea) {
            dom.uploadArea.classList.add('border-red-400', 'ring-2', 'ring-red-200');
            setTimeout(() => {
                if (dom.uploadArea) {
                    dom.uploadArea.classList.remove('border-red-400', 'ring-2', 'ring-red-200');
                }
            }, 2000);
        }

        // Show error in the status area
        if (dom.uploadStatus) {
            dom.uploadStatus.classList.remove('hidden', 'success');
            dom.uploadStatus.classList.add('error');
        }

        if (dom.selectedFilename) {
            dom.selectedFilename.textContent = 'Validation failed';
        }

        if (dom.uploadProgress) {
            dom.uploadProgress.textContent = message;
        }

        this._hideSpinner();
    }

    /**
     * Hide the upload status area.
     *
     * @private
     */
    _hideUploadStatus() {
        const dom = this._dom;
        if (dom.uploadStatus) {
            dom.uploadStatus.classList.add('hidden');
            dom.uploadStatus.classList.remove('success', 'error');
        }
        if (dom.selectedFilename) {
            dom.selectedFilename.textContent = '';
        }
        if (dom.uploadProgress) {
            dom.uploadProgress.textContent = '';
        }
        this._hideSpinner();
    }

    // ============================================================
    // UI State: Dataset Info
    // ============================================================

    /**
     * Show the dataset information card with upload metadata.
     *
     * @param {Object} response - The upload response.
     * @private
     */
    _showDatasetInfo(response) {
        const dom = this._dom;

        if (dom.datasetInfo) {
            dom.datasetInfo.classList.remove('hidden');
        }

        if (dom.datasetName) {
            dom.datasetName.textContent = response.filename || 'Unknown';
        }

        if (dom.datasetRows) {
            dom.datasetRows.textContent = (response.rows || 0).toLocaleString();
        }

        if (dom.datasetColumns) {
            dom.datasetColumns.textContent = (response.columns || 0).toLocaleString();
        }

        if (dom.sessionId) {
            dom.sessionId.textContent = response.session_id || '';
        }
    }

    /**
     * Hide the dataset information card.
     *
     * @private
     */
    _hideDatasetInfo() {
        const dom = this._dom;
        if (dom.datasetInfo) {
            dom.datasetInfo.classList.add('hidden');
        }
        if (dom.datasetName) {
            dom.datasetName.textContent = '';
        }
        if (dom.datasetRows) {
            dom.datasetRows.textContent = '';
        }
        if (dom.datasetColumns) {
            dom.datasetColumns.textContent = '';
        }
        if (dom.sessionId) {
            dom.sessionId.textContent = '';
        }
    }

    // ============================================================
    // Spinner
    // ============================================================

    /**
     * Show the upload spinner.
     *
     * @private
     */
    _showSpinner() {
        const spinner = this._dom.uploadSpinner;
        if (spinner) {
            spinner.classList.remove('hidden');
        }
    }

    /**
     * Hide the upload spinner.
     *
     * @private
     */
    _hideSpinner() {
        const spinner = this._dom.uploadSpinner;
        if (spinner) {
            spinner.classList.add('hidden');
        }
    }

    // ============================================================
    // Drag and Drop
    // ============================================================

    /**
     * Handle dragenter event on the upload area.
     *
     * @param {DragEvent} event - The drag event.
     * @private
     */
    _handleDragEnter(event) {
        event.preventDefault();
        event.stopPropagation();

        this._dragCounter += 1;

        if (this._state === UploadState.IDLE || this._state === UploadState.FAILED) {
            this._setState(UploadState.DRAGGING);
            this._addDragStyles();
        }
    }

    /**
     * Handle dragover event on the upload area.
     *
     * @param {DragEvent} event - The drag event.
     * @private
     */
    _handleDragOver(event) {
        event.preventDefault();
        event.stopPropagation();

        // Reset the debounce timer to keep the drag style active
        if (this._dragTimer) {
            clearTimeout(this._dragTimer);
        }
        this._dragTimer = setTimeout(() => {
            this._addDragStyles();
        }, 10);
    }

    /**
     * Handle dragleave event on the upload area.
     *
     * @param {DragEvent} event - The drag event.
     * @private
     */
    _handleDragLeave(event) {
        event.preventDefault();
        event.stopPropagation();

        this._dragCounter -= 1;

        if (this._dragCounter <= 0) {
            this._dragCounter = 0;
            if (this._state === UploadState.DRAGGING) {
                this._setState(UploadState.IDLE);
                this._removeDragStyles();
            }
        }
    }

    /**
     * Handle drop event on the upload area.
     *
     * @param {DragEvent} event - The drop event.
     * @private
     */
    _handleDrop(event) {
        event.preventDefault();
        event.stopPropagation();

        this._dragCounter = 0;
        this._removeDragStyles();

        if (this._state === UploadState.UPLOADING) {
            return;
        }

        const files = event.dataTransfer && event.dataTransfer.files;
        if (!files || files.length === 0) {
            return;
        }

        const file = files[0];
        if (file) {
            this._setState(UploadState.IDLE);
            this._processFile(file);
        }
    }

    /**
     * Add visual drag-over styles to the upload area.
     *
     * @private
     */
    _addDragStyles() {
        const area = this._dom.uploadArea;
        if (area) {
            area.classList.add('border-primary-500', 'bg-primary-50', 'scale-102');
        }
    }

    /**
     * Remove visual drag-over styles from the upload area.
     *
     * @private
     */
    _removeDragStyles() {
        const area = this._dom.uploadArea;
        if (area) {
            area.classList.remove('border-primary-500', 'bg-primary-50', 'scale-102');
        }
    }

    // ============================================================
    // Input State Management
    // ============================================================

    /**
     * Enable the upload button and file input.
     *
     * @private
     */
    _enableInput() {
        const button = this._dom.uploadButton;
        if (button) {
            button.disabled = false;
        }
    }

    /**
     * Disable the upload button and file input during upload.
     *
     * @private
     */
    _disableInput() {
        const button = this._dom.uploadButton;
        if (button) {
            button.disabled = true;
        }
    }

    // ============================================================
    // Event Handlers
    // ============================================================

    /**
     * Handle click on the upload area (open file dialog).
     *
     * @private
     */
    _handleAreaClick() {
        if (this._state === UploadState.UPLOADING) {
            return;
        }
        this._openFileDialog();
    }

    /**
     * Handle click on the Select File button.
     *
     * @param {Event} event - The click event.
     * @private
     */
    _handleButtonClick(event) {
        event.stopPropagation();

        if (this._state === UploadState.UPLOADING) {
            return;
        }
        this._openFileDialog();
    }

    /**
     * Handle file input change (file selected via dialog).
     *
     * @param {Event} event - The change event.
     * @private
     */
    _handleInputChange(event) {
        const files = event.target && event.target.files;
        if (!files || files.length === 0) {
            return;
        }

        const file = files[0];
        if (file) {
            this._processFile(file);
        }
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
            return 'An unexpected error occurred. Please try again.';
        }

        const code = error.code || error.name || '';
        const message = error.message || String(error);

        // ApiClient error classes
        if (code === 'NETWORK_ERROR') {
            return 'Unable to connect to the server. Please check your network connection and try again.';
        }
        if (code === 'TIMEOUT_ERROR') {
            return 'The upload took too long. Please try again with a smaller file or slower connection.';
        }
        if (code === 'VALIDATION_ERROR') {
            // Extract the backend validation detail if available
            if (error.details && error.details.message) {
                return error.details.message;
            }
            return 'The file could not be validated. Please check the file and try again.';
        }
        if (code === 'AUTHENTICATION_ERROR') {
            return 'Authentication failed. The server configuration may need to be updated.';
        }
        if (code === 'HTTP_ERROR') {
            const status = error.statusCode;
            if (status === 413) {
                return `File size exceeds the maximum allowed size of ${MAX_FILE_SIZE_MB} MB.`;
            }
            if (status === 415) {
                return 'Unsupported file type. Please upload a CSV or Excel file.';
            }
            if (status === 422) {
                return 'The server could not process the file. Please check the file format and try again.';
            }
            if (status === 503) {
                return 'The server is temporarily unavailable. Please try again in a moment.';
            }
        }

        // Backend validation errors from response
        if (message.includes('Unsupported file extension')) {
            return `Unsupported file type. Please upload a ${SUPPORTED_FORMATS} file.`;
        }
        if (message.includes('empty')) {
            return 'The uploaded file is empty. Please choose a file with data.';
        }
        if (message.includes('Failed to parse') || message.includes('Failed to load')) {
            return 'The file could not be read. Please check the file format and try again.';
        }

        // Generic fallback
        return 'An error occurred during upload. Please try again.';
    }

    // ============================================================
    // State Management
    // ============================================================

    /**
     * Set the current upload state.
     *
     * @param {string} newState - One of UploadState values.
     * @private
     */
    _setState(newState) {
        const previousState = this._state;
        this._state = newState;

        this._dispatchEvent('upload:stateChanged', {
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
    // Cleanup
    // ============================================================

    /**
     * Remove event listeners and clean up resources.
     *
     * Called by app.js during shutdown.
     */
    destroy() {
        const dom = this._dom;
        const area = dom.uploadArea;
        const button = dom.uploadButton;
        const input = dom.fileInput;

        if (area) {
            area.removeEventListener('dragenter', this._handlers.dragEnter);
            area.removeEventListener('dragover', this._handlers.dragOver);
            area.removeEventListener('dragleave', this._handlers.dragLeave);
            area.removeEventListener('drop', this._handlers.drop);
            area.removeEventListener('click', this._handlers.areaClick);
        }

        if (button) {
            button.removeEventListener('click', this._handlers.buttonClick);
        }

        if (input) {
            input.removeEventListener('change', this._handlers.inputChange);
        }

        if (this._dragTimer) {
            clearTimeout(this._dragTimer);
            this._dragTimer = null;
        }

        this._initialized = false;
        console.log('[Upload] UploadManager destroyed');
    }
}

// ============================================================
// Initialization Function
// ============================================================

/**
 * Initialize the upload module.
 *
 * Creates an UploadManager instance, initializes it, and returns it
 * for storage by the application module (app.js).
 *
 * The function is exposed on window for discovery by app.js,
 * which checks for `typeof window.initializeUpload === 'function'`.
 *
 * @async
 * @param {Object} [config] - Optional configuration.
 * @returns {Promise<UploadManager>} The initialized UploadManager instance.
 */
async function initializeUpload(config = {}) {
    const manager = new UploadManager(config);
    manager.init();
    return manager;
}

// ============================================================
// Global Exports
// ============================================================

// Expose for app.js initialization discovery
window.initializeUpload = initializeUpload;

// Expose UploadManager class for testing and direct access
window.UploadManager = UploadManager;

console.log('[Upload] Upload module loaded');