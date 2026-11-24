"""条件边与终止策略。

终止条件按 prd/03-agent-design.md §4.2 的固定优先级求值，命中即短路。
路由函数保持纯函数：只读状态，不修改状态；stop_reason 由 NODE-4 写入。
"""

from __future__ import annotations

from time import monotonic
from typing import Literal

from app.agents.state import AgentState
from app.core.config import get_settings

Route = Literal["plan_queries", "final_answer"]


def resolve_stop_reason(
    state: AgentState,
    *,
    no_new_evidence_rounds: int | None = None,
    settings=None,
) -> str | None:
    """按优先级返回终止原因；不修改输入状态。"""
    s = settings or get_settings()

    # 1. 前置节点已判定终止
    stop = state.get("stop_reason")
    if stop in ("no_new_queries", "low_relevance"):
        return stop

    # 2. 证据充分
    if state.get("is_sufficient"):
        return "sufficient"

    # 3. 达到最大轮次
    if state.get("iteration", 0) >= state.get("max_iterations", s.agent_max_iterations):
        return "max_iterations_reached"

    # 4. 连续无新增证据
    threshold = (
        no_new_evidence_rounds
        if no_new_evidence_rounds is not None
        else s.agent_no_new_evidence_rounds
    )
    if state.get("no_new_evidence_rounds", 0) >= threshold:
        return "no_new_evidence"

    # 5. Token 预算 / 总耗时超限
    if state.get("token_used", 0) >= state.get("token_budget", s.agent_token_budget):
        return "budget_exceeded"
    timeout = state.get("timeout_seconds", s.agent_timeout_seconds)
    started_at = state.get("started_at")
    if started_at is not None and monotonic() - started_at >= timeout:
        return "budget_exceeded"

    return None


def route_after_decide(state: AgentState) -> Route:
    """决定继续规划下一轮还是进入终答节点。"""
    return "final_answer" if resolve_stop_reason(state) else "plan_queries"
