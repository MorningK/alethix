"""查询向量 Redis 缓存与降级测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.core.config import Settings
from app.db import redis as redis_db
from app.services import qdrant_service, retrieval_service


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


async def test_query_embedding_is_cached(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(redis_db, "get_redis", lambda: fake_redis)

    calls: list[list[str]] = []

    async def _embed(texts, settings=None):
        calls.append(list(texts))
        return [[0.1, 0.2, 0.3]]

    def _query(settings, vector, query_filter, **kwargs):
        return [
            SimpleNamespace(
                id="chunk-1",
                payload={"doc_id": "doc-1", "content": "命中"},
                score=0.9,
            )
        ]

    monkeypatch.setattr(retrieval_service, "embed_texts", _embed)
    monkeypatch.setattr(qdrant_service, "query_points", _query)
    settings = Settings(_env_file=None)

    await retrieval_service.search(query="风险", user_id="user-1", settings=settings)
    await retrieval_service.search(query="风险", user_id="user-1", settings=settings)

    assert len(calls) == 1
    cached = await fake_redis.get(redis_db.key_embedding_cache("风险"))
    assert json.loads(cached) == [0.1, 0.2, 0.3]


async def test_redis_unavailable_falls_back_to_embedding(monkeypatch):
    def _broken_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(redis_db, "get_redis", _broken_redis)

    calls: list[str] = []

    async def _embed(texts, settings=None):
        calls.append(texts[0])
        return [[0.4, 0.5]]

    monkeypatch.setattr(retrieval_service, "embed_texts", _embed)
    monkeypatch.setattr(qdrant_service, "query_points", lambda *a, **k: [])

    hits = await retrieval_service.search(
        query="风险", user_id="user-1", settings=Settings(_env_file=None)
    )
    assert hits == []
    assert calls == ["风险"]
