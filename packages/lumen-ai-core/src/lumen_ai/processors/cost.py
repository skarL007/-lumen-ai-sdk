"""
CostComputingSpanProcessor — computes USD cost per span on end.

Reads gen_ai.usage.* attributes, looks up pricing provider, stores
result in a thread-safe OrderedDict keyed by trace_id:span_id (GC-safe).

Must run AFTER TenantSpanProcessor in the processor chain.
"""
import logging
import threading
from collections import OrderedDict
from typing import Optional

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from lumen_ai.providers import BasePricingProvider
from lumen_ai.schema.semconv import (
    GenAIAttributes,
    OpenInferenceAttributes,
    compute_cost_usd,
)

logger = logging.getLogger(__name__)

_span_cost_map: OrderedDict[str, dict] = OrderedDict()
_map_lock = threading.Lock()
_MAX_ENTRIES = 50_000
_EVICT_BATCH = _MAX_ENTRIES // 10


def _span_key(span: ReadableSpan) -> str:
    ctx = span.context
    if ctx and ctx.trace_id and ctx.span_id:
        return f"{ctx.trace_id:032x}:{ctx.span_id:016x}"
    return ""


def _attribute_to_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _attribute_to_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _store_cost(key: str, data: dict) -> None:
    with _map_lock:
        if key in _span_cost_map:
            _span_cost_map.move_to_end(key)
        _span_cost_map[key] = data
        if len(_span_cost_map) > _MAX_ENTRIES:
            for _ in range(_EVICT_BATCH):
                _span_cost_map.popitem(last=False)


def get_span_cost_data(span: ReadableSpan) -> dict:
    """Retrieve computed cost data for a span (non-destructive read)."""
    key = _span_key(span)
    if not key:
        return {}
    with _map_lock:
        return dict(_span_cost_map.get(key, {}))


class CostComputingSpanProcessor(SpanProcessor):
    """
    Enriches spans with USD cost based on token usage and model pricing.

    Args:
        pricing_provider: Implementation of BasePricingProvider.
    """

    def __init__(self, pricing_provider: BasePricingProvider) -> None:
        self._pricing = pricing_provider

    def on_start(self, span, parent_context=None) -> None:
        pass

    def _compute_cost(
        self,
        pricing: dict,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
    ) -> float:
        # Single source of truth for the cost formula (see semconv.compute_cost_usd).
        return compute_cost_usd(pricing, input_tokens, output_tokens, cache_read)

    def on_end(self, span: ReadableSpan) -> None:
        try:
            attrs = span.attributes or {}

            model = (
                _attribute_to_str(attrs.get(GenAIAttributes.REQUEST_MODEL))
                or _attribute_to_str(attrs.get(GenAIAttributes.RESPONSE_MODEL))
                or _attribute_to_str(attrs.get(OpenInferenceAttributes.MODEL_NAME))
            )
            if not model:
                return

            try:
                pricing = self._pricing.get_pricing(model)
            except Exception:
                logger.debug("PricingProvider raised for model '%s'", model, exc_info=True)
                return

            if not pricing:
                logger.debug("No pricing found for model '%s' — cost skipped", model)
                return

            input_tokens = _attribute_to_int(attrs.get(GenAIAttributes.USAGE_INPUT_TOKENS))
            output_tokens = _attribute_to_int(attrs.get(GenAIAttributes.USAGE_OUTPUT_TOKENS))
            cache_read = _attribute_to_int(attrs.get(GenAIAttributes.USAGE_CACHE_READ))

            if input_tokens == 0 and output_tokens == 0:
                return

            cost_usd = self._compute_cost(pricing, input_tokens, output_tokens, cache_read)

            key = _span_key(span)
            if not key:
                return

            _store_cost(key, {
                "cost_usd": cost_usd,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read,
                "model": model,
            })

            logger.debug(
                "Cost computed: model=%s in=%d out=%d cache=%d cost=$%.6f",
                model, input_tokens, output_tokens, cache_read, cost_usd,
            )

        except Exception:
            logger.warning("CostComputingSpanProcessor.on_end failed silently", exc_info=True)

    def shutdown(self) -> None:
        with _map_lock:
            _span_cost_map.clear()

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        return True
