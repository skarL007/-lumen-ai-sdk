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
    _current_tenant,
    get_tenant_id,
    set_tenant_id,
)


def test_strips_control_chars_and_newlines():
    token = set_tenant_id("ac\nme\t")  # internal newline + trailing tab
    try:
        assert get_tenant_id() == "acme"
    finally:
        _current_tenant.reset(token)


def test_caps_length():
    token = set_tenant_id("x" * 500)
    try:
        assert len(get_tenant_id()) == 128
    finally:
        _current_tenant.reset(token)


def test_valid_tenant_passes_through_unchanged():
    token = set_tenant_id("acme-corp_123:eu")
    try:
        assert get_tenant_id() == "acme-corp_123:eu"
    finally:
        _current_tenant.reset(token)


def test_existing_whitespace_strip_still_works():
    token = set_tenant_id("  spaces  ")
    try:
        assert get_tenant_id() == "spaces"
    finally:
        _current_tenant.reset(token)
