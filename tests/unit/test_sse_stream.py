"""API-7 流式问答接口契约测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import ask as ask_api  # noqa: F401  # 确保路由模块已加载
from app.core.errors import ERR_ASK_BAD_QUESTION, ApiError
from app.db.postgres import get_session
from app.main import app
from app.schemas.ask import AskRequest
from app.services import agent_service, ask_service, sse_event_service
from app.services.agent_service import ResearchResult
from app.services.ask_service import AskPrepared
from app.services.sse_event_service import InMemorySSEEventStore

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"
RUN_ID = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"
HEADERS = {"X-User-Id": USER_ID}
PAYLOAD = {"session_id": SESSION_ID, "question": "主要风险有哪些？", "document_ids": []}


class DummyDb:
    async def execute(self, stmt, params=None):
        return None


@pytest.fixture(autouse=True)
def stream_env(monkeypatch):
    async def _override_session():
        yield DummyDb()

    app.dependency_overrides[get_session] = _override_session

    prepared = AskPrepared(
        payload=AskRequest(**PAYLOAD),
        chat_session=SimpleNamespace(id=SESSION_ID),
        scope_ids=["doc-1"],
        filename_map={"doc-1": "报告.pdf"},
        question="主要风险有哪些？",
        history_findings=[],
    )

    async def _prepare(**kwargs):
        return prepared

    async def _persist(**kwargs):
        return RUN_ID

    monkeypatch.setattr(ask_service, "prepare_ask", _prepare)
    monkeypatch.setattr(ask_service, "persist_research", _persist)
    sse_event_service.set_event_store(InMemorySSEEventStore(max_events=100))

    yield monkeypatch

    app.dependency_overrides.clear()
    sse_event_service.set_event_store(None)


def _research() -> ResearchResult:
    return ResearchResult(
        agent_run_id=RUN_ID,
        state={"max_score": 0.82},
        answer="根据文档，主要风险是数据合规风险。",
        confidence="medium",
        stop_reason="sufficient",
        iterations=[],
        citations=[],
        token_used=120,
        prompt_tokens=60,
        completion_tokens=60,
        llm_call_count=3,
        fallback_count=0,
        citation_filtered_count=0,
        duration_ms=1200,
    )


async def _fake_stream(**kwargs):
    sink = kwargs["event_sink"]
    await sink("iteration", {"iteration": 1, "queries": ["主要风险"], "searched_query_count": 1})
    await sink(
        "retrieved",
        {"iteration": 1, "retrieved_chunk_count": 4, "new_chunk_count": 4, "max_score": 0.82},
    )
    await sink(
        "reasoning",
        {
            "iteration": 1,
            "decision": "answer",
            "reason": "证据充分",
            "missing_information": "",
            "findings_count": 2,
            "conflicts_count": 0,
        },
    )
    return _research()


def test_stream_emits_full_event_sequence(stream_env):
    stream_env.setattr(agent_service, "stream_research", _fake_stream)

    response = TestClient(app).post("/api/v1/ask/stream", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"

    body = response.text
    for event in ("started", "iteration", "retrieved", "reasoning", "final_answer"):
        assert f"event: {event}" in body
    assert "数据合规风险" in body
    assert "id: 1" in body
    assert "event: error" not in body


def test_pre_stream_validation_returns_json_error(stream_env):
    async def _fail(**kwargs):
        raise ApiError(ERR_ASK_BAD_QUESTION, "question 不能为空", status=400)

    stream_env.setattr(ask_service, "prepare_ask", _fail)

    response = TestClient(app).post("/api/v1/ask/stream", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ERR_ASK_BAD_QUESTION


def test_execution_error_is_pushed_as_sse_error_event(stream_env):
    async def _fail(**kwargs):
        raise ApiError("5003001", "智能体执行失败", status=500)

    stream_env.setattr(agent_service, "stream_research", _fail)

    response = TestClient(app).post("/api/v1/ask/stream", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "5003001" in response.text
