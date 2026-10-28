"""
Per-tenant budgets: alert when a tenant's GenAI spend crosses a share of its limit.

``BudgetExporter`` wraps any exporter. Every event still reaches the wrapped
exporter first; the wrapper adds up ``cost_usd`` per tenant and period (UTC
calendar day or month, taken from each event's own timestamp). When a tenant
crosses a threshold (80% and 100% by default) it fires once per period:

* the ``on_alert`` callback receives a ``BudgetAlert``;
* a ``COST_THRESHOLD_EXCEEDED`` event goes to the wrapped exporter
  (severity ``WARN`` below the limit, ``ERROR`` at or over it);
* a WARNING is logged.

Spend lives in this process's memory. With several workers, each one tracks
only its own share; give each worker its slice of the limit, or aggregate the
exported events downstream.

    LumenAI.init(exporter=BudgetExporter(
        JsonlExporter("events.jsonl"),
        limits={"acme": 50.0},
        default_limit=10.0,
        on_alert=lambda alert: notify(alert.tenant_id, alert.spent_usd),
    ))
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional

# providers imports the processors package, which imports providers back; load
# the processors first so either module can be the first one imported.
import lumen_ai.processors  # noqa: F401
from lumen_ai.providers import BaseLumenAIExporter
from lumen_ai.schema.event_types import EventType, LumenAIEvent, Severity

logger = logging.getLogger(__name__)

_PERIOD_FORMATS = {"day": "%Y-%m-%d", "month": "%Y-%m"}
_PERIOD_ADJECTIVES = {"day": "daily", "month": "monthly"}


@dataclass(frozen=True)
class BudgetAlert:
    """A tenant crossed ``threshold`` (a share of ``limit_usd``) in ``period``."""

    tenant_id: str
    period: str
    threshold: float
    spent_usd: float
    limit_usd: float
    # Events in the period that used tokens without a price: spend is a lower bound.
    unpriced_events: int


class BudgetExporter(BaseLumenAIExporter):
    """
    Exporter wrapper that enforces nothing but reports budget crossings.

    Args:
        exporter: the exporter every event is passed to.
        limits: USD limit per tenant id for each period.
        default_limit: limit for tenants missing from ``limits``; ``None``
            leaves them untracked.
        period: ``"month"`` (default) or ``"day"``, in UTC.
        thresholds: shares of the limit that alert, each once per period.
        on_alert: called with a ``BudgetAlert``; exceptions are logged, never raised.
    """

    def __init__(
        self,
        exporter: BaseLumenAIExporter,
        limits: Optional[Mapping[str, float]] = None,
        *,
        default_limit: Optional[float] = None,
        period: str = "month",
        thresholds: tuple[float, ...] = (0.8, 1.0),
        on_alert: Optional[Callable[[BudgetAlert], None]] = None,
    ) -> None:
        if period not in _PERIOD_FORMATS:
            raise ValueError(f"period must be one of {sorted(_PERIOD_FORMATS)}, not {period!r}")
        if any(t <= 0 for t in thresholds):
            raise ValueError("thresholds must be positive shares of the limit, e.g. (0.8, 1.0)")
        for tenant, limit in {**(limits or {}), "": default_limit or 1}.items():
            if limit is not None and limit <= 0:
                raise ValueError(f"limit for {tenant or 'default'} must be positive")
        self._exporter = exporter
        self._limits = dict(limits or {})
        self._default_limit = default_limit
        self._format = _PERIOD_FORMATS[period]
        self._period_adjective = _PERIOD_ADJECTIVES[period]
        self._thresholds = tuple(sorted(thresholds))
        self._on_alert = on_alert
        self._lock = threading.Lock()
        # tenant -> [period, spent_usd, unpriced_events, alerted thresholds]
        self._state: dict[str, list] = {}

    def limit_for(self, tenant_id: str) -> Optional[float]:
        return self._limits.get(tenant_id, self._default_limit)

    def spent(self, tenant_id: str) -> float:
        """USD this tenant has spent in its current period (0.0 if untracked)."""
        with self._lock:
            state = self._state.get(tenant_id)
            return state[1] if state else 0.0

    def export(self, tenant_id: str, event: LumenAIEvent) -> None:
        self._exporter.export(tenant_id, event)
        if event.get("event_type") == EventType.COST_THRESHOLD_EXCEEDED:
            return
        limit = self.limit_for(tenant_id)
        if limit is None:
            return
        period = self._period_of(event)
        crossed: list[BudgetAlert] = []
        with self._lock:
            state = self._state.get(tenant_id)
            if state is None or state[0] != period:
                state = [period, 0.0, 0, set()]
                self._state[tenant_id] = state
            state[1] += float(event.get("cost_usd") or 0.0)
            if event.get("unpriced"):
                state[2] += 1
            for threshold in self._thresholds:
                if threshold not in state[3] and state[1] >= threshold * limit:
                    state[3].add(threshold)
                    crossed.append(BudgetAlert(
                        tenant_id=tenant_id, period=period, threshold=threshold,
                        spent_usd=round(state[1], 8), limit_usd=limit, unpriced_events=state[2],
                    ))
        for alert in crossed:
            self._alert(alert, event)

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        flush = getattr(self._exporter, "force_flush", None)
        return bool(flush(timeout_millis)) if flush else True

    def shutdown(self) -> None:
        self._exporter.shutdown()

    def _period_of(self, event: LumenAIEvent) -> str:
        try:
            moment = datetime.fromisoformat(str(event.get("timestamp")))
        except ValueError:
            moment = datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime(self._format)

    def _alert(self, alert: BudgetAlert, trigger: LumenAIEvent) -> None:
        share = round(alert.spent_usd / alert.limit_usd * 100)
        message = (
            f"Tenant {alert.tenant_id} spent ${alert.spent_usd:.4f} of its "
            f"${alert.limit_usd:.2f} {self._period_adjective} GenAI budget ({share}%) "
            f"in {alert.period}"
        )
        if alert.unpriced_events:
            message += f"; {alert.unpriced_events} unpriced events not counted"
        logger.warning(message)
        if self._on_alert is not None:
            try:
                self._on_alert(alert)
            except Exception:
                logger.warning("BudgetExporter on_alert callback raised", exc_info=True)
        event: LumenAIEvent = {
            "id": str(uuid.uuid4()),
            "tenant_id": alert.tenant_id,
            "session_id": trigger.get("session_id", ""),
            "agent_id": trigger.get("agent_id", ""),
            "trace_id": trigger.get("trace_id", ""),
            "span_id": trigger.get("span_id", ""),
            "timestamp": trigger.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "event_type": EventType.COST_THRESHOLD_EXCEEDED,
            "severity": Severity.ERROR if alert.threshold >= 1.0 else Severity.WARN,
            "message": message,
            "duration_ms": 0,
            "is_error": False,
            "cost_usd": 0.0,
            "unpriced": False,
            "tokens_in": 0,
            "tokens_out": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "model": "",
            "tool_name": "",
            "span_kind": "",
        }
        try:
            self._exporter.export(alert.tenant_id, event)
        except Exception:
            logger.warning("BudgetExporter could not export the alert event", exc_info=True)
