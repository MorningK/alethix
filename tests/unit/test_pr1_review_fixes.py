"""PR #1 CodeRabbit 复查评论的回归测试。

逐条覆盖 8 条评论中可在单测层验证的修复：
    1. 上传读取有上限（read 最多 limit + 1 字节）
    2. 配额校验前按用户加 advisory 锁（与 insert 同事务）
    3. document_id 归一化为规范小写 UUID 后再用于缓存 / 入队
    4. BLPOP 超时 clamp 到 socket_timeout 之下
    5. worker run() 先初始化中间件客户端
    6. 英文句点作为句界（不影响 3.5 这类小数）
    7. DSN 百分号经 ConfigParser 转义后可正确读回
"""

from __future__ import annotations

import pytest
from alembic.config import Config
from fastapi import Response

from app.api import documents as documents_api
from app.core.config import Settings
from app.db import redis as redis_db
from app.models.document import Document
from app.services import document_service
from app.services.chunk_service import _block_to_units
from app.services.parser_service import ParsedBlock
from workers.ingest_worker import IngestWorker

NO_ENV_FILE = {"_env_file": None}

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
DOC_ID = "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
DOC_ID_UPPER = DOC_ID.upper()


class DummySession:
    """记录 execute / commit 的最小假会话。"""

    def __init__(self) -> None:
        self.executed: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


class FakeUploadFile:
    """记录 read(size) 入参的假上传文件。"""

    def __init__(self, data: bytes, filename: str = "report.md") -> None:
        self.filename = filename
        self.content_type = "text/markdown"
        self._data = data
        self.read_sizes: list = []

    async def read(self, size: int = -1):
        self.read_sizes.append(size)
        if size is None or size < 0:
            return self._data
        return self._data[:size]


class FakeRedis:
    """记录 blpop 入参的假 Redis 客户端。"""

    def __init__(self, socket_timeout=None) -> None:
        self.connection_pool = type("Pool", (), {})()
        self.connection_pool.connection_kwargs = (
            {"socket_timeout": socket_timeout} if socket_timeout is not None else {}
        )
        self.blpop_calls: list = []

    async def blpop(self, keys, timeout=0):
        self.blpop_calls.append((list(keys), timeout))
        return None


def _document(**kwargs) -> Document:
    base = dict(
        id=DOC_ID,
        user_id=USER_ID,
        filename="report.md",
        content_hash="h" * 64,
        source_format="md",
        status="ready",
    )
    base.update(kwargs)
    return Document(**base)


# ---------------- 1 / 2 / 3：上传与删除 ----------------


async def test_upload_reads_at_most_limit_plus_one(monkeypatch):
    settings = Settings(doc_max_file_size_mb=1, **NO_ENV_FILE)
    upload = FakeUploadFile(b"# hello")
    db = DummySession()
    published: list[str] = []

    monkeypatch.setattr(document_service, "validate_upload", lambda *a, **k: "md")
    monkeypatch.setattr(document_service, "find_active_by_hash", _async_none)
    monkeypatch.setattr(document_service, "count_user_documents", _async_zero)
    monkeypatch.setattr(document_service, "check_quota", lambda *a, **k: None)
    monkeypatch.setattr(document_service, "save_upload_file", lambda *a, **k: "/tmp/x.md")
    monkeypatch.setattr(document_service, "create_document", _create_document)
    monkeypatch.setattr(redis_db, "set_doc_task", _record_task(published, "set"))
    monkeypatch.setattr(redis_db, "enqueue_ingest", _record_task(published, "ingest"))

    await documents_api.upload_document(
        file=upload,
        session_id=None,
        user_id=USER_ID,
        settings=settings,
        db=db,
        response=Response(),
    )

    # 读取上限 = 限制字节数 + 1（超限数据仍会被 validate_upload 拒绝）
    assert upload.read_sizes == [settings.max_file_size_bytes + 1]


async def test_upload_takes_per_user_advisory_lock_before_count(monkeypatch):
    settings = Settings(**NO_ENV_FILE)
    db = DummySession()

    monkeypatch.setattr(document_service, "validate_upload", lambda *a, **k: "md")
    monkeypatch.setattr(document_service, "find_active_by_hash", _async_none)
    monkeypatch.setattr(document_service, "count_user_documents", _async_zero)
    monkeypatch.setattr(document_service, "check_quota", lambda *a, **k: None)
    monkeypatch.setattr(document_service, "save_upload_file", lambda *a, **k: "/tmp/x.md")
    monkeypatch.setattr(document_service, "create_document", _create_document)
    monkeypatch.setattr(redis_db, "set_doc_task", _async_noop)
    monkeypatch.setattr(redis_db, "enqueue_ingest", _async_noop)

    await documents_api.upload_document(
        file=FakeUploadFile(b"# hello"),
        session_id=None,
        user_id=USER_ID,
        settings=settings,
        db=db,
        response=Response(),
    )

    lock_calls = [
        (stmt, params) for stmt, params in db.executed if "pg_advisory_xact_lock" in stmt and params
    ]
    assert lock_calls, "配额计数前未按用户加 advisory 锁"
    assert lock_calls[0][1] == {"uid": USER_ID}


async def test_delete_uses_canonical_lowercase_uuid(monkeypatch):
    db = DummySession()
    deleted_keys: list[str] = []
    purged: list[str] = []

    monkeypatch.setattr(document_service, "get_document", _async_return(_document(status="ready")))
    monkeypatch.setattr(document_service, "soft_delete_document", _async_noop)
    monkeypatch.setattr(redis_db, "delete_doc_task", _record_task(deleted_keys, "delete"))
    monkeypatch.setattr(redis_db, "enqueue_purge", _record_task(purged, "purge"))

    # 客户端传入大写 UUID：缓存键与 purge 入队都必须使用规范小写形式
    resp = await documents_api.delete_document(document_id=DOC_ID_UPPER, user_id=USER_ID, db=db)

    assert resp.document_id == DOC_ID
    assert deleted_keys == [DOC_ID]
    assert purged == [DOC_ID]


# ---------------- 4：BLPOP 超时 clamp ----------------


async def test_pop_task_clamps_timeout_below_socket_timeout(monkeypatch):
    fake = FakeRedis(socket_timeout=3)
    monkeypatch.setattr(redis_db, "get_redis", lambda: fake)

    result = await redis_db.pop_task(["queue:ingest"], timeout=5)

    assert result is None
    assert fake.blpop_calls == [(["queue:ingest"], 2)]  # min(5, 3-1)


async def test_pop_task_keeps_timeout_without_socket_timeout(monkeypatch):
    fake = FakeRedis(socket_timeout=None)
    monkeypatch.setattr(redis_db, "get_redis", lambda: fake)

    await redis_db.pop_task(["queue:ingest"], timeout=5)

    assert fake.blpop_calls == [(["queue:ingest"], 5)]


# ---------------- 5：worker 启动初始化 ----------------


async def test_worker_run_initializes_clients(monkeypatch):
    initialized: list[str] = []
    monkeypatch.setattr(IngestWorker, "init_clients", lambda self: initialized.append("init"))

    worker = IngestWorker(settings=Settings(**NO_ENV_FILE))

    async def fake_pop_task(queues, timeout=5):
        worker.request_stop()  # 首轮即请求停止，避免真实循环
        return None

    monkeypatch.setattr(redis_db, "pop_task", fake_pop_task)

    await worker.run()

    assert initialized == ["init"], "run() 进入循环前必须初始化中间件客户端"


# ---------------- 6：英文句界 ----------------


def test_english_sentence_boundary_keeps_decimals():
    text = "The value is 3.5 here. Next sentence follows."

    # _block_to_units 按句界切分原子单位：小数 3.5 不被切开，句点 + 空白处断开
    units = _block_to_units(ParsedBlock(content=text))

    assert [u.content for u in units] == [
        "The value is 3.5 here.",
        "Next sentence follows.",
    ]


# ---------------- 7：DSN 百分号转义 ----------------


def test_dsn_percent_round_trips_through_configparser():
    dsn = "postgresql+asyncpg://user:p%40ss@localhost:5432/alethix"

    # 未转义：ConfigParser 插值语法报错（env.py 修复前 alembic upgrade 直接失败）
    raw = Config()
    with pytest.raises(Exception):  # noqa: BLE001  # 具体异常类型随 Python 版本变化
        raw.set_main_option("sqlalchemy.url", dsn)
        raw.get_main_option("sqlalchemy.url")

    # 转义后原样读回
    escaped = Config()
    escaped.set_main_option("sqlalchemy.url", dsn.replace("%", "%%"))
    assert escaped.get_main_option("sqlalchemy.url") == dsn


# ---------------- 桩函数 ----------------


async def _async_none(*args, **kwargs):
    return None


async def _async_zero(*args, **kwargs):
    return 0


async def _async_noop(*args, **kwargs):
    return None


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn


async def _create_document(session, **kwargs):
    return _document(id=kwargs.get("document_id") or DOC_ID, filename=kwargs["filename"])


def _record_task(sink: list, tag: str):
    async def _fn(document_id, *args, **kwargs):
        sink.append(document_id)
        return None

    return _fn
