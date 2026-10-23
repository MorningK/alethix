"""初始迁移：documents / chunks（M1 文档入库）

仅包含 M1 范围的两张表；sessions / agent_runs 等表由后续里程碑的迁移创建。
DDL 对齐 prd/04-data-model.md §3.2 / §3.3。
已知偏差：user_id 暂不建 users 外键（无 users 表，鉴权属 M6），届时补 FK 迁移。

Revision ID: 0001
Revises: None
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("source_format", sa.String(16), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("storage_path", sa.String(512), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(16), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('uploaded','parsing','chunking','embedding','ready','failed')",
            name="ck_documents_status",
        ),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    # 去重：同一用户的同一内容只允许一条有效记录（软删后释放，支撑并发同内容上传 B-8）
    op.create_index(
        "uq_documents_user_content",
        "documents",
        ["user_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # 列表查询：按用户 + 时间倒序
    op.create_index(
        "idx_documents_user_created",
        "documents",
        ["user_id", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_documents_status",
        "documents",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
    )
    op.create_index("ix_chunks_user_id", "chunks", ["user_id"])
    op.create_index("idx_chunks_document", "chunks", ["document_id"])


def downgrade() -> None:
    op.drop_index("idx_chunks_document", table_name="chunks")
    op.drop_index("ix_chunks_user_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("idx_documents_status", table_name="documents")
    op.drop_index("idx_documents_user_created", table_name="documents")
    op.drop_index("uq_documents_user_content", table_name="documents")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
