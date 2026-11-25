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
from app.core.config import get_settings

_graph: Any | None = None
_graph_checkpointer: Any | None = None


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


def _resolve_checkpointer() -> Any:
    try:
        return runtime.get_checkpointer()
    except RuntimeError:
        if get_settings().app_env == "test":
            return InMemorySaver()
        raise RuntimeError("LangGraph checkpointer 未初始化，无法执行多轮调研")


def get_graph() -> Any:
    """获取编译后的图单例；检查点变化时自动重建。"""
    global _graph, _graph_checkpointer
    checkpointer = _resolve_checkpointer()
    if _graph is None or _graph_checkpointer is not checkpointer:
        _graph = build_graph(checkpointer=checkpointer)
        _graph_checkpointer = checkpointer
    return _graph


def reset_graph() -> None:
    """重置图单例，供测试切换 checkpointer 使用。"""
    global _graph, _graph_checkpointer
    _graph = None
    _graph_checkpointer = None


__all__ = ["build_graph", "get_graph", "reset_graph"]
