"""SSE 事件载荷 DTO。

字段与 prd/05-api-spec.md §4 及 web/src/types/sse.ts 逐一对齐。
事件正文不包含检索原文全文，仅包含统计与摘要（SSE-5）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.ask import Confidence, StopReason
from app.schemas.document import Citation


class StartedEvent(BaseModel):
    type: Literal["started"] = "started"
    agent_run_id: str
    session_id: str
    question: str
    max_iterations: int


class IterationEvent(BaseModel):
    type: Literal["iteration"] = "iteration"
    iteration: int
    queries: list[str] = Field(default_factory=list)
    searched_query_count: int = 0


class RetrievedEvent(BaseModel):
    type: Literal["retrieved"] = "retrieved"
    iteration: int
    retrieved_chunk_count: int = 0
    new_chunk_count: int = 0
    max_score: float = 0.0


class ReasoningEvent(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    iteration: int
    decision: Literal["continue", "answer"]
    reason: str = ""
    missing_information: str = ""
    findings_count: int = 0
    conflicts_count: int = 0


class FinalAnswerEvent(BaseModel):
    type: Literal["final_answer"] = "final_answer"
    agent_run_id: str
    answer: str
    confidence: Confidence
    stop_reason: StopReason | None = None
    iteration_count: int = 0
    duration_ms: int = 0
    token_used: int = 0
    citations: list[Citation] = Field(default_factory=list)


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    trace_id: str = ""


__all__ = [
    "ErrorEvent",
    "FinalAnswerEvent",
    "IterationEvent",
    "ReasoningEvent",
    "RetrievedEvent",
    "StartedEvent",
]
