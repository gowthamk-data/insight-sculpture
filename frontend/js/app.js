/**
 * app.js
 * Application entry point. Wires DOM events to the feature modules.
 *
 * Architecture (ES modules):
 *   app.js     - bootstrap + event wiring (this file)
 *   api.js     - fetch + SSE networking
 *   upload.js  - file handling, dataset info, preview
 *   query.js   - query submission + clear
 *   stream.js  - SSE event processing + result rendering
 *   ui.js      - DOM refs, notifications, status, tabs, overlay
 *   chart.js   - Chart.js rendering
 *   state.js   - shared app state
 *   utils.js   - helpers/formatters
 */

'use strict';

import { handleFileSelected, restoreDatasetUi, showPreview } from './upload.js';
import { clearAll, runQuery } from './query.js';
import { restoreSession } from './state.js';
import {
    els,
    getPreviewButton,
    hideNotification,
    initTabs,
    setSystemStatus,
} from './ui.js';

/**
 * Attach all event listeners.
 */
function wireEvents() {
    // --- Upload: "Choose CSV" opens the hidden file input ---
    els.uploadBtn?.addEventListener('click', () => els.csvUpload?.click());
    els.csvUpload?.addEventListener('change', (event) => {
        const file = event.target.files?.[0];
        if (file) handleFileSelected(file);
    });

    // --- Preview (button has no id; located by label) ---
    const previewBtn = getPreviewButton();
    if (previewBtn) {
        // Disabled until a dataset is uploaded.
        previewBtn.setAttribute('disabled', '');
        previewBtn.classList.add('opacity-60', 'cursor-not-allowed');
        previewBtn.addEventListener('click', showPreview);
    }

    // --- Query submission ---
    els.generateBtn?.addEventListener('click', runQuery);

    // Ctrl/Cmd+Enter submits from the textarea.
    els.queryInput?.addEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
            event.preventDefault();
            runQuery();
        }
    });

    // --- Clear ---
    els.clearBtn?.addEventListener('click', clearAll);

    // --- Notification close ---
    els.notificationClose?.addEventListener('click', hideNotification);
}

/**
 * Application bootstrap.
 */
function init() {
    // Guard: ensure the expected DOM is present.
    if (!els.systemStatus || !els.uploadBtn || !els.generateBtn) {
        console.error('[App] Required DOM elements are missing; aborting init.');
        return;
    }

    initTabs();
    wireEvents();
    setSystemStatus('Ready');

    // Restore a persisted dataset session across a page refresh.
    if (restoreSession()) {
        restoreDatasetUi();
    }

    // Warn early if Chart.js failed to load from the CDN.
    if (typeof window.Chart === 'undefined') {
        console.warn('[App] Chart.js was not detected. Charts will be unavailable.');
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
