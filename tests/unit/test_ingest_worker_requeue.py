"""ingest worker 重试入队路由测试。

打桩 Redis 计数、sleep 与入队函数，不依赖真实中间件。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.db import redis as redis_db
from workers import ingest_worker

DOCUMENT_ID = "00935f9e-c408-44ab-847d-30e6c307933a"


@pytest.fixture
def stub_worker(monkeypatch):
    calls: list[tuple[str, str]] = []
    retry = {"count": 1}

    async def _next_retry_count(document_id: str) -> int:
        return retry["count"]

    async def _no_sleep(seconds: int) -> None:
        return None

    async def _ingest(document_id: str) -> None:
        calls.append(("ingest", document_id))

    async def _purge(document_id: str) -> None:
        calls.append(("purge", document_id))

    monkeypatch.setattr(redis_db, "next_retry_count", _next_retry_count)
    monkeypatch.setattr(ingest_worker.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(redis_db, "enqueue_ingest", _ingest)
    monkeypatch.setattr(redis_db, "enqueue_purge", _purge)

    worker = ingest_worker.IngestWorker(Settings(ingest_max_retries=3))
    return worker, calls, retry


async def test_requeue_routes_ingest_queue(stub_worker):
    worker, calls, _ = stub_worker

    result = await worker._requeue_with_backoff(DOCUMENT_ID, redis_db.key_ingest_queue())

    assert result is True
    assert calls == [("ingest", DOCUMENT_ID)]


async def test_requeue_routes_purge_queue(stub_worker):
    worker, calls, _ = stub_worker

    result = await worker._requeue_with_backoff(DOCUMENT_ID, redis_db.key_purge_queue())

    assert result is True
    assert calls == [("purge", DOCUMENT_ID)]


async def test_requeue_ignores_unknown_queue(stub_worker):
    worker, calls, _ = stub_worker

    result = await worker._requeue_with_backoff(DOCUMENT_ID, "queue:unknown")

    assert result is False
    assert calls == []


async def test_requeue_stops_after_max_retries(stub_worker):
    worker, calls, retry = stub_worker
    retry["count"] = 4

    result = await worker._requeue_with_backoff(DOCUMENT_ID, redis_db.key_ingest_queue())

    assert result is False
    assert calls == []
