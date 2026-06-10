import os
import sys
import threading
import types

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src"),
)


def test_async_redis_exporter_flushes_full_buffer_without_deadlock(monkeypatch):
    class FakePipeline:
        def xadd(self, *args, **kwargs):
            return None

        async def execute(self):
            return None

    class FakeRedis:
        def pipeline(self):
            return FakePipeline()

        async def aclose(self):
            return None

    redis_module = types.ModuleType("redis")
    redis_module.__path__ = []
    redis_asyncio = types.ModuleType("redis.asyncio")
    redis_asyncio.from_url = lambda *args, **kwargs: FakeRedis()
    redis_module.asyncio = redis_asyncio
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_asyncio)

    from lumen_ai.providers import AsyncRedisExporter

    exporter = AsyncRedisExporter("redis://localhost:6379/0", max_buffer=1)
    thread = threading.Thread(
        target=lambda: exporter.export("acme", {"id": "event-1", "tenant_id": "acme"}),
        daemon=True,
    )

    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive()
    exporter.shutdown()
