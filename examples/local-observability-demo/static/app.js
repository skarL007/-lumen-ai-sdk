const tenantInput = document.querySelector("#tenant-input");
const modelInput = document.querySelector("#model-input");
const inputTokens = document.querySelector("#input-tokens");
const outputTokens = document.querySelector("#output-tokens");
const cacheTokens = document.querySelector("#cache-tokens");
const latencyMs = document.querySelector("#latency-ms");
const failInput = document.querySelector("#fail-input");
const simulateButton = document.querySelector("#simulate-button");
const scenarioButton = document.querySelector("#scenario-button");
const resetButton = document.querySelector("#reset-button");
const refreshButton = document.querySelector("#refresh-button");
const statusLine = document.querySelector("#status-line");
const streamName = document.querySelector("#stream-name");
const eventsList = document.querySelector("#events-list");
const metricCost = document.querySelector("#metric-cost");
const metricEvents = document.querySelector("#metric-events");
const metricTokens = document.querySelector("#metric-tokens");
const metricErrors = document.querySelector("#metric-errors");
const metricCache = document.querySelector("#metric-cache");
const chart = document.querySelector("#cost-chart");
const chartContext = chart.getContext("2d");

function tenantId() {
  return tenantInput.value.trim() || "acme";
}

function formatCost(value) {
  return `$${Number(value || 0).toFixed(6)}`;
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString("en-US");
}

function setStatus(message) {
  statusLine.textContent = message;
}

function setBusy(isBusy) {
  simulateButton.disabled = isBusy;
  scenarioButton.disabled = isBusy;
  resetButton.disabled = isBusy;
  refreshButton.disabled = isBusy;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortId(value) {
  const text = String(value || "");
  return text.length > 12 ? `${text.slice(0, 8)}...${text.slice(-4)}` : text;
}

async function checkedFetch(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`${url} failed: ${response.status}`);
  }
  return response.json();
}

async function runSimulation() {
  setBusy(true);
  setStatus("Creating span");

  const payload = {
    tenant_id: tenantId(),
    model: modelInput.value,
    input_tokens: Number(inputTokens.value || 0),
    output_tokens: Number(outputTokens.value || 0),
    cache_read_tokens: Number(cacheTokens.value || 0),
    latency_ms: Number(latencyMs.value || 0),
    fail: failInput.checked,
  };

  try {
    await checkedFetch("/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await refreshDashboard();
  } finally {
    setBusy(false);
  }
}

async function runScenario() {
  setBusy(true);
  setStatus("Running deterministic scenario");

  try {
    const data = await checkedFetch("/scenario", { method: "POST" });
    if (data.tenants && data.tenants.includes("acme")) {
      tenantInput.value = "acme";
    }
    await refreshDashboard();
    setStatus(`Scenario created ${data.events_created} events`);
  } finally {
    setBusy(false);
  }
}

async function resetTenant() {
  setBusy(true);
  const tenant = tenantId();
  setStatus(`Resetting ${tenant}`);

  try {
    await checkedFetch(`/events/${encodeURIComponent(tenant)}`, { method: "DELETE" });
    await refreshDashboard();
    setStatus(`Tenant ${tenant} reset`);
  } finally {
    setBusy(false);
  }
}

async function refreshStats() {
  const tenant = tenantId();
  const stats = await checkedFetch(`/stats/${encodeURIComponent(tenant)}`);

  streamName.textContent = stats.stream || `LumenAI:events:${tenant}`;
  metricCost.textContent = formatCost(stats.cost_usd);
  metricEvents.textContent = formatInteger(stats.events);
  metricTokens.textContent = formatInteger(stats.tokens);
  metricErrors.textContent = formatInteger(stats.errors);
  metricCache.textContent = formatInteger(stats.cache_read_tokens);
}

async function refreshEvents() {
  const tenant = tenantId();
  const data = await checkedFetch(`/events/${encodeURIComponent(tenant)}?limit=25`);
  renderEvents(data.events || []);
  streamName.textContent = data.stream || `LumenAI:events:${tenant}`;
}

async function refreshDashboard() {
  const tenant = tenantId();
  setStatus(`Loading ${tenant}`);
  await Promise.all([refreshStats(), refreshEvents()]);
  setStatus(`Tenant ${tenant}`);
}

function renderEvents(events) {
  if (events.length === 0) {
    eventsList.innerHTML = '<p class="empty">No events yet for this tenant.</p>';
    drawChart([]);
    return;
  }

  eventsList.innerHTML = events
    .map((event) => {
      const rowClass = event.is_error ? "event-row event-error" : "event-row";
      const tokens = `${formatInteger(event.tokens_in)} in / ${formatInteger(event.tokens_out)} out`;
      const cache = formatInteger(event.cache_read_tokens);
      const eventType = escapeHtml(event.event_type || "EVENT");
      const model = escapeHtml(event.model || "unknown model");
      const severity = escapeHtml(event.severity || "INFO");
      const trace_id = escapeHtml(event.trace_id || "");
      const span_id = escapeHtml(event.span_id || "");
      const json = escapeHtml(JSON.stringify(event, null, 2));

      return `
        <article class="${rowClass}">
          <div class="event-main">
            <div>
              <strong>${eventType}</strong>
              <small>${model} - ${tokens} - cache ${cache}</small>
            </div>
            <div class="event-cost">${formatCost(event.cost_usd)}</div>
          </div>
          <dl class="event-meta">
            <div><dt>severity</dt><dd>${severity}</dd></div>
            <div><dt>duration</dt><dd>${formatInteger(event.duration_ms)} ms</dd></div>
            <div><dt>trace_id</dt><dd title="${trace_id}">${shortId(trace_id)}</dd></div>
            <div><dt>span_id</dt><dd>${shortId(span_id)}</dd></div>
          </dl>
          <details>
            <summary>Normalized JSON</summary>
            <pre>${json}</pre>
          </details>
        </article>
      `;
    })
    .join("");

  drawChart(events.slice().reverse());
}

function drawChart(events) {
  const width = chart.width;
  const height = chart.height;
  const padding = 28;

  chartContext.clearRect(0, 0, width, height);
  chartContext.fillStyle = "#ffffff";
  chartContext.fillRect(0, 0, width, height);
  chartContext.strokeStyle = "#d8e0e4";
  chartContext.lineWidth = 1;

  for (let i = 0; i < 4; i += 1) {
    const y = padding + ((height - padding * 2) / 3) * i;
    chartContext.beginPath();
    chartContext.moveTo(padding, y);
    chartContext.lineTo(width - padding, y);
    chartContext.stroke();
  }

  if (events.length === 0) {
    chartContext.fillStyle = "#65737c";
    chartContext.font = "16px system-ui";
    chartContext.fillText("Run a span or scenario to populate the chart.", padding, height / 2);
    return;
  }

  const values = events.map((event) => Number(event.cost_usd || 0));
  const maxValue = Math.max(...values, 0.000001);
  const step = events.length > 1 ? (width - padding * 2) / (events.length - 1) : 0;

  chartContext.strokeStyle = "#2563eb";
  chartContext.lineWidth = 3;
  chartContext.beginPath();

  values.forEach((value, index) => {
    const x = padding + step * index;
    const y = height - padding - (value / maxValue) * (height - padding * 2);
    if (index === 0) {
      chartContext.moveTo(x, y);
    } else {
      chartContext.lineTo(x, y);
    }
  });

  chartContext.stroke();

  values.forEach((value, index) => {
    const x = padding + step * index;
    const y = height - padding - (value / maxValue) * (height - padding * 2);
    chartContext.fillStyle = "#0f766e";
    chartContext.beginPath();
    chartContext.arc(x, y, 4, 0, Math.PI * 2);
    chartContext.fill();
  });
}

simulateButton.addEventListener("click", () => {
  runSimulation().catch((error) => {
    setBusy(false);
    setStatus(error.message);
  });
});

scenarioButton.addEventListener("click", () => {
  runScenario().catch((error) => {
    setBusy(false);
    setStatus(error.message);
  });
});

resetButton.addEventListener("click", () => {
  resetTenant().catch((error) => {
    setBusy(false);
    setStatus(error.message);
  });
});

refreshButton.addEventListener("click", () => {
  refreshDashboard().catch((error) => setStatus(error.message));
});

tenantInput.addEventListener("change", () => {
  refreshDashboard().catch((error) => setStatus(error.message));
});

refreshDashboard().catch((error) => setStatus(error.message));
