/**
 * state.js
 * Minimal shared application state. Kept intentionally tiny so modules can
 * coordinate without a framework or global variables.
 */

'use strict';

export const state = {
    /** @type {string|null} Active analytics session id from the last upload. */
    sessionId: null,
    /** @type {string|null} Display name of the uploaded dataset. */
    datasetName: null,
    /** @type {number|null} Row count of the uploaded dataset. */
    datasetRows: null,
    /** @type {number|null} Column count of the uploaded dataset. */
    datasetColumns: null,
    /** @type {Object|null} Dataset profile from the upload response. */
    profile: null,
    /** @type {boolean} Whether a query stream is currently in flight. */
    isQuerying: false,
    /** @type {AbortController|null} Controller to cancel the active stream. */
    abortController: null,
    /** @type {number} Monotonic id identifying the current query run. */
    runId: 0,
    /** @type {Object|null} Last full analysis result assembled from the stream. */
    lastResult: null,
};

/**
 * Reset only the transient query-in-flight state. Deliberately preserves both
 * the uploaded dataset and `lastResult` (the JSON tab keeps its content after
 * a run completes); `lastResult` is cleared only by an explicit clear action.
 */
export function resetQueryState() {
    state.isQuerying = false;
    state.abortController = null;
}

const SESSION_KEY = 'insightSculpture.session';

/**
 * Persist the current dataset session so a browser refresh can restore it
 * (the backend session may still be alive). Fails silently if storage is
 * unavailable (e.g. private mode, disabled cookies).
 */
export function persistSession() {
    try {
        sessionStorage.setItem(
            SESSION_KEY,
            JSON.stringify({
                sessionId: state.sessionId,
                datasetName: state.datasetName,
                datasetRows: state.datasetRows,
                datasetColumns: state.datasetColumns,
                profile: state.profile,
            }),
        );
    } catch {
        /* storage unavailable - non-fatal */
    }
}

/**
 * Restore a persisted dataset session, if any.
 * @returns {boolean} true if a session was restored.
 */
export function restoreSession() {
    try {
        const raw = sessionStorage.getItem(SESSION_KEY);
        if (!raw) return false;
        const saved = JSON.parse(raw);
        if (!saved || !saved.sessionId) return false;
        state.sessionId = saved.sessionId;
        state.datasetName = saved.datasetName ?? null;
        state.datasetRows = saved.datasetRows ?? null;
        state.datasetColumns = saved.datasetColumns ?? null;
        state.profile = saved.profile ?? null;
        return true;
    } catch {
        return false;
    }
}

/** Remove any persisted dataset session. */
export function clearPersistedSession() {
    try {
        sessionStorage.removeItem(SESSION_KEY);
    } catch {
        /* non-fatal */
    }
}
