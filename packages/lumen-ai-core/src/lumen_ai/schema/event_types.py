"""
Canonical Event Types — 40+ event types for agent observability.

Each event type maps to a specific point in an agent's lifecycle.
"""


from typing import TypedDict


class LumenAIEvent(TypedDict):
    """Normalized metadata-only event emitted by LumenAI exporters."""

    id: str
    tenant_id: str
    session_id: str
    agent_id: str
    trace_id: str
    span_id: str
    timestamp: str
    event_type: str
    severity: str
    message: str
    duration_ms: int
    is_error: bool
    cost_usd: float
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    model: str
    tool_name: str
    span_kind: str


class EventType:
    """All canonical event types emitted by LumenAI Master instrumentors."""

    # ─── Session lifecycle ────────────────────────────────────────────────
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    SESSION_FAILED = "SESSION_FAILED"
    SESSION_TIMEOUT = "SESSION_TIMEOUT"

    # ─── Agent lifecycle ──────────────────────────────────────────────────
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED = "AGENT_FAILED"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_RETRY = "AGENT_RETRY"

    # ─── Subagent delegation ──────────────────────────────────────────────
    SUBAGENT_SPAWNED = "SUBAGENT_SPAWNED"
    SUBAGENT_COMPLETED = "SUBAGENT_COMPLETED"
    SUBAGENT_FAILED = "SUBAGENT_FAILED"
    HANDOFF_STARTED = "HANDOFF_STARTED"
    HANDOFF_COMPLETED = "HANDOFF_COMPLETED"

    # ─── LLM calls ───────────────────────────────────────────────────────
    LLM_CALL_STARTED = "LLM_CALL_STARTED"
    LLM_CALL_COMPLETED = "LLM_CALL_COMPLETED"
    LLM_CALL_FAILED = "LLM_CALL_FAILED"
    LLM_CALL_CACHED = "LLM_CALL_CACHED"
    LLM_STREAMING_STARTED = "LLM_STREAMING_STARTED"
    LLM_STREAMING_TOKEN = "LLM_STREAMING_TOKEN"
    LLM_STREAMING_COMPLETED = "LLM_STREAMING_COMPLETED"

    # ─── Retrieval / RAG ──────────────────────────────────────────────────
    EMBEDDING_COMPLETED = "EMBEDDING_COMPLETED"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    RETRIEVAL_COMPLETED = "RETRIEVAL_COMPLETED"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    RERANK_COMPLETED = "RERANK_COMPLETED"
    RERANK_FAILED = "RERANK_FAILED"

    # ─── Tool calls ──────────────────────────────────────────────────────
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_CALL_COMPLETED = "TOOL_CALL_COMPLETED"
    TOOL_CALL_FAILED = "TOOL_CALL_FAILED"
    TOOL_CALL_REJECTED = "TOOL_CALL_REJECTED"

    # ─── Artifacts ────────────────────────────────────────────────────────
    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    ARTIFACT_UPDATED = "ARTIFACT_UPDATED"
    ARTIFACT_APPROVED = "ARTIFACT_APPROVED"
    ARTIFACT_REJECTED = "ARTIFACT_REJECTED"

    # ─── Approvals (human-in-the-loop) ────────────────────────────────────
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"

    # ─── Memory / Context ─────────────────────────────────────────────────
    MEMORY_READ = "MEMORY_READ"
    MEMORY_WRITE = "MEMORY_WRITE"
    CONTEXT_UPDATED = "CONTEXT_UPDATED"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"

    # ─── Celery / Task queue ──────────────────────────────────────────────
    TASK_QUEUED = "TASK_QUEUED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_RETRIED = "TASK_RETRIED"
    TASK_REVOKED = "TASK_REVOKED"

    # ─── System / Observability ───────────────────────────────────────────
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    COST_THRESHOLD_EXCEEDED = "COST_THRESHOLD_EXCEEDED"
    LATENCY_SPIKE = "LATENCY_SPIKE"
    ERROR_RATE_SPIKE = "ERROR_RATE_SPIKE"


class Severity:
    """Log severity levels for events."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
