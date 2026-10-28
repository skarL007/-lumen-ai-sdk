"""
Regression tests for model-id -> pricing resolution.

These cover the substring-fallback bug where a dated/versioned model id
(e.g. "gpt-4o-mini-2024-07-18") resolved to a SHORTER base key that happened
to appear earlier in PRICING_TABLE ("gpt-4o"), silently over-billing 16-20x.
The resolver must pick the LONGEST boundary-anchored key, order-independently.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest
from lumen_ai.providers import DefaultPricingProvider
from lumen_ai.schema.semconv import PRICING_TABLE, compute_cost


@pytest.mark.parametrize(
    "model, expected_key",
    [
        ("gpt-4o-mini-2024-07-18", "gpt-4o-mini"),   # must NOT resolve to gpt-4o
        ("gpt-4.1-nano-2025-04-14", "gpt-4.1-nano"),  # must NOT resolve to gpt-4.1
        ("gpt-4.1-mini-2025-04-14", "gpt-4.1-mini"),  # must NOT resolve to gpt-4.1
        ("gpt-4o-2024-11-20", "gpt-4o"),              # base id keeps its own tier
        ("claude-sonnet-4-6", "claude-sonnet-4-6"),   # exact match unchanged
        ("claude-opus-5-5", "claude-opus-5-5"),       # must NOT resolve to claude-opus-5
        ("claude-fable-5-1", "claude-fable-5-1"),     # must NOT resolve to claude-fable-5
        ("claude-haiku-4-5-20251001", "claude-haiku-4-5"),
        ("anthropic/claude-sonnet-5-5", "claude-sonnet-5-5"),  # prefixed id, bare key
        ("gpt-5.5", "gpt-5.5"),                       # "." is no separator: not gpt-5
        ("gpt-5-mini-2025-08-07", "gpt-5-mini"),      # must NOT resolve to gpt-5
        ("gpt-5.4-mini-2026-03-17", "gpt-5.4-mini"),
        ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite"),  # not gemini-2.5-flash
        ("models/gemini-2.5-flash", "gemini-2.5-flash"),     # google-genai style id
        ("mistral-large-latest", "mistral-large"),    # alias of Mistral Large 3
        ("mistral-large-4-0", "mistral-large-4"),     # must NOT resolve to Large 3
        ("deepseek-flash", "deepseek-flash"),
    ],
)
def test_dated_model_ids_resolve_to_their_own_tier(model, expected_key):
    provider = DefaultPricingProvider(PRICING_TABLE)
    assert provider.get_pricing(model) == PRICING_TABLE[expected_key]


def test_compute_cost_dated_mini_not_billed_as_base():
    # gpt-4o-mini = $0.15/M in + $0.60/M out => $0.75 for 1M each.
    # The bug billed it as gpt-4o ($2.50 + $10.00 = $12.50).
    assert compute_cost("gpt-4o-mini-2024-07-18", 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_longest_match_is_insertion_order_independent():
    # Even when the base key is inserted BEFORE the variant, a mini id must
    # still resolve to the mini tier (longest boundary match, not first match).
    shuffled = {
        "gpt-4o": PRICING_TABLE["gpt-4o"],
        "gpt-4o-mini": PRICING_TABLE["gpt-4o-mini"],
    }
    provider = DefaultPricingProvider(shuffled)
    assert provider.get_pricing("gpt-4o-mini-2024-07-18") == PRICING_TABLE["gpt-4o-mini"]


def test_provider_prefix_still_resolves():
    provider = DefaultPricingProvider(PRICING_TABLE)
    assert (
        provider.get_pricing("openrouter/anthropic/claude-sonnet-4-6")
        == PRICING_TABLE["anthropic/claude-sonnet-4-6"]
    )


def test_unknown_model_still_returns_none():
    provider = DefaultPricingProvider(PRICING_TABLE)
    assert provider.get_pricing("some-totally-unknown-model-v99") is None


def test_substring_without_boundary_does_not_match():
    # "claude-sonnet-4-6" must not be matched by an unrelated id that merely
    # contains it without a separator boundary.
    provider = DefaultPricingProvider(PRICING_TABLE)
    assert provider.get_pricing("notaclaude-sonnet-4-6x") is None
