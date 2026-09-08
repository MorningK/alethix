"""五个状态机节点（占位）。

    NODE-1 plan_queries          规划本轮检索查询
    NODE-2 retrieve_documents    检索 Qdrant 并合并去重
    NODE-3 analyze_evidence      提取发现与冲突
    NODE-4 decide_next_step      判断证据是否充分
    NODE-5 final_answer          生成带引用的答案

职责与输入输出契约见 prd/03-agent-design.md §3。实现阶段：M3。
"""

from __future__ import annotations

from app.agents.state import AgentState


async def plan_queries(state: AgentState) -> dict:
    """NODE-1：规划本轮查询。首轮基于原始问题，后续基于 findings 与缺口。"""
    raise NotImplementedError("待 M3 实现：见 prd/03-agent-design.md §3.1")


async def retrieve_documents(state: AgentState) -> dict:
    """NODE-2：并发检索并按 chunk_id 合并去重，计算本轮最高分。"""
    raise NotImplementedError("待 M3 实现：见 prd/03-agent-design.md §3.2")


async def analyze_evidence(state: AgentState) -> dict:
    """NODE-3：提取发现、校验 used_chunk_ids、识别冲突。"""
    raise NotImplementedError("待 M3 实现：见 prd/03-agent-design.md §3.3")


async def decide_next_step(state: AgentState) -> dict:
    """NODE-4：判断证据是否充分。本系统区别于普通 RAG 的关键节点。"""
    raise NotImplementedError("待 M3 实现：见 prd/03-agent-design.md §3.4")


async def final_answer(state: AgentState) -> dict:
    """NODE-5：生成最终答案，并做引用白名单校验（AG-1.21）。"""
    raise NotImplementedError("待 M3 实现：见 prd/03-agent-design.md §3.5")
