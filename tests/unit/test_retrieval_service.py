"""检索服务单测：过滤条件、命中归一化与异常映射。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.errors import ERR_LLM_UNAVAILABLE, ERR_VECTORDB_UNAVAILABLE, ApiError
from app.services import qdrant_service, retrieval_service

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
DOC_ID = "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
CHUNK_ID = "b1e2d3c4-5f6a-7b8c-9d0e-1f2a3b4c5d6e"


def _settings() -> Settings:
    return Settings(embedding_dim=3, agent_top_k_per_query=5, agent_score_threshold=0.35)


def _point() -> SimpleNamespace:
    return SimpleNamespace(
        id=CHUNK_ID,
        score=0.82,
        payload={
            "user_id": USER_ID,
            "doc_id": DOC_ID,
            "content": "数据合规风险需要重点关注。",
            "chunk_index": 3,
            "page": 5,
            "section": "3.2 风险分析",
            "title": "AI 行业报告",
        },
    )


async def test_search_builds_filter_and_normalizes_hits(monkeypatch):
    captured: dict = {}

    async def _embed(texts, settings=None):
        captured["texts"] = texts
        return [[0.1, 0.2, 0.3]]

    def _query(settings, vector, query_filter, **kwargs):
        captured["filter"] = query_filter
        captured["kwargs"] = kwargs
        return [_point()]

    monkeypatch.setattr(retrieval_service, "embed_texts", _embed)
    monkeypatch.setattr(qdrant_service, "query_points", _query)

    hits = await retrieval_service.search(
        query="风险有哪些",
        user_id=USER_ID,
        document_ids=[DOC_ID],
        top_k=5,
        score_threshold=0.35,
        settings=_settings(),
    )

    assert captured["texts"] == ["风险有哪些"]
    conditions = captured["filter"].must
    assert conditions[0].key == "user_id"
    assert conditions[0].match.value == USER_ID
    assert conditions[1].key == "doc_id"
    assert conditions[1].match.value == DOC_ID
    assert captured["kwargs"]["limit"] == 5
    assert len(hits) == 1
    assert hits[0].chunk_id == CHUNK_ID
    assert hits[0].document_id == DOC_ID
    assert hits[0].score == 0.82
    assert hits[0].page == 5


async def test_search_maps_embedding_failure(monkeypatch):
    async def _embed(texts, settings=None):
        raise RuntimeError("embedding down")

    monkeypatch.setattr(retrieval_service, "embed_texts", _embed)
    with pytest.raises(ApiError) as exc:
        await retrieval_service.search(query="风险", user_id=USER_ID, settings=_settings())
    assert exc.value.code == ERR_LLM_UNAVAILABLE
    assert exc.value.status == 503


async def test_search_maps_qdrant_failure(monkeypatch):
    async def _embed(texts, settings=None):
        return [[0.1, 0.2, 0.3]]

    def _query(*args, **kwargs):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(retrieval_service, "embed_texts", _embed)
    monkeypatch.setattr(qdrant_service, "query_points", _query)
    with pytest.raises(ApiError) as exc:
        await retrieval_service.search(query="风险", user_id=USER_ID, settings=_settings())
    assert exc.value.code == ERR_VECTORDB_UNAVAILABLE
    assert exc.value.status == 503
