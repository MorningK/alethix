"""文档接口（占位）。

API-2 POST   /documents/upload                 上传文档
API-3 GET    /documents/{document_id}/status    处理状态
API-4 GET    /documents                         文档列表
API-5 DELETE /documents/{document_id}           删除文档

契约见 prd/05-api-spec.md；对应 FR-1 ~ FR-3。
实现阶段：后端 M1。
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.schemas.common import NotImplementedResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def upload_document() -> NotImplementedResponse:
    """上传文档，异步处理。待 M1 实现。

    请求：multipart/form-data，字段 file（可选 session_id）
    响应 202：{ document_id, filename, status, deduplicated, created_at }
    """
    return NotImplementedResponse(detail="API-2 文档上传：待 M1 实现", api="API-2")


@router.get("/{document_id}/status", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def get_document_status(document_id: str) -> NotImplementedResponse:
    """查询处理状态（六态）。待 M1 实现。

    响应：{ document_id, filename, status, chunk_count, page_count, updated_at, error }
    """
    return NotImplementedResponse(
        detail=f"API-3 文档状态：待 M1 实现（document_id={document_id}）", api="API-3"
    )


@router.get("", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def list_documents() -> NotImplementedResponse:
    """文档列表，按 created_at 倒序。待 M1 实现。

    查询参数：status、page、page_size
    """
    return NotImplementedResponse(detail="API-4 文档列表：待 M1 实现", api="API-4")


@router.delete("/{document_id}", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def delete_document(document_id: str) -> NotImplementedResponse:
    """删除文档（软删 + 异步清理向量）。待 M1 实现。

    响应 202：{ document_id, status: deleting, message }
    """
    return NotImplementedResponse(
        detail=f"API-5 删除文档：待 M1 实现（document_id={document_id}）", api="API-5"
    )
