"""M2 迁移：sessions / messages / agent_runs / iterations / answers / citations。

DDL 对齐 prd/04-data-model.md §3.4 ~ §3.9；表名、列名与 app.models 保持一致。
已知偏差：user_id 暂不建 users 外键（无 users 表，鉴权属 M6）。

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column(
            "default_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index(
        "idx_sessions_user_updated",
        "sessions",
        ["user_id", "updated_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_messages_role"),
        sa.UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),
    )
    op.create_index("idx_messages_session_created", "messages", ["session_id", "created_at"])
    op.create_index(
        "idx_messages_agent_run",
        "messages",
        ["agent_run_id"],
        postgresql_where=sa.text("agent_run_id IS NOT NULL"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "message_id",
            sa.BigInteger(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("max_iterations", sa.Integer(), server_default="3", nullable=False),
        sa.Column("status", sa.String(16), server_default="running", nullable=False),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.Column("iteration_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retrieved_chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("citation_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("citation_filtered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("token_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_call_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fallback_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(16), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','done','failed')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN "
            "('sufficient','max_iterations_reached','no_new_queries',"
            "'no_new_evidence','low_relevance','budget_exceeded','internal_error')",
            name="ck_agent_runs_stop_reason",
        ),
    )
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("idx_agent_runs_user_created", "agent_runs", ["user_id", "created_at"])
    op.create_index("idx_agent_runs_session", "agent_runs", ["session_id", "created_at"])
    op.create_index("idx_agent_runs_stop_reason", "agent_runs", ["stop_reason", "created_at"])

    op.create_table(
        "iterations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column(
            "queries",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("retrieved_chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new_chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column(
            "findings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conflicts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("missing_information", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("decision IN ('continue','answer')", name="ck_iterations_decision"),
        sa.UniqueConstraint("agent_run_id", "iteration", name="uq_iterations_run_index"),
    )

    op.create_table(
        "answers",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IN ('high','medium','low')",
            name="ck_answers_confidence",
        ),
    )
    op.create_index("idx_answers_session", "answers", ["session_id", "created_at"])

    op.create_table(
        "citations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "answer_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(512), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_citations_answer", "citations", ["answer_id", "ordinal"])
    op.create_index("idx_citations_chunk", "citations", ["chunk_id"])
    op.create_index("idx_citations_document", "citations", ["document_id"])


def downgrade() -> None:
    op.drop_index("idx_citations_document", table_name="citations")
    op.drop_index("idx_citations_chunk", table_name="citations")
    op.drop_index("idx_citations_answer", table_name="citations")
    op.drop_table("citations")

    op.drop_index("idx_answers_session", table_name="answers")
    op.drop_table("answers")

    op.drop_table("iterations")

    op.drop_index("idx_agent_runs_stop_reason", table_name="agent_runs")
    op.drop_index("idx_agent_runs_session", table_name="agent_runs")
    op.drop_index("idx_agent_runs_user_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("idx_messages_agent_run", table_name="messages")
    op.drop_index("idx_messages_session_created", table_name="messages")
    op.drop_table("messages")

    op.drop_index("idx_sessions_user_updated", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
