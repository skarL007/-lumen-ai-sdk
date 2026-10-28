"""
CostComputingSpanProcessor — computes USD cost per span on end.

Reads token usage (OTel GenAI ``gen_ai.usage.*``, falling back to
OpenInference ``llm.token_count.*``), looks up the pricing provider, and stores
the result in a thread-safe OrderedDict keyed by trace_id:span_id (GC-safe).

Each call is billed once: a span whose usage equals the sum of its children's
(a second instrumentation wrapping the same call, or an agent span carrying
totals) is stored with zero tokens and zero cost.

Must run AFTER TenantSpanProcessor in the processor chain.
"""
import logging
import threading
from collections import OrderedDict
from typing import Optional

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from lumen_ai._attributes import first_int, first_str, span_key
from lumen_ai.providers import BasePricingProvider
from lumen_ai.schema.semconv import (
    GenAIAttributes,
    OpenInferenceAttributes,
    compute_cost_usd,
    input_includes_cache,
)

logger = logging.getLogger(__name__)

_span_cost_map: OrderedDict[str, dict] = OrderedDict()
_map_lock = threading.Lock()
_MAX_ENTRIES = 50_000
_EVICT_BATCH = _MAX_ENTRIES // 10

# Usage reported under each parent span, summed from the children that ended
# first: (billable input, output, cache read, cache write).
_Usage = tuple[int, int, int, int]
_child_usage: OrderedDict[tuple[int, int], _Usage] = OrderedDict()
_usage_lock = threading.Lock()


def _add(a: _Usage, b: _Usage) -> _Usage:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3])


def _track_usage(span: ReadableSpan, usage: _Usage) -> bool:
    """
    Add this span's usage to its parent's tally; True if the span only repeats
    what its children already reported (so it must not be billed again).

    Spans without usage still pass their children's tally up, so an agent span
    two levels above the LLM call is matched too.
    """
    ctx = span.context
    if ctx is None or not isinstance(ctx.span_id, int):
        return False
    has_usage = any(usage)
    with _usage_lock:
        children = _child_usage.pop((ctx.trace_id, ctx.span_id), None)
        repeats = has_usage and children == usage
        if repeats or not has_usage:
            subtotal = children
        else:
            subtotal = _add(usage, children or (0, 0, 0, 0))
        parent = getattr(span, "parent", None)
        parent_id = getattr(parent, "span_id", None)
        if subtotal and isinstance(parent_id, int) and parent_id:
            key = (ctx.trace_id, parent_id)
            _child_usage[key] = _add(_child_usage.get(key, (0, 0, 0, 0)), subtotal)
            _child_usage.move_to_end(key)
            if len(_child_usage) > _MAX_ENTRIES:
                for _ in range(_EVICT_BATCH):
                    _child_usage.popitem(last=False)
    return repeats


# Models already warned about as unpriced. Bounded so span-supplied model ids
# cannot grow it without limit; past the cap the events_unpriced counter and the
# event's ``unpriced`` flag still report every case.
_warned_models: set[str] = set()
_warned_lock = threading.Lock()
_MAX_WARNED_MODELS = 256


def _warn_unpriced(model: str) -> None:
    """Log one WARNING per model id that reports tokens but has no price."""
    with _warned_lock:
        if model in _warned_models or len(_warned_models) >= _MAX_WARNED_MODELS:
            return
        _warned_models.add(model)
    logger.warning(
        "No price for model %r: its events are exported with cost_usd=0.0 and "
        "unpriced=True. Pass a pricing_provider that knows this model.",
        model[:128],
    )


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
    key = span_key(span)
    if not key:
        return {}
    with _map_lock:
        return dict(_span_cost_map.get(key, {}))


def pop_span_cost_data(span: ReadableSpan) -> dict:
    """
    Retrieve and REMOVE computed cost data for a span.

    The downstream normalizer calls this so each span's side-map entry is freed
    once consumed (bounds memory and prevents a later id-reuse stale read).
    """
    key = span_key(span)
    if not key:
        return {}
    with _map_lock:
        return _span_cost_map.pop(key, {})


class CostComputingSpanProcessor(SpanProcessor):
    """
    Enriches spans with USD cost based on token usage and model pricing.

    Args:
        pricing_provider: Implementation of BasePricingProvider.
    """

    def __init__(self, pricing_provider: BasePricingProvider, runtime=None) -> None:
        self._pricing = pricing_provider
        self._runtime = runtime

    def on_start(self, span, parent_context=None) -> None:
        pass

    def _compute_cost(
        self,
        pricing: dict,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_write: int = 0,
    ) -> float:
        # Single source of truth for the cost formula (see semconv.compute_cost_usd).
        return compute_cost_usd(pricing, input_tokens, output_tokens, cache_read, cache_write)

    def on_end(self, span: ReadableSpan) -> None:
        try:
            attrs = span.attributes or {}

            # OpenInference-only emitters (e.g. Arize Phoenix instrumentation)
            # report usage as llm.token_count.*; without this fallback their
            # spans would be priced at $0 even when the model is known.
            input_tokens = first_int(
                attrs,
                GenAIAttributes.USAGE_INPUT_TOKENS,
                OpenInferenceAttributes.TOKEN_COUNT_PROMPT,
            )
            output_tokens = first_int(
                attrs,
                GenAIAttributes.USAGE_OUTPUT_TOKENS,
                OpenInferenceAttributes.TOKEN_COUNT_COMPLETION,
            )
            cache_read = first_int(
                attrs, GenAIAttributes.USAGE_CACHE_READ, OpenInferenceAttributes.TOKEN_COUNT_CACHE_READ
            )
            cache_write = first_int(
                attrs,
                GenAIAttributes.USAGE_CACHE_CREATION,
                GenAIAttributes.USAGE_CACHE_WRITE,
                OpenInferenceAttributes.TOKEN_COUNT_CACHE_WRITE,
            )

            # Whether input_tokens already counts the cached tokens depends on the
            # emitter (and, for unknown ones, the provider); bill only the uncached
            # remainder at input rate so cached tokens are never charged twice.
            scope = getattr(getattr(span, "instrumentation_scope", None), "name", "")
            if not isinstance(scope, str):  # shims and test doubles
                scope = ""
            provider = first_str(
                attrs,
                GenAIAttributes.PROVIDER_NAME,
                GenAIAttributes.SYSTEM,
                OpenInferenceAttributes.PROVIDER,
                OpenInferenceAttributes.SYSTEM,
            )
            billable_input = input_tokens
            if input_includes_cache(scope, provider, input_tokens, cache_read, cache_write):
                billable_input = input_tokens - cache_read - cache_write

            repeats = _track_usage(span, (billable_input, output_tokens, cache_read, cache_write))

            # Cache-only spans (input==output==0, cache_read>0) still have real cost.
            if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
                return

            key = span_key(span)
            if not key:
                return

            model = first_str(
                attrs,
                GenAIAttributes.REQUEST_MODEL,
                GenAIAttributes.RESPONSE_MODEL,
                OpenInferenceAttributes.MODEL_NAME,
            )

            if repeats:
                _store_cost(key, {
                    "cost_usd": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "model": model,
                })
                logger.debug("Span %s repeats its children's usage; not billed again", span.name)
                return

            if not model:
                return

            try:
                pricing_provider = (
                    self._runtime.pricing_provider
                    if self._runtime is not None
                    else self._pricing
                )
                if pricing_provider is None:
                    return
                pricing = pricing_provider.get_pricing(model)
            except Exception:
                logger.debug("PricingProvider raised for model '%s'", model, exc_info=True)
                _warn_unpriced(model)
                return

            # The span used tokens but the model has no price: the normalizer
            # marks its event unpriced, so a $0 here is never mistaken for free.
            if not pricing:
                _warn_unpriced(model)
                return

            cost_usd = self._compute_cost(
                pricing, billable_input, output_tokens, cache_read, cache_write
            )

            _store_cost(key, {
                "cost_usd": cost_usd,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "model": model,
            })

            logger.debug(
                "Cost computed: model=%s in=%d out=%d cache_read=%d cache_write=%d cost=$%.6f",
                model, input_tokens, output_tokens, cache_read, cache_write, cost_usd,
            )

        except Exception:
            logger.warning("CostComputingSpanProcessor.on_end failed silently", exc_info=True)

    def shutdown(self) -> None:
        with _map_lock:
            _span_cost_map.clear()
        with _warned_lock:
            _warned_models.clear()
        with _usage_lock:
            _child_usage.clear()

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        return True
