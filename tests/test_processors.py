"""
LumenAI SDK — processor unit tests.

Covers: TenantSpanProcessor context API, CostComputingSpanProcessor USD math,
        PRICING_TABLE sanity checks.

Run with:
    pip install -e packages/lumen-ai-core && pytest tests/ -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src"))

import pytest
from unittest.mock import MagicMock

from lumen_ai.processors.tenant import (
    set_tenant_id,
    get_tenant_id,
    lumen_tenant,
    _current_tenant,
)
from lumen_ai.processors.cost import CostComputingSpanProcessor, get_span_cost_data
from lumen_ai.providers import DefaultPricingProvider
from lumen_ai.schema.semconv import PRICING_TABLE, GenAIAttributes, OpenInferenceAttributes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_span(model: str, input_tokens: int, output_tokens: int,
                   cache_read: int = 0, trace_id: int = 0xA0, span_id: int = 0xB0):
    span = MagicMock()
    span.context.trace_id = trace_id
    span.context.span_id = span_id
    span.name = "test-llm"
    span.attributes = {
        GenAIAttributes.REQUEST_MODEL: model,
        GenAIAttributes.USAGE_INPUT_TOKENS: input_tokens,
        GenAIAttributes.USAGE_OUTPUT_TOKENS: output_tokens,
        GenAIAttributes.USAGE_CACHE_READ: cache_read,
    }
    return span


# ---------------------------------------------------------------------------
# Tenant ContextVar
# ---------------------------------------------------------------------------

def test_set_and_get_tenant():
    token = set_tenant_id("acme")
    assert get_tenant_id() == "acme"
    _current_tenant.reset(token)


def test_lumen_tenant_context_manager():
    with lumen_tenant("tenant-x"):
        assert get_tenant_id() == "tenant-x"
    assert get_tenant_id() == ""


def test_tenant_isolation_nested():
    with lumen_tenant("outer"):
        with lumen_tenant("inner"):
            assert get_tenant_id() == "inner"
        assert get_tenant_id() == "outer"


def test_set_tenant_strips_whitespace():
    token = set_tenant_id("  spaces  ")
    assert get_tenant_id() == "spaces"
    _current_tenant.reset(token)


# ---------------------------------------------------------------------------
# CostComputingSpanProcessor
# ---------------------------------------------------------------------------

def test_cost_haiku_1m_tokens():
    """claude-haiku-4-5: $0.25/M in + $1.25/M out = $1.50 for 1M each."""
    pricing = DefaultPricingProvider(PRICING_TABLE)
    proc = CostComputingSpanProcessor(pricing)

    span = _make_llm_span("claude-haiku-4-5",
                          input_tokens=1_000_000, output_tokens=1_000_000,
                          trace_id=0xC1, span_id=0xD1)
    proc.on_end(span)

    cost_data = get_span_cost_data(span)
    assert abs(cost_data["cost_usd"] - 1.50) < 0.001


def test_cost_unknown_model_no_crash():
    """Unknown model produces no cost entry, no exception."""
    pricing = DefaultPricingProvider(PRICING_TABLE)
    proc = CostComputingSpanProcessor(pricing)

    span = _make_llm_span("unknown-model-xyz",
                          input_tokens=1000, output_tokens=1000,
                          trace_id=0xC2, span_id=0xD2)
    proc.on_end(span)

    assert get_span_cost_data(span) == {}


def test_cost_cache_read_with_minimal_input():
    """Cache read tokens contribute to cost (needs input>0 to avoid early return)."""
    pricing = DefaultPricingProvider(PRICING_TABLE)
    proc = CostComputingSpanProcessor(pricing)

    # claude-sonnet-4-6: cache_read = $0.30/M
    span = _make_llm_span("claude-sonnet-4-6",
                          input_tokens=1, output_tokens=0,
                          cache_read=1_000_000,
                          trace_id=0xC3, span_id=0xD3)
    proc.on_end(span)

    cost_data = get_span_cost_data(span)
    expected_cache = 1_000_000 * 0.30 / 1_000_000  # $0.30
    # total = tiny input cost + $0.30 cache
    assert cost_data["cost_usd"] >= 0.29
    assert cost_data["cache_read_tokens"] == 1_000_000


def test_cost_processor_reads_openinference_token_attributes():
    pricing = DefaultPricingProvider(PRICING_TABLE)
    proc = CostComputingSpanProcessor(pricing)

    span = MagicMock()
    span.context.trace_id = 0xC4
    span.context.span_id = 0xD4
    span.name = "openinference-llm"
    span.attributes = {
        OpenInferenceAttributes.MODEL_NAME: "gpt-4o-mini",
        OpenInferenceAttributes.TOKEN_COUNT_PROMPT: 1200,
        OpenInferenceAttributes.TOKEN_COUNT_COMPLETION: 300,
    }

    proc.on_end(span)

    cost_data = get_span_cost_data(span)
    assert cost_data["model"] == "gpt-4o-mini"
    assert cost_data["input_tokens"] == 1200
    assert cost_data["output_tokens"] == 300
    assert cost_data["cost_usd"] > 0


# ---------------------------------------------------------------------------
# Pricing table sanity
# ---------------------------------------------------------------------------

def test_pricing_table_has_required_models():
    required = ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"]
    for model in required:
        assert model in PRICING_TABLE, f"Missing: {model}"


def test_pricing_table_no_negative_prices():
    for model, prices in PRICING_TABLE.items():
        assert prices["input"] >= 0, f"{model} has negative input price"
        assert prices["output"] >= 0, f"{model} has negative output price"
        assert prices.get("cache_read", 0) >= 0, f"{model} has negative cache_read price"
