import os
import sys
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from lumen_ai.processors.normalizer import EventNormalizerProcessor
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes


class _Capture:
    def __init__(self):
        self.events = []

    def export(self, tenant_id, event):
        self.events.append(event)


def _span(attrs):
    span = MagicMock()
    span.context.trace_id = 0xDAD1
    span.context.span_id = 0xDAD2
    span.name = "metadata"
    span.start_time = 1_000_000
    span.end_time = 2_000_000
    span.status = MagicMock(status_code=0)
    span.attributes = attrs
    return span


def test_openinference_only_span_preserves_model_and_tokens():
    cap = _Capture()
    EventNormalizerProcessor(exporter=cap).on_end(
        _span(
            {
                OpenInferenceAttributes.SPAN_KIND: "LLM",
                OpenInferenceAttributes.MODEL_NAME: "gpt-4o-mini",
                OpenInferenceAttributes.TOKEN_COUNT_PROMPT: 1200,
                OpenInferenceAttributes.TOKEN_COUNT_COMPLETION: 300,
            }
        )
    )

    event = cap.events[0]
    assert event["model"] == "gpt-4o-mini"
    assert event["tokens_in"] == 1200
    assert event["tokens_out"] == 300
    assert event["cost_usd"] == 0.0


def test_unknown_priced_model_preserves_metadata_with_zero_cost():
    cap = _Capture()
    EventNormalizerProcessor(exporter=cap).on_end(
        _span(
            {
                OpenInferenceAttributes.SPAN_KIND: "LLM",
                GenAIAttributes.REQUEST_MODEL: "new-provider/new-model",
                GenAIAttributes.USAGE_INPUT_TOKENS: 10,
                GenAIAttributes.USAGE_OUTPUT_TOKENS: 2,
            }
        )
    )

    event = cap.events[0]
    assert event["model"] == "new-provider/new-model"
    assert event["tokens_in"] == 10
    assert event["tokens_out"] == 2
    assert event["cost_usd"] == 0.0

