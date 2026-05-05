"""
LumenAI SDK — performance benchmarks.

Measures per-span overhead of the processor chain.
No external services required. Benchmarks are opt-in because host load varies
too much across local machines and CI runners.

Run locally:
    pytest tests/test_benchmark.py -v
"""
# ruff: noqa: E402, I001
import os
import sys
import time

import pytest

# Benchmarks are opt-in because thresholds vary with host load, Docker,
# antivirus, and runner hardware. Normal correctness gates should not fail
# because the machine is busy.
pytestmark = pytest.mark.skipif(
    os.environ.get("LUMEN_RUN_BENCHMARKS") != "1",
    reason="Benchmarks are opt-in: set LUMEN_RUN_BENCHMARKS=1 to run them",
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src"))

from lumen_ai.processors.cost import CostComputingSpanProcessor
from lumen_ai.processors.normalizer import EventNormalizerProcessor
from lumen_ai.processors.tenant import TenantSpanProcessor, _current_tenant, set_tenant_id
from lumen_ai.providers import BaseLumenAIExporter, DefaultPricingProvider
from lumen_ai.schema.semconv import GenAIAttributes, PRICING_TABLE


class NullExporter(BaseLumenAIExporter):
    """Exporter that discards events — measures pure processor overhead."""
    def __init__(self):
        self.count = 0

    def export(self, tenant_id: str, event: dict) -> None:
        self.count += 1


class FakeContext:
    def __init__(self, trace_id: int, span_id: int):
        self.trace_id = trace_id
        self.span_id = span_id


class FakeStatus:
    status_code = 0
    is_ok = True


class FakeSpan:
    def __init__(self, trace_id: int, span_id: int):
        self.context = FakeContext(trace_id, span_id)
        self.name = "anthropic.messages.create"
        self.start_time = 1_000_000_000
        self.end_time = 1_200_000_000
        self.status = FakeStatus()
        self.attributes = {
            GenAIAttributes.REQUEST_MODEL: "claude-sonnet-4-6",
            GenAIAttributes.USAGE_INPUT_TOKENS: 1500,
            GenAIAttributes.USAGE_OUTPUT_TOKENS: 800,
            GenAIAttributes.USAGE_CACHE_READ: 200,
        }

    def is_recording(self) -> bool:
        return True

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


def _make_span(trace_id: int, span_id: int) -> FakeSpan:
    """Create a lightweight LLM span with token attributes."""
    return FakeSpan(trace_id, span_id)


N_SPANS = 10_000
# Generous upper bound: host load still affects timings. The benchmark is a
# regression guard, not a production latency SLA.
MAX_US_PER_SPAN_SINGLE = 250
MAX_US_PER_SPAN_CHAIN = 750


# ---------------------------------------------------------------------------
# Benchmark 1: TenantSpanProcessor alone
# ---------------------------------------------------------------------------

def test_tenant_processor_overhead():
    """TenantSpanProcessor.on_end() overhead per span."""
    proc = TenantSpanProcessor(default_tenant="bench-tenant")
    token = set_tenant_id("bench-tenant")

    try:
        start = time.perf_counter()
        for i in range(N_SPANS):
            span = _make_span(trace_id=i, span_id=i)
            proc.on_end(span)
        elapsed = time.perf_counter() - start
    finally:
        _current_tenant.reset(token)

    us_per_span = (elapsed / N_SPANS) * 1_000_000
    print(f"\n  TenantProcessor: {us_per_span:.1f} us/span ({N_SPANS} spans in {elapsed:.3f}s)")
    assert us_per_span < MAX_US_PER_SPAN_SINGLE, f"Too slow: {us_per_span:.1f} us/span"
    proc.shutdown()


# ---------------------------------------------------------------------------
# Benchmark 2: CostComputingSpanProcessor alone
# ---------------------------------------------------------------------------

def test_cost_processor_overhead():
    """CostComputingSpanProcessor.on_end() overhead per span."""
    pricing = DefaultPricingProvider(PRICING_TABLE)
    proc = CostComputingSpanProcessor(pricing)

    start = time.perf_counter()
    for i in range(N_SPANS):
        span = _make_span(trace_id=0x10000 + i, span_id=i)
        proc.on_end(span)
    elapsed = time.perf_counter() - start

    us_per_span = (elapsed / N_SPANS) * 1_000_000
    print(f"\n  CostProcessor: {us_per_span:.1f} us/span ({N_SPANS} spans in {elapsed:.3f}s)")
    assert us_per_span < MAX_US_PER_SPAN_SINGLE, f"Too slow: {us_per_span:.1f} us/span"
    proc.shutdown()


# ---------------------------------------------------------------------------
# Benchmark 3: Full 3-processor chain + NullExporter
# ---------------------------------------------------------------------------

def test_full_chain_overhead():
    """Full pipeline (Tenant → Cost → Normalizer + NullExporter) per span."""
    pricing = DefaultPricingProvider(PRICING_TABLE)
    exporter = NullExporter()

    p1 = TenantSpanProcessor(default_tenant="bench")
    p2 = CostComputingSpanProcessor(pricing)
    p3 = EventNormalizerProcessor(exporter=exporter)

    token = set_tenant_id("bench-full")

    try:
        start = time.perf_counter()
        for i in range(N_SPANS):
            span = _make_span(trace_id=0x20000 + i, span_id=i)
            p1.on_end(span)
            p2.on_end(span)
            p3.on_end(span)
        elapsed = time.perf_counter() - start
    finally:
        _current_tenant.reset(token)

    us_per_span = (elapsed / N_SPANS) * 1_000_000
    print(f"\n  Full chain: {us_per_span:.1f} us/span ({N_SPANS} spans in {elapsed:.3f}s)")
    print(f"  Events exported: {exporter.count}")
    assert exporter.count == N_SPANS
    assert us_per_span < MAX_US_PER_SPAN_CHAIN, f"Too slow: {us_per_span:.1f} us/span"

    p1.shutdown()
    p2.shutdown()
    p3.shutdown()


# ---------------------------------------------------------------------------
# Benchmark 4: Pricing lookup speed (with partial match)
# ---------------------------------------------------------------------------

def test_pricing_lookup_speed():
    """DefaultPricingProvider.get_pricing() with partial model name."""
    provider = DefaultPricingProvider(PRICING_TABLE)

    models = [
        "claude-sonnet-4-6",            # exact match
        "anthropic/claude-sonnet-4-6",   # exact (aliased)
        "openrouter/anthropic/claude-sonnet-4-6",  # partial match
        "gpt-4o",                        # exact
        "unknown-model-xyz",             # miss
    ]

    start = time.perf_counter()
    for _ in range(N_SPANS):
        for model in models:
            provider.get_pricing(model)
    elapsed = time.perf_counter() - start

    lookups = N_SPANS * len(models)
    us_per_lookup = (elapsed / lookups) * 1_000_000
    print(f"\n  Pricing lookup: {us_per_lookup:.2f} us/lookup ({lookups} lookups in {elapsed:.3f}s)")
    assert us_per_lookup < 100, f"Too slow: {us_per_lookup:.2f} us/lookup"
