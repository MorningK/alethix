"""文档入库服务。

编排「解析 → 清洗 → 切片 → 向量化 → 写入 Qdrant」全流程。
写入顺序见 prd/04-data-model.md §5.1：先 PG 落 chunks，再写 Qdrant。

实现阶段：M1。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ERR_DOC_UNREADABLE, ERR_INTERNAL, ApiError
from app.core.logging import get_logger, safe_extra
from app.db import postgres
from app.db import redis as redis_db
from app.models.document import Chunk, Document
from app.services import qdrant_service
from app.services.chunk_service import ChunkDraft, build_embedding_text, split_blocks
from app.services.document_service import (
    get_any_document,
    get_document_including_deleted,
    hard_delete_document,
    task_payload,
)
from app.services.embedding_service import embed_texts
from app.services.parser_service import parse_document

logger = get_logger(__name__)

# 向量化函数签名：注入用于测试打桩
EmbedFn = Callable[[Sequence[str], Settings], Awaitable[list[list[float]]]]


async def ingest_document(
    document_id: str,
    *,
    settings: Settings | None = None,
    embed_fn: EmbedFn | None = None,
) -> None:
    """执行单个文档的入库流程。由 worker 调用。

    状态推进：parsing → chunking → embedding → ready
    任一环节失败：置 failed 并清理 Qdrant 残留 Point（幂等）
    """
    settings = settings or get_settings()
    try:
        await _ingest(document_id, settings=settings, embed_fn=embed_fn)
    except ApiError as exc:
        await _mark_failed(document_id, exc, settings=settings)
        raise
    except Exception as exc:  # noqa: BLE001
        wrapped = ApiError(ERR_INTERNAL, f"文档入库失败：{exc}", status=500)
        await _mark_failed(document_id, wrapped, settings=settings)
        raise wrapped from exc


async def purge_document(document_id: str, *, settings: Settings | None = None) -> None:
    """物理清理（API-5 软删后的异步补偿，AC-1.8）。

    顺序：删 Qdrant Point → 删本地文件 → 硬删文档行（chunks 级联删除）。
    Qdrant 删除失败不阻塞 PG 清理，孤儿 Point 由 M5 对账兜底。
    """
    settings = settings or get_settings()
    async with postgres.session_scope() as session:
        # 软删文档同样需要物理清理，故不过滤 deleted_at
        document = await get_document_including_deleted(session, document_id)
        if document is None:
            logger.info(
                "清理任务跳过：文档不存在或已删除", extra=safe_extra(document_id=document_id)
            )
            return
        user_id = document.user_id
        storage_path = document.storage_path

        try:
            qdrant_service.delete_by_document_id(settings, user_id, document_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Qdrant Point 清理失败，交由对账补偿：%s",
                exc,
                extra=safe_extra(document_id=document_id),
            )

        if storage_path:
            try:
                Path(storage_path).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "本地文件删除失败：%s", exc, extra=safe_extra(document_id=document_id)
                )

        await hard_delete_document(session, document)
        await session.commit()
    logger.info("文档物理清理完成", extra=safe_extra(document_id=document_id))


# ---------------- 内部实现 ----------------


async def _ingest(document_id: str, *, settings: Settings, embed_fn: EmbedFn | None) -> None:
    async with postgres.session_scope() as session:
        document = await get_any_document(session, document_id)
        if document is None:
            logger.warning("入库任务跳过：文档不存在", extra=safe_extra(document_id=document_id))
            return
        if document.status == "ready":
            logger.info("文档已就绪，跳过重复入库", extra=safe_extra(document_id=document_id))
            return

        user_id = document.user_id

        # ---- parsing ----
        await _advance(session, document, "parsing")
        parsed = parse_document(document.storage_path or "", document.source_format or "")

        # ---- chunking ----
        await _advance(session, document, "chunking")
        drafts = split_blocks(
            parsed.blocks,
            settings.chunk_size_tokens,
            settings.chunk_overlap_tokens,
        )
        if not drafts:
            raise ApiError(ERR_DOC_UNREADABLE, "解析结果为空，未能生成有效切片", status=400)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                user_id=user_id,
                chunk_index=index,
                content=draft.content,
                content_length=len(draft.content),
                token_count=draft.token_count,
                page=draft.page,
                section=draft.section,
            )
            for index, draft in enumerate(drafts)
        ]
        session.add_all(chunks)
        await _advance(session, document, "embedding")

        # ---- embedding ----
        texts = [
            build_embedding_text(document.title, draft.section, draft.page, draft.content)
            for draft in drafts
        ]
        vectors = await (embed_fn or embed_texts)(texts, settings)
        if len(vectors) != len(chunks):
            raise ApiError(ERR_INTERNAL, "向量化结果数量与切片不一致", status=500)

        # ---- Qdrant（point id = chunk_id）----
        points = [
            (
                chunk.id,
                vector,
                {
                    "user_id": user_id,
                    "doc_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "page": chunk.page,
                    "section": chunk.section,
                    "content": chunk.content,
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        qdrant_service.upsert_points(settings, points)

        # ---- ready ----
        document.chunk_count = len(chunks)
        document.page_count = parsed.page_count
        if parsed.title and not document.title:
            document.title = parsed.title
        document.ready_at = datetime.now(UTC)
        await _advance(session, document, "ready")

    logger.info(
        "文档入库完成",
        extra=safe_extra(document_id=document_id, chunk_count=len(chunks)),
    )
    await _publish_status(document_id, settings=settings)


async def _advance(session: AsyncSession, document: Document, status: str) -> None:
    """推进状态机并立即提交（崩溃后可从当前状态恢复，见 prd/04 §5.1）。"""
    document.status = status
    document.error_code = None
    document.error_message = None
    await session.commit()


async def _mark_failed(document_id: str, exc: ApiError, *, settings: Settings) -> None:
    """失败终态：记录错误码 + 回滚 Qdrant 残留 Point（幂等）+ 广播状态。"""
    try:
        async with postgres.session_scope() as session:
            document = await get_any_document(session, document_id)
            if document is None:
                return
            document.status = "failed"
            document.error_code = exc.code
            document.error_message = exc.message
            try:
                qdrant_service.delete_by_document_id(settings, document.user_id, document_id)
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.error(
                    "Qdrant 残留 Point 清理失败：%s",
                    cleanup_exc,
                    extra=safe_extra(document_id=document_id),
                )
            await session.commit()
    except Exception as mark_exc:  # noqa: BLE001
        logger.error("标记文档失败时出错：%s", mark_exc, extra=safe_extra(document_id=document_id))
    logger.warning(
        "文档入库失败",
        extra=safe_extra(document_id=document_id, error_code=exc.code),
    )
    await _publish_status(document_id, settings=settings)


async def _publish_status(document_id: str, *, settings: Settings) -> None:
    """把文档最新状态写入 Redis doc:task（API-3 快路径）。Redis 不可用不阻断流程。"""
    try:
        async with postgres.session_scope() as session:
            document = await get_any_document(session, document_id)
            if document is None:
                return
            payload = task_payload(document)
        await redis_db.set_doc_task(document_id, payload, settings.ingest_task_ttl_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "任务状态写入 Redis 失败（PG 仍为权威源）：%s",
            exc,
            extra=safe_extra(document_id=document_id),
        )


__all__ = ["ChunkDraft", "ingest_document", "purge_document"]
