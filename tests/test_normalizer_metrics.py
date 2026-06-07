"""
The normalizer swallows exporter failures and event-build errors with a logged
warning and no counter, so silent event/cost loss is invisible. Expose simple
counters (events_exported / export_errors / events_dropped) for health checks.
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from lumen_ai.processors.normalizer import (
    EventNormalizerProcessor,
    get_metrics,
    reset_metrics,
)


def _ok_span(trace_id, span_id):
    span = MagicMock()
    span.context.trace_id = trace_id
    span.context.span_id = span_id
    span.name = "op"
    span.status = MagicMock(status_code=0)
    span.start_time = 1_000_000
    span.end_time = 2_000_000
    span.attributes = {}
    return span


class _OK:
    def export(self, tenant_id, event):
        pass


class _Boom:
    def export(self, tenant_id, event):
        raise RuntimeError("sink down")


class _BadSpan:
    name = "bad"
    status = None

    @property
    def attributes(self):
        raise RuntimeError("boom")


def test_normalizer_counts_exports_errors_and_drops():
    reset_metrics()
    EventNormalizerProcessor(exporter=_OK()).on_end(_ok_span(0x9001, 0x9002))
    EventNormalizerProcessor(exporter=_Boom()).on_end(_ok_span(0x9003, 0x9004))
    EventNormalizerProcessor(exporter=_OK()).on_end(_BadSpan())

    m = get_metrics()
    assert m["events_exported"] == 1
    assert m["export_errors"] == 1
    assert m["events_dropped"] == 1
