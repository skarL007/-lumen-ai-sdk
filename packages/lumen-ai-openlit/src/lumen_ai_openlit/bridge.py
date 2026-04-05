"""
OpenLIT Bridge — connects OpenLIT auto-instrumentation to LumenAI Master schema.

OpenLIT auto-instruments 60+ LLM providers (OpenAI, Anthropic, Ollama, etc.)
generating OTel spans. This bridge normalizes those spans into LumenAI schema.

Usage:
    from LumenAI_openlit import OpenLITBridge
    LumenAI.init(instrumentors=[OpenLITBridge()])
"""
import logging

from LumenAI.sdk import BaseInstrumentor

logger = logging.getLogger(__name__)


class OpenLITBridge(BaseInstrumentor):
    """
    Bridge between OpenLIT auto-instrumentation and LumenAI Master.

    OpenLIT generates standard OTel spans with gen_ai.* attributes.
    This bridge simply initializes OpenLIT with the LumenAI TracerProvider,
    so all LLM spans flow through LumenAI processors (Cost → Tenant → Normalizer).
    """

    def __init__(
        self,
        collect_gpu_stats: bool = False,
        disable_batch: bool = False,
        pricing_json: str | None = None,
    ):
        self._collect_gpu_stats = collect_gpu_stats
        self._disable_batch = disable_batch
        self._pricing_json = pricing_json
        self._initialized = False

    def instrumentation_dependencies(self) -> list[str]:
        return ["openlit >= 1.0"]

    def _instrument(self, tracer_provider=None, **kwargs):
        if self._initialized:
            return

        try:
            import openlit
            import inspect

            # Build init kwargs defensively — openlit.init() API may vary by version
            init_kwargs: dict = {}

            # Check which params openlit.init() actually accepts
            sig = inspect.signature(openlit.init)
            params = set(sig.parameters.keys())

            if "tracer_provider" in params and tracer_provider:
                init_kwargs["tracer_provider"] = tracer_provider
            if "collect_gpu_stats" in params:
                init_kwargs["collect_gpu_stats"] = self._collect_gpu_stats
            if "disable_batch" in params:
                init_kwargs["disable_batch"] = self._disable_batch
            if "pricing_json" in params and self._pricing_json:
                init_kwargs["pricing_json"] = self._pricing_json

            openlit.init(**init_kwargs)

            self._initialized = True
            logger.info(
                "OpenLITBridge: auto-instrumentation active (params: %s)",
                list(init_kwargs.keys()),
            )

        except ImportError:
            logger.warning(
                "OpenLIT not installed — LLM auto-instrumentation disabled. "
                "Install with: pip install openlit"
            )
        except Exception as e:
            logger.error("OpenLITBridge initialization failed: %s", e)

    def _uninstrument(self, **kwargs):
        # OpenLIT doesn't have a clean uninstrument API
        self._initialized = False
        logger.info("OpenLITBridge: deactivated (note: monkey-patches persist until restart)")
