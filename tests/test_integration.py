"""
LumenAI SDK — integration tests with real Redis.

Requires a running Redis instance on localhost:6379.
Skipped automatically if Redis is unavailable.

Run with:
    pytest tests/test_integration.py -v
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src"))

import pytest

# ---------------------------------------------------------------------------
# Skip guard — all tests in this module require Redis
# ---------------------------------------------------------------------------

def _redis_available() -> bool:
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=1)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(), reason="Redis not running on localhost:6379"
)

REDIS_URL = "redis://localhost:6379/0"
TEST_PREFIX = "lumenai_test"


@pytest.fixture(autouse=True)
def _cleanup_streams():
    """Delete test streams before and after each test."""
    import redis
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    yield
    # Cleanup: delete all test streams
    for key in r.keys(f"{TEST_PREFIX}:*"):
        r.delete(key)
    r.close()


# ---------------------------------------------------------------------------
# Test 1: RedisExporter writes and reads back
# ---------------------------------------------------------------------------

def test_redis_exporter_roundtrip():
    """Event written by RedisExporter is readable via XRANGE."""
    from lumen_ai.providers import RedisExporter

    exporter = RedisExporter(REDIS_URL, stream_prefix=TEST_PREFIX)

    event = {
        "id": "test-001",
        "tenant_id": "acme",
        "cost_usd": 0.0042,
        "model": "claude-sonnet-4-6",
        "tokens_in": 1000,
        "tokens_out": 500,
    }
    exporter.export("acme", event)

    # Read back
    import redis
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    entries = r.xrange(f"{TEST_PREFIX}:acme")
    assert len(entries) >= 1

    last_event = json.loads(entries[-1][1]["data"])
    assert last_event["id"] == "test-001"
    assert last_event["cost_usd"] == 0.0042
    assert last_event["model"] == "claude-sonnet-4-6"

    exporter.shutdown()
    r.close()


# ---------------------------------------------------------------------------
# Test 2: Tenant isolation in Redis streams
# ---------------------------------------------------------------------------

def test_tenant_isolation_in_redis():
    """Events from different tenants land in separate streams."""
    from lumen_ai.providers import RedisExporter

    exporter = RedisExporter(REDIS_URL, stream_prefix=TEST_PREFIX)

    exporter.export("tenant-a", {"id": "a1", "tenant_id": "tenant-a", "cost_usd": 1.0})
    exporter.export("tenant-b", {"id": "b1", "tenant_id": "tenant-b", "cost_usd": 2.0})
    exporter.export("tenant-a", {"id": "a2", "tenant_id": "tenant-a", "cost_usd": 3.0})

    import redis
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

    entries_a = r.xrange(f"{TEST_PREFIX}:tenant-a")
    entries_b = r.xrange(f"{TEST_PREFIX}:tenant-b")

    assert len(entries_a) == 2
    assert len(entries_b) == 1

    # Tenant A cannot see Tenant B's events
    ids_a = [json.loads(e[1]["data"])["id"] for e in entries_a]
    assert "a1" in ids_a
    assert "a2" in ids_a
    assert "b1" not in ids_a

    exporter.shutdown()
    r.close()


# ---------------------------------------------------------------------------
# Test 3: Full pipeline — span → processors → Redis
# ---------------------------------------------------------------------------

def test_full_pipeline_span_to_redis():
    """A span with token attributes flows through all 3 processors to Redis."""
    from unittest.mock import MagicMock
    from lumen_ai.processors.tenant import TenantSpanProcessor, set_tenant_id, _current_tenant
    from lumen_ai.processors.cost import CostComputingSpanProcessor
    from lumen_ai.processors.normalizer import EventNormalizerProcessor
    from lumen_ai.providers import DefaultPricingProvider, RedisExporter
    from lumen_ai.schema.semconv import PRICING_TABLE, GenAIAttributes

    exporter = RedisExporter(REDIS_URL, stream_prefix=TEST_PREFIX)
    pricing = DefaultPricingProvider(PRICING_TABLE)

    p1 = TenantSpanProcessor(default_tenant="test-default")
    p2 = CostComputingSpanProcessor(pricing)
    p3 = EventNormalizerProcessor(exporter=exporter)

    # Create a realistic span
    span = MagicMock()
    span.context.trace_id = 0xDEADBEEF
    span.context.span_id = 0xCAFE
    span.name = "anthropic.messages.create"
    span.start_time = 1000000000  # 1ms in ns
    span.end_time = 1500000000    # 1.5ms in ns
    span.status = MagicMock(status_code=0)
    span.is_recording.return_value = True

    attrs = {
        GenAIAttributes.REQUEST_MODEL: "claude-sonnet-4-6",
        GenAIAttributes.USAGE_INPUT_TOKENS: 1000,
        GenAIAttributes.USAGE_OUTPUT_TOKENS: 500,
        GenAIAttributes.USAGE_CACHE_READ: 0,
    }
    span.attributes = attrs
    span.set_attribute = lambda k, v: attrs.update({k: v})

    # Set tenant and run pipeline
    token = set_tenant_id("pipeline-test")
    try:
        p1.on_end(span)
        p2.on_end(span)
        p3.on_end(span)
    finally:
        _current_tenant.reset(token)

    # Verify event arrived in Redis
    import redis
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    entries = r.xrange(f"{TEST_PREFIX}:pipeline-test")
    assert len(entries) >= 1

    event = json.loads(entries[-1][1]["data"])
    assert event["tenant_id"] == "pipeline-test"
    assert event["model"] == "claude-sonnet-4-6"
    assert event["tokens_in"] == 1000
    assert event["tokens_out"] == 500
    assert event["cost_usd"] > 0
    assert event["duration_ms"] == 500

    exporter.shutdown()
    r.close()


# ---------------------------------------------------------------------------
# Test 4: LumenAI.init() validation
# ---------------------------------------------------------------------------

def test_init_rejects_invalid_redis_url():
    """LumenAI.init() raises on invalid redis_url."""
    from lumen_ai.sdk import LumenAI
    LumenAI._initialized = False  # Reset singleton

    with pytest.raises(ValueError, match="Invalid redis_url"):
        LumenAI.init(redis_url="http://not-redis:6379")

    LumenAI._initialized = False


def test_init_rejects_empty_tenant():
    """LumenAI.init() raises on empty default_tenant."""
    from lumen_ai.sdk import LumenAI
    LumenAI._initialized = False

    with pytest.raises(ValueError, match="default_tenant must be"):
        LumenAI.init(default_tenant="", redis_url=REDIS_URL)

    LumenAI._initialized = False


def test_init_rejects_redis_url_and_exporter():
    """LumenAI.init() raises when both redis_url and exporter are passed."""
    from lumen_ai.sdk import LumenAI
    from lumen_ai.providers import RedisExporter
    LumenAI._initialized = False

    exporter = RedisExporter(REDIS_URL)
    with pytest.raises(ValueError, match="Cannot pass both"):
        LumenAI.init(redis_url=REDIS_URL, exporter=exporter)

    exporter.shutdown()
    LumenAI._initialized = False
