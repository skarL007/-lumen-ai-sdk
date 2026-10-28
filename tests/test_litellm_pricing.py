"""LiteLLMPricingProvider and scripts/check_prices.py, offline."""
import importlib.util
import io
import json
import os
import sys
import threading
import time

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest
from lumen_ai import providers
from lumen_ai.providers import LiteLLMPricingProvider, litellm_pricing_table

ROOT = os.path.join(os.path.dirname(__file__), "..")

LIST = {
    "sample_spec": {"input_cost_per_token": 0.0},
    "groq/llama-3.3-70b-versatile": {"input_cost_per_token": 5.9e-07, "output_cost_per_token": 7.9e-07},
    "xai/grok-4": {"input_cost_per_token": 3e-06, "output_cost_per_token": 1.5e-05,
                   "cache_read_input_token_cost": 7.5e-07},
    "anthropic/claude-new": {"input_cost_per_token": 2e-06, "output_cost_per_token": 1e-05,
                             "cache_read_input_token_cost": 2e-07,
                             "cache_creation_input_token_cost": 2.5e-06},
    "claude-sonnet-4-6": {"input_cost_per_token": 9e-06, "output_cost_per_token": 9e-05},
    "image-model": {"output_cost_per_image": 0.04},
    "broken": {"input_cost_per_token": True},
    "negative": {"input_cost_per_token": -1e-06},
}


def test_conversion_to_usd_per_million():
    table = litellm_pricing_table(LIST)
    assert table["xai/grok-4"] == {"input": 3.0, "output": 15.0, "cache_read": 0.75}
    assert table["anthropic/claude-new"]["cache_write"] == 2.5
    # No cache discount listed: cached tokens cost the input rate, never less.
    assert table["groq/llama-3.3-70b-versatile"]["cache_read"] == 0.59
    assert table["grok-4"] == table["xai/grok-4"]  # bare alias
    for skipped in ("sample_spec", "image-model", "broken", "negative"):
        assert skipped not in table


def test_bare_alias_never_overrides_a_native_entry():
    table = litellm_pricing_table({
        "claude-x": {"input_cost_per_token": 1e-06},
        "bedrock/claude-x": {"input_cost_per_token": 5e-06},
    })
    assert table["claude-x"]["input"] == 1.0


@pytest.fixture
def price_file(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(LIST), encoding="utf-8")
    return path


def test_builtin_table_wins_then_litellm_fills_the_gaps(price_file):
    provider = LiteLLMPricingProvider(path=price_file)
    assert provider.loaded
    assert provider.get_pricing("claude-sonnet-4-6")["input"] == 3.0  # built-in, verified
    assert provider.get_pricing("grok-4")["input"] == 3.0
    assert provider.get_pricing("groq/llama-3.3-70b-versatile")["output"] == 0.79
    assert provider.get_pricing("acme-llm-9000") is None


def test_only_https_downloads():
    with pytest.raises(ValueError):
        LiteLLMPricingProvider(url="http://example.com/prices.json")


def test_download_never_blocks_the_caller(monkeypatch):
    release = threading.Event()

    def slow_urlopen(url, timeout):
        release.wait(5)
        return io.BytesIO(json.dumps(LIST).encode())

    monkeypatch.setattr(providers.urllib.request, "urlopen", slow_urlopen)
    started = time.monotonic()
    provider = LiteLLMPricingProvider()
    assert time.monotonic() - started < 1.0
    assert provider.get_pricing("grok-4") is None  # not loaded yet: unpriced, not blocked
    assert provider.get_pricing("gpt-4o-mini") is not None  # built-in still answers
    release.set()
    assert provider.wait_until_loaded(5)
    assert provider.get_pricing("grok-4")["input"] == 3.0


def test_failed_download_keeps_the_builtin_table(monkeypatch):
    def failing_urlopen(url, timeout):
        raise OSError("offline")

    monkeypatch.setattr(providers.urllib.request, "urlopen", failing_urlopen)
    provider = LiteLLMPricingProvider()
    assert provider.wait_until_loaded(5) is False
    assert provider.get_pricing("gpt-4o-mini") is not None


def _check_prices():
    spec = importlib.util.spec_from_file_location("check_prices", os.path.join(ROOT, "scripts", "check_prices.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_prices_reports_differences_and_gaps():
    check = _check_prices()
    table = {
        "model-a": {"input": 1.0, "output": 2.0, "cache_read": 0.1},
        "model-b": {"input": 1.0, "output": 2.0, "cache_read": 1.0},
        "vendor/model-c": {"input": 1.0, "output": 2.0, "cache_read": 0.1},
        "local": {"input": 0.0, "output": 0.0, "cache_read": 0.0},
    }
    litellm = {
        "model-a": {"input_cost_per_token": 1e-06, "output_cost_per_token": 3e-06},
        # cache_read repeats the input rate on our side: no discount, not compared
        "model-b": {"input_cost_per_token": 1e-06, "output_cost_per_token": 2e-06,
                    "cache_read_input_token_cost": 1e-08},
    }
    differences, missing = check.compare(table, litellm)
    assert differences == [("model-a", "output", 2.0, 3.0)]
    assert missing == ["vendor/model-c"]


def test_check_prices_prefers_the_latest_alias():
    check = _check_prices()
    names = check.candidates("mistral/mistral-small")
    assert names.index("mistral/mistral-small-latest") < names.index("mistral/mistral-small")
