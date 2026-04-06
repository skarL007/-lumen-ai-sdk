"""
LumenAI SDK — one-line bootstrap for AI observability.

Quickstart::

    from lumen_ai import LumenAI

    LumenAI.init(
        service_name="my-agent",
        redis_url="redis://localhost:6379/0",
        default_tenant="anonymous",
    )
"""
import logging
from typing import List, Optional

from opentelemetry import trace

from lumen_ai.tracer import create_tracer_provider
from lumen_ai.providers import (
    BaseLumenAIExporter,
    BasePricingProvider,
    DefaultPricingProvider,
    RedisExporter,
)
from lumen_ai.schema.semconv import PRICING_TABLE

logger = logging.getLogger(__name__)


class LumenAI:
    """
    Central SDK entry point — process-level singleton.

    Call ``LumenAI.init()`` once at application startup.
    All subsequent calls are no-ops (a warning is logged).
    """

    _initialized: bool = False
    _provider = None
    _exporter: Optional[BaseLumenAIExporter] = None
    _instrumentors: list = []

    @classmethod
    def init(
        cls,
        service_name: str = "lumen-ai",
        otlp_endpoint: Optional[str] = None,
        redis_url: Optional[str] = None,
        default_tenant: str = "default",
        enable_otlp: bool = False,
        otlp_insecure: bool = True,
        pricing_provider: Optional[BasePricingProvider] = None,
        exporter: Optional[BaseLumenAIExporter] = None,
        instrumentors: Optional[List] = None,
    ) -> None:
        """
        Initialize LumenAI observability.

        Args:
            service_name:      OTel service name tag.
            otlp_endpoint:     OTLP gRPC endpoint for raw span export.
            redis_url:         Shortcut — creates a RedisExporter automatically.
            default_tenant:    Fallback tenant_id for spans with no context set.
            enable_otlp:       Forward spans to OTLP collector (default: False).
            otlp_insecure:     Use insecure (plaintext) gRPC for OTLP.
                               Set to False for TLS in production.
            pricing_provider:  Custom pricing source. Defaults to built-in table.
            exporter:          Custom event sink. Defaults to RedisExporter when
                               redis_url is supplied.
            instrumentors:     List of BaseInstrumentor instances to activate
                               (e.g. CeleryInstrumentor).
        """
        if cls._initialized:
            logger.warning("LumenAI.init() called more than once — ignoring")
            return

        # Validate configuration
        if not default_tenant or not default_tenant.strip():
            raise ValueError("default_tenant must be a non-empty string")
        if redis_url and exporter:
            raise ValueError(
                "Cannot pass both redis_url and exporter — choose one. "
                "redis_url creates a RedisExporter automatically."
            )
        if redis_url and not redis_url.startswith(("redis://", "rediss://")):
            raise ValueError(
                f"Invalid redis_url '{redis_url}': must start with redis:// or rediss://"
            )
        if enable_otlp and not otlp_endpoint:
            logger.warning(
                "enable_otlp=True but no otlp_endpoint — "
                "will use OTEL_EXPORTER_OTLP_ENDPOINT env var or localhost:4317"
            )

        logger.info("LumenAI initializing (service=%s)", service_name)

        # Pricing
        if pricing_provider is None:
            pricing_provider = DefaultPricingProvider(PRICING_TABLE)

        # Exporter
        if exporter is None and redis_url:
            exporter = RedisExporter(redis_url)
        cls._exporter = exporter

        # Tracer provider
        cls._provider = create_tracer_provider(
            service_name=service_name,
            otlp_endpoint=otlp_endpoint,
            default_tenant=default_tenant,
            pricing_provider=pricing_provider,
            exporter=exporter,
            enable_otlp=enable_otlp,
            otlp_insecure=otlp_insecure,
        )
        trace.set_tracer_provider(cls._provider)

        # Instrumentors (Celery, OpenLIT, etc.)
        for inst in instrumentors or []:
            try:
                inst.instrument(tracer_provider=cls._provider)
                cls._instrumentors.append(inst)
                logger.info("Instrumentor activated: %s", type(inst).__name__)
            except Exception:
                logger.error(
                    "Failed to activate instrumentor %s",
                    type(inst).__name__,
                    exc_info=True,
                )

        cls._initialized = True
        logger.info("LumenAI ready")

    @classmethod
    def shutdown(cls) -> None:
        """Flush pending spans and shut down all components gracefully."""
        if cls._provider:
            cls._provider.shutdown()
        for inst in cls._instrumentors:
            try:
                inst.uninstrument()
            except Exception:
                pass
        if cls._exporter:
            cls._exporter.shutdown()
        cls._initialized = False
        cls._instrumentors.clear()
        logger.info("LumenAI shut down")

    @classmethod
    def is_initialized(cls) -> bool:
        """Return True if LumenAI.init() has been called."""
        return cls._initialized
