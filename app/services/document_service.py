"""文档服务。

职责：文档元数据与生命周期管理（DM-2）。
对应 FR-1 ~ FR-3。实现阶段：M1。

关键流程：
    上传 → 校验（类型/魔数/大小）→ content_hash 去重 → 落 documents(status=uploaded)
    → 投递入库任务 → worker 推进 parsing/chunking/embedding → ready
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ERR_DOC_PARAM, ERR_DOC_QUOTA, ERR_DOC_TYPE_OR_SIZE, ApiError
from app.models.document import Document
from app.services.parser_service import detect_format

# 单用户文档数上限（prd/05-api-spec.md API-2 约束）
MAX_DOCUMENTS_PER_USER = 500


def compute_content_hash(data: bytes) -> str:
    """计算文件内容 SHA-256，用于重复上传去重（FR-1 第 3 条）。"""
    return hashlib.sha256(data).hexdigest()


def build_storage_path(settings: Settings, document_id: str, ext: str) -> str:
    """原始文件存储路径。服务端以 document_id 命名，不直接使用用户文件名。"""
    return f"{settings.storage_path.rstrip('/')}/{document_id}.{ext}"


def validate_upload(filename: str, data: bytes, settings: Settings) -> str:
    """上传校验：扩展名白名单 + 魔数 + 大小（API-2 约束）。

    返回归一化格式（pdf / md / txt）；任一不满足抛出对应错误码。
    """
    if not filename or filename.strip() == "":
        raise ApiError(ERR_DOC_PARAM, "文件名不能为空", status=400)
    if len(data) == 0:
        raise ApiError(ERR_DOC_TYPE_OR_SIZE, "文件内容为空", status=400)
    if len(data) > settings.max_file_size_bytes:
        raise ApiError(
            ERR_DOC_TYPE_OR_SIZE,
            f"文件大小超过限制（{settings.doc_max_file_size_mb} MB）",
            status=400,
        )
    return detect_format(filename, data, settings.allowed_extensions)


def check_quota(document_count: int, limit: int = MAX_DOCUMENTS_PER_USER) -> None:
    """配额校验：单用户有效文档数达到上限即拒绝（4001005）。"""
    if document_count >= limit:
        raise ApiError(
            ERR_DOC_QUOTA,
            f"文档数量已达上限（{limit} 篇），请先清理后再上传",
            status=400,
        )


def save_upload_file(settings: Settings, document_id: str, ext: str, data: bytes) -> str:
    """落盘原始文件（以 document_id 命名），返回存储路径。"""
    storage_path = build_storage_path(settings, document_id, ext)
    path = Path(storage_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return storage_path


async def create_document(
    session: AsyncSession,
    *,
    user_id: str,
    filename: str,
    content_hash: str,
    source_format: str,
    file_size_bytes: int,
    storage_path: str,
    mime_type: str | None = None,
    document_id: str | None = None,
) -> Document:
    """插入文档记录（status=uploaded）。document_id 缺省由调用方传入 UUID。"""
    document = Document(
        id=document_id,
        user_id=user_id,
        filename=filename,
        content_hash=content_hash,
        mime_type=mime_type,
        source_format=source_format,
        file_size_bytes=file_size_bytes,
        storage_path=storage_path,
        status="uploaded",
    )
    session.add(document)
    await session.flush()
    return document


async def find_active_by_hash(
    session: AsyncSession, user_id: str, content_hash: str
) -> Document | None:
    """查找同用户同内容的未删除文档（去重，AC-1.5）。"""
    stmt = select(Document).where(
        Document.user_id == user_id,
        Document.content_hash == content_hash,
        Document.deleted_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_document(session: AsyncSession, document_id: str, user_id: str) -> Document | None:
    """按 id + user_id 查询；越权与不存在一律返回 None（API 层统一 404）。"""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.user_id == user_id,
        Document.deleted_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def count_user_documents(session: AsyncSession, user_id: str) -> int:
    """统计用户有效文档数（配额校验）。"""
    stmt = (
        select(func.count())
        .select_from(Document)
        .where(Document.user_id == user_id, Document.deleted_at.is_(None))
    )
    return int((await session.execute(stmt)).scalar_one())


async def list_documents(
    session: AsyncSession,
    user_id: str,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[Sequence[Document], int]:
    """文档列表：created_at 倒序 + 可选状态过滤（AC-1.7）。返回 (items, total)。"""
    conditions = [Document.user_id == user_id, Document.deleted_at.is_(None)]
    if status:
        conditions.append(Document.status == status)

    count_stmt = select(func.count()).select_from(Document).where(*conditions)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        select(Document)
        .where(*conditions)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = (await session.execute(stmt)).scalars().all()
    return items, total


async def get_any_document(session: AsyncSession, document_id: str) -> Document | None:
    """按 id 查询文档（worker 无用户上下文时使用）。"""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.deleted_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_document_including_deleted(
    session: AsyncSession, document_id: str
) -> Document | None:
    """按 id 查询文档（含软删；purge 物理清理使用）。"""
    stmt = select(Document).where(Document.id == document_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def soft_delete_document(session: AsyncSession, document: Document) -> None:
    """软删：立即生效，物理清理由 purge 任务异步执行（AC-1.8）。"""
    document.deleted_at = datetime.now(UTC)
    await session.flush()


def task_payload(document: Document) -> dict:
    """构造 doc:task:{id} 与 API-3 共用的任务状态快照（prd/05-api-spec.md §2）。

    user_id 仅用于缓存路径的越权校验，不返回给客户端（Pydantic 默认忽略多余字段）。

    注意：updated_at 为 server_default + onupdate=now()，UPDATE 提交后 SQLAlchemy 会将该列
    标记为 expired，异步上下文中读取会触发懒加载并抛 MissingGreenlet。快照时间取当前时刻
    （写入时机即状态变更时机，语义等价）。
    """
    error = None
    if document.error_code:
        error = {"code": document.error_code, "message": document.error_message or ""}
    return {
        "user_id": document.user_id,
        "document_id": str(document.id),
        "filename": document.filename,
        "status": document.status,
        "chunk_count": document.chunk_count,
        "page_count": document.page_count,
        "updated_at": datetime.now(UTC).isoformat(),
        "error": error,
    }


async def hard_delete_document(session: AsyncSession, document: Document) -> None:
    """物理删除文档行（chunks 经 ON DELETE CASCADE 级联清理）。"""
    await session.delete(document)
    await session.flush()


__all__ = [
    "MAX_DOCUMENTS_PER_USER",
    "build_storage_path",
    "check_quota",
    "compute_content_hash",
    "count_user_documents",
    "create_document",
    "find_active_by_hash",
    "get_any_document",
    "get_document",
    "get_document_including_deleted",
    "hard_delete_document",
    "list_documents",
    "save_upload_file",
    "soft_delete_document",
    "task_payload",
    "validate_upload",
]
