(function () {
    "use strict";

    const SVG_NS = "http://www.w3.org/2000/svg";
    const CHART_ORDER = [
        "topic_distribution", "accuracy_per_topic", "accuracy_vs_phase",
        "correctness_per_reply", "response_time_trend", "rating_distribution",
        "length_preference"
    ];
    const TABLE_ORDER = [
        "topic_vs_accuracy", "reply_correctness", "phase_wise_accuracy",
        "response_time_summary", "rating_distribution", "length_preference"
    ];
    const PALETTE = ["#ba8cff", "#78bbff", "#e4bb80", "#f091bd", "#85dcc8", "#a9a9f7", "#f6cb86"];
    const OVERVIEW = [
        { key: "total_interactions", label: "Total Interactions", kind: "number" },
        { key: "weighted_accuracy_percentage", label: "Weighted Accuracy", kind: "percent" },
        { key: "strict_correct_percentage", label: "Strict Correct", kind: "percent" },
        { key: "average_rating", label: "Average Rating", kind: "rating" },
        { key: "average_response_time_seconds", label: "Average Response Time", kind: "seconds" },
        { key: "dominant_topic", label: "Dominant Topic", kind: "text" },
        { key: "feedback_submitted_count", label: "Feedback Submitted", kind: "number" },
        { key: "dominant_length_preference", label: "Preferred Length", kind: "text" }
    ];

    function isNumber(value) {
        return typeof value === "number" && Number.isFinite(value);
    }

    function displayValue(value, kind) {
        if (value === null || value === undefined || value === "") return "N/A";
        if (kind === "text") return String(value);
        if (!isNumber(value)) return "N/A";
        const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: kind === "seconds" ? 3 : 2 }).format(value);
        if (kind === "percent") return `${formatted}%`;
        if (kind === "seconds") return `${formatted} s`;
        if (kind === "rating") return `${formatted} / 4`;
        return formatted;
    }

    function sessionTimestamp(value) {
        if (typeof value !== "string" || !value.trim()) return NaN;
        const text = value.trim();
        // Mongo's naive datetime ISO strings represent UTC in the existing API.
        const withoutZone = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;
        const timestamp = withoutZone.test(text)
            ? Date.parse(`${text.replace(" ", "T")}Z`)
            : Date.parse(text);
        return Number.isFinite(timestamp) ? timestamp : NaN;
    }

    function chooseSession(sessions, preferredId, currentId) {
        if (!Array.isArray(sessions) || !sessions.length) return null;
        const owned = sessions.filter(session => session && typeof session.session_id === "string");
        if (!owned.length) return null;
        const match = id => owned.find(session => session.session_id === id);
        if (currentId && match(currentId)) return match(currentId).session_id;
        if (preferredId && match(preferredId)) return match(preferredId).session_id;
        const newest = owned.slice().sort((left, right) => {
            const l = sessionTimestamp(left.updated_at);
            const r = sessionTimestamp(right.updated_at);
            if (!Number.isFinite(l)) return Number.isFinite(r) ? 1 : left.session_id.localeCompare(right.session_id);
            if (!Number.isFinite(r)) return -1;
            return r - l || left.session_id.localeCompare(right.session_id);
        });
        return newest[0].session_id;
    }

    function finalizationPresentation(finalization, session) {
        if (finalization && finalization.is_finalized === true) {
            const timestamp = sessionTimestamp(finalization.finalized_at);
            return {
                label: "Finalized",
                date: Number.isFinite(timestamp) ? `Finalized ${new Date(timestamp).toLocaleString()}` : "",
                finalized: true
            };
        }
        return {
            label: session && session.status === "active" ? "Active" : "Ended",
            date: "",
            finalized: false
        };
    }

    function chartValues(spec) {
        const dataset = spec && Array.isArray(spec.datasets) ? spec.datasets[0] : null;
        return dataset && Array.isArray(dataset.values) ? dataset.values : [];
    }

    function chartHasData(spec) {
        if (!spec || spec.empty) return false;
        const values = chartValues(spec);
        if (spec.type === "pie") return values.some(value => isNumber(value) && value > 0);
        return values.some(value => isNumber(value) && value >= 0);
    }

    function svgElement(tag, attributes) {
        const element = document.createElementNS(SVG_NS, tag);
        Object.entries(attributes || {}).forEach(([key, value]) => element.setAttribute(key, String(value)));
        return element;
    }

    function svgText(svg, x, y, content, attributes) {
        const node = svgElement("text", { x, y, ...attributes });
        node.textContent = String(content);
        svg.appendChild(node);
        return node;
    }

    function pointTitle(element, content) {
        const title = svgElement("title");
        title.textContent = content;
        element.appendChild(title);
    }

    function axisMaximum(spec, values) {
        const limit = spec && spec.metadata && spec.metadata.y_max;
        if (isNumber(limit) && limit > 0) return limit;
        const max = values.reduce((current, value) => isNumber(value) && value >= 0 ? Math.max(current, value) : current, 0);
        if (max === 0) return 1;
        if (max <= 4 && spec.metadata && spec.metadata.unit === "count") return Math.max(1, Math.ceil(max));
        const step = Math.pow(10, Math.floor(Math.log10(max)));
        const rounded = Math.ceil(max / step) * step;
        return Number.isFinite(rounded) && rounded >= max ? rounded : max;
    }

    function chartNumber(value, unit) {
        if (!isNumber(value)) return "N/A";
        return displayValue(value, unit === "percent" ? "percent" : unit === "seconds" ? "seconds" : "number");
    }

    function pointDescription(spec, index, label, value, unit) {
        const point = spec.metadata && Array.isArray(spec.metadata.points) ? spec.metadata.points[index] : null;
        const context = point ? [point.topic_label, point.phase, point.correctness].filter(Boolean).join(" · ") : "";
        return `${label}: ${chartNumber(value, unit)}${context ? ` · ${context}` : ""}`;
    }

    function plotFrame(spec, count) {
        const width = Math.max(520, count * 78 + 90);
        const height = 300;
        const frame = { width, height, left: 52, top: 24, right: 18, bottom: 74 };
        frame.plotWidth = width - frame.left - frame.right;
        frame.plotHeight = height - frame.top - frame.bottom;
        const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": spec.title || "Analytics chart" });
        svg.style.minWidth = `${width}px`;
        return { frame, svg };
    }

    function renderAxes(svg, frame, maximum, unit) {
        [0, .5, 1].forEach(fraction => {
            const y = frame.top + frame.plotHeight * (1 - fraction);
            svg.appendChild(svgElement("line", {
                x1: frame.left, y1: y, x2: frame.width - frame.right, y2: y,
                stroke: fraction === 0 ? "#a68cce" : "#55446f", "stroke-opacity": fraction === 0 ? .8 : .45
            }));
            svgText(svg, frame.left - 9, y + 4, chartNumber(maximum * fraction, unit), { "text-anchor": "end" });
        });
    }

    function xLabel(svg, x, y, label) {
        const full = String(label);
        const node = svgText(svg, x, y, full.length > 20 ? `${full.slice(0, 18)}…` : full, { "text-anchor": "middle" });
        pointTitle(node, full);
    }

    function renderBarChart(spec) {
        const labels = Array.isArray(spec.labels) ? spec.labels : [];
        const values = chartValues(spec);
        const { frame, svg } = plotFrame(spec, labels.length);
        const unit = spec.metadata && spec.metadata.unit;
        const max = axisMaximum(spec, values);
        renderAxes(svg, frame, max, unit);
        labels.forEach((label, index) => {
            const value = values[index];
            const slot = frame.plotWidth / labels.length;
            const x = frame.left + slot * (index + .5);
            const yBase = frame.top + frame.plotHeight;
            xLabel(svg, x, yBase + 22, label);
            if (!isNumber(value) || value < 0) {
                svgText(svg, x, yBase - 11, "N/A", { "text-anchor": "middle" });
                return;
            }
            const barHeight = Math.min(frame.plotHeight, value / max * frame.plotHeight);
            const bar = svgElement("rect", {
                x: x - Math.min(slot * .48, 25), y: yBase - barHeight,
                width: Math.min(slot * .96, 50), height: Math.max(barHeight, value === 0 ? 2 : 0),
                rx: 4, fill: PALETTE[index % PALETTE.length]
            });
            pointTitle(bar, pointDescription(spec, index, label, value, unit));
            svg.appendChild(bar);
            svgText(svg, x, Math.max(frame.top + 10, yBase - barHeight - 8), chartNumber(value, unit), { "text-anchor": "middle" });
        });
        return svg;
    }

    function renderLineChart(spec) {
        const labels = Array.isArray(spec.labels) ? spec.labels : [];
        const values = chartValues(spec);
        const { frame, svg } = plotFrame(spec, labels.length);
        const unit = spec.metadata && spec.metadata.unit;
        const max = axisMaximum(spec, values);
        renderAxes(svg, frame, max, unit);
        let segment = [];
        const flush = () => {
            if (segment.length > 1) svg.appendChild(svgElement("polyline", {
                points: segment.join(" "), fill: "none", stroke: "#ba8cff", "stroke-width": 3,
                "stroke-linecap": "round", "stroke-linejoin": "round"
            }));
            segment = [];
        };
        labels.forEach((label, index) => {
            const value = values[index];
            const x = frame.left + frame.plotWidth * (labels.length === 1 ? .5 : index / (labels.length - 1));
            xLabel(svg, x, frame.top + frame.plotHeight + 22, label);
            if (!isNumber(value) || value < 0) {
                flush();
                svgText(svg, x, frame.top + frame.plotHeight - 11, "N/A", { "text-anchor": "middle" });
                return;
            }
            const y = frame.top + frame.plotHeight * (1 - Math.min(1, value / max));
            segment.push(`${x},${y}`);
        });
        flush();
        labels.forEach((label, index) => {
            const value = values[index];
            if (!isNumber(value) || value < 0) return;
            const x = frame.left + frame.plotWidth * (labels.length === 1 ? .5 : index / (labels.length - 1));
            const y = frame.top + frame.plotHeight * (1 - Math.min(1, value / max));
            const circle = svgElement("circle", { cx: x, cy: y, r: 5, fill: "#e8d7ff", stroke: "#7c3aed", "stroke-width": 2 });
            pointTitle(circle, pointDescription(spec, index, label, value, unit));
            svg.appendChild(circle);
            svgText(svg, x, Math.max(13, y - 11), chartNumber(value, unit), { "text-anchor": "middle" });
        });
        return svg;
    }

    function renderPieChart(spec) {
        const labels = Array.isArray(spec.labels) ? spec.labels : [];
        const values = chartValues(spec);
        const total = values.reduce((sum, value) => sum + (isNumber(value) && value > 0 ? value : 0), 0);
        const svg = svgElement("svg", { viewBox: "0 0 400 250", role: "img", "aria-label": spec.title || "Analytics chart" });
        const centerX = 200, centerY = 124, radius = 88;
        let start = -Math.PI / 2;
        labels.forEach((label, index) => {
            const value = values[index];
            if (!isNumber(value) || value <= 0) return;
            const sweep = value / total * Math.PI * 2;
            let slice;
            if (value === total) {
                slice = svgElement("circle", { cx: centerX, cy: centerY, r: radius, fill: PALETTE[index % PALETTE.length] });
            } else {
                const end = start + sweep;
                const x1 = centerX + radius * Math.cos(start), y1 = centerY + radius * Math.sin(start);
                const x2 = centerX + radius * Math.cos(end), y2 = centerY + radius * Math.sin(end);
                slice = svgElement("path", {
                    d: `M ${centerX} ${centerY} L ${x1} ${y1} A ${radius} ${radius} 0 ${sweep > Math.PI ? 1 : 0} 1 ${x2} ${y2} Z`,
                    fill: PALETTE[index % PALETTE.length], stroke: "#211434", "stroke-width": 2
                });
            }
            const percentages = spec.metadata && spec.metadata.percentages;
            const percentage = Array.isArray(percentages) && isNumber(percentages[index])
                ? ` (${displayValue(percentages[index], "percent")})` : "";
            pointTitle(slice, `${label}: ${value}${percentage}`);
            svg.appendChild(slice);
            start += sweep;
        });
        svg.appendChild(svgElement("circle", { cx: centerX, cy: centerY, r: 49, fill: "#15102c" }));
        const reportedTotal = spec.metadata && spec.metadata.total_count;
        svgText(svg, centerX, centerY + 6, displayValue(isNumber(reportedTotal) && reportedTotal >= 0 ? reportedTotal : total, "number"), { "text-anchor": "middle", style: "font-size:22px;font-weight:bold;fill:#fff" });
        return svg;
    }

    function renderLegend(spec) {
        const legend = document.createElement("div");
        legend.className = "chart-legend";
        const values = chartValues(spec);
        const unit = spec.metadata && spec.metadata.unit;
        (spec.labels || []).forEach((label, index) => {
            const item = document.createElement("span");
            item.className = "legend-item";
            const swatch = document.createElement("span");
            swatch.className = "legend-swatch";
            swatch.style.backgroundColor = PALETTE[index % PALETTE.length];
            item.append(swatch, document.createTextNode(`${label}: ${chartNumber(values[index], unit)}`));
            legend.appendChild(item);
        });
        return legend;
    }

    function renderChart(spec) {
        const card = document.createElement("article");
        card.className = "chart-card";
        const heading = document.createElement("h3");
        heading.textContent = spec && spec.title ? spec.title : "Chart unavailable";
        card.appendChild(heading);
        const subtitle = document.createElement("p");
        subtitle.className = "chart-subtitle";
        subtitle.textContent = spec && spec.datasets && spec.datasets[0] && spec.datasets[0].label || "";
        card.appendChild(subtitle);
        const plot = document.createElement("div");
        plot.className = "chart-plot";
        if (!chartHasData(spec)) {
            const empty = document.createElement("div");
            empty.className = "chart-empty";
            empty.textContent = "No data available";
            plot.appendChild(empty);
        } else {
            const renderer = { bar: renderBarChart, line: renderLineChart, pie: renderPieChart }[spec.type];
            if (renderer) plot.appendChild(renderer(spec));
            else {
                const unsupported = document.createElement("div");
                unsupported.className = "chart-empty";
                unsupported.textContent = "Chart unavailable";
                plot.appendChild(unsupported);
            }
            if (spec.type === "pie") plot.appendChild(renderLegend(spec));
        }
        card.appendChild(plot);
        return card;
    }

    function renderTable(spec) {
        const card = document.createElement("article");
        card.className = "table-card";
        const heading = document.createElement("h3");
        heading.textContent = spec && spec.title ? spec.title : "Table unavailable";
        card.appendChild(heading);
        const columns = spec && Array.isArray(spec.columns) ? spec.columns : [];
        const rows = spec && Array.isArray(spec.rows) ? spec.rows : [];
        if (!columns.length) {
            const empty = document.createElement("div");
            empty.className = "table-empty";
            empty.textContent = "No data available";
            card.appendChild(empty);
            return card;
        }
        const wrap = document.createElement("div");
        wrap.className = "table-wrap";
        wrap.tabIndex = 0;
        wrap.setAttribute("aria-label", `Scrollable ${heading.textContent} table`);
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const header = document.createElement("tr");
        columns.forEach(column => {
            const th = document.createElement("th");
            th.scope = "col";
            th.textContent = column.label || column.key || "";
            header.appendChild(th);
        });
        thead.appendChild(header);
        table.appendChild(thead);
        const tbody = document.createElement("tbody");
        if (!rows.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = columns.length;
            cell.className = "na-value";
            cell.textContent = "No data available";
            row.appendChild(cell);
            tbody.appendChild(row);
        } else {
            rows.forEach(source => {
                const row = document.createElement("tr");
                columns.forEach(column => {
                    const cell = document.createElement("td");
                    const value = source && source[column.key];
                    cell.textContent = value === null || value === undefined || value === "" ? "N/A" : String(value);
                    if (cell.textContent === "N/A") cell.className = "na-value";
                    row.appendChild(cell);
                });
                tbody.appendChild(row);
            });
        }
        table.appendChild(tbody);
        wrap.appendChild(table);
        card.appendChild(wrap);
        if (isNumber(spec.valid_response_count)) {
            const note = document.createElement("p");
            note.className = "chart-subtitle";
            note.style.marginTop = "10px";
            note.textContent = `${spec.valid_response_count} timed replies`;
            card.appendChild(note);
        }
        return card;
    }

    if (typeof module !== "undefined" && module.exports) {
        module.exports = {
            displayValue, sessionTimestamp, chooseSession, chartValues, chartHasData, axisMaximum,
            renderTable, renderBarChart, renderLineChart, renderPieChart, finalizationPresentation
        };
    }
    if (typeof document === "undefined") return;

    const username = localStorage.getItem("username");
    const userId = localStorage.getItem("user_id");
    if (!username || !userId) {
        window.location.replace("/login.html");
        return;
    }

    const nodes = {
        selector: document.getElementById("analyticsSession"),
        refresh: document.getElementById("analyticsRefresh"),
        message: document.getElementById("analyticsMessage"),
        context: document.getElementById("sessionContext"),
        overview: document.getElementById("overviewCards"),
        charts: document.getElementById("analyticsCharts"),
        tables: document.getElementById("analyticsTables"),
        finalization: document.getElementById("finalizationStatus")
    };
    let selectedSessionId = null;
    let sessions = [];
    let requestVersion = 0;
    let pendingRequest = null;

    function showMessage(text, kind) {
        nodes.message.textContent = text;
        nodes.message.dataset.kind = kind || "info";
        nodes.message.hidden = !text;
    }

    function renderOverview(overview) {
        nodes.overview.replaceChildren();
        OVERVIEW.forEach(item => {
            const card = document.createElement("article");
            card.className = "overview-card";
            const label = document.createElement("p");
            label.className = "card-label";
            label.textContent = item.label;
            const value = document.createElement("p");
            value.className = "card-value";
            value.textContent = displayValue(overview && overview[item.key], item.kind);
            if (value.textContent === "N/A") value.classList.add("muted");
            card.append(label, value);
            nodes.overview.appendChild(card);
        });
    }

    function placeholder(container, message) {
        const node = document.createElement("div");
        node.className = "chart-empty";
        node.textContent = message;
        container.replaceChildren(node);
    }

    function clearDashboard(message) {
        renderOverview(null);
        placeholder(nodes.charts, message);
        placeholder(nodes.tables, message);
        nodes.context.textContent = "Choose a session to see its analytics.";
        nodes.finalization.hidden = true;
        nodes.finalization.replaceChildren();
    }

    function formatSessionDate(value) {
        const time = sessionTimestamp(value);
        return Number.isFinite(time) ? new Date(time).toLocaleString() : "No updates yet";
    }

    function renderSessionSelector() {
        nodes.selector.replaceChildren();
        if (!sessions.length) {
            const option = document.createElement("option");
            option.textContent = "No sessions available";
            nodes.selector.appendChild(option);
            nodes.selector.disabled = true;
            return;
        }
        sessions.forEach(session => {
            const option = document.createElement("option");
            option.value = session.session_id;
            const status = session.status === "active" ? "Active" : "Ended";
            option.textContent = `${session.title || "New chat"} · ${status} · ${formatSessionDate(session.updated_at)}`;
            nodes.selector.appendChild(option);
        });
        nodes.selector.disabled = false;
        nodes.selector.value = selectedSessionId;
    }

    function requestError(response) {
        if (response.status === 403) return "This session belongs to another user. Choose an owned session and refresh.";
        if (response.status === 404) return "This session no longer exists. Refresh the session list.";
        if (response.status === 503) return "The database is unavailable. Try again after it reconnects.";
        return "Analytics could not be loaded. Please try again.";
    }

    async function readJson(response) {
        try { return await response.json(); }
        catch (_) { throw new Error("The server returned an invalid response."); }
    }

    function beginLoad() {
        requestVersion += 1;
        if (pendingRequest) pendingRequest.abort();
        pendingRequest = new AbortController();
        return { version: requestVersion, signal: pendingRequest.signal };
    }

    function renderDashboard(data) {
        renderOverview(data.overview);
        nodes.charts.replaceChildren();
        CHART_ORDER.forEach(key => nodes.charts.appendChild(renderChart(data.charts && data.charts[key])));
        nodes.tables.replaceChildren();
        TABLE_ORDER.forEach(key => nodes.tables.appendChild(renderTable(data.tables && data.tables[key])));
        const session = sessions.find(item => item.session_id === selectedSessionId);
        const finalization = finalizationPresentation(data.finalization, session);
        const badge = document.createElement("span");
        badge.className = "finalization-badge";
        if (finalization.finalized) badge.classList.add("finalized");
        badge.textContent = finalization.label;
        nodes.finalization.replaceChildren(badge);
        if (finalization.date) {
            const date = document.createElement("span");
            date.textContent = finalization.date;
            nodes.finalization.appendChild(date);
        }
        nodes.finalization.hidden = false;
        const count = data.overview && data.overview.total_interactions;
        nodes.context.textContent = `${session && session.title || "Session"} · ${session && session.status || "Unknown status"} · ${displayValue(count, "number")} interactions`;
        if (count === 0) showMessage("This session has no interactions yet. Charts and tables are ready for future replies.");
        else showMessage("");
    }

    async function loadDashboard(id, request) {
        selectedSessionId = id;
        nodes.selector.value = id;
        clearDashboard("Loading analytics…");
        showMessage("Loading session analytics…");
        try {
            const url = `/analytics/session/${encodeURIComponent(id)}/dashboard?user_id=${encodeURIComponent(userId)}`;
            const response = await fetch(url, { signal: request.signal });
            if (!response.ok) throw new Error(requestError(response));
            const data = await readJson(response);
            if (request.version !== requestVersion) return;
            if (!data || !data.success || !data.overview || !data.charts || !data.tables) {
                throw new Error("The dashboard response is incomplete. Please try again.");
            }
            renderDashboard(data);
        } catch (error) {
            if (request.version !== requestVersion || error.name === "AbortError") return;
            clearDashboard("Analytics unavailable");
            showMessage(error instanceof TypeError ? "Network error. Check the server and try again." : error.message || "Analytics could not be loaded.", "error");
        }
    }

    async function refreshSessions() {
        const request = beginLoad();
        clearDashboard("Loading sessions…");
        showMessage("Loading your sessions…");
        nodes.selector.disabled = true;
        nodes.refresh.disabled = true;
        try {
            const response = await fetch(`/sessions/user/${encodeURIComponent(userId)}`, { signal: request.signal });
            if (!response.ok) throw new Error(requestError(response));
            const data = await readJson(response);
            if (request.version !== requestVersion) return;
            if (!data || !data.success || !Array.isArray(data.sessions)) throw new Error("The session list is unavailable.");
            sessions = data.sessions;
            selectedSessionId = chooseSession(sessions, localStorage.getItem(`trace_session_${userId}`), selectedSessionId);
            renderSessionSelector();
            if (!selectedSessionId) {
                clearDashboard("No sessions yet");
                showMessage("No chat sessions yet. Start a chat to create analytics.");
                return;
            }
            await loadDashboard(selectedSessionId, request);
        } catch (error) {
            if (request.version !== requestVersion || error.name === "AbortError") return;
            sessions = [];
            selectedSessionId = null;
            renderSessionSelector();
            clearDashboard("Analytics unavailable");
            showMessage(error instanceof TypeError ? "Network error. Check the server and try again." : error.message || "Sessions could not be loaded.", "error");
        } finally {
            if (request.version === requestVersion) nodes.refresh.disabled = false;
        }
    }

    nodes.selector.addEventListener("change", () => {
        if (!sessions.some(session => session.session_id === nodes.selector.value)) return;
        const request = beginLoad();
        nodes.refresh.disabled = false;
        loadDashboard(nodes.selector.value, request);
    });
    nodes.refresh.addEventListener("click", refreshSessions);
    renderOverview(null);
    refreshSessions();
}());
