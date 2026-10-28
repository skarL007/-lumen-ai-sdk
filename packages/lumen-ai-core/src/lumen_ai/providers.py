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

from lumen_ai.processors.tenant import sanitize_tenant_id
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

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        """Write out any buffered events. Unbuffered exporters return True."""
        return True

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

LITELLM_PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)


def _per_million(value: Any) -> Optional[float]:
    """A LiteLLM per-token USD price as USD per 1M tokens, or None if unusable."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rate = float(value) * 1_000_000
    if rate != rate or rate < 0 or rate == float("inf"):
        return None
    return round(rate, 6)


def litellm_pricing_table(data: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """
    Convert LiteLLM's ``model_prices_and_context_window.json`` to LumenAI's
    format (USD per 1M tokens). Each model is reachable by its LiteLLM key
    (``gemini/gemini-2.5-flash``) and, when no native entry claims it, by the
    bare id after the last ``/`` (``gemini-2.5-flash``). Entries without an
    input price are skipped; a missing cache-read price falls back to the input
    rate, so cached tokens are never billed below what they may cost.
    """
    table: Dict[str, Dict[str, float]] = {}
    bare: Dict[str, Dict[str, float]] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict) or key == "sample_spec":
            continue
        rate_in = _per_million(entry.get("input_cost_per_token"))
        if rate_in is None:
            continue
        pricing = {
            "input": rate_in,
            "output": _per_million(entry.get("output_cost_per_token")) or 0.0,
        }
        cache_read = _per_million(entry.get("cache_read_input_token_cost"))
        pricing["cache_read"] = rate_in if cache_read is None else cache_read
        cache_write = _per_million(entry.get("cache_creation_input_token_cost"))
        if cache_write:
            pricing["cache_write"] = cache_write
        table[key] = pricing
        short = key.rsplit("/", 1)[-1]
        if short != key:
            bare.setdefault(short, pricing)
    for short, pricing in bare.items():
        table.setdefault(short, pricing)
    return table


class LiteLLMPricingProvider(BasePricingProvider):
    """
    Prices from LumenAI's built-in table first, then from LiteLLM's community
    price list (thousands of models) for anything the table lacks.

    The list is downloaded in a background thread when the provider is created
    and again after ``ttl_seconds``; a span never waits for the network. Until
    the first download lands, only the built-in table answers, and models it
    lacks are exported ``unpriced``. Pass ``path`` to read a local copy instead
    (offline or pinned deployments).

        LumenAI.init(pricing_provider=LiteLLMPricingProvider())
    """

    _MAX_BYTES = 16 * 1_048_576  # the list is about 3 MiB

    def __init__(
        self,
        url: str = LITELLM_PRICES_URL,
        path: Optional[str | Path] = None,
        builtin: Optional[Dict[str, Dict[str, float]]] = None,
        ttl_seconds: float = 86_400,
    ):
        from lumen_ai.schema.semconv import PRICING_TABLE

        if path is None and urllib.parse.urlparse(url).scheme.lower() != "https":
            raise ValueError("LiteLLMPricingProvider only downloads over https")
        self._url = url
        self._path = Path(path) if path is not None else None
        self._builtin = PRICING_TABLE if builtin is None else builtin
        self._ttl = ttl_seconds
        self._table: Dict[str, Dict[str, float]] = {}
        self._loaded_at = 0.0
        self._lock = threading.Lock()
        self._loading: Optional[threading.Thread] = None
        if self._path is not None:
            self._load()
        else:
            self._refresh_in_background()

    @property
    def loaded(self) -> bool:
        """True once a price list has been read."""
        return bool(self._table)

    def get_pricing(self, model: str) -> Optional[Dict[str, float]]:
        builtin = match_model_pricing(self._builtin, model)
        if builtin is not None:
            return builtin
        if self._path is None and time.time() - self._loaded_at > self._ttl:
            self._refresh_in_background()
        return match_model_pricing(self._table, model)

    def wait_until_loaded(self, timeout: float = 30.0) -> bool:
        """Block until the current download finishes (useful in scripts and tests)."""
        thread = self._loading
        if thread is not None:
            thread.join(timeout)
        return self.loaded

    def _refresh_in_background(self) -> None:
        with self._lock:
            if self._loading is not None and self._loading.is_alive():
                return
            # Back off for the full TTL even if this attempt fails.
            self._loaded_at = time.time()
            self._loading = threading.Thread(
                target=self._load, name="lumen-litellm-prices", daemon=True
            )
            self._loading.start()

    def _load(self) -> None:
        try:
            if self._path is not None:
                raw = self._path.read_bytes()
            else:
                with urllib.request.urlopen(self._url, timeout=30) as response:
                    raw = response.read(self._MAX_BYTES + 1)
            if len(raw) > self._MAX_BYTES:
                logger.warning("LiteLLMPricingProvider: price list exceeds %d bytes — ignored", self._MAX_BYTES)
                return
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                logger.warning("LiteLLMPricingProvider: price list is not a JSON object — ignored")
                return
            table = litellm_pricing_table(data)
            with self._lock:
                self._table = table
            logger.info("LiteLLMPricingProvider: %d model prices loaded", len(table))
        except Exception as e:
            logger.warning("LiteLLMPricingProvider: could not load prices: %s", e)


class RedisExporter(BaseLumenAIExporter):
    """
    Synchronous Redis Streams exporter.

    ``export()`` runs a blocking ``XADD`` inline in ``on_end`` on the
    span-ending (request / event-loop) thread, so it suits low-throughput or
    testing setups. For high-throughput or latency-sensitive paths use
    :class:`AsyncRedisExporter`, which buffers and writes from a dedicated
    background event loop and never blocks the caller.
    """

    def __init__(
        self,
        redis_url: str,
        stream_prefix: str = "LumenAI:events",
        maxlen: int = 10000,
    ):
        import redis as _redis
        self._redis = _redis.Redis.from_url(redis_url, decode_responses=True)
        self._stream_prefix = stream_prefix
        self._maxlen = maxlen

    def export(self, tenant_id: str, event: LumenAIEvent) -> None:
        tenant_id = sanitize_tenant_id(tenant_id)
        stream_key = f"{self._stream_prefix}:{tenant_id}"
        try:
            self._redis.xadd(
                stream_key,
                {"data": json.dumps(event, default=str)},
                maxlen=self._maxlen,
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
            if self._file.closed:
                logger.debug("JsonlExporter: export after shutdown ignored")
                return
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
    thread) only appends to an in-memory buffer. The buffer is written as one
    pipelined batch on a dedicated background event loop when it reaches
    ``max_buffer`` events or every ``flush_interval`` seconds, whichever comes
    first, so low-traffic services still see events within about a second. It never
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
        flush_interval: Optional[float] = 1.0,
    ):
        if flush_interval is not None and flush_interval <= 0:
            raise ValueError("flush_interval must be > 0 seconds, or None to disable")
        self._redis_url = redis_url
        self._flush_interval = flush_interval
        self._stream_prefix = stream_prefix
        self._max_buffer = max_buffer
        self._maxlen = maxlen
        self._buffer: List[Tuple[str, LumenAIEvent]] = []
        self._lock = threading.RLock()
        self._redis: Optional[Any] = None
        self._closed = False
        self._futures: set[Any] = set()
        # Dedicated event loop in a daemon thread; all Redis I/O runs here so the
        # loop-bound client is never shared across loops.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="lumenai-async-redis", daemon=True
        )
        self._thread.start()
        # The periodic flusher is tracked apart from _futures: it never finishes
        # on its own, so shutdown/force_flush must cancel it, not wait on it.
        self._periodic: Optional[Any] = None
        if flush_interval is not None:
            self._periodic = asyncio.run_coroutine_threadsafe(
                self._periodic_flush(flush_interval), self._loop
            )

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _periodic_flush(self, interval: float) -> None:
        """Time-based flush so a partially filled buffer never waits forever."""
        while True:
            await asyncio.sleep(interval)
            events = self._drain()
            if events:
                await self._write_batch(events)

    async def _get_client(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def export(self, tenant_id: str, event: LumenAIEvent) -> None:
        """Buffer an event; schedule a background flush when the buffer is full."""
        tenant_id = sanitize_tenant_id(tenant_id)
        with self._lock:
            if self._closed:
                return
            self._buffer.append((tenant_id, event))
            if len(self._buffer) >= self._max_buffer:
                events = self._buffer
                self._buffer = []
                self._schedule_locked(self._write_batch(events))

    def _schedule_locked(self, coro: Any) -> Optional[Any]:
        """Submit a coroutine while ``self._lock`` is already held."""
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            self._futures.add(future)
            future.add_done_callback(self._discard_future)
            return future
        except RuntimeError:
            coro.close()  # loop already stopped (shutting down) — drop quietly
            return None

    def _schedule(self, coro: Any) -> Optional[Any]:
        """Submit a coroutine to the background loop without blocking."""
        with self._lock:
            return self._schedule_locked(coro)

    def _discard_future(self, future: Any) -> None:
        with self._lock:
            self._futures.discard(future)

    def _drain(self) -> List[Tuple[str, LumenAIEvent]]:
        with self._lock:
            events = self._buffer
            self._buffer = []
            return events

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        """Write the buffer now and wait for in-flight batches (blocking).

        ``TracerProvider.force_flush()`` reaches this through the normalizer.
        Do not call it from the exporter's own background loop.
        """
        timeout = timeout_millis / 1000 if timeout_millis else 5.0
        with self._lock:
            if self._closed:
                return True
            events = self._buffer
            self._buffer = []
            if events:
                self._schedule_locked(self._write_batch(events))
            pending = list(self._futures)
        deadline = time.monotonic() + timeout
        for future in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                future.result(timeout=remaining)
            except Exception:
                return False
        return True

    async def aflush(self) -> None:
        """Async flush — schedules the flush on the background loop and awaits it."""
        with self._lock:
            events = self._buffer
            self._buffer = []
            if not events:
                return
            fut = self._schedule_locked(self._write_batch(events))
        if fut is not None:
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
            futures = list(self._futures)
        if self._periodic is not None:
            self._periodic.cancel()
        if not self._loop.is_closed():
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._shutdown_coro(events, futures), self._loop
                )
                fut.result(timeout=5)
            except Exception as e:
                logger.debug("AsyncRedisExporter shutdown flush failed: %s", e)
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if not self._thread.is_alive() and not self._loop.is_closed():
            self._loop.close()

    async def _shutdown_coro(
        self,
        events: List[Tuple[str, LumenAIEvent]],
        futures: List[Any],
    ) -> None:
        for future in futures:
            try:
                await asyncio.wrap_future(future)
            except Exception:
                logger.debug("AsyncRedisExporter in-flight flush raised", exc_info=True)
        if events:
            await self._write_batch(events)
        if self._redis is not None:
            await self._redis.aclose()
