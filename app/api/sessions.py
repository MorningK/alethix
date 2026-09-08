"""会话接口（占位）。

API-1 POST   /sessions                      创建会话
API-8 GET    /sessions/{session_id}/messages 会话历史

契约见 prd/05-api-spec.md；对应 FR-4（会话管理）与 FR-10（追问延续）。
实现阶段：前端 F4 / 后端 M2。
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.schemas.common import NotImplementedResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED, response_model=NotImplementedResponse)
async def create_session() -> NotImplementedResponse:
    """创建会话。待 M2 实现。

    请求：{ title?, default_document_ids? }
    响应：{ session_id, title, default_document_ids, message_count, created_at }
    """
    return NotImplementedResponse(detail="API-1 创建会话：待 M2 实现", api="API-1")


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
