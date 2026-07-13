/**
 * Insight Sculpture - Chart Manager Module
 *
 * This module is responsible ONLY for rendering and managing data visualizations.
 * It does NOT upload files, communicate with the backend, call fetch(), manage
 * chat, manage SSE connections, execute analytics, manipulate application state,
 * or contain business logic.
 *
 * Data flow:
 *   Receive Chart Data  ->  Validate  ->  Render Plotly Chart  ->  Update  ->  Destroy
 *
 * Charts are received exclusively through frontend events (never directly from the
 * backend). All incoming data is treated as untrusted; nothing is ever eval'd and
 * no executable content is injected into the DOM.
 *
 * Dependencies:
 *   - Plotly.js (global `Plotly`, loaded via CDN in index.html)
 *   - DOM ids from index.html: #visualization-section, #chart-container,
 *     #chart-placeholder, #chart-loading
 *
 * @module charts
 */

// ============================================================
// Constants
// ============================================================

/**
 * Chart types this module can render today. Charts are figure-driven (the backend
 * supplies a fully-built Plotly figure), so any type the backend can produce a
 * figure for is renderable. These are kept explicit so unknown/future types can be
 * rejected gracefully rather than silently mis-rendered.
 *
 * @const {Set<string>}
 */
const KNOWN_CHART_TYPES = new Set([
    // Supported
    'bar',
    'line',
    'scatter',
    'pie',
    'histogram',
    // Future-ready (accepted; backend can build the figure)
    'box',
    'heatmap',
    'area',
    'bubble',
]);

/**
 * Export formats supported today. PDF is intentionally excluded from the active
 * set but the public API accepts it and reports a friendly "not yet supported"
 * message so adding it later is a one-line change.
 *
 * @const {Set<string>}
 */
const SUPPORTED_EXPORT_FORMATS = new Set(['png', 'svg']);

/** @const {string} Default export filename stem. */
const DEFAULT_EXPORT_FILENAME = 'insight-sculpture-chart';

/** @const {number} Debounce window (ms) for window resize re-layout. */
const RESIZE_DEBOUNCE_MS = 200;

/** @const {string} DOM id for the Plotly render target we manage. */
const PLOT_DIV_ID = 'chart-plot';

// ============================================================
// Error Types
// ============================================================

/**
 * Base error for chart operations. Carries a user-friendly message only.
 */
class ChartError extends Error {
    /**
     * @param {string} message - User-friendly, non-technical message.
     * @param {string} [code] - Stable machine code for programmatic handling.
     */
    constructor(message, code = 'CHART_ERROR') {
        super(message);
        this.name = 'ChartError';
        this.code = code;
    }
}

/**
 * Raised when a chart type is not in the known set.
 */
class ChartUnsupportedError extends ChartError {
    /**
     * @param {string} chartType - The unsupported chart type name.
     */
    constructor(chartType) {
        super(
            `Charts of type "${chartType || 'unknown'}" are not supported.`,
            'UNSUPPORTED_CHART_TYPE'
        );
        this.chartType = chartType;
    }
}

// ============================================================
// Chart Manager
// ============================================================

/**
 * Manages a single, reusable Plotly chart surface.
 *
 * The manager is intentionally limited to one visible chart at a time (the current
 * "active" chart). Future dashboard/multi-chart features can layer on top of the
 * public API without changing it.
 */
class ChartManager {
    /**
     * @param {Object} [options]
     * @param {Object} [options.plotly] - Plotly reference (defaults to window.Plotly).
     *   Injectable to make rendering mockable in tests.
     * @param {Object} [options.dom] - Optional DOM overrides for testing.
     */
    constructor(options = {}) {
        /**
         * Plotly entry point (injected or global). Never call Plotly directly
         * except through this reference.
         * @private
         * @type {Object|null}
         */
        this._plotly = options.plotly || (typeof window !== 'undefined' ? window.Plotly : null);

        /**
         * Resolved DOM elements.
         * @private
         * @type {Object}
         */
        this._dom = options.dom || null;

        /**
         * The managed Plotly render target.
         * @private
         * @type {HTMLElement|null}
         */
        this._plotDiv = null;

        /**
         * The currently rendered, validated chart payload.
         * @private
         * @type {Object|null}
         */
        this._currentChart = null;

        /**
         * Whether the manager has been initialized.
         * @private
         * @type {boolean}
         */
        this._initialized = false;

        /**
         * Bound event handlers (kept for clean removal).
         * @private
         * @type {Object}
         */
        this._handlers = {};

        /**
         * Pending resize timer handle.
         * @private
         * @type {number|null}
         */
        this._resizeTimer = null;
    }

    // ============================================================
    // Initialization
    // ============================================================

    /**
     * Initialize the chart manager: cache DOM, create the plot surface, bind
     * events, and show the empty state.
     *
     * Safe to call once. Returns the manager for chaining/storage by app.js.
     *
     * @returns {ChartManager} This instance.
     */
    init() {
        if (this._initialized) {
            console.warn('[Charts] Already initialized, skipping.');
            return this;
        }

        this._cacheDOMElements();
        this._assertPlotly();
        this._ensurePlotDiv();
        this._bindEventListeners();

        this._showEmptyState();

        this._initialized = true;
        console.log('[Charts] ChartManager initialized');

        return this;
    }

    /**
     * Resolve the DOM elements the manager depends on.
     *
     * @private
     */
    _cacheDOMElements() {
        const $ = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

        this._dom = {
            section: $('visualization-section'),
            container: $('chart-container'),
            placeholder: $('chart-placeholder'),
            loading: $('chart-loading'),
        };
    }

    /**
     * Warn (do not throw) if Plotly is unavailable so the rest of the app keeps
     * working; chart operations will then report friendly errors.
     *
     * @private
     */
    _assertPlotly() {
        if (!this._plotly) {
            console.warn(
                '[Charts] Plotly.js is not available. Charts cannot be rendered. ' +
                'Ensure the Plotly CDN script is loaded before charts.js.'
            );
        }
    }

    /**
     * Create (once) the div Plotly renders into, appended to the chart container.
     * Reuses the same node across renders to avoid leaks.
     *
     * @returns {HTMLElement} The plot div.
     * @private
     */
    _ensurePlotDiv() {
        if (this._plotDiv && this._plotDiv.parentNode) {
            return this._plotDiv;
        }

        if (typeof document === 'undefined' || !this._dom || !this._dom.container) {
            return null;
        }

        let plotDiv = document.getElementById(PLOT_DIV_ID);
        if (!plotDiv) {
            plotDiv = document.createElement('div');
            plotDiv.id = PLOT_DIV_ID;
            plotDiv.className = 'w-full h-full';
            plotDiv.style.width = '100%';
            plotDiv.style.height = '100%';
            this._dom.container.appendChild(plotDiv);
        }

        // Always start hidden until a valid chart exists.
        plotDiv.style.display = 'none';
        this._plotDiv = plotDiv;
        return plotDiv;
    }

    /**
     * Subscribe to the events this module reacts to.
     *
     * @private
     */
    _bindEventListeners() {
        if (typeof document === 'undefined') {
            return;
        }

        this._handlers.streamChart = this._handleStreamChart.bind(this);
        this._handlers.analysisChartReady = this._handleAnalysisChartReady.bind(this);
        this._handlers.datasetUploaded = this._handleDatasetUploaded.bind(this);
        this._handlers.windowResize = this._handleWindowResize.bind(this);

        document.addEventListener('streamChart', this._handlers.streamChart);
        document.addEventListener('analysisChartReady', this._handlers.analysisChartReady);
        document.addEventListener('datasetUploaded', this._handlers.datasetUploaded);

        if (typeof window !== 'undefined') {
            window.addEventListener('resize', this._handlers.windowResize);
        }
    }

    // ============================================================
    // Public API — Rendering
    // ============================================================

    /**
     * Render a (validated) chart payload as a brand-new chart.
     * Destroys any existing chart first to prevent leaks.
     *
     * @param {Object} chart - Backend chart payload. May contain `figure`
     *   (Plotly JSON string or object), or `data`+`layout`.
     * @returns {boolean} True if rendered successfully.
     */
    renderChart(chart) {
        try {
            const validated = this._validateChartPayload(chart);

            const plotDiv = this._ensurePlotDiv();
            if (!plotDiv) {
                throw new ChartError('Chart container is not available in the document.');
            }

            // Tear down any previous chart before drawing the new one.
            this._purgeCurrent();

            const config = this._buildPlotlyConfig();
            this._plotly.newPlot(
                plotDiv,
                validated.figure.data,
                validated.figure.layout || {},
                config
            );

            this._currentChart = validated;
            this._applyAccessibility(plotDiv, validated);
            this._showChart(validated);
            this.resizeChart();

            this._emit('chartRendered', {
                chartType: validated.chartType,
                title: validated.title,
                hasFigure: Boolean(validated.figure),
            });

            return true;
        } catch (error) {
            this._handleError(error, 'render');
            return false;
        }
    }

    /**
     * Update the currently displayed chart in place using Plotly.react (avoids a
     * full teardown/re-create). If no chart is currently shown, this falls back to
     * a full render.
     *
     * @param {Object} chart - Backend chart payload.
     * @returns {boolean} True if updated successfully.
     */
    updateChart(chart) {
        try {
            const validated = this._validateChartPayload(chart);

            const plotDiv = this._ensurePlotDiv();
            if (!plotDiv) {
                throw new ChartError('Chart container is not available in the document.');
            }

            const config = this._buildPlotlyConfig();

            if (this._currentChart) {
                this._plotly.react(
                    plotDiv,
                    validated.figure.data,
                    validated.figure.layout || {},
                    config
                );
            } else {
                this._purgeCurrent();
                this._plotly.newPlot(
                    plotDiv,
                    validated.figure.data,
                    validated.figure.layout || {},
                    config
                );
            }

            this._currentChart = validated;
            this._applyAccessibility(plotDiv, validated);
            this._showChart(validated);
            this.resizeChart();

            this._emit('chartUpdated', {
                chartType: validated.chartType,
                title: validated.title,
            });

            return true;
        } catch (error) {
            this._handleError(error, 'update');
            return false;
        }
    }

    /**
     * Clear the current chart and return to the empty state.
     */
    clearChart() {
        this._purgeCurrent();
        this._currentChart = null;
        this._showEmptyState();

        this._emit('chartCleared', {});
    }

    /**
     * Resize the active chart to fit its container. No-op if nothing is rendered
     * or Plotly is unavailable.
     */
    resizeChart() {
        if (!this._plotly || !this._plotDiv || !this._currentChart) {
            return;
        }
        try {
            this._plotly.Plots.resize(this._plotDiv);
        } catch (error) {
            // Resizing is best-effort; never let it break the app.
            console.warn('[Charts] Resize failed:', error && error.message);
        }
    }

    /**
     * Export the current chart as an image and trigger a browser download.
     *
     * @param {string} [format='png'] - 'png' or 'svg' (pdf prepared but not active).
     * @returns {boolean} True if an export was initiated.
     */
    exportChart(format = 'png') {
        const normalized = String(format || 'png').toLowerCase();

        if (normalized === 'pdf') {
            // Prepared for future support; not active yet.
            this._handleError(
                new ChartError('PDF export is not yet supported.', 'EXPORT_NOT_SUPPORTED'),
                'export'
            );
            return false;
        }

        if (!SUPPORTED_EXPORT_FORMATS.has(normalized)) {
            this._handleError(
                new ChartError(
                    `Unsupported export format "${normalized}". Use png or svg.`,
                    'EXPORT_UNSUPPORTED_FORMAT'
                ),
                'export'
            );
            return false;
        }

        if (!this._plotly || !this._plotDiv || !this._currentChart) {
            this._handleError(
                new ChartError('No chart is available to export.', 'EXPORT_NO_CHART'),
                'export'
            );
            return false;
        }

        const filename = this._buildExportFilename(normalized);

        try {
            const promise = this._plotly.downloadImage(this._plotDiv, {
                format: normalized,
                filename,
                scale: 2,
            });

            if (promise && typeof promise.then === 'function') {
                promise.then(
                    () => {
                        this._emit('chartExported', { format: normalized, filename });
                    },
                    (err) => {
                        this._handleError(
                            new ChartError('Failed to export chart image.', 'EXPORT_FAILED'),
                            'export'
                        );
                        console.error('[Charts] Export failed:', err && err.message);
                    }
                );
            } else {
                this._emit('chartExported', { format: normalized, filename });
            }
            return true;
        } catch (error) {
            this._handleError(error, 'export');
            return false;
        }
    }

    /**
     * Fully tear down: purge the chart, remove listeners, release references.
     * Safe to call multiple times.
     */
    destroy() {
        this._purgeCurrent();
        this._currentChart = null;

        if (this._resizeTimer !== null && typeof clearTimeout === 'function') {
            clearTimeout(this._resizeTimer);
            this._resizeTimer = null;
        }

        if (typeof document !== 'undefined') {
            document.removeEventListener('streamChart', this._handlers.streamChart);
            document.removeEventListener('analysisChartReady', this._handlers.analysisChartReady);
            document.removeEventListener('datasetUploaded', this._handlers.datasetUploaded);
        }
        if (typeof window !== 'undefined') {
            window.removeEventListener('resize', this._handlers.windowResize);
        }

        this._initialized = false;
        console.log('[Charts] ChartManager destroyed');
    }

    // ============================================================
    // Public API — Introspection
    // ============================================================

    /**
     * @returns {boolean} True if a chart is currently rendered.
     */
    hasChart() {
        return Boolean(this._currentChart);
    }

    /**
     * @returns {Object|null} The current validated chart payload (or null).
     */
    getCurrentChart() {
        return this._currentChart ? { ...this._currentChart } : null;
    }

    /**
     * @returns {string|null} The current chart type.
     */
    getCurrentChartType() {
        return this._currentChart ? this._currentChart.chartType : null;
    }

    // ============================================================
    // Validation & Normalization
    // ============================================================

    /**
     * Validate an incoming chart payload and extract a renderable Plotly figure.
     *
     * @param {Object} chart - Raw chart payload (object or string-figure).
     * @returns {Object} Normalized { chartType, figure, title, description, metadata }.
     * @throws {ChartError|ChartUnsupportedError} When the payload is invalid.
     * @private
     */
    _validateChartPayload(chart) {
        if (!chart || typeof chart !== 'object') {
            throw new ChartError('Chart payload is missing or invalid.', 'INVALID_CHART');
        }

        const chartType = String(chart.chart_type || chart.type || '').toLowerCase();
        if (!chartType) {
            throw new ChartError('Chart type is missing from the payload.', 'MISSING_CHART_TYPE');
        }
        if (!KNOWN_CHART_TYPES.has(chartType)) {
            throw new ChartUnsupportedError(chartType);
        }

        let figure = null;
        if (chart.figure != null) {
            figure =
                typeof chart.figure === 'string'
                    ? this._safeJsonParse(chart.figure)
                    : chart.figure;
        } else if (Array.isArray(chart.data) && chart.layout != null) {
            figure = { data: chart.data, layout: chart.layout };
        }

        if (!figure || !Array.isArray(figure.data)) {
            throw new ChartError(
                'Chart contains no renderable data.',
                'NO_RENDERABLE_DATA'
            );
        }

        return {
            chartType,
            figure,
            title: typeof chart.title === 'string' ? chart.title : '',
            description: typeof chart.description === 'string' ? chart.description : '',
            metadata: chart.metadata && typeof chart.metadata === 'object' ? chart.metadata : {},
        };
    }

    /**
     * Parse a Plotly JSON figure string safely.
     *
     * @param {string} json - Figure JSON.
     * @returns {Object} Parsed figure.
     * @throws {ChartError} On malformed JSON.
     * @private
     */
    _safeJsonParse(json) {
        try {
            const parsed = JSON.parse(json);
            if (!parsed || typeof parsed !== 'object') {
                throw new ChartError('Chart figure JSON is not an object.', 'INVALID_CHART_JSON');
            }
            return parsed;
        } catch (error) {
            if (error instanceof ChartError) {
                throw error;
            }
            throw new ChartError('Chart figure JSON could not be parsed.', 'INVALID_CHART_JSON');
        }
    }

    // ============================================================
    // Plotly Helpers
    // ============================================================

    /**
     * Build a consistent Plotly config.
     *
     * @returns {Object}
     * @private
     */
    _buildPlotlyConfig() {
        return {
            responsive: true,
            displaylogo: false,
            toImageButtonOptions: {
                format: 'png',
                filename: DEFAULT_EXPORT_FILENAME,
                scale: 2,
            },
            modeBarButtonsToRemove: ['lasso2d', 'select2d'],
        };
    }

    /**
     * Remove the currently displayed Plotly chart without throwing.
     *
     * @private
     */
    _purgeCurrent() {
        if (!this._plotly || !this._plotDiv) {
            return;
        }
        try {
            this._plotly.purge(this._plotDiv);
        } catch (error) {
            // Ignore purge errors; we are tearing down anyway.
            console.warn('[Charts] Purge failed:', error && error.message);
        }
    }

    // ============================================================
    // View State
    // ============================================================

    /**
     * Reveal the chart and hide placeholders.
     *
     * @param {Object} validated - Validated chart payload.
     * @private
     */
    _showChart(validated) {
        if (this._dom && this._dom.section) {
            this._dom.section.classList.remove('hidden');
        }
        if (this._plotDiv) {
            this._plotDiv.style.display = 'block';
        }
        if (this._dom && this._dom.placeholder) {
            this._dom.placeholder.classList.add('hidden');
        }
        if (this._dom && this._dom.loading) {
            this._dom.loading.classList.add('hidden');
        }
        if (validated && validated.title && typeof this._dom !== 'undefined') {
            // No-op hook for future title rendering; kept for extensibility.
        }
    }

    /**
     * Show the empty/no-chart state.
     *
     * @private
     */
    _showEmptyState() {
        if (this._plotDiv) {
            this._plotDiv.style.display = 'none';
        }
        if (this._dom && this._dom.placeholder) {
            this._dom.placeholder.classList.remove('hidden');
            this._dom.placeholder.textContent = 'No visualization available.';
        }
        if (this._dom && this._dom.loading) {
            this._dom.loading.classList.add('hidden');
        }
        // Keep the section hidden until a chart actually exists.
        if (this._dom && this._dom.section) {
            this._dom.section.classList.add('hidden');
        }
    }

    /**
     * Show the "generating" spinner state (used during streaming).
     *
     * @private
     */
    _showLoading() {
        if (this._plotDiv) {
            this._plotDiv.style.display = 'none';
        }
        if (this._dom && this._dom.placeholder) {
            this._dom.placeholder.classList.add('hidden');
        }
        if (this._dom && this._dom.loading) {
            this._dom.loading.classList.remove('hidden');
        }
    }

    // ============================================================
    // Accessibility
    // ============================================================

    /**
     * Attach accessible metadata to the plot surface. Plotly renders SVG; we give
     * the container a role/label and an off-screen text description as a fallback.
     *
     * @param {HTMLElement} plotDiv - The Plotly target.
     * @param {Object} validated - Validated chart payload.
     * @private
     */
    _applyAccessibility(plotDiv, validated) {
        if (!plotDiv) {
            return;
        }
        plotDiv.setAttribute('role', 'img');
        plotDiv.setAttribute('aria-label', this._buildAriaLabel(validated));

        // Remove any previous fallback text node we added.
        const existing = plotDiv.querySelector('.chart-a11y-desc');
        if (existing) {
            existing.remove();
        }

        const desc = document.createElement('p');
        desc.className = 'chart-a11y-desc';
        desc.setAttribute('aria-hidden', 'true');
        desc.style.position = 'absolute';
        desc.style.width = '1px';
        desc.style.height = '1px';
        desc.style.overflow = 'hidden';
        desc.style.clip = 'rect(0 0 0 0)';
        desc.textContent = this._buildAriaLabel(validated);
        plotDiv.appendChild(desc);
    }

    /**
     * Build a human-readable description of the chart for screen readers.
     *
     * @param {Object} validated - Validated chart payload.
     * @returns {string}
     * @private
     */
    _buildAriaLabel(validated) {
        const type = validated.chartType || 'chart';
        const title = validated.title || validated.description || '';
        const base = `Data visualization: ${type} chart`;
        return title ? `${base}. ${title}` : base;
    }

    // ============================================================
    // Export Helpers
    // ============================================================

    /**
     * Build a safe export filename from the current chart title.
     *
     * @param {string} format - Export format extension stem.
     * @returns {string}
     * @private
     */
    _buildExportFilename(format) {
        const safeTitle = (this._currentChart && this._currentChart.title
            ? String(this._currentChart.title)
            : DEFAULT_EXPORT_FILENAME
        )
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 60);

        const stem = safeTitle || DEFAULT_EXPORT_FILENAME;
        return `${stem}.${format}`;
    }

    // ============================================================
    // Event Handlers
    // ============================================================

    /**
     * Handle a `streamChart` event from the streaming module.
     *
     * @param {CustomEvent} event
     * @private
     */
    _handleStreamChart(event) {
        const detail = (event && event.detail) || {};

        if (detail.status === 'generating') {
            this._showLoading();
            return;
        }

        if (detail.status === 'completed') {
            const chart = detail.chartData || detail.chart || null;
            if (chart && (chart.figure != null || (Array.isArray(chart.data) && chart.layout != null))) {
                this.renderChart(chart);
            } else {
                // Streamed without a renderable figure (e.g. no chart recommended).
                this.clearChart();
            }
        }
    }

    /**
     * Handle an `analysisChartReady` event (from the analyze path).
     *
     * @param {CustomEvent} event
     * @private
     */
    _handleAnalysisChartReady(event) {
        const detail = (event && event.detail) || {};
        const chart = detail.chart || detail.chartData || detail.chart_data || detail;
        if (chart) {
            this.renderChart(chart);
        }
    }

    /**
     * Handle a `datasetUploaded` event: reset to empty state.
     *
     * @private
     */
    _handleDatasetUploaded() {
        this.clearChart();
    }

    /**
     * Handle window resize with debounce.
     *
     * @private
     */
    _handleWindowResize() {
        if (typeof clearTimeout === 'function') {
            clearTimeout(this._resizeTimer);
        }
        this._resizeTimer = setTimeout(() => {
            this.resizeChart();
        }, RESIZE_DEBOUNCE_MS);
    }

    // ============================================================
    // Error Handling
    // ============================================================

    /**
     * Normalize and surface a chart error as a friendly, non-technical message.
     * Never exposes stack traces or raw exception text to the user.
     *
     * @param {Error} error - The caught error.
     * @param {string} [context] - Where the error occurred.
     * @private
     */
    _handleError(error, context = 'unknown') {
        const message =
            error && error.message
                ? error.message
                : 'An unexpected error occurred while preparing the visualization.';

        console.error(`[Charts] ${context} error:`, error && error.message);

        this._emit('chartError', {
            code: error && error.code ? error.code : 'CHART_ERROR',
            context,
            message,
        });
    }

    // ============================================================
    // Event Dispatch
    // ============================================================

    /**
     * Dispatch a CustomEvent on the document.
     *
     * @param {string} eventName
     * @param {Object} detail
     * @private
     */
    _emit(eventName, detail) {
        if (typeof document === 'undefined') {
            return;
        }
        const event = new CustomEvent(eventName, {
            bubbles: true,
            cancelable: true,
            detail,
        });
        document.dispatchEvent(event);
    }
}

// ============================================================
// Initialization Function
// ============================================================

/**
 * Initialize the charts module.
 *
 * Creates a ChartManager instance, initializes it, and returns it for storage by
 * the application module (app.js), which calls `await window.initializeCharts()`.
 *
 * @param {Object} [config] - Optional configuration (e.g. { plotly } for tests).
 * @returns {ChartManager} The initialized ChartManager instance.
 */
function initializeCharts(config = {}) {
    const manager = new ChartManager(config);
    manager.init();
    return manager;
}

// ============================================================
// Global Exports
// ============================================================

// Expose for app.js initialization discovery.
if (typeof window !== 'undefined') {
    window.initializeCharts = initializeCharts;

    // Expose the class for testing and direct access.
    window.ChartManager = ChartManager;
}

console.log('[Charts] Chart module loaded');
