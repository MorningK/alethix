"""M2 单次问答编排服务。

流程：校验会话与文档范围 → 单次检索 → 单次答案生成 → 引用白名单校验 →
事务持久化 agent_runs / iterations / answers / citations / messages。
不启用 LangGraph 多轮状态机（M3 范围）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import (
    ERR_AGENT_FAILED,
    ERR_ASK_BAD_MAX_ITER,
    ERR_ASK_BAD_QUESTION,
    ERR_ASK_DOC_FORBIDDEN,
    ERR_ASK_DOC_NOT_READY,
    ERR_ASK_TOO_MANY_DOCS,
    ERR_INTERNAL,
    ERR_SESSION_BUSY,
    ERR_SESSION_NOT_FOUND,
    ERR_SESSION_PARAM,
    ApiError,
)
from app.core.logging import get_logger, safe_extra
from app.db import redis as redis_db
from app.models.agent import AgentRun, Answer, Iteration
from app.models.agent import Citation as CitationORM
from app.models.document import Document
from app.models.session import Message, Session
from app.schemas.ask import AskRequest, AskResponse, IterationRecord
from app.services import (
    agent_service,
    answer_service,
    citation_service,
    followup_service,
    retrieval_service,
)

logger = get_logger(__name__)

_SESSION_LOCK_PERSISTENCE_BUFFER_SECONDS = 30


@dataclass(frozen=True)
class AskPrepared:
    """API-6 / API-7 共用的已校验问答上下文。"""

    payload: AskRequest
    chat_session: Session
    scope_ids: list[str]
    filename_map: dict[str, str]
    question: str
    history_findings: list[str]


@dataclass(frozen=True)
class AskLock:
    """会话锁状态：Redis 不可用时降级为 PostgreSQL 行锁。"""

    token: str | None
    degraded: bool


def _validate_payload(payload: AskRequest) -> None:
    question = payload.question or ""
    if not question.strip() or len(question) > 2000:
        raise ApiError(ERR_ASK_BAD_QUESTION, "question 必须为 1 ~ 2000 个字符", status=400)
    if not 1 <= payload.max_iterations <= 10:
        raise ApiError(ERR_ASK_BAD_MAX_ITER, "max_iterations 必须在 1 ~ 10 之间", status=400)
    try:
        uuid.UUID(str(payload.session_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ApiError(ERR_SESSION_PARAM, "session_id 不是合法 UUID", status=400) from exc


def _normalize_document_ids(document_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in document_ids:
        try:
            value = str(uuid.UUID(str(raw)))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ApiError(
                ERR_ASK_DOC_FORBIDDEN, "document_ids 包含非法文档 ID", status=400
            ) from exc
        if value not in normalized:
            normalized.append(value)
    return normalized


async def _resolve_scope(
    *, payload: AskRequest, user_id: str, db: AsyncSession
) -> tuple[Session, list[str], dict[str, str]]:
    """解析会话与检索范围；越权文档一律 4003001，未就绪文档 4003002。"""
    result = await db.execute(
        select(Session).where(
            Session.id == payload.session_id,
            Session.user_id == user_id,
            Session.deleted_at.is_(None),
        )
    )
    chat_session = result.scalar_one_or_none()
    if chat_session is None:
        raise ApiError(ERR_SESSION_NOT_FOUND, "会话不存在", status=404)

    if payload.document_ids is None:
        request_ids = list(chat_session.default_document_ids or [])
    else:
        request_ids = list(payload.document_ids)

    document_ids = _normalize_document_ids(request_ids)
    if len(document_ids) > 20:
        raise ApiError(ERR_ASK_TOO_MANY_DOCS, "单次问答最多指定 20 篇文档", status=400)

    if document_ids:
        docs_result = await db.execute(
            select(Document).where(
                Document.id.in_(document_ids),
                Document.user_id == user_id,
                Document.deleted_at.is_(None),
            )
        )
        docs = docs_result.scalars().all()
        found = {str(doc.id): doc for doc in docs}
        if len(found) != len(document_ids):
            raise ApiError(ERR_ASK_DOC_FORBIDDEN, "包含无权访问的文档", status=400)
    else:
        docs_result = await db.execute(
            select(Document).where(
                Document.user_id == user_id,
                Document.status == "ready",
                Document.deleted_at.is_(None),
            )
        )
        docs = docs_result.scalars().all()

    if any(doc.status != "ready" for doc in docs):
        raise ApiError(ERR_ASK_DOC_NOT_READY, "包含尚未处理完成的文档", status=400)

    filename_map = {str(doc.id): str(doc.filename) for doc in docs}
    scope_ids = document_ids or [str(doc.id) for doc in docs]
    return chat_session, scope_ids, filename_map


async def prepare_ask(
    *,
    payload: AskRequest,
    user_id: str,
    db: AsyncSession,
    settings: Settings | None = None,
    followup: bool = True,
) -> AskPrepared:
    """同步与流式问答共用的入流前校验、范围解析与追问上下文准备。"""
    s = settings or get_settings()
    _validate_payload(payload)
    try:
        chat_session, scope_ids, filename_map = await _resolve_scope(
            payload=payload, user_id=user_id, db=db
        )
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("问答范围校验失败", extra=safe_extra(reason=type(exc).__name__))
        raise ApiError(ERR_INTERNAL, "问答范围校验失败", status=500) from exc

    question = payload.question.strip()
    history_findings: list[str] = []
    if followup:
        question, history_findings = await followup_service.build_followup_context(
            session_id=str(chat_session.id),
            question=question,
            user_id=user_id,
            db=db,
            settings=s,
        )
    return AskPrepared(
        payload=payload,
        chat_session=chat_session,
        scope_ids=scope_ids,
        filename_map=filename_map,
        question=question,
        history_findings=list(history_findings),
    )


def ask_lock_ttl(settings: Settings) -> int:
    """会话锁 TTL 必须覆盖完整调研，避免长任务期间锁提前过期。"""
    ttl = max(
        settings.agent_session_lock_ttl_seconds,
        settings.agent_timeout_seconds + _SESSION_LOCK_PERSISTENCE_BUFFER_SECONDS,
    )
    if ttl > settings.agent_session_lock_ttl_seconds:
        logger.warning(
            "会话锁 TTL 已上调以覆盖完整调研",
            extra=safe_extra(configured=settings.agent_session_lock_ttl_seconds, effective=ttl),
        )
    return ttl


async def acquire_ask_lock(*, session_id: str, settings: Settings) -> AskLock:
    """获取会话锁；Redis 异常时降级为持久化阶段的行锁。"""
    try:
        token = await redis_db.acquire_session_lock(session_id, ask_lock_ttl(settings))
    except Exception:  # noqa: BLE001
        return AskLock(token=None, degraded=True)
    if token is None:
        raise ApiError(ERR_SESSION_BUSY, "该会话正在处理上一个问题", status=409)
    return AskLock(token=token, degraded=False)


async def release_ask_lock(*, session_id: str, lock: AskLock) -> None:
    """释放本请求持有的会话锁，忽略释放阶段的异常。"""
    if lock.token is None:
        return
    try:
        await redis_db.release_session_lock(session_id, lock.token)
    except Exception:  # noqa: BLE001
        pass


async def _persist(
    *,
    db: AsyncSession,
    chat_session: Session,
    user_id: str,
    payload: AskRequest,
    scope_ids: list[str],
    answer_text: str,
    confidence: str,
    stop_reason: str,
    agent_question: str | None = None,
    generated=None,
    hits: list[retrieval_service.RetrievedChunk] | None = None,
    citations: list | None = None,
    citation_filtered_count: int = 0,
    duration_ms: int = 0,
    iterations: list | None = None,
    agent_run_id: str | None = None,
    token_used: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    llm_call_count: int | None = None,
    fallback_count: int = 0,
    max_score: float | None = None,
) -> str:
    """在一个事务中写入消息、运行记录、迭代、答案与引用。"""
    run_id = agent_run_id or str(uuid.uuid4())
    answer_id = str(uuid.uuid4())
    hits = hits or []
    citations = citations or []
    generated = generated or SimpleNamespace(findings=[], conflicts=[], reason=None)

    try:
        # 检索与生成完成后才锁定会话行，避免跨 LLM 调用持锁。
        locked_result = await db.execute(
            select(Session)
            .where(
                Session.id == chat_session.id,
                Session.user_id == user_id,
                Session.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        locked = locked_result.scalar_one_or_none()
        if locked is None:
            raise ApiError(ERR_SESSION_NOT_FOUND, "会话不存在", status=404)

        seq = int(locked.message_count or 0)
        if seq == 0 and not locked.title:
            locked.title = payload.question.strip()[:20]

        messages = [
            Message(
                session_id=locked.id,
                role="user",
                content=payload.question,
                seq=seq + 1,
            ),
            Message(
                session_id=locked.id,
                role="assistant",
                content=answer_text,
                agent_run_id=run_id,
                seq=seq + 2,
            ),
        ]
        iteration_count = len(iterations) if iterations else 1
        retrieved_count = (
            sum(int(item.retrieved_chunk_count) for item in iterations) if iterations else len(hits)
        )
        agent_run = await db.get(AgentRun, run_id)
        if agent_run is None:
            agent_run = AgentRun(
                id=run_id,
                session_id=locked.id,
                user_id=user_id,
            )
            db.add(agent_run)
        agent_run.question = agent_question or payload.question
        agent_run.document_ids = list(scope_ids)
        agent_run.max_iterations = payload.max_iterations
        agent_run.status = "done"
        agent_run.stop_reason = stop_reason
        agent_run.iteration_count = iteration_count
        agent_run.retrieved_chunk_count = retrieved_count
        agent_run.citation_count = len(citations)
        agent_run.citation_filtered_count = citation_filtered_count
        agent_run.prompt_tokens = prompt_tokens
        agent_run.completion_tokens = completion_tokens
        agent_run.token_used = token_used
        agent_run.llm_call_count = (
            llm_call_count
            if llm_call_count is not None
            else 0
            if stop_reason == "low_relevance"
            else 1
        )
        agent_run.fallback_count = fallback_count
        agent_run.duration_ms = duration_ms
        if iterations:
            iteration_rows = [
                Iteration(
                    agent_run_id=run_id,
                    iteration=int(item.iteration),
                    queries=list(item.queries),
                    retrieved_chunk_count=int(item.retrieved_chunk_count),
                    new_chunk_count=int(item.new_chunk_count),
                    max_score=item.max_score,
                    findings=list(item.findings),
                    conflicts=list(item.conflicts),
                    decision=item.decision,
                    reason=item.reason or None,
                    missing_information=item.missing_information,
                )
                for item in iterations
            ]
        else:
            iteration_rows = [
                Iteration(
                    agent_run_id=run_id,
                    iteration=1,
                    queries=[agent_question or payload.question],
                    retrieved_chunk_count=len(hits),
                    new_chunk_count=len(hits),
                    max_score=max_score,
                    findings=list(generated.findings),
                    conflicts=list(generated.conflicts),
                    decision="answer",
                    reason=generated.reason or None,
                    missing_information=None,
                )
            ]
        answer = Answer(
            id=answer_id,
            agent_run_id=run_id,
            session_id=locked.id,
            content=answer_text,
            confidence=confidence,
            stop_reason=stop_reason,
        )
        citation_rows = [
            CitationORM(
                answer_id=answer_id,
                agent_run_id=run_id,
                document_id=citation.document_id,
                chunk_id=citation.chunk_id,
                filename=citation.filename,
                page=citation.page,
                section=citation.section,
                quote=citation.quote,
                ordinal=ordinal,
                score=citation.score,
            )
            for ordinal, citation in enumerate(citations, start=1)
        ]

        locked.message_count = seq + 2
        db.add_all([*messages, agent_run, *iteration_rows, answer, *citation_rows])
        await db.commit()
    except ApiError:
        await db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning("问答结果持久化失败", extra=safe_extra(reason=type(exc).__name__))
        raise ApiError(ERR_AGENT_FAILED, "问答结果保存失败", status=500) from exc
    return run_id


async def register_stream_run(
    *,
    prepared: AskPrepared,
    agent_run_id: str,
    user_id: str,
    db: AsyncSession,
) -> None:
    """在 started 事件前登记运行归属，使 pending 运行也可被重连恢复。"""
    try:
        existing = await db.get(AgentRun, agent_run_id)
        if existing is None:
            db.add(
                AgentRun(
                    id=agent_run_id,
                    session_id=prepared.chat_session.id,
                    user_id=user_id,
                    question=prepared.question,
                    document_ids=list(prepared.scope_ids),
                    max_iterations=prepared.payload.max_iterations,
                    status="running",
                )
            )
        await db.commit()
        logger.info(
            "流式调研运行已登记",
            extra=safe_extra(agent_run_id=agent_run_id, session_id=str(prepared.chat_session.id)),
        )
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning(
            "流式调研运行登记失败",
            extra=safe_extra(agent_run_id=agent_run_id, reason=type(exc).__name__),
        )
        raise ApiError(ERR_AGENT_FAILED, "调研运行登记失败", status=500) from exc


async def mark_run_failed(
    *,
    agent_run_id: str,
    user_id: str,
    db: AsyncSession,
) -> None:
    """把预登记运行标记为失败；失败本身不阻断错误事件推送。"""
    try:
        run = await db.get(AgentRun, agent_run_id)
        if run is not None and run.user_id == user_id:
            run.status = "failed"
            run.stop_reason = "internal_error"
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning(
            "流式调研运行失败状态更新失败",
            extra=safe_extra(agent_run_id=agent_run_id, reason=type(exc).__name__),
        )


async def persist_research(
    *,
    research: agent_service.ResearchResult,
    prepared: AskPrepared,
    user_id: str,
    db: AsyncSession,
) -> str:
    """把调研结果在一个事务中落库；同步与流式问答共用。"""
    return await _persist(
        db=db,
        chat_session=prepared.chat_session,
        user_id=user_id,
        payload=prepared.payload,
        scope_ids=prepared.scope_ids,
        answer_text=research.answer,
        confidence=research.confidence,
        stop_reason=research.stop_reason or "sufficient",
        agent_question=prepared.question,
        generated=None,
        hits=[],
        citations=research.citations,
        citation_filtered_count=research.citation_filtered_count,
        duration_ms=research.duration_ms,
        iterations=research.iterations,
        agent_run_id=research.agent_run_id,
        token_used=research.token_used,
        prompt_tokens=research.prompt_tokens,
        completion_tokens=research.completion_tokens,
        llm_call_count=research.llm_call_count,
        fallback_count=research.fallback_count,
        max_score=research.state.get("max_score"),
    )


async def run_single_ask(
    *,
    payload: AskRequest,
    user_id: str,
    db: AsyncSession,
    settings: Settings | None = None,
) -> AskResponse:
    """执行同步问答并返回契约响应；内部委托多轮调研状态机。"""
    start = time.perf_counter()
    s = settings or get_settings()
    prepared = await prepare_ask(payload=payload, user_id=user_id, db=db, settings=s)
    chat_session = prepared.chat_session
    session_id = str(chat_session.id)

    lock = await acquire_ask_lock(session_id=session_id, settings=s)

    try:
        if prepared.scope_ids:
            research = await agent_service.run_research(
                agent_run_id=str(uuid.uuid4()),
                question=prepared.question,
                session_id=session_id,
                user_id=user_id,
                document_ids=prepared.scope_ids,
                filename_map=prepared.filename_map,
                max_iterations=payload.max_iterations,
                history_findings=prepared.history_findings,
                settings=s,
            )
            agent_run_id = await _persist(
                db=db,
                chat_session=chat_session,
                user_id=user_id,
                payload=payload,
                scope_ids=prepared.scope_ids,
                answer_text=research.answer,
                confidence=research.confidence,
                stop_reason=research.stop_reason or "sufficient",
                agent_question=prepared.question,
                generated=None,
                hits=[],
                citations=research.citations,
                citation_filtered_count=research.citation_filtered_count,
                duration_ms=research.duration_ms,
                iterations=research.iterations,
                agent_run_id=research.agent_run_id,
                token_used=research.token_used,
                prompt_tokens=research.prompt_tokens,
                completion_tokens=research.completion_tokens,
                llm_call_count=research.llm_call_count,
                fallback_count=research.fallback_count,
                max_score=research.state.get("max_score"),
            )
            return AskResponse(
                agent_run_id=agent_run_id,
                session_id=chat_session.id,
                question=payload.question,
                answer=research.answer,
                confidence=research.confidence,  # type: ignore[arg-type]
                stop_reason=research.stop_reason,  # type: ignore[arg-type]
                iteration_count=len(research.iterations),
                duration_ms=research.duration_ms,
                token_used=research.token_used,
                iterations=[
                    IterationRecord(
                        iteration=item.iteration,
                        queries=list(item.queries),
                        retrieved_chunk_count=item.retrieved_chunk_count,
                        new_chunk_count=item.new_chunk_count,
                        findings=list(item.findings),
                        conflicts=list(item.conflicts),
                        decision=item.decision,  # type: ignore[arg-type]
                        reason=item.reason,
                        missing_information=item.missing_information,
                    )
                    for item in research.iterations
                ],
                citations=research.citations,
            )

        # 空范围不能退化为「仅按 user_id 检索」：直接走无证据答案分支。
        hits: list[retrieval_service.RetrievedChunk] = []
        generated = await answer_service.generate_answer(prepared.question, hits, s)
        citations, filtered_count = citation_service.build_citations(
            hits, prepared.filename_map, generated.used_chunk_ids, settings=s
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        agent_run_id = await _persist(
            db=db,
            chat_session=chat_session,
            user_id=user_id,
            payload=payload,
            scope_ids=prepared.scope_ids,
            answer_text=generated.answer,
            confidence=generated.confidence,
            stop_reason="low_relevance",
            agent_question=prepared.question,
            generated=generated,
            hits=hits,
            citations=citations,
            citation_filtered_count=filtered_count,
            duration_ms=duration_ms,
        )
        return AskResponse(
            agent_run_id=agent_run_id,
            session_id=chat_session.id,
            question=payload.question,
            answer=generated.answer,
            confidence=generated.confidence,
            stop_reason="low_relevance",
            iteration_count=1,
            duration_ms=duration_ms,
            token_used=0,
            iterations=[
                IterationRecord(
                    iteration=1,
                    queries=[prepared.question],
                    retrieved_chunk_count=0,
                    new_chunk_count=0,
                    findings=list(generated.findings),
                    conflicts=list(generated.conflicts),
                    decision="answer",
                    reason=generated.reason,
                    missing_information=None,
                )
            ],
            citations=citations,
        )
    finally:
        await release_ask_lock(session_id=session_id, lock=lock)


__all__ = ["prepare_ask", "run_single_ask"]
