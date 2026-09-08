"""文档入库服务（占位）。

编排「解析 → 清洗 → 切片 → 向量化 → 写入 Qdrant」全流程。
写入顺序见 prd/04-data-model.md §5.1：先 PG 落 chunks，再写 Qdrant。

实现阶段：M1。
"""

from __future__ import annotations


async def ingest_document(document_id: str) -> None:
    """执行单个文档的入库流程。由 worker 调用。

    状态推进：parsing → chunking → embedding → ready
    任一环节失败：置 failed 并清理 Qdrant 残留 Point（幂等）
    """
    raise NotImplementedError("待 M1 实现")
