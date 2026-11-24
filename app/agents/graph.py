"""StateGraph 组装与编译单例。

拓扑：START → plan_queries → retrieve_documents → analyze_evidence
      → decide_next_step →(条件边)→ plan_queries | final_answer → END

图结构见 prd/03-agent-design.md §2。编译一次、复用实例（AG-6.4）。
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents import runtime
from app.agents.nodes import (
    analyze_evidence,
    decide_next_step,
    final_answer,
    plan_queries,
    retrieve_documents,
)
from app.agents.routing import route_after_decide
from app.agents.state import AgentState

_graph: Any | None = None


def build_graph(*, checkpointer: Any | None = None) -> Any:
    """构建并编译调研状态机。"""
    builder = StateGraph(AgentState)

    builder.add_node("plan_queries", plan_queries)
    builder.add_node("retrieve_documents", retrieve_documents)
    builder.add_node("analyze_evidence", analyze_evidence)
    builder.add_node("decide_next_step", decide_next_step)
    builder.add_node("final_answer", final_answer)

    builder.add_edge(START, "plan_queries")
    builder.add_edge("plan_queries", "retrieve_documents")
    builder.add_edge("retrieve_documents", "analyze_evidence")
    builder.add_edge("analyze_evidence", "decide_next_step")
    builder.add_conditional_edges(
        "decide_next_step",
        route_after_decide,
        {"plan_queries": "plan_queries", "final_answer": "final_answer"},
    )
    builder.add_edge("final_answer", END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else runtime.get_checkpointer()
    )


def get_graph() -> Any:
    """获取编译后的图单例。"""
    global _graph
    if _graph is None:
        try:
            checkpointer = runtime.get_checkpointer()
        except RuntimeError:
            # 未走应用 lifespan 的场景（脚本 / 单测）使用内存检查点兜底。
            checkpointer = InMemorySaver()
        _graph = build_graph(checkpointer=checkpointer)
    return _graph


def reset_graph() -> None:
    """重置图单例，供测试切换 checkpointer 使用。"""
    global _graph
    _graph = None


__all__ = ["build_graph", "get_graph", "reset_graph"]
