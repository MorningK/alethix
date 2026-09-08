"""文档入库 worker（占位）。

消费入库任务：解析 → 切片 → 向量化 → 写入 Qdrant，并推进 documents 状态。
任务幂等锁见 prd/04-data-model.md §7.1（doc:lock:{document_id}）。

实现阶段：M1。
"""

from __future__ import annotations


def process_document_task(document_id: str) -> None:
    """处理单个文档的入库任务。待 M1 实现。"""
    raise NotImplementedError("待 M1 实现")
