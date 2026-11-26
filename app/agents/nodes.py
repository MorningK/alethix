"""LangGraph 五节点实现。

节点只负责产出状态增量，终止判断集中在 routing.resolve_stop_reason。
LLM、检索与引用构造通过 AgentDeps 注入，便于单元测试替换。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents import prompts, runtime
from app.agents.routing import resolve_stop_reason
from app.agents.schemas import (
    AnalyzeEvidenceOutput,
    FinalAnswerOutput,
    PlanQueriesOutput,
    SufficiencyDecision,
)
from app.agents.state import (
    AgentState,
    IterationRecord,
)
from app.agents.state import (
    Citation as StateCitation,
)
from app.agents.state import (
    RetrievedChunk as StateRetrievedChunk,
)
from app.core.logging import get_logger, safe_extra
from app.services.retrieval_service import RetrievedChunk as ServiceRetrievedChunk

logger = get_logger(__name__)

LOW_RELEVANCE_ANSWER = "当前文档中未找到足够相关的证据来回答该问题。"
_NO_EVIDENCE_NOTICE = "未能定位到可核验的原文依据。"

_DEFAULT_CONFIDENCE: dict[str, str] = {
    "sufficient": "high",
    "max_iterations_reached": "medium",
    "no_new_queries": "medium",
    "no_new_evidence": "medium",
    "low_relevance": "low",
    "budget_exceeded": "low",
    "internal_error": "low",
}

_WHITESPACE = re.compile(r"\s+")
_BRACKETED_TEXT = re.compile(r"\[([^\[\]\n]+)\]")
_UUID_CITATION = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_INVALID_MARKER_NOTICE = "已移除无法核验的引用标记。"


def _normalize_query(value: str) -> str:
    return _WHITESPACE.sub("", value).casefold()


def _dedupe(values: list[str]) -> list[str]:
    return list(
        dict.fromkeys(value for value in values if isinstance(value, str) and value.strip())
    )


def _sanitize_answer_markers(answer: str, valid_ids: set[str]) -> tuple[str, list[str]]:
    """只移除 UUID 形状且不在白名单中的引用标记，保留普通方括号文本。"""
    invalid: list[str] = []
    allowed = {item.casefold() for item in valid_ids}

    def _replace(match: re.Match[str]) -> str:
        marker = match.group(1).strip()
        if not _UUID_CITATION.fullmatch(marker):
            return match.group(0)
        if marker.casefold() in allowed:
            return match.group(0)
        invalid.append(marker)
        return ""

    return _BRACKETED_TEXT.sub(_replace, answer), invalid


def _account(
    result: Any,
    state: AgentState,
    config: RunnableConfig,
) -> int:
    """累加 token 与降级次数，返回新的 token_used。"""
    metrics = runtime.get_metrics(config)
    metrics["fallback_count"] = int(metrics.get("fallback_count", 0)) + int(
        getattr(result, "fallback_count", 0)
    )
    metrics["llm_call_count"] = int(metrics.get("llm_call_count", 0)) + 1
    metrics["prompt_tokens"] = int(metrics.get("prompt_tokens", 0)) + int(
        getattr(result, "prompt_tokens", 0)
    )
    metrics["completion_tokens"] = int(metrics.get("completion_tokens", 0)) + int(
        getattr(result, "completion_tokens", 0)
    )
    return int(state.get("token_used", 0)) + int(getattr(result, "token_used", 0))


def _build_retrieved_context(
    chunks: list[StateRetrievedChunk], max_chars: int, max_items: int = 12
) -> str:
    blocks: list[str] = []
    for chunk in chunks[:max_items]:
        location: list[str] = []
        if chunk.page is not None:
            location.append(f"第 {chunk.page} 页")
        if chunk.section:
            location.append(str(chunk.section))
        header = f"[chunk_id: {chunk.chunk_id}]（来源：{chunk.filename}" + (
            f"，{'，'.join(location)}）" if location else "）"
        )
        content = chunk.content.strip()[:max_chars]
        if len(chunk.content.strip()) > max_chars:
            content += "……（已截断）"
        blocks.append(f"{header}\n{content}")
    return "\n\n".join(blocks)


def _hits_from_metrics(config: RunnableConfig) -> list[ServiceRetrievedChunk]:
    hits_by_id = runtime.get_metrics(config).get("hits_by_id") or {}
    hits = [ServiceRetrievedChunk(**data) for data in hits_by_id.values()]
    return sorted(hits, key=lambda hit: hit.score, reverse=True)


async def plan_queries(state: AgentState, config: RunnableConfig) -> dict:
    """NODE-1：规划本轮查询。"""
    deps = runtime.get_agent_deps(config)
    settings = deps.settings
    iteration = int(state.get("iteration", 0)) + 1

    result = await deps.call_structured(
        PlanQueriesOutput,
        messages=[
            (
                "user",
                prompts.render_plan_queries(
                    question=state["question"],
                    searched_queries=list(state.get("searched_queries") or []),
                    findings=list(state.get("findings") or []),
                    missing_information=str(state.get("missing_information") or ""),
                    iteration=iteration,
                ),
            )
        ],
        settings=settings,
        node="plan_queries",
        temperature=0,
    )
    token_used = _account(result, state, config)
    payload = result.payload

    candidates = list(payload.queries) if payload is not None else [state["question"]]
    seen = {_normalize_query(value) for value in state.get("searched_queries") or []}
    deduped: list[str] = []
    for raw in candidates:
        query = str(raw).strip()
        key = _normalize_query(query)
        if not query or key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    deduped = deduped[: settings.agent_max_queries_per_round]

    return {
        "iteration": iteration,
        "queries": deduped,
        "searched_queries": deduped,
        "stop_reason": "no_new_queries" if not deduped else None,
        "token_used": token_used,
        "status": "planning",
    }


async def retrieve_documents(state: AgentState, config: RunnableConfig) -> dict:
    """NODE-2：并发检索、合并去重并计算本轮最高分。"""
    deps = runtime.get_agent_deps(config)
    settings = deps.settings

    if state.get("stop_reason") or not state.get("queries"):
        return {"retrieved_chunks": [], "max_score": 0.0, "status": "retrieving"}

    tasks = [
        deps.retrieve(
            query=query,
            user_id=state["user_id"],
            document_ids=list(state.get("document_ids") or []),
            top_k=settings.agent_top_k_per_query,
            score_threshold=None,
            settings=settings,
        )
        for query in state["queries"]
    ]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    merged: dict[str, ServiceRetrievedChunk] = {}
    errors: list[BaseException] = []
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            errors.append(outcome)
            logger.warning(
                "多轮检索中的单条查询失败",
                extra=safe_extra(reason=type(outcome).__name__),
            )
            continue
        for hit in outcome:
            current = merged.get(hit.chunk_id)
            if current is None or hit.score > current.score:
                merged[hit.chunk_id] = hit
    if not merged and errors:
        raise errors[0]

    metrics = runtime.get_metrics(config)
    for hit in merged.values():
        metrics.setdefault("hits_by_id", {})[hit.chunk_id] = asdict(hit)

    ranked = sorted(merged.values(), key=lambda hit: hit.score, reverse=True)
    chunks = [
        StateRetrievedChunk(
            doc_id=hit.document_id,
            chunk_id=hit.chunk_id,
            content=hit.content,
            score=hit.score,
            filename=hit.title or "未知文档",
            page=hit.page,
            section=hit.section,
        )
        for hit in ranked[: settings.agent_max_evidence_per_round]
    ]
    max_score = ranked[0].score if ranked else 0.0
    return {
        "retrieved_chunks": chunks,
        "max_score": max_score,
        "stop_reason": "low_relevance" if max_score < settings.agent_score_threshold else None,
        "status": "retrieving",
    }


async def analyze_evidence(state: AgentState, config: RunnableConfig) -> dict:
    """NODE-3：提取发现、校验 chunk_id 并统计新增证据。"""
    deps = runtime.get_agent_deps(config)
    settings = deps.settings
    metrics = runtime.get_metrics(config)

    if state.get("stop_reason"):
        metrics.update(
            last_new_chunk_count=0,
            last_findings=[],
            last_conflicts=[],
        )
        return {"status": "analyzing"}

    context = _build_retrieved_context(
        list(state.get("retrieved_chunks") or []),
        settings.agent_max_chunk_chars,
        settings.agent_max_evidence_per_round,
    )
    result = await deps.call_structured(
        AnalyzeEvidenceOutput,
        messages=[("user", prompts.render_analyze_evidence(state["question"], context))],
        settings=settings,
        node="analyze_evidence",
        temperature=0.2,
    )
    token_used = _account(result, state, config)
    payload = result.payload

    current_ids = {chunk.chunk_id for chunk in state.get("retrieved_chunks") or []}
    declared_ids = _dedupe(list(payload.used_chunk_ids) if payload else [])
    valid_ids = [chunk_id for chunk_id in declared_ids if chunk_id in current_ids]
    previous_ids = set(state.get("used_chunk_ids") or [])
    new_ids = [chunk_id for chunk_id in valid_ids if chunk_id not in previous_ids]

    previous_findings = set(state.get("findings") or [])
    new_findings = [
        item
        for item in _dedupe(list(payload.findings) if payload else [])
        if item not in previous_findings
    ]
    previous_conflicts = set(state.get("conflicts") or [])
    new_conflicts = [
        item
        for item in _dedupe(list(payload.conflicts) if payload else [])
        if item not in previous_conflicts
    ]

    no_new = not new_ids and not new_findings
    counter = int(state.get("no_new_evidence_rounds", 0)) + 1 if no_new else 0
    metrics.update(
        last_new_chunk_count=len(new_ids),
        last_findings=new_findings,
        last_conflicts=new_conflicts,
    )

    return {
        "findings": new_findings,
        "used_chunk_ids": new_ids,
        "conflicts": new_conflicts,
        "no_new_evidence_rounds": counter,
        "token_used": token_used,
        "status": "analyzing",
    }


async def decide_next_step(state: AgentState, config: RunnableConfig) -> dict:
    """NODE-4：判断证据是否充分并写入迭代记录。"""
    deps = runtime.get_agent_deps(config)
    settings = deps.settings
    metrics = runtime.get_metrics(config)
    pre_stop = state.get("stop_reason")

    is_sufficient = False
    missing_information = ""
    next_queries: list[str] = []
    reason = str(pre_stop or "")
    token_used = int(state.get("token_used", 0))

    if not pre_stop:
        result = await deps.call_structured(
            SufficiencyDecision,
            messages=[
                (
                    "user",
                    prompts.render_decide_next_step(
                        question=state["question"],
                        findings=list(state.get("findings") or []),
                        conflicts=list(state.get("conflicts") or []),
                        searched_queries=list(state.get("searched_queries") or []),
                        iteration=int(state.get("iteration", 0)),
                        max_iterations=int(
                            state.get("max_iterations", settings.agent_max_iterations)
                        ),
                    ),
                )
            ],
            settings=settings,
            node="decide_next_step",
            temperature=0,
        )
        token_used = _account(result, state, config)
        payload = result.payload
        if payload is not None:
            is_sufficient = bool(payload.is_sufficient)
            missing_information = str(payload.missing_information or "")
            next_queries = _dedupe(list(payload.new_queries)) if not is_sufficient else []
            reason = str(payload.reason or "")

    projected: dict[str, Any] = dict(state)
    projected.update(is_sufficient=is_sufficient, token_used=token_used)
    stop_reason = resolve_stop_reason(projected, settings=settings)

    record = IterationRecord(
        iteration=int(state.get("iteration", 0)),
        queries=list(state.get("queries") or []),
        retrieved_chunk_count=len(state.get("retrieved_chunks") or []),
        new_chunk_count=int(metrics.get("last_new_chunk_count", 0)),
        findings=list(metrics.get("last_findings") or []),
        conflicts=list(metrics.get("last_conflicts") or []),
        decision="answer" if stop_reason else "continue",
        reason=reason,
        max_score=float(state.get("max_score", 0.0)),
        missing_information=missing_information or None,
    )

    return {
        "is_sufficient": is_sufficient,
        "missing_information": missing_information,
        "next_queries": next_queries,
        "iterations": [record],
        "stop_reason": stop_reason,
        "token_used": token_used,
        "status": "deciding",
    }


def _citation_context(hits: list[ServiceRetrievedChunk], settings: Any) -> str:
    blocks: list[str] = []
    for hit in hits[: settings.agent_max_evidence_per_round]:
        location: list[str] = []
        if hit.page is not None:
            location.append(f"第 {hit.page} 页")
        if hit.section:
            location.append(str(hit.section))
        header = f"[chunk_id: {hit.chunk_id}]（来源：{hit.title or '未知文档'}" + (
            f"，{'，'.join(location)}）" if location else "）"
        )
        content = hit.content.strip()[: settings.agent_max_chunk_chars]
        blocks.append(f"{header}\n{content}")
    return "\n\n".join(blocks)


async def final_answer(state: AgentState, config: RunnableConfig) -> dict:
    """NODE-5：生成带引用的最终答案。"""
    deps = runtime.get_agent_deps(config)
    settings = deps.settings
    metrics = runtime.get_metrics(config)
    stop_reason = str(state.get("stop_reason") or "")
    token_used = int(state.get("token_used", 0))
    hits = _hits_from_metrics(config)
    hit_by_id = {hit.chunk_id: hit for hit in hits}
    whitelist = set(state.get("used_chunk_ids") or [])

    has_accumulated_evidence = bool(state.get("findings") or state.get("used_chunk_ids"))
    if stop_reason == "low_relevance" and not has_accumulated_evidence:
        citations, _ = deps.build_citations(
            hits[:3], metrics.get("filename_map") or {}, [], settings=settings
        )
        return {
            "final_answer": LOW_RELEVANCE_ANSWER,
            "confidence": "low",
            "citations": [
                StateCitation(
                    doc_id=item.document_id,
                    chunk_id=item.chunk_id,
                    filename=item.filename,
                    page=item.page,
                    section=item.section,
                    quote=item.quote,
                )
                for item in citations
            ],
            "stop_reason": stop_reason,
            "status": "done",
        }

    evidence_hits = [hit for hit in hits if hit.chunk_id in whitelist]
    guidance = runtime.stop_reason_guidance(stop_reason)
    if stop_reason == "low_relevance":
        guidance = (
            "注意：最新一轮检索相关度不足，已停止继续检索；"
            "请基于已收集证据给出部分结论，并明确说明仍存在的信息缺口。"
        )
    result = await deps.call_structured(
        FinalAnswerOutput,
        messages=[
            (
                "user",
                prompts.render_final_answer(
                    question=state["question"],
                    findings=list(state.get("findings") or []),
                    evidence_context=_citation_context(evidence_hits, settings),
                    stop_reason_guidance=guidance,
                ),
            )
        ],
        settings=settings,
        node="final_answer",
        temperature=0.2,
    )
    token_used = _account(result, state, config)
    payload = result.payload

    declared = _dedupe([item.chunk_id for item in payload.citations]) if payload else []
    valid_ids = [
        chunk_id for chunk_id in declared if chunk_id in whitelist and chunk_id in hit_by_id
    ]
    filtered_count = len(declared) - len(valid_ids)
    metrics["citation_filtered_count"] = filtered_count

    citations, _ = (
        deps.build_citations(hits, metrics.get("filename_map") or {}, valid_ids, settings=settings)
        if valid_ids
        else ([], filtered_count)
    )
    answer = (
        payload.answer.strip()
        if payload and payload.answer.strip()
        else ("基于当前已检索到的内容，暂时无法形成可靠结论。")
    )
    answer, invalid_markers = _sanitize_answer_markers(answer, set(valid_ids))
    if invalid_markers:
        metrics["invalid_citation_marker_count"] = len(invalid_markers)
        answer = f"{answer.rstrip()}\n\n{_INVALID_MARKER_NOTICE}"

    confidence = str(payload.confidence) if payload else _DEFAULT_CONFIDENCE.get(stop_reason, "low")
    if stop_reason == "low_relevance" or invalid_markers:
        confidence = "low"
    if not citations:
        confidence = "low"
        answer = f"{answer}\n\n{_NO_EVIDENCE_NOTICE}"

    return {
        "final_answer": answer,
        "confidence": confidence,
        "citations": [
            StateCitation(
                doc_id=item.document_id,
                chunk_id=item.chunk_id,
                filename=item.filename,
                page=item.page,
                section=item.section,
                quote=item.quote,
            )
            for item in citations
        ],
        "token_used": token_used,
        "status": "done",
    }


__all__ = [
    "analyze_evidence",
    "decide_next_step",
    "final_answer",
    "plan_queries",
    "retrieve_documents",
]
