"""智能体运行时服务测试。"""

from __future__ import annotations

from types import SimpleNamespace

from app.agents.state import IterationRecord as StateIteration
from app.core.config import Settings
from app.services import agent_service

RUN_ID = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"
USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"


async def test_timeout_recovers_latest_checkpoint_state(monkeypatch):
    completed = StateIteration(
        iteration=1,
        queries=["查询"],
        retrieved_chunk_count=2,
        new_chunk_count=2,
        findings=["已完成发现"],
        conflicts=[],
        decision="continue",
        reason="证据不足",
        max_score=0.8,
        missing_information="缺少风险等级",
    )

    class FakeGraph:
        async def ainvoke(self, state, config):
            raise TimeoutError()

        async def aget_state(self, config):
            return SimpleNamespace(
                values={
                    "findings": ["已完成发现"],
                    "used_chunk_ids": [],
                    "iterations": [completed],
                    "token_used": 12,
                    "final_answer": "",
                    "confidence": "low",
                    "citations": [],
                    "stop_reason": None,
                    "status": "deciding",
                }
            )

    monkeypatch.setattr(agent_service, "get_graph", lambda: FakeGraph())

    result = await agent_service.run_research(
        agent_run_id=RUN_ID,
        question="风险？",
        session_id=SESSION_ID,
        user_id=USER_ID,
        document_ids=["doc-1"],
        filename_map={"doc-1": "报告.pdf"},
        max_iterations=3,
        settings=Settings(_env_file=None, app_env="test", agent_timeout_seconds=1),
    )

    assert result.stop_reason == "budget_exceeded"
    assert result.token_used == 12
    assert len(result.iterations) == 1
    assert "已完成发现" in result.answer
