"""
Cache-read accounting tests.

Two distinct bugs:
  * #9  A span whose only tokens are cache reads (input==output==0) was skipped
        entirely, dropping real cache cost.
  * #5  For emitters whose gen_ai.usage.input_tokens INCLUDES the cached tokens
        (OpenAI / Azure), billing input*rate + cache*rate double-charges the
        cached tokens. Anthropic reports them separately, so it must stay additive.
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest

from lumen_ai.processors.cost import CostComputingSpanProcessor, get_span_cost_data
from lumen_ai.providers import DefaultPricingProvider
from lumen_ai.schema.semconv import PRICING_TABLE, GenAIAttributes


def _span(model, input_tokens, output_tokens, cache_read=0, provider=None,
          trace_id=0xA1, span_id=0xB1):
    span = MagicMock()
    span.context.trace_id = trace_id
    span.context.span_id = span_id
    span.name = "llm"
    span.status = MagicMock(status_code=0)
    attrs = {
        GenAIAttributes.REQUEST_MODEL: model,
        GenAIAttributes.USAGE_INPUT_TOKENS: input_tokens,
        GenAIAttributes.USAGE_OUTPUT_TOKENS: output_tokens,
        GenAIAttributes.USAGE_CACHE_READ: cache_read,
    }
    if provider is not None:
        attrs[GenAIAttributes.PROVIDER_NAME] = provider
    span.attributes = attrs
    return span


def _proc():
    return CostComputingSpanProcessor(DefaultPricingProvider(PRICING_TABLE))


def test_cache_only_span_is_still_billed():
    # input==output==0 but 1M cache-read tokens on claude-sonnet-4-6 ($0.30/M cache).
    proc = _proc()
    proc.on_end(_span("claude-sonnet-4-6", 0, 0, cache_read=1_000_000,
                      trace_id=0xCA0001, span_id=0xCB0001))
    data = get_span_cost_data(_span("claude-sonnet-4-6", 0, 0, cache_read=1_000_000,
                                    trace_id=0xCA0001, span_id=0xCB0001))
    assert data.get("cost_usd") == pytest.approx(0.30)


def test_openai_inclusive_cache_not_double_billed():
    # gpt-4o: input $2.50/M, cache_read $1.25/M. OpenAI input_tokens INCLUDES the
    # 200 cached tokens, so only 800 should be billed at input rate.
    proc = _proc()
    proc.on_end(_span("gpt-4o", input_tokens=1000, output_tokens=0,
                      cache_read=200, provider="openai", trace_id=0xCA0002, span_id=0xCB0002))
    data = get_span_cost_data(_span("gpt-4o", 1000, 0, cache_read=200, provider="openai",
                                    trace_id=0xCA0002, span_id=0xCB0002))
    expected = round((800 * 2.50 + 200 * 1.25) / 1_000_000, 8)  # 0.00225, not 0.00275
    assert data.get("cost_usd") == pytest.approx(expected)
    # token counts must still report the ORIGINAL input, not the billed subset
    assert data.get("input_tokens") == 1000


def test_anthropic_exclusive_cache_stays_additive():
    # claude-sonnet-4-6: input $3/M, cache_read $0.30/M. Anthropic reports input
    # WITHOUT the cached tokens, so the full input is billed (no subtraction).
    proc = _proc()
    proc.on_end(_span("claude-sonnet-4-6", input_tokens=1000, output_tokens=0,
                      cache_read=200, provider="anthropic", trace_id=0xCA0003, span_id=0xCB0003))
    data = get_span_cost_data(_span("claude-sonnet-4-6", 1000, 0, cache_read=200,
                                    provider="anthropic", trace_id=0xCA0003, span_id=0xCB0003))
    expected = round((1000 * 3.0 + 200 * 0.30) / 1_000_000, 8)
    assert data.get("cost_usd") == pytest.approx(expected)


def test_unknown_provider_cache_stays_additive():
    # No provider attribute -> conservative additive behavior (unchanged).
    proc = _proc()
    proc.on_end(_span("claude-sonnet-4-6", input_tokens=1000, output_tokens=0,
                      cache_read=200, provider=None, trace_id=0xCA0004, span_id=0xCB0004))
    data = get_span_cost_data(_span("claude-sonnet-4-6", 1000, 0, cache_read=200,
                                    provider=None, trace_id=0xCA0004, span_id=0xCB0004))
    expected = round((1000 * 3.0 + 200 * 0.30) / 1_000_000, 8)
    assert data.get("cost_usd") == pytest.approx(expected)
