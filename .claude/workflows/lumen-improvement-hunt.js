// LumenAI multi-lens improvement + bug hunt.
//
// Fans out specialist "finder" lenses across the codebase, adversarially
// verifies every finding (each finder's claim is handed to a skeptic that tries
// to REFUTE it), then deduplicates and ranks the survivors.
//
// Run:   Workflow({ name: "lumen-improvement-hunt" })
//   subset of lenses:  Workflow({ name: "lumen-improvement-hunt", args: ["cost-money","concurrency-async"] })
//
// Paths are relative to the repo root (the workflow's working directory).
export const meta = {
  name: 'lumen-improvement-hunt',
  description: 'Multi-lens bug + improvement hunt on lumen-ai-sdk with adversarial verification and ranked synthesis',
  phases: [
    { title: 'Hunt', detail: 'parallel finder lenses over the codebase' },
    { title: 'Verify', detail: 'adversarially refute each finding' },
    { title: 'Synthesize', detail: 'dedup + rank confirmed findings' },
  ],
}

const CONTEXT = `
You are auditing the open-source Python SDK **LumenAI** (repo root = the current working directory). It is a real-time FinOps + multi-tenant observability layer for Generative AI built on OpenTelemetry. Goal: find REAL bugs and HIGH-VALUE improvements, not style nitpicks.

ARCHITECTURE (read the actual code):
- Monorepo under packages/: lumen-ai-core ('lumen_ai'), lumen-ai-celery ('lumen_ai_celery'), lumen-ai-openlit ('lumen_ai_openlit'). Tests in tests/, examples in examples/, CI in .github/workflows/.
- Core flow: LumenAI.init() (sdk.py) -> tracer.py registers 3 SpanProcessors IN ORDER: TenantSpanProcessor (processors/tenant.py) -> CostComputingSpanProcessor (processors/cost.py) -> EventNormalizerProcessor (processors/normalizer.py), plus optional OTLP. Tenant + cost write to module-global OrderedDict side-maps keyed "trace_id:span_id"; the normalizer reads them and exports a metadata-ONLY event (schema/event_types.py LumenAIEvent TypedDict) via a BaseLumenAIExporter.
- providers.py: pricing providers (DefaultPricingProvider, CommunityPricingProvider) + exporters (RedisExporter, JsonlExporter, AsyncRedisExporter). schema/semconv.py: attribute constants, PRICING_TABLE, match_model_pricing, compute_cost_usd. models.py: SQLAlchemy ORM (not wired into the processor chain).

PRIVACY CONTRACT (a selling point — verify it holds): the normalizer emits a fixed whitelist of metadata fields and must NEVER export prompt text, completion text, tool arguments, or raw request bodies (tests/test_public_api_contract.py).

OUTPUT RULES: read real files and cite file + line; no generic advice; rate severity honestly (critical = data loss/corruption/crash-on-normal-use/cross-tenant leak/silent money error). Give a concrete fix_sketch and a test_idea per finding.`

const COMMON = `\nReturn findings via the structured schema. Only report what the code actually does; include both confirmed bugs and concrete improvements within your lens.`

const ALL_LENSES = [
  { key: 'concurrency-async', title: 'Concurrency, async & threading', focus: `LENS: asyncio/threads/locks. Check: AsyncRedisExporter (deadlock if a flush path re-acquires its own non-reentrant Lock; loop-bound redis client reused across asyncio.run loops; fire-and-forget shutdown); module-global side-map locking + eviction races; ContextVar propagation across threads/async; Celery _active_spans concurrency + leak on revoke/worker-kill.` },
  { key: 'cost-money', title: 'Cost & money correctness', focus: `LENS: USD accuracy (the core value). Check: match_model_pricing must be longest-boundary, not first-substring (dated ids like gpt-4o-mini-2024-07-18 must NOT resolve to gpt-4o); cache_read double-billing for OpenAI/Azure (input includes cached) vs Anthropic (separate); KeyError on partial pricing dicts; duplicated cost math; rounding/int coercion; zero-token vs cache-only early return.` },
  { key: 'multitenant-isolation', title: 'Multi-tenant isolation', focus: `LENS: cross-tenant leakage. Check: on_end tenant resolution precedence (start-pinned attribute must win over the live ContextVar); the exported tenant_id vs the Redis stream key; default fallback masking real data; side-map eviction/id-reuse stale reads; tenant propagation across BatchSpanProcessor worker thread / Celery pools. Cross-check SECURITY.md.` },
  { key: 'otel-integration', title: 'OpenTelemetry integration', focus: `LENS: correct OTel SDK use. Check: blocking I/O in on_end on the span-ending thread; span.context None handling; is_recording; set-once global TracerProvider (init adopt-or-create, shutdown/re-init); _is_error status handling; span-kind -> event-type mapping (embedding/retriever/reranker); resource attributes; enable_otlp/insecure defaults.` },
  { key: 'resource-robustness', title: 'Resource mgmt & robustness', focus: `LENS: leaks & silent failures. Check: JsonlExporter file handle lifecycle + per-line flush; redis connection close; broad except that swallows real bugs (no dropped-event counter); Celery span/token leak; CommunityPricingProvider retry/back-off on failure + blocking urlopen on hot path.` },
  { key: 'api-typing-contracts', title: 'Public API, typing & contracts', focus: `LENS: API ergonomics + internal contradictions. Check: init() rejecting redis_url+exporter vs docs that show both; mypy gaps; backwards-compat aliases; __version__ duplicated across pyprojects; enable_otlp default mismatch (sdk vs tracer); TypedDict vs ORM name collisions; missing public tenant-reset helper (examples reach into _current_tenant).` },
  { key: 'security', title: 'Security', focus: `LENS: malicious span data / config / supply chain. Check: CommunityPricingProvider URL scheme allowlist + size cap + redirects (SSRF / file read / pricing poisoning of the BILLING table); tenant_id used raw in Redis stream keys (injection / unbounded keyspace); JsonlExporter arbitrary path write; anything leaking prompt/response/tool-args (privacy contract); OTLP insecure default; json default=str leaking objects. Read SECURITY.md and check claims vs code.` },
  { key: 'packaging-release', title: 'Packaging, build & release', focus: `LENS: packaging/CI. Check: py.typed inclusion per package; version single-source; inter-package pins; CI branch triggers vs the real default branch; ruff/mypy scope (core only?); publish/release-drafter/changelog/linear-sync workflow footguns; missing [tool.ruff]/[tool.pytest] config; sys.path hacks in tests. Read .github/workflows/*.yml.` },
  { key: 'tests-coverage', title: 'Tests & coverage gaps', focus: `LENS: what bug could ship undetected. Check: MagicMock spans skipping on_start/real Status; untested paths (async exporter buffer overflow, tenant cross-context, pricing dated-id resolution, community provider, celery revoke, double-init); tests that encode a wrong behavior; flaky timing/benchmark tests; examples not smoke-tested.` },
  { key: 'docs-examples', title: 'Docs & examples correctness', focus: `LENS: docs/examples that contradict code. Check: wrong import paths/module names in docstrings; processor order claims (must be Tenant->Cost->Normalizer); init usage that raises; examples that emit zero spans or always $0; README event-schema vs the TypedDict; CHANGELOG/orientation drift; misleadingly-named workflow files. Read README.md, package READMEs, examples/*/main.py.` },
]

const FINDINGS_SCHEMA = {
  type: 'object', required: ['findings'],
  properties: { findings: { type: 'array', items: {
    type: 'object',
    required: ['title', 'category', 'severity', 'file', 'description', 'why_it_matters', 'fix_sketch', 'confidence'],
    properties: {
      title: { type: 'string' }, category: { type: 'string' },
      severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
      file: { type: 'string' }, line: { type: 'string' }, description: { type: 'string' },
      why_it_matters: { type: 'string' }, evidence: { type: 'string' },
      fix_sketch: { type: 'string' }, test_idea: { type: 'string' }, confidence: { type: 'number' },
    },
  } } },
}

const VERDICT_SCHEMA = {
  type: 'object', required: ['is_real', 'adjusted_severity', 'reasoning'],
  properties: {
    is_real: { type: 'boolean' },
    adjusted_severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'not-a-bug'] },
    reasoning: { type: 'string' }, fix_recommendation: { type: 'string' },
  },
}

const SYNTHESIS_SCHEMA = {
  type: 'object', required: ['ranked', 'summary'],
  properties: {
    summary: { type: 'string' }, themes: { type: 'array', items: { type: 'string' } },
    ranked: { type: 'array', items: {
      type: 'object',
      required: ['rank', 'title', 'severity', 'file', 'fix_sketch', 'effort', 'confidence'],
      properties: {
        rank: { type: 'number' }, title: { type: 'string' },
        severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
        category: { type: 'string' }, file: { type: 'string' }, line: { type: 'string' },
        description: { type: 'string' }, fix_sketch: { type: 'string' }, test_idea: { type: 'string' },
        effort: { type: 'string', enum: ['trivial', 'small', 'medium', 'large'] }, confidence: { type: 'number' },
      },
    } },
  },
}

// Optional subset of lens keys via args.
const want = Array.isArray(args) ? args : (args && Array.isArray(args.lenses) ? args.lenses : null)
const LENSES = want ? ALL_LENSES.filter((l) => want.includes(l.key)) : ALL_LENSES

function verifyPrompt(f, lens) {
  return `${CONTEXT}\n\nYou are an ADVERSARIAL VERIFIER. A finder (lens: ${lens.title}) reported the finding below. REFUTE it: read the actual code and decide whether it is REAL or a false positive, considering Python/asyncio/OTel/redis semantics. Default to is_real=false unless the code clearly exhibits the problem; if real but the severity is inflated, lower it.\n\nFINDING:\n- title: ${f.title}\n- claimed severity: ${f.severity}\n- file: ${f.file} ${f.line ? '(line ' + f.line + ')' : ''}\n- description: ${f.description}\n- why it matters: ${f.why_it_matters}\n- proposed fix: ${f.fix_sketch}\n\nReturn is_real, adjusted_severity (or "not-a-bug"), reasoning (cite code), and a corrected fix_recommendation if real.`
}

phase('Hunt')
const perLens = await pipeline(
  LENSES,
  (lens) => agent(CONTEXT + '\n' + lens.focus + '\n' + COMMON, { label: `hunt:${lens.key}`, phase: 'Hunt', schema: FINDINGS_SCHEMA }),
  (found, lens) => {
    const list = found && Array.isArray(found.findings) ? found.findings : []
    return parallel(list.map((f, i) => () =>
      agent(verifyPrompt(f, lens), { label: `verify:${lens.key}#${i}`, phase: 'Verify', schema: VERDICT_SCHEMA })
        .then((v) => ({ ...f, lens: lens.key, verdict: v }))
    ))
  }
)

const all = perLens.flat().filter(Boolean)
const confirmed = all.filter((f) => f.verdict && f.verdict.is_real && f.verdict.adjusted_severity !== 'not-a-bug')
log(`${all.length} raw findings -> ${confirmed.length} confirmed after adversarial verification`)

phase('Synthesize')
const compact = confirmed.map((f) => ({
  title: f.title, category: f.category, severity: f.verdict.adjusted_severity || f.severity,
  file: f.file, line: f.line || '', description: f.description, why_it_matters: f.why_it_matters,
  fix: f.verdict.fix_recommendation || f.fix_sketch, test_idea: f.test_idea || '', lens: f.lens, confidence: f.confidence,
}))

const synth = await agent(
  `${CONTEXT}\n\nYou are the SYNTHESIS lead. Below is a JSON array of ${compact.length} adversarially-CONFIRMED findings from the audit lenses. (1) DEDUPLICATE (the same root issue often appears in several files/lenses — merge, listing all locations). (2) RANK by impact x likelihood-in-normal-use x credibility value (a reproducible deadlock or a silent money error outranks a doc typo). (3) For each: crisp title, final severity, file(s)+line(s), 1-3 sentence description, concrete fix_sketch, test_idea, effort (trivial/small/medium/large), confidence. (4) Drop pure subjective nits. (5) 'themes' = 3-6 cross-cutting themes. (6) 'summary' = 4-6 sentence executive health summary + what to fix first.\n\nCONFIRMED FINDINGS JSON:\n${JSON.stringify(compact)}`,
  { label: 'synthesize', phase: 'Synthesize', schema: SYNTHESIS_SCHEMA }
)

return { raw_count: all.length, confirmed_count: confirmed.length, summary: synth.summary, themes: synth.themes || [], ranked: synth.ranked, confirmed_detail: compact }
