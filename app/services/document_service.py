"""文档服务（占位）。

职责：文档元数据与生命周期管理（DM-2）。
对应 FR-1 ~ FR-3。实现阶段：M1。

关键流程：
    上传 → 校验（类型/魔数/大小）→ content_hash 去重 → 落 documents(status=uploaded)
    → 投递入库任务 → worker 推进 parsing/chunking/embedding → ready
"""

from __future__ import annotations

from app.core.config import Settings


def compute_content_hash(data: bytes) -> str:
    """计算文件内容 SHA-256，用于重复上传去重（FR-1 第 3 条）。"""
    import hashlib

    return hashlib.sha256(data).hexdigest()


def build_storage_path(settings: Settings, document_id: str, ext: str) -> str:
    """原始文件存储路径。服务端以 document_id 命名，不直接使用用户文件名。"""
    return f"{settings.storage_path.rstrip('/')}/{document_id}.{ext}"
