"""
Span-semantics regressions found in the 0.1.5 review pass.

  * OpenInference-only spans (``llm.token_count.*``) were priced at $0 because
    the cost processor read only ``gen_ai.usage.*``.
  * Event ``timestamp`` was the export wall-clock, not the span's end time.
  * A failed span with no GenAI/OpenInference kind was reported as
    ``AGENT_COMPLETED``.
  * ``session_id`` / ``agent_id`` ignored the OTel GenAI equivalents.
  * ``TracerProvider.force_flush()`` never reached the exporter's buffer.
"""
import os
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest
from lumen_ai import JsonlExporter
from lumen_ai.providers import (
    AsyncRedisExporter,
    BaseLumenAIExporter,
    DefaultPricingProvider,
)
from lumen_ai.schema.event_types import EventType
from lumen_ai.schema.semconv import (
    PRICING_TABLE,
    GenAIAttributes,
    LumenAIAttributes,
    OpenInferenceAttributes,
    SpanKind,
)
from lumen_ai.tracer import create_tracer_provider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Status, StatusCode


class _Capture(BaseLumenAIExporter):
    def __init__(self):
        self.events = []
        self.flushes = 0

    def export(self, tenant_id, event):
        self.events.append(event)

    def force_flush(self, timeout_millis=None):
        self.flushes += 1
        return True


def _provider(exporter) -> TracerProvider:
    return create_tracer_provider(
        service_name="semantics-test",
        default_tenant="t",
        pricing_provider=DefaultPricingProvider(PRICING_TABLE),
        exporter=exporter,
        enable_otlp=False,
    )


def test_openinference_token_counts_are_priced():
    cap = _Capture()
    tracer = _provider(cap).get_tracer("t")
    with tracer.start_as_current_span("phoenix.llm") as span:
        span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
        span.set_attribute(OpenInferenceAttributes.MODEL_NAME, "gpt-4o-mini")
        span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_PROMPT, 1_000_000)
        span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_COMPLETION, 1_000_000)

    event = cap.events[0]
    assert event["tokens_in"] == 1_000_000
    assert event["tokens_out"] == 1_000_000
    # gpt-4o-mini: $0.15 in + $0.60 out per 1M tokens
    assert event["cost_usd"] == pytest.approx(0.75)


def test_genai_tokens_win_over_openinference_when_both_present():
    cap = _Capture()
    tracer = _provider(cap).get_tracer("t")
    with tracer.start_as_current_span("llm") as span:
        span.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
        span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 1_000_000)
        span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_PROMPT, 5)

    assert cap.events[0]["tokens_in"] == 1_000_000
    assert cap.events[0]["cost_usd"] == pytest.approx(0.15)


def test_event_timestamp_is_span_end_time_not_export_time():
    cap = _Capture()
    tracer = _provider(cap).get_tracer("t")
    span = tracer.start_span("timed", start_time=1_700_000_000_000_000_000)
    span.end(end_time=1_700_000_001_500_000_000)

    event = cap.events[0]
    stamp = datetime.fromisoformat(event["timestamp"])
    assert stamp == datetime.fromtimestamp(1_700_000_001.5, tz=timezone.utc)
    assert event["duration_ms"] == 1500


def test_failed_span_without_kind_is_reported_as_failed():
    cap = _Capture()
    tracer = _provider(cap).get_tracer("t")
    with tracer.start_as_current_span("http.handler") as span:
        span.set_status(Status(StatusCode.ERROR, "boom"))

    event = cap.events[0]
    assert event["is_error"] is True
    assert event["event_type"] == EventType.AGENT_FAILED


def test_session_and_agent_fall_back_to_genai_attributes():
    cap = _Capture()
    tracer = _provider(cap).get_tracer("t")
    with tracer.start_as_current_span("chat") as span:
        span.set_attribute(GenAIAttributes.CONVERSATION_ID, "conv-1")
        span.set_attribute(GenAIAttributes.AGENT_ID, "agent-7")
    with tracer.start_as_current_span("chat") as span:
        span.set_attribute(LumenAIAttributes.SESSION_ID, "lumen-session")
        span.set_attribute(GenAIAttributes.CONVERSATION_ID, "conv-ignored")

    assert (cap.events[0]["session_id"], cap.events[0]["agent_id"]) == ("conv-1", "agent-7")
    assert cap.events[1]["session_id"] == "lumen-session"


def test_provider_force_flush_reaches_the_exporter():
    cap = _Capture()
    provider = _provider(cap)
    assert provider.force_flush() is True
    assert cap.flushes == 1


def test_duck_typed_exporter_without_force_flush_is_tolerated():
    class _Plain:
        def __init__(self):
            self.events = []

        def export(self, tenant_id, event):
            self.events.append(event)

    plain = _Plain()
    provider = _provider(plain)
    with provider.get_tracer("t").start_as_current_span("x"):
        pass
    assert provider.force_flush() is True
    assert len(plain.events) == 1


def test_jsonl_export_after_shutdown_is_ignored(tmp_path):
    exporter = JsonlExporter(tmp_path / "events.jsonl")
    exporter.shutdown()
    exporter.export("t", {"id": "late"})  # must not raise on the closed file
    assert (tmp_path / "events.jsonl").read_text(encoding="utf-8") == ""


def _recording_exporter(**kwargs):
    exp = AsyncRedisExporter("redis://localhost:6379/0", **kwargs)
    recorded = []
    written = threading.Event()

    async def rec(events):
        recorded.extend(events)
        written.set()

    exp._write_batch = rec
    return exp, recorded, written


def test_async_exporter_flushes_on_interval_below_max_buffer():
    exp, recorded, written = _recording_exporter(max_buffer=100, flush_interval=0.05)
    try:
        exp.export("acme", {"id": "1"})
        assert written.wait(timeout=2), "periodic flush never wrote the partial buffer"
        assert recorded == [("acme", {"id": "1"})]
    finally:
        exp.shutdown()


def test_async_exporter_force_flush_is_synchronous():
    exp, recorded, _ = _recording_exporter(max_buffer=100, flush_interval=None)
    try:
        exp.export("acme", {"id": "1"})
        assert exp.force_flush(timeout_millis=2000) is True
        assert recorded == [("acme", {"id": "1"})]
    finally:
        exp.shutdown()


def test_async_exporter_shutdown_is_prompt_with_periodic_flush():
    exp, _, _ = _recording_exporter(flush_interval=30)
    started = time.monotonic()
    exp.shutdown()
    assert time.monotonic() - started < 2, "shutdown waited on the periodic flusher"


@pytest.mark.parametrize("bad", [0, -1])
def test_async_exporter_rejects_non_positive_interval(bad):
    with pytest.raises(ValueError):
        AsyncRedisExporter("redis://localhost:6379/0", flush_interval=bad)
