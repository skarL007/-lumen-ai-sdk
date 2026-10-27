"""
``LumenAI.init(genai_only=True)``: export only spans with GenAI semantics.

Frameworks now emit their own OTel spans (FastAPI request, endpoint and
serialization spans, for example). By default LumenAI reports untyped spans as
generic agent steps; with ``genai_only`` it skips them so the event stream
holds only GenAI work.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest
from lumen_ai import LumenAI, lumen_tenant
from lumen_ai.processors.normalizer import get_metrics, reset_metrics
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes, SpanKind
from opentelemetry import trace
from opentelemetry.util._once import Once


@pytest.fixture(autouse=True)
def _isolate_global_tracer_provider():
    saved_tp = trace._TRACER_PROVIDER
    saved_once = trace._TRACER_PROVIDER_SET_ONCE
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    LumenAI._initialized = False
    LumenAI._provider = None
    LumenAI._exporter = None
    LumenAI._runtime = None
    LumenAI._instrumentors = []
    reset_metrics()
    yield
    LumenAI.shutdown()
    LumenAI._initialized = False
    LumenAI._provider = None
    LumenAI._exporter = None
    LumenAI._runtime = None
    LumenAI._instrumentors = []
    trace._TRACER_PROVIDER = saved_tp
    trace._TRACER_PROVIDER_SET_ONCE = saved_once


class _Capture:
    def __init__(self):
        self.events = []

    def export(self, tenant_id, event):
        self.events.append(event)

    def shutdown(self):
        pass


def _emit_mixed_workload():
    tracer = trace.get_tracer("genai-only-test")
    with lumen_tenant("acme"):
        with tracer.start_as_current_span("POST /chat"):  # framework span, no GenAI attrs
            with tracer.start_as_current_span("llm") as span:
                span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
                span.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
                span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 1_000)
                span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, 100)
            with tracer.start_as_current_span("search") as span:
                span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.TOOL)
            with tracer.start_as_current_span("plan") as span:
                span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.AGENT)
            with tracer.start_as_current_span("fastapi.serialization"):
                pass


def test_default_still_reports_untyped_spans_as_agent_steps():
    capture = _Capture()
    LumenAI.init(service_name="t", default_tenant="acme", exporter=capture)
    _emit_mixed_workload()

    names = [event["message"] for event in capture.events]
    assert names == ["llm", "search", "plan", "fastapi.serialization", "POST /chat"]
    untyped = [e for e in capture.events if e["message"] == "POST /chat"][0]
    assert untyped["event_type"] == "AGENT_COMPLETED"


def test_genai_only_skips_framework_spans():
    capture = _Capture()
    LumenAI.init(service_name="t", default_tenant="acme", exporter=capture, genai_only=True)
    _emit_mixed_workload()

    assert [event["message"] for event in capture.events] == ["llm", "search", "plan"]
    assert [event["event_type"] for event in capture.events] == [
        "LLM_CALL_COMPLETED", "TOOL_CALL_COMPLETED", "AGENT_COMPLETED",
    ]
    assert capture.events[0]["cost_usd"] == pytest.approx(0.00021)
    assert get_metrics()["events_skipped"] == 2


def test_genai_only_follows_reinit():
    first = _Capture()
    LumenAI.init(service_name="t1", default_tenant="acme", exporter=first, genai_only=True)
    LumenAI.shutdown()

    second = _Capture()
    LumenAI.init(service_name="t2", default_tenant="acme", exporter=second)
    _emit_mixed_workload()

    assert len(second.events) == 5
