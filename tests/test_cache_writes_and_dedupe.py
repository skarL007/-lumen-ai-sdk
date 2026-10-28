"""
Cache writes, emitter-aware cache accounting, and billing each call once.

* Cache writes (gen_ai.usage.cache_creation.input_tokens, the Anthropic SDK's
  gen_ai.usage.cache_write.input_tokens, OpenInference's
  llm.token_count.prompt_details.cache_write) are billed at the model's
  cache_write rate, else at its input rate. They used to cost nothing.
* Whether input tokens include the cached ones depends on the emitter: the
  instrumentation scopes in CACHE_INCLUSIVE_SCOPES always include them.
* A span whose usage equals the sum of its children's is not billed again.
"""
import os
import sys
import types

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-openlit", "src")
)

import pytest
from lumen_ai import LumenAI, lumen_tenant
from lumen_ai.processors.normalizer import reset_metrics
from lumen_ai.schema.semconv import (
    PRICING_TABLE,
    GenAIAttributes,
    OpenInferenceAttributes,
    compute_cost_usd,
    input_includes_cache,
)
from opentelemetry import trace
from opentelemetry.util._once import Once

SONNET = PRICING_TABLE["claude-sonnet-4-6"]  # 3 / 15, cache read 0.30, cache write 3.75


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


def _init():
    capture = _Capture()
    LumenAI.init(service_name="t", default_tenant="acme", exporter=capture, genai_only=True)
    return capture


def _usage(span, model="claude-sonnet-4-6", provider="anthropic", input_tokens=0,
           output_tokens=0, cache_read=0, cache_write=0, write_attr=GenAIAttributes.USAGE_CACHE_CREATION):
    span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
    span.set_attribute(GenAIAttributes.REQUEST_MODEL, model)
    span.set_attribute(GenAIAttributes.PROVIDER_NAME, provider)
    span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, input_tokens)
    span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, output_tokens)
    span.set_attribute(GenAIAttributes.USAGE_CACHE_READ, cache_read)
    span.set_attribute(write_attr, cache_write)


def _billed(capture):
    return [e for e in capture.events if e["cost_usd"] > 0]


# ── formula ─────────────────────────────────────────────────────────────────

def test_cache_writes_use_the_cache_write_rate():
    cost = compute_cost_usd(SONNET, 0, 0, 0, cache_write_tokens=1_000_000)
    assert cost == pytest.approx(3.75)


def test_cache_writes_fall_back_to_the_input_rate():
    cost = compute_cost_usd({"input": 2.0, "output": 8.0, "cache_read": 0.5}, 0, 0, 0, 1_000_000)
    assert cost == pytest.approx(2.0)


@pytest.mark.parametrize(
    "scope, provider, input_tokens, read, write, expected",
    [
        ("opentelemetry.instrumentation.anthropic", "anthropic", 1700, 1000, 500, True),
        ("openinference.instrumentation.anthropic", "anthropic", 1200, 1000, 0, True),
        ("com.anthropic.sdk.python", "anthropic", 1200, 1000, 0, True),
        ("opentelemetry.util.genai.handler", "openai", 1200, 1000, 0, True),
        ("openlit.instrumentation.anthropic", "anthropic", 5000, 1000, 0, False),  # provider-native
        ("openlit.instrumentation.openai", "openai", 1200, 1000, 0, True),
        ("my.app", "anthropic", 5000, 1000, 0, False),        # unknown emitter: provider rule
        ("opentelemetry.instrumentation.anthropic", "anthropic", 200, 1000, 0, False),  # cannot contain
        ("opentelemetry.instrumentation.anthropic", "anthropic", 1200, 0, 0, False),    # nothing cached
    ],
)
def test_input_includes_cache_rules(scope, provider, input_tokens, read, write, expected):
    assert input_includes_cache(scope, provider, input_tokens, read, write) is expected


# ── processor ───────────────────────────────────────────────────────────────

def test_exclusive_emitter_bills_cache_writes():
    capture = _init()
    with lumen_tenant("acme"), trace.get_tracer("my.app").start_as_current_span("llm") as span:
        _usage(span, input_tokens=200, output_tokens=300, cache_read=1000, cache_write=500)

    event = capture.events[0]
    assert event["cost_usd"] == pytest.approx((200 * 3 + 300 * 15 + 1000 * 0.30 + 500 * 3.75) / 1e6)
    assert event["cache_write_tokens"] == 500


def test_inclusive_emitter_subtracts_reads_and_writes_from_input():
    capture = _init()
    tracer = trace.get_tracer("opentelemetry.instrumentation.anthropic")
    with lumen_tenant("acme"), tracer.start_as_current_span("llm") as span:
        _usage(span, input_tokens=1700, output_tokens=300, cache_read=1000, cache_write=500)

    event = capture.events[0]
    assert event["cost_usd"] == pytest.approx((200 * 3 + 300 * 15 + 1000 * 0.30 + 500 * 3.75) / 1e6)
    assert event["tokens_in"] == 1700  # reported as the emitter sent it


def test_anthropic_sdk_cache_write_attribute_is_read():
    capture = _init()
    tracer = trace.get_tracer("com.anthropic.sdk.python")
    with lumen_tenant("acme"), tracer.start_as_current_span("llm") as span:
        _usage(span, input_tokens=1700, output_tokens=300, cache_read=1000, cache_write=500,
               write_attr=GenAIAttributes.USAGE_CACHE_WRITE)

    assert capture.events[0]["cache_write_tokens"] == 500
    assert capture.events[0]["cost_usd"] == pytest.approx(0.007275)


def test_openinference_cache_details_are_read():
    capture = _init()
    tracer = trace.get_tracer("openinference.instrumentation.openai")
    with lumen_tenant("acme"), tracer.start_as_current_span("ChatCompletion") as span:
        span.set_attribute(OpenInferenceAttributes.SPAN_KIND, "LLM")
        span.set_attribute(OpenInferenceAttributes.MODEL_NAME, "gpt-4o-mini")
        span.set_attribute(OpenInferenceAttributes.PROVIDER, "openai")
        span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_PROMPT, 1200)
        span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_COMPLETION, 300)
        span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_CACHE_READ, 1000)

    event = capture.events[0]
    assert event["cache_read_tokens"] == 1000
    assert event["cost_usd"] == pytest.approx(0.000285)


# ── each call billed once ───────────────────────────────────────────────────

def test_two_instrumentations_of_one_call_bill_it_once():
    capture = _init()
    outer_tracer = trace.get_tracer("openinference.instrumentation.anthropic")
    inner_tracer = trace.get_tracer("com.anthropic.sdk.python")
    with lumen_tenant("acme"):
        with outer_tracer.start_as_current_span("messages.create") as outer:
            with inner_tracer.start_as_current_span("anthropic.messages.create") as inner:
                _usage(inner, input_tokens=1200, output_tokens=300, cache_read=1000)
            _usage(outer, input_tokens=1200, output_tokens=300, cache_read=1000)

    billed = _billed(capture)
    assert len(billed) == 1 and billed[0]["message"] == "anthropic.messages.create"
    assert billed[0]["cost_usd"] == pytest.approx(0.0054)
    repeated = [e for e in capture.events if e["message"] == "messages.create"][0]
    assert repeated["tokens_in"] == 0 and repeated["unpriced"] is False


def test_inclusive_and_exclusive_layers_of_one_call_bill_it_once():
    capture = _init()
    with lumen_tenant("acme"):
        with trace.get_tracer("opentelemetry.instrumentation.anthropic").start_as_current_span("outer") as outer:
            with trace.get_tracer("openlit.instrumentation.anthropic").start_as_current_span("inner") as inner:
                _usage(inner, input_tokens=200, output_tokens=300, cache_read=1000)
            _usage(outer, input_tokens=1200, output_tokens=300, cache_read=1000)

    assert [e["message"] for e in _billed(capture)] == ["inner"]


def test_agent_span_with_totals_of_two_calls_is_not_billed_again():
    capture = _init()
    tracer = trace.get_tracer("my.app")
    with lumen_tenant("acme"):
        with tracer.start_as_current_span("agent") as agent:
            with tracer.start_as_current_span("step"):  # no usage of its own
                with tracer.start_as_current_span("call-1") as first:
                    _usage(first, input_tokens=100, output_tokens=10)
                with tracer.start_as_current_span("call-2") as second:
                    _usage(second, input_tokens=300, output_tokens=30)
            _usage(agent, input_tokens=400, output_tokens=40)

    assert sorted(e["message"] for e in _billed(capture)) == ["call-1", "call-2"]


def test_repeating_span_without_a_model_id_is_not_flagged_unpriced():
    capture = _init()
    tracer = trace.get_tracer("my.app")
    with lumen_tenant("acme"):
        with tracer.start_as_current_span("wrapper") as wrapper:
            with tracer.start_as_current_span("call") as call:
                _usage(call, input_tokens=100, output_tokens=10)
            wrapper.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
            wrapper.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 100)
            wrapper.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, 10)

    wrapper_event = [e for e in capture.events if e["message"] == "wrapper"][0]
    assert wrapper_event["unpriced"] is False and wrapper_event["tokens_in"] == 0


def test_parent_with_its_own_different_usage_is_still_billed():
    capture = _init()
    tracer = trace.get_tracer("my.app")
    with lumen_tenant("acme"):
        with tracer.start_as_current_span("planner") as planner:
            with tracer.start_as_current_span("tool-llm") as child:
                _usage(child, input_tokens=100, output_tokens=10)
            _usage(planner, input_tokens=900, output_tokens=90)

    assert sorted(e["message"] for e in _billed(capture)) == ["planner", "tool-llm"]


# ── OpenLIT bridge stays metadata-only ──────────────────────────────────────

def test_openlit_bridge_starts_openlit_without_content_events_or_metrics(monkeypatch):
    calls = {}

    def init(capture_message_content=True, disable_events=False, disable_metrics=False,
             disable_batch=False, collect_gpu_stats=False, pricing_json=None):
        calls.update(capture_message_content=capture_message_content,
                     disable_events=disable_events, disable_metrics=disable_metrics)

    monkeypatch.setitem(sys.modules, "openlit", types.SimpleNamespace(init=init))
    from lumen_ai_openlit import OpenLITBridge

    OpenLITBridge()._instrument()
    assert calls == {"capture_message_content": False, "disable_events": True, "disable_metrics": True}
