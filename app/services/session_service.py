"""会话服务（占位）。

职责：会话与消息管理（DM-4 / DM-5）。
追问的指代消解在进入图之前完成（AG-1.28）。

实现阶段：M2。
"""

from __future__ import annotations


async def create_session(
    *, user_id: str, title: str | None = None, default_document_ids: list[str] | None = None
) -> dict:
    """创建会话（API-1）。待 M2 实现。"""
    raise NotImplementedError("待 M2 实现")


async def list_messages(*, session_id: str, page: int = 1, page_size: int = 20) -> dict:
    """拉取会话历史（API-8），按时间正序。待 M2 实现。"""
    raise NotImplementedError("待 M2 实现")
