"""会话服务参数校验单测。"""

from __future__ import annotations

import pytest

from app.core.errors import ERR_SESSION_PARAM, ApiError
from app.schemas.session import SessionCreateRequest
from app.services import session_service

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
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
