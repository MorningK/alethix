"""Embedding 服务（占位）。

必须独立构造客户端，使用 resolved_embedding_*（AG-7.1）。
OpenAIEmbeddings 关键参数（已核对 langchain-openai 文档）：
    model / dimensions / api_key / base_url
    - 指向非官方端点（如本地 TEI）时必须设置 check_embedding_ctx_length=False，
      否则会按 token 截断文本，而多数兼容端点不支持该行为

维度必须与 Qdrant Collection 的 size 一致（EMBEDDING_DIM，默认 1536）。

实现阶段：M1。
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings, get_settings


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


async def embed_texts(texts: Sequence[str], settings: Settings | None = None) -> list[list[float]]:
    """批量向量化：按 embedding_batch_size 分批调用，保持输入顺序。"""
    if not texts:
        return []
    s = settings or get_settings()
    embeddings = build_embeddings(s)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), s.embedding_batch_size):
        batch = list(texts[start : start + s.embedding_batch_size])
        vectors.extend(await embeddings.aembed_documents(batch))
    return vectors


__all__ = ["build_embeddings", "embed_texts", "get_embeddings"]
