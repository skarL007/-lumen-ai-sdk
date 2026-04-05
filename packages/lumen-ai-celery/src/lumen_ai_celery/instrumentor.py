"""
CeleryInstrumentor — passively observes Celery task lifecycle via signals.

Uses Celery's built-in signal system (task_prerun, task_postrun, task_failure)
to create OTel spans without modifying any existing task code.
"""
import logging
import time

from opentelemetry import trace
from opentelemetry.trace import StatusCode

from LumenAI.sdk import BaseInstrumentor
from LumenAI.schema.semconv import (
    GenAIAttributes,
    OpenInferenceAttributes,
    LumenAIAttributes,
    SpanKind,
)

logger = logging.getLogger(__name__)

# In-flight span tracking: task_id → (span, context_token, start_time)
_active_spans: dict[str, tuple] = {}


class CeleryInstrumentor(BaseInstrumentor):
    """
    Instruments Celery tasks via signal hooks (read-only, zero code modification).

    Captures:
    - task_prerun → start CHAIN span
    - task_postrun → end span (success)
    - task_failure → end span (error)
    """

    def __init__(self):
        self._tracer = None
        self._connected = False

    def instrumentation_dependencies(self) -> list[str]:
        return ["celery >= 5.0"]

    def _instrument(self, tracer_provider=None, **kwargs):
        if self._connected:
            return

        from celery.signals import task_prerun, task_postrun, task_failure

        self._tracer = trace.get_tracer("LumenAI-master-celery")

        task_prerun.connect(self._on_task_prerun, weak=False)
        task_postrun.connect(self._on_task_postrun, weak=False)
        task_failure.connect(self._on_task_failure, weak=False)

        self._connected = True
        logger.info("CeleryInstrumentor: signal hooks connected")

    def _uninstrument(self, **kwargs):
        if not self._connected:
            return

        from celery.signals import task_prerun, task_postrun, task_failure

        task_prerun.disconnect(self._on_task_prerun)
        task_postrun.disconnect(self._on_task_postrun)
        task_failure.disconnect(self._on_task_failure)

        self._connected = False
        _active_spans.clear()
        logger.info("CeleryInstrumentor: signal hooks disconnected")

    def _on_task_prerun(self, sender=None, task_id=None, task=None,
                        args=None, kwargs=None, **extra):
        """Called before a task executes — start a CHAIN span."""
        if not self._tracer:
            return

        task_name = getattr(task, "name", str(sender)) if task else str(sender)

        span = self._tracer.start_span(
            name=f"celery.{task_name}",
            attributes={
                OpenInferenceAttributes.SPAN_KIND: SpanKind.CHAIN,
                GenAIAttributes.OPERATION_NAME: "execute_agent",
                "celery.task.name": task_name,
                "celery.task.id": task_id or "",
            },
        )

        # Extract tenant_id from task kwargs if passed
        tenant_id = ""
        if kwargs and isinstance(kwargs, dict):
            tenant_id = kwargs.get("tenant_id", "")
        if tenant_id:
            span.set_attribute(LumenAIAttributes.TENANT_ID, tenant_id)

        ctx_token = trace.context_api.attach(trace.set_span_in_context(span))
        _active_spans[task_id] = (span, ctx_token, time.monotonic())

        logger.debug("Celery span started: %s (task_id=%s)", task_name, task_id)

    def _on_task_postrun(self, sender=None, task_id=None, task=None,
                         retval=None, state=None, **extra):
        """Called after a task completes — end the span."""
        entry = _active_spans.pop(task_id, None)
        if not entry:
            return

        span, ctx_token, start_time = entry
        duration_ms = int((time.monotonic() - start_time) * 1000)

        span.set_attribute("celery.task.state", state or "SUCCESS")
        span.set_attribute("duration_ms", duration_ms)

        # Extract cost/token info from retval if it's a dict
        if isinstance(retval, dict):
            if "cost_usd" in retval:
                span.set_attribute(LumenAIAttributes.COST_USD, retval["cost_usd"])
            if "tokens_in" in retval:
                span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, retval["tokens_in"])
            if "tokens_out" in retval:
                span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, retval["tokens_out"])

        span.set_status(StatusCode.OK)
        span.end()
        trace.context_api.detach(ctx_token)

        logger.debug("Celery span ended: task_id=%s duration=%dms", task_id, duration_ms)

    def _on_task_failure(self, sender=None, task_id=None, exception=None,
                         traceback=None, **extra):
        """Called when a task fails — end span with error status."""
        entry = _active_spans.pop(task_id, None)
        if not entry:
            return

        span, ctx_token, start_time = entry
        duration_ms = int((time.monotonic() - start_time) * 1000)

        span.set_attribute("celery.task.state", "FAILURE")
        span.set_attribute("duration_ms", duration_ms)
        span.set_status(StatusCode.ERROR, description=str(exception) if exception else "Task failed")

        if exception:
            span.record_exception(exception)

        span.end()
        trace.context_api.detach(ctx_token)

        logger.debug("Celery span failed: task_id=%s error=%s", task_id, exception)
