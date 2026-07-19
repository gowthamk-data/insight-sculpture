/**
 * upload.js
 * Dataset upload lifecycle: validation, transit, dataset-info updates, and the
 * dataset preview (rendered from the profile returned by the upload response,
 * since the backend exposes no separate preview endpoint).
 */

'use strict';

import { uploadDataset } from './api.js';
import { persistSession, state } from './state.js';
import {
    els,
    getPreviewButton,
    notify,
    setLoading,
    setSystemStatus,
    activateTab,
} from './ui.js';
import {
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_UPLOAD_SIZE_MB,
    clearNode,
    createEl,
    formatBytes,
    formatCell,
    formatNumber,
} from './utils.js';

/* ============================================================
   Validation
   ============================================================ */

/**
 * Validate a selected file for type, extension and size.
 * @param {File} file
 * @returns {{ ok: boolean, message?: string }}
 */
export function validateFile(file) {
    if (!file) return { ok: false, message: 'No file selected.' };

    const name = file.name || '';
    const lower = name.toLowerCase();
    const hasValidExt = ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
    if (!hasValidExt) {
        return { ok: false, message: 'Please choose a CSV file (.csv).' };
    }

    // MIME type is advisory only; some OS/browsers mislabel CSV files.
    if (file.type && !ALLOWED_MIME_TYPES.includes(file.type)) {
        return { ok: false, message: `Unsupported file type "${file.type}". Expected CSV.` };
    }

    if (file.size === 0) {
        return { ok: false, message: 'The selected file is empty.' };
    }
    if (file.size > MAX_UPLOAD_SIZE_BYTES) {
        return {
            ok: false,
            message: `File is ${formatBytes(file.size)}; the maximum allowed size is ${MAX_UPLOAD_SIZE_MB} MB.`,
        };
    }

    return { ok: true };
}

/* ============================================================
   Upload flow
   ============================================================ */

/**
 * Handle a chosen file: validate, upload, update state and UI.
 * Always restores the UI to a usable state, success or failure.
 * @param {File} file
 */
export async function handleFileSelected(file) {
    const validation = validateFile(file);
    if (!validation.ok) {
        notify(validation.message, 'warning');
        return;
    }

    setSystemStatus('Uploading');
    setLoading(true, 'Uploading dataset...');
    els.uploadBtn?.setAttribute('disabled', '');
    els.uploadBtn?.classList.add('opacity-60', 'cursor-not-allowed');

    try {
        const result = await uploadDataset(file);

        state.sessionId = result.session_id;
        state.datasetName = result.filename;
        state.datasetRows = result.rows;
        state.datasetColumns = result.columns;
        state.profile = result.profile || null;
        persistSession();

        updateDatasetInfo(result);
        enablePreview();
        setSystemStatus('Ready');
        notify(`Uploaded "${result.filename}" (${formatNumber(result.rows)} rows).`, 'success');
    } catch (error) {
        setSystemStatus('Error');
        notify(error?.message || 'Upload failed. Please try again.', 'error');
    } finally {
        setLoading(false);
        els.uploadBtn?.removeAttribute('disabled');
        els.uploadBtn?.classList.remove('opacity-60', 'cursor-not-allowed');
        // Allow re-selecting the same file.
        if (els.csvUpload) els.csvUpload.value = '';
    }
}

/**
 * Update the dataset summary cards.
 * @param {Object} result - UploadResponse
 */
export function updateDatasetInfo(result) {
    if (els.datasetName) els.datasetName.textContent = result.filename || '\u2014';
    if (els.datasetRows) els.datasetRows.textContent = formatNumber(result.rows);
    if (els.datasetColumns) els.datasetColumns.textContent = formatNumber(result.columns);
}

/**
 * Repopulate the dataset cards and enable preview from restored session state
 * (used after a page refresh). Does not perform any network request.
 */
export function restoreDatasetUi() {
    if (!state.sessionId) return;
    updateDatasetInfo({
        filename: state.datasetName,
        rows: state.datasetRows,
        columns: state.datasetColumns,
    });
    if (state.profile) enablePreview();
}

/* ============================================================
   Preview
   ============================================================ */

/** Enable the "Preview Dataset" button once a dataset is loaded. */
function enablePreview() {
    const btn = getPreviewButton();
    if (!btn) return;
    btn.removeAttribute('disabled');
    btn.classList.remove('opacity-60', 'cursor-not-allowed');
}

/**
 * Render a dataset preview into the Results tab, using the profile's sample
 * rows and per-column metadata returned at upload time.
 */
export function showPreview() {
    const container = els.resultsContainer;
    if (!container) return;

    if (!state.profile) {
        notify('Upload a dataset first to preview it.', 'warning');
        return;
    }

    const profile = state.profile;
    const columns = Object.keys(profile.columns || {});
    const sampleRows = Array.isArray(profile.sample_rows) ? profile.sample_rows : [];

    clearNode(container);

    container.append(createEl('div', {
        class: 'mb-4',
        children: [
            createEl('h3', {
                class: 'text-base font-semibold text-slate-900',
                text: `Preview: ${state.datasetName || 'Dataset'}`,
            }),
            createEl('p', {
                class: 'text-sm text-slate-500 mt-1',
                text: `${formatNumber(profile.shape?.rows ?? state.datasetRows)} rows \u00d7 ` +
                    `${formatNumber(profile.shape?.columns ?? state.datasetColumns)} columns ` +
                    `\u2014 showing first ${sampleRows.length} row(s).`,
            }),
        ],
    }));

    container.append(buildTable(columns, sampleRows));
    activateTab('tab-results');
}

/**
 * Build a responsive, scrollable table with sticky headers.
 * @param {string[]} columns
 * @param {Array<Object>} rows
 * @returns {HTMLElement}
 */
export function buildTable(columns, rows) {
    const wrapper = createEl('div', {
        class: 'overflow-auto max-h-[28rem] rounded-lg border border-slate-200',
    });

    const table = createEl('table', { class: 'min-w-full text-sm text-left border-collapse' });

    // Header
    const thead = createEl('thead', { class: 'bg-slate-50 sticky top-0 z-10' });
    const headRow = createEl('tr');
    for (const col of columns) {
        headRow.append(createEl('th', {
            class: 'px-4 py-2 font-semibold text-slate-700 whitespace-nowrap border-b border-slate-200',
            text: col,
            attrs: { scope: 'col' },
        }));
    }
    thead.append(headRow);
    table.append(thead);

    // Body
    const tbody = createEl('tbody');
    if (!rows.length) {
        const emptyRow = createEl('tr');
        emptyRow.append(createEl('td', {
            class: 'px-4 py-6 text-center text-slate-500',
            text: 'No rows to display.',
            attrs: { colspan: String(Math.max(columns.length, 1)) },
        }));
        tbody.append(emptyRow);
    } else {
        rows.forEach((row, index) => {
            const tr = createEl('tr', { class: index % 2 ? 'bg-white' : 'bg-slate-50/40' });
            for (const col of columns) {
                tr.append(createEl('td', {
                    class: 'px-4 py-2 text-slate-600 whitespace-nowrap border-b border-slate-100',
                    text: formatCell(row?.[col]),
                }));
            }
            tbody.append(tr);
        });
    }
    table.append(tbody);
    wrapper.append(table);
    return wrapper;
}
