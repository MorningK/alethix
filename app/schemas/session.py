"""会话相关 DTO。

字段与 prd/05-api-spec.md API-1 对齐。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.document import Citation


class SessionCreateRequest(BaseModel):
    """API-1 请求体。"""

    title: str | None = None
    default_document_ids: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    """API-1 响应。"""

    session_id: str
    title: str | None = None
    default_document_ids: list[str] = Field(default_factory=list)
    message_count: int = 0
    created_at: datetime | None = None


class MessageItem(BaseModel):
    """API-8 单条消息，assistant 消息携带置信度与引用。"""

    message_id: str
    role: str
    content: str
    created_at: datetime
    agent_run_id: str | None = None
    confidence: str | None = None
    citations: list[Citation] = Field(default_factory=list)
