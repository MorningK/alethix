"""会话服务参数校验单测。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.errors import ERR_SESSION_NOT_FOUND, ERR_SESSION_PARAM, ApiError
from app.models.agent import Answer
from app.models.agent import Citation as CitationORM
from app.models.session import Message
from app.schemas.session import SessionCreateRequest
from app.services import session_service

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"
DOC_ID = "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"


class DummySession:
    async def execute(self, stmt, params=None):
        return None

    async def commit(self) -> None:
        return None


async def test_title_with_nul_is_rejected():
    payload = SessionCreateRequest(title="报告\x00说明", default_document_ids=[])
    with pytest.raises(ApiError) as exc:
        await session_service.create_session(payload=payload, user_id=USER_ID, db=DummySession())
    assert exc.value.code == ERR_SESSION_PARAM
    assert exc.value.status == 400


def test_equivalent_uuid_spellings_are_deduplicated():
    variants = [
        DOC_ID,
        DOC_ID.upper(),
        f"{{{DOC_ID}}}",
    ]
    assert session_service._normalize_document_ids(variants) == [DOC_ID]


def test_21st_distinct_document_is_rejected_immediately():
    document_ids = [f"00000000-0000-4000-8000-{index:012d}" for index in range(21)]
    with pytest.raises(ApiError) as exc:
        session_service._normalize_document_ids(document_ids)
    assert exc.value.code == ERR_SESSION_PARAM
    assert "20" in exc.value.message


class FakeDb:
    """按查询顺序返回归属、总数、消息、答案与引用结果。"""

    def __init__(self, results: list[SimpleNamespace]) -> None:
        self.results = list(results)
        self.index = 0

    async def execute(self, stmt, params=None):
        result = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return result


def _result(*, rows=None, scalar=None, count=None):
    return SimpleNamespace(
        scalar_one_or_none=lambda: scalar,
        scalar_one=lambda: count,
        scalars=lambda: SimpleNamespace(all=lambda: rows or []),
    )


async def test_list_messages_assembles_citations_in_order():
    run_id = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"
    answer_id = "b1e2d3c4-5f6a-7b8c-9d0e-1f2a3b4c5d6e"
    message = Message(
        id=9,
        session_id=SESSION_ID,
        role="assistant",
        content="根据文档，主要风险包括数据合规风险。",
        agent_run_id=run_id,
        seq=2,
        created_at=datetime(2026, 9, 4, 10, 5, tzinfo=UTC),
    )
    answer = Answer(
        id=answer_id,
        agent_run_id=run_id,
        session_id=SESSION_ID,
        content=message.content,
        confidence="medium",
        stop_reason="sufficient",
    )
    citation = CitationORM(
        id=1,
        answer_id=answer_id,
        agent_run_id=run_id,
        document_id=DOC_ID,
        chunk_id="3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
        filename="报告.pdf",
        page=3,
        section="风险分析",
        quote="数据合规风险",
        ordinal=1,
    )
    db = FakeDb(
        [
            _result(scalar=SESSION_ID),
            _result(count=2),
            _result(rows=[message]),
            _result(rows=[answer]),
            _result(rows=[citation]),
        ]
    )

    page = await session_service.list_messages(
        session_id=SESSION_ID, user_id=USER_ID, db=db, page=1, page_size=20
    )
    assert page.total == 2
    assert page.items[0].message_id == "9"
    assert page.items[0].confidence == "medium"
    assert page.items[0].citations[0].quote == "数据合规风险"


async def test_list_messages_rejects_unowned_session():
    db = FakeDb([_result(scalar=None)])

    with pytest.raises(ApiError) as exc:
        await session_service.list_messages(session_id=SESSION_ID, user_id=USER_ID, db=db)
    assert exc.value.code == ERR_SESSION_NOT_FOUND
    assert exc.value.status == 404
