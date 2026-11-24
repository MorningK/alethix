"""会话相关 DTO。

字段与 prd/05-api-spec.md API-1 对齐。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
