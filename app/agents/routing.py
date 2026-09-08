"""条件边与终止策略（占位）。

终止条件按固定优先级短路求值，优先级见 prd/03-agent-design.md §4.2：
    1. 前置节点已判定（no_new_queries / low_relevance）
    2. is_sufficient
    3. iteration >= max_iterations
    4. no_new_evidence_rounds >= N
    5. Token 预算 / 总耗时超限

实现阶段：M3。
"""

from __future__ import annotations

from typing import Literal

from app.agents.state import AgentState

Route = Literal["plan_queries", "final_answer"]


def route_after_decide(state: AgentState) -> Route:
    """按优先级求值终止条件，命中则收尾，否则继续下一轮。

    注意：实现时应将 stop_reason 的写入下沉到独立节点，
    或使用 Command(goto=..., update={...}) 同时完成路由与状态更新；
    但**终止条件的优先级顺序不得改变**。
    """
    raise NotImplementedError("待 M3 实现：见 prd/03-agent-design.md §4.1")
