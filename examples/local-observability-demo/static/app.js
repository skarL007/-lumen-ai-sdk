// LumenAI demo dashboard. Live mode talks to the FastAPI backend in main.py;
// without a backend (a static host), it replays static/recorded-events.json,
// a real run of the README scenario recorded by record.py. On a serverless
// host (per-request store), each call returns the events it exported and this
// page keeps them, so visitors never share data.

const CONTENT_KEYS = ["prompt", "completion", "input.value", "output.value", "messages"];
const KIND = {
  LLM_CALL_COMPLETED: "LLM",
  LLM_CALL_FAILED: "LLM failed",
  EMBEDDING_COMPLETED: "Embedding",
  TOOL_CALL_COMPLETED: "Tool",
  AGENT_COMPLETED: "Agent",
};

const $ = (selector) => document.querySelector(selector);
const state = { mode: "connecting", perRequest: false, events: [], tenant: null, open: new Set(), busy: false };

const theme = new URLSearchParams(location.search).get("theme");
if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;

const usd = (value) => `$${Number(value || 0).toFixed(6)}`;
const int = (value) => Number(value || 0).toLocaleString("en-US");
const count = (n, one, many = `${one}s`) => `${int(n)} ${n === 1 ? one : many}`;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

function announce(message) {
  $("#status").textContent = message;
}

async function getJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${options?.method || "GET"} ${url} → ${response.status}`);
  return response.json();
}

/* ---------- aggregation (the same rules as the README report) ---------- */
function summarize(events) {
  const tenants = new Map();
  const total = { cost: 0, events: 0, llm: 0, errors: 0, tin: 0, tout: 0, cached: 0 };
  for (const event of events) {
    const row = tenants.get(event.tenant_id) || { tenant: event.tenant_id, cost: 0, events: 0, llm: 0, errors: 0, tin: 0, tout: 0, cached: 0 };
    const isLlm = String(event.event_type || "").startsWith("LLM_CALL");
    for (const target of [row, total]) {
      target.cost += Number(event.cost_usd || 0);
      target.events += 1;
      target.llm += isLlm ? 1 : 0;
      target.errors += event.is_error ? 1 : 0;
      target.tin += Number(event.tokens_in || 0);
      target.tout += Number(event.tokens_out || 0);
      target.cached += Number(event.cache_read_tokens || 0);
    }
    tenants.set(event.tenant_id, row);
  }
  const rows = [...tenants.values()].sort((a, b) => b.cost - a.cost || a.tenant.localeCompare(b.tenant));
  return { rows, total };
}

function checks(events) {
  const items = [];
  const crossing = events.find((event) => event.message === "support.async_followup");
  if (crossing) {
    const ok = crossing.tenant_id === "acme-health";
    items.push({
      status: ok ? "pass" : "fail",
      title: "Tenant isolation",
      text: `A span started in acme-health and ended while globex-legal was active. It was billed to ${crossing.tenant_id}.`,
    });
  } else {
    items.push({ status: "info", title: "Tenant isolation", text: "Run the scenario: one span starts in acme-health and ends while globex-legal is active." });
  }

  const leaked = events.reduce((count, event) => count + CONTENT_KEYS.filter((key) => key in event).length, 0);
  items.push({
    status: events.length === 0 ? "info" : leaked === 0 ? "pass" : "fail",
    title: "Privacy",
    text: `${count(events.length, "event")} exported, ${leaked} prompt or response fields.`,
  });

  const failed = events.find((event) => event.is_error && Number(event.cost_usd) > 0);
  items.push(failed
    ? { status: "pass", title: "Failed calls still cost", text: `${failed.message} failed and was billed ${usd(failed.cost_usd)} for the ${int(failed.tokens_in)} input tokens it consumed.` }
    : { status: "info", title: "Failed calls still cost", text: "No failed call with tokens yet." });

  const cached = events.find((event) => Number(event.cache_read_tokens) > 0);
  items.push(cached
    ? { status: "info", title: "Prompt cache", text: `${cached.message}: ${int(cached.cache_read_tokens)} cache-read tokens on ${cached.model}, billed at the cache rate. Total ${usd(cached.cost_usd)}.` }
    : { status: "info", title: "Prompt cache", text: "No cache reads yet." });
  return items;
}

/* ---------- rendering ---------- */
function render() {
  const { rows, total } = summarize(state.events);
  $("#kpi-cost").textContent = usd(total.cost);
  $("#kpi-tenants").textContent = int(rows.length);
  $("#kpi-events").textContent = `${int(total.events)} · ${int(total.llm)}`;
  $("#kpi-tokens").textContent = `${int(total.tin)} · ${int(total.tout)} · ${int(total.cached)}`;
  $("#kpi-errors").textContent = int(total.errors);

  const privacy = $("#privacy-chip");
  const leaked = checks(state.events)[1];
  privacy.hidden = state.events.length === 0;
  privacy.className = `chip ${leaked.status === "pass" ? "chip-ok" : "chip-err"}`;
  privacy.textContent = leaked.status === "pass" ? "0 prompt fields exported" : "prompt fields found";

  const list = $("#tenant-list");
  list.replaceChildren();
  const max = Math.max(...rows.map((row) => row.cost), 0);
  for (const row of rows) {
    const share = total.cost > 0 ? (row.cost / total.cost) * 100 : 0;
    const width = max > 0 ? Math.max((row.cost / max) * 100, 0.8) : 0.8;
    list.append(el("li", { class: "tenant-row" },
      el("span", { class: "tenant-name", text: row.tenant }),
      el("span", { class: "tenant-cost" }, usd(row.cost), el("small", { text: `${share.toFixed(1)}%` })),
      el("span", { class: "bar", "aria-hidden": "true" }, el("i", { style: `width:${width.toFixed(2)}%` })),
      el("span", { class: "tenant-meta", text: `${count(row.events, "event")} · ${count(row.llm, "LLM call")} · ${count(row.errors, "error")} · ${int(row.tin)} in / ${int(row.tout)} out${row.cached ? ` / ${int(row.cached)} cached` : ""}` }),
    ));
  }
  $("#tenants-empty").hidden = rows.length > 0;

  const checkList = $("#checks");
  checkList.replaceChildren();
  for (const item of checks(state.events)) {
    const mark = item.status === "pass" ? "✓" : item.status === "fail" ? "✕" : "i";
    checkList.append(el("li", { class: item.status },
      el("span", { class: "tick", "aria-hidden": "true", text: mark }),
      el("b", { text: `${item.title}${item.status === "pass" ? " · verified" : item.status === "fail" ? " · failed" : ""}` }),
      el("p", { text: item.text }),
    ));
  }

  if (state.tenant && !rows.some((row) => row.tenant === state.tenant)) state.tenant = null;
  const filter = $("#tenant-filter");
  filter.replaceChildren();
  if (rows.length > 1) {
    for (const name of [null, ...rows.map((row) => row.tenant)]) {
      const button = el("button", { class: "filter", type: "button", "aria-pressed": String(state.tenant === name), text: name || "All tenants" });
      button.addEventListener("click", () => { state.tenant = name; render(); });
      filter.append(button);
    }
  }

  const body = $("#events-body");
  body.replaceChildren();
  state.events.forEach((event, index) => {
    if (state.tenant && event.tenant_id !== state.tenant) return;
    const id = event.id || String(index);
    const open = state.open.has(id);
    const kind = KIND[event.event_type] || String(event.event_type || "event").toLowerCase();
    const toggle = el("button", { class: "raw-btn", type: "button", "aria-expanded": String(open), "aria-label": `Show the raw event for ${event.message || "this span"}`, text: "JSON" });
    toggle.addEventListener("click", () => { open ? state.open.delete(id) : state.open.add(id); render(); });
    const cached = Number(event.cache_read_tokens) ? int(event.cache_read_tokens) : "–";
    body.append(el("tr", { class: event.is_error ? "is-error" : "" },
      el("td", { class: "idx", text: String(index + 1) }),
      el("td", { class: "mono", text: event.tenant_id }),
      el("td", { class: "mono", text: event.message || "" }),
      el("td", {}, el("span", { class: `kind${event.is_error ? " kind-error" : ""}`, text: kind })),
      el("td", { class: "mono", text: event.model || event.tool_name || "–" }),
      el("td", { class: "num", text: `${int(event.tokens_in)} · ${int(event.tokens_out)} · ${cached}` }),
      el("td", { class: "num", text: usd(event.cost_usd) }),
      el("td", {}, toggle),
    ));
    if (open) body.append(el("tr", { class: "raw" }, el("td", { colspan: "8" }, el("pre", { text: JSON.stringify(event, null, 2) }))));
  });
  $("#events-empty").hidden = state.events.length > 0;
}

function setMode(mode, detail) {
  state.mode = mode;
  const chip = $("#mode-chip");
  const live = mode === "jsonl" || mode === "redis" || mode === "memory";
  chip.className = `chip ${live ? "chip-live" : mode === "error" ? "chip-err" : ""}`;
  chip.textContent = { jsonl: "Live · JSONL exporter", redis: "Live · Redis Streams", memory: "Live · per request", replay: "Recorded run", error: "No backend" }[mode] || "Connecting…";
  $("#replay-banner").hidden = mode !== "replay";
  $("#live-actions").hidden = !live;
  $("#custom-panel").hidden = !live;
  if (detail) $("#store-line").textContent = detail;
}

/* ---------- data ---------- */
async function loadEvents() {
  const data = await getJSON("api/events?limit=2000");
  state.events = data.events || [];
  render();
}

// keep(result) applies a per-request response; stores that persist are re-read instead.
async function act(button, work, done, keep) {
  if (state.busy) return;
  state.busy = true;
  if (button) button.disabled = true;
  try {
    const result = await work();
    if (state.perRequest) {
      keep(result);
      render();
    } else {
      await loadEvents();
    }
    announce(done);
  } catch (error) {
    announce(error.message);
    setMode("error", `Request failed: ${error.message}`);
  } finally {
    state.busy = false;
    if (button) button.disabled = false;
  }
}

async function loadModels() {
  const data = await getJSON("api/models");
  const select = $("#model-select");
  select.replaceChildren(...data.models.map((model) => el("option", { value: model.id, text: model.id })));
  select.value = "gpt-4o-mini";
}

async function start() {
  try {
    const health = await getJSON("api/health");
    state.perRequest = Boolean(health.per_request);
    if (state.perRequest) {
      setMode(health.exporter, "Each request runs LumenAI on the server and returns the events its exporter received. Nothing is stored there; your events stay in this tab.");
      await loadModels();
      await act(null, runScenario, "Scenario run on the server: 3 tenants, 11 events.", keepScenario);
    } else {
      setMode(health.exporter, `Events are read back from ${health.store} after LumenAI exports them.`);
      await Promise.all([loadModels(), loadEvents()]);
    }
    return;
  } catch {
    // no backend: fall through to the recorded run
  }
  try {
    const recording = await getJSON("static/recorded-events.json");
    state.events = recording.events || [];
    setMode("replay", `Recorded with ${recording.recorded_with} from ${recording.scenario}.`);
    render();
  } catch (error) {
    setMode("error", "No backend and no recording found. Start it with: uvicorn main:app --app-dir examples/local-observability-demo");
    render();
  }
}

const runScenario = () => getJSON("api/scenario", { method: "POST" });
const keepScenario = (result) => { state.events = result.produced || []; };

$("#run-scenario").addEventListener("click", (event) =>
  act(event.currentTarget, runScenario, "Scenario replayed: 3 tenants, 11 events.", keepScenario));
$("#reset").addEventListener("click", (event) =>
  act(event.currentTarget, () => getJSON("api/reset", { method: "POST" }), "Events cleared.", () => { state.events = []; }));
$("#simulate-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {
    tenant_id: String(form.get("tenant_id") || "").trim() || "acme",
    model: form.get("model"),
    input_tokens: Number(form.get("input_tokens") || 0),
    output_tokens: Number(form.get("output_tokens") || 0),
    cache_read_tokens: Number(form.get("cache_read_tokens") || 0),
    fail: form.get("fail") === "on",
  };
  const button = event.currentTarget.querySelector("button[type=submit]");
  act(button, () => getJSON("api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
    `Span sent for ${payload.tenant_id}.`, (result) => { state.events = [...state.events, ...(result.produced || [])]; });
});

start();
