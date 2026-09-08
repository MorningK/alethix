"""智能体运行服务（占位）。

职责：agent_run 编排、trace 落库、迭代与引用持久化。
对应 DM-6 ~ DM-9。实现阶段：M3。
"""

from __future__ import annotations


async def run_research(*, agent_run_id: str, question: str, session_id: str, user_id: str) -> dict:
    """执行一次调研运行。待 M3 实现。"""
    raise NotImplementedError("待 M3 实现")
