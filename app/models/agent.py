"""DM-6 agent_runs / DM-7 iterations / DM-8 answers / DM-9 citations。

DDL 见 prd/04-data-model.md §3。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

_STOP_REASONS = (
    "sufficient",
    "max_iterations_reached",
    "no_new_queries",
    "no_new_evidence",
    "low_relevance",
    "budget_exceeded",
    "internal_error",
)


class AgentRun(Base):
    """DM-6 调研运行，承载可观测性与成本归因。"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','done','failed')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN "
            "('sufficient','max_iterations_reached','no_new_queries',"
            "'no_new_evidence','low_relevance','budget_exceeded','internal_error')",
            name="ck_agent_runs_stop_reason",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    message_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("messages.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    document_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(32))

    iteration_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retrieved_chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    citation_filtered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fallback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(16))
    error_message: Mapped[str | None] = mapped_column(Text)


class Iteration(Base):
    """DM-7 单轮迭代记录。"""

    __tablename__ = "iterations"
    __table_args__ = (
        CheckConstraint("decision IN ('continue','answer')", name="ck_iterations_decision"),
        UniqueConstraint("agent_run_id", "iteration", name="uq_iterations_run_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    queries: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    retrieved_chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_score: Mapped[float | None] = mapped_column(Float)
    findings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    conflicts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    missing_information: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Answer(Base):
    """DM-8 最终答案。"""

    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint(
            "confidence IN ('high','medium','low')",
            name="ck_answers_confidence",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Citation(Base):
    """DM-9 答案引用。quote 由服务层按 chunk_id 取原文，不信任模型摘录。"""

    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    answer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("answers.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(512))
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
