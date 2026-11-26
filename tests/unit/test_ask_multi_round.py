"""同步问答入口的多轮编排与持久化契约测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.state import IterationRecord as StateIteration
from app.core.config import Settings
from app.core.errors import ERR_SESSION_BUSY, ApiError
from app.db import redis as redis_db
from app.schemas.ask import AskRequest
from app.schemas.document import Citation
from app.services import agent_service, ask_service
from app.services.agent_service import ResearchResult

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"
RUN_ID = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"


class DummyDb:
    async def execute(self, stmt, params=None):
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    def add_all(self, rows) -> None:
        return None


def _research(**overrides) -> ResearchResult:
    base = dict(
        agent_run_id=RUN_ID,
        state={"max_score": 0.8},
        answer="多轮调研答案 [chunk-1]",
        confidence="high",
        stop_reason="sufficient",
        iterations=[
            StateIteration(
                iteration=1,
                queries=["风险"],
                retrieved_chunk_count=2,
                new_chunk_count=2,
                findings=["发现"],
                conflicts=[],
                decision="answer",
                reason="证据充分",
                max_score=0.8,
                missing_information=None,
            )
        ],
        citations=[
            Citation(
                document_id="doc-1",
                chunk_id="chunk-1",
                filename="报告.pdf",
                quote="原文",
                score=0.8,
            )
        ],
        token_used=12,
        prompt_tokens=6,
        completion_tokens=6,
        llm_call_count=4,
        fallback_count=1,
        citation_filtered_count=0,
        duration_ms=100,
    )
    base.update(overrides)
    return ResearchResult(**base)


@pytest.fixture
def patched(monkeypatch):
    async def _scope(*, payload, user_id, db):
        return (
            SimpleNamespace(id=SESSION_ID, default_document_ids=[]),
            ["doc-1"],
            {"doc-1": "报告.pdf"},
        )

    async def _lock(*args, **kwargs):
        return "owner-token"

    released: list[tuple] = []

    async def _unlock(*args, **kwargs):
        released.append(args)
        return None

    async def _persist(**kwargs):
        return RUN_ID

    monkeypatch.setattr(ask_service, "_resolve_scope", _scope)
    monkeypatch.setattr(redis_db, "acquire_session_lock", _lock)
    monkeypatch.setattr(redis_db, "release_session_lock", _unlock)
    monkeypatch.setattr(ask_service, "_persist", _persist)
    return monkeypatch


async def test_run_single_ask_returns_multi_round_result(patched):
    calls: dict = {}

    async def _research_stub(**kwargs):
        calls.update(kwargs)
        return _research()

    patched.setattr(agent_service, "run_research", _research_stub)

    response = await ask_service.run_single_ask(
        payload=AskRequest(session_id=SESSION_ID, question="风险？", document_ids=[]),
        user_id=USER_ID,
        db=DummyDb(),
    )

    assert response.iteration_count == 1
    assert response.stop_reason == "sufficient"
    assert response.answer == "多轮调研答案 [chunk-1]"
    assert response.token_used == 12
    assert response.citations[0].chunk_id == "chunk-1"
    assert calls["max_iterations"] == 3


async def test_session_busy_returns_conflict(patched):
    async def _busy(*args, **kwargs):
        return None

    patched.setattr(redis_db, "acquire_session_lock", _busy)
    with pytest.raises(ApiError) as exc:
        await ask_service.run_single_ask(
            payload=AskRequest(session_id=SESSION_ID, question="风险？", document_ids=[]),
            user_id=USER_ID,
            db=DummyDb(),
        )
    assert exc.value.code == ERR_SESSION_BUSY
    assert exc.value.status == 409


async def test_session_lock_released_with_owner_token(monkeypatch):
    async def _scope(*, payload, user_id, db):
        return SimpleNamespace(id=SESSION_ID, default_document_ids=[]), [], {}

    async def _acquire(*args, **kwargs):
        return "owner-token-123"

    released: dict = {}

    async def _release(session_id, token):
        released.update(session_id=session_id, token=token)

    async def _persist(**kwargs):
        return RUN_ID

    monkeypatch.setattr(ask_service, "_resolve_scope", _scope)
    monkeypatch.setattr(redis_db, "acquire_session_lock", _acquire)
    monkeypatch.setattr(redis_db, "release_session_lock", _release)
    monkeypatch.setattr(ask_service, "_persist", _persist)

    await ask_service.run_single_ask(
        payload=AskRequest(session_id=SESSION_ID, question="风险？", document_ids=[]),
        user_id=USER_ID,
        db=DummyDb(),
    )

    assert released == {"session_id": SESSION_ID, "token": "owner-token-123"}


async def test_session_lock_ttl_is_clamped_to_run_duration(monkeypatch):
    captured: dict = {}

    async def _scope(*, payload, user_id, db):
        return SimpleNamespace(id=SESSION_ID, default_document_ids=[]), [], {}

    async def _acquire(session_id, ttl):
        captured["ttl"] = ttl
        return "owner-token"

    async def _release(session_id, token):
        return None

    async def _persist(**kwargs):
        return RUN_ID

    monkeypatch.setattr(ask_service, "_resolve_scope", _scope)
    monkeypatch.setattr(redis_db, "acquire_session_lock", _acquire)
    monkeypatch.setattr(redis_db, "release_session_lock", _release)
    monkeypatch.setattr(ask_service, "_persist", _persist)

    settings = Settings(
        _env_file=None,
        agent_timeout_seconds=120,
        agent_session_lock_ttl_seconds=10,
    )
    await ask_service.run_single_ask(
        payload=AskRequest(session_id=SESSION_ID, question="风险？", document_ids=[]),
        user_id=USER_ID,
        db=DummyDb(),
        settings=settings,
    )

    assert captured["ttl"] >= 150
