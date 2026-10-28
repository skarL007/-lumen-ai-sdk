"""
LumenAI against the spans real instrumentation libraries emit.

Each case runs a real OpenAI or Anthropic SDK call, with a real instrumentor
installed, against a mocked HTTP transport (``_instrumented_call.py``), and
checks the cost LumenAI exports. The emitters disagree on whether the input
token count includes cached tokens, and on what to call cache writes; these
cases pin the cost for each of them. A case is skipped when its libraries are
not installed (``pip install openai anthropic openinference-instrumentation-openai
opentelemetry-instrumentation-openai opentelemetry-instrumentation-anthropic openlit``).

Workload: 1,000 cached and 200 uncached input tokens, 300 output tokens.
  gpt-4o-mini:       200*0.15 + 1000*0.075 + 300*0.60  per 1M = $0.000285
  claude-sonnet-4-6: 200*3    + 1000*0.30  + 300*15    per 1M = $0.0054
  ... plus 500 cache-write tokens at $3.75/M                     = $0.007275
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

HELPER = os.path.join(os.path.dirname(__file__), "_instrumented_call.py")

OPENAI_COST = 0.000285
ANTHROPIC_COST = 0.0054
ANTHROPIC_WRITE_COST = 0.007275


def _installed(*modules):
    for module in modules:
        try:
            if importlib.util.find_spec(module) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def _run(sdk, instrumentation, *extra):
    result = subprocess.run(
        [sys.executable, HELPER, sdk, instrumentation, *extra],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 3:
        pytest.skip(result.stdout.strip().splitlines()[-1])
    assert result.returncode == 0, result.stderr[-2000:]
    prefix = "LUMEN_EVENT "
    return [json.loads(line[len(prefix):]) for line in result.stdout.splitlines() if line.startswith(prefix)]


def _billed(events):
    """The events that carry the call's cost (a repeated outer span is zeroed)."""
    return [e for e in events if e["cost_usd"] > 0]


CASES = [
    # (sdk, instrumentation, modules needed, extra args, expected cost)
    ("openai", "openinference", ("openai", "openinference.instrumentation.openai"), (), OPENAI_COST),
    ("openai", "traceloop", ("openai", "opentelemetry.instrumentation.openai"), (), OPENAI_COST),
    ("openai", "openlit", ("openai", "openlit"), (), OPENAI_COST),
    ("anthropic", "traceloop", ("anthropic", "opentelemetry.instrumentation.anthropic"), (), ANTHROPIC_COST),
    ("anthropic", "traceloop", ("anthropic", "opentelemetry.instrumentation.anthropic"),
     ("cache_write",), ANTHROPIC_WRITE_COST),
    ("anthropic", "openlit", ("anthropic", "openlit"), (), ANTHROPIC_COST),
    ("anthropic", "openlit", ("anthropic", "openlit"), ("cache_write",), ANTHROPIC_WRITE_COST),
    ("anthropic", "openinference", ("anthropic", "openinference.instrumentation.anthropic"),
     (), ANTHROPIC_COST),
    ("anthropic", "openinference", ("anthropic", "openinference.instrumentation.anthropic"),
     ("cache_write",), ANTHROPIC_WRITE_COST),
]


@pytest.mark.parametrize(
    "sdk, instrumentation, modules, extra, expected",
    CASES,
    ids=[f"{c[0]}-{c[1]}{'-cache_write' if c[3] else ''}" for c in CASES],
)
def test_real_instrumentation_is_billed_once_at_the_right_cost(sdk, instrumentation, modules, extra, expected):
    if not _installed(*modules):
        pytest.skip(f"needs {', '.join(modules)}")
    events = _run(sdk, instrumentation, *extra)

    billed = _billed(events)
    assert len(billed) == 1, events  # one call, billed once even if two layers saw it
    assert billed[0]["cost_usd"] == pytest.approx(expected)
    assert billed[0]["tenant_id"] == "acme"
    assert billed[0]["cache_read_tokens"] == 1000
    assert not any(e["unpriced"] for e in events)


def test_official_otel_openai_instrumentation_without_cache_counts_bills_full_input():
    # opentelemetry-instrumentation-openai-v2 does not report cached tokens, so
    # LumenAI cannot discount them: the cost is the uncached price, an upper bound.
    if not _installed("openai", "opentelemetry.instrumentation.openai_v2"):
        pytest.skip("needs opentelemetry-instrumentation-openai-v2")
    events = _run("openai", "otel-v2")

    billed = _billed(events)
    assert len(billed) == 1
    assert billed[0]["cache_read_tokens"] == 0
    assert billed[0]["cost_usd"] == pytest.approx(1200 * 0.15 / 1e6 + 300 * 0.60 / 1e6)
