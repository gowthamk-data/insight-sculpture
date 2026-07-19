/**
 * api.js
 * All network I/O for the app: base-URL resolution, fetch wrappers with
 * timeouts and structured error handling, dataset upload, and the
 * Server-Sent Events (SSE) streaming reader for /stream.
 *
 * The backend mounts routers under the "/api" prefix:
 *   POST /api/upload/   -> multipart file upload (returns session + profile)
 *   POST /api/analyze/  -> full non-streaming analysis (JSON)
 *   POST /api/stream/   -> SSE stream (text/event-stream) of progress + result
 *
 * Note: the backend exposes no GET /preview endpoint; the dataset preview is
 * derived from the profile returned by the upload response (see upload.js).
 */

'use strict';

import { parseSseFrame, safeJsonParse } from './utils.js';

/* ============================================================
   Base URL resolution
   ============================================================ */

const DEFAULT_DEV_ORIGIN = 'http://127.0.0.1:8000';
const DEFAULT_TIMEOUT_MS = 30000;

/**
 * Resolve the API base URL.
 * - If the page is served over http(s) from a real host, assume the API is
 *   same-origin (or reachable at that origin) under "/api".
 * - If opened via file:// or from a static dev server, fall back to the
 *   FastAPI dev origin.
 * A global override `window.__API_BASE__` always wins.
 * @returns {string}
 */
export function getApiBase() {
    if (typeof window !== 'undefined' && window.__API_BASE__) {
        return String(window.__API_BASE__).replace(/\/$/, '');
    }
    const { protocol, origin, port } = window.location;
    if (protocol === 'file:' || !origin || origin === 'null') {
        return `${DEFAULT_DEV_ORIGIN}/api`;
    }
    // Common static-preview ports that are NOT the FastAPI server.
    const staticPorts = new Set(['5500', '5501', '3000', '8080', '4173', '5173']);
    if (staticPorts.has(port)) {
        return `${DEFAULT_DEV_ORIGIN}/api`;
    }
    return `${origin}/api`;
}

/* ============================================================
   Error type
   ============================================================ */

/**
 * Normalized API error carrying an HTTP status and optional details.
 */
export class ApiError extends Error {
    constructor(message, { status = 0, code = 'ERROR', details = null } = {}) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
        this.details = details;
    }
}

/**
 * Extract a human-readable message from a backend error payload.
 * The backend returns: { success:false, error:{ code, message, details } }
 * @param {*} payload
 * @param {number} status
 * @returns {ApiError}
 */
function toApiError(payload, status) {
    const err = payload && typeof payload === 'object' ? payload.error : null;
    if (err && err.message) {
        return new ApiError(err.message, { status, code: err.code, details: err.details });
    }
    if (payload && typeof payload === 'object' && payload.detail) {
        const detail = payload.detail;
        const msg = typeof detail === 'string' ? detail : JSON.stringify(detail);
        return new ApiError(msg, { status, code: 'HTTP_ERROR', details: detail });
    }
    return new ApiError(`Request failed with status ${status}`, { status });
}

/* ============================================================
   Core fetch with timeout
   ============================================================ */

/**
 * fetch() wrapper adding an AbortController timeout and network-error mapping.
 * @param {string} url
 * @param {RequestInit & { timeout?: number, signal?: AbortSignal }} [options]
 * @returns {Promise<Response>}
 */
async function fetchWithTimeout(url, options = {}) {
    const { timeout = DEFAULT_TIMEOUT_MS, signal: externalSignal, ...rest } = options;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new ApiError('Request timed out.', { code: 'TIMEOUT' })), timeout);

    // Chain an externally provided signal (e.g. user cancellation).
    if (externalSignal) {
        if (externalSignal.aborted) controller.abort(externalSignal.reason);
        else externalSignal.addEventListener('abort', () => controller.abort(externalSignal.reason), { once: true });
    }

    try {
        return await fetch(url, { ...rest, signal: controller.signal });
    } catch (error) {
        if (error && error.name === 'AbortError') {
            throw controller.signal.reason instanceof ApiError
                ? controller.signal.reason
                : new ApiError('Request was aborted.', { code: 'ABORTED' });
        }
        throw new ApiError('Network error: unable to reach the server.', { code: 'NETWORK' });
    } finally {
        clearTimeout(timer);
    }
}

/**
 * Parse a Response as JSON, throwing a normalized ApiError on non-2xx or
 * invalid JSON bodies.
 * @param {Response} response
 * @returns {Promise<*>}
 */
async function parseJsonResponse(response) {
    const text = await response.text();
    const payload = text ? safeJsonParse(text, undefined) : undefined;

    if (!response.ok) {
        throw toApiError(payload ?? text, response.status);
    }
    if (payload === undefined) {
        throw new ApiError('Server returned an invalid JSON response.', {
            status: response.status,
            code: 'INVALID_JSON',
        });
    }
    return payload;
}

/* ============================================================
   Endpoints
   ============================================================ */

/**
 * Upload a dataset file (multipart/form-data, field name "file").
 * @param {File} file
 * @param {{ timeout?: number, signal?: AbortSignal }} [options]
 * @returns {Promise<Object>} UploadResponse
 */
export async function uploadDataset(file, options = {}) {
    const formData = new FormData();
    formData.append('file', file, file.name);

    const response = await fetchWithTimeout(`${getApiBase()}/upload/`, {
        method: 'POST',
        body: formData,
        timeout: options.timeout ?? 60000,
        signal: options.signal,
    });
    return parseJsonResponse(response);
}

/**
 * Run a full non-streaming analysis. Kept available for callers that prefer a
 * single request/response instead of SSE.
 * @param {{ sessionId: string, question: string, history?: Array }} params
 * @param {{ timeout?: number, signal?: AbortSignal }} [options]
 * @returns {Promise<Object>} AnalyzeResponse
 */
export async function analyze({ sessionId, question, history = null }, options = {}) {
    const response = await fetchWithTimeout(`${getApiBase()}/analyze/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: sessionId,
            question,
            conversation_history: history,
        }),
        timeout: options.timeout ?? 60000,
        signal: options.signal,
    });
    return parseJsonResponse(response);
}

/* ============================================================
   SSE streaming
   ============================================================ */

/**
 * Open the analysis SSE stream and dispatch each parsed event to a handler.
 *
 * The stream is a POST returning text/event-stream, so it cannot use the
 * native EventSource API; we read the body stream manually and parse frames.
 *
 * @param {{ sessionId: string, question: string, history?: Array }} params
 * @param {{
 *   onEvent: (name: string, data: Object) => void,
 *   signal?: AbortSignal,
 *   timeout?: number,
 *   idleTimeout?: number,
 * }} handlers
 * @returns {Promise<void>} resolves when the stream ends.
 */
export async function streamAnalysis(
    { sessionId, question, history = null },
    { onEvent, signal, timeout = 120000, idleTimeout = 90000 },
) {
    const response = await fetchWithTimeout(`${getApiBase()}/stream/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
        },
        body: JSON.stringify({
            session_id: sessionId,
            question,
            conversation_history: history,
        }),
        timeout,
        signal,
    });

    if (!response.ok) {
        // Error responses arrive as JSON, not as a stream.
        const text = await response.text();
        throw toApiError(safeJsonParse(text, text), response.status);
    }
    if (!response.body) {
        throw new ApiError('Streaming is not supported in this environment.', { code: 'NO_STREAM' });
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let cancelled = false;
    let timedOut = false;

    // Ensure an external abort (cancellation) tears the stream down promptly.
    const onAbort = () => {
        cancelled = true;
        reader.cancel().catch(() => { /* already closing */ });
    };
    if (signal) {
        if (signal.aborted) onAbort();
        else signal.addEventListener('abort', onAbort, { once: true });
    }

    // Inactivity watchdog: the connection-open timeout is cleared once headers
    // arrive, so guard against a stalled mid-stream connection here.
    let idleTimer = null;
    const armIdleTimer = () => {
        if (idleTimer) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => {
            timedOut = true;
            reader.cancel().catch(() => { /* already closing */ });
        }, idleTimeout);
    };

    try {
        armIdleTimer();
        for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            armIdleTimer();
            buffer += decoder.decode(value, { stream: true });

            // Frames are separated by a blank line (\n\n).
            let separatorIndex;
            while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
                const rawFrame = buffer.slice(0, separatorIndex);
                buffer = buffer.slice(separatorIndex + 2);
                dispatchFrame(rawFrame, onEvent);
            }
        }
        // Flush any trailing frame without a terminating blank line.
        if (buffer.trim()) dispatchFrame(buffer, onEvent);
    } catch (error) {
        if (timedOut) {
            throw new ApiError('The streaming connection stalled and timed out.', { code: 'TIMEOUT' });
        }
        if (cancelled || (error && (error.name === 'AbortError' || error.code === 'ABORTED'))) {
            throw new ApiError('The streaming connection was cancelled.', { code: 'ABORTED' });
        }
        throw new ApiError('The streaming connection was lost.', { code: 'STREAM_LOST' });
    } finally {
        // Explicitly close the stream and clear timers to avoid leaks.
        if (idleTimer) clearTimeout(idleTimer);
        if (signal) signal.removeEventListener('abort', onAbort);
        try {
            await reader.cancel();
        } catch {
            /* stream already closed */
        }
    }
}

/**
 * Parse a single SSE frame and forward it to the handler.
 * @param {string} rawFrame
 * @param {(name: string, data: Object) => void} onEvent
 */
function dispatchFrame(rawFrame, onEvent) {
    const { event, data } = parseSseFrame(rawFrame);
    if (!data) return;
    const parsed = safeJsonParse(data, { message: data });
    onEvent(event, parsed);
}
