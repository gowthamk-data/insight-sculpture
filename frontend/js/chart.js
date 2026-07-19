/**
 * chart.js
 * Renders analysis charts with Chart.js (loaded via CDN as the global `Chart`).
 *
 * The backend produces charts as serialized Plotly figures. Rather than pulling
 * in Plotly, we translate the figure's data traces into Chart.js datasets so we
 * can honor the "use Chart.js" requirement while reusing the backend's chart
 * type selection (bar / line / pie / scatter / histogram / heatmap fallback).
 *
 * The same trace data is also used to reconstruct a tabular view for the
 * Results tab, because the serialized execution result omits row-level data.
 */

'use strict';

import { clearNode, createEl, safeJsonParse } from './utils.js';

let activeChart = null;

const PALETTE = [
    '#0ea5e9', '#6366f1', '#f59e0b', '#10b981', '#ef4444',
    '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#64748b',
];

/** Destroy any existing Chart.js instance to prevent canvas/memory leaks. */
export function destroyChart() {
    if (activeChart) {
        try { activeChart.destroy(); } catch { /* noop */ }
        activeChart = null;
    }
}

/**
 * Parse the serialized chart payload from the backend into a usable figure.
 * @param {Object|null} chartData - { chart_type, title, figure, ... }
 * @returns {{ type: string, title: string, figure: Object|null }|null}
 */
export function parseChartData(chartData) {
    if (!chartData) return null;
    const figure =
        typeof chartData.figure === 'string'
            ? safeJsonParse(chartData.figure, null)
            : chartData.figure || null;
    return {
        type: String(chartData.chart_type || 'bar'),
        title: chartData.title || '',
        xAxis: chartData.x_axis || null,
        yAxis: chartData.y_axis || null,
        figure,
    };
}

/**
 * Render a chart into the chart tab using Chart.js.
 * @param {Object|null} chartData - serialized backend chart payload
 * @returns {boolean} true if a chart was rendered
 */
export function renderChart(chartData) {
    const container = document.getElementById('chart-container');
    if (!container) return false;

    destroyChart();
    clearNode(container);

    if (typeof window.Chart === 'undefined') {
        container.append(createEl('p', {
            class: 'text-sm text-red-600',
            text: 'Chart library failed to load.',
        }));
        return false;
    }

    const parsed = parseChartData(chartData);
    const config = parsed ? buildChartConfig(parsed) : null;

    if (!config) {
        container.append(createEl('p', {
            class: 'text-sm text-slate-500',
            text: 'No chart available for this result.',
        }));
        return false;
    }

    if (parsed.title) {
        container.append(createEl('h3', {
            class: 'text-base font-semibold text-slate-900 mb-4',
            text: parsed.title,
        }));
    }

    const wrapper = createEl('div', { class: 'relative w-full', attrs: { style: 'height: 24rem;' } });
    const canvas = createEl('canvas', { attrs: { role: 'img', 'aria-label': parsed.title || 'Analysis chart' } });
    wrapper.append(canvas);
    container.append(wrapper);

    try {
        activeChart = new window.Chart(canvas.getContext('2d'), config);
        return true;
    } catch {
        clearNode(container);
        container.append(createEl('p', {
            class: 'text-sm text-red-600',
            text: 'Unable to render the chart.',
        }));
        return false;
    }
}

/* ============================================================
   Plotly figure -> Chart.js config translation
   ============================================================ */

/**
 * Build a Chart.js config object from a parsed backend figure.
 * @param {{ type: string, title: string, figure: Object|null }} parsed
 * @returns {Object|null}
 */
function buildChartConfig(parsed) {
    const traces = Array.isArray(parsed.figure?.data) ? parsed.figure.data : [];
    if (!traces.length) return null;

    const baseOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, position: 'bottom' } },
    };

    switch (parsed.type) {
        case 'pie':
            return buildPieConfig(traces, baseOptions);
        case 'scatter':
            return buildScatterConfig(traces, parsed, baseOptions);
        case 'histogram':
            return buildHistogramConfig(traces, parsed, baseOptions);
        case 'line':
            return buildXYConfig('line', traces, parsed, baseOptions);
        case 'bar':
        case 'heatmap': // heatmaps are approximated as a bar summary
        default:
            return buildXYConfig('bar', traces, parsed, baseOptions);
    }
}

/**
 * Coerce a Plotly value array into numbers where possible.
 * @param {Array} arr
 * @returns {Array<number>}
 */
function toNumbers(arr) {
    return (arr || []).map((v) => {
        const n = Number(v);
        return Number.isFinite(n) ? n : 0;
    });
}

/** Bar / line share the same category-vs-value structure. */
function buildXYConfig(kind, traces, parsed, baseOptions) {
    const first = traces[0] || {};
    const labels = (first.x || first.labels || []).map(String);

    const datasets = traces.map((trace, index) => {
        const color = PALETTE[index % PALETTE.length];
        return {
            label: trace.name || parsed.yAxis || `Series ${index + 1}`,
            data: toNumbers(trace.y || trace.values),
            backgroundColor: kind === 'line' ? `${color}33` : color,
            borderColor: color,
            borderWidth: 2,
            fill: kind === 'line' ? false : undefined,
            tension: kind === 'line' ? 0.25 : undefined,
            pointRadius: kind === 'line' ? 3 : undefined,
        };
    });

    return {
        type: kind,
        data: { labels, datasets },
        options: {
            ...baseOptions,
            scales: {
                x: { title: { display: !!parsed.xAxis, text: parsed.xAxis || '' } },
                y: { beginAtZero: true, title: { display: !!parsed.yAxis, text: parsed.yAxis || '' } },
            },
        },
    };
}

/** Pie chart from a single trace's labels/values. */
function buildPieConfig(traces, baseOptions) {
    const first = traces[0] || {};
    const labels = (first.labels || first.x || []).map(String);
    const values = toNumbers(first.values || first.y);
    return {
        type: 'pie',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
                borderColor: '#ffffff',
                borderWidth: 2,
            }],
        },
        options: baseOptions,
    };
}

/** Scatter chart from paired numeric x/y arrays. */
function buildScatterConfig(traces, parsed, baseOptions) {
    const datasets = traces.map((trace, index) => {
        const xs = toNumbers(trace.x);
        const ys = toNumbers(trace.y);
        const points = xs.map((x, i) => ({ x, y: ys[i] ?? 0 }));
        const color = PALETTE[index % PALETTE.length];
        return {
            label: trace.name || `Series ${index + 1}`,
            data: points,
            backgroundColor: color,
            borderColor: color,
            pointRadius: 4,
        };
    });

    return {
        type: 'scatter',
        data: { datasets },
        options: {
            ...baseOptions,
            scales: {
                x: { type: 'linear', position: 'bottom', title: { display: !!parsed.xAxis, text: parsed.xAxis || '' } },
                y: { title: { display: !!parsed.yAxis, text: parsed.yAxis || '' } },
            },
        },
    };
}

/**
 * Histogram: Plotly histograms carry raw x values and bin client-side.
 * Chart.js has no native histogram, so we bin here and render as a bar chart.
 */
function buildHistogramConfig(traces, parsed, baseOptions) {
    const first = traces[0] || {};
    const values = toNumbers(first.x || first.y);
    if (!values.length) return null;

    const { labels, counts } = computeHistogram(values);
    return {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: parsed.xAxis || 'Count',
                data: counts,
                backgroundColor: PALETTE[0],
                borderColor: PALETTE[0],
                borderWidth: 1,
            }],
        },
        options: {
            ...baseOptions,
            plugins: { legend: { display: false } },
            scales: {
                x: { title: { display: !!parsed.xAxis, text: parsed.xAxis || '' } },
                y: { beginAtZero: true, title: { display: true, text: 'Count' } },
            },
        },
    };
}

/**
 * Bin numeric values into evenly spaced buckets (Sturges' rule).
 * @param {Array<number>} values
 * @returns {{ labels: string[], counts: number[] }}
 */
function computeHistogram(values) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    if (min === max) return { labels: [String(min)], counts: [values.length] };

    const binCount = Math.max(1, Math.ceil(Math.log2(values.length) + 1));
    const width = (max - min) / binCount;
    const counts = new Array(binCount).fill(0);

    for (const v of values) {
        const idx = Math.min(binCount - 1, Math.floor((v - min) / width));
        counts[idx] += 1;
    }

    const labels = counts.map((_, i) => {
        const lo = min + i * width;
        const hi = lo + width;
        return `${lo.toFixed(1)}\u2013${hi.toFixed(1)}`;
    });

    return { labels, counts };
}

/* ============================================================
   Tabular reconstruction (for the Results tab)
   ============================================================ */

/**
 * Reconstruct row records from a serialized chart figure so the Results tab
 * can display actual data even though the execution result omits the dataframe.
 * @param {Object|null} chartData
 * @returns {{ columns: string[], rows: Array<Object> }|null}
 */
export function extractTableFromChart(chartData) {
    const parsed = parseChartData(chartData);
    const traces = Array.isArray(parsed?.figure?.data) ? parsed.figure.data : [];
    if (!traces.length) return null;

    const first = traces[0];

    // Pie: labels + values.
    if (parsed.type === 'pie' && (first.labels || first.values)) {
        const labels = first.labels || [];
        const values = first.values || [];
        return {
            columns: ['label', 'value'],
            rows: labels.map((label, i) => ({ label, value: values[i] ?? null })),
        };
    }

    // Scatter: x/y pairs across traces.
    if (parsed.type === 'scatter') {
        const xLabel = parsed.xAxis || 'x';
        const yLabel = parsed.yAxis || 'y';
        const rows = [];
        for (const trace of traces) {
            const xs = trace.x || [];
            const ys = trace.y || [];
            xs.forEach((x, i) => rows.push({ [xLabel]: x, [yLabel]: ys[i] ?? null }));
        }
        return rows.length ? { columns: [xLabel, yLabel], rows } : null;
    }

    // Histogram: raw values in a single column.
    if (parsed.type === 'histogram') {
        const col = parsed.xAxis || 'value';
        const vals = first.x || first.y || [];
        return vals.length ? { columns: [col], rows: vals.map((v) => ({ [col]: v })) } : null;
    }

    // Bar / line / other: category (x) + one column per trace.
    const xLabel = parsed.xAxis || 'category';
    const labels = first.x || first.labels || [];
    if (!labels.length) return null;

    const seriesNames = traces.map((t, i) => t.name || parsed.yAxis || `series_${i + 1}`);
    const rows = labels.map((label, rowIndex) => {
        const row = { [xLabel]: label };
        traces.forEach((trace, tIndex) => {
            const y = trace.y || trace.values || [];
            row[seriesNames[tIndex]] = y[rowIndex] ?? null;
        });
        return row;
    });

    return { columns: [xLabel, ...seriesNames], rows };
}
