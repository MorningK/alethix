"""API-1 创建会话接口测试。

以依赖覆盖 + 服务打桩验证 201 / 401 / 业务错误码，不连接真实数据库。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import sessions as sessions_api  # noqa: F401  # 确保路由模块已加载
from app.core.errors import ERR_SESSION_PARAM, ApiError
from app.db.postgres import get_session
from app.main import app
from app.schemas.session import SessionResponse
from app.services import session_service

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
HEADERS = {"X-User-Id": USER_ID}


class DummySession:
    async def execute(self, stmt, params=None):
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch):
    dummy = DummySession()

    async def _override_session():
        yield dummy

    app.dependency_overrides[get_session] = _override_session
    calls: dict = {}

    async def _create_session(*, payload, user_id, db):
        calls["payload"] = payload
        calls["user_id"] = user_id
        return SessionResponse(
            session_id="7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f",
            title=payload.title,
            default_document_ids=payload.default_document_ids,
            message_count=0,
        )

    monkeypatch.setattr(session_service, "create_session", _create_session)
    yield TestClient(app), calls
    app.dependency_overrides.clear()


def test_create_session_success(client):
    http, calls = client
    response = http.post(
        "/api/v1/sessions",
        headers=HEADERS,
        json={"title": "研读报告", "default_document_ids": []},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"
    assert body["title"] == "研读报告"
    assert body["message_count"] == 0
    assert calls["user_id"] == USER_ID


def test_create_session_requires_user_header(client):
    http, _ = client
    response = http.post("/api/v1/sessions", json={"title": "研读报告"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "4010001"


def test_create_session_maps_service_error(client, monkeypatch):
    http, _ = client

    async def _fail(*, payload, user_id, db):
        raise ApiError(ERR_SESSION_PARAM, "默认文档范围无效", status=400)

    monkeypatch.setattr(session_service, "create_session", _fail)
    response = http.post("/api/v1/sessions", headers=HEADERS, json={"title": "研读报告"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ERR_SESSION_PARAM
