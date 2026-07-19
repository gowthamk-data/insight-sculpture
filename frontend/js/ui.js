/**
 * ui.js
 * Centralized DOM access and presentation logic:
 * - Cached element references (by the fixed IDs defined in index.html)
 * - System status pill
 * - Loading overlay
 * - Auto-dismissing notifications (success / warning / error / info)
 * - Tab switching
 * - Streaming status stepper (thinking / planning / executing / rendering / completed)
 *
 * All user-generated content is inserted via textContent / safe DOM helpers.
 */

'use strict';

import { clearNode, createEl } from './utils.js';

/* ============================================================
   Element references
   ============================================================ */

const ELEMENT_IDS = {
    systemStatus: 'system-status',
    csvUpload: 'csv-upload',
    uploadBtn: 'upload-btn',
    datasetName: 'dataset-name',
    datasetRows: 'dataset-rows',
    datasetColumns: 'dataset-columns',
    queryInput: 'query-input',
    generateBtn: 'generate-btn',
    clearBtn: 'clear-btn',
    streamStatus: 'stream-status',
    planContainer: 'plan-container',
    resultsContainer: 'results-container',
    chartContainer: 'chart-container',
    jsonContainer: 'json-container',
    loadingOverlay: 'loading-overlay',
    notification: 'notification',
    notificationIcon: 'notification-icon',
    notificationMessage: 'notification-message',
    notificationClose: 'notification-close',
};

/**
 * Lazily-resolved, cached element references. Using getters (instead of
 * resolving at module-load time) avoids stale/null caches regardless of when
 * this module is first evaluated relative to DOM parsing.
 */
const _elCache = {};
export const els = {};
for (const [key, id] of Object.entries(ELEMENT_IDS)) {
    Object.defineProperty(els, key, {
        enumerable: true,
        get() {
            const cached = _elCache[key];
            if (cached && cached.isConnected) return cached;
            const found = document.getElementById(id);
            _elCache[key] = found;
            return found;
        },
    });
}

/**
 * Locate the "Preview Dataset" button. It has no id in the scaffold, so we
 * find it by its label without renaming or restructuring the markup. The
 * result is cached to avoid repeated full-document scans.
 * @returns {HTMLButtonElement|null}
 */
let _previewButton;
export function getPreviewButton() {
    if (_previewButton && _previewButton.isConnected) return _previewButton;
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
        if (btn.textContent.trim().toLowerCase() === 'preview dataset') {
            _previewButton = btn;
            return btn;
        }
    }
    return null;
}

/* ============================================================
   System status pill
   ============================================================ */

const STATUS_STYLES = {
    Ready: { pill: 'bg-emerald-50 text-emerald-700 border-emerald-200', dot: 'bg-emerald-500' },
    Uploading: { pill: 'bg-sky-50 text-sky-700 border-sky-200', dot: 'bg-sky-500 animate-pulse' },
    Planning: { pill: 'bg-indigo-50 text-indigo-700 border-indigo-200', dot: 'bg-indigo-500 animate-pulse' },
    Executing: { pill: 'bg-amber-50 text-amber-700 border-amber-200', dot: 'bg-amber-500 animate-pulse' },
    Completed: { pill: 'bg-emerald-50 text-emerald-700 border-emerald-200', dot: 'bg-emerald-500' },
    Error: { pill: 'bg-red-50 text-red-700 border-red-200', dot: 'bg-red-500' },
};

const STATUS_BASE = 'inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium border';

/**
 * Update the system status pill text and color.
 * @param {'Ready'|'Uploading'|'Planning'|'Executing'|'Completed'|'Error'} state
 */
export function setSystemStatus(state) {
    const el = els.systemStatus;
    if (!el) return;
    const style = STATUS_STYLES[state] || STATUS_STYLES.Ready;
    el.className = `${STATUS_BASE} ${style.pill}`;
    clearNode(el);
    el.append(
        createEl('span', { class: `w-2 h-2 rounded-full ${style.dot}`, attrs: { 'aria-hidden': 'true' } }),
        document.createTextNode(state)
    );
}

/* ============================================================
   Loading overlay
   ============================================================ */

/**
 * Show or hide the full-screen loading overlay. Optionally update its message.
 * @param {boolean} visible
 * @param {string} [message]
 */
export function setLoading(visible, message) {
    const overlay = els.loadingOverlay;
    if (!overlay) return;
    if (message) {
        const p = overlay.querySelector('p');
        if (p) p.textContent = message;
    }
    overlay.classList.toggle('hidden', !visible);
}

/* ============================================================
   Notifications
   ============================================================ */

const NOTIFICATION_TYPES = {
    success: { border: 'border-emerald-200', text: 'text-emerald-600', symbol: '\u2713' },
    error: { border: 'border-red-200', text: 'text-red-600', symbol: '\u2715' },
    warning: { border: 'border-amber-200', text: 'text-amber-600', symbol: '!' },
    info: { border: 'border-sky-200', text: 'text-sky-600', symbol: 'i' },
};

let notificationTimer = null;

/**
 * Show an auto-dismissing notification.
 * @param {string} message
 * @param {'success'|'error'|'warning'|'info'} [type='info']
 * @param {number} [duration=5000] - ms before auto-dismiss (0 = sticky)
 */
export function notify(message, type = 'info', duration = 5000) {
    const { notification, notificationIcon, notificationMessage } = els;
    if (!notification) return;

    const config = NOTIFICATION_TYPES[type] || NOTIFICATION_TYPES.info;

    // Icon badge (safe DOM, no innerHTML).
    if (notificationIcon) {
        clearNode(notificationIcon);
        notificationIcon.append(
            createEl('span', {
                class: `flex items-center justify-center w-6 h-6 rounded-full text-sm font-bold border ${config.border} ${config.text}`,
                text: config.symbol,
                attrs: { 'aria-hidden': 'true' },
            })
        );
    }

    if (notificationMessage) notificationMessage.textContent = message;

    const card = notification.firstElementChild;
    if (card) {
        card.className =
            `bg-white rounded-lg shadow-lg border ${config.border} p-4 flex items-start gap-3`;
    }

    notification.classList.remove('hidden');

    if (notificationTimer) clearTimeout(notificationTimer);
    if (duration > 0) {
        notificationTimer = setTimeout(hideNotification, duration);
    }
}

/** Hide the notification immediately. */
export function hideNotification() {
    if (notificationTimer) {
        clearTimeout(notificationTimer);
        notificationTimer = null;
    }
    els.notification?.classList.add('hidden');
}

/* ============================================================
   Tabs
   ============================================================ */

const TAB_PANELS = {
    'tab-plan': 'plan-container',
    'tab-results': 'results-container',
    'tab-chart': 'chart-container',
    'tab-json': 'json-container',
};

const TAB_ACTIVE = 'text-slate-700 border-slate-900';
const TAB_INACTIVE = 'text-slate-500 border-transparent hover:text-slate-700 hover:border-slate-300';

/**
 * Activate a tab and reveal its panel.
 * @param {string} tabId - one of the tab button IDs
 */
export function activateTab(tabId) {
    for (const [btnId, panelId] of Object.entries(TAB_PANELS)) {
        const btn = document.getElementById(btnId);
        const panel = document.getElementById(panelId);
        const isActive = btnId === tabId;
        if (btn) {
            btn.setAttribute('aria-selected', String(isActive));
            btn.className =
                `tab-btn inline-flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 ` +
                `focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 ` +
                (isActive ? TAB_ACTIVE : TAB_INACTIVE);
        }
        if (panel) panel.classList.toggle('hidden', !isActive);
    }
}

/** Wire click handlers for all tab buttons. */
export function initTabs() {
    for (const btnId of Object.keys(TAB_PANELS)) {
        const btn = document.getElementById(btnId);
        btn?.addEventListener('click', () => activateTab(btnId));
    }
}

/* ============================================================
   Streaming status state machine (sequential stepper)
   ============================================================ */

const STREAM_STATES = new Set(['idle', 'thinking', 'planning', 'executing', 'completed', 'error']);

// Allowed transitions define the single, valid lifecycle. Any transition not
// listed here is rejected, guaranteeing mutually exclusive, predictable states.
const STREAM_TRANSITIONS = {
    idle: ['thinking'],
    thinking: ['planning', 'error'],
    planning: ['executing', 'error'],
    executing: ['completed', 'error'],
    completed: ['idle'],
    error: ['idle'],
};

const STEP_ORDER = ['thinking', 'planning', 'executing', 'completed'];
const STEP_ELEMENT_IDS = {
    thinking: 'status-thinking',
    planning: 'status-planning',
    executing: 'status-executing',
    completed: 'status-completed',
};

// Single source of truth for the current streaming state.
let currentStreamState = 'idle';

/** Read the current streaming state (single source of truth). */
export function getStreamState() {
    return currentStreamState;
}

/**
 * Normalize a backend phase name into a state-machine state. The backend emits
 * a "rendering_chart" phase that has no dedicated element, so it maps onto the
 * ongoing "executing" step.
 * @param {string} phase
 * @returns {string}
 */
function normalizeStreamPhase(phase) {
    if (phase === 'rendering_chart') return 'executing';
    return STREAM_STATES.has(phase) ? phase : 'thinking';
}

/**
 * Resolve which step is "active" for a given machine state, and how many
 * leading steps are "completed". The "error" state is handled separately so
 * the failing step can be highlighted while animations stop.
 *
 * @param {string} state
 * @returns {{ active: string|null, doneUpTo: number }}
 */
function resolveStepLayout(state) {
    switch (state) {
        case 'thinking': return { active: 'thinking', doneUpTo: 0 };
        case 'planning': return { active: 'planning', doneUpTo: 1 };
        case 'executing': return { active: 'executing', doneUpTo: 2 };
        case 'completed': return { active: null, doneUpTo: 4 };
        default: return { active: null, doneUpTo: 0 }; // idle / error handled elsewhere
    }
}

/**
 * Paint a single step node into one of: idle, active, done, or error.
 * @param {HTMLElement} node
 * @param {'idle'|'active'|'done'|'error'} appearance
 */
function paintStepNode(node, appearance) {
    const icon = node.querySelector('.step-icon');
    const label = node.querySelector('.step-label');
    const connector = node.querySelector('.step-connector');

    const idle = node.querySelector('.icon-idle');
    const active = node.querySelector('.icon-active');
    const done = node.querySelector('.icon-done');

    // Toggle which icon variant is visible (exclusivity of the visual).
    idle?.classList.toggle('hidden', appearance !== 'idle');
    active?.classList.toggle('hidden', appearance !== 'active');
    done?.classList.toggle('hidden', appearance !== 'done');

    // Color states per spec: gray idle, blue active, green done, red error.
    const iconClasses = [
        'border-slate-300', 'bg-white', 'text-slate-400',
        'border-sky-500', 'bg-sky-50', 'text-sky-600',
        'border-emerald-500', 'bg-emerald-500', 'text-emerald-600', 'text-white',
        'border-red-500', 'bg-red-500', 'text-red-600',
    ];
    if (icon) icon.classList.remove(...iconClasses);

    const labelColor = ['text-slate-400', 'text-sky-600', 'text-emerald-600', 'text-red-600'];
    if (label) label.classList.remove(...labelColor);

    if (appearance === 'idle') {
        icon?.classList.add('border-slate-300', 'bg-white', 'text-slate-400');
        label?.classList.add('text-slate-400');
    } else if (appearance === 'active') {
        icon?.classList.add('border-sky-500', 'bg-sky-50', 'text-sky-600');
        label?.classList.add('text-sky-600');
    } else if (appearance === 'done') {
        icon?.classList.add('border-emerald-500', 'bg-emerald-500', 'text-white');
        label?.classList.add('text-emerald-600');
    } else if (appearance === 'error') {
        icon?.classList.add('border-red-500', 'bg-red-500', 'text-white');
        label?.classList.add('text-red-600');
    }

    // The connector after a completed step turns green; otherwise neutral.
    if (connector) {
        connector.classList.remove('bg-slate-200', 'bg-emerald-500');
        connector.classList.add(appearance === 'done' ? 'bg-emerald-500' : 'bg-slate-200');
    }
}

/**
 * Apply the full stepper appearance for the given machine state. Guarantees
 * exactly one active step and that all earlier steps show the green checkmark.
 * @param {string} state
 */
function paintStreamState(state) {
    const { active, doneUpTo } = resolveStepLayout(state);

    STEP_ORDER.forEach((step, index) => {
        const node = document.getElementById(STEP_ELEMENT_IDS[step]);
        if (!node) return;
        if (index < doneUpTo) {
            paintStepNode(node, 'done');
        } else if (step === active) {
            paintStepNode(node, 'active');
        } else {
            paintStepNode(node, 'idle');
        }
    });
}

/** Show the streaming status region. */
export function showStreamStatus() {
    els.streamStatus?.classList.remove('hidden');
}

/** Hide the streaming status region. */
export function hideStreamStatus() {
    els.streamStatus?.classList.add('hidden');
}

/**
 * Centralized, mutually-exclusive streaming state controller. All progress
 * updates must flow through this function; no other module may directly toggle
 * the status icons, spinners, or animation classes.
 *
 * Before activating any new state it fully repaints the stepper (idle/active/
 * done), so no stale icons or lingering spinners persist across transitions.
 *
 * @param {'idle'|'thinking'|'planning'|'executing'|'completed'|'error'} nextState
 * @returns {boolean} true if the transition was applied (or was a no-op).
 */
export function updateStreamState(nextState) {
    if (!STREAM_STATES.has(nextState)) return false;

    if (nextState !== currentStreamState) {
        const allowed = STREAM_TRANSITIONS[currentStreamState] || [];
        if (!allowed.includes(nextState)) return false; // illegal transition rejected
        currentStreamState = nextState;
    }

    if (nextState === 'error') {
        paintErrorState();
    } else {
        paintStreamState(currentStreamState);
    }
    return true;
}

/**
 * Error state: stop all spinners and mark the step that was in progress (or the
 * first step if none) as failed in red, while earlier completed steps keep
 * their green checkmarks.
 */
function paintErrorState() {
    // Find the step currently animated (the one that failed), else default.
    let failedStep = STEP_ORDER.find((step) => {
        const node = document.getElementById(STEP_ELEMENT_IDS[step]);
        const active = node?.querySelector('.icon-active');
        return active && !active.classList.contains('hidden');
    }) || 'thinking';

    STEP_ORDER.forEach((step) => {
        const node = document.getElementById(STEP_ELEMENT_IDS[step]);
        if (!node) return;
        if (step === failedStep) {
            node.querySelector('.icon-active')?.classList.add('hidden'); // halt animation
            paintStepNode(node, 'error');
        }
    });
    currentStreamState = 'error';
}

/**
 * Reset the indicator to the neutral `idle` state. Safe to call before any new
 * query; stops all animations and clears highlights.
 */
export function resetStreamState() {
    currentStreamState = 'idle';
    paintStreamState('idle');
}

/**
 * Convenience wrapper for backend phase names (thinking/planning/executing/
 * rendering_chart/completed). Rejected transitions (e.g. planning -> completed)
 * are ignored so the indicator never jumps out of order.
 * @param {string} phase
 */
export function setStreamPhase(phase) {
    updateStreamState(normalizeStreamPhase(phase));
}

/* ============================================================
   Placeholder / reset helpers for result panels
   ============================================================ */

/**
 * Replace a container's contents with a muted placeholder message.
 * @param {HTMLElement} container
 * @param {string} message
 */
export function setPlaceholder(container, message) {
    if (!container) return;
    clearNode(container);
    container.append(createEl('p', { class: 'text-sm text-slate-500', text: message }));
}
