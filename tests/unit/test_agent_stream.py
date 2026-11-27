"""LangGraph astream 事件映射测试。"""

from __future__ import annotations

from app.agents.state import IterationRecord
from app.core.config import Settings
from app.services import agent_service

RUN_ID = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"


class FakeGraph:
    """按节点顺序产出状态增量，替代真实 LLM 与检索。"""

    def __init__(self, chunks: list[dict]) -> None:
        self.chunks = chunks

    def astream(self, state, *, config, stream_mode):
        async def _generate():
            for chunk in self.chunks:
                yield chunk

        return _generate()


async def test_stream_research_maps_nodes_to_sse_events(monkeypatch):
    record = IterationRecord(
        iteration=1,
        queries=["风险"],
        retrieved_chunk_count=2,
        new_chunk_count=2,
        findings=["发现"],
        conflicts=[],
        decision="answer",
        reason="证据充分",
    )
    chunks = [
        {"plan_queries": {"iteration": 1, "queries": ["风险"], "searched_queries": ["风险"]}},
        {"analyze_evidence": {"findings": ["发现"], "used_chunk_ids": ["chunk-1"]}},
        {
            "decide_next_step": {
                "stop_reason": "sufficient",
                "iterations": [record],
                "missing_information": "",
            }
        },
        {
            "final_answer": {
                "final_answer": "答案",
                "confidence": "high",
                "stop_reason": "sufficient",
            }
        },
    ]
    monkeypatch.setattr(agent_service, "get_graph", lambda: FakeGraph(chunks))

    events: list[tuple[str, dict]] = []

    async def _sink(event: str, data: dict) -> None:
        events.append((event, data))

    result = await agent_service.stream_research(
        agent_run_id=RUN_ID,
        question="主要风险有哪些？",
        session_id=SESSION_ID,
        user_id="9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34",
        document_ids=["doc-1"],
        filename_map={"doc-1": "报告.pdf"},
        max_iterations=3,
        event_sink=_sink,
        settings=Settings(_env_file=None, app_env="test", agent_timeout_seconds=10),
    )

    assert [event for event, _ in events] == ["iteration", "retrieved", "reasoning"]
    assert events[0][1]["queries"] == ["风险"]
    assert events[1][1]["iteration"] == 1
    assert events[2][1]["decision"] == "answer"
    assert result.answer == "答案"
    assert result.stop_reason == "sufficient"
