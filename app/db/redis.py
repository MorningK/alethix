"""Redis 异步客户端。

键设计规范见 prd/04-data-model.md §7：全部键必须设置 TTL。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
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


# ---------------- 任务队列（M1 文档入库） ----------------
def key_ingest_queue() -> str:
    return "queue:ingest"


def key_purge_queue() -> str:
    return "queue:purge"


def key_doc_retry(document_id: str) -> str:
    return f"doc:retry:{document_id}"


async def enqueue_ingest(document_id: str) -> None:
    """投递入库任务（API-2 上传成功后调用）。"""
    await get_redis().rpush(key_ingest_queue(), document_id)


async def enqueue_purge(document_id: str) -> None:
    """投递物理清理任务（API-5 软删成功后调用）。"""
    await get_redis().rpush(key_purge_queue(), document_id)


async def pop_task(queues: Sequence[str], timeout: int = 5) -> tuple[str, str] | None:
    """阻塞弹出任务，返回 (队列名, document_id)；超时返回 None。"""
    result = await get_redis().blpop(list(queues), timeout=timeout)
    if result is None:
        return None
    queue_name, document_id = result
    return queue_name, document_id


async def set_doc_task(document_id: str, payload: dict[str, Any], ttl_seconds: int) -> None:
    """写入任务状态快照（API-3 快路径数据源），统一带 TTL。"""
    await get_redis().set(
        key_doc_task(document_id), json.dumps(payload, ensure_ascii=False), ex=ttl_seconds
    )


async def get_doc_task(document_id: str) -> dict[str, Any] | None:
    """读取任务状态快照；不存在或损坏时返回 None（回退 PostgreSQL）。"""
    raw = await get_redis().get(key_doc_task(document_id))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


async def acquire_doc_lock(document_id: str, ttl_seconds: int = 600) -> bool:
    """获取文档处理幂等锁（prd/04 §7.1 doc:lock:{id}），已被持有返回 False。"""
    return bool(await get_redis().set(key_doc_lock(document_id), "1", nx=True, ex=ttl_seconds))


async def release_doc_lock(document_id: str) -> None:
    await get_redis().delete(key_doc_lock(document_id))


async def next_retry_count(document_id: str, ttl_seconds: int = 86400) -> int:
    """重试计数自增并返回（worker 有限重试）。"""
    client = get_redis()
    count = int(await client.incr(key_doc_retry(document_id)))
    await client.expire(key_doc_retry(document_id), ttl_seconds)
    return count


async def clear_retry_count(document_id: str) -> None:
    await get_redis().delete(key_doc_retry(document_id))
