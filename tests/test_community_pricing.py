"""
CommunityPricingProvider fetch hardening.

  * #23 The provider pulled the BILLING pricing table from an arbitrary URL with
        no scheme allowlist (file://, http:// allowed) and no size cap — SSRF /
        local-file read / pricing poisoning. Only https is allowed by default.
  * #8  On a failed fetch _last_fetch was never advanced, so every subsequent
        span retried the 5s blocking urlopen (hot-path stall + thundering herd).
        The attempt time is now recorded regardless of outcome.
"""
import os
import sys
import urllib.request

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from lumen_ai.providers import CommunityPricingProvider


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, n=-1):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_https_pricing_is_fetched(monkeypatch):
    payload = b'{"x/y": {"input": 1.0, "output": 2.0, "cache_read": 0.0}}'
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=5: _FakeResp(payload))
    p = CommunityPricingProvider("https://example.com/pricing.json")
    assert p.get_pricing("x/y") == {"input": 1.0, "output": 2.0, "cache_read": 0.0}


def test_non_https_scheme_is_refused(monkeypatch):
    calls = []
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **k: calls.append(1) or _FakeResp(b"{}"),
    )
    p = CommunityPricingProvider(
        "file:///etc/passwd", fallback_table={"m": {"input": 0.0, "output": 0.0}}
    )
    assert p.get_pricing("m") == {"input": 0.0, "output": 0.0}  # fallback only
    assert calls == []  # the fetch was never attempted


def test_failed_fetch_backs_off_within_ttl(monkeypatch):
    calls = []

    def boom(url, timeout=5):
        calls.append(1)
        raise OSError("source down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    p = CommunityPricingProvider("https://example.com/pricing.json")
    p.get_pricing("m1")
    p.get_pricing("m2")
    assert len(calls) == 1  # second call backed off instead of re-blocking
