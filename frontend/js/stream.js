/**
 * stream.js
 * Server-Sent Events processing. Consumes the backend SSE stream and drives
 * the UI: streaming status stepper, system status pill, and the four result
 * tabs (Plan, Results, Chart, Raw JSON).
 *
 * Backend SSE event names handled:
 *   connected, planning_started, planning_completed,
 *   execution_started, execution_completed,
 *   chart_started, chart_completed,
 *   token, completed, error
 *
 * These are mapped onto the spec phases:
 *   thinking -> planning -> executing -> rendering_chart -> completed
 */

'use strict';

import { renderChart, extractTableFromChart } from './chart.js';
import { state } from './state.js';
import {
    els,
    notify,
    setPlaceholder,
    setStreamPhase,
    setSystemStatus,
    updateStreamState,
} from './ui.js';
import {
    clearNode,
    createEl,
    formatNumber,
    prettyJson,
} from './utils.js';
import { buildTable } from './upload.js';

/**
 * Create a fresh accumulator for a single query run.
 * @returns {Object}
 */
export function createStreamContext() {
    return {
        plan: null,
        execution: null,
        chart: null,
        chartGenerated: false,
        explanation: '',
        completed: null,
        errored: false,
        errorMessage: '',
    };
}

/**
 * Handle a single SSE event, updating the accumulator and the live UI.
 * @param {string} eventName
 * @param {Object} data
 * @param {Object} ctx - stream context from createStreamContext()
 */
export function handleStreamEvent(eventName, data, ctx) {
    switch (eventName) {
        case 'connected':
            setStreamPhase('thinking');
            setSystemStatus('Planning');
            break;

        case 'planning_started':
            setStreamPhase('planning');
            setSystemStatus('Planning');
            break;

        case 'planning_completed':
            ctx.plan = data;
            setStreamPhase('planning');
            break;

        case 'execution_started':
            setStreamPhase('executing');
            setSystemStatus('Executing');
            break;

        case 'execution_completed':
            ctx.execution = data;
            setStreamPhase('executing');
            break;

        case 'chart_started':
            setStreamPhase('rendering_chart');
            break;

        case 'chart_completed':
            ctx.chartGenerated = Boolean(data?.chart_generated);
            ctx.chart = data?.chart_data || null;
            renderResultTabs(ctx);
            break;

        case 'token':
            if (typeof data?.token === 'string') ctx.explanation += data.token;
            break;

        case 'completed':
            ctx.completed = data;
            if (data?.explanation) ctx.explanation = data.explanation;
            updateStreamState('completed');
            finalizeStream(ctx);
            break;

        case 'error':
            ctx.errored = true;
            ctx.errorMessage = data?.message || 'The analysis failed.';
            updateStreamState('error');
            setSystemStatus('Error');
            break;

        default:
            // Ignore unknown/keepalive events.
            break;
    }
}

/**
 * Finalize UI after the terminal "completed" event.
 * @param {Object} ctx
 */
function finalizeStream(ctx) {
    setStreamPhase('completed');
    setSystemStatus('Completed');
    renderResultTabs(ctx);
    state.lastResult = buildRawResult(ctx);
    renderJson(state.lastResult);
    renderExplanation(ctx.explanation, ctx.plan);
}

/* ============================================================
   Result tab rendering
   ============================================================ */

/**
 * Render Plan, Results, and Chart tabs from the current context.
 * Safe to call multiple times as data arrives.
 * @param {Object} ctx
 */
export function renderResultTabs(ctx) {
    if (ctx.plan) renderPlan(ctx.plan, ctx.execution);
    renderResults(ctx);
    if (ctx.chartGenerated && ctx.chart) {
        renderChart(ctx.chart);
    } else {
        setPlaceholder(els.chartContainer, 'No chart was generated for this result.');
    }
}

/**
 * Render the analysis plan in a clean, formatted layout (not raw JSON).
 * @param {Object} plan - planning_completed payload (operation, chart_type)
 * @param {Object|null} execution - execution_completed payload
 */
export function renderPlan(plan, execution) {
    const container = els.planContainer;
    if (!container) return;
    clearNode(container);

    const grid = createEl('dl', { class: 'grid grid-cols-1 sm:grid-cols-2 gap-4' });

    const fields = [
        ['Operation', plan.operation],
        ['Chart Type', plan.chart_type],
    ];
    if (execution) {
        fields.push(
            ['Rows Returned', execution.rows_returned != null ? formatNumber(execution.rows_returned) : null],
            ['Columns Returned', execution.columns_returned != null ? formatNumber(execution.columns_returned) : null],
            ['Execution Time', execution.execution_time_ms != null ? `${Number(execution.execution_time_ms).toFixed(1)} ms` : null],
        );
    }

    for (const [label, value] of fields) {
        if (value === null || value === undefined || value === '') continue;
        grid.append(createEl('div', {
            class: 'bg-slate-50 rounded-lg p-4 border border-slate-100',
            children: [
                createEl('dt', {
                    class: 'text-xs font-medium text-slate-500 uppercase tracking-wide',
                    text: label,
                }),
                createEl('dd', { class: 'mt-1 text-sm font-semibold text-slate-900', text: String(value) }),
            ],
        }));
    }

    container.append(
        createEl('h3', { class: 'text-base font-semibold text-slate-900 mb-4', text: 'Analysis Plan' }),
        grid,
    );
}

/**
 * Render the Results tab: an explanation summary plus a reconstructed data
 * table when tabular data is available from the chart figure.
 * @param {Object} ctx
 */
export function renderResults(ctx) {
    const container = els.resultsContainer;
    if (!container) return;
    clearNode(container);

    const heading = createEl('h3', {
        class: 'text-base font-semibold text-slate-900 mb-3',
        text: 'Results',
    });
    container.append(heading);

    // Summary line from execution metadata.
    if (ctx.execution) {
        container.append(createEl('p', {
            class: 'text-sm text-slate-500 mb-4',
            text: `${formatNumber(ctx.execution.rows_returned ?? 0)} row(s) \u00d7 ` +
                `${formatNumber(ctx.execution.columns_returned ?? 0)} column(s).`,
        }));
    }

    const table = ctx.chart ? extractTableFromChart(ctx.chart) : null;
    if (table && table.rows.length) {
        container.append(buildTable(table.columns, table.rows));
    } else if (ctx.explanation) {
        container.append(createEl('div', {
            class: 'prose prose-sm max-w-none text-slate-700 whitespace-pre-wrap',
            text: ctx.explanation,
        }));
    } else {
        container.append(createEl('p', {
            class: 'text-sm text-slate-500',
            text: 'Results will appear here once analysis completes.',
        }));
    }
}

/**
 * Render the streamed natural-language explanation into the Plan tab footer,
 * giving the user readable narrative alongside the structured plan.
 * @param {string} explanation
 * @param {Object|null} plan
 */
export function renderExplanation(explanation, plan) {
    if (!explanation) return;
    const container = els.planContainer;
    if (!container) return;

    container.append(createEl('div', {
        class: 'mt-6 pt-4 border-t border-slate-200',
        children: [
            createEl('h4', { class: 'text-sm font-semibold text-slate-900 mb-2', text: 'Explanation' }),
            createEl('p', { class: 'text-sm text-slate-700 whitespace-pre-wrap', text: explanation }),
        ],
    }));
}

/* ============================================================
   Raw JSON tab
   ============================================================ */

/**
 * Assemble a consolidated raw result object for the JSON tab.
 * @param {Object} ctx
 * @returns {Object}
 */
function buildRawResult(ctx) {
    return {
        plan: ctx.plan,
        execution: ctx.execution,
        chart: ctx.chart,
        explanation: ctx.explanation,
        completed: ctx.completed,
    };
}

/**
 * Pretty-print the raw response with a "Copy JSON" button.
 * @param {Object} result
 */
export function renderJson(result) {
    const container = els.jsonContainer;
    if (!container) return;
    clearNode(container);

    const jsonText = prettyJson(result);

    const header = createEl('div', { class: 'flex items-center justify-between mb-3' });
    header.append(createEl('h3', { class: 'text-base font-semibold text-slate-900', text: 'Raw JSON' }));

    const copyBtn = createEl('button', {
        class: 'inline-flex items-center gap-2 px-3 py-1.5 bg-slate-900 text-white text-xs font-medium ' +
            'rounded-lg hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 transition-colors',
        text: 'Copy JSON',
        attrs: { type: 'button' },
    });
    copyBtn.addEventListener('click', () => copyToClipboard(jsonText, copyBtn));
    header.append(copyBtn);

    const pre = createEl('pre', {
        class: 'bg-slate-900 text-slate-100 rounded-lg p-4 overflow-auto max-h-[28rem] text-xs leading-relaxed',
    });
    pre.append(createEl('code', { class: 'font-mono', text: jsonText }));

    container.append(header, pre);
}

/**
 * Copy text to the clipboard, with a graceful fallback and button feedback.
 * @param {string} text
 * @param {HTMLButtonElement} button
 */
async function copyToClipboard(text, button) {
    const original = button.textContent;
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            fallbackCopy(text);
        }
        button.textContent = 'Copied!';
        notify('JSON copied to clipboard.', 'success', 2500);
    } catch {
        notify('Could not copy JSON to clipboard.', 'error');
    } finally {
        setTimeout(() => { button.textContent = original; }, 1500);
    }
}

/**
 * Legacy clipboard fallback for insecure contexts.
 * @param {string} text
 */
function fallbackCopy(text) {
    const textarea = createEl('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.append(textarea);
    textarea.select();
    document.execCommand('copy');
    textarea.remove();
}
