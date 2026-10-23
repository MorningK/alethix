"""DM-2 documents / DM-3 chunks。

DDL 见 prd/04-data-model.md §3。本阶段仅定义 ORM 占位，
迁移脚本随 M1 生成。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# 软删后依然有效的部分索引条件（prd/04-data-model.md §3.2）
_NOT_DELETED = text("deleted_at IS NULL")


class Document(Base, TimestampMixin):
    """DM-2 文档主表。"""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','parsing','chunking','embedding','ready','failed')",
            name="ck_documents_status",
        ),
        # 同一用户的同一内容只允许一条有效记录（软删后释放）
        Index(
            "uq_documents_user_content",
            "user_id",
            "content_hash",
            unique=True,
            postgresql_where=_NOT_DELETED,
        ),
        # 列表查询：按用户 + 时间倒序 + 状态过滤
        Index("idx_documents_user_created", "user_id", "created_at", postgresql_where=_NOT_DELETED),
        Index("idx_documents_status", "status", postgresql_where=_NOT_DELETED),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    source_format: Mapped[str | None] = mapped_column(String(16))
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    storage_path: Mapped[str | None] = mapped_column(String(512))
    title: Mapped[str | None] = mapped_column(String(512))

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploaded")
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(16))
    error_message: Mapped[str | None] = mapped_column(Text)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(Base):
    """DM-3 文档切片。id 同时作为 Qdrant Point ID。"""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index("idx_chunks_document", "document_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(512))
    # 与 prd/04-data-model.md §3.3 对齐：chunks 只有 created_at，无 updated_at
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
