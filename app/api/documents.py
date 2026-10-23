"""文档接口。

API-2 POST   /documents/upload                 上传文档
API-3 GET    /documents/{document_id}/status    处理状态
API-4 GET    /documents                         文档列表
API-5 DELETE /documents/{document_id}           删除文档

契约见 prd/05-api-spec.md §2；对应 FR-1 ~ FR-3。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUserId, DbSession, SettingsDep
from app.core.errors import (
    ERR_DOC_DELETE_BUSY,
    ERR_DOC_NOT_FOUND,
    ERR_INTERNAL,
    ApiError,
)
from app.core.logging import get_logger, safe_extra
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


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadDocumentResponse,
)
async def upload_document(
    file: UploadFile = File(...),
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
    data = await file.read()
    source_format = document_service.validate_upload(file.filename or "", data, settings)
    content_hash = document_service.compute_content_hash(data)

    # 去重（AC-1.5）：同用户同内容直接返回已有文档
    existing = await document_service.find_active_by_hash(db, user_id, content_hash)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _upload_response(existing, deduplicated=True)

    # 配额校验（4001005）
    count = await document_service.count_user_documents(db, user_id)
    document_service.check_quota(count)

    document_id = str(uuid.uuid4())
    storage_path = document_service.save_upload_file(settings, document_id, source_format, data)

    try:
        document = await document_service.create_document(
            db,
            user_id=user_id,
            filename=file.filename or document_id,
            content_hash=content_hash,
            source_format=source_format,
            file_size_bytes=len(data),
            storage_path=storage_path,
            mime_type=file.content_type,
            document_id=document_id,
        )
        await db.commit()
    except IntegrityError:
        # 并发上传同一文件（B-8）：部分唯一索引兜底，回查已有记录并按去重响应
        await db.rollback()
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

    Redis doc:task 快路径（高频轮询），miss 或越权回退 PostgreSQL 权威数据。
    """
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
        return DocumentStatusResponse(
            document_id=str(cached.get("document_id", document_id)),
            filename=str(cached.get("filename", "")),
            status=str(cached.get("status", "uploaded")),
            chunk_count=cached.get("chunk_count"),
            page_count=cached.get("page_count"),
            updated_at=cached.get("updated_at"),
            error=cached.get("error"),
        )

    document = await document_service.get_document(db, document_id, user_id)
    if document is None:
        raise ApiError(ERR_DOC_NOT_FOUND, "文档不存在或不属于当前用户", status=404)
    return _status_response(document)


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
    document = await document_service.get_document(db, document_id, user_id)
    if document is None:
        raise ApiError(ERR_DOC_NOT_FOUND, "文档不存在或不属于当前用户", status=404)
    if document.status not in ("ready", "failed"):
        raise ApiError(ERR_DOC_DELETE_BUSY, "文档正在处理中，无法删除", status=409)

    await document_service.soft_delete_document(db, document)
    await db.commit()

    try:
        await redis_db.enqueue_purge(document_id)
    except Exception as exc:  # noqa: BLE001  # Redis 不可用不阻断软删
        logger.warning(
            "清理任务投递失败（Redis 不可用）：%s",
            exc,
            extra=safe_extra(document_id=document_id),
        )
    return DeleteDocumentResponse(
        document_id=document_id,
        status="deleting",
        message="文档已进入删除队列，向量数据将在后台清理",
    )


# ---------------- 内部实现 ----------------


def _upload_response(document: Document, *, deduplicated: bool) -> UploadDocumentResponse:
    return UploadDocumentResponse(
        document_id=str(document.id),
        filename=document.filename,
        status=document.status,
        deduplicated=deduplicated,
        created_at=document.created_at,
    )


def _status_response(document: Document) -> DocumentStatusResponse:
    error = None
    if document.error_code:
        error = {"code": document.error_code, "message": document.error_message or ""}
    return DocumentStatusResponse(
        document_id=str(document.id),
        filename=document.filename,
        status=document.status,
        chunk_count=document.chunk_count,
        page_count=document.page_count,
        updated_at=document.updated_at,
        error=error,
    )


async def _publish_task(document: Document, ttl_seconds: int) -> None:
    """上传后立即写入任务状态，使 API-3 立即可查（Redis 不可用不阻断）。"""
    try:
        await redis_db.set_doc_task(
            str(document.id), document_service.task_payload(document), ttl_seconds
        )
        await redis_db.enqueue_ingest(str(document.id))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "任务状态写入 / 投递失败（Redis 不可用）：%s",
            exc,
            extra=safe_extra(document_id=str(document.id)),
        )
