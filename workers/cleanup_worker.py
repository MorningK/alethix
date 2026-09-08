"""清理与一致性补偿 worker（占位）。

职责：
    - 删除软删文档的 Qdrant Point 与数据库记录
    - 修正「非终态且超时」的文档状态
    - 对账 PG chunks 与 Qdrant Point 计数，差异则重建

策略见 prd/04-data-model.md §5.2 / §5.3。实现阶段：M5。
"""

from __future__ import annotations


def reconcile() -> None:
    """执行一致性对账与补偿。待 M5 实现。"""
    raise NotImplementedError("待 M5 实现")
