"""文档入库服务。

编排「解析 → 清洗 → 切片 → 向量化 → 写入 Qdrant」全流程。
写入顺序见 prd/04-data-model.md §5.1：先 PG 落 chunks，再写 Qdrant。

可靠性：
    - 每个阶段提交后立即写入 Redis doc:task，API-3 快路径可见中间状态（AC-1.2）
    - 重入幂等：清理上次残留的 chunks 与 Qdrant Point 后重新入库（prd/04 §5.3）
    - 任一环节失败：置 failed 并清理 Qdrant 残留 Point（幂等）

实现阶段：M1。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ERR_DOC_UNREADABLE, ERR_INTERNAL, ApiError
from app.core.logging import get_logger, safe_extra
from app.db import postgres
from app.db import redis as redis_db
from app.models.document import Chunk, Document
from app.services import qdrant_service
from app.services.chunk_service import build_embedding_text, split_blocks
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

        await _delete_points_quietly(document_id, user_id, settings)

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
        # 重入幂等：清除上次失败可能残留的 chunks 与 Qdrant Point
        await _reset_document_data(session, document, settings)

        # ---- parsing ----
        await _advance(session, document, "parsing", settings)
        parsed = parse_document(document.storage_path or "", document.source_format or "")
        title = document.title or parsed.title

        # ---- chunking ----
        await _advance(session, document, "chunking", settings)
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
        await _advance(session, document, "embedding", settings)

        # ---- embedding（结构头只增强语义，content 仍存纯正文）----
        texts = [
            build_embedding_text(title, draft.section, draft.page, draft.content)
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
                    "title": title,
                    "chunk_index": chunk.chunk_index,
                    "page": chunk.page,
                    "section": chunk.section,
                    "content": chunk.content,
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        await asyncio.to_thread(qdrant_service.upsert_points, settings, points)

        # ---- ready ----
        document.chunk_count = len(chunks)
        document.page_count = parsed.page_count
        document.title = title
        document.ready_at = datetime.now(UTC)
        await _advance(session, document, "ready", settings)

    logger.info(
        "文档入库完成",
        extra=safe_extra(document_id=document_id, chunk_count=len(chunks)),
    )


async def _reset_document_data(
    session: AsyncSession, document: Document, settings: Settings
) -> None:
    """清理文档残留数据，使 ingest 可安全重入（prd/04 §5.3 向量重建语义）。"""
    await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
    await session.commit()
    await _delete_points_quietly(str(document.id), document.user_id, settings)


async def _delete_points_quietly(document_id: str, user_id: str, settings: Settings) -> None:
    """删除 Qdrant Point；失败仅记日志（PG 为权威源，孤儿由 M5 对账兜底）。"""
    try:
        await asyncio.to_thread(
            qdrant_service.delete_by_document_id, settings, user_id, document_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant Point 清理失败：%s", exc, extra=safe_extra(document_id=document_id))


async def _advance(
    session: AsyncSession, document: Document, status: str, settings: Settings
) -> None:
    """推进状态机并立即提交 + 广播（prd/04 §5.1：崩溃后可从当前状态恢复）。"""
    document.status = status
    document.error_code = None
    document.error_message = None
    await session.commit()
    await _write_task_status(document, settings)


async def _write_task_status(document: Document, settings: Settings) -> None:
    """把文档最新状态写入 Redis doc:task（API-3 快路径）；Redis 不可用不阻断。"""
    try:
        await redis_db.set_doc_task(
            str(document.id), task_payload(document), settings.ingest_task_ttl_seconds
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "任务状态写入 Redis 失败（PG 仍为权威源）：%s",
            exc,
            extra=safe_extra(document_id=str(document.id)),
        )


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
            await session.commit()
            await _delete_points_quietly(document_id, document.user_id, settings)
            await _write_task_status(document, settings)
    except Exception as mark_exc:  # noqa: BLE001
        logger.error("标记文档失败时出错：%s", mark_exc, extra=safe_extra(document_id=document_id))
    logger.warning(
        "文档入库失败",
        extra=safe_extra(document_id=document_id, error_code=exc.code),
    )


__all__ = ["ingest_document", "purge_document"]
