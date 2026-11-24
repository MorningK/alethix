"""答案生成与引用校验单测。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.errors import ERR_LLM_UNAVAILABLE, ApiError
from app.schemas.answer import GeneratedAnswer
from app.services import answer_service, citation_service, llm_service
from app.services.retrieval_service import RetrievedChunk

DOC_ID = "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
CHUNK_ID = "b1e2d3c4-5f6a-7b8c-9d0e-1f2a3b4c5d6e"


def _settings() -> Settings:
    return Settings(
        agent_score_threshold=0.35,
        agent_max_evidence_per_round=2,
        agent_max_chunk_chars=20,
        llm_max_tokens=2000,
    )


def _hit(score: float = 0.8, content: str = "数据合规风险需要重点关注。") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=CHUNK_ID,
        document_id=DOC_ID,
        content=content,
        score=score,
        page=5,
        section="3.2 风险分析",
        title="AI 行业报告",
    )


def test_build_context_limits_evidence_and_chars():
    context = answer_service.build_context(
        [_hit(content="0123456789abcdefghijklmnopqrstuvwxyz"), _hit(), _hit()],
        _settings(),
    )
    assert context.count("chunk_id=") == 2
    assert "0123456789abcdefghij" in context
    assert "klmnopqrstuvwxyz" not in context


async def test_low_relevance_skips_llm(monkeypatch):
    def _unexpected(*args, **kwargs):
        raise AssertionError("低相关度时不应调用 LLM")

    monkeypatch.setattr(answer_service, "build_llm", _unexpected)
    result = await answer_service.generate_answer("风险？", [_hit(score=0.1)], _settings())
    assert result.answer == answer_service.LOW_RELEVANCE_ANSWER
    assert result.confidence == "low"
    assert result.used_chunk_ids == []


async def test_generate_answer_returns_structured_result(monkeypatch):
    class FakeChain:
        async def ainvoke(self, messages):
            assert messages[0][0] == "system"
            assert "<context>" in messages[1][1]
            return GeneratedAnswer(
                answer="主要风险是数据合规风险。",
                confidence="high",
                findings=["第 5 页提到数据合规风险"],
                used_chunk_ids=[CHUNK_ID],
                reason="证据充分",
            )

    monkeypatch.setattr(answer_service, "build_llm", lambda *a, **k: FakeChain())
    result = await answer_service.generate_answer("风险？", [_hit()], _settings())
    assert result.confidence == "high"
    assert result.used_chunk_ids == [CHUNK_ID]


async def test_generate_answer_maps_llm_failure_after_retry(monkeypatch):
    calls: list = []

    class FailingChain:
        async def ainvoke(self, messages):
            calls.append(messages)
            raise RuntimeError("llm down")

    monkeypatch.setattr(answer_service, "build_llm", lambda *a, **k: FailingChain())
    with pytest.raises(ApiError) as exc:
        await answer_service.generate_answer("风险？", [_hit()], _settings())
    assert exc.value.code == ERR_LLM_UNAVAILABLE
    assert exc.value.status == 503
    assert len(calls) == 2


def test_citations_filter_hallucinated_chunk_ids_and_trim_quote():
    long_content = "证" * 400
    hits = [_hit(content=long_content)]
    citations, filtered = citation_service.build_citations(
        hits,
        {DOC_ID: "2026_ai_report.pdf"},
        [CHUNK_ID, "ffffffff-ffff-ffff-ffff-ffffffffffff"],
        settings=Settings(agent_max_chunk_chars=1500),
    )
    assert filtered == 1
    assert len(citations) == 1
    assert citations[0].chunk_id == CHUNK_ID
    assert citations[0].filename == "2026_ai_report.pdf"
    assert len(citations[0].quote) == 301
    assert citations[0].quote.endswith("…")


def test_citations_without_declared_ids_use_all_hits():
    citations, filtered = citation_service.build_citations(
        [_hit()], {DOC_ID: "报告.md"}, None, settings=_settings()
    )
    assert filtered == 0
    assert len(citations) == 1


def test_build_llm_uses_json_mode_and_max_tokens(monkeypatch):
    captured: dict = {}

    class FakeChat:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def with_structured_output(self, schema, *, method=None):
            captured["structured"] = (schema, method)
            return "chain"

    monkeypatch.setattr(llm_service, "ChatOpenAI", FakeChat)
    result = llm_service.build_llm(_settings(), structured=GeneratedAnswer)

    assert result == "chain"
    assert captured["init"]["max_tokens"] == 2000
    assert captured["structured"][1] == "json_mode"


async def test_generate_answer_normalizes_numeric_confidence(monkeypatch):
    class FakeChain:
        async def ainvoke(self, messages):
            return SimpleNamespace(
                answer="主要风险是数据合规风险。",
                confidence=0.95,
                findings=["第 5 页提到数据合规风险"],
                used_chunk_ids=[CHUNK_ID],
                reason="证据充分",
                conflicts=[],
            )

    monkeypatch.setattr(answer_service, "build_llm", lambda *a, **k: FakeChain())
    result = await answer_service.generate_answer("风险？", [_hit()], _settings())
    assert result.confidence == "high"


async def test_generate_answer_retries_empty_payload(monkeypatch):
    calls: list = []

    class RetryChain:
        async def ainvoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                return SimpleNamespace(
                    answer="",
                    confidence="high",
                    findings=[],
                    used_chunk_ids=[],
                    reason="",
                    conflicts=[],
                )
            return SimpleNamespace(
                answer="证据显示存在数据合规风险。",
                confidence="medium",
                findings=["第 5 页有相关描述"],
                used_chunk_ids=[CHUNK_ID],
                reason="证据充分",
                conflicts=[],
            )

    monkeypatch.setattr(answer_service, "build_llm", lambda *a, **k: RetryChain())
    result = await answer_service.generate_answer("风险？", [_hit()], _settings())

    assert len(calls) == 2
    assert answer_service._RETRY_HINT in calls[1][0][1]
    assert result.answer == "证据显示存在数据合规风险。"
    assert result.confidence == "medium"
