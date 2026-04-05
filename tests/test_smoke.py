"""
LumenAI SDK — smoke tests.

Run with:
    cd packages/lumen-ai-core && pip install -e . && pytest ../../tests/test_smoke.py -v
"""
import sys
import os

# Ensure the installed package is importable when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src"))

import pytest


# ---------------------------------------------------------------------------
# Test 1: Import — nothing should raise
# ---------------------------------------------------------------------------

def test_import_top_level():
    """LumenAI class importable from top-level package."""
    from lumen_ai import LumenAI  # noqa: F401
    assert LumenAI is not None


def test_import_processors():
    """All three processors importable."""
    from lumen_ai.processors.tenant import TenantSpanProcessor
    from lumen_ai.processors.cost import CostComputingSpanProcessor
    from lumen_ai.processors.normalizer import EventNormalizerProcessor
    assert TenantSpanProcessor is not None
    assert CostComputingSpanProcessor is not None
    assert EventNormalizerProcessor is not None


def test_import_providers():
    """Pricing and exporter ABCs importable."""
    from lumen_ai.providers import (
        BasePricingProvider,
        BaseLumenAIExporter,
        DefaultPricingProvider,
    )
    assert BasePricingProvider is not None
    assert BaseLumenAIExporter is not None
    assert DefaultPricingProvider is not None


# ---------------------------------------------------------------------------
# Test 2: TenantSpanProcessor — context isolation
# ---------------------------------------------------------------------------

def _make_dummy_span(trace_id: int = 1, span_id: int = 1, tenant_attr: str = ""):
    """Return a minimal ReadableSpan-like object for testing."""
    from unittest.mock import MagicMock
    span = MagicMock()
    span.context.trace_id = trace_id
    span.context.span_id = span_id
    span.name = "test-span"
    span.status = MagicMock(status_code=0)
    span.is_recording.return_value = True

    attrs = {}
    if tenant_attr:
        from lumen_ai.schema.semconv import LumenAIAttributes
        attrs[LumenAIAttributes.TENANT_ID] = tenant_attr

    span.attributes = attrs
    span.set_attribute = lambda k, v: attrs.update({k: v})
    return span


def test_tenant_processor_uses_context_var():
    """TenantSpanProcessor reads tenant from ContextVar."""
    from lumen_ai.processors.tenant import TenantSpanProcessor, set_tenant_id, get_span_tenant, _current_tenant

    proc = TenantSpanProcessor(default_tenant="default")
    token = set_tenant_id("tenant-alpha")
    try:
        span = _make_dummy_span(trace_id=0xAA, span_id=0xBB)
        proc.on_end(span)
        assert get_span_tenant(span) == "tenant-alpha"
    finally:
        _current_tenant.reset(token)


def test_tenant_processor_isolation_between_tenants():
    """Two different spans get different tenant tags when context changes."""
    from lumen_ai.processors.tenant import TenantSpanProcessor, lumen_tenant, get_span_tenant

    proc = TenantSpanProcessor(default_tenant="default")

    span_a = _make_dummy_span(trace_id=0x11, span_id=0x01)
    span_b = _make_dummy_span(trace_id=0x22, span_id=0x02)

    with lumen_tenant("tenant-a"):
        proc.on_end(span_a)

    with lumen_tenant("tenant-b"):
        proc.on_end(span_b)

    assert get_span_tenant(span_a) == "tenant-a"
    assert get_span_tenant(span_b) == "tenant-b"
    assert get_span_tenant(span_a) != get_span_tenant(span_b)


def test_tenant_processor_falls_back_to_default():
    """Without ContextVar set, uses default_tenant."""
    from lumen_ai.processors.tenant import TenantSpanProcessor, get_span_tenant, _current_tenant

    # Ensure no tenant is set
    _current_tenant.set("")

    proc = TenantSpanProcessor(default_tenant="fallback-org")
    span = _make_dummy_span(trace_id=0x33, span_id=0x03)
    proc.on_end(span)

    assert get_span_tenant(span) == "fallback-org"


# ---------------------------------------------------------------------------
# Test 3: CostComputingSpanProcessor — USD calculation
# ---------------------------------------------------------------------------

def _make_llm_span(model: str, input_tokens: int, output_tokens: int,
                   cache_read: int = 0, trace_id: int = 0xFF, span_id: int = 0xEE):
    """Return a span with gen_ai.usage.* attributes set."""
    from unittest.mock import MagicMock
    from lumen_ai.schema.semconv import GenAIAttributes

    span = MagicMock()
    span.context.trace_id = trace_id
    span.context.span_id = span_id
    span.name = "llm-call"
    span.status = MagicMock(status_code=0)

    span.attributes = {
        GenAIAttributes.REQUEST_MODEL: model,
        GenAIAttributes.USAGE_INPUT_TOKENS: input_tokens,
        GenAIAttributes.USAGE_OUTPUT_TOKENS: output_tokens,
        GenAIAttributes.USAGE_CACHE_READ: cache_read,
    }
    return span


def test_cost_processor_calculates_usd():
    """CostProcessor stores expected USD amount for known model."""
    from lumen_ai.processors.cost import CostComputingSpanProcessor, get_span_cost_data
    from lumen_ai.providers import DefaultPricingProvider
    from lumen_ai.schema.semconv import PRICING_TABLE

    pricing = DefaultPricingProvider(PRICING_TABLE)
    proc = CostComputingSpanProcessor(pricing)

    # claude-sonnet-4-6: $3/M input, $15/M output
    span = _make_llm_span("claude-sonnet-4-6", input_tokens=1_000, output_tokens=500,
                          trace_id=0x44, span_id=0x04)
    proc.on_end(span)

    cost_data = get_span_cost_data(span)
    assert cost_data["model"] == "claude-sonnet-4-6"
    assert cost_data["input_tokens"] == 1_000
    assert cost_data["output_tokens"] == 500

    expected = round((1_000 * 3.0 / 1_000_000) + (500 * 15.0 / 1_000_000), 8)
    assert cost_data["cost_usd"] == pytest.approx(expected, rel=1e-5)


def test_cost_processor_zero_tokens_skipped():
    """Span with zero tokens produces no cost entry."""
    from lumen_ai.processors.cost import CostComputingSpanProcessor, get_span_cost_data
    from lumen_ai.providers import DefaultPricingProvider
    from lumen_ai.schema.semconv import PRICING_TABLE

    pricing = DefaultPricingProvider(PRICING_TABLE)
    proc = CostComputingSpanProcessor(pricing)

    span = _make_llm_span("claude-haiku-4-5", input_tokens=0, output_tokens=0,
                          trace_id=0x55, span_id=0x05)
    proc.on_end(span)

    assert get_span_cost_data(span) == {}


def test_cost_processor_cache_read_tokens():
    """Cache read tokens add fractional cost."""
    from lumen_ai.processors.cost import CostComputingSpanProcessor, get_span_cost_data
    from lumen_ai.providers import DefaultPricingProvider
    from lumen_ai.schema.semconv import PRICING_TABLE

    pricing = DefaultPricingProvider(PRICING_TABLE)
    proc = CostComputingSpanProcessor(pricing)

    # claude-sonnet-4-6: cache_read = $0.30/M
    span = _make_llm_span("claude-sonnet-4-6", input_tokens=100, output_tokens=100,
                          cache_read=10_000, trace_id=0x66, span_id=0x06)
    proc.on_end(span)

    cost_data = get_span_cost_data(span)
    expected_cache = round(10_000 * 0.30 / 1_000_000, 8)
    assert cost_data["cache_read_tokens"] == 10_000
    assert cost_data["cost_usd"] > expected_cache  # total > cache alone


# ---------------------------------------------------------------------------
# Test 4: DefaultPricingProvider — partial model name matching
# ---------------------------------------------------------------------------

def test_pricing_provider_exact_match():
    """Exact model name returns correct prices."""
    from lumen_ai.providers import DefaultPricingProvider
    from lumen_ai.schema.semconv import PRICING_TABLE

    provider = DefaultPricingProvider(PRICING_TABLE)
    pricing = provider.get_pricing("claude-sonnet-4-6")

    assert pricing is not None
    assert pricing["input"] == pytest.approx(3.0)
    assert pricing["output"] == pytest.approx(15.0)
    assert pricing["cache_read"] == pytest.approx(0.30)


def test_pricing_provider_partial_match():
    """Provider/model prefix like 'anthropic/claude-sonnet-4-6' still resolves."""
    from lumen_ai.providers import DefaultPricingProvider
    from lumen_ai.schema.semconv import PRICING_TABLE

    provider = DefaultPricingProvider(PRICING_TABLE)
    pricing = provider.get_pricing("anthropic/claude-sonnet-4-6")

    assert pricing is not None
    assert pricing["input"] == pytest.approx(3.0)


def test_pricing_provider_unknown_model():
    """Unknown model returns None — no crash."""
    from lumen_ai.providers import DefaultPricingProvider
    from lumen_ai.schema.semconv import PRICING_TABLE

    provider = DefaultPricingProvider(PRICING_TABLE)
    pricing = provider.get_pricing("some-totally-unknown-model-v99")

    assert pricing is None


def test_pricing_provider_free_local_model():
    """Ollama local models return zero cost."""
    from lumen_ai.providers import DefaultPricingProvider
    from lumen_ai.schema.semconv import PRICING_TABLE

    provider = DefaultPricingProvider(PRICING_TABLE)
    pricing = provider.get_pricing("ollama/gemma3:12b")

    assert pricing is not None
    assert pricing["input"] == 0.0
    assert pricing["output"] == 0.0
