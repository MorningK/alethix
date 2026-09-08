"""文档相关 DTO。

字段与 prd/05-api-spec.md §2.1 / §2.2 对齐。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# 文档处理状态，见 README 状态枚举速查
DOCUMENT_STATUSES = ("uploaded", "parsing", "chunking", "embedding", "ready", "failed")


class DocumentBrief(BaseModel):
    """文档摘要（API-2 / API-3 / API-4 复用）。"""

    document_id: str
    filename: str
    status: str = Field(description="uploaded/parsing/chunking/embedding/ready/failed")
    source_format: str | None = None
    file_size_bytes: int | None = None
    chunk_count: int | None = None
    page_count: int | None = None
    created_at: datetime | None = None
    ready_at: datetime | None = None


class UploadDocumentResponse(BaseModel):
    """API-2 响应。"""

    document_id: str
    filename: str
    status: str
    deduplicated: bool = False
    created_at: datetime | None = None


class DocumentError(BaseModel):
    code: str
    message: str


class DocumentStatusResponse(BaseModel):
    """API-3 响应。"""

    document_id: str
    filename: str
    status: str
    chunk_count: int | None = None
    page_count: int | None = None
    updated_at: datetime | None = None
    error: DocumentError | None = None


class Citation(BaseModel):
    """引用（prd/05-api-spec.md §2.2）。"""

    document_id: str
    chunk_id: str
    filename: str
    page: int | None = None
    section: str | None = None
    quote: str
    score: float | None = None
