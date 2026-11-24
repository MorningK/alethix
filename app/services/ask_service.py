"""M2 单次问答编排服务。

流程：校验会话与文档范围 → 单次检索 → 单次答案生成 → 引用白名单校验 →
事务持久化 agent_runs / iterations / answers / citations / messages。
不启用 LangGraph 多轮状态机（M3 范围）。
"""

from __future__ import annotations

import time
import uuid

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
    ERR_SESSION_NOT_FOUND,
    ApiError,
)
from app.core.logging import get_logger, safe_extra
from app.models.agent import AgentRun, Answer, Iteration
from app.models.agent import Citation as CitationORM
from app.models.document import Document
from app.models.session import Message, Session
from app.schemas.ask import AskRequest, AskResponse, IterationRecord
from app.services import answer_service, citation_service, retrieval_service

logger = get_logger(__name__)


def _validate_payload(payload: AskRequest) -> None:
    question = payload.question or ""
    if not question.strip() or len(question) > 2000:
        raise ApiError(ERR_ASK_BAD_QUESTION, "question 必须为 1 ~ 2000 个字符", status=400)
    if not 1 <= payload.max_iterations <= 10:
        raise ApiError(ERR_ASK_BAD_MAX_ITER, "max_iterations 必须在 1 ~ 10 之间", status=400)


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
    generated,
    hits: list[retrieval_service.RetrievedChunk],
    citations: list,
    citation_filtered_count: int,
    duration_ms: int,
) -> str:
    """在一个事务中写入消息、运行记录、迭代、答案与引用。"""
    run_id = str(uuid.uuid4())
    answer_id = str(uuid.uuid4())
    seq = int(chat_session.message_count or 0)

    messages = [
        Message(
            session_id=chat_session.id,
            role="user",
            content=payload.question,
            seq=seq + 1,
        ),
        Message(
            session_id=chat_session.id,
            role="assistant",
            content=answer_text,
            agent_run_id=run_id,
            seq=seq + 2,
        ),
    ]
    agent_run = AgentRun(
        id=run_id,
        session_id=chat_session.id,
        user_id=user_id,
        question=payload.question,
        document_ids=list(scope_ids),
        max_iterations=payload.max_iterations,
        status="done",
        stop_reason=stop_reason,
        iteration_count=1,
        retrieved_chunk_count=len(hits),
        citation_count=len(citations),
        citation_filtered_count=citation_filtered_count,
        token_used=0,
        llm_call_count=0 if stop_reason == "low_relevance" else 1,
        duration_ms=duration_ms,
    )
    iteration = Iteration(
        agent_run_id=run_id,
        iteration=1,
        queries=[payload.question],
        retrieved_chunk_count=len(hits),
        new_chunk_count=len(hits),
        findings=list(generated.findings),
        conflicts=list(generated.conflicts),
        decision="answer",
        reason=generated.reason or None,
        missing_information=None,
    )
    answer = Answer(
        id=answer_id,
        agent_run_id=run_id,
        session_id=chat_session.id,
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

    try:
        chat_session.message_count = seq + 2
        db.add_all([*messages, agent_run, iteration, answer, *citation_rows])
        await db.commit()
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
    """执行单次问答并返回契约响应。"""
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

    try:
        hits = await retrieval_service.search(
            query=payload.question.strip(),
            user_id=user_id,
            document_ids=scope_ids or None,
            top_k=s.agent_top_k_per_query,
            score_threshold=s.agent_score_threshold,
            settings=s,
        )
        generated = await answer_service.generate_answer(payload.question.strip(), hits, s)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("单次问答执行失败", extra=safe_extra(reason=type(exc).__name__))
        raise ApiError(ERR_AGENT_FAILED, "问答执行失败", status=500) from exc

    citations, filtered_count = citation_service.build_citations(
        hits, filename_map, generated.used_chunk_ids, settings=s
    )
    stop_reason = (
        "low_relevance" if generated.answer == answer_service.LOW_RELEVANCE_ANSWER else "sufficient"
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
        stop_reason=stop_reason,
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
        stop_reason=stop_reason,
        iteration_count=1,
        duration_ms=duration_ms,
        token_used=0,
        iterations=[
            IterationRecord(
                iteration=1,
                queries=[payload.question],
                retrieved_chunk_count=len(hits),
                new_chunk_count=len(hits),
                findings=list(generated.findings),
                conflicts=list(generated.conflicts),
                decision="answer",
                reason=generated.reason,
                missing_information=None,
            )
        ],
        citations=citations,
    )


__all__ = ["run_single_ask"]
