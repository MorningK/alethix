"""API-7 流式问答接口契约测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import ask as ask_api  # noqa: F401  # 确保路由模块已加载
from app.core.errors import ERR_ASK_BAD_QUESTION, ERR_SESSION_BUSY, ApiError
from app.db.postgres import get_session
from app.main import app
from app.schemas.ask import AskRequest
from app.services import agent_service, ask_service, sse_event_service
from app.services.agent_service import ResearchResult
from app.services.ask_service import AskLock, AskPrepared
from app.services.sse_event_service import InMemorySSEEventStore

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"
RUN_ID = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"
HEADERS = {"X-User-Id": USER_ID}
PAYLOAD = {"session_id": SESSION_ID, "question": "主要风险有哪些？", "document_ids": []}


class DummyDb:
    async def execute(self, stmt, params=None):
        return None

    async def get(self, model, key):
        return None

    def add(self, item):
        return None

    async def commit(self):
        return None

    async def rollback(self):
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
    lock_calls: list[tuple[str, dict]] = []

    async def _prepare(**kwargs):
        return prepared

    async def _persist(**kwargs):
        return RUN_ID

    async def _acquire(**kwargs):
        lock_calls.append(("acquire", kwargs))
        return AskLock(token="token", degraded=False)

    async def _release(**kwargs):
        lock_calls.append(("release", kwargs))

    monkeypatch.setattr(ask_service, "prepare_ask", _prepare)
    monkeypatch.setattr(ask_service, "persist_research", _persist)
    monkeypatch.setattr(ask_service, "acquire_ask_lock", _acquire)
    monkeypatch.setattr(ask_service, "release_ask_lock", _release)
    sse_event_service.set_event_store(InMemorySSEEventStore(max_events=100))

    yield {"monkeypatch": monkeypatch, "lock_calls": lock_calls}

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
    stream_env["monkeypatch"].setattr(agent_service, "stream_research", _fake_stream)

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
    assert [name for name, _ in stream_env["lock_calls"]] == ["acquire", "release"]


def test_pre_stream_validation_returns_json_error(stream_env):
    async def _fail(**kwargs):
        raise ApiError(ERR_ASK_BAD_QUESTION, "question 不能为空", status=400)

    stream_env["monkeypatch"].setattr(ask_service, "prepare_ask", _fail)

    response = TestClient(app).post("/api/v1/ask/stream", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ERR_ASK_BAD_QUESTION


def test_execution_error_is_pushed_as_sse_error_event(stream_env):
    calls: list[dict] = []

    async def _fail(**kwargs):
        raise ApiError("5003001", "智能体执行失败", status=500)

    async def _mark(**kwargs):
        calls.append(kwargs)

    stream_env["monkeypatch"].setattr(agent_service, "stream_research", _fail)
    stream_env["monkeypatch"].setattr(ask_service, "mark_run_failed", _mark)

    response = TestClient(app).post("/api/v1/ask/stream", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "5003001" in response.text
    assert len(calls) == 1


def test_stream_registers_run_before_start(stream_env):
    calls: list[dict] = []

    async def _register(**kwargs):
        calls.append(kwargs)

    stream_env["monkeypatch"].setattr(ask_service, "register_stream_run", _register, raising=False)
    stream_env["monkeypatch"].setattr(agent_service, "stream_research", _fake_stream)

    response = TestClient(app).post("/api/v1/ask/stream", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["agent_run_id"] in response.text


class EmptyReplayStore:
    async def after(self, agent_run_id, event_id):
        return []


def test_completed_run_with_no_replayable_events_closes_stream():
    async def _collect():
        return [
            chunk
            async for chunk in ask_api._resume_events(
                agent_run_id=RUN_ID,
                run_status="done",
                store=EmptyReplayStore(),
                replay_from=0,
                heartbeat_seconds=0,
            )
        ]

    assert asyncio.run(_collect()) == []


def test_concurrent_stream_is_rejected_before_response(stream_env):
    async def _busy(**kwargs):
        raise ApiError(ERR_SESSION_BUSY, "该会话正在处理上一个问题", status=409)

    stream_env["monkeypatch"].setattr(ask_service, "acquire_ask_lock", _busy)

    response = TestClient(app).post("/api/v1/ask/stream", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == ERR_SESSION_BUSY


@pytest.mark.parametrize("run_status", ["running", "done", "failed"])
def test_resolve_existing_run_allows_all_lifecycle_statuses(monkeypatch, run_status):
    async def _execute(self, stmt, params=None):
        return SimpleNamespace(
            scalar_one_or_none=lambda: SimpleNamespace(id=RUN_ID, status=run_status)
        )

    monkeypatch.setattr(DummyDb, "execute", _execute)
    prepared = SimpleNamespace(chat_session=SimpleNamespace(id=SESSION_ID))

    resolved_id, resolved_status = asyncio.run(
        ask_api._resolve_existing_run(
            run_id=RUN_ID, user_id=USER_ID, db=DummyDb(), prepared=prepared
        )
    )
    assert resolved_id == RUN_ID
    assert resolved_status == run_status


def test_resume_replays_original_run_without_new_research(stream_env):
    monkeypatch = stream_env["monkeypatch"]
    store = sse_event_service.get_event_store()

    async def _seed():
        await store.append(RUN_ID, "started", {"agent_run_id": RUN_ID})
        await store.append(RUN_ID, "final_answer", {"agent_run_id": RUN_ID, "answer": "缓存答案"})

    asyncio.run(_seed())

    async def _execute(self, stmt, params=None):
        return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=RUN_ID, status="done"))

    monkeypatch.setattr(DummyDb, "execute", _execute)

    async def _must_not_run(**kwargs):
        raise AssertionError("恢复运行不得启动新调研")

    monkeypatch.setattr(agent_service, "stream_research", _must_not_run)
    monkeypatch.setattr(ask_service, "persist_research", _must_not_run)

    response = TestClient(app).post(
        "/api/v1/ask/stream",
        headers={**HEADERS, "X-Agent-Run-Id": RUN_ID, "Last-Event-ID": "1"},
        json=PAYLOAD,
    )
    assert response.status_code == 200
    assert "event: final_answer" in response.text
    assert "缓存答案" in response.text
    assert "event: started" not in response.text
    assert stream_env["lock_calls"] == []
