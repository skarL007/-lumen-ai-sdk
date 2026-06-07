"""
Cross-tenant isolation tests.

  * #3  on_end resolved the LIVE ContextVar first, so a span that started under
        tenant A but ended while the ending thread/context held tenant B was
        re-attributed to B — leaking A's cost + metadata into B's stream and
        violating SECURITY.md. The tenant pinned at on_start must win at on_end.
  * #20 The normalizer must CONSUME (pop) the per-span side-map entries it reads,
        so they don't accumulate and so a later span that reuses a trace/span id
        can't read a stale tenant/cost.
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from lumen_ai.processors.tenant import (
    TenantSpanProcessor,
    get_span_tenant,
    lumen_tenant,
)
from lumen_ai.schema.semconv import GenAIAttributes, LumenAIAttributes


def _span(trace_id, span_id, tenant_attr=None, recording=True):
    span = MagicMock()
    span.context.trace_id = trace_id
    span.context.span_id = span_id
    span.name = "s"
    span.status = MagicMock(status_code=0)
    span.is_recording.return_value = recording
    attrs = {}
    if tenant_attr is not None:
        attrs[LumenAIAttributes.TENANT_ID] = tenant_attr
    span.attributes = attrs
    span.set_attribute = lambda k, v: attrs.__setitem__(k, v)
    return span


def test_start_pinned_tenant_survives_context_change():
    # Realistic: span starts under tenant-a, ends while the context holds tenant-b.
    proc = TenantSpanProcessor(default_tenant="default")
    span = _span(0x7E11, 0x7E12)
    with lumen_tenant("tenant-a"):
        proc.on_start(span)  # stamps the attribute from the start context
    assert span.attributes[LumenAIAttributes.TENANT_ID] == "tenant-a"
    with lumen_tenant("tenant-b"):
        proc.on_end(span)
    assert get_span_tenant(span) == "tenant-a"  # NOT tenant-b


def test_on_end_prefers_stamped_attribute_over_live_contextvar():
    proc = TenantSpanProcessor(default_tenant="default")
    span = _span(0x7E21, 0x7E22, tenant_attr="tenant-a")
    with lumen_tenant("tenant-b"):
        proc.on_end(span)
    assert get_span_tenant(span) == "tenant-a"


def test_on_end_falls_back_to_contextvar_when_unstamped():
    # Regression guard: when the span was never stamped, the ContextVar is used.
    proc = TenantSpanProcessor(default_tenant="default")
    span = _span(0x7E31, 0x7E32)
    with lumen_tenant("tenant-c"):
        proc.on_end(span)
    assert get_span_tenant(span) == "tenant-c"


def test_normalizer_consumes_side_map_entries():
    from lumen_ai.processors.cost import (
        CostComputingSpanProcessor,
        get_span_cost_data,
    )
    from lumen_ai.processors.normalizer import EventNormalizerProcessor
    from lumen_ai.providers import DefaultPricingProvider
    from lumen_ai.schema.semconv import PRICING_TABLE

    tenant_proc = TenantSpanProcessor(default_tenant="default")
    cost_proc = CostComputingSpanProcessor(DefaultPricingProvider(PRICING_TABLE))
    normalizer = EventNormalizerProcessor(exporter=None)

    span = _span(0x7E41, 0x7E42, tenant_attr="tenant-z")
    span.attributes[GenAIAttributes.REQUEST_MODEL] = "claude-haiku-4-5"
    span.attributes[GenAIAttributes.USAGE_INPUT_TOKENS] = 100
    span.attributes[GenAIAttributes.USAGE_OUTPUT_TOKENS] = 50
    span.start_time = 1_000_000
    span.end_time = 2_000_000

    tenant_proc.on_end(span)
    cost_proc.on_end(span)
    assert get_span_tenant(span) == "tenant-z"
    assert get_span_cost_data(span) != {}

    normalizer.on_end(span)
    # Entries are consumed once the event is emitted.
    assert get_span_tenant(span) == ""
    assert get_span_cost_data(span) == {}
