import json
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src"),
)


def _make_span_with_sensitive_attrs():
    from lumen_ai.schema.semconv import (
        GenAIAttributes,
        LumenAIAttributes,
        OpenInferenceAttributes,
    )

    span = MagicMock()
    span.context.trace_id = 0xABCD
    span.context.span_id = 0x1234
    span.name = "privacy-check"
    span.start_time = 1_000_000_000
    span.end_time = 1_010_000_000
    span.status = MagicMock(status_code=0)
    span.attributes = {
        LumenAIAttributes.TENANT_ID: "tenant-private",
        GenAIAttributes.REQUEST_MODEL: "gpt-4o-mini",
        GenAIAttributes.USAGE_INPUT_TOKENS: 100,
        GenAIAttributes.USAGE_OUTPUT_TOKENS: 20,
        GenAIAttributes.TOOL_NAME: "search_docs",
        OpenInferenceAttributes.SPAN_KIND: "LLM",
        "gen_ai.prompt": "SECRET_PROMPT_TEXT",
        "gen_ai.completion": "SECRET_RESPONSE_TEXT",
        "tool.arguments": {"query": "SECRET_TOOL_ARG"},
        "http.request.body": "SECRET_RAW_BODY",
    }
    return span


def test_top_level_api_exports_stable_helpers():
    from lumen_ai import (
        AsyncRedisExporter,
        BaseLumenAIExporter,
        BasePricingProvider,
        DefaultPricingProvider,
        JsonlExporter,
        LumenAI,
        LumenAIEvent,
        RedisExporter,
        clear_tenant_id,
        get_tenant_id,
        lumen_tenant,
        set_tenant_id,
    )

    assert LumenAI is not None
    assert BaseLumenAIExporter is not None
    assert BasePricingProvider is not None
    assert DefaultPricingProvider is not None
    assert RedisExporter is not None
    assert AsyncRedisExporter is not None
    assert JsonlExporter is not None
    assert set_tenant_id is not None
    assert get_tenant_id is not None
    assert clear_tenant_id is not None
    assert lumen_tenant is not None
    assert "tenant_id" in LumenAIEvent.__annotations__
    assert "cost_usd" in LumenAIEvent.__annotations__


def test_event_normalizer_does_not_export_prompt_response_or_raw_payloads():
    from lumen_ai.processors.normalizer import EventNormalizerProcessor
    from lumen_ai.schema.event_types import LumenAIEvent

    captured: list[LumenAIEvent] = []

    class CaptureExporter:
        def export(self, tenant_id: str, event: LumenAIEvent) -> None:
            captured.append(event)

    processor = EventNormalizerProcessor(exporter=CaptureExporter())
    processor.on_end(_make_span_with_sensitive_attrs())

    assert len(captured) == 1
    event_json = json.dumps(captured[0], default=str)
    assert "SECRET_PROMPT_TEXT" not in event_json
    assert "SECRET_RESPONSE_TEXT" not in event_json
    assert "SECRET_TOOL_ARG" not in event_json
    assert "SECRET_RAW_BODY" not in event_json


def test_event_normalizer_preserves_explicit_cost_and_openinference_tokens():
    from lumen_ai.processors.normalizer import EventNormalizerProcessor
    from lumen_ai.schema.event_types import LumenAIEvent
    from lumen_ai.schema.semconv import LumenAIAttributes, OpenInferenceAttributes

    captured: list[LumenAIEvent] = []

    class CaptureExporter:
        def export(self, tenant_id: str, event: LumenAIEvent) -> None:
            captured.append(event)

    span = MagicMock()
    span.context.trace_id = 0xBEEF
    span.context.span_id = 0xCAFE
    span.name = "openinference-cost-fallback"
    span.start_time = 1_000_000_000
    span.end_time = 1_050_000_000
    span.status = MagicMock(status_code=0)
    span.attributes = {
        LumenAIAttributes.TENANT_ID: "tenant-fallback",
        LumenAIAttributes.COST_USD: 0.042,
        OpenInferenceAttributes.SPAN_KIND: "LLM",
        OpenInferenceAttributes.MODEL_NAME: "llm-only-model",
        OpenInferenceAttributes.TOKEN_COUNT_PROMPT: 1200,
        OpenInferenceAttributes.TOKEN_COUNT_COMPLETION: 300,
    }

    EventNormalizerProcessor(exporter=CaptureExporter()).on_end(span)

    assert captured[0]["tenant_id"] == "tenant-fallback"
    assert captured[0]["model"] == "llm-only-model"
    assert captured[0]["cost_usd"] == 0.042
    assert captured[0]["tokens_in"] == 1200
    assert captured[0]["tokens_out"] == 300


def test_lumenai_shutdown_closes_custom_exporter_once():
    from lumen_ai import LumenAI

    class CountingExporter:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def export(self, tenant_id: str, event: dict) -> None:
            return None

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    exporter = CountingExporter()
    LumenAI._initialized = False
    LumenAI.init(service_name="shutdown-contract", exporter=exporter)

    LumenAI.shutdown()

    assert exporter.shutdown_calls == 1
