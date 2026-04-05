<div align="center">

# Security Policy

[![Security: Privacy by Design](https://img.shields.io/badge/security-privacy%20by%20design-blue?style=flat-square&logo=shield&logoColor=white)](SECURITY.md)

</div>

---

## Privacy by Design

LumenAI is an observability layer, not a logging layer. This distinction is intentional and fundamental to the architecture.

### What LumenAI NEVER touches

- **Prompt content** — the text you send to an LLM is never read, stored, or transmitted by LumenAI.
- **Response text** — LLM completions, generated code, summaries, and answers are never intercepted.
- **Personally Identifiable Information (PII)** — names, emails, addresses, and any user-provided content pass through without inspection.
- **API keys and credentials** — LumenAI reads OTel span attributes, none of which contain authentication material when using standard instrumentation.
- **Tool call arguments** — the inputs and outputs of function/tool calls are not captured.
- **Raw request or response bodies** — HTTP bodies, gRPC payloads, and message contents are not accessed.

### What LumenAI DOES track

- **Token counts** — `input_tokens`, `output_tokens`, `cache_read_tokens` as integers.
- **Model name** — e.g. `"claude-sonnet-4-6"`, `"gpt-4o"`. The string identifier only.
- **Computed cost** — a USD float derived from token counts and the pricing table.
- **Tenant ID** — the business identifier you configure via `set_tenant_id()` or your middleware. This is your own string (e.g. an organization slug, UUID, or plan identifier).
- **Span metadata** — trace ID, span ID, span name, duration, and error status from the OTel context.
- **Session and agent IDs** — optional identifiers you explicitly set via span attributes.

**In summary: LumenAI processes the economics and metadata of AI calls, not the semantics.**

---

## Data Flow

The following diagram shows exactly what data moves through LumenAI and where it comes from:

```
Your Application
       │
       │  LLM call (prompt content NOT touched by LumenAI)
       ▼
┌─────────────────────────────────────────────────────────────┐
│  OTel Span (metadata only)                                  │
│  ─────────────────────────────────────────────────────────  │
│  gen_ai.request.model     = "claude-sonnet-4-6"             │
│  gen_ai.usage.input_tokens  = 1024                          │
│  gen_ai.usage.output_tokens = 256                           │
│  span.name                = "anthropic.messages.create"     │
│  span.duration            = 1842 ms                         │
│  span.status              = OK                              │
│                                                             │
│  ← prompt text: NOT HERE. Never in OTel span attributes.   │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  LumenAI Processor Chain                                    │
│  ─────────────────────────────────────────────────────────  │
│  TenantSpanProcessor  → reads ContextVar → tenant_id        │
│  CostComputingSpanProcessor → reads token counts → $0.0038  │
│  EventNormalizerProcessor → assembles event dict            │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  LumenAI Event (metadata only — no content)                 │
│  ─────────────────────────────────────────────────────────  │
│  tenant_id:   "client-abc"                                  │
│  model:       "claude-sonnet-4-6"                           │
│  cost_usd:    0.00384000                                     │
│  tokens_in:   1024                                          │
│  tokens_out:  256                                           │
│  duration_ms: 1842                                          │
│  is_error:    false                                         │
│  event_type:  "llm_call_completed"                          │
│                                                             │
│  ← no prompt. no response. no PII.                         │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
Redis Streams: LumenAI:events:client-abc
(only the event dict above — stream is tenant-namespaced)
```

---

## Supported Versions

| Version | Supported |
|---|---|
| Latest alpha (main branch) | Yes — security fixes applied here |
| Any pinned pre-release tag | No — please update to latest |
| PyPI release (v0.1.0+) | Yes — receives security patches as patch releases |

LumenAI is currently in alpha. The latest commit on the `main` branch and the latest PyPI release are both actively supported. We recommend pinning to the latest release and updating promptly when new versions are published.

---

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.** Public disclosure before a fix is available puts all users at risk.

### Step 1: Open a Private Security Advisory

Use GitHub's built-in private reporting mechanism:

[Open a GitHub Security Advisory](https://github.com/skarL007/-lumen-ai-sdk/security/advisories/new)

This creates a private thread visible only to you and the maintainer. No public exposure until a fix is ready.

### Step 2: Include the Following Information

To help us reproduce and fix the issue quickly, please include:

- **Description** — what is the vulnerability? What is the impact?
- **Affected component** — which file, class, or function is involved?
- **Steps to reproduce** — minimal code that demonstrates the issue
- **Python version** — output of `python --version`
- **Package version** — output of `pip show lumen-ai-core`
- **Suggested fix** — if you have one (optional but very welcome)
- **CVE reference** — if this relates to a known CVE in a dependency

### Step 3: Response Timeline

| Milestone | Target |
|---|---|
| Acknowledgment of report | Within 48 hours |
| Initial assessment and severity classification | Within 5 days |
| Fix estimate provided | Within 7 days |
| Fix released (patch or new version) | Depends on severity — critical issues within 14 days |
| Public disclosure (coordinated) | After fix is available, agreed with reporter |

We follow [coordinated vulnerability disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). You will be credited in the release notes unless you prefer to remain anonymous.

---

## Our Security Commitments

1. **No prompt logging.** LumenAI processors only read `gen_ai.usage.*` attributes (token counts) and `gen_ai.request.model` (a string). The content of `gen_ai.system`, `gen_ai.prompt`, and `gen_ai.completion` attributes is never read or stored by LumenAI, even if present in the span.

2. **No PII collection.** Tenant IDs are business identifiers that you define and control (e.g. an org slug or UUID). LumenAI does not attempt to infer or collect user-level identity.

3. **No cross-tenant data leakage by design.** Tenant isolation is enforced at the ContextVar level. Python `ContextVar` objects provide per-coroutine isolation — one async request cannot read the ContextVar set by another. The `TenantSpanProcessor` reads the ContextVar value on `on_start()` and stores it in a side-dict keyed by `trace_id:span_id`. A span from Tenant A cannot be re-attributed to Tenant B.

4. **No raw content in the event dict.** The `LumenAIEvent` schema (see README) contains only numeric metrics, string identifiers, and boolean flags. There is no field that would contain prompt text or LLM output.

5. **Redis stream namespacing.** Events are written to streams keyed as `LumenAI:events:{tenant_id}`. Consumers reading `LumenAI:events:client-abc` cannot access `LumenAI:events:client-xyz` — Redis access control is the only barrier, and we recommend standard Redis ACLs to enforce this in production.

6. **Processor exceptions are caught and logged, never re-raised.** A security-sensitive exception (e.g. a pricing provider exposing a secrets store error) will be logged at `WARNING` level with `exc_info=True` but will not propagate to the application. This prevents internal infrastructure details from leaking into HTTP responses.

7. **No network calls from core processors.** `TenantSpanProcessor`, `CostComputingSpanProcessor`, and `EventNormalizerProcessor` make no outbound network calls. Only the `RedisExporter` and `CommunityPricingProvider` (opt-in) make network calls, and both are injected by you at `LumenAI.init()` time.

---

## Dependency Security

LumenAI core has a minimal, intentionally small dependency footprint:

| Dependency | Purpose | Why minimal attack surface |
|---|---|---|
| `opentelemetry-api >= 1.30.0` | OTel span interface | Maintained by the CNCF OpenTelemetry project with a formal security policy |
| `opentelemetry-sdk >= 1.30.0` | `TracerProvider`, `SpanProcessor` base classes | Same project as above |
| `redis >= 5.0.0` | Redis Streams export | Only used in `RedisExporter`, which is optional and opt-in |

Optional packages (`lumen-ai-celery`, `lumen-ai-openlit`) add `celery >= 5.0` and `openlit >= 1.0` respectively. These are only imported when the corresponding instrumentor is instantiated.

We do not pin transitive dependencies. We recommend users apply their own dependency pinning strategy (e.g. `pip-compile`, `poetry.lock`, `uv.lock`) appropriate to their security posture.

If you discover a vulnerability in one of these dependencies that affects LumenAI's security properties, please report it via the private advisory process above. We will coordinate with the upstream project and release an updated `pyproject.toml` dependency bound as appropriate.

---

## Production Hardening Checklist

<details>
<summary>Recommended steps before deploying LumenAI in production</summary>

- [ ] **Use Redis ACLs** to restrict which services can read `LumenAI:events:*` streams. Consumers should only access their own tenant's stream.
- [ ] **Set `maxlen` on Redis Streams** (default is already `10000` per stream in `RedisExporter`). Adjust based on your event volume and retention needs.
- [ ] **Do not log `tenant_id` values in plain-text application logs** if they correspond to customer-identifiable information. Use opaque UUIDs as tenant IDs where possible.
- [ ] **Validate `tenant_id` in your middleware** before passing it to `set_tenant_id()`. Reject empty strings, unexpected characters, or IDs that do not match your known tenant list.
- [ ] **Rotate Redis credentials** independently of LumenAI SDK updates.
- [ ] **Use TLS for Redis connections** in production: `redis_url="rediss://..."` (note the `s`).
- [ ] **Pin your LumenAI version** in `requirements.txt` or `pyproject.toml` and review the changelog before upgrading.

</details>

---

*For questions about LumenAI's security model that are not vulnerability reports, feel free to reach out on [Discord (skar1v9)](https://discord.com/users/skar1v9) or open a regular [GitHub Issue](https://github.com/skarL007/-lumen-ai-sdk/issues).*
