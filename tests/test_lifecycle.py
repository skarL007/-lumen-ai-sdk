"""
LumenAI lifecycle tests (operate on the real OTel global TracerProvider).

  * #4  OTel's set_tracer_provider is set-once. After init()->shutdown()->init()
        the global still pointed at the first (now shut-down) provider, so the
        second init() silently produced no telemetry. Re-init must install a
        fresh, live provider.
  * #11 If another library already installed a real SDK provider, init() called
        set_tracer_provider (ignored) and attached its processors to an orphan,
        producing zero events. init() must ADOPT the installed provider.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.util._once import Once

from lumen_ai import LumenAI


@pytest.fixture(autouse=True)
def _isolate_global_tracer_provider():
    """Give each test a clean set-once slate and restore the original after."""
    saved_tp = trace._TRACER_PROVIDER
    saved_once = trace._TRACER_PROVIDER_SET_ONCE
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    LumenAI._initialized = False
    LumenAI._provider = None
    LumenAI._exporter = None
    LumenAI._instrumentors = []
    yield
    LumenAI._initialized = False
    LumenAI._provider = None
    LumenAI._exporter = None
    LumenAI._instrumentors = []
    trace._TRACER_PROVIDER = saved_tp
    trace._TRACER_PROVIDER_SET_ONCE = saved_once


class _Capture:
    def __init__(self):
        self.events = []

    def export(self, tenant_id, event):
        self.events.append((tenant_id, event))

    def shutdown(self):
        pass


def _emit_one_llm_span():
    tracer = trace.get_tracer("lifecycle-test")
    with tracer.start_as_current_span("op") as span:
        span.set_attribute("openinference.span.kind", "LLM")


def test_reinit_after_shutdown_emits_events_again():
    LumenAI.init(service_name="t1", default_tenant="a", exporter=_Capture())
    LumenAI.shutdown()

    cap2 = _Capture()
    LumenAI.init(service_name="t2", default_tenant="acme", exporter=cap2)
    _emit_one_llm_span()
    LumenAI.shutdown()

    assert cap2.events, "re-init produced no events — telemetry pointed at the dead provider"


def test_reinit_installs_a_fresh_provider():
    LumenAI.init(service_name="t1", default_tenant="a")
    p1 = trace.get_tracer_provider()
    assert isinstance(p1, TracerProvider)
    LumenAI.shutdown()

    LumenAI.init(service_name="t2", default_tenant="a")
    p2 = trace.get_tracer_provider()
    assert isinstance(p2, TracerProvider)
    assert p2 is not p1
    LumenAI.shutdown()


def test_init_adopts_externally_installed_provider():
    external = TracerProvider()
    trace.set_tracer_provider(external)

    cap = _Capture()
    LumenAI.init(service_name="t", default_tenant="acme", exporter=cap)

    # Did not orphan a different provider, and our pipeline runs on the external one.
    assert trace.get_tracer_provider() is external
    _emit_one_llm_span()
    LumenAI.shutdown()
    assert cap.events, "processors were attached to an orphan, not the installed provider"
