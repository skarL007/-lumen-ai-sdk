const tenantInput = document.querySelector("#tenant-input");
const modelInput = document.querySelector("#model-input");
const inputTokens = document.querySelector("#input-tokens");
const outputTokens = document.querySelector("#output-tokens");
const failInput = document.querySelector("#fail-input");
const simulateButton = document.querySelector("#simulate-button");
const refreshButton = document.querySelector("#refresh-button");
const statusLine = document.querySelector("#status-line");
const eventsList = document.querySelector("#events-list");
const metricCost = document.querySelector("#metric-cost");
const metricEvents = document.querySelector("#metric-events");
const metricTokens = document.querySelector("#metric-tokens");
const metricErrors = document.querySelector("#metric-errors");
const chart = document.querySelector("#cost-chart");
const chartContext = chart.getContext("2d");

function tenantId() {
  return tenantInput.value.trim() || "acme";
}

function formatCost(value) {
  return `$${Number(value || 0).toFixed(6)}`;
}

function setStatus(message) {
  statusLine.textContent = message;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function runSimulation() {
  simulateButton.disabled = true;
  setStatus("Creating span");

  const payload = {
    tenant_id: tenantId(),
    model: modelInput.value,
    input_tokens: Number(inputTokens.value || 0),
    output_tokens: Number(outputTokens.value || 0),
    fail: failInput.checked,
  };

  const response = await fetch("/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Simulation failed: ${response.status}`);
  }

  await refreshEvents();
  simulateButton.disabled = false;
}

async function refreshEvents() {
  const tenant = tenantId();
  setStatus(`Loading ${tenant}`);

  const response = await fetch(`/events/${encodeURIComponent(tenant)}?limit=25`);
  if (!response.ok) {
    throw new Error(`Event fetch failed: ${response.status}`);
  }

  const data = await response.json();
  renderEvents(data.events || []);
  setStatus(`Tenant ${tenant}`);
}

function renderEvents(events) {
  const totalCost = events.reduce((sum, event) => sum + Number(event.cost_usd || 0), 0);
  const totalTokens = events.reduce(
    (sum, event) => sum + Number(event.tokens_in || 0) + Number(event.tokens_out || 0),
    0,
  );
  const errorCount = events.filter((event) => event.is_error).length;

  metricCost.textContent = formatCost(totalCost);
  metricEvents.textContent = String(events.length);
  metricTokens.textContent = String(totalTokens);
  metricErrors.textContent = String(errorCount);

  if (events.length === 0) {
    eventsList.innerHTML = '<p class="empty">No events yet for this tenant.</p>';
    drawChart([]);
    return;
  }

  eventsList.innerHTML = events
    .map((event) => {
      const rowClass = event.is_error ? "event-row event-error" : "event-row";
      const tokens = `${event.tokens_in || 0} in / ${event.tokens_out || 0} out`;
      const eventType = escapeHtml(event.event_type || "EVENT");
      const model = escapeHtml(event.model || "unknown model");
      return `
        <article class="${rowClass}">
          <div>
            <strong>${eventType}</strong>
            <small>${model} - ${tokens}</small>
          </div>
          <div class="event-cost">${formatCost(event.cost_usd)}</div>
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
    chartContext.fillText("Run a span to populate the chart.", padding, height / 2);
    return;
  }

  const values = events.map((event) => Number(event.cost_usd || 0));
  const maxValue = Math.max(...values, 0.000001);
  const step = events.length > 1 ? (width - padding * 2) / (events.length - 1) : 0;

  chartContext.strokeStyle = "#0f766e";
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
    simulateButton.disabled = false;
    setStatus(error.message);
  });
});

refreshButton.addEventListener("click", () => {
  refreshEvents().catch((error) => setStatus(error.message));
});

tenantInput.addEventListener("change", () => {
  refreshEvents().catch((error) => setStatus(error.message));
});

refreshEvents().catch((error) => setStatus(error.message));
