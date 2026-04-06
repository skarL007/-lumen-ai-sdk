"""
LumenAI Master Providers — Abstractions for Pricing and Exporting.

Enables market-ready flexibility by decoupling core logic from
specific databases (Redis) and static pricing tables.
"""
import abc
import json
import logging
import threading
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

class BasePricingProvider(abc.ABC):
    """
    Interface for providing LLM token prices.
    Implement this to fetch prices from an API, DB, or Config.
    """
    @abc.abstractmethod
    def get_pricing(self, model: str) -> Optional[Dict[str, float]]:
        """Return {"input": 0.0, "output": 0.0, "cache_read": 0.0} or None."""
        pass

class BaseLumenAIExporter(abc.ABC):
    """
    Interface for exporting normalized events.
    Implement this to send events to Redis, ClickHouse, Postgres, etc.
    """
    @abc.abstractmethod
    def export(self, tenant_id: str, event: dict) -> None:
        """Send the event to the target sink."""
        pass

    def shutdown(self) -> None:
        """Gracefully close connections."""
        pass

# --- Default Implementations (Backward Compatibility) ---

class DefaultPricingProvider(BasePricingProvider):
    """Fallback provider using the internal static PRICING_TABLE."""
    def __init__(self, static_table: Dict[str, Dict[str, float]]):
        self._table = static_table

    def get_pricing(self, model: str) -> Optional[Dict[str, float]]:
        pricing = self._table.get(model)
        if not pricing:
            for key, val in self._table.items():
                if key in model or model.endswith(key):
                    return val
        return pricing

class CommunityPricingProvider(BasePricingProvider):
    """
    Fetches model prices from a remote JSON URL (e.g. GitHub Gist).
    Enables community-driven updates without redeploying code.
    """
    def __init__(self, url: str, fallback_table: Optional[Dict] = None):
        self._url = url
        self._table = fallback_table or {}
        self._last_fetch = 0
        self._ttl = 3600  # Refresh every hour

    def _fetch_remote(self):
        import urllib.request
        import json
        import time
        if time.time() - self._last_fetch < self._ttl:
            return
        try:
            with urllib.request.urlopen(self._url, timeout=5) as response:
                self._table = json.loads(response.read().decode())
                self._last_fetch = time.time()
                logger.info("LumenAI: Remote pricing table updated from community source.")
        except Exception as e:
            logger.warning("LumenAI: Failed to fetch remote pricing: %s", e)

    def get_pricing(self, model: str) -> Optional[Dict[str, float]]:
        self._fetch_remote()
        pricing = self._table.get(model)
        if not pricing:
            for key, val in self._table.items():
                if key in model or model.endswith(key):
                    return val
        return pricing

class RedisExporter(BaseLumenAIExporter):
    """Synchronous Redis Streams exporter."""

    def __init__(self, redis_url: str, stream_prefix: str = "LumenAI:events"):
        import redis as _redis
        self._redis = _redis.Redis.from_url(redis_url, decode_responses=True)
        self._stream_prefix = stream_prefix

    def export(self, tenant_id: str, event: dict) -> None:
        stream_key = f"{self._stream_prefix}:{tenant_id}"
        try:
            self._redis.xadd(
                stream_key,
                {"data": json.dumps(event, default=str)},
                maxlen=10000,
            )
        except Exception as e:
            logger.warning("Redis export failed: %s", e)

    def shutdown(self) -> None:
        self._redis.close()


class AsyncRedisExporter(BaseLumenAIExporter):
    """
    Non-blocking Redis Streams exporter.

    Buffers events in memory and flushes to Redis in batches.
    Use ``aflush()`` from your async event loop for true non-blocking writes,
    or let the buffer auto-flush when it reaches ``max_buffer`` size.

    Usage::

        LumenAI.init(
            redis_url="redis://localhost:6379/0",
            exporter=AsyncRedisExporter("redis://localhost:6379/0"),
        )

        # In your shutdown handler:
        await exporter.aflush()
    """

    def __init__(
        self,
        redis_url: str,
        stream_prefix: str = "LumenAI:events",
        max_buffer: int = 100,
        maxlen: int = 10000,
    ):
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._stream_prefix = stream_prefix
        self._max_buffer = max_buffer
        self._maxlen = maxlen
        self._buffer: List[Tuple[str, dict]] = []
        self._lock = threading.Lock()

    def export(self, tenant_id: str, event: dict) -> None:
        """Buffer event for async flush (called synchronously from on_end)."""
        with self._lock:
            self._buffer.append((tenant_id, event))
            if len(self._buffer) >= self._max_buffer:
                self._flush_sync()

    def _flush_sync(self) -> None:
        """Synchronous fallback flush using a new event loop."""
        import asyncio
        events = self._drain_buffer()
        if not events:
            return
        try:
            asyncio.get_running_loop()
            # Already in async context — schedule coroutine
            asyncio.ensure_future(self._write_batch(events))
        except RuntimeError:
            # No running loop — create one
            asyncio.run(self._write_batch(events))

    async def aflush(self) -> None:
        """Async flush — call from your event loop (e.g. lifespan shutdown)."""
        events = self._drain_buffer()
        if events:
            await self._write_batch(events)

    def _drain_buffer(self) -> List[Tuple[str, dict]]:
        with self._lock:
            events = list(self._buffer)
            self._buffer.clear()
            return events

    async def _write_batch(self, events: List[Tuple[str, dict]]) -> None:
        pipe = self._redis.pipeline()
        for tenant_id, event in events:
            stream_key = f"{self._stream_prefix}:{tenant_id}"
            pipe.xadd(
                stream_key,
                {"data": json.dumps(event, default=str)},
                maxlen=self._maxlen,
            )
        try:
            await pipe.execute()
        except Exception as e:
            logger.warning("AsyncRedisExporter batch flush failed: %s", e)

    def shutdown(self) -> None:
        """Flush remaining buffer and close connection."""
        self._flush_sync()
        import asyncio
        try:
            asyncio.get_running_loop()
            asyncio.ensure_future(self._redis.aclose())
        except RuntimeError:
            asyncio.run(self._redis.aclose())
