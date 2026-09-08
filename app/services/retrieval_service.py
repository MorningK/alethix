"""检索服务（占位）。

职责：查询向量化 → Qdrant 检索 → 跨查询/跨轮次合并去重。

约束见 prd/03-agent-design.md §6.1 / §6.2：
    - user_id 过滤必须无条件附加（AG-1.2）
    - 多查询结果按 chunk_id 合并，保留最高分（AG-1.6）
    - 分数阈值过滤（AG-2.4）

实现阶段：M2。
"""

from __future__ import annotations

from app.services.qdrant_service import build_filter


async def search(
    *,
    query: str,
    user_id: str,
    document_ids: list[str] | None = None,
    top_k: int = 10,
    score_threshold: float | None = None,
) -> list[dict]:
    """执行检索。待 M2 实现。

    filter 必须使用 build_filter(user_id, document_ids)，禁止绕过。
    """
    raise NotImplementedError("待 M2 实现；filter 见 qdrant_service.build_filter")


__all__ = ["build_filter", "search"]
