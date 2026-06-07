"""
LumenAI Master Providers — Abstractions for Pricing and Exporting.

Enables market-ready flexibility by decoupling core logic from
specific databases (Redis) and static pricing tables.
"""
import abc
import asyncio
import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lumen_ai.schema.event_types import LumenAIEvent
from lumen_ai.schema.semconv import match_model_pricing

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
    def export(self, tenant_id: str, event: LumenAIEvent) -> None:
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
        return match_model_pricing(self._table, model)

class CommunityPricingProvider(BasePricingProvider):
    """
    Fetches model prices from a remote JSON URL (e.g. GitHub Gist).
    Enables community-driven updates without redeploying code.
    """
    _MAX_BYTES = 1_048_576  # 1 MiB cap on the pricing document

    def __init__(
        self,
        url: str,
        fallback_table: Optional[Dict] = None,
        allow_insecure: bool = False,
    ):
        self._url = url
        self._table = fallback_table or {}
        self._last_attempt = 0.0
        self._ttl = 3600  # Refresh at most once per hour (success OR failure)
        self._allow_insecure = allow_insecure

    def _fetch_remote(self) -> None:
        now = time.time()
        if now - self._last_attempt < self._ttl:
            return
        # Record the attempt up front so a failing/forbidden source backs off for
        # the full TTL instead of re-blocking the hot path on every span.
        self._last_attempt = now

        scheme = urllib.parse.urlparse(self._url).scheme.lower()
        allowed = ("https", "http") if self._allow_insecure else ("https",)
        if scheme not in allowed:
            logger.warning(
                "CommunityPricingProvider: refusing URL scheme '%s' (allowed: %s)",
                scheme, ", ".join(allowed),
            )
            return

        try:
            with urllib.request.urlopen(self._url, timeout=5) as response:
                raw = response.read(self._MAX_BYTES + 1)
                if len(raw) > self._MAX_BYTES:
                    logger.warning(
                        "CommunityPricingProvider: pricing document exceeds %d bytes — ignored",
                        self._MAX_BYTES,
                    )
                    return
                data = json.loads(raw.decode())
                if not isinstance(data, dict):
                    logger.warning(
                        "CommunityPricingProvider: pricing document is not a JSON object — ignored"
                    )
                    return
                self._table = data
                logger.info("LumenAI: Remote pricing table updated from community source.")
        except Exception as e:
            logger.warning("LumenAI: Failed to fetch remote pricing: %s", e)

    def get_pricing(self, model: str) -> Optional[Dict[str, float]]:
        self._fetch_remote()
        return match_model_pricing(self._table, model)

class RedisExporter(BaseLumenAIExporter):
    """Synchronous Redis Streams exporter."""

    def __init__(self, redis_url: str, stream_prefix: str = "LumenAI:events"):
        import redis as _redis
        self._redis = _redis.Redis.from_url(redis_url, decode_responses=True)
        self._stream_prefix = stream_prefix

    def export(self, tenant_id: str, event: LumenAIEvent) -> None:
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


class JsonlExporter(BaseLumenAIExporter):
    """Append-only JSON Lines exporter for local demos and smoke tests."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def export(self, tenant_id: str, event: LumenAIEvent) -> None:
        line = json.dumps(event, default=str, separators=(",", ":"))
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()

    def shutdown(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()


class AsyncRedisExporter(BaseLumenAIExporter):
    """
    Non-blocking Redis Streams exporter.

    ``export()`` (called synchronously from ``on_end`` on the request/worker
    thread) only appends to an in-memory buffer and, when the buffer fills,
    schedules a batch flush on a dedicated background event loop. It never
    blocks on network I/O and never touches the caller's event loop. The
    ``redis.asyncio`` client is created on and used only by that one loop —
    these clients are bound to the loop that first drives them, so sharing one
    across throwaway ``asyncio.run()`` loops silently drops writes.

    Usage::

        # Pass it as ``exporter=`` — do NOT also pass ``redis_url`` (init()
        # rejects that combination).
        LumenAI.init(exporter=AsyncRedisExporter("redis://localhost:6379/0"))
        ...
        LumenAI.shutdown()          # drains the buffer and closes the client

        # Or, from your own async shutdown handler:
        await exporter.aflush()
    """

    def __init__(
        self,
        redis_url: str,
        stream_prefix: str = "LumenAI:events",
        max_buffer: int = 100,
        maxlen: int = 10000,
    ):
        self._redis_url = redis_url
        self._stream_prefix = stream_prefix
        self._max_buffer = max_buffer
        self._maxlen = maxlen
        self._buffer: List[Tuple[str, LumenAIEvent]] = []
        self._lock = threading.Lock()
        self._redis: Optional[Any] = None
        self._closed = False
        # Dedicated event loop in a daemon thread; all Redis I/O runs here so the
        # loop-bound client is never shared across loops.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="lumenai-async-redis", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _get_client(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def export(self, tenant_id: str, event: LumenAIEvent) -> None:
        """Buffer an event; schedule a background flush when the buffer is full."""
        to_flush: Optional[List[Tuple[str, LumenAIEvent]]] = None
        with self._lock:
            if self._closed:
                return
            self._buffer.append((tenant_id, event))
            if len(self._buffer) >= self._max_buffer:
                to_flush = self._buffer
                self._buffer = []
        # Schedule OUTSIDE the lock — the flush path must never re-acquire it.
        if to_flush:
            self._schedule(self._write_batch(to_flush))

    def _schedule(self, coro: Any) -> None:
        """Submit a coroutine to the background loop without blocking."""
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            coro.close()  # loop already stopped (shutting down) — drop quietly

    def _drain(self) -> List[Tuple[str, LumenAIEvent]]:
        with self._lock:
            events = self._buffer
            self._buffer = []
            return events

    async def aflush(self) -> None:
        """Async flush — schedules the flush on the background loop and awaits it."""
        events = self._drain()
        if not events:
            return
        fut = asyncio.run_coroutine_threadsafe(self._write_batch(events), self._loop)
        await asyncio.wrap_future(fut)

    async def _write_batch(self, events: List[Tuple[str, LumenAIEvent]]) -> None:
        try:
            client = await self._get_client()
            pipe = client.pipeline()
            for tenant_id, event in events:
                stream_key = f"{self._stream_prefix}:{tenant_id}"
                pipe.xadd(
                    stream_key,
                    {"data": json.dumps(event, default=str)},
                    maxlen=self._maxlen,
                )
            await pipe.execute()
        except Exception as e:
            logger.warning("AsyncRedisExporter batch flush failed: %s", e)

    def shutdown(self) -> None:
        """Flush remaining events, close the client, stop the loop (blocking)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            events = self._buffer
            self._buffer = []
        if not self._loop.is_closed():
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._shutdown_coro(events), self._loop
                )
                fut.result(timeout=5)
            except Exception as e:
                logger.debug("AsyncRedisExporter shutdown flush failed: %s", e)
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if not self._thread.is_alive() and not self._loop.is_closed():
            self._loop.close()

    async def _shutdown_coro(self, events: List[Tuple[str, LumenAIEvent]]) -> None:
        if events:
            await self._write_batch(events)
        if self._redis is not None:
            await self._redis.aclose()
