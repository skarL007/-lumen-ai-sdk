"""
TenantSpanProcessor — ensures every span carries tenant_id.

Resolution order:
  1. ContextVar set via set_tenant_id() — preferred (middleware / FastAPI Depends)
  2. Span attribute already set by caller
  3. default_tenant passed at processor construction

Side-dict (OrderedDict) keyed by trace_id:span_id is GC-safe and
non-destructive — downstream processors can read tenant without
consuming the data.

Public API
----------
set_tenant_id(tenant_id)        Set tenant for current async context.
get_tenant_id()                 Read current tenant from context.
lumen_tenant(tenant_id)         Context manager — resets on exit.
get_span_tenant(span)           Read tenant written by processor.
"""
import logging
import threading
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Generator, Optional

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from lumen_ai.schema.semconv import LumenAIAttributes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ContextVar — propagates tenant across async/threading boundaries
# ---------------------------------------------------------------------------
_current_tenant: ContextVar[str] = ContextVar("lumenai_tenant_id", default="")

# ---------------------------------------------------------------------------
# Side storage — OrderedDict gives O(1) LRU eviction (move_to_end)
# ---------------------------------------------------------------------------
_span_tenant_map: OrderedDict[str, str] = OrderedDict()
_map_lock = threading.Lock()
_MAX_ENTRIES = 50_000
_EVICT_BATCH = _MAX_ENTRIES // 10  # evict 10 % at a time


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def set_tenant_id(tenant_id: str) -> Token:
    """
    Set the tenant for the current async context.

    Returns the ContextVar Token so callers can reset() if needed.

    Usage (FastAPI / middleware)::

        token = set_tenant_id(request.headers["X-Tenant-ID"])
        try:
            ...
        finally:
            _current_tenant.reset(token)
    """
    if not isinstance(tenant_id, str):
        tenant_id = str(tenant_id)
    return _current_tenant.set(tenant_id.strip())


# Keep old name as an alias for backwards compatibility
set_current_tenant = set_tenant_id


def get_tenant_id() -> str:
    """Return the tenant_id for the current context, or empty string."""
    return _current_tenant.get()


# Keep old name as an alias
get_current_tenant = get_tenant_id


def clear_tenant_id() -> None:
    """Reset tenant to empty string in the current context."""
    _current_tenant.set("")


@contextmanager
def lumen_tenant(tenant_id: str) -> Generator[None, None, None]:
    """
    Context manager that sets tenant_id and resets it on exit.

    Usage::

        with lumen_tenant("client-abc"):
            response = call_openai(prompt)   # span tagged automatically
    """
    token = set_tenant_id(tenant_id)
    try:
        yield
    finally:
        _current_tenant.reset(token)


def get_span_tenant(span: ReadableSpan) -> str:
    """
    Retrieve the tenant_id recorded for a span.

    Non-destructive — safe to call multiple times.
    Returns empty string if span has no context or tenant was not recorded.
    """
    key = _span_key(span)
    if not key:
        return ""
    with _map_lock:
        return _span_tenant_map.get(key, "")


def pop_span_tenant(span: ReadableSpan) -> str:
    """
    Retrieve and REMOVE the tenant recorded for a span.

    The downstream normalizer calls this so each span's side-map entry is freed
    once consumed (bounds memory and prevents a later id-reuse stale read).
    """
    key = _span_key(span)
    if not key:
        return ""
    with _map_lock:
        return _span_tenant_map.pop(key, "")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _span_key(span: ReadableSpan) -> str:
    """Stable, collision-resistant key from OTel IDs."""
    ctx = span.context
    if ctx and ctx.trace_id and ctx.span_id:
        return f"{ctx.trace_id:032x}:{ctx.span_id:016x}"
    return ""


def _attribute_to_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    return ""


def _store_tenant(key: str, tenant: str) -> None:
    """Thread-safe write with LRU eviction."""
    with _map_lock:
        if key in _span_tenant_map:
            _span_tenant_map.move_to_end(key)
        _span_tenant_map[key] = tenant
        if len(_span_tenant_map) > _MAX_ENTRIES:
            for _ in range(_EVICT_BATCH):
                _span_tenant_map.popitem(last=False)


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------

class TenantSpanProcessor(SpanProcessor):
    """
    Enriches every span with a tenant_id attribute.

    Attach early in the processor chain so downstream processors
    (CostComputingSpanProcessor, EventNormalizerProcessor) can read it.

    Args:
        default_tenant: Fallback used when no tenant is found in context
                        or span attributes. Defaults to "default".
    """

    def __init__(self, default_tenant: str = "default") -> None:
        if not default_tenant or not default_tenant.strip():
            raise ValueError("default_tenant must be a non-empty string")
        self._default_tenant = default_tenant.strip()

    def on_start(self, span, parent_context=None) -> None:
        """Tag span at start so child spans inherit the tenant attribute."""
        try:
            if not getattr(span, "is_recording", lambda: True)():
                return
            tenant = get_tenant_id() or self._default_tenant
            span.set_attribute(LumenAIAttributes.TENANT_ID, tenant)
        except Exception:
            logger.debug("TenantSpanProcessor.on_start failed silently", exc_info=True)

    def on_end(self, span: ReadableSpan) -> None:
        """Persist final tenant_id to side-dict for downstream processors."""
        try:
            attrs = span.attributes or {}
            # The tenant stamped on the span at on_start (from the start context)
            # is authoritative; the live ContextVar is only a fallback for spans
            # that were never stamped. Reading the ContextVar first would let a
            # span that ENDS in another tenant's context be re-attributed to it
            # (cross-tenant cost/metadata leak — see SECURITY.md).
            tenant = (
                _attribute_to_str(attrs.get(LumenAIAttributes.TENANT_ID, ""))
                or get_tenant_id()
                or self._default_tenant
            )

            if not attrs.get(LumenAIAttributes.TENANT_ID):
                logger.debug(
                    "Span '%s' has no tenant_id — tagged as '%s'",
                    span.name,
                    tenant,
                )

            key = _span_key(span)
            if key:
                _store_tenant(key, tenant)

        except Exception:
            logger.warning("TenantSpanProcessor.on_end failed silently", exc_info=True)

    def shutdown(self) -> None:
        with _map_lock:
            _span_tenant_map.clear()

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        return True
