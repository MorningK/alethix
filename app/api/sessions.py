"""会话接口（占位）。

API-1 POST   /sessions                      创建会话
API-8 GET    /sessions/{session_id}/messages 会话历史

契约见 prd/05-api-spec.md；对应 FR-4（会话管理）与 FR-10（追问延续）。
实现阶段：前端 F4 / 后端 M2。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUserId, DbSession
from app.schemas.common import Page
from app.schemas.session import MessageItem, SessionCreateRequest, SessionResponse
from app.services import session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
async def create_session(
    payload: SessionCreateRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    db: DbSession = None,  # type: ignore[assignment]
) -> SessionResponse:
    """创建会话（API-1）。默认检索范围必须为用户已就绪的文档。"""
    return await session_service.create_session(payload=payload, user_id=user_id, db=db)


@router.get("/{session_id}/messages", response_model=Page[MessageItem])
async def list_messages(
    session_id: str,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    db: DbSession = None,  # type: ignore[assignment]
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[MessageItem]:
    """拉取会话历史（API-8），按 seq 正序；assistant 消息自带引用。"""
    return await session_service.list_messages(
        session_id=session_id, user_id=user_id, db=db, page=page, page_size=page_size
    )
