"""Redis 异步客户端。

键设计规范见 prd/04-data-model.md §7：全部键必须设置 TTL。
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

_client: Redis | None = None


def init_redis(url: str) -> None:
    """创建 Redis 客户端。在应用启动时调用一次。"""
    global _client
    _client = Redis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


async def close_redis() -> None:
    """关闭客户端。在应用关闭时调用。"""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def get_redis() -> Redis:
    """获取 Redis 客户端。"""
    if _client is None:
        raise RuntimeError("Redis 未初始化，请先调用 init_redis()")
    return _client


async def check_redis() -> bool:
    """连通性探测，用于健康检查。"""
    if _client is None:
        return False
    try:
        await _client.ping()
        return True
    except Exception:
        return False


def client_state() -> dict[str, Any]:
    """客户端状态快照。"""
    if _client is None:
        return {"initialized": False}
    return {"initialized": True}


# ---------------- 常用键构造（prd/04-data-model.md §7.1） ----------------
def key_doc_task(document_id: str) -> str:
    return f"doc:task:{document_id}"


def key_doc_lock(document_id: str) -> str:
    return f"doc:lock:{document_id}"


def key_embedding_cache(query: str) -> str:
    import hashlib

    return f"emb:q:{hashlib.sha256(query.encode('utf-8')).hexdigest()}"


def key_rate_limit(scope: str, user_id: str, minute: int) -> str:
    return f"rate:{scope}:{user_id}:{minute}"


def key_session_lock(session_id: str) -> str:
    return f"sess:lock:{session_id}"


def key_sse_events(agent_run_id: str) -> str:
    return f"ask:events:{agent_run_id}"
