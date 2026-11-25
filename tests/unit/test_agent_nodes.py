"""LangGraph 节点契约测试（Fake LLM / Fake Retriever）。"""

from __future__ import annotations

from time import monotonic
from types import SimpleNamespace

from app.agents import nodes, runtime
from app.agents.schemas import (
    AnalyzeEvidenceOutput,
    FinalAnswerOutput,
    PlanQueriesOutput,
    SufficiencyDecision,
)
from app.agents.state import RetrievedChunk
from app.core.config import Settings
from app.services import citation_service
from app.services.retrieval_service import RetrievedChunk as ServiceHit

USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"
RUN_ID = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _result(payload, *, tokens: int = 8, fallback: int = 0):
    return SimpleNamespace(
        payload=payload,
        token_used=tokens,
        fallback_count=fallback,
        prompt_tokens=tokens // 2,
        completion_tokens=tokens - tokens // 2,
    )


class FakeLLM:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    async def __call__(self, schema, **kwargs):
        self.calls.append(schema.__name__)
        return self.results.pop(0)


async def _retrieve(**kwargs) -> list[ServiceHit]:
    return []


def _config(llm: FakeLLM, *, retrieve=_retrieve, settings=None, hits=None) -> dict:
    deps = runtime.AgentDeps(
        settings=settings or _settings(),
        call_structured=llm,
        retrieve=retrieve,
        build_citations=citation_service.build_citations,
    )
    return {
        "configurable": {
            "agent_deps": deps,
            "metrics": {
                "fallback_count": 0,
                "llm_call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "citation_filtered_count": 0,
                "hits_by_id": hits or {},
                "filename_map": {"doc-1": "报告.pdf"},
                "last_new_chunk_count": 0,
                "last_findings": [],
                "last_conflicts": [],
            },
        }
    }


def _state(**overrides) -> dict:
    base = dict(
        user_id=USER_ID,
        session_id=SESSION_ID,
        agent_run_id=RUN_ID,
        question="主要风险有哪些？",
        document_ids=["doc-1"],
        max_iterations=3,
        token_budget=60000,
        timeout_seconds=120,
        iteration=0,
        queries=[],
        searched_queries=[],
        retrieved_chunks=[],
        max_score=0.0,
        findings=[],
        used_chunk_ids=[],
        conflicts=[],
        missing_information="",
        next_queries=[],
        is_sufficient=False,
        no_new_evidence_rounds=0,
        token_used=0,
        started_at=monotonic(),
        iterations=[],
        final_answer="",
        confidence="low",
        citations=[],
        stop_reason=None,
        status="planning",
    )
    base.update(overrides)
    return base


async def test_plan_queries_dedupes_and_counts_tokens():
    llm = FakeLLM(_result(PlanQueriesOutput(queries=[" 风险 ", "风险", "合规"])))
    config = _config(llm, settings=_settings(agent_max_queries_per_round=2))

    result = await nodes.plan_queries(_state(), config)

    assert result["iteration"] == 1
    assert result["queries"] == ["风险", "合规"]
    assert result["searched_queries"] == ["风险", "合规"]
    assert result["token_used"] == 8
    assert config["configurable"]["metrics"]["llm_call_count"] == 1


async def test_plan_queries_falls_back_to_original_question():
    llm = FakeLLM(_result(None))
    result = await nodes.plan_queries(_state(searched_queries=["主要风险有哪些？"]), _config(llm))
    assert result["stop_reason"] == "no_new_queries"
    assert result["queries"] == []


async def test_retrieve_documents_merges_by_chunk_id_and_detects_low_score():
    calls: list[str] = []

    async def _fake_retrieve(**kwargs) -> list[ServiceHit]:
        calls.append(kwargs["query"])
        return [
            ServiceHit(
                chunk_id="chunk-1",
                document_id="doc-1",
                content="风险A",
                score=0.2,
            ),
            ServiceHit(
                chunk_id="chunk-2",
                document_id="doc-1",
                content="风险B",
                score=0.6,
            ),
        ]

    llm = FakeLLM()
    config = _config(llm, retrieve=_fake_retrieve, settings=_settings(agent_score_threshold=0.35))
    result = await nodes.retrieve_documents(_state(queries=["风险", "合规"]), config)

    assert calls == ["风险", "合规"]
    assert result["max_score"] == 0.6
    assert len(result["retrieved_chunks"]) == 2
    assert result["stop_reason"] is None


async def test_retrieve_documents_sets_low_relevance():
    async def _low_score(**kwargs) -> list[ServiceHit]:
        return [ServiceHit(chunk_id="c1", document_id="doc-1", content="无关", score=0.1)]

    result = await nodes.retrieve_documents(
        _state(queries=["风险"]),
        _config(FakeLLM(), retrieve=_low_score, settings=_settings(agent_score_threshold=0.35)),
    )
    assert result["stop_reason"] == "low_relevance"


async def test_analyze_evidence_filters_fake_chunk_ids():
    llm = FakeLLM(
        _result(
            AnalyzeEvidenceOutput(
                findings=["第 3 页提到合规风险", "编造的发现"],
                used_chunk_ids=["chunk-1", "fake-chunk"],
                conflicts=["A 与 B 冲突"],
                reasoning="分析完成",
            )
        )
    )
    state = _state(
        iteration=1,
        searches=None,
        retrieved_chunks=[
            RetrievedChunk(
                doc_id="doc-1",
                chunk_id="chunk-1",
                content="合规风险",
                score=0.8,
                filename="报告.pdf",
            )
        ],
    )
    result = await nodes.analyze_evidence(state, _config(llm))

    assert result["used_chunk_ids"] == ["chunk-1"]
    assert len(result["findings"]) == 2
    assert result["conflicts"] == ["A 与 B 冲突"]
    assert result["no_new_evidence_rounds"] == 0


async def test_analyze_evidence_counts_no_new_evidence():
    llm = FakeLLM(
        _result(AnalyzeEvidenceOutput(findings=[], used_chunk_ids=[], conflicts=[], reasoning=""))
    )
    state = _state(
        iteration=2,
        retrieved_chunks=[
            RetrievedChunk(
                doc_id="doc-1", chunk_id="chunk-1", content="X", score=0.8, filename="报告.pdf"
            )
        ],
        used_chunk_ids=["chunk-1"],
        findings=["已有发现"],
    )
    result = await nodes.analyze_evidence(state, _config(llm))
    assert result["no_new_evidence_rounds"] == 1


async def test_decide_next_step_skips_llm_after_pre_stop():
    llm = FakeLLM()
    state = _state(iteration=1, stop_reason="low_relevance", queries=["风险"])
    result = await nodes.decide_next_step(state, _config(llm))

    assert llm.calls == []
    assert result["iterations"][0].decision == "answer"
    assert result["stop_reason"] == "low_relevance"


async def test_decide_next_step_continues_when_insufficient():
    llm = FakeLLM(
        _result(
            SufficiencyDecision(
                is_sufficient=False,
                missing_information="缺少风险等级",
                new_queries=["风险等级"],
                reason="证据不足",
            )
        )
    )
    result = await nodes.decide_next_step(_state(iteration=1), _config(llm))
    assert result["iterations"][0].decision == "continue"
    assert result["next_queries"] == ["风险等级"]
    assert result["stop_reason"] is None


async def test_final_answer_filters_fake_citations():
    hit = ServiceHit(chunk_id="chunk-1", document_id="doc-1", content="合规风险原文", score=0.9)
    llm = FakeLLM(
        _result(
            FinalAnswerOutput(
                answer="存在合规风险 [chunk-1]",
                confidence="high",
                citations=[
                    {
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "filename": "报告.pdf",
                        "quote": "伪造",
                    },
                    {
                        "chunk_id": "fake",
                        "document_id": "doc-1",
                        "filename": "报告.pdf",
                        "quote": "伪造",
                    },
                ],
            )
        )
    )
    config = _config(
        llm,
        hits={"chunk-1": hit.__dict__},
    )
    config["configurable"]["metrics"]["filename_map"] = {"doc-1": "报告.pdf"}
    state = _state(used_chunk_ids=["chunk-1"], stop_reason="sufficient")

    result = await nodes.final_answer(state, config)

    assert len(result["citations"]) == 1
    assert result["citations"][0].quote == "合规风险原文"
    assert result["confidence"] == "high"
    assert config["configurable"]["metrics"]["citation_filtered_count"] == 1


async def test_final_answer_low_relevance_skips_llm():
    llm = FakeLLM()
    result = await nodes.final_answer(_state(stop_reason="low_relevance"), _config(llm))
    assert llm.calls == []
    assert result["confidence"] == "low"
    assert result["final_answer"] == nodes.LOW_RELEVANCE_ANSWER


async def test_final_answer_keeps_partial_answer_when_evidence_exists():
    hit = ServiceHit(chunk_id="chunk-1", document_id="doc-1", content="合规风险", score=0.9)
    llm = FakeLLM(
        _result(
            FinalAnswerOutput(
                answer="部分结论 [chunk-1]",
                confidence="high",
                citations=[{"chunk_id": "chunk-1", "document_id": "doc-1"}],
            )
        )
    )
    config = _config(llm, hits={hit.chunk_id: hit.__dict__})
    state = _state(
        stop_reason="low_relevance",
        findings=["第 3 页提到合规风险"],
        used_chunk_ids=["chunk-1"],
    )

    result = await nodes.final_answer(state, config)

    assert result["final_answer"] != nodes.LOW_RELEVANCE_ANSWER
    assert "部分结论" in result["final_answer"]
    assert result["confidence"] == "low"


async def test_final_answer_removes_unverifiable_markers():
    hit = ServiceHit(chunk_id="chunk-1", document_id="doc-1", content="合规风险", score=0.9)
    llm = FakeLLM(
        _result(
            FinalAnswerOutput(
                answer="结论 [fake] 与 [chunk-1]",
                confidence="high",
                citations=[{"chunk_id": "chunk-1", "document_id": "doc-1"}],
            )
        )
    )
    config = _config(llm, hits={hit.chunk_id: hit.__dict__})

    result = await nodes.final_answer(
        _state(stop_reason="sufficient", used_chunk_ids=["chunk-1"]), config
    )

    assert "[fake]" not in result["final_answer"]
    assert "[chunk-1]" in result["final_answer"]
    assert result["confidence"] == "low"
    assert config["configurable"]["metrics"]["invalid_citation_marker_count"] == 1


async def test_decide_next_step_records_score_and_missing_information():
    llm = FakeLLM(
        _result(
            SufficiencyDecision(
                is_sufficient=False,
                missing_information="缺少风险等级",
                new_queries=["风险等级"],
                reason="证据不足",
            )
        )
    )
    result = await nodes.decide_next_step(_state(iteration=1, max_score=0.8), _config(llm))
    record = result["iterations"][0]
    assert record.max_score == 0.8
    assert record.missing_information == "缺少风险等级"
