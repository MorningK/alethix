"""M2 单次问答编排服务。

流程：校验会话与文档范围 → 单次检索 → 单次答案生成 → 引用白名单校验 →
事务持久化 agent_runs / iterations / answers / citations / messages。
不启用 LangGraph 多轮状态机（M3 范围）。
"""

from __future__ import annotations

import time
import uuid
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
from app.services import agent_service, answer_service, citation_service, retrieval_service

logger = get_logger(__name__)

_SESSION_LOCK_PERSISTENCE_BUFFER_SECONDS = 30


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
        agent_run = AgentRun(
            id=run_id,
            session_id=locked.id,
            user_id=user_id,
            question=payload.question,
            document_ids=list(scope_ids),
            max_iterations=payload.max_iterations,
            status="done",
            stop_reason=stop_reason,
            iteration_count=iteration_count,
            retrieved_chunk_count=retrieved_count,
            citation_count=len(citations),
            citation_filtered_count=citation_filtered_count,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            token_used=token_used,
            llm_call_count=(
                llm_call_count
                if llm_call_count is not None
                else 0
                if stop_reason == "low_relevance"
                else 1
            ),
            fallback_count=fallback_count,
            duration_ms=duration_ms,
        )
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
                    queries=[payload.question],
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

    lock_ttl = max(
        s.agent_session_lock_ttl_seconds,
        s.agent_timeout_seconds + _SESSION_LOCK_PERSISTENCE_BUFFER_SECONDS,
    )
    if lock_ttl > s.agent_session_lock_ttl_seconds:
        logger.warning(
            "会话锁 TTL 已上调以覆盖完整调研",
            extra=safe_extra(configured=s.agent_session_lock_ttl_seconds, effective=lock_ttl),
        )

    lock_token: str | None = None
    lock_degraded = False
    try:
        lock_token = await redis_db.acquire_session_lock(str(chat_session.id), lock_ttl)
    except Exception:  # noqa: BLE001
        # Redis 不可用时降级到 _persist 中的 PostgreSQL 行锁，不阻断问答。
        lock_degraded = True
    if not lock_degraded and lock_token is None:
        raise ApiError(ERR_SESSION_BUSY, "该会话正在处理上一个问题", status=409)

    try:
        if scope_ids:
            research = await agent_service.run_research(
                agent_run_id=str(uuid.uuid4()),
                question=payload.question.strip(),
                session_id=str(chat_session.id),
                user_id=user_id,
                document_ids=scope_ids,
                filename_map=filename_map,
                max_iterations=payload.max_iterations,
                settings=s,
            )
            agent_run_id = await _persist(
                db=db,
                chat_session=chat_session,
                user_id=user_id,
                payload=payload,
                scope_ids=scope_ids,
                answer_text=research.answer,
                confidence=research.confidence,
                stop_reason=research.stop_reason or "sufficient",
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
        generated = await answer_service.generate_answer(payload.question.strip(), hits, s)
        citations, filtered_count = citation_service.build_citations(
            hits, filename_map, generated.used_chunk_ids, settings=s
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        agent_run_id = await _persist(
            db=db,
            chat_session=chat_session,
            user_id=user_id,
            payload=payload,
            scope_ids=scope_ids,
            answer_text=generated.answer,
            confidence=generated.confidence,
            stop_reason="low_relevance",
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
                    queries=[payload.question],
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
        if lock_token:
            try:
                await redis_db.release_session_lock(str(chat_session.id), lock_token)
            except Exception:  # noqa: BLE001
                pass


__all__ = ["run_single_ask"]
