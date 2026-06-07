"""
Normalizer event-type + error detection.

  * #17 _is_error compared status_code against the int 2, but StatusCode.ERROR
        is an enum member (!= 2), so that clause was dead and mock/shim spans
        with an ERROR status were reported as success.
  * #24 EMBEDDING / RETRIEVER / RERANKER spans fell through to AGENT_COMPLETED,
        mis-bucketing RAG cost. They get their own event types.
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from opentelemetry.trace import StatusCode

from lumen_ai.processors.normalizer import _is_error, _span_to_event_type
from lumen_ai.schema.event_types import EventType
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes


def _span(span_kind=None, op_name=None, status_code=StatusCode.OK):
    span = MagicMock()
    attrs = {}
    if span_kind is not None:
        attrs[OpenInferenceAttributes.SPAN_KIND] = span_kind
    if op_name is not None:
        attrs[GenAIAttributes.OPERATION_NAME] = op_name
    span.attributes = attrs
    span.status = MagicMock(status_code=status_code)
    return span


def test_error_status_enum_is_detected():
    assert _is_error(_span(status_code=StatusCode.ERROR)) is True


def test_ok_status_is_not_error():
    s = _span(status_code=StatusCode.OK)
    s.status = MagicMock(status_code=StatusCode.OK, is_ok=True)
    assert _is_error(s) is False


def test_embedding_span_maps_to_embedding_event():
    assert _span_to_event_type(_span(span_kind="EMBEDDING")) == EventType.EMBEDDING_COMPLETED
    assert _span_to_event_type(_span(op_name="embedding")) == EventType.EMBEDDING_COMPLETED


def test_retriever_and_reranker_map_to_rag_events():
    assert _span_to_event_type(_span(span_kind="RETRIEVER")) == EventType.RETRIEVAL_COMPLETED
    assert _span_to_event_type(_span(span_kind="RERANKER")) == EventType.RERANK_COMPLETED


def test_embedding_error_maps_to_embedding_failed():
    span = _span(span_kind="EMBEDDING", status_code=StatusCode.ERROR)
    assert _span_to_event_type(span) == EventType.EMBEDDING_FAILED


def test_llm_span_still_maps_to_llm():
    assert _span_to_event_type(_span(span_kind="LLM")) == EventType.LLM_CALL_COMPLETED
    assert _span_to_event_type(_span(op_name="chat")) == EventType.LLM_CALL_COMPLETED
