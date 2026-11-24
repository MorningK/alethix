"""智能体运行服务。

负责组装 AgentState、驱动 LangGraph 五节点图、统计运行成本并输出结构化结果。
业务侧 trace 落库由 ask_service 在事务中完成。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

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


async def run_research(
    *,
    agent_run_id: str,
    question: str,
    session_id: str,
    user_id: str,
    document_ids: list[str],
    filename_map: dict[str, str],
    max_iterations: int,
    settings: Settings | None = None,
) -> ResearchResult:
    """执行一次多轮调研运行。"""
    s = settings or get_settings()
    deps = runtime.build_agent_deps(s)
    config = runtime.build_run_config(
        agent_run_id, deps, filename_map, max_iterations=max_iterations
    )
    metrics = runtime.get_metrics(config)
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

    try:
        final_state = await get_graph().ainvoke(state, config=config)
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


__all__ = ["ResearchResult", "run_research"]
