"""LangGraph 图集成测试：循环、终止与状态累积。"""

from __future__ import annotations

from types import SimpleNamespace

from langgraph.checkpoint.memory import InMemorySaver

from app.agents import nodes, runtime
from app.agents.graph import build_graph
from app.agents.schemas import (
    AnalyzeEvidenceOutput,
    FinalAnswerOutput,
    PlanQueriesOutput,
    SufficiencyDecision,
)
from app.core.config import Settings
from app.services import citation_service
from app.services.agent_service import _initial_state
from app.services.retrieval_service import RetrievedChunk as ServiceHit

RUN_ID = "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f"
USER_ID = "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
SESSION_ID = "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f"


def _settings(**overrides) -> Settings:
    return Settings(  # type: ignore[arg-type]
        _env_file=None,
        agent_max_iterations=2,
        agent_max_queries_per_round=1,
        agent_top_k_per_query=3,
        agent_score_threshold=0.3,
        agent_max_evidence_per_round=3,
        agent_max_chunk_chars=1500,
        agent_token_budget=60000,
        agent_timeout_seconds=120,
        agent_no_new_evidence_rounds=1,
        **overrides,
    )


def _result(payload):
    return SimpleNamespace(
        payload=payload,
        token_used=4,
        fallback_count=0,
        prompt_tokens=2,
        completion_tokens=2,
    )


class ScriptedLLM:
    def __init__(self, *, decisions, analyses=None, final=None) -> None:
        self.decisions = list(decisions)
        self.analyses = list(analyses or [])
        self.final = final or FinalAnswerOutput(
            answer="基于证据的回答 [chunk-1]",
            confidence="high",
            citations=[{"chunk_id": "chunk-1", "document_id": "doc-1", "filename": "报告.pdf"}],
        )
        self.plan_index = 0

    async def __call__(self, schema, **kwargs):
        name = schema.__name__
        if name == "PlanQueriesOutput":
            self.plan_index += 1
            return _result(PlanQueriesOutput(queries=[f"查询{self.plan_index}"]))
        if name == "AnalyzeEvidenceOutput":
            payload = (
                self.analyses.pop(0)
                if self.analyses
                else AnalyzeEvidenceOutput(
                    findings=["发现"], used_chunk_ids=["chunk-1"], conflicts=[], reasoning=""
                )
            )
            return _result(payload)
        if name == "SufficiencyDecision":
            return _result(self.decisions.pop(0))
        if name == "FinalAnswerOutput":
            return _result(self.final)
        raise AssertionError(f"未预期的 schema: {name}")


async def _fake_retrieve(**kwargs) -> list[ServiceHit]:
    return [
        ServiceHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            content="文档明确提到合规风险。",
            score=0.8,
            title="报告.pdf",
        )
    ]


async def _run(
    *, decisions, analyses=None, retrieve=_fake_retrieve, max_iterations=2, settings=None
):
    s = settings or _settings()
    deps = runtime.AgentDeps(
        settings=s,
        call_structured=ScriptedLLM(decisions=decisions, analyses=analyses),
        retrieve=retrieve,
        build_citations=citation_service.build_citations,
    )
    config = runtime.build_run_config(
        RUN_ID, deps, {"doc-1": "报告.pdf"}, max_iterations=max_iterations
    )
    state = _initial_state(
        agent_run_id=RUN_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        question="主要风险有哪些？",
        document_ids=["doc-1"],
        max_iterations=max_iterations,
        settings=s,
    )
    graph = build_graph(checkpointer=InMemorySaver())
    return await graph.ainvoke(state, config=config)


async def test_first_round_sufficient():
    result = await _run(
        decisions=[
            SufficiencyDecision(
                is_sufficient=True, missing_information="", new_queries=[], reason="证据充分"
            )
        ]
    )
    assert result["stop_reason"] == "sufficient"
    assert len(result["iterations"]) == 1
    assert result["iterations"][0].decision == "answer"
    assert result["confidence"] == "high"


async def test_max_iterations_stops_run():
    insufficient = SufficiencyDecision(
        is_sufficient=False, missing_information="继续查", new_queries=["补充查询"], reason="不足"
    )
    result = await _run(decisions=[insufficient, insufficient])
    assert result["stop_reason"] == "max_iterations_reached"
    assert len(result["iterations"]) == 2


async def test_low_relevance_ends_without_decision_llm():
    async def _low_score(**kwargs) -> list[ServiceHit]:
        return [ServiceHit(chunk_id="chunk-1", document_id="doc-1", content="无关", score=0.1)]

    result = await _run(decisions=[], retrieve=_low_score)
    assert result["stop_reason"] == "low_relevance"
    assert result["confidence"] == "low"
    assert len(result["iterations"]) == 1


async def test_no_new_evidence_stops_second_round():
    first = AnalyzeEvidenceOutput(
        findings=["首次发现"], used_chunk_ids=["chunk-1"], conflicts=[], reasoning=""
    )
    second = AnalyzeEvidenceOutput(findings=[], used_chunk_ids=[], conflicts=[], reasoning="")
    insufficient = SufficiencyDecision(
        is_sufficient=False, missing_information="无新增证据", new_queries=["新查询"], reason="不足"
    )
    result = await _run(
        decisions=[insufficient, insufficient], analyses=[first, second], max_iterations=3
    )
    assert result["stop_reason"] == "no_new_evidence"
    assert len(result["iterations"]) == 2


async def test_single_iteration_cap():
    result = await _run(
        decisions=[
            SufficiencyDecision(
                is_sufficient=False,
                missing_information="未完",
                new_queries=["下一轮"],
                reason="不足",
            )
        ],
        max_iterations=1,
    )
    assert result["stop_reason"] == "max_iterations_reached"
    assert len(result["iterations"]) == 1


async def test_later_low_relevance_does_not_discard_earlier_evidence():
    call_count = 0

    async def _high_then_low(**kwargs) -> list[ServiceHit]:
        nonlocal call_count
        call_count += 1
        score = 0.8 if call_count == 1 else 0.1
        return [
            ServiceHit(
                chunk_id="chunk-1",
                document_id="doc-1",
                content="文档明确提到合规风险。",
                score=score,
                title="报告.pdf",
            )
        ]

    insufficient = SufficiencyDecision(
        is_sufficient=False, missing_information="继续查", new_queries=["补充查询"], reason="不足"
    )
    result = await _run(
        decisions=[insufficient],
        analyses=[
            AnalyzeEvidenceOutput(
                findings=["首次发现"], used_chunk_ids=["chunk-1"], conflicts=[], reasoning=""
            )
        ],
        retrieve=_high_then_low,
        max_iterations=3,
    )

    assert result["stop_reason"] == "low_relevance"
    assert result["final_answer"] != nodes.LOW_RELEVANCE_ANSWER
    assert "[chunk-1]" in result["final_answer"]
