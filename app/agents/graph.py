"""StateGraph 组装（占位）。

拓扑：START → plan_queries → retrieve_documents → analyze_evidence
      → decide_next_step →(条件边)→ plan_queries | final_answer → END

图结构见 prd/03-agent-design.md §2。实现阶段：M3。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.state import AgentState


def build_graph():
    """构建并编译调研状态机。

    实现要点（prd/03-agent-design.md §2.2）：
        - 五节点：plan_queries / retrieve_documents / analyze_evidence /
                  decide_next_step / final_answer
        - add_conditional_edges("decide_next_step", route_after_decide, {...})
        - checkpointer 使用 AsyncPostgresSaver，thread_id 取 agent_run_id（AG-6.1/6.2）
    """
    builder = StateGraph(AgentState)

    builder.add_node("plan_queries", _not_implemented("plan_queries"))
    builder.add_node("retrieve_documents", _not_implemented("retrieve_documents"))
    builder.add_node("analyze_evidence", _not_implemented("analyze_evidence"))
    builder.add_node("decide_next_step", _not_implemented("decide_next_step"))
    builder.add_node("final_answer", _not_implemented("final_answer"))

    builder.add_edge(START, "plan_queries")
    builder.add_edge("plan_queries", "retrieve_documents")
    builder.add_edge("retrieve_documents", "analyze_evidence")
    builder.add_edge("analyze_evidence", "decide_next_step")
    builder.add_edge("final_answer", END)

    return builder


def _not_implemented(name: str):
    async def _node(state: AgentState) -> dict:
        raise NotImplementedError(f"节点 {name} 待 M3 实现：见 prd/03-agent-design.md §3")

    _node.__name__ = name
    return _node
