"""文档接口。

API-2 POST   /documents/upload                 上传文档
API-3 GET    /documents/{document_id}/status    处理状态
API-4 GET    /documents                         文档列表
API-5 DELETE /documents/{document_id}           删除文档

契约见 prd/05-api-spec.md §2；对应 FR-1 ~ FR-3。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUserId, DbSession, SettingsDep
from app.core.errors import (
    ERR_DOC_DELETE_BUSY,
    ERR_DOC_NO_FILE,
    ERR_DOC_NOT_FOUND,
    ERR_DOC_PARAM,
    ERR_INTERNAL,
    ApiError,
)
from app.core.logging import get_logger, safe_extra
from app.core.security import normalize_filename
from app.db import redis as redis_db
from app.models.document import Document
from app.schemas.common import Page
from app.schemas.document import (
    DeleteDocumentResponse,
    DocumentBrief,
    DocumentStatusResponse,
    UploadDocumentResponse,
)
from app.services import document_service

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# 任务投递重试：Redis 抖动时避免任务静默丢失（prd/04 §5.2 失败告警）
_ENQUEUE_ATTEMPTS = 3

# 仅 ready / failed 状态可删除（prd/05-api-spec.md API-5 约束）
_DELETABLE_STATUSES = ("ready", "failed")


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadDocumentResponse,
)
async def upload_document(
    file: UploadFile | None = File(None),
    # session_id：传入则将该文档加入会话默认检索范围；sessions 模块 M4 落地后生效
    session_id: str | None = Form(None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    settings: SettingsDep = None,  # type: ignore[assignment]
    db: DbSession = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> UploadDocumentResponse:
    """上传文档，异步处理。

    请求：multipart/form-data，字段 file（可选 session_id）
    命中去重返回 200 { deduplicated: true }；新文档返回 202。
    """
    if file is None:
        raise ApiError(ERR_DOC_NO_FILE, "缺少必填字段 file", status=400)

    raw_filename = (file.filename or "").strip()
    if not raw_filename:
        raise ApiError(ERR_DOC_PARAM, "文件名不能为空", status=400)
    # 文件名安全规范化（去路径穿越与控制字符，NFR-3.3），并限制 ≤ 255 字符
    filename = normalize_filename(raw_filename)
    if len(filename) > 255:
        raise ApiError(ERR_DOC_PARAM, "文件名长度超过 255 字符", status=400)
    if session_id is not None:
        try:
            uuid.UUID(session_id)
        except ValueError:
            raise ApiError(ERR_DOC_PARAM, "session_id 必须是合法 UUID", status=400) from None

    # 有上限读取：最多读 limit + 1 字节，超限数据仍由 validate_upload 拒绝（4001003），
    # 避免超大 Body 被整体载入内存
    data = await file.read(settings.max_file_size_bytes + 1)
    source_format = document_service.validate_upload(filename, data, settings)
    content_hash = document_service.compute_content_hash(data)

    # 去重（AC-1.5）：同用户同内容直接返回已有文档
    existing = await document_service.find_active_by_hash(db, user_id, content_hash)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _upload_response(existing, deduplicated=True)

    # 配额校验（4001005）：advisory 锁按用户串行化「计数 → 插入」，
    # 与后续 insert/commit 处于同一事务，锁随事务结束释放；并发同内容上传仍由唯一索引兜底
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:uid))"), {"uid": user_id})
    count = await document_service.count_user_documents(db, user_id)
    document_service.check_quota(count)

    document_id = str(uuid.uuid4())
    storage_path = document_service.save_upload_file(settings, document_id, source_format, data)

    try:
        document = await document_service.create_document(
            db,
            user_id=user_id,
            filename=filename,
            content_hash=content_hash,
            source_format=source_format,
            file_size_bytes=len(data),
            storage_path=storage_path,
            mime_type=file.content_type,
            document_id=document_id,
        )
        await db.commit()
    except IntegrityError:
        # 并发上传同一文件（B-8）：部分唯一索引兜底，回查已有记录并按去重响应；
        # 竞争失败方的本地文件成为孤儿，需删除
        await db.rollback()
        _remove_file_quietly(storage_path)
        raced = await document_service.find_active_by_hash(db, user_id, content_hash)
        if raced is None:
            raise ApiError(ERR_INTERNAL, "文档创建冲突且无法定位已有记录", status=500) from None
        response.status_code = status.HTTP_200_OK
        return _upload_response(raced, deduplicated=True)

    await _publish_task(document, settings.ingest_task_ttl_seconds)
    logger.info(
        "文档上传成功，已投递入库任务",
        extra=safe_extra(document_id=document_id, source_format=source_format),
    )
    return _upload_response(document, deduplicated=False)


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    db: DbSession = None,  # type: ignore[assignment]
) -> DocumentStatusResponse:
    """查询处理状态（六态）。

    Redis doc:task 快路径（高频轮询，中间状态由 worker 每阶段广播），
    miss 或越权回退 PostgreSQL 权威数据。
    """
    # 归一化为规范小写 UUID：uuid.UUID 接受大写/花括号/无连字符写法，
    # 而 Redis 键与 Qdrant doc_id 匹配均大小写敏感
    document_id = _ensure_document_id(document_id)

    try:
        cached = await redis_db.get_doc_task(document_id)
    except Exception as exc:  # noqa: BLE001  # Redis 不可用不阻断查询
        logger.warning(
            "读取任务状态缓存失败，回退 PostgreSQL：%s",
            exc,
            extra=safe_extra(document_id=document_id),
        )
        cached = None

    if cached is not None:
        if cached.get("user_id") != user_id:
            raise ApiError(ERR_DOC_NOT_FOUND, "文档不存在或不属于当前用户", status=404)
        return _status_response_from_dict(cached)

    document = await document_service.get_document(db, document_id, user_id)
    if document is None:
        raise ApiError(ERR_DOC_NOT_FOUND, "文档不存在或不属于当前用户", status=404)
    return _status_response_from_dict(document_service.task_payload(document))


@router.get("", response_model=Page[DocumentBrief])
async def list_documents(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    db: DbSession = None,  # type: ignore[assignment]
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[DocumentBrief]:
    """文档列表，按 created_at 倒序（AC-1.7）。"""
    items, total = await document_service.list_documents(
        db, user_id, status=status_filter, page=page, page_size=page_size
    )
    briefs = [
        DocumentBrief(
            document_id=str(item.id),
            filename=item.filename,
            status=item.status,
            source_format=item.source_format,
            file_size_bytes=item.file_size_bytes,
            chunk_count=item.chunk_count,
            page_count=item.page_count,
            created_at=item.created_at,
            ready_at=item.ready_at,
        )
        for item in items
    ]
    return Page(items=briefs, total=total, page=page, page_size=page_size)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DeleteDocumentResponse,
)
async def delete_document(
    document_id: str,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    db: DbSession = None,  # type: ignore[assignment]
) -> DeleteDocumentResponse:
    """删除文档（软删 + 异步清理向量）。

    仅 ready / failed 状态可删除（处理中需先取消任务，4091002）。
    """
    # 归一化为规范小写 UUID（缓存键 / purge 入队 / Qdrant doc_id 过滤一致）
    document_id = _ensure_document_id(document_id)

    document = await document_service.get_document(db, document_id, user_id)
    if document is None:
        raise ApiError(ERR_DOC_NOT_FOUND, "文档不存在或不属于当前用户", status=404)
    if document.status not in _DELETABLE_STATUSES:
        raise ApiError(ERR_DOC_DELETE_BUSY, "文档正在处理中，无法删除", status=409)

    await document_service.soft_delete_document(db, document)
    await db.commit()
    await _finalize_delete(document_id)

    return DeleteDocumentResponse(
        document_id=document_id,
        status="deleting",
        message="文档已进入删除队列，向量数据将在后台清理",
    )


# ---------------- 内部实现 ----------------


def _ensure_document_id(document_id: str) -> str:
    """document_id 必须是合法 UUID；非法格式按不存在处理（4041001），避免 PG 报 500。"""
    try:
        return str(uuid.UUID(document_id))
    except ValueError:
        raise ApiError(ERR_DOC_NOT_FOUND, "文档不存在或不属于当前用户", status=404) from None


def _remove_file_quietly(storage_path: str) -> None:
    """删除孤儿文件；失败仅记日志。"""
    try:
        Path(storage_path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("孤儿文件删除失败：%s", exc, extra=safe_extra(storage_path=storage_path))


def _upload_response(document: Document, *, deduplicated: bool) -> UploadDocumentResponse:
    return UploadDocumentResponse(
        document_id=str(document.id),
        filename=document.filename,
        status=document.status,
        deduplicated=deduplicated,
        created_at=document.created_at,
    )


def _status_response_from_dict(payload: dict) -> DocumentStatusResponse:
    """API-3 响应统一构造（Redis 快路径与 PG 回退共用，user_id 不透出）。"""
    return DocumentStatusResponse(
        document_id=str(payload.get("document_id", "")),
        filename=str(payload.get("filename", "")),
        status=str(payload.get("status", "uploaded")),
        chunk_count=payload.get("chunk_count"),
        page_count=payload.get("page_count"),
        updated_at=payload.get("updated_at"),
        error=payload.get("error"),
    )


async def _publish_task(document: Document, ttl_seconds: int) -> None:
    """上传后立即写入任务状态并投递入库任务（Redis 不可用时重试，最终失败告警）。"""
    document_id = str(document.id)
    for attempt in range(1, _ENQUEUE_ATTEMPTS + 1):
        try:
            await redis_db.set_doc_task(
                document_id, document_service.task_payload(document), ttl_seconds
            )
            await redis_db.enqueue_ingest(document_id)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "任务状态写入 / 投递失败（第 %d/%d 次）：%s",
                attempt,
                _ENQUEUE_ATTEMPTS,
                exc,
                extra=safe_extra(document_id=document_id),
            )
            if attempt < _ENQUEUE_ATTEMPTS:
                await asyncio.sleep(0.5 * attempt)
    logger.error(
        "入库任务投递失败，文档停留在 uploaded，需补偿投递",
        extra=safe_extra(document_id=document_id),
    )


async def _finalize_delete(document_id: str) -> None:
    """软删后：失效 API-3 缓存（软删立即生效）+ 重试投递 purge 任务。"""
    for attempt in range(1, _ENQUEUE_ATTEMPTS + 1):
        try:
            await redis_db.delete_doc_task(document_id)
            await redis_db.enqueue_purge(document_id)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "缓存失效 / 清理任务投递失败（第 %d/%d 次）：%s",
                attempt,
                _ENQUEUE_ATTEMPTS,
                exc,
                extra=safe_extra(document_id=document_id),
            )
            if attempt < _ENQUEUE_ATTEMPTS:
                await asyncio.sleep(0.5 * attempt)
    logger.error(
        "purge 任务投递失败，文档向量未清理，需对账补偿",
        extra=safe_extra(document_id=document_id),
    )
