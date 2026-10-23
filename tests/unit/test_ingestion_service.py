"""入库服务测试（M1）。

以打桩方式覆盖 ingestion_service 编排逻辑：
    - 状态机推进顺序 parsing → chunking → embedding → ready
    - 先 PG 后 Qdrant：chunk_id 同时作为 Point ID，payload 含越权过滤字段
    - 解析失败（4xx）与向量化失败（5xx）均置 failed 并回滚 Qdrant 残留 Point
    - purge：删 Qdrant Point → 删本地文件 → 硬删文档行
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.core.errors import ERR_DOC_UNREADABLE, ERR_INTERNAL, ApiError
from app.db import postgres
from app.models.document import Document
from app.services import ingestion_service, qdrant_service
from app.services.parser_service import ParsedBlock, ParseResult

NO_ENV_FILE = {"_env_file": None}

DOC_ID = "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"


class FakeSession:
    """记录状态提交序列与 ORM 操作的假会话。"""

    def __init__(self, document: Document | None) -> None:
        self.document = document
        self.status_log: list[str] = []
        self.commits = 0
        self.added: list = []
        self.deleted: list = []

    async def commit(self) -> None:
        self.commits += 1
        if self.document is not None:
            self.status_log.append(self.document.status)

    async def rollback(self) -> None:
        pass

    async def flush(self) -> None:
        pass

    def add(self, obj) -> None:
        self.added.append(obj)

    def add_all(self, objs) -> None:
        self.added.extend(objs)

    async def delete(self, obj) -> None:
        self.deleted.append(obj)

    async def execute(self, stmt):  # pragma: no cover - 不应被走到
        raise AssertionError("测试不应直接执行 SQL")


def _document(**kwargs) -> Document:
    base = dict(
        id=DOC_ID,
        user_id=USER_ID,
        filename="report.pdf",
        content_hash="h" * 64,
        source_format="pdf",
        storage_path="",
        status="uploaded",
    )
    base.update(kwargs)
    return Document(**base)


def _parse_result() -> ParseResult:
    return ParseResult(
        blocks=[
            ParsedBlock(content="第一段内容。第二句话。", page=1, section="第一章"),
            ParsedBlock(content="第二段内容。", page=2, section="第二章"),
        ],
        title="测试报告",
        page_count=2,
    )


async def _fake_embed(texts, settings):
    return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture
def stub_env(monkeypatch):
    """打桩 PG 会话 / 解析 / Qdrant / Redis，返回记录容器。"""
    document = _document()
    session = FakeSession(document)
    upserts: list = []
    deletes: list[tuple[str, str]] = []
    task_writes: list[dict] = []

    @asynccontextmanager
    async def fake_scope():
        yield session

    monkeypatch.setattr(postgres, "session_scope", fake_scope)
    monkeypatch.setattr(ingestion_service.postgres, "session_scope", fake_scope)
    monkeypatch.setattr(ingestion_service, "get_any_document", _async_return(document))
    monkeypatch.setattr(
        ingestion_service, "get_document_including_deleted", _async_return(document)
    )
    monkeypatch.setattr(ingestion_service, "parse_document", _sync_return(_parse_result()))
    monkeypatch.setattr(qdrant_service, "upsert_points", _record_upsert(upserts))
    monkeypatch.setattr(qdrant_service, "delete_by_document_id", _record_delete(deletes))

    async def fake_set_task(document_id, payload, ttl):
        task_writes.append(payload)

    monkeypatch.setattr(ingestion_service.redis_db, "set_doc_task", fake_set_task)

    return SimpleNamespace(
        document=document,
        session=session,
        upserts=upserts,
        deletes=deletes,
        task_writes=task_writes,
    )


class SimpleNamespace:  # 轻量记录容器
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn


def _sync_return(value):
    def _fn(*args, **kwargs):
        return value

    return _fn


def _record_upsert(sink: list):
    def _fn(settings, points):
        sink.extend(points)
        return len(points)

    return _fn


def _record_delete(sink: list):
    def _fn(settings, user_id, document_id):
        sink.append((user_id, document_id))

    return _fn


# ---------------- 正常入库 ----------------


async def test_ingest_happy_path(stub_env):
    settings = Settings(**NO_ENV_FILE)

    await ingestion_service.ingest_document(DOC_ID, settings=settings, embed_fn=_fake_embed)

    # 状态机顺序：parsing → chunking → embedding → ready（初始 uploaded 不提交）
    assert stub_env.session.status_log == ["parsing", "chunking", "embedding", "ready"]
    assert stub_env.document.status == "ready"
    assert stub_env.document.chunk_count == 2
    assert stub_env.document.page_count == 2
    assert stub_env.document.title == "测试报告"
    assert stub_env.document.ready_at is not None

    # 先 PG 后 Qdrant：chunks 先 add_all，再 upsert；point id 即 chunk_id
    assert len(stub_env.session.added) == 2
    chunk_ids = {c.id for c in stub_env.session.added}
    assert len(stub_env.upserts) == 2
    for point_id, vector, payload in stub_env.upserts:
        assert point_id in chunk_ids
        assert payload["user_id"] == USER_ID
        assert payload["doc_id"] == DOC_ID
        assert payload["content"]  # payload 存纯正文
        assert "chunk_index" in payload
        assert vector == [0.1, 0.2, 0.3]

    # 终态写入 Redis 任务状态
    assert stub_env.task_writes and stub_env.task_writes[-1]["status"] == "ready"


async def test_ingest_skips_ready_document(stub_env):
    stub_env.document.status = "ready"
    settings = Settings(**NO_ENV_FILE)

    await ingestion_service.ingest_document(DOC_ID, settings=settings, embed_fn=_fake_embed)

    assert stub_env.session.status_log == []
    assert stub_env.upserts == []


# ---------------- 失败路径 ----------------


async def test_ingest_parse_failure_marks_failed_and_rolls_back(stub_env, monkeypatch):
    settings = Settings(**NO_ENV_FILE)

    def boom(*args, **kwargs):
        raise ApiError(ERR_DOC_UNREADABLE, "扫描件无可提取文本", status=400)

    monkeypatch.setattr(ingestion_service, "parse_document", boom)

    with pytest.raises(ApiError) as exc:
        await ingestion_service.ingest_document(DOC_ID, settings=settings, embed_fn=_fake_embed)

    assert exc.value.code == ERR_DOC_UNREADABLE
    assert stub_env.document.status == "failed"
    assert stub_env.document.error_code == ERR_DOC_UNREADABLE
    # 回滚 Qdrant 残留 Point（幂等）
    assert stub_env.deletes == [(USER_ID, DOC_ID)]
    assert stub_env.task_writes[-1]["status"] == "failed"


async def test_ingest_embed_failure_wrapped_as_internal(stub_env):
    settings = Settings(**NO_ENV_FILE)

    async def boom(texts, settings):
        raise RuntimeError("embedding endpoint down")

    with pytest.raises(ApiError) as exc:
        await ingestion_service.ingest_document(DOC_ID, settings=settings, embed_fn=boom)

    assert exc.value.code == ERR_INTERNAL
    assert exc.value.status == 500
    assert stub_env.document.status == "failed"
    assert stub_env.deletes == [(USER_ID, DOC_ID)]


# ---------------- 物理清理 ----------------


async def test_purge_deletes_points_file_and_row(stub_env, tmp_path, monkeypatch):
    settings = Settings(**NO_ENV_FILE)
    target = tmp_path / "stored.pdf"
    target.write_bytes(b"%PDF-1.4")
    stub_env.document.storage_path = str(target)
    stub_env.document.deleted_at = datetime.now(UTC)

    await ingestion_service.purge_document(DOC_ID, settings=settings)

    assert stub_env.deletes == [(USER_ID, DOC_ID)]
    assert not target.exists()  # 本地文件已删
    assert stub_env.session.deleted == [stub_env.document]  # 硬删（级联 chunks）


async def test_purge_missing_document_is_noop(stub_env, monkeypatch):
    settings = Settings(**NO_ENV_FILE)
    monkeypatch.setattr(ingestion_service, "get_document_including_deleted", _async_return(None))

    await ingestion_service.purge_document(DOC_ID, settings=settings)

    assert stub_env.deletes == []
    assert stub_env.session.deleted == []
