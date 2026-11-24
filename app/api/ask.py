"""问答接口。

API-6 POST /ask         同步智能问答
API-7 POST /ask/stream  流式智能问答（SSE）

契约见 prd/05-api-spec.md；事件格式见 §4 SSE 事件契约。
对应 FR-5 ~ FR-11。实现阶段：后端 M2（同步）/ M4（流式）。
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUserId, DbSession, SettingsDep
from app.schemas.ask import AskRequest, AskResponse
from app.schemas.common import NotImplementedResponse
from app.services import ask_service

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    settings: SettingsDep = None,  # type: ignore[assignment]
    db: DbSession = None,  # type: ignore[assignment]
) -> AskResponse:
    """同步单次问答（API-6）。多轮调研由 M3 的 LangGraph 状态机实现。"""
    return await ask_service.run_single_ask(
        payload=payload, user_id=user_id, settings=settings, db=db
    )


@router.post("/ask/stream", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def ask_stream() -> NotImplementedResponse:
    """流式问答（SSE）。待 M4 实现。

    事件序列：started → (iteration → retrieved → reasoning)* → final_answer
    注意：反向代理需禁用缓冲，否则事件被攒批（SSE-6）。
    """
    return NotImplementedResponse(detail="API-7 流式问答：待 M4 实现", api="API-7")
