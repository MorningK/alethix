"""API-6 同步问答接口与编排服务测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import ask as ask_api  # noqa: F401  # 确保路由模块已加载
from app.core.errors import (
    ERR_ASK_BAD_MAX_ITER,
    ERR_ASK_BAD_QUESTION,
    ERR_VECTORDB_UNAVAILABLE,
    ApiError,
)
from app.db.postgres import get_session
from app.main import app
from app.schemas.ask import AskRequest, AskResponse
from app.services import ask_service, retrieval_service

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"
HEADERS = {"X-User-Id": USER_ID}
PAYLOAD = {"session_id": SESSION_ID, "question": "主要风险有哪些？", "document_ids": []}


def _response(**overrides) -> AskResponse:
    base = dict(
        agent_run_id="c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f",
        session_id=SESSION_ID,
        question=PAYLOAD["question"],
        answer="根据文档，主要风险包括数据合规风险。",
        confidence="medium",
        stop_reason="sufficient",
        iteration_count=1,
        duration_ms=120,
        token_used=0,
        iterations=[],
        citations=[],
    )
    base.update(overrides)
    return AskResponse(**base)


class DummySession:
    async def execute(self, stmt, params=None):
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch):
    async def _override_session():
        yield DummySession()

    app.dependency_overrides[get_session] = _override_session
    calls: dict = {}

    async def _run(*, payload, user_id, settings, db):
        calls["payload"] = payload
        calls["user_id"] = user_id
        return _response()

    monkeypatch.setattr(ask_service, "run_single_ask", _run)
    yield TestClient(app), calls
    app.dependency_overrides.clear()


def test_ask_success(client):
    http, calls = client
    response = http.post("/api/v1/ask", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == SESSION_ID
    assert body["iteration_count"] == 1
    assert calls["user_id"] == USER_ID


def test_ask_requires_user_header(client):
    http, _ = client
    response = http.post("/api/v1/ask", json=PAYLOAD)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "4010001"


def test_ask_propagates_llm_error(client, monkeypatch):
    http, _ = client

    async def _fail(*, payload, user_id, settings, db):
        raise ApiError("5032001", "大模型服务不可用", status=503)

    monkeypatch.setattr(ask_service, "run_single_ask", _fail)
    response = http.post("/api/v1/ask", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "5032001"


def test_ask_stream_still_placeholder(client):
    http, _ = client
    response = http.post("/api/v1/ask/stream", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 501


def test_validate_payload_rejects_bad_question():
    with pytest.raises(ApiError) as exc:
        ask_service._validate_payload(AskRequest(session_id=SESSION_ID, question="   "))
    assert exc.value.code == ERR_ASK_BAD_QUESTION


def test_validate_payload_rejects_bad_max_iterations():
    with pytest.raises(ApiError) as exc:
        ask_service._validate_payload(
            AskRequest(session_id=SESSION_ID, question="问题", max_iterations=0)
        )
    assert exc.value.code == ERR_ASK_BAD_MAX_ITER


async def test_run_single_ask_maps_vector_error(monkeypatch):
    payload = AskRequest(session_id=SESSION_ID, question="风险？", document_ids=[])

    async def _scope(*, payload, user_id, db):
        return SimpleNamespace(id=SESSION_ID, default_document_ids=[]), [], {}

    async def _search(**kwargs):
        raise ApiError(ERR_VECTORDB_UNAVAILABLE, "向量检索不可用", status=503)

    monkeypatch.setattr(ask_service, "_resolve_scope", _scope)
    monkeypatch.setattr(retrieval_service, "search", _search)

    with pytest.raises(ApiError) as exc:
        await ask_service.run_single_ask(
            payload=payload, user_id=USER_ID, db=DummySession(), settings=None
        )
    assert exc.value.code == ERR_VECTORDB_UNAVAILABLE
    assert exc.value.status == 503
