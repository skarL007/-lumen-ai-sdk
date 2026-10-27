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
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from lumen_ai.processors.cost import CostComputingSpanProcessor
from lumen_ai.processors.normalizer import EventNormalizerProcessor
from lumen_ai.processors.tenant import TenantSpanProcessor
from lumen_ai.providers import BaseLumenAIExporter, BasePricingProvider
from lumen_ai.runtime import LumenRuntimeState

logger = logging.getLogger(__name__)


def _resolve_otlp_insecure(endpoint: Optional[str], override: Optional[bool]) -> bool:
    """
    Decide whether to use plaintext (insecure) gRPC for the OTLP exporter.

    An explicit ``override`` always wins. Otherwise transport is chosen from the
    endpoint: ``https://`` → TLS, ``http://`` → plaintext (the caller opted in),
    and a bare ``host:port`` uses plaintext only for loopback hosts and TLS for
    anything remote — so traces (model + span names) aren't sent in cleartext to
    a remote collector by default.
    """
    if override is not None:
        return override
    ep = (endpoint or "").strip()
    if ep.startswith("https://"):
        return False
    if ep.startswith("http://"):
        return True
    host = (urlparse("//" + ep).hostname or ep).lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")


def create_tracer_provider(
    service_name: str = "lumen-ai",
    otlp_endpoint: Optional[str] = None,
    default_tenant: str = "default",
    pricing_provider: Optional[BasePricingProvider] = None,
    exporter: Optional[BaseLumenAIExporter] = None,
    enable_otlp: bool = True,
    otlp_insecure: Optional[bool] = None,
    runtime: Optional[LumenRuntimeState] = None,
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
        otlp_insecure:     Use insecure (plaintext) gRPC for OTLP. Default None
                           auto-selects: plaintext for loopback / http:// only,
                           TLS for remote endpoints. Pass True/False to force it.

    Returns:
        Configured TracerProvider — set as global via
        ``trace.set_tracer_provider(provider)``.
    """
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    add_lumen_processors(
        provider,
        default_tenant=default_tenant,
        pricing_provider=pricing_provider,
        exporter=exporter,
        enable_otlp=enable_otlp,
        otlp_endpoint=otlp_endpoint,
        otlp_insecure=otlp_insecure,
        runtime=runtime,
    )
    return provider


def add_lumen_processors(
    provider: TracerProvider,
    default_tenant: str = "default",
    pricing_provider: Optional[BasePricingProvider] = None,
    exporter: Optional[BaseLumenAIExporter] = None,
    enable_otlp: bool = False,
    otlp_endpoint: Optional[str] = None,
    otlp_insecure: Optional[bool] = None,
    runtime: Optional[LumenRuntimeState] = None,
) -> None:
    """
    Attach the LumenAI processor chain to a TracerProvider.

    Used both for providers LumenAI creates and for an externally-installed
    provider that LumenAI adopts (see ``LumenAI.init``).
    """
    # 1. Tenant — must run first so downstream processors can read tenant_id
    if runtime is None:
        runtime = LumenRuntimeState(
            default_tenant=default_tenant,
            pricing_provider=pricing_provider,
            exporter=exporter,
        )

    provider.add_span_processor(TenantSpanProcessor(default_tenant=default_tenant, runtime=runtime))

    # 2. Cost — reads model + token attrs, writes cost to side-dict
    if pricing_provider:
        provider.add_span_processor(CostComputingSpanProcessor(pricing_provider, runtime=runtime))

    # 3. Normalizer — reads tenant + cost side-dicts, exports canonical event
    provider.add_span_processor(EventNormalizerProcessor(exporter=exporter, runtime=runtime))

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
            insecure = _resolve_otlp_insecure(endpoint, otlp_insecure)
            if insecure and not _resolve_otlp_insecure(endpoint, None):
                logger.warning(
                    "LumenAI OTLP sending PLAINTEXT telemetry to non-loopback %s "
                    "(otlp_insecure forced True). Use TLS in production.", endpoint,
                )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure))
            )
            logger.info("LumenAI OTLP exporter → %s (insecure=%s)", endpoint, insecure)
        except ImportError:
            logger.debug("opentelemetry-exporter-otlp not installed — OTLP skipped")


def get_lumen_tracer(name: str = "lumen-ai") -> trace.Tracer:
    """Return a tracer from the current global TracerProvider."""
    return trace.get_tracer(name)


# ---------------------------------------------------------------------------
# Backwards-compat aliases (remove in v1.0)
# ---------------------------------------------------------------------------
create_LumenAI_tracer_provider = create_tracer_provider
get_LumenAI_tracer = get_lumen_tracer
