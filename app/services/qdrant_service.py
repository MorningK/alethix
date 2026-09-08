"""Qdrant 向量库服务。

Collection 定义见 prd/04-data-model.md §4.1：
    - 名称：document_chunks（可通过 QDRANT_COLLECTION 覆盖）
    - 命名向量 dense，size = EMBEDDING_DIM（默认 1536），距离 COSINE
    - HNSW: m=16, ef_construct=100
    - payload 索引：user_id / doc_id / chunk_index（§4.4）

Filter 构造规范见 prd/04-data-model.md §4.3：user_id 必须无条件附加。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    Range,
    VectorParams,
)

from app.core.config import Settings

_client: QdrantClient | None = None

# 需要建立 payload 索引的字段（prd/04-data-model.md §4.4）
_INDEXED_PAYLOAD_FIELDS: dict[str, PayloadSchemaType] = {
    "user_id": PayloadSchemaType.KEYWORD,
    "doc_id": PayloadSchemaType.KEYWORD,
    "chunk_index": PayloadSchemaType.INTEGER,
}


def init_qdrant(settings: Settings) -> None:
    """创建 Qdrant 客户端。在应用启动时调用一次。"""
    global _client
    _client = QdrantClient(
        url=settings.qdrant_url,
        # 空字符串需归一为 None，否则客户端会认为启用了 api key 而发出不安全连接告警
        api_key=settings.qdrant_api_key or None,
        timeout=10,
    )


def close_qdrant() -> None:
    """关闭客户端。"""
    global _client
    if _client is not None:
        _client.close()
    _client = None


def get_qdrant() -> QdrantClient:
    if _client is None:
        raise RuntimeError("Qdrant 未初始化，请先调用 init_qdrant()")
    return _client


def ensure_collection(settings: Settings) -> bool:
    """确保 Collection 与 payload 索引存在。

    幂等：已存在时只补建索引，不重建向量数据。
    返回 True 表示新建，False 表示已存在。
    """
    client = get_qdrant()
    name = settings.qdrant_collection
    exists = client.collection_exists(name)

    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": VectorParams(
                    size=settings.embedding_dim,
                    distance=Distance.COSINE,
                )
            },
            hnsw_config=HnswConfigDiff(
                m=16,
                ef_construct=100,
                full_scan_threshold=10000,
            ),
        )

    for field, schema in _INDEXED_PAYLOAD_FIELDS.items():
        client.create_payload_index(
            collection_name=name,
            field_name=field,
            field_schema=schema,
        )

    return not exists


def check_qdrant() -> bool:
    """连通性探测，用于健康检查。"""
    if _client is None:
        return False
    try:
        _client.get_collections()
        return True
    except Exception:
        return False


def build_filter(user_id: str, document_ids: Sequence[str] | None = None) -> Filter:
    """构造检索过滤条件。

    user_id 无条件附加（QF-1）；单文档用 MatchValue，多文档用 MatchAny（QF-2）。
    """
    must: list[FieldCondition] = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]

    if document_ids:
        if len(document_ids) == 1:
            must.append(FieldCondition(key="doc_id", match=MatchValue(value=document_ids[0])))
        else:
            must.append(FieldCondition(key="doc_id", match=MatchAny(any=list(document_ids))))

    return Filter(must=must)


def build_neighbor_filter(user_id: str, doc_id: str, chunk_index: int, span: int = 1) -> Filter:
    """相邻切片召回（AG-1.8）。"""
    return Filter(
        must=[
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
            FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
            FieldCondition(
                key="chunk_index",
                range=Range(gte=chunk_index - span, lte=chunk_index + span),
            ),
        ]
    )


def collection_info(settings: Settings) -> dict[str, Any]:
    """Collection 状态快照。"""
    if _client is None:
        return {"initialized": False}
    try:
        info = _client.get_collection(settings.qdrant_collection)
        return {
            "initialized": True,
            "collection": settings.qdrant_collection,
            "points_count": info.points_count,
            "vector_size": settings.embedding_dim,
        }
    except Exception as exc:  # noqa: BLE001
        return {"initialized": True, "error": str(exc)}
