"""
Run one real LLM-SDK call under one real instrumentation library and print the
LumenAI events as JSON lines. The provider is a mocked HTTP transport, so no
key or network is needed. Used by test_real_instrumentations.py in a fresh
process, because instrumentors patch the SDKs globally.

Usage: python _instrumented_call.py <openai|anthropic> <instrumentation> [cache_write]
"""
import json
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-openlit", "src")
)

from lumen_ai import LumenAI, lumen_tenant  # noqa: E402

SDK, INSTRUMENTATION = sys.argv[1], sys.argv[2]
CACHE_WRITE = 500 if len(sys.argv) > 3 and sys.argv[3] == "cache_write" else 0

OPENAI_BODY = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 1761600000,
    "model": "gpt-4o-mini-2024-07-18",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500,
              "prompt_tokens_details": {"cached_tokens": 1000}},
}
ANTHROPIC_BODY = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 200, "output_tokens": 300, "cache_read_input_tokens": 1000,
              "cache_creation_input_tokens": CACHE_WRITE},
}


class _Capture:
    def __init__(self):
        self.events = []

    def export(self, tenant_id, event):
        self.events.append(event)

    def shutdown(self):
        pass


def _mock_client(sdk_module, body):
    """The SDK's client on a mocked transport; newer SDKs ship on httpx2."""
    for transport_lib in ("httpx", "httpx2"):
        try:
            lib = __import__(transport_lib)
            client = lib.Client(transport=lib.MockTransport(lambda request: lib.Response(200, json=body)))
            if sdk_module.__name__ == "openai":
                return sdk_module.OpenAI(api_key="test", http_client=client)
            return sdk_module.Anthropic(api_key="test", http_client=client)
        except (ImportError, TypeError):
            continue
    raise RuntimeError("no usable HTTP client library")


capture = _Capture()
instrumentors = []
if INSTRUMENTATION == "openlit":
    from lumen_ai_openlit import OpenLITBridge
    instrumentors = [OpenLITBridge(disable_batch=True)]
LumenAI.init(service_name="real-instrumentation", exporter=capture, genai_only=True,
             instrumentors=instrumentors)
provider = LumenAI._provider

instrumentor = None
if INSTRUMENTATION == "openinference":
    if SDK == "openai":
        from openinference.instrumentation.openai import (
            OpenAIInstrumentor as Instrumentor,
        )
    else:
        from openinference.instrumentation.anthropic import (
            AnthropicInstrumentor as Instrumentor,
        )
    instrumentor = Instrumentor()
elif INSTRUMENTATION == "traceloop":
    if SDK == "openai":
        from opentelemetry.instrumentation.openai import (
            OpenAIInstrumentor as Instrumentor,
        )
    else:
        from opentelemetry.instrumentation.anthropic import (
            AnthropicInstrumentor as Instrumentor,
        )
    instrumentor = Instrumentor()
elif INSTRUMENTATION == "otel-v2":
    from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
    instrumentor = OpenAIInstrumentor()
if instrumentor is not None:
    instrumentor.instrument(tracer_provider=provider)
    # Instrumentors refuse SDK versions outside their range; nothing to test then.
    if not instrumentor.is_instrumented_by_opentelemetry:
        print("SKIP: instrumentation does not support the installed SDK version")
        sys.exit(3)

if SDK == "openai":
    import openai
    client = _mock_client(openai, OPENAI_BODY)
    with lumen_tenant("acme"):
        client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
else:
    import anthropic
    client = _mock_client(anthropic, ANTHROPIC_BODY)
    with lumen_tenant("acme"):
        client.messages.create(model="claude-sonnet-4-6", max_tokens=64,
                               messages=[{"role": "user", "content": "hi"}])

provider.force_flush()
for event in capture.events:
    print("LUMEN_EVENT " + json.dumps(event))
