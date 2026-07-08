"""
CeleryInstrumentor lifecycle edge cases.

  * A task that starts (prerun) but is REVOKED or whose worker is killed never
    fires postrun/failure, so its span + context token leaked forever (#16).
  * A None task_id created a bogus _active_spans[None] entry.
"""
import os
import sys
import types
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-celery", "src")
)


def _instrumentor_with_tracer():
    from lumen_ai_celery.instrumentor import CeleryInstrumentor

    span = MagicMock()
    tracer = MagicMock()
    tracer.start_span.return_value = span
    inst = CeleryInstrumentor()
    inst._tracer = tracer
    return inst, span


def test_revoked_task_ends_span_and_frees_entry():
    from lumen_ai_celery.instrumentor import _active_spans

    inst, span = _instrumentor_with_tracer()
    task = MagicMock()
    task.name = "demo.task"

    _active_spans.clear()
    inst._on_task_prerun(task_id="task-r", task=task, kwargs={"tenant_id": "acme"})
    assert "task-r" in _active_spans

    inst._on_task_revoked(request=types.SimpleNamespace(id="task-r"))

    assert "task-r" not in _active_spans
    span.end.assert_called_once()


def test_worker_shutdown_ends_all_active_spans():
    from lumen_ai_celery.instrumentor import _active_spans

    inst, span = _instrumentor_with_tracer()
    task = MagicMock()
    task.name = "demo.task"

    _active_spans.clear()
    inst._on_task_prerun(task_id="task-w", task=task, kwargs={})
    assert "task-w" in _active_spans

    inst._on_worker_shutdown()

    assert "task-w" not in _active_spans
    span.end.assert_called_once()


def test_prerun_with_none_task_id_creates_no_entry():
    from lumen_ai_celery.instrumentor import _active_spans

    inst, span = _instrumentor_with_tracer()
    task = MagicMock()
    task.name = "demo.task"

    _active_spans.clear()
    inst._on_task_prerun(task_id=None, task=task, kwargs={})

    assert None not in _active_spans
    assert len(_active_spans) == 0


def test_prerun_sanitizes_tenant_from_kwargs():
    inst, span = _instrumentor_with_tracer()
    task = MagicMock()
    task.name = "demo.task"

    inst._on_task_prerun(task_id="task-s", task=task, kwargs={"tenant_id": "ac\nme\t"})

    span.set_attribute.assert_any_call("LumenAI.tenant_id", "acme")
