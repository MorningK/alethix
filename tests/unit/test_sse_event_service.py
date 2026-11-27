"""SSE 事件存储与协议编码测试。"""

from __future__ import annotations

from app.services.sse_event_service import (
    InMemorySSEEventStore,
    ResilientSSEEventStore,
    format_event,
)


async def test_memory_store_assigns_monotonic_ids_and_replays_after_cursor():
    store = InMemorySSEEventStore(max_events=100)
    first = await store.append("run-1", "started", {"question": "风险？"})
    second = await store.append("run-1", "iteration", {"iteration": 1})

    assert first["id"] == 1
    assert second["id"] == 2
    assert [item["event"] for item in await store.after("run-1", 0)] == ["started", "iteration"]
    assert [item["event"] for item in await store.after("run-1", 1)] == ["iteration"]


async def test_memory_store_trims_to_last_100_events():
    store = InMemorySSEEventStore(max_events=100)
    for index in range(105):
        await store.append("run-1", "iteration", {"iteration": index})

    records = await store.after("run-1", 0)
    assert len(records) == 100
    assert records[0]["data"]["iteration"] == 5
    assert records[-1]["id"] == 105


async def test_memory_store_clear_removes_all_events():
    store = InMemorySSEEventStore()
    await store.append("run-1", "started", {})
    await store.clear("run-1")
    assert await store.after("run-1", 0) == []


async def test_memory_store_expires_after_ttl():
    store = InMemorySSEEventStore(max_events=100, ttl_seconds=0)
    await store.append("run-1", "started", {})
    assert await store.after("run-1", 0) == []
    assert "run-1" not in store._events
    assert "run-1" not in store._sequence


class BrokenStore:
    async def append(self, agent_run_id, event, data):
        raise RuntimeError("redis down")

    async def after(self, agent_run_id, event_id):
        raise RuntimeError("redis down")

    async def clear(self, agent_run_id):
        raise RuntimeError("redis down")


async def test_resilient_store_falls_back_on_redis_failure():
    store = ResilientSSEEventStore(
        primary=BrokenStore(), fallback=InMemorySSEEventStore(max_events=100)
    )

    record = await store.append("run-1", "started", {})
    assert record["id"] == 1
    assert store.degraded is True
    assert [item["event"] for item in await store.after("run-1", 0)] == ["started"]

    await store.clear("run-1")
    assert await store.after("run-1", 0) == []


def test_format_event_follows_sse_wire_format():
    text = format_event({"id": 7, "event": "final_answer", "data": {"answer": "结论"}})
    assert text.startswith("id: 7\nevent: final_answer\ndata: ")
    assert text.endswith("\n\n")
    assert "结论" in text
