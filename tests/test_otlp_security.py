"""
OTLP transport security. The exporter defaulted to insecure=True, sending traces
(incl. model + span names) as plaintext gRPC even to a REMOTE collector. The
resolver now defaults plaintext only for loopback / explicit http:// endpoints and
TLS for anything remote, while honoring an explicit override.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from lumen_ai.tracer import _resolve_otlp_insecure


def test_loopback_endpoints_default_to_plaintext():
    assert _resolve_otlp_insecure("http://localhost:4317", None) is True
    assert _resolve_otlp_insecure("localhost:4317", None) is True
    assert _resolve_otlp_insecure("127.0.0.1:4317", None) is True
    assert _resolve_otlp_insecure("[::1]:4317", None) is True


def test_remote_bare_endpoint_defaults_to_tls():
    assert _resolve_otlp_insecure("collector.example.com:4317", None) is False
    assert _resolve_otlp_insecure("otel.prod.internal:4317", None) is False


def test_scheme_is_explicit_intent():
    assert _resolve_otlp_insecure("https://collector:4317", None) is False
    assert _resolve_otlp_insecure("http://collector:4317", None) is True  # user opted into plaintext


def test_explicit_override_wins():
    assert _resolve_otlp_insecure("collector.example.com:4317", True) is True
    assert _resolve_otlp_insecure("http://localhost:4317", False) is False
