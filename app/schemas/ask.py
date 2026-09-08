"""问答相关 DTO。

字段与 prd/05-api-spec.md §2.3 / §4 对齐；
stop_reason 枚举与 prd/03-agent-design.md §5 一致。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.document import Citation

StopReason = Literal[
    "sufficient",
    "max_iterations_reached",
    "no_new_queries",
    "no_new_evidence",
    "low_relevance",
    "budget_exceeded",
    "internal_error",
]

Confidence = Literal["high", "medium", "low"]


class AskRequest(BaseModel):
    """API-6 / API-7 请求体。"""

    session_id: str
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=3, ge=1, le=10)


class IterationRecord(BaseModel):
    """单轮迭代记录（prd/05-api-spec.md §2.3）。"""

    iteration: int
    queries: list[str] = Field(default_factory=list)
    retrieved_chunk_count: int = 0
    new_chunk_count: int = 0
    findings: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    decision: Literal["continue", "answer"]
    reason: str = ""
    missing_information: str | None = None


class AskResponse(BaseModel):
    """API-6 响应。"""

    agent_run_id: str
    session_id: str
    question: str
    answer: str
    confidence: Confidence
    stop_reason: StopReason | None = None
    iteration_count: int = 0
    duration_ms: int | None = None
    token_used: int | None = None
    iterations: list[IterationRecord] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
