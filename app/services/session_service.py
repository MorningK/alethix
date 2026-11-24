"""会话服务。

职责：会话与消息管理（DM-4 / DM-5）。
追问的指代消解属于 M4 范围，暂不在本服务实现。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_SESSION_PARAM, ApiError
from app.models.document import Document
from app.models.session import Session
from app.schemas.session import SessionCreateRequest, SessionResponse


def _normalize_document_ids(document_ids: list[str], max_count: int = 20) -> list[str]:
    """校验并归一化文档 UUID，set 查重保序，超过上限立即拒绝。"""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in document_ids:
        try:
            value = str(uuid.UUID(str(raw)))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ApiError(ERR_SESSION_PARAM, "默认文档 ID 不是合法 UUID", status=400) from exc
        if value in seen:
            continue
        if len(seen) >= max_count:
            raise ApiError(ERR_SESSION_PARAM, "会话默认文档不能超过 20 篇", status=400)
        seen.add(value)
        normalized.append(value)
    return normalized


async def create_session(
    *,
    payload: SessionCreateRequest,
    user_id: str,
    db: AsyncSession,
) -> SessionResponse:
    """创建会话（API-1）。default_document_ids 必须为用户已就绪的文档。"""
    title = payload.title.strip() if isinstance(payload.title, str) else None
    if title and "\x00" in title:
        raise ApiError(ERR_SESSION_PARAM, "会话标题不能包含 NUL 字符", status=400)
    if title and len(title) > 255:
        raise ApiError(ERR_SESSION_PARAM, "会话标题不能超过 255 个字符", status=400)

    document_ids = _normalize_document_ids(payload.default_document_ids)

    if document_ids:
        result = await db.execute(
            select(Document.id).where(
                Document.id.in_(document_ids),
                Document.user_id == user_id,
                Document.deleted_at.is_(None),
                Document.status == "ready",
            )
        )
        allowed = {str(row_id) for row_id in result.scalars().all()}
        if len(allowed) != len(document_ids):
            raise ApiError(
                ERR_SESSION_PARAM,
                "默认文档范围包含无权访问或尚未就绪的文档",
                status=400,
                details={"document_ids": document_ids},
            )

    chat_session = Session(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title or None,
        default_document_ids=document_ids,
        message_count=0,
    )
    db.add(chat_session)
    await db.commit()

    return SessionResponse(
        session_id=chat_session.id,
        title=chat_session.title,
        default_document_ids=list(chat_session.default_document_ids or []),
        message_count=chat_session.message_count,
        created_at=getattr(chat_session, "created_at", None),
    )


async def list_messages(*, session_id: str, page: int = 1, page_size: int = 20) -> dict:
    """拉取会话历史（API-8），按时间正序。待 M4 实现。"""
    raise NotImplementedError("API-8 会话历史：待 M4 实现")
