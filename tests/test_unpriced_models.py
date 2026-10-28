"""
Spans that used tokens but have no price must not pass for free.

A model missing from the price table used to export ``cost_usd=0.0`` with only
a DEBUG log, so a new model looked free. Now the event carries ``unpriced=True``,
``events_unpriced`` counts it, and the first such span per model logs a WARNING.
A model priced at $0 (a local Ollama model) stays ``unpriced=False``.
"""
import logging
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest
from lumen_ai import LumenAI, lumen_tenant
from lumen_ai.processors import cost as cost_module
from lumen_ai.processors.normalizer import get_metrics, reset_metrics
from lumen_ai.providers import BasePricingProvider
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
    cost_module._warned_models.clear()
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


def _llm_span(model, input_tokens=1_000, output_tokens=100, name="llm"):
    tracer = trace.get_tracer("unpriced-test")
    with lumen_tenant("acme"):
        with tracer.start_as_current_span(name) as span:
            span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
            if model:
                span.set_attribute(GenAIAttributes.REQUEST_MODEL, model)
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, input_tokens)
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, output_tokens)


def _init(**kwargs):
    capture = _Capture()
    LumenAI.init(service_name="t", default_tenant="acme", exporter=capture, **kwargs)
    return capture


def _unpriced_warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING and "No price" in r.message]


def test_unknown_model_is_flagged_counted_and_warned_once(caplog):
    capture = _init()
    with caplog.at_level(logging.WARNING, logger="lumen_ai.processors.cost"):
        _llm_span("acme-llm-9000")
        _llm_span("acme-llm-9000")

    assert [e["unpriced"] for e in capture.events] == [True, True]
    assert all(e["cost_usd"] == 0.0 for e in capture.events)
    assert capture.events[0]["model"] == "acme-llm-9000"
    assert capture.events[0]["tokens_in"] == 1_000
    assert get_metrics()["events_unpriced"] == 2
    warnings = _unpriced_warnings(caplog)
    assert len(warnings) == 1
    assert "acme-llm-9000" in warnings[0].message


def test_each_unknown_model_gets_its_own_warning(caplog):
    _init()
    with caplog.at_level(logging.WARNING, logger="lumen_ai.processors.cost"):
        _llm_span("acme-llm-9000")
        _llm_span("acme-llm-9001")

    assert len(_unpriced_warnings(caplog)) == 2


def test_priced_model_is_not_flagged(caplog):
    capture = _init()
    with caplog.at_level(logging.WARNING, logger="lumen_ai.processors.cost"):
        _llm_span("gpt-4o-mini")

    event = capture.events[0]
    assert event["unpriced"] is False
    assert event["cost_usd"] > 0
    assert get_metrics()["events_unpriced"] == 0
    assert _unpriced_warnings(caplog) == []


def test_model_priced_at_zero_is_free_not_unpriced():
    capture = _init()
    _llm_span("ollama/gemma3:12b")

    event = capture.events[0]
    assert event["cost_usd"] == 0.0
    assert event["unpriced"] is False
    assert get_metrics()["events_unpriced"] == 0


def test_span_without_tokens_is_not_flagged():
    capture = _init()
    tracer = trace.get_tracer("unpriced-test")
    with lumen_tenant("acme"):
        with tracer.start_as_current_span("search") as span:
            span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.TOOL)
        with tracer.start_as_current_span("llm") as span:
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, "acme-llm-9000")

    assert [e["unpriced"] for e in capture.events] == [False, False]
    assert get_metrics()["events_unpriced"] == 0


def test_tokens_without_a_model_id_are_flagged():
    capture = _init()
    _llm_span(None)

    assert capture.events[0]["unpriced"] is True
    assert get_metrics()["events_unpriced"] == 1


def test_failing_pricing_provider_flags_the_event(caplog):
    class _Broken(BasePricingProvider):
        def get_pricing(self, model):
            raise RuntimeError("price service down")

    capture = _init(pricing_provider=_Broken())
    with caplog.at_level(logging.WARNING, logger="lumen_ai.processors.cost"):
        _llm_span("gpt-4o-mini")

    assert capture.events[0]["unpriced"] is True
    assert get_metrics()["events_unpriced"] == 1
    assert len(_unpriced_warnings(caplog)) == 1


def test_warned_models_set_is_bounded(caplog):
    _init()
    cost_module._warned_models.update(
        f"filler-{i}" for i in range(cost_module._MAX_WARNED_MODELS)
    )
    with caplog.at_level(logging.WARNING, logger="lumen_ai.processors.cost"):
        _llm_span("acme-llm-9000")

    assert len(cost_module._warned_models) == cost_module._MAX_WARNED_MODELS
    assert _unpriced_warnings(caplog) == []
    assert get_metrics()["events_unpriced"] == 1
