"""
LumenAI TracerProvider — configures OTel with the 3 custom processors.

Processor chain order (on_end runs in insertion order):
  1. TenantSpanProcessor   — tags every span with tenant_id
  2. CostComputingSpanProcessor — calculates USD cost from token counts
  3. EventNormalizerProcessor  — builds canonical event and exports it
  4. BatchSpanProcessor (OTLP) — forwards raw spans to collector
"""
import logging
import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from lumen_ai.processors.tenant import TenantSpanProcessor
from lumen_ai.processors.cost import CostComputingSpanProcessor
from lumen_ai.processors.normalizer import EventNormalizerProcessor
from lumen_ai.providers import BasePricingProvider, BaseLumenAIExporter

logger = logging.getLogger(__name__)


def create_tracer_provider(
    service_name: str = "lumen-ai",
    otlp_endpoint: Optional[str] = None,
    default_tenant: str = "default",
    pricing_provider: Optional[BasePricingProvider] = None,
    exporter: Optional[BaseLumenAIExporter] = None,
    enable_otlp: bool = True,
) -> TracerProvider:
    """
    Create a TracerProvider with the LumenAI processor chain.

    Args:
        service_name:      OTel resource service.name attribute.
        otlp_endpoint:     OTLP gRPC endpoint. Falls back to
                           OTEL_EXPORTER_OTLP_ENDPOINT env var,
                           then http://localhost:4317.
        default_tenant:    Fallback tenant_id when none is set in context.
        pricing_provider:  Provider for model pricing. If None, cost
                           computation is skipped.
        exporter:          Sink for normalized events (Redis, etc.).
                           If None, events are only logged at DEBUG level.
        enable_otlp:       Forward raw spans to an OTLP collector.
                           Silently skipped if the exporter package is
                           not installed.

    Returns:
        Configured TracerProvider — set as global via
        ``trace.set_tracer_provider(provider)``.
    """
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # 1. Tenant — must run first so downstream processors can read tenant_id
    provider.add_span_processor(TenantSpanProcessor(default_tenant=default_tenant))

    # 2. Cost — reads model + token attrs, writes cost to side-dict
    if pricing_provider:
        provider.add_span_processor(CostComputingSpanProcessor(pricing_provider))

    # 3. Normalizer — reads tenant + cost side-dicts, exports canonical event
    provider.add_span_processor(EventNormalizerProcessor(exporter=exporter))

    # 4. OTLP — forward raw OTel spans to Jaeger / Tempo / Phoenix
    if enable_otlp:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            endpoint = (
                otlp_endpoint
                or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
            )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
            )
            logger.info("LumenAI OTLP exporter → %s", endpoint)
        except ImportError:
            logger.debug("opentelemetry-exporter-otlp not installed — OTLP skipped")

    return provider


def get_lumen_tracer(name: str = "lumen-ai") -> trace.Tracer:
    """Return a tracer from the current global TracerProvider."""
    return trace.get_tracer(name)


# ---------------------------------------------------------------------------
# Backwards-compat aliases (remove in v1.0)
# ---------------------------------------------------------------------------
create_LumenAI_tracer_provider = create_tracer_provider
get_LumenAI_tracer = get_lumen_tracer
