"""
set_tenant_id sanitizes the tenant id so a hostile/malformed value (newlines,
control chars, absurd length) cannot corrupt Redis stream keys or log lines.
Valid tenant ids are passed through unchanged (attribution is preserved).
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from lumen_ai.processors.tenant import (
    TenantSpanProcessor,
    get_tenant_id,
    get_span_tenant,
    reset_tenant_id,
    set_tenant_id,
)


def test_strips_control_chars_and_newlines():
    token = set_tenant_id("ac\nme\t")  # internal newline + trailing tab
    try:
        assert get_tenant_id() == "acme"
    finally:
        reset_tenant_id(token)


def test_caps_length():
    token = set_tenant_id("x" * 500)
    try:
        assert len(get_tenant_id()) == 128
    finally:
        reset_tenant_id(token)


def test_valid_tenant_passes_through_unchanged():
    token = set_tenant_id("acme-corp_123:eu")
    try:
        assert get_tenant_id() == "acme-corp_123:eu"
    finally:
        reset_tenant_id(token)


def test_existing_whitespace_strip_still_works():
    token = set_tenant_id("  spaces  ")
    try:
        assert get_tenant_id() == "spaces"
    finally:
        reset_tenant_id(token)


def test_public_reset_tenant_id_restores_previous_context():
    outer = set_tenant_id("outer")
    inner = set_tenant_id("inner")
    try:
        assert get_tenant_id() == "inner"
        reset_tenant_id(inner)
        assert get_tenant_id() == "outer"
    finally:
        reset_tenant_id(outer)


def test_span_attribute_tenant_is_sanitized():
    from unittest.mock import MagicMock

    from lumen_ai.schema.semconv import LumenAIAttributes

    span = MagicMock()
    span.context.trace_id = 0xAA01
    span.context.span_id = 0xAA02
    span.name = "tenant-attr"
    span.attributes = {LumenAIAttributes.TENANT_ID: "ac\nme\t"}

    proc = TenantSpanProcessor(default_tenant="default")
    proc.on_end(span)

    assert get_span_tenant(span) == "acme"
