import builtins
import os
import sys
import types
from unittest.mock import MagicMock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src"),
)
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-openlit", "src"),
)
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-celery", "src"),
)


def test_openlit_bridge_passes_supported_init_kwargs(monkeypatch):
    from lumen_ai_openlit import OpenLITBridge

    calls: list[dict] = []

    def fake_init(
        tracer_provider=None,
        collect_gpu_stats=False,
        disable_batch=False,
        pricing_json=None,
    ):
        calls.append(
            {
                "tracer_provider": tracer_provider,
                "collect_gpu_stats": collect_gpu_stats,
                "disable_batch": disable_batch,
                "pricing_json": pricing_json,
            }
        )

    monkeypatch.setitem(sys.modules, "openlit", types.SimpleNamespace(init=fake_init))

    tracer_provider = object()
    bridge = OpenLITBridge(
        collect_gpu_stats=True,
        disable_batch=True,
        pricing_json="pricing.json",
    )
    bridge._instrument(tracer_provider=tracer_provider)

    assert calls == [
        {
            "tracer_provider": tracer_provider,
            "collect_gpu_stats": True,
            "disable_batch": True,
            "pricing_json": "pricing.json",
        }
    ]


def test_celery_signal_handlers_track_success_without_worker():
    from lumen_ai_celery.instrumentor import CeleryInstrumentor, _active_spans

    span = MagicMock()
    tracer = MagicMock()
    tracer.start_span.return_value = span

    instrumentor = CeleryInstrumentor()
    instrumentor._tracer = tracer

    task = MagicMock(name="Task")
    task.name = "demo.task"

    _active_spans.clear()
    instrumentor._on_task_prerun(task_id="task-1", task=task, kwargs={"tenant_id": "acme"})
    assert "task-1" in _active_spans

    instrumentor._on_task_postrun(
        task_id="task-1",
        task=task,
        retval={"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.001},
        state="SUCCESS",
    )

    assert "task-1" not in _active_spans
    span.end.assert_called_once()


def test_celery_signal_handlers_track_failure_without_worker():
    from lumen_ai_celery.instrumentor import CeleryInstrumentor, _active_spans

    span = MagicMock()
    tracer = MagicMock()
    tracer.start_span.return_value = span

    instrumentor = CeleryInstrumentor()
    instrumentor._tracer = tracer

    task = MagicMock(name="Task")
    task.name = "demo.failing_task"
    error = RuntimeError("simulated task failure")

    _active_spans.clear()
    instrumentor._on_task_prerun(task_id="task-2", task=task, kwargs={"tenant_id": "acme"})
    instrumentor._on_task_failure(task_id="task-2", exception=error)

    assert "task-2" not in _active_spans
    span.record_exception.assert_called_once_with(error)
    span.end.assert_called_once()


def test_openlit_bridge_missing_dependency_does_not_raise(monkeypatch):
    from lumen_ai_openlit import OpenLITBridge

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openlit":
            raise ImportError("openlit unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    bridge = OpenLITBridge()
    bridge._instrument(tracer_provider=object())

    assert bridge._initialized is False
