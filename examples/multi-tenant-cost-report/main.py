"""
Reproducible multi-tenant cost report — no Redis, Docker, or API key.

Drives a fixed workload of synthetic OpenTelemetry spans for three tenants
through the real LumenAI processor chain (tenant → cost → normalizer), writes
the normalized events to JSONL, then rebuilds a per-tenant cost report from
that file alone. Every number is deterministic, so the output below is exactly
what you should see:

    python examples/multi-tenant-cost-report/main.py

The workload exercises the paths a FinOps layer has to get right:

* OTel GenAI spans (OpenAI-style) and OpenInference-only spans (Phoenix-style)
* Anthropic prompt-cache reads billed at the cache rate
* an embedding call, a tool call, an agent span, a local free model
* a failed LLM call that still costs money
* a span that STARTS in one tenant's context and ENDS in another's — it must
  stay attributed to the tenant it started in
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from lumen_ai import JsonlExporter, LumenAI, lumen_tenant
from lumen_ai.schema.semconv import (
    GenAIAttributes,
    OpenInferenceAttributes,
    SpanKind,
)
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# Keys that would only appear if content leaked into telemetry.
_CONTENT_KEYS = ("prompt", "completion", "input.value", "output.value", "messages")


def _llm(span, model: str, tokens_in: int, tokens_out: int, provider: str = "openai") -> None:
    span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
    span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
    span.set_attribute(GenAIAttributes.PROVIDER_NAME, provider)
    span.set_attribute(GenAIAttributes.REQUEST_MODEL, model)
    span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, tokens_in)
    span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, tokens_out)


def run_workload(tracer: trace.Tracer) -> None:
    # ── acme-health: support assistant on a small model ──────────────────────
    with lumen_tenant("acme-health"):
        for turn in range(3):
            with tracer.start_as_current_span(f"support.turn.{turn}") as span:
                _llm(span, "gpt-4o-mini", 1_200, 300)
        with tracer.start_as_current_span("kb.embed") as span:
            span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.EMBEDDING)
            span.set_attribute(GenAIAttributes.OPERATION_NAME, "embedding")
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, "openai/text-embedding-3-small")
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 8_000)
        with tracer.start_as_current_span("tool.search_kb") as span:
            span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.TOOL)
            span.set_attribute(GenAIAttributes.TOOL_NAME, "search_kb")

    # ── globex-legal: long contracts on a large model with prompt caching ────
    with lumen_tenant("globex-legal"):
        with tracer.start_as_current_span("contract.review") as span:
            _llm(span, "claude-sonnet-4-6", 40_000, 2_000, provider="anthropic")
            span.set_attribute(GenAIAttributes.USAGE_CACHE_READ, 30_000)
        with tracer.start_as_current_span("contract.review.retry") as span:
            _llm(span, "claude-sonnet-4-6", 5_000, 0, provider="anthropic")
            span.set_status(Status(StatusCode.ERROR, "upstream timeout"))

    # ── initech: an agent instrumented with OpenInference only (Phoenix) ─────
    with lumen_tenant("initech"):
        with tracer.start_as_current_span("agent.plan") as agent:
            agent.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.AGENT)
            with tracer.start_as_current_span("agent.llm") as span:
                span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
                span.set_attribute(OpenInferenceAttributes.MODEL_NAME, "gpt-4.1-mini")
                span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_PROMPT, 20_000)
                span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_COMPLETION, 4_000)
            with tracer.start_as_current_span("agent.local") as span:
                _llm(span, "ollama/gemma3:12b", 3_000, 500, provider="ollama")

    # ── isolation: starts under acme-health, ends while globex-legal is active ─
    with lumen_tenant("acme-health"):
        crossing = tracer.start_span("support.async_followup")
        _llm(crossing, "gpt-4o-mini", 1_200, 300)
    with lumen_tenant("globex-legal"):
        token = otel_context.attach(trace.set_span_in_context(crossing))
        try:
            crossing.end()
        finally:
            otel_context.detach(token)


def build_report(events: list[dict]) -> dict[str, dict]:
    report: dict[str, dict] = defaultdict(
        lambda: {"events": 0, "llm_calls": 0, "errors": 0, "tokens_in": 0,
                 "tokens_out": 0, "cached": 0, "cost_usd": 0.0}
    )
    for event in events:
        row = report[event["tenant_id"]]
        row["events"] += 1
        row["llm_calls"] += event["event_type"].startswith("LLM_CALL")
        row["errors"] += bool(event["is_error"])
        row["tokens_in"] += event["tokens_in"]
        row["tokens_out"] += event["tokens_out"]
        row["cached"] += event["cache_read_tokens"]
        row["cost_usd"] += event["cost_usd"]
    return dict(report)


@contextmanager
def lumen_session(output: Path) -> Iterator[trace.Tracer]:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("", encoding="utf-8")  # fresh file → reproducible totals
    LumenAI.init(
        service_name="multi-tenant-cost-report",
        default_tenant="unattributed",
        exporter=JsonlExporter(output),
    )
    try:
        yield trace.get_tracer("multi-tenant-cost-report")
    finally:
        LumenAI.shutdown()


def render(report: dict[str, dict], events: list[dict], output: Path) -> str:
    header = (f"{'tenant':<14}{'events':>7}{'llm':>5}{'errors':>7}"
              f"{'tokens in':>11}{'out':>8}{'cached':>8}{'cost (USD)':>13}")
    lines = [header, "-" * len(header)]
    rows = sorted(report.items(), key=lambda item: item[1]["cost_usd"], reverse=True)
    for tenant, r in rows:
        lines.append(
            f"{tenant:<14}{r['events']:>7}{r['llm_calls']:>5}{r['errors']:>7}"
            f"{r['tokens_in']:>11,}{r['tokens_out']:>8,}{r['cached']:>8,}"
            f"{r['cost_usd']:>13.6f}"
        )
    total = sum(r["cost_usd"] for r in report.values())
    lines += ["-" * len(header), f"{'total':<14}{len(events):>7}{total:>{len(header) - 21}.6f}", ""]

    crossing = next(e for e in events if e["message"] == "support.async_followup")
    leaked = [k for e in events for k in _CONTENT_KEYS if k in e]
    lines.append(f"isolation  span started in acme-health, ended in globex-legal "
                 f"-> billed to {crossing['tenant_id']}")
    lines.append(f"privacy    {len(events)} events, {len(leaked)} prompt/response fields exported")
    lines.append(f"events     {output.as_posix()}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--output", type=Path, default=Path(".runtime/cost-report.jsonl"))
    args = parser.parse_args()

    with lumen_session(args.output) as tracer:
        run_workload(tracer)

    events = [json.loads(line) for line in args.output.read_text(encoding="utf-8").splitlines()]
    print(render(build_report(events), events, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
