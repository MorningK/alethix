"""DM-6 agent_runs / DM-7 iterations / DM-8 answers / DM-9 citations。

DDL 见 prd/04-data-model.md §3。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

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
    findings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    conflicts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class Answer(Base):
    """DM-8 最终答案。"""

    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(16))
    stop_reason: Mapped[str | None] = mapped_column(String(32))


class Citation(Base, TimestampMixin):
    """DM-9 答案引用。quote 由服务层按 chunk_id 取原文，不信任模型摘录。"""

    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    answer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("answers.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    document_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    chunk_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(512))
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column()
