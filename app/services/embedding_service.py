"""Embedding 服务。

必须独立构造客户端，使用 resolved_embedding_*（AG-7.1）。
OpenAIEmbeddings 关键参数（已核对 langchain-openai 文档）：
    model / dimensions / api_key / base_url
    - 指向非官方端点（如本地 TEI）时必须设置 check_embedding_ctx_length=False，
      否则会按 token 截断文本，而多数兼容端点不支持该行为

维度必须与 Qdrant Collection 的 size 一致（EMBEDDING_DIM，默认 1536）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings, get_settings
from app.db import redis as redis_db


def build_embeddings(settings: Settings) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
        api_key=settings.resolved_embedding_api_key,
        base_url=settings.resolved_embedding_base_url,
        # 兼容 TEI / vLLM / Ollama 等 OpenAI 兼容端点
        check_embedding_ctx_length=False,
    )


def get_embeddings() -> OpenAIEmbeddings:
    return build_embeddings(get_settings())


def _query_cache_key(text: str, settings: Settings) -> str:
    return redis_db.key_embedding_cache(
        text,
        embedding_model=settings.embedding_model,
        embedding_base_url=settings.resolved_embedding_base_url,
        embedding_dim=settings.embedding_dim,
    )


async def embed_texts(
    texts: Sequence[str],
    settings: Settings | None = None,
    *,
    cache: bool = False,
) -> list[list[float]]:
    """批量向量化：按 embedding_batch_size 分批调用，保持输入顺序。

    cache=True 用于查询向量复用 Redis 缓存；Redis 不可用时直接回落到 Embedding 服务。
    文档切片入库不使用缓存，避免缓存体量膨胀。
    """
    if not texts:
        return []
    s = settings or get_settings()

    cached: dict[int, list[float]] = {}
    pending: list[tuple[int, str]] = list(enumerate(texts))
    if cache:
        try:
            client = redis_db.get_redis()
            remaining: list[tuple[int, str]] = []
            for index, text in pending:
                raw = await client.get(_query_cache_key(text, s))
                if raw:
                    vector = json.loads(raw)
                    if isinstance(vector, list) and vector:
                        cached[index] = [float(value) for value in vector]
                        continue
                remaining.append((index, text))
            pending = remaining
        except Exception:  # noqa: BLE001
            pending = list(enumerate(texts))

    vectors: list[list[float] | None] = [None] * len(texts)
    for index, vector in cached.items():
        vectors[index] = vector

    embeddings = build_embeddings(s)
    for start in range(0, len(pending), s.embedding_batch_size):
        batch = pending[start : start + s.embedding_batch_size]
        computed = await embeddings.aembed_documents([text for _, text in batch])
        for (index, _), vector in zip(batch, computed):
            resolved = [float(value) for value in vector]
            vectors[index] = resolved
            if cache:
                try:
                    await redis_db.get_redis().set(
                        _query_cache_key(texts[index], s),
                        json.dumps(resolved),
                        ex=s.agent_embedding_cache_ttl_seconds,
                    )
                except Exception:  # noqa: BLE001
                    pass

    return [vector for vector in vectors if vector is not None]


__all__ = ["build_embeddings", "embed_texts", "get_embeddings"]
