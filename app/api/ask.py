"""问答接口（占位）。

API-6 POST /ask         同步智能问答
API-7 POST /ask/stream  流式智能问答（SSE）

契约见 prd/05-api-spec.md；事件格式见 §4 SSE 事件契约。
对应 FR-5 ~ FR-11。实现阶段：后端 M2（同步）/ M4（流式）。
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.schemas.common import NotImplementedResponse

router = APIRouter(tags=["ask"])


@router.post("/ask", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def ask() -> NotImplementedResponse:
    """同步问答，返回完整答案与调研轨迹。待 M2 实现。

    请求：{ session_id, question, document_ids?, max_iterations? }
    响应：{ agent_run_id, answer, confidence, stop_reason, iterations, citations }
    """
    return NotImplementedResponse(detail="API-6 同步问答：待 M2 实现", api="API-6")


@router.post("/ask/stream", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def ask_stream() -> NotImplementedResponse:
    """流式问答（SSE）。待 M4 实现。

    事件序列：started → (iteration → retrieved → reasoning)* → final_answer
    注意：反向代理需禁用缓冲，否则事件被攒批（SSE-6）。
    """
    return NotImplementedResponse(detail="API-7 流式问答：待 M4 实现", api="API-7")
