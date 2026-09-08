"""健康检查冒烟测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_returns_components():
    """健康检查应返回三个中间件的连通性明细，且不因组件不可用而抛异常。"""
    with TestClient(app) as client:
        resp = client.get("/healthz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert set(body["components"]) == {"postgres", "redis", "qdrant"}


def test_api_health():
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
