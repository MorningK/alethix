"""智能体运行服务。

负责组装 AgentState、驱动 LangGraph 五节点图、统计运行成本并输出结构化结果。
业务侧 trace 落库由 ask_service 在事务中完成。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from app.agents import runtime
from app.agents.graph import get_graph
from app.agents.state import AgentState, IterationRecord
from app.core.config import Settings, get_settings
from app.core.errors import ERR_AGENT_FAILED, ApiError
from app.core.logging import get_logger, safe_extra
from app.schemas.document import Citation

logger = get_logger(__name__)


@dataclass(frozen=True)
class ResearchResult:
    """多轮调研的结构化输出。"""

    agent_run_id: str
    state: AgentState
    answer: str
    confidence: str
    stop_reason: str | None
    iterations: list[IterationRecord]
    citations: list[Citation]
    token_used: int
    prompt_tokens: int
    completion_tokens: int
    llm_call_count: int
    fallback_count: int
    citation_filtered_count: int
    duration_ms: int


def _initial_state(
    *,
    agent_run_id: str,
    user_id: str,
    session_id: str,
    question: str,
    document_ids: list[str],
    max_iterations: int,
    settings: Settings,
) -> AgentState:
    return {
        "user_id": user_id,
        "session_id": session_id,
        "agent_run_id": agent_run_id,
        "question": question,
        "document_ids": document_ids,
        "max_iterations": max_iterations,
        "token_budget": settings.agent_token_budget,
        "timeout_seconds": settings.agent_timeout_seconds,
        "iteration": 0,
        "queries": [],
        "searched_queries": [],
        "retrieved_chunks": [],
        "max_score": 0.0,
        "findings": [],
        "used_chunk_ids": [],
        "conflicts": [],
        "missing_information": "",
        "next_queries": [],
        "is_sufficient": False,
        "no_new_evidence_rounds": 0,
        "token_used": 0,
        "started_at": monotonic(),
        "iterations": [],
        "final_answer": "",
        "confidence": "low",
        "citations": [],
        "stop_reason": None,
        "status": "planning",
    }


def _find_api_error(exc: BaseException) -> ApiError | None:
    """LangGraph 可能把节点异常包进 ExceptionGroup / __cause__ 中。"""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ApiError):
            return current
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
    return None


def _to_citations(state: AgentState, metrics: dict) -> list[Citation]:
    score_by_id = {
        chunk_id: float(data.get("score", 0.0))
        for chunk_id, data in (metrics.get("hits_by_id") or {}).items()
    }
    return [
        Citation(
            document_id=item.doc_id,
            chunk_id=item.chunk_id,
            filename=item.filename,
            page=item.page,
            section=item.section,
            quote=item.quote,
            score=score_by_id.get(item.chunk_id),
        )
        for item in state.get("citations") or []
    ]


def _timeout_state(state: AgentState) -> AgentState:
    """硬超时后返回保守收尾状态，不再发起额外 LLM 调用。"""
    findings = list(state.get("findings") or [])
    detail = (
        "\n".join(f"- {item}" for item in findings[:5])
        if findings
        else "当前证据不足以形成可靠答案。"
    )
    result: dict = dict(state)
    result.update(
        final_answer=f"因检索规模受限，以下结论可能不完整。\n{detail}",
        confidence="low",
        citations=[],
        stop_reason="budget_exceeded",
        status="done",
    )
    return result  # type: ignore[return-value]


async def run_research(
    *,
    agent_run_id: str,
    question: str,
    session_id: str,
    user_id: str,
    document_ids: list[str],
    filename_map: dict[str, str],
    max_iterations: int,
    history_findings: list[str] | None = None,
    settings: Settings | None = None,
) -> ResearchResult:
    """执行一次多轮调研运行。"""
    s = settings or get_settings()
    deps = runtime.build_agent_deps(s)
    config = runtime.build_run_config(
        agent_run_id, deps, filename_map, max_iterations=max_iterations
    )
    metrics = runtime.get_metrics(config)
    metrics["history_findings"] = list(history_findings or [])
    state = _initial_state(
        agent_run_id=agent_run_id,
        user_id=user_id,
        session_id=session_id,
        question=question,
        document_ids=document_ids,
        max_iterations=max_iterations,
        settings=s,
    )
    started_at = state["started_at"]

    graph = get_graph()
    try:
        final_state = await asyncio.wait_for(
            graph.ainvoke(state, config=config), timeout=s.agent_timeout_seconds
        )
    except TimeoutError:
        logger.warning(
            "多轮调研硬超时，尝试从检查点恢复已完成状态",
            extra=safe_extra(agent_run_id=agent_run_id),
        )
        timeout_base: dict = dict(state)
        try:
            snapshot = await graph.aget_state({"configurable": {"thread_id": agent_run_id}})
            if snapshot.values:
                timeout_base = dict(snapshot.values)
                logger.warning(
                    "已从检查点恢复超时前状态",
                    extra=safe_extra(
                        agent_run_id=agent_run_id,
                        iterations=len(snapshot.values.get("iterations") or []),
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "超时后读取检查点失败，回退到输入状态",
                extra=safe_extra(agent_run_id=agent_run_id, reason=type(exc).__name__),
            )
        final_state = _timeout_state(timeout_base)  # type: ignore[arg-type]
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        api_error = _find_api_error(exc)
        if api_error is not None:
            raise api_error
        logger.warning("多轮调研执行失败", extra=safe_extra(reason=type(exc).__name__))
        raise ApiError(ERR_AGENT_FAILED, "多轮调研执行失败", status=500) from exc

    token_used = int(final_state.get("token_used", 0))
    return ResearchResult(
        agent_run_id=agent_run_id,
        state=final_state,
        answer=str(final_state.get("final_answer") or ""),
        confidence=str(final_state.get("confidence") or "low"),
        stop_reason=final_state.get("stop_reason"),
        iterations=list(final_state.get("iterations") or []),
        citations=_to_citations(final_state, metrics),
        token_used=token_used,
        prompt_tokens=int(metrics.get("prompt_tokens", 0)),
        completion_tokens=int(metrics.get("completion_tokens", 0)),
        llm_call_count=int(metrics.get("llm_call_count", 0)),
        fallback_count=int(metrics.get("fallback_count", 0)),
        citation_filtered_count=int(metrics.get("citation_filtered_count", 0)),
        duration_ms=int((monotonic() - started_at) * 1000),
    )


_ACCUMULATED_KEYS = ("searched_queries", "findings", "used_chunk_ids", "conflicts", "iterations")


def _merge_delta(state: dict[str, Any], delta: dict[str, Any]) -> None:
    """按 AgentState 的 reducer 语义合并节点增量，供事件映射使用。"""
    for key, value in delta.items():
        if key in _ACCUMULATED_KEYS:
            state[key] = list(state.get(key) or []) + list(value or [])
        else:
            state[key] = value


def _last_iteration_reason(delta: dict[str, Any]) -> str:
    """从 decide_next_step 的最后一个迭代记录中读取判断理由。"""
    records = delta.get("iterations") or []
    if not records:
        return ""
    last = records[-1]
    reason = getattr(last, "reason", None)
    if reason is None and isinstance(last, dict):
        reason = last.get("reason")
    return str(reason or "")


async def _emit_node_event(
    node_name: str,
    delta: dict[str, Any],
    state: dict[str, Any],
    metrics: dict[str, Any],
    event_sink: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> None:
    """把节点完成的增量映射为 SSE 过程事件（AG-5.4：不发送原文）。"""
    if node_name == "plan_queries":
        await event_sink(
            "iteration",
            {
                "iteration": int(delta.get("iteration") or 0),
                "queries": list(delta.get("queries") or []),
                "searched_query_count": len(state.get("searched_queries") or []),
            },
        )
    elif node_name == "analyze_evidence":
        await event_sink(
            "retrieved",
            {
                "iteration": int(state.get("iteration") or 0),
                "retrieved_chunk_count": len(state.get("retrieved_chunks") or []),
                "new_chunk_count": int(metrics.get("last_new_chunk_count", 0)),
                "max_score": float(state.get("max_score") or 0.0),
            },
        )
    elif node_name == "decide_next_step":
        await event_sink(
            "reasoning",
            {
                "iteration": int(state.get("iteration") or 0),
                "decision": "answer" if delta.get("stop_reason") else "continue",
                "reason": _last_iteration_reason(delta),
                "missing_information": str(delta.get("missing_information") or ""),
                "findings_count": len(state.get("findings") or []),
                "conflicts_count": len(state.get("conflicts") or []),
            },
        )


def _result_from_state(
    *,
    agent_run_id: str,
    final_state: dict[str, Any],
    metrics: dict[str, Any],
    started_at: float,
) -> ResearchResult:
    """把图终态统一转换为 ResearchResult。"""
    return ResearchResult(
        agent_run_id=agent_run_id,
        state=final_state,  # type: ignore[arg-type]
        answer=str(final_state.get("final_answer") or ""),
        confidence=str(final_state.get("confidence") or "low"),
        stop_reason=final_state.get("stop_reason"),
        iterations=list(final_state.get("iterations") or []),
        citations=_to_citations(final_state, metrics),
        token_used=int(final_state.get("token_used", 0)),
        prompt_tokens=int(metrics.get("prompt_tokens", 0)),
        completion_tokens=int(metrics.get("completion_tokens", 0)),
        llm_call_count=int(metrics.get("llm_call_count", 0)),
        fallback_count=int(metrics.get("fallback_count", 0)),
        citation_filtered_count=int(metrics.get("citation_filtered_count", 0)),
        duration_ms=int((monotonic() - started_at) * 1000),
    )


async def stream_research(
    *,
    agent_run_id: str,
    question: str,
    session_id: str,
    user_id: str,
    document_ids: list[str],
    filename_map: dict[str, str],
    max_iterations: int,
    event_sink: Callable[[str, dict[str, Any]], Awaitable[None]],
    history_findings: list[str] | None = None,
    settings: Settings | None = None,
) -> ResearchResult:
    """以 LangGraph astream 驱动多轮调研，并在节点完成后推送过程事件。"""
    s = settings or get_settings()
    deps = runtime.build_agent_deps(s)
    config = runtime.build_run_config(
        agent_run_id, deps, filename_map, max_iterations=max_iterations
    )
    metrics = runtime.get_metrics(config)
    metrics["history_findings"] = list(history_findings or [])
    state = _initial_state(
        agent_run_id=agent_run_id,
        user_id=user_id,
        session_id=session_id,
        question=question,
        document_ids=document_ids,
        max_iterations=max_iterations,
        settings=s,
    )
    started_at = state["started_at"]
    current: dict[str, Any] = dict(state)
    graph = get_graph()

    async def _consume() -> dict[str, Any]:
        async for chunk in graph.astream(state, config=config, stream_mode="updates"):
            for node_name, delta in chunk.items():
                _merge_delta(current, delta)
                await _emit_node_event(node_name, delta, current, metrics, event_sink)
        return current

    try:
        final_state = await asyncio.wait_for(_consume(), timeout=s.agent_timeout_seconds)
    except TimeoutError:
        logger.warning(
            "流式多轮调研硬超时，尝试从检查点恢复已完成状态",
            extra=safe_extra(agent_run_id=agent_run_id),
        )
        timeout_base: dict[str, Any] = dict(current)
        try:
            snapshot = await graph.aget_state({"configurable": {"thread_id": agent_run_id}})
            if snapshot.values:
                timeout_base = dict(snapshot.values)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "超时后读取检查点失败，回退到输入状态",
                extra=safe_extra(agent_run_id=agent_run_id, reason=type(exc).__name__),
            )
        final_state = _timeout_state(timeout_base)  # type: ignore[arg-type]
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        api_error = _find_api_error(exc)
        if api_error is not None:
            raise api_error
        logger.warning("流式多轮调研执行失败", extra=safe_extra(reason=type(exc).__name__))
        raise ApiError(ERR_AGENT_FAILED, "流式多轮调研执行失败", status=500) from exc

    return _result_from_state(
        agent_run_id=agent_run_id,
        final_state=final_state,
        metrics=metrics,
        started_at=started_at,
    )


__all__ = ["ResearchResult", "run_research", "stream_research"]
