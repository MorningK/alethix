"""会话服务。

职责：会话与消息管理（DM-4 / DM-5）。
追问的指代消解属于 M4 范围，暂不在本服务实现。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_SESSION_NOT_FOUND, ERR_SESSION_PARAM, ApiError
from app.models.agent import Answer
from app.models.agent import Citation as CitationORM
from app.models.document import Document
from app.models.session import Message, Session
from app.schemas.common import Page
from app.schemas.document import Citation as CitationDTO
from app.schemas.session import MessageItem, SessionCreateRequest, SessionResponse


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


async def list_messages(
    *,
    session_id: str,
    user_id: str,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> Page[MessageItem]:
    """拉取会话历史（API-8），按 seq 正序并批量装配答案与引用。"""
    try:
        normalized = str(uuid.UUID(str(session_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ApiError(ERR_SESSION_PARAM, "session_id 不是合法 UUID", status=400) from exc
    if page < 1 or page_size < 1 or page_size > 100:
        raise ApiError(ERR_SESSION_PARAM, "分页参数超出范围", status=400)

    owned = await db.execute(
        select(Session.id).where(
            Session.id == normalized,
            Session.user_id == user_id,
            Session.deleted_at.is_(None),
        )
    )
    if owned.scalar_one_or_none() is None:
        raise ApiError(ERR_SESSION_NOT_FOUND, "会话不存在", status=404)

    total_result = await db.execute(
        select(func.count()).select_from(Message).where(Message.session_id == normalized)
    )
    total = int(total_result.scalar_one())

    rows = await db.execute(
        select(Message)
        .where(Message.session_id == normalized)
        .order_by(Message.seq.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    messages = list(rows.scalars().all())

    run_ids = [str(item.agent_run_id) for item in messages if item.agent_run_id]
    answers_by_run: dict[str, Answer] = {}
    if run_ids:
        answer_rows = await db.execute(select(Answer).where(Answer.agent_run_id.in_(run_ids)))
        answers_by_run = {str(row.agent_run_id): row for row in answer_rows.scalars().all()}

    answer_ids = [str(row.id) for row in answers_by_run.values()]
    citations_by_answer: dict[str, list[CitationDTO]] = {}
    if answer_ids:
        citation_rows = await db.execute(
            select(CitationORM)
            .where(CitationORM.answer_id.in_(answer_ids))
            .order_by(CitationORM.ordinal.asc())
        )
        for row in citation_rows.scalars().all():
            citations_by_answer.setdefault(str(row.answer_id), []).append(
                CitationDTO(
                    document_id=str(row.document_id),
                    chunk_id=str(row.chunk_id),
                    filename=row.filename,
                    page=row.page,
                    section=row.section,
                    quote=row.quote,
                    score=row.score,
                )
            )

    items: list[MessageItem] = []
    for item in messages:
        answer = answers_by_run.get(str(item.agent_run_id)) if item.agent_run_id else None
        items.append(
            MessageItem(
                message_id=str(item.id),
                role=item.role,
                content=item.content,
                created_at=item.created_at,
                agent_run_id=str(item.agent_run_id) if item.agent_run_id else None,
                confidence=answer.confidence if answer else None,
                citations=citations_by_answer.get(str(answer.id), []) if answer else [],
            )
        )
    return Page[MessageItem](items=items, total=total, page=page, page_size=page_size)
