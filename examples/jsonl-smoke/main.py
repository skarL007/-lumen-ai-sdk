"""Minimal LumenAI JSONL smoke example with no paid API key."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lumen_ai import JsonlExporter, LumenAI, lumen_tenant
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes, SpanKind
from opentelemetry import trace


def run_demo(output: Path) -> dict[str, object]:
    LumenAI.init(
        service_name="jsonl-smoke-demo",
        default_tenant="anonymous",
        exporter=JsonlExporter(output),
    )

    tracer = trace.get_tracer("jsonl-smoke-demo")
    with lumen_tenant("portfolio-acme"):
        with tracer.start_as_current_span("llm.chat") as span:
            span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
            span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 1200)
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, 300)

    LumenAI.shutdown()

    lines = output.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError("No LumenAI events were written.")
    return json.loads(lines[-1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write one LumenAI event to JSONL.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".runtime/events.jsonl"),
        help="JSONL file path to write.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    event = run_demo(args.output)
    print(f"Wrote 1 event to {args.output.resolve()}")
    print(
        "tenant={tenant} model={model} cost_usd={cost:.6f}".format(
            tenant=event["tenant_id"],
            model=event["model"],
            cost=float(event["cost_usd"]),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
