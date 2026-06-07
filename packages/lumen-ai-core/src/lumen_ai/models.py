"""
LumenAI Master ORM Models — SQLAlchemy declarative models for LumenAI_* tables.

All tables are prefixed with LumenAI_ to avoid collisions with existing schema.
Every table has tenant_id (NOT NULL) for multi-tenant isolation.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LumenAISession(Base):
    __tablename__ = "LumenAI_sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    run_id = Column(String(64), default="")
    goal = Column(Text, default="")
    status = Column(String(20), default="running")  # pending|running|completed|failed
    started_at = Column(DateTime, default=_utcnow)
    ended_at = Column(DateTime, nullable=True)
    cost_usd_total = Column(Float, default=0.0)
    token_in_total = Column(Integer, default=0)
    token_out_total = Column(Integer, default=0)
    agent_count = Column(Integer, default=0)
    tool_call_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default=dict)

    # Relationships
    agents = relationship("LumenAIAgent", back_populates="session", cascade="all, delete-orphan")
    events = relationship("LumenAIEventRow", back_populates="session", cascade="all, delete-orphan")
    artifacts = relationship("LumenAIArtifact", back_populates="session", cascade="all, delete-orphan")
    approvals = relationship("LumenAIApproval", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_LumenAI_session_tenant_status", "tenant_id", "status"),
    )


class LumenAIAgent(Base):
    __tablename__ = "LumenAI_agents"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("LumenAI_sessions.id"), nullable=False)
    parent_agent_id = Column(String(36), ForeignKey("LumenAI_agents.id"), nullable=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    trace_id = Column(String(64), default="")
    parent_tool_use_id = Column(String(64), default="")
    name = Column(String(128), default="")
    type = Column(String(20), default="agent")  # agent|subagent|task|chain
    provider = Column(String(32), default="")   # anthropic|openai|ollama|celery
    model = Column(String(64), default="")
    role = Column(String(64), default="")
    status = Column(String(20), default="running")
    started_at = Column(DateTime, default=_utcnow)
    ended_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    current_tool = Column(String(128), default="")
    context_summary = Column(JSON, default=dict)

    # Relationships
    session = relationship("LumenAISession", back_populates="agents")
    children = relationship("LumenAIAgent", backref="parent", remote_side=[id])
    events = relationship("LumenAIEventRow", back_populates="agent", cascade="all, delete-orphan")
    artifacts = relationship("LumenAIArtifact", back_populates="agent", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_LumenAI_agent_session", "session_id"),
        Index("idx_LumenAI_agent_tenant", "tenant_id"),
    )


class LumenAIEventRow(Base):
    __tablename__ = "LumenAI_events"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("LumenAI_sessions.id"), nullable=False)
    agent_id = Column(String(36), ForeignKey("LumenAI_agents.id"), nullable=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    trace_id = Column(String(64), default="")
    span_id = Column(String(32), default="")
    sequence = Column(Integer, default=0)
    timestamp = Column(DateTime, default=_utcnow)
    event_type = Column(String(40), nullable=False)
    severity = Column(String(10), default="INFO")
    message = Column(Text, default="")
    payload = Column(JSON, default=dict)
    duration_ms = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    is_error = Column(Boolean, default=False)
    tool_name = Column(String(128), default="")
    error_message = Column(Text, default="")
    model = Column(String(64), default="")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)

    # Relationships
    session = relationship("LumenAISession", back_populates="events")
    agent = relationship("LumenAIAgent", back_populates="events")

    __table_args__ = (
        Index("idx_LumenAI_event_session_seq", "session_id", "sequence"),
        Index("idx_LumenAI_event_tenant_type", "tenant_id", "event_type"),
        Index("idx_LumenAI_event_timestamp", "timestamp"),
    )


class LumenAIArtifact(Base):
    __tablename__ = "LumenAI_artifacts"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("LumenAI_sessions.id"), nullable=False)
    agent_id = Column(String(36), ForeignKey("LumenAI_agents.id"), nullable=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    type = Column(String(20), default="code")  # code|doc|plan|report|test|diff
    name = Column(String(255), default="")
    uri = Column(Text, default="")
    version = Column(Integer, default=1)
    status = Column(String(20), default="draft")  # draft|approved|rejected
    diff_ref = Column(Text, default="")
    preview = Column(JSON, default=dict)
    metadata_ = Column("metadata", JSON, default=dict)

    # Relationships
    session = relationship("LumenAISession", back_populates="artifacts")
    agent = relationship("LumenAIAgent", back_populates="artifacts")

    __table_args__ = (
        Index("idx_LumenAI_artifact_session", "session_id"),
        Index("idx_LumenAI_artifact_tenant", "tenant_id"),
    )


class LumenAIApproval(Base):
    __tablename__ = "LumenAI_approvals"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("LumenAI_sessions.id"), nullable=False)
    agent_id = Column(String(36), ForeignKey("LumenAI_agents.id"), nullable=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    type = Column(String(40), default="")
    status = Column(String(20), default="pending")  # pending|approved|rejected
    requested_at = Column(DateTime, default=_utcnow)
    resolved_at = Column(DateTime, nullable=True)
    justification = Column(Text, default="")
    artifact_ref = Column(String(255), default="")
    context = Column(JSON, default=dict)
    resolved_by = Column(String(128), default="")

    # Relationships
    session = relationship("LumenAISession", back_populates="approvals")

    __table_args__ = (
        Index("idx_LumenAI_approval_tenant_status", "tenant_id", "status"),
    )


class LumenAIReport(Base):
    __tablename__ = "LumenAI_reports"

    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    type = Column(String(20), default="daily")  # daily|weekly|session
    session_id = Column(String(36), nullable=True)
    generated_at = Column(DateTime, default=_utcnow)
    file_path = Column(Text, default="")
    size_bytes = Column(Integer, default=0)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    summary = Column(JSON, default=dict)

    __table_args__ = (
        Index("idx_LumenAI_report_tenant_type", "tenant_id", "type"),
    )
