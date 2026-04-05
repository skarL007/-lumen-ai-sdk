"""
LumenAI Master Providers — Abstractions for Pricing and Exporting.

Enables market-ready flexibility by decoupling core logic from 
specific databases (Redis) and static pricing tables.
"""
import abc
import logging
from typing import Optional, Dict

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
    """Standard Redis Streams exporter."""
    def __init__(self, redis_url: str, stream_prefix: str = "LumenAI:events"):
        import redis
        import json
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._stream_prefix = stream_prefix
        self._json = json

    def export(self, tenant_id: str, event: dict) -> None:
        stream_key = f"{self._stream_prefix}:{tenant_id}"
        try:
            self._redis.xadd(
                stream_key,
                {"data": self._json.dumps(event, default=str)},
                maxlen=10000,
            )
        except Exception as e:
            logger.debug("Redis export failed: %s", e)

    def shutdown(self) -> None:
        self._redis.close()
