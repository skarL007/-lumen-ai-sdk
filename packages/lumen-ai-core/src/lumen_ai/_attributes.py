"""
Span attribute helpers shared by the LumenAI processors.

OTel attribute values are loosely typed (str / int / float / bool / sequences),
and different emitters (OTel GenAI, OpenInference, hand-written spans) put the
same fact under different keys. These helpers coerce values defensively and
resolve the first non-empty key, so every processor reads spans the same way.
"""
from typing import Mapping, Optional

from opentelemetry.sdk.trace import ReadableSpan


def span_key(span: ReadableSpan) -> str:
    """Stable, collision-resistant side-map key from OTel IDs (empty if no context)."""
    ctx = span.context
    if ctx and ctx.trace_id and ctx.span_id:
        return f"{ctx.trace_id:032x}:{ctx.span_id:016x}"
    return ""


def attr_str(value: object) -> str:
    """Coerce a scalar attribute value to a stripped string; anything else → ``""``."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    return ""


def attr_int(value: object) -> int:
    """Coerce a scalar attribute value to ``int``; unparseable values → ``0``."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def first_str(attrs: Optional[Mapping[str, object]], *keys: str) -> str:
    """Return the first non-empty string value among ``keys``."""
    if not attrs:
        return ""
    for key in keys:
        value = attr_str(attrs.get(key))
        if value:
            return value
    return ""


def first_int(attrs: Optional[Mapping[str, object]], *keys: str) -> int:
    """Return the first non-zero integer value among ``keys``."""
    if not attrs:
        return 0
    for key in keys:
        value = attr_int(attrs.get(key))
        if value:
            return value
    return 0
