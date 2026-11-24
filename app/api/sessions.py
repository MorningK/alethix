"""会话接口（占位）。

API-1 POST   /sessions                      创建会话
API-8 GET    /sessions/{session_id}/messages 会话历史

契约见 prd/05-api-spec.md；对应 FR-4（会话管理）与 FR-10（追问延续）。
实现阶段：前端 F4 / 后端 M2。
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUserId, DbSession
from app.schemas.common import NotImplementedResponse
from app.schemas.session import SessionCreateRequest, SessionResponse
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


@router.get(
    "/{session_id}/messages",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    response_model=NotImplementedResponse,
)
async def list_messages(session_id: str) -> NotImplementedResponse:
    """拉取会话历史（按时间正序）。待 M2 实现。

    响应：分页结构，items 为 Message 列表，assistant 消息自带 citations。
    """
    return NotImplementedResponse(
        detail=f"API-8 会话历史：待 M2 实现（session_id={session_id}）", api="API-8"
    )
