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

from lumen_ai.providers import (
    BaseLumenAIExporter,
    BasePricingProvider,
    DefaultPricingProvider,
    RedisExporter,
)
from lumen_ai.runtime import LumenRuntimeState
from lumen_ai.schema.semconv import PRICING_TABLE
from lumen_ai.tracer import add_lumen_processors, create_tracer_provider

logger = logging.getLogger(__name__)

# Marks a TracerProvider that already carries the LumenAI processor chain, so
# adopting the same provider twice never double-registers the processors.
_ATTACHED_FLAG = "_lumen_ai_attached"
_RUNTIME_ATTR = "_lumen_ai_runtime"


def _reset_global_tracer_provider() -> None:
    """
    Best-effort reset of OTel's set-once global TracerProvider so a later
    ``LumenAI.init()`` can install a fresh provider after ``shutdown()``.

    OTel's ``set_tracer_provider`` fires only once; without this reset a re-init
    would be ignored and telemetry would keep flowing to the shut-down provider.
    Touches OTel internals and degrades gracefully if they ever change.
    """
    try:
        from opentelemetry.util._once import Once
        trace._TRACER_PROVIDER_SET_ONCE = Once()
        trace._TRACER_PROVIDER = None
    except Exception:
        logger.debug("Could not reset global TracerProvider for re-init", exc_info=True)


class LumenAI:
    """
    Central SDK entry point — process-level singleton.

    Call ``LumenAI.init()`` once at application startup.
    All subsequent calls are no-ops (a warning is logged).
    """

    _initialized: bool = False
    _provider = None
    _exporter: Optional[BaseLumenAIExporter] = None
    _runtime: Optional[LumenRuntimeState] = None
    _instrumentors: list = []
    _owns_provider: bool = False

    @classmethod
    def init(
        cls,
        service_name: str = "lumen-ai",
        otlp_endpoint: Optional[str] = None,
        redis_url: Optional[str] = None,
        default_tenant: str = "default",
        enable_otlp: bool = False,
        otlp_insecure: Optional[bool] = None,
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
            otlp_insecure:     Use insecure (plaintext) gRPC for OTLP. Default
                               None auto-selects plaintext for loopback / http://
                               endpoints and TLS for remote ones; pass True/False
                               to force it.
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
        runtime = LumenRuntimeState(
            default_tenant=default_tenant,
            pricing_provider=pricing_provider,
            exporter=exporter,
        )

        # Tracer provider. OTel's set_tracer_provider is set-once, so if a real
        # SDK provider is already installed (ours from a prior init, or another
        # library's) we ADOPT it — attaching our processors — rather than setting
        # a new global that OTel would ignore (which would silently drop events).
        from opentelemetry.sdk.trace import TracerProvider

        current = trace.get_tracer_provider()
        if isinstance(current, TracerProvider):
            if not getattr(current, _ATTACHED_FLAG, False):
                add_lumen_processors(
                    current,
                    default_tenant=default_tenant,
                    pricing_provider=pricing_provider,
                    exporter=exporter,
                    enable_otlp=enable_otlp,
                    otlp_endpoint=otlp_endpoint,
                    otlp_insecure=otlp_insecure,
                    runtime=runtime,
                )
                setattr(current, _ATTACHED_FLAG, True)
                setattr(current, _RUNTIME_ATTR, runtime)
                logger.info("LumenAI adopted the already-installed TracerProvider")
            else:
                logger.warning(
                    "LumenAI processors already attached to the active provider — skipping"
                )
            attached_runtime = getattr(current, _RUNTIME_ATTR, None)
            if isinstance(attached_runtime, LumenRuntimeState):
                attached_runtime.configure(
                    default_tenant=default_tenant,
                    pricing_provider=pricing_provider,
                    exporter=exporter,
                )
                runtime = attached_runtime
            cls._provider = current
            cls._owns_provider = False
        else:
            cls._provider = create_tracer_provider(
                service_name=service_name,
                otlp_endpoint=otlp_endpoint,
                default_tenant=default_tenant,
                pricing_provider=pricing_provider,
                exporter=exporter,
                enable_otlp=enable_otlp,
                otlp_insecure=otlp_insecure,
                runtime=runtime,
            )
            setattr(cls._provider, _ATTACHED_FLAG, True)
            setattr(cls._provider, _RUNTIME_ATTR, runtime)
            trace.set_tracer_provider(cls._provider)
            cls._owns_provider = True
        cls._runtime = runtime

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
        if not cls._initialized:
            return
        for inst in cls._instrumentors:
            try:
                inst.uninstrument()
            except Exception:
                pass
        if cls._owns_provider and cls._provider is not None:
            # We installed this provider — shut it down and free the OTel global
            # so a later init() can install a fresh, live provider.
            try:
                cls._provider.shutdown()
            except Exception:
                logger.debug("TracerProvider shutdown raised", exc_info=True)
            _reset_global_tracer_provider()
        elif cls._provider is not None:
            # Adopted an external provider — don't tear it down, just flush.
            try:
                cls._provider.force_flush()
            except Exception:
                logger.debug("TracerProvider force_flush raised", exc_info=True)
        try:
            if cls._runtime is not None:
                cls._runtime.shutdown_exporter()
            elif cls._exporter:
                cls._exporter.shutdown()
        finally:
            cls._initialized = False
            cls._owns_provider = False
            cls._provider = None
            cls._exporter = None
            cls._runtime = None
            cls._instrumentors = []
            logger.info("LumenAI shut down")

    @classmethod
    def is_initialized(cls) -> bool:
        """Return True if LumenAI.init() has been called."""
        return cls._initialized
