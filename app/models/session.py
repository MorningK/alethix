"""DM-4 sessions / DM-5 messages。

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


class Session(Base, TimestampMixin):
    """DM-4 会话。"""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    default_document_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)  # 占位，M2 改为 DateTime


class Message(Base):
    """DM-5 会话消息。"""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_messages_role"),
        UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
