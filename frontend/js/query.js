/**
 * query.js
 * Query submission and the "clear" action.
 * - Validates input and session presence
 * - Runs the analysis via the SSE stream
 * - Keeps the UI usable on every outcome (success, error, cancel)
 * - Clears query/results without touching the uploaded dataset
 */

'use strict';

import { streamAnalysis } from './api.js';
import { destroyChart } from './chart.js';
import { clearPersistedSession, resetQueryState, state } from './state.js';
import {
    createStreamContext,
    handleStreamEvent,
    renderResultTabs,
} from './stream.js';
import {
    activateTab,
    els,
    getStreamState,
    hideNotification,
    hideStreamStatus,
    notify,
    resetStreamState,
    setLoading,
    setPlaceholder,
    setSystemStatus,
    showStreamStatus,
    updateStreamState,
} from './ui.js';

const MAX_QUESTION_LENGTH = 1000;

/**
 * Detect a backend "session not found" condition from either an ApiError
 * (HTTP 404 / message) or an SSE error message.
 * @param {{ status?: number, message?: string }|string|null} source
 * @returns {boolean}
 */
function isSessionNotFound(source) {
    if (!source) return false;
    const message = (typeof source === 'string' ? source : source.message || '').toLowerCase();
    const status = typeof source === 'object' ? source.status : undefined;
    if (status === 404 && message.includes('session')) return true;
    return message.includes('session not found') || message.includes('dataset profile not found');
}

/**
 * Recover from a stale/expired backend session: clear frontend session state,
 * reset the dataset cards, and prompt the user to re-upload. Restores the UI
 * to the "Ready" state.
 */
function handleStaleSession() {
    state.sessionId = null;
    state.datasetName = null;
    state.datasetRows = null;
    state.datasetColumns = null;
    state.profile = null;
    clearPersistedSession();

    if (els.datasetName) els.datasetName.textContent = '-';
    if (els.datasetRows) els.datasetRows.textContent = '-';
    if (els.datasetColumns) els.datasetColumns.textContent = '-';

    setSystemStatus('Ready');
    notify('Your dataset session has expired. Please upload the dataset again.', 'warning');
}

/**
 * Validate the current query and session state.
 * @returns {{ ok: boolean, question?: string, message?: string }}
 */
export function validateQuery() {
    if (!state.sessionId) {
        return { ok: false, message: 'Upload a dataset before asking a question.' };
    }
    const question = (els.queryInput?.value || '').trim();
    if (!question) {
        return { ok: false, message: 'Please enter a question about your dataset.' };
    }
    if (question.length > MAX_QUESTION_LENGTH) {
        return { ok: false, message: `Question is too long (max ${MAX_QUESTION_LENGTH} characters).` };
    }
    return { ok: true, question };
}

/**
 * Submit a query and process the streamed analysis.
 */
export async function runQuery() {
    if (state.isQuerying) {
        notify('An analysis is already in progress.', 'warning');
        return;
    }

    const validation = validateQuery();
    if (!validation.ok) {
        notify(validation.message, 'warning');
        return;
    }

    let ctx;
    let controller;
    const runId = ++state.runId;
    try {
        beginQueryUi();

        ctx = createStreamContext();
        controller = new AbortController();
        state.abortController = controller;

        await streamAnalysis(
            { sessionId: state.sessionId, question: validation.question },
            {
                signal: controller.signal,
                // Ignore late events from a superseded/aborted run.
                onEvent: (name, data) => {
                    if (state.runId === runId) handleStreamEvent(name, data, ctx);
                },
            },
        );

        if (state.runId !== runId) return; // superseded

        // If the stream ended without a terminal event, still finalize the UI.
        if (ctx.errored) {
            if (isSessionNotFound(ctx.errorMessage)) {
                handleStaleSession();
            } else {
                notify(ctx.errorMessage || 'The analysis failed.', 'error');
            }
        } else if (!ctx.completed) {
            renderResultTabs(ctx);
            setSystemStatus('Completed');
            notify('Analysis finished.', 'success');
        } else {
            notify('Analysis complete.', 'success');
        }
    } catch (error) {
        if (state.runId !== runId) return; // superseded; suppress stale errors
        if (error?.code === 'ABORTED') {
            notify('Analysis cancelled.', 'info');
            setSystemStatus('Ready');
        } else if (isSessionNotFound(error)) {
            handleStaleSession();
        } else {
            notify(error?.message || 'Analysis failed. Please try again.', 'error');
            setSystemStatus('Error');
        }
    } finally {
        if (state.runId === runId) endQueryUi();
    }
}

/**
 * Cancel an in-flight query, if any.
 */
export function cancelQuery() {
    if (state.abortController) {
        state.abortController.abort();
    }
}

/**
 * Prepare the UI for a running query.
 */
function beginQueryUi() {
    state.isQuerying = true;
    hideNotification();

    // Reset result panels so stale output from a prior run is never shown.
    destroyChart();
    setPlaceholder(els.planContainer, 'Generating plan\u2026');
    setPlaceholder(els.resultsContainer, 'Running analysis\u2026');
    setPlaceholder(els.chartContainer, 'Preparing chart\u2026');
    setPlaceholder(els.jsonContainer, 'Awaiting response\u2026');

    // Reset the indicator to idle, then advance to the first state. This
    // guarantees no animation leaks in from a previous run before starting.
    resetStreamState();
    showStreamStatus();
    updateStreamState('thinking');

    setSystemStatus('Planning');
    setLoading(true, 'Generating analytics plan...');
    activateTab('tab-plan');

    els.generateBtn?.setAttribute('disabled', '');
    els.generateBtn?.classList.add('opacity-60', 'cursor-not-allowed');
}

/**
 * Restore the UI after a query ends (any outcome). The state machine already
 * stops animations in terminal states (completed/error); if the run ended
 * early (e.g. cancellation) the indicator is still in an intermediate state,
 * so stop any lingering spinner here for lifecycle safety.
 */
function endQueryUi() {
    setLoading(false);
    els.generateBtn?.removeAttribute('disabled');
    els.generateBtn?.classList.remove('opacity-60', 'cursor-not-allowed');

    // On cancel/abort the stream never reaches a terminal state; force idle.
    const s = getStreamState();
    if (s === 'thinking' || s === 'planning' || s === 'executing') {
        resetStreamState();
    }

    resetQueryState();
}

/* ============================================================
   Clear
   ============================================================ */

/**
 * Reset the query input and all result panels, streaming status, and
 * notifications. Deliberately preserves the uploaded dataset and its info.
 */
export function clearAll() {
    // Cancel anything in flight first.
    cancelQuery();

    if (els.queryInput) els.queryInput.value = '';

    destroyChart();
    setPlaceholder(els.planContainer, 'No plan generated');
    setPlaceholder(els.resultsContainer, 'No results available');
    setPlaceholder(els.chartContainer, 'No chart generated');
    setPlaceholder(els.jsonContainer, 'No JSON data');

    resetStreamState();
    hideStreamStatus();
    hideNotification();
    activateTab('tab-plan');

    state.lastResult = null;
    setSystemStatus('Ready');
}
