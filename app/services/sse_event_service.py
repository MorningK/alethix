"""SSE 事件存储与序列化。

事件按 agent_run_id 独立编号，最多保留最近 100 条并带 TTL（AG-5.2 / SSE-1）。
Redis 不可用时回落到进程内存，保证测试与单机降级场景可用。
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, safe_extra
from app.db import redis as redis_db

logger = get_logger(__name__)

EventRecord = dict[str, Any]


class SSEEventStore(Protocol):
    """事件存储协议。"""

    async def append(self, agent_run_id: str, event: str, data: dict[str, Any]) -> EventRecord: ...

    async def after(self, agent_run_id: str, event_id: int) -> list[EventRecord]: ...

    async def clear(self, agent_run_id: str) -> None: ...

    async def mark_terminal(self, agent_run_id: str) -> None: ...

    async def is_terminal(self, agent_run_id: str) -> bool: ...


class InMemorySSEEventStore:
    """测试环境使用的内存事件存储。"""

    def __init__(self, max_events: int = 100, ttl_seconds: int = 3600) -> None:
        self._max_events = max_events
        self._ttl = ttl_seconds
        self._events: dict[str, list[EventRecord]] = {}
        self._sequence: dict[str, int] = {}
        self._expires: dict[str, float] = {}
        self._terminals: dict[str, float] = {}

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [run_id for run_id, deadline in self._expires.items() if deadline <= now]
        for run_id in expired:
            self._events.pop(run_id, None)
            self._sequence.pop(run_id, None)
            self._expires.pop(run_id, None)

    async def append(self, agent_run_id: str, event: str, data: dict[str, Any]) -> EventRecord:
        self._purge_expired()
        events = self._events.setdefault(agent_run_id, [])
        event_id = self._sequence.get(agent_run_id, 0) + 1
        self._sequence[agent_run_id] = event_id
        self._expires[agent_run_id] = time.monotonic() + self._ttl
        record: EventRecord = {
            "id": event_id,
            "event": event,
            "data": dict(data),
        }
        events.append(record)
        del events[: -self._max_events]
        return dict(record)

    async def after(self, agent_run_id: str, event_id: int) -> list[EventRecord]:
        self._purge_expired()
        return [dict(item) for item in self._events.get(agent_run_id, []) if item["id"] > event_id]

    async def clear(self, agent_run_id: str) -> None:
        self._events.pop(agent_run_id, None)
        self._sequence.pop(agent_run_id, None)
        self._expires.pop(agent_run_id, None)
        self._terminals.pop(agent_run_id, None)

    async def mark_terminal(self, agent_run_id: str) -> None:
        self._terminals[agent_run_id] = time.monotonic() + self._ttl

    async def is_terminal(self, agent_run_id: str) -> bool:
        deadline = self._terminals.get(agent_run_id)
        if deadline is None:
            return False
        if deadline <= time.monotonic():
            self._terminals.pop(agent_run_id, None)
            return False
        return True

    def set_sequence(self, agent_run_id: str, sequence: int) -> None:
        """接力主存储的事件编号，避免降级后编号重复。"""
        self._sequence[agent_run_id] = max(self._sequence.get(agent_run_id, 0), sequence)


class RedisSSEEventStore:
    """多 worker 场景下的可重放事件存储。"""

    def __init__(self, *, ttl_seconds: int, max_events: int) -> None:
        self._ttl = ttl_seconds
        self._max_events = max_events

    async def append(self, agent_run_id: str, event: str, data: dict[str, Any]) -> EventRecord:
        client = redis_db.get_redis()
        seq_key = redis_db.key_sse_events_seq(agent_run_id)
        list_key = redis_db.key_sse_events(agent_run_id)
        async with client.pipeline(transaction=True) as pipe:
            await pipe.incr(seq_key)
            await pipe.expire(seq_key, self._ttl)
            seq = (await pipe.execute())[0]
        record: EventRecord = {"id": int(seq), "event": event, "data": dict(data)}
        async with client.pipeline(transaction=True) as pipe:
            await pipe.rpush(list_key, json.dumps(record, ensure_ascii=False))
            await pipe.ltrim(list_key, -self._max_events, -1)
            await pipe.expire(list_key, self._ttl)
            await pipe.execute()
        return record

    async def after(self, agent_run_id: str, event_id: int) -> list[EventRecord]:
        raw_events: Sequence[str | bytes] = await redis_db.get_redis().lrange(
            redis_db.key_sse_events(agent_run_id), 0, -1
        )
        result: list[EventRecord] = []
        for raw in raw_events:
            try:
                record = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(record, dict) and int(record.get("id", 0)) > event_id:
                result.append(record)
        return result

    async def clear(self, agent_run_id: str) -> None:
        await redis_db.get_redis().delete(
            redis_db.key_sse_events(agent_run_id),
            redis_db.key_sse_events_seq(agent_run_id),
            redis_db.key_sse_terminal(agent_run_id),
        )

    async def mark_terminal(self, agent_run_id: str) -> None:
        await redis_db.get_redis().set(redis_db.key_sse_terminal(agent_run_id), "1", ex=self._ttl)

    async def is_terminal(self, agent_run_id: str) -> bool:
        return bool(await redis_db.get_redis().exists(redis_db.key_sse_terminal(agent_run_id)))


class ResilientSSEEventStore:
    """Redis 故障时回退到进程内存；降级期间跨 worker 重放不可用。"""

    def __init__(
        self,
        *,
        primary: SSEEventStore,
        fallback: SSEEventStore,
        ttl_seconds: int = 3600,
        max_sequences: int = 100,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._degraded = False
        self._primary_sequences: dict[str, int] = {}
        self._sequence_expires: dict[str, float] = {}
        self._sequence_ttl = ttl_seconds
        self._max_sequences = max_sequences

    @property
    def degraded(self) -> bool:
        return self._degraded

    def _degrade(self, operation: str, exc: Exception) -> None:
        if not self._degraded:
            logger.warning(
                "SSE 事件存储降级到进程内存",
                extra=safe_extra(operation=operation, reason=type(exc).__name__),
            )
        self._degraded = True

    def _prune_sequences(self) -> None:
        now = time.monotonic()
        expired = [run_id for run_id, deadline in self._sequence_expires.items() if deadline <= now]
        for run_id in expired:
            self._primary_sequences.pop(run_id, None)
            self._sequence_expires.pop(run_id, None)
        while len(self._primary_sequences) > self._max_sequences:
            oldest = next(iter(self._primary_sequences))
            self._primary_sequences.pop(oldest, None)
            self._sequence_expires.pop(oldest, None)

    def _record_primary_sequence(self, agent_run_id: str, sequence: int) -> None:
        self._prune_sequences()
        self._primary_sequences[agent_run_id] = max(
            self._primary_sequences.get(agent_run_id, 0), sequence
        )
        self._sequence_expires[agent_run_id] = time.monotonic() + self._sequence_ttl
        self._prune_sequences()

    async def append(self, agent_run_id: str, event: str, data: dict[str, Any]) -> EventRecord:
        if not self._degraded:
            try:
                record = await self._primary.append(agent_run_id, event, data)
                self._record_primary_sequence(agent_run_id, int(record["id"]))
                return record
            except Exception as exc:  # noqa: BLE001
                self._degrade("append", exc)
        self._prune_sequences()
        set_sequence = getattr(self._fallback, "set_sequence", None)
        if callable(set_sequence):
            set_sequence(agent_run_id, self._primary_sequences.get(agent_run_id, 0))
        return await self._fallback.append(agent_run_id, event, data)

    async def after(self, agent_run_id: str, event_id: int) -> list[EventRecord]:
        if not self._degraded:
            try:
                return await self._primary.after(agent_run_id, event_id)
            except Exception as exc:  # noqa: BLE001
                self._degrade("after", exc)
        return await self._fallback.after(agent_run_id, event_id)

    async def clear(self, agent_run_id: str) -> None:
        self._primary_sequences.pop(agent_run_id, None)
        self._sequence_expires.pop(agent_run_id, None)
        if not self._degraded:
            try:
                await self._primary.clear(agent_run_id)
                return
            except Exception as exc:  # noqa: BLE001
                self._degrade("clear", exc)
        await self._fallback.clear(agent_run_id)

    async def mark_terminal(self, agent_run_id: str) -> None:
        if not self._degraded:
            try:
                await self._primary.mark_terminal(agent_run_id)
                return
            except Exception as exc:  # noqa: BLE001
                self._degrade("mark_terminal", exc)
        await self._fallback.mark_terminal(agent_run_id)

    async def is_terminal(self, agent_run_id: str) -> bool:
        if not self._degraded:
            try:
                return await self._primary.is_terminal(agent_run_id)
            except Exception as exc:  # noqa: BLE001
                self._degrade("is_terminal", exc)
        return await self._fallback.is_terminal(agent_run_id)


_store: SSEEventStore | None = None


def get_event_store(settings: Settings | None = None) -> SSEEventStore:
    """获取事件存储单例；测试环境或 Redis 未初始化时使用内存实现。"""
    global _store
    if _store is not None:
        return _store
    s = settings or get_settings()
    if s.app_env == "test" or not redis_db.client_state()["initialized"]:
        _store = InMemorySSEEventStore(
            max_events=s.sse_max_events, ttl_seconds=s.sse_event_ttl_seconds
        )
    else:
        _store = ResilientSSEEventStore(
            primary=RedisSSEEventStore(
                ttl_seconds=s.sse_event_ttl_seconds, max_events=s.sse_max_events
            ),
            fallback=InMemorySSEEventStore(
                max_events=s.sse_max_events, ttl_seconds=s.sse_event_ttl_seconds
            ),
            ttl_seconds=s.sse_event_ttl_seconds,
            max_sequences=s.sse_max_events,
        )
    return _store


def set_event_store(store: SSEEventStore | None) -> None:
    """供测试注入事件存储。"""
    global _store
    _store = store


def format_event(record: EventRecord) -> str:
    """按 SSE 协议编码单条事件。"""
    data = json.dumps(record["data"], ensure_ascii=False, separators=(",", ":"))
    return f"id: {record['id']}\nevent: {record['event']}\ndata: {data}\n\n"


__all__ = [
    "EventRecord",
    "InMemorySSEEventStore",
    "RedisSSEEventStore",
    "ResilientSSEEventStore",
    "SSEEventStore",
    "format_event",
    "get_event_store",
    "set_event_store",
]
