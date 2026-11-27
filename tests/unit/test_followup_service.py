"""追问改写与历史发现注入测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.agent import Iteration
from app.models.session import Message
from app.services import followup_service, llm_service

SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"
RUN_ID = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"
USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"


class FakeDb:
    """按调用顺序返回消息与迭代记录。"""

    def __init__(self, batches: list[list]) -> None:
        self.batches = batches
        self.index = 0

    async def execute(self, stmt):
        rows = self.batches[min(self.index, len(self.batches) - 1)]
        self.index += 1
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _history():
    message = Message(
        id=1,
        session_id=SESSION_ID,
        role="assistant",
        content="上一轮结论：方案具备明显成本优势。",
        agent_run_id=RUN_ID,
        seq=2,
    )
    iteration = Iteration(
        agent_run_id=RUN_ID,
        iteration=1,
        findings=["历史发现：成本下降 20%"],
        conflicts=[],
    )
    return message, iteration


@pytest.fixture
def settings():
    return Settings(_env_file=None, app_env="test")


async def test_first_question_skips_rewrite(monkeypatch, settings):
    calls: list[str] = []

    async def _rewrite(*args, **kwargs):
        calls.append("rewrite")
        raise AssertionError("首轮不应调用改写")

    monkeypatch.setattr(llm_service, "invoke_structured", _rewrite)
    question, findings = await followup_service.build_followup_context(
        session_id=SESSION_ID,
        question="方案的主要风险有哪些？",
        user_id=USER_ID,
        db=FakeDb([[]]),
        settings=settings,
    )
    assert question == "方案的主要风险有哪些？"
    assert findings == []
    assert calls == []


async def test_followup_rewrite_and_history_findings(monkeypatch, settings):
    message, iteration = _history()
    calls: list[str] = []

    async def _rewrite(schema, *, messages, settings=None, node="", temperature=None):
        calls.append(node)
        return SimpleNamespace(payload=SimpleNamespace(question="方案 X 的缺点有哪些？"))

    monkeypatch.setattr(llm_service, "invoke_structured", _rewrite)
    question, findings = await followup_service.build_followup_context(
        session_id=SESSION_ID,
        question="那它的缺点呢？",
        user_id=USER_ID,
        db=FakeDb([[message], [iteration]]),
        settings=settings,
    )
    assert question == "方案 X 的缺点有哪些？"
    assert findings == ["历史发现：成本下降 20%"]
    assert calls == ["followup_rewrite"]


async def test_rewrite_failure_falls_back_to_original_question(monkeypatch, settings):
    message, iteration = _history()

    async def _rewrite(*args, **kwargs):
        return SimpleNamespace(payload=None)

    monkeypatch.setattr(llm_service, "invoke_structured", _rewrite)
    question, findings = await followup_service.build_followup_context(
        session_id=SESSION_ID,
        question="那它的缺点呢？",
        user_id=USER_ID,
        db=FakeDb([[message], [iteration]]),
        settings=settings,
    )
    assert question == "那它的缺点呢？"
    assert findings == ["历史发现：成本下降 20%"]
