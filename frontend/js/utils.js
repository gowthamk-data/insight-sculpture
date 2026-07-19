/**
 * utils.js
 * Pure helper functions: formatting, sanitization, safe DOM building,
 * and Server-Sent Events (SSE) frame parsing.
 *
 * This module has no side effects and imports nothing else in the app.
 */

'use strict';

/* ============================================================
   Constants
   ============================================================ */

export const MAX_UPLOAD_SIZE_MB = 50;
export const MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024;
export const ALLOWED_EXTENSIONS = ['.csv'];
export const ALLOWED_MIME_TYPES = [
    'text/csv',
    'application/csv',
    'application/vnd.ms-excel', // some browsers report CSV as this
    'text/plain',
    '', // some OSes provide an empty type for .csv
];

/* ============================================================
   String / number formatting
   ============================================================ */

/**
 * Format an integer with locale-aware thousands separators.
 * @param {number|string} value
 * @returns {string}
 */
export function formatNumber(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return String(value ?? '-');
    return num.toLocaleString('en-US');
}

/**
 * Format bytes into a human-readable size.
 * @param {number} bytes
 * @returns {string}
 */
export function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const index = Math.min(
        units.length - 1,
        Math.floor(Math.log(bytes) / Math.log(1024))
    );
    const size = bytes / Math.pow(1024, index);
    return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

/**
 * Render a cell value safely for display, handling null / undefined / NaN.
 * @param {*} value
 * @returns {string}
 */
export function formatCell(value) {
    if (value === null || value === undefined) return '\u2014'; // em dash
    if (typeof value === 'number') {
        if (!Number.isFinite(value)) return '\u2014';
        return Number.isInteger(value) ? formatNumber(value) : value.toLocaleString('en-US', { maximumFractionDigits: 4 });
    }
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    const str = String(value).trim();
    return str === '' ? '\u2014' : str;
}

/**
 * Turn a snake_case / kebab-case identifier into a Title Case label.
 * @param {string} key
 * @returns {string}
 */
export function humanizeKey(key) {
    return String(key)
        .replace(/[_-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (c) => c.toUpperCase());
}

/* ============================================================
   Sanitization / safe DOM
   ============================================================ */

/**
 * Escape a string for safe insertion as HTML text.
 * Prefer createEl / textContent; use only when interpolating into templates.
 * @param {*} value
 * @returns {string}
 */
export function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value === null || value === undefined ? '' : String(value);
    return div.innerHTML;
}

/**
 * Create an element with attributes and children using only safe DOM APIs.
 * Text children are inserted via textContent-equivalent text nodes.
 *
 * @param {string} tag
 * @param {Object} [options]
 * @param {string} [options.class] - className
 * @param {string} [options.text] - textContent (safe)
 * @param {Object} [options.attrs] - attribute map
 * @param {Array<Node|string>} [options.children]
 * @returns {HTMLElement}
 */
export function createEl(tag, options = {}) {
    const el = document.createElement(tag);
    if (options.class) el.className = options.class;
    if (options.text !== undefined && options.text !== null) {
        el.textContent = String(options.text);
    }
    if (options.attrs) {
        for (const [name, val] of Object.entries(options.attrs)) {
            if (val === false || val === null || val === undefined) continue;
            el.setAttribute(name, val === true ? '' : String(val));
        }
    }
    if (options.children) {
        for (const child of options.children) {
            if (child === null || child === undefined) continue;
            el.append(child instanceof Node ? child : document.createTextNode(String(child)));
        }
    }
    return el;
}

/**
 * Remove all children from a node.
 * @param {Node} node
 */
export function clearNode(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
}

/* ============================================================
   Timing helpers
   ============================================================ */

/**
 * Debounce a function.
 * @param {Function} fn
 * @param {number} wait
 * @returns {Function}
 */
export function debounce(fn, wait = 200) {
    let timer = null;
    return (...args) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => fn(...args), wait);
    };
}

/**
 * Sleep for a number of milliseconds.
 * @param {number} ms
 * @returns {Promise<void>}
 */
export function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

/* ============================================================
   JSON helpers
   ============================================================ */

/**
 * Safely parse JSON, returning a fallback on failure.
 * @param {string} text
 * @param {*} [fallback=null]
 * @returns {*}
 */
export function safeJsonParse(text, fallback = null) {
    try {
        return JSON.parse(text);
    } catch {
        return fallback;
    }
}

/**
 * Pretty-print any value as indented JSON.
 * @param {*} value
 * @returns {string}
 */
export function prettyJson(value) {
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

/* ============================================================
   SSE parsing
   ============================================================ */

/**
 * Parse a raw SSE frame (text between blank lines) into { event, data }.
 * Follows the text/event-stream spec: lines beginning with "event:" and
 * "data:" (data lines are concatenated with newlines).
 *
 * @param {string} rawFrame
 * @returns {{ event: string, data: string }}
 */
export function parseSseFrame(rawFrame) {
    let event = 'message';
    const dataLines = [];

    for (const line of rawFrame.split('\n')) {
        if (!line || line.startsWith(':')) continue; // comment / keepalive
        const colon = line.indexOf(':');
        const field = colon === -1 ? line : line.slice(0, colon);
        // Spec: strip a single leading space after the colon.
        let value = colon === -1 ? '' : line.slice(colon + 1);
        if (value.startsWith(' ')) value = value.slice(1);

        if (field === 'event') event = value;
        else if (field === 'data') dataLines.push(value);
    }

    return { event, data: dataLines.join('\n') };
}
