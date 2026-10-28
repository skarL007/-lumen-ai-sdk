"""BudgetExporter: per-tenant spend alerts at shares of a USD limit."""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest
from lumen_ai import BudgetAlert, BudgetExporter, LumenAI, lumen_tenant
from lumen_ai.processors.normalizer import reset_metrics
from lumen_ai.schema.semconv import GenAIAttributes
from opentelemetry import trace
from opentelemetry.util._once import Once


class _Capture:
    def __init__(self):
        self.events = []
        self.closed = False

    def export(self, tenant_id, event):
        self.events.append(event)

    def shutdown(self):
        self.closed = True


def _event(cost, timestamp="2026-10-28T12:00:00+00:00", unpriced=False):
    return {"cost_usd": cost, "timestamp": timestamp, "unpriced": unpriced,
            "event_type": "LLM_CALL_COMPLETED", "trace_id": "t", "span_id": "s"}


def _alerts(capture):
    return [e for e in capture.events if e["event_type"] == "COST_THRESHOLD_EXCEEDED"]


def test_alerts_once_at_80_and_100_percent():
    inner, alerts = _Capture(), []
    budget = BudgetExporter(inner, {"acme": 10.0}, on_alert=alerts.append)

    for cost in (5.0, 3.5, 0.5, 2.0, 1.0):  # 5, 8.5, 9, 11, 12
        budget.export("acme", _event(cost))

    assert [(a.threshold, a.spent_usd) for a in alerts] == [(0.8, 8.5), (1.0, 11.0)]
    assert alerts[0] == BudgetAlert("acme", "2026-10", 0.8, 8.5, 10.0, 0)
    events = _alerts(inner)
    assert [e["severity"] for e in events] == ["WARN", "ERROR"]
    assert "85%" in events[0]["message"] and events[0]["cost_usd"] == 0.0
    assert len(inner.events) == 5 + 2  # every event still reaches the wrapped exporter
    assert budget.spent("acme") == pytest.approx(12.0)


def test_new_month_starts_from_zero():
    inner, alerts = _Capture(), []
    budget = BudgetExporter(inner, {"acme": 10.0}, on_alert=alerts.append)
    budget.export("acme", _event(9.0, "2026-10-31T23:59:00+00:00"))
    budget.export("acme", _event(9.0, "2026-11-01T00:01:00+00:00"))

    assert [(a.period, a.threshold) for a in alerts] == [("2026-10", 0.8), ("2026-11", 0.8)]
    assert budget.spent("acme") == pytest.approx(9.0)


def test_daily_period():
    alerts = []
    budget = BudgetExporter(_Capture(), {"acme": 1.0}, period="day", on_alert=alerts.append)
    budget.export("acme", _event(1.0, "2026-10-28T10:00:00+00:00"))
    budget.export("acme", _event(1.0, "2026-10-29T10:00:00+00:00"))

    assert [a.period for a in alerts if a.threshold == 1.0] == ["2026-10-28", "2026-10-29"]


def test_tenants_without_a_limit_are_not_tracked():
    alerts = []
    budget = BudgetExporter(_Capture(), {"acme": 1.0}, on_alert=alerts.append)
    budget.export("globex", _event(100.0))

    assert alerts == [] and budget.spent("globex") == 0.0


def test_default_limit_covers_other_tenants():
    alerts = []
    budget = BudgetExporter(_Capture(), {"acme": 100.0}, default_limit=1.0, on_alert=alerts.append)
    budget.export("globex", _event(1.0))

    assert [(a.tenant_id, a.limit_usd) for a in alerts] == [("globex", 1.0), ("globex", 1.0)]


def test_unpriced_events_are_reported_as_a_lower_bound():
    inner, alerts = _Capture(), []
    budget = BudgetExporter(inner, {"acme": 1.0}, thresholds=(1.0,), on_alert=alerts.append)
    budget.export("acme", _event(0.0, unpriced=True))
    budget.export("acme", _event(1.0))

    assert alerts[0].unpriced_events == 1
    assert "1 unpriced events not counted" in _alerts(inner)[0]["message"]


def test_a_failing_callback_never_breaks_export():
    inner = _Capture()

    def boom(alert):
        raise RuntimeError("pager down")

    budget = BudgetExporter(inner, {"acme": 1.0}, on_alert=boom)
    budget.export("acme", _event(2.0))

    assert len(_alerts(inner)) == 2


@pytest.mark.parametrize(
    "kwargs",
    [{"period": "week"}, {"thresholds": (0.0, 1.0)}, {"limits": {"acme": 0}}, {"default_limit": -1.0}],
)
def test_bad_configuration_is_rejected(kwargs):
    kwargs = {"limits": {"acme": 1.0}, **kwargs}
    limits = kwargs.pop("limits")
    with pytest.raises(ValueError):
        BudgetExporter(_Capture(), limits, **kwargs)


def test_flush_and_shutdown_reach_the_wrapped_exporter():
    inner = _Capture()
    budget = BudgetExporter(inner, {"acme": 1.0})
    assert budget.force_flush() is True
    budget.shutdown()
    assert inner.closed


def test_end_to_end_with_lumenai_spans():
    saved_tp, saved_once = trace._TRACER_PROVIDER, trace._TRACER_PROVIDER_SET_ONCE
    trace._TRACER_PROVIDER, trace._TRACER_PROVIDER_SET_ONCE = None, Once()
    LumenAI._initialized = False
    reset_metrics()
    inner, alerts = _Capture(), []
    try:
        LumenAI.init(service_name="t", exporter=BudgetExporter(
            inner, {"acme": 0.01}, on_alert=alerts.append), genai_only=True)
        tracer = trace.get_tracer("budget-test")
        for _ in range(3):
            with lumen_tenant("acme"), tracer.start_as_current_span("llm") as span:
                span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
                span.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
                span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 10_000)
                span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, 20_000)
    finally:
        LumenAI.shutdown()
        LumenAI._initialized = False
        LumenAI._provider = None
        LumenAI._exporter = None
        LumenAI._runtime = None
        LumenAI._instrumentors = []
        trace._TRACER_PROVIDER, trace._TRACER_PROVIDER_SET_ONCE = saved_tp, saved_once

    # 10k * 0.15 + 20k * 0.60 per 1M = $0.0135 per call: the first call crosses both.
    assert [a.threshold for a in alerts] == [0.8, 1.0]
    assert alerts[0].tenant_id == "acme"
    assert len([e for e in inner.events if e["event_type"] == "LLM_CALL_COMPLETED"]) == 3
