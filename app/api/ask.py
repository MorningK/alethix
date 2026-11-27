"""问答接口。

API-6 POST /ask         同步智能问答
API-7 POST /ask/stream  流式智能问答（SSE）

契约见 prd/05-api-spec.md；事件格式见 §4 SSE 事件契约。
对应 FR-5 ~ FR-11。实现阶段：后端 M2（同步）/ M4（流式）。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession, SettingsDep
from app.core.errors import (
    ERR_AGENT_FAILED,
    ERR_SESSION_NOT_FOUND,
    ERR_SESSION_PARAM,
    ApiError,
)
from app.core.logging import get_logger, safe_extra, trace_id_var
from app.models.agent import AgentRun
from app.schemas.ask import AskRequest, AskResponse
from app.services import agent_service, ask_service, sse_event_service
from app.services.sse_event_service import EventRecord

router = APIRouter(tags=["ask"])
logger = get_logger(__name__)

_TERMINAL_EVENTS = {"final_answer", "error"}


def _last_event_id(value: str | None) -> int:
    """解析 Last-Event-ID，非法值按 0 处理。"""
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


def _sse_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _resolve_existing_run(
    *, run_id: str | None, user_id: str, db: Any, prepared: Any
) -> tuple[str, str]:
    """校验恢复运行存在且属于当前用户与会话。"""
    if not run_id:
        raise ApiError(ERR_SESSION_PARAM, "重连缺少 X-Agent-Run-Id", status=400)
    try:
        uuid.UUID(run_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ApiError(ERR_SESSION_PARAM, "X-Agent-Run-Id 不是合法 UUID", status=400) from exc

    result = await db.execute(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
            AgentRun.session_id == prepared.chat_session.id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise ApiError(ERR_SESSION_NOT_FOUND, "调研运行不存在或无权访问", status=404)
    return run_id, str(run.status)


async def _resume_events(
    *,
    agent_run_id: str,
    store: sse_event_service.SSEEventStore,
    replay_from: int,
    heartbeat_seconds: int,
) -> Any:
    """尾随已有运行的事件，不启动新调研、不重复落库。"""
    last_emitted_id = replay_from
    while True:
        records = await store.after(agent_run_id, last_emitted_id)
        if not records and await store.is_terminal(agent_run_id):
            return
        if records:
            for record in records:
                if int(record["id"]) <= last_emitted_id:
                    continue
                yield sse_event_service.format_event(record)
                last_emitted_id = int(record["id"])
                if record["event"] in _TERMINAL_EVENTS:
                    await store.mark_terminal(agent_run_id)
                    return
            continue
        yield ": ping\n\n"
        await asyncio.sleep(heartbeat_seconds)


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


@router.post("/ask/stream")
async def ask_stream(
    payload: AskRequest,
    request: Request,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    settings: SettingsDep = None,  # type: ignore[assignment]
    db: DbSession = None,  # type: ignore[assignment]
) -> StreamingResponse:
    """流式问答（API-7）。业务校验在进入流之前完成，执行异常以 error 事件推送。"""
    run_id_header = request.headers.get("x-agent-run-id")
    replay_from = _last_event_id(request.headers.get("last-event-id"))
    is_resume = bool(run_id_header or replay_from)

    prepared = await ask_service.prepare_ask(
        payload=payload,
        user_id=user_id,
        db=db,
        settings=settings,
        followup=not is_resume,
    )
    store = sse_event_service.get_event_store(settings)

    if is_resume:
        agent_run_id, _ = await _resolve_existing_run(
            run_id=run_id_header, user_id=user_id, db=db, prepared=prepared
        )
        return StreamingResponse(
            _resume_events(
                agent_run_id=agent_run_id,
                store=store,
                replay_from=replay_from,
                heartbeat_seconds=settings.sse_heartbeat_seconds,
            ),
            status_code=status.HTTP_200_OK,
            headers=_sse_headers(),
            media_type="text/event-stream",
        )

    agent_run_id = str(uuid.uuid4())
    await store.clear(agent_run_id)
    queue: asyncio.Queue[EventRecord | None] = asyncio.Queue()
    lock = await ask_service.acquire_ask_lock(
        session_id=str(prepared.chat_session.id), settings=settings
    )

    async def publish(event: str, data: dict[str, Any]) -> None:
        record = await store.append(agent_run_id, event, data)
        await queue.put(record)

    try:
        await ask_service.register_stream_run(
            prepared=prepared,
            agent_run_id=agent_run_id,
            user_id=user_id,
            db=db,
        )
        await publish(
            "started",
            {
                "agent_run_id": agent_run_id,
                "session_id": prepared.chat_session.id,
                "question": prepared.question,
                "max_iterations": payload.max_iterations,
            },
        )
    except Exception:
        await ask_service.release_ask_lock(session_id=str(prepared.chat_session.id), lock=lock)
        raise

    async def run() -> None:
        try:
            research = await agent_service.stream_research(
                agent_run_id=agent_run_id,
                question=prepared.question,
                session_id=str(prepared.chat_session.id),
                user_id=user_id,
                document_ids=prepared.scope_ids,
                filename_map=prepared.filename_map,
                max_iterations=payload.max_iterations,
                event_sink=publish,
                history_findings=prepared.history_findings,
                settings=settings,
            )
            await ask_service.persist_research(
                research=research, prepared=prepared, user_id=user_id, db=db
            )
            await publish(
                "final_answer",
                {
                    "agent_run_id": agent_run_id,
                    "answer": research.answer,
                    "confidence": research.confidence,
                    "stop_reason": research.stop_reason,
                    "iteration_count": len(research.iterations),
                    "duration_ms": research.duration_ms,
                    "token_used": research.token_used,
                    "citations": [item.model_dump(mode="json") for item in research.citations],
                },
            )
            with suppress(Exception):
                await store.mark_terminal(agent_run_id)
        except asyncio.CancelledError:
            logger.info("流式问答已取消", extra=safe_extra(agent_run_id=agent_run_id))
            with suppress(Exception):
                await ask_service.mark_run_failed(agent_run_id=agent_run_id, user_id=user_id, db=db)
            with suppress(Exception):
                await store.mark_terminal(agent_run_id)
            raise
        except ApiError as exc:
            with suppress(Exception):
                await ask_service.mark_run_failed(agent_run_id=agent_run_id, user_id=user_id, db=db)
            await publish(
                "error",
                {
                    "code": exc.code,
                    "message": exc.message,
                    "trace_id": trace_id_var.get() or "",
                },
            )
            with suppress(Exception):
                await store.mark_terminal(agent_run_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "流式问答执行失败",
                extra=safe_extra(agent_run_id=agent_run_id, reason=type(exc).__name__),
            )
            with suppress(Exception):
                await ask_service.mark_run_failed(agent_run_id=agent_run_id, user_id=user_id, db=db)
            await publish(
                "error",
                {
                    "code": ERR_AGENT_FAILED,
                    "message": "智能体执行失败，请稍后重试",
                    "trace_id": trace_id_var.get() or "",
                },
            )
            with suppress(Exception):
                await store.mark_terminal(agent_run_id)
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())

    async def events():
        last_emitted_id = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    record = await asyncio.wait_for(
                        queue.get(), timeout=settings.sse_heartbeat_seconds
                    )
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if record is None:
                    break
                if int(record["id"]) <= last_emitted_id:
                    continue
                yield sse_event_service.format_event(record)
                last_emitted_id = int(record["id"])
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            await ask_service.release_ask_lock(session_id=str(prepared.chat_session.id), lock=lock)

    return StreamingResponse(
        events(),
        status_code=status.HTTP_200_OK,
        headers=_sse_headers(),
        media_type="text/event-stream",
    )
