"""Mutable runtime state shared by LumenAI span processors."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from lumen_ai.providers import BaseLumenAIExporter, BasePricingProvider

logger = logging.getLogger(__name__)


class LumenRuntimeState:
    """Holds runtime-configurable pieces for processors attached once."""

    def __init__(
        self,
        *,
        default_tenant: str,
        pricing_provider: Optional[BasePricingProvider],
        exporter: Optional[BaseLumenAIExporter],
    ) -> None:
        self._lock = threading.RLock()
        self._default_tenant = default_tenant.strip()
        self._pricing_provider = pricing_provider
        self._exporter = exporter
        self._closed_exporter_ids: set[int] = set()

    def configure(
        self,
        *,
        default_tenant: str,
        pricing_provider: Optional[BasePricingProvider],
        exporter: Optional[BaseLumenAIExporter],
    ) -> None:
        """Update state used by already-attached processors."""
        with self._lock:
            self._default_tenant = default_tenant.strip()
            self._pricing_provider = pricing_provider
            self._exporter = exporter

    @property
    def default_tenant(self) -> str:
        with self._lock:
            return self._default_tenant

    @property
    def pricing_provider(self) -> Optional[BasePricingProvider]:
        with self._lock:
            return self._pricing_provider

    @property
    def exporter(self) -> Optional[BaseLumenAIExporter]:
        with self._lock:
            return self._exporter

    def shutdown_exporter(self) -> None:
        """Close the current exporter at most once and detach it from runtime."""
        with self._lock:
            exporter = self._exporter
            self._exporter = None
            if exporter is None:
                return
            exporter_id = id(exporter)
            if exporter_id in self._closed_exporter_ids:
                return
            self._closed_exporter_ids.add(exporter_id)

        try:
            exporter.shutdown()
        except Exception:
            logger.debug("LumenAI exporter shutdown raised", exc_info=True)
