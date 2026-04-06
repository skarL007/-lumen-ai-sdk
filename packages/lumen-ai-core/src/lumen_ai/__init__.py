"""
LumenAI Master — Multi-Agent Observability SDK.

Usage:
    from lumen_ai import LumenAI
    LumenAI.init(service_name="my-app", instrumentors=[...])
"""
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor

from lumen_ai.sdk import LumenAI

__all__ = ["LumenAI", "BaseInstrumentor"]
__version__ = "0.1.1"
