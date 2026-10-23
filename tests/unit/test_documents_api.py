"""文档接口测试（M1）。

以依赖覆盖 + 打桩覆盖 API-2 ~ API-5 的接口行为：
    - 上传 202 / 命中去重 200 / 校验失败 400 / 超配额 4001005 / 并发冲突回查
    - 状态查询 Redis 快路径 / PG 回退 / 越权 404
    - 列表分页结构
    - 删除 202 / 处理中 409 / 不存在 404

不连接真实中间件：会话依赖被覆盖，服务函数与 Redis 操作全部打桩。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api import documents as documents_api  # noqa: F401  # 确保路由模块已加载
from app.core.errors import ApiError
from app.db import redis as redis_db
from app.db.postgres import get_session
from app.main import app
from app.models.document import Document
from app.services import document_service

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
OTHER_USER = "11111111-2222-3333-4444-555555555555"
DOC_ID = "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
HEADERS = {"X-User-Id": USER_ID}


class DummySession:
    """仅实现路由用到的提交 / 回滚。"""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _document(**kwargs) -> Document:
    base = dict(
        id=DOC_ID,
        user_id=USER_ID,
        filename="report.md",
        content_hash="h" * 64,
        source_format="md",
        file_size_bytes=128,
        status="ready",
        chunk_count=5,
        page_count=None,
        created_at=datetime(2026, 10, 23, 10, 0, 0, tzinfo=UTC),
    )
    base.update(kwargs)
    return Document(**base)


@pytest.fixture
def client(monkeypatch):
    """装配 TestClient：覆盖会话依赖 + 打桩服务与 Redis。"""
    dummy = DummySession()

    async def _override_session():
        yield dummy

    app.dependency_overrides[get_session] = _override_session

    calls: dict = {"enqueue_ingest": [], "enqueue_purge": [], "set_task": []}

    async def _enqueue_ingest(document_id):
        calls["enqueue_ingest"].append(document_id)

    async def _enqueue_purge(document_id):
        calls["enqueue_purge"].append(document_id)

    async def _set_doc_task(document_id, payload, ttl):
        calls["set_task"].append((document_id, payload))

    async def _get_doc_task(document_id):
        return None

    monkeypatch.setattr(redis_db, "get_doc_task", _get_doc_task)
    monkeypatch.setattr(redis_db, "set_doc_task", _set_doc_task)
    monkeypatch.setattr(redis_db, "enqueue_ingest", _enqueue_ingest)
    monkeypatch.setattr(redis_db, "enqueue_purge", _enqueue_purge)

    # 服务层默认桩（各测试按需覆盖）
    monkeypatch.setattr(document_service, "validate_upload", lambda *a, **k: "md")
    monkeypatch.setattr(document_service, "find_active_by_hash", _async_none)
    monkeypatch.setattr(document_service, "count_user_documents", _async_zero)
    monkeypatch.setattr(document_service, "create_document", _create_document)
    monkeypatch.setattr(document_service, "get_document", _async_none)
    monkeypatch.setattr(document_service, "list_documents", _list_empty)
    monkeypatch.setattr(document_service, "soft_delete_document", _async_noop)

    test_client = TestClient(app)
    test_client.calls = calls  # type: ignore[attr-defined]
    test_client.dummy_session = dummy  # type: ignore[attr-defined]
    test_client._monkeypatch = monkeypatch  # type: ignore[attr-defined]
    yield test_client

    app.dependency_overrides.clear()


# ---------------- 桩函数 ----------------


async def _async_none(*args, **kwargs):
    return None


async def _async_zero(*args, **kwargs):
    return 0


async def _async_noop(*args, **kwargs):
    return None


async def _create_document(session, **kwargs):
    return _document(
        id=kwargs.get("document_id") or DOC_ID,
        filename=kwargs["filename"],
        status="uploaded",
    )


async def _list_empty(session, user_id, **kwargs):
    return [], 0


# ---------------- API-2 上传 ----------------


def test_upload_returns_202_and_enqueues(client):
    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("report.md", b"# hello", "text/markdown")},
        headers=HEADERS,
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["deduplicated"] is False
    assert body["status"] == "uploaded"
    assert body["document_id"]
    assert client.calls["enqueue_ingest"] == [body["document_id"]]
    assert client.dummy_session.commits == 1


def test_upload_dedup_returns_200(client, monkeypatch):
    existing = _document(status="ready")

    async def _find(session, user_id, content_hash):
        return existing

    monkeypatch.setattr(document_service, "find_active_by_hash", _find)

    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("report.md", b"# hello", "text/markdown")},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["deduplicated"] is True
    assert body["status"] == "ready"
    assert client.calls["enqueue_ingest"] == []  # 去中不重复投递


def test_upload_rejects_invalid_file(client, monkeypatch):
    def _boom(filename, data, settings):
        raise ApiError("4001003", "不支持的文件类型：exe", status=400)

    monkeypatch.setattr(document_service, "validate_upload", _boom)

    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("a.exe", b"MZ", "application/octet-stream")},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "4001003"


def test_upload_rejects_over_quota(client, monkeypatch):
    async def _full(session, user_id):
        return 500

    monkeypatch.setattr(document_service, "count_user_documents", _full)

    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("report.md", b"# hello", "text/markdown")},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "4001005"
    assert client.calls["enqueue_ingest"] == []


def test_upload_integrity_error_falls_back_to_dedup(client, monkeypatch):
    raced = _document(status="uploaded")
    find_results = iter([None, raced])  # 第一次去重未命中，冲突后回查命中

    async def _find(session, user_id, content_hash):
        return next(find_results)

    async def _conflict(session, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    monkeypatch.setattr(document_service, "find_active_by_hash", _find)
    monkeypatch.setattr(document_service, "create_document", _conflict)

    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("report.md", b"# hello", "text/markdown")},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json()["deduplicated"] is True
    assert client.dummy_session.rollbacks == 1


def test_upload_requires_user_header(client):
    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("report.md", b"# hello", "text/markdown")},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "4010001"


# ---------------- API-3 状态 ----------------


def test_status_uses_redis_fast_path(client, monkeypatch):
    payload = {
        "user_id": USER_ID,
        "document_id": DOC_ID,
        "filename": "report.md",
        "status": "embedding",
        "chunk_count": None,
        "page_count": None,
        "updated_at": "2026-10-23T10:00:58+00:00",
        "error": None,
    }
    monkeypatch.setattr(redis_db, "get_doc_task", _async_return(payload))

    def _pg_should_not_run(*args, **kwargs):  # pragma: no cover
        raise AssertionError("Redis 快路径命中时不应查询 PostgreSQL")

    monkeypatch.setattr(document_service, "get_document", _pg_should_not_run)

    resp = client.get(f"/api/v1/documents/{DOC_ID}/status", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "embedding"
    assert body["document_id"] == DOC_ID
    assert "user_id" not in body  # 缓存中的 user_id 不得外泄


def test_status_falls_back_to_pg(client):
    doc = _document(status="ready", chunk_count=5)

    async def _get(session, document_id, user_id):
        return doc

    monkeypatch_attr(client, "get_document", _get)

    resp = client.get(f"/api/v1/documents/{DOC_ID}/status", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_status_cache_ownership_mismatch_returns_404(client, monkeypatch):
    payload = {"user_id": OTHER_USER, "document_id": DOC_ID, "status": "ready"}
    monkeypatch.setattr(redis_db, "get_doc_task", _async_return(payload))

    resp = client.get(f"/api/v1/documents/{DOC_ID}/status", headers=HEADERS)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "4041001"


def test_status_missing_document_returns_404(client):
    resp = client.get(f"/api/v1/documents/{DOC_ID}/status", headers=HEADERS)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "4041001"


# ---------------- API-4 列表 ----------------


def test_list_documents_pagination(client, monkeypatch):
    doc = _document()

    async def _list(session, user_id, *, status=None, page=1, page_size=20):
        return [doc], 1

    monkeypatch_attr(client, "list_documents", _list)

    resp = client.get("/api/v1/documents?page=1&page_size=20&status=ready", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["items"][0]["document_id"] == DOC_ID
    assert body["items"][0]["status"] == "ready"


# ---------------- API-5 删除 ----------------


def test_delete_ready_document_returns_202(client, monkeypatch):
    async def _get(session, document_id, user_id):
        return _document(status="ready")

    monkeypatch_attr(client, "get_document", _get)

    resp = client.delete(f"/api/v1/documents/{DOC_ID}", headers=HEADERS)

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "deleting"
    assert client.calls["enqueue_purge"] == [DOC_ID]
    assert client.dummy_session.commits == 1


def test_delete_processing_document_returns_409(client, monkeypatch):
    async def _get(session, document_id, user_id):
        return _document(status="parsing")

    monkeypatch_attr(client, "get_document", _get)

    resp = client.delete(f"/api/v1/documents/{DOC_ID}", headers=HEADERS)

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "4091002"
    assert client.calls["enqueue_purge"] == []


def test_delete_missing_document_returns_404(client):
    resp = client.delete(f"/api/v1/documents/{DOC_ID}", headers=HEADERS)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "4041001"


# ---------------- 工具 ----------------


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn


def monkeypatch_attr(client, name, value):
    """在活动测试内替换 document_service 的属性（随测试自动恢复）。"""
    import app.services.document_service as ds

    client._monkeypatch.setattr(ds, name, value)
    return value
