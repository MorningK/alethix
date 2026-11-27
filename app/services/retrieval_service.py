"""检索服务。

职责：查询向量化 → Qdrant 单次检索 → 命中结果归一化。

约束见 prd/03-agent-design.md §6.1 / §6.2：
    - user_id 过滤必须无条件附加（AG-1.2）
    - 检索与入库使用同一 Embedding 模型（避免维度/语义不一致）
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.errors import ERR_LLM_UNAVAILABLE, ERR_VECTORDB_UNAVAILABLE, ApiError
from app.core.logging import get_logger, safe_extra
from app.db import redis as redis_db
from app.services import qdrant_service
from app.services.embedding_service import embed_texts

logger = get_logger(__name__)


def _query_cache_key(query: str, settings: Settings) -> str:
    return redis_db.key_embedding_cache(
        query,
        embedding_model=settings.embedding_model,
        embedding_base_url=settings.resolved_embedding_base_url,
        embedding_dim=settings.embedding_dim,
    )


@dataclass(frozen=True)
class RetrievedChunk:
    """归一化后的检索命中，供答案生成与引用构造复用。"""

    chunk_id: str
    document_id: str
    content: str
    score: float
    chunk_index: int | None = None
    page: int | None = None
    section: str | None = None
    title: str | None = None


async def search(
    *,
    query: str,
    user_id: str,
    document_ids: list[str] | None = None,
    top_k: int = 10,
    score_threshold: float | None = None,
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    """执行单次检索；返回按分数降序排列的命中切片。"""
    s = settings or get_settings()
    query_filter = qdrant_service.build_filter(user_id, document_ids)

    try:
        cached = None
        try:
            raw = await redis_db.get_redis().get(_query_cache_key(query, s))
            if raw:
                candidate = json.loads(raw)
                if isinstance(candidate, list) and candidate:
                    cached = [float(value) for value in candidate]
        except Exception:  # noqa: BLE001
            cached = None

        if cached is not None:
            vectors = [cached]
        else:
            vectors = await embed_texts([query], s)
            if vectors:
                try:
                    await redis_db.get_redis().set(
                        _query_cache_key(query, s),
                        json.dumps(vectors[0]),
                        ex=s.agent_embedding_cache_ttl_seconds,
                    )
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询向量化失败", extra=safe_extra(reason=type(exc).__name__))
        raise ApiError(
            ERR_LLM_UNAVAILABLE,
            "Embedding 服务不可用，请稍后重试",
            status=503,
            details={"stage": "embedding"},
        ) from exc

    if not vectors:
        return []

    try:
        points = await asyncio.to_thread(
            qdrant_service.query_points,
            s,
            vectors[0],
            query_filter,
            limit=top_k,
            score_threshold=score_threshold,
        )
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant 检索失败", extra=safe_extra(reason=type(exc).__name__))
        raise ApiError(
            ERR_VECTORDB_UNAVAILABLE,
            "向量检索服务不可用，请稍后重试",
            status=503,
            details={"stage": "retrieval"},
        ) from exc

    hits: list[RetrievedChunk] = []
    for point in points:
        payload = point.payload or {}
        chunk_id = str(point.id)
        document_id = str(payload.get("doc_id") or "")
        content = str(payload.get("content") or "")
        if not document_id or not content:
            continue
        hits.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                content=content,
                score=float(point.score),
                chunk_index=payload.get("chunk_index"),
                page=payload.get("page"),
                section=payload.get("section"),
                title=payload.get("title"),
            )
        )
    return hits


__all__ = ["RetrievedChunk", "search"]
