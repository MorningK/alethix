"""智能体状态定义。

与 prd/03-agent-design.md §1.2 逐字段对齐，不得自行增减字段。
reducer 语义见 §1.3 字段读写矩阵。
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

StopReason = Literal[
    "sufficient",
    "max_iterations_reached",
    "no_new_queries",
    "no_new_evidence",
    "low_relevance",
    "budget_exceeded",
    "internal_error",
]

AgentStatus = Literal[
    "planning",
    "retrieving",
    "analyzing",
    "deciding",
    "answering",
    "done",
    "failed",
]


class RetrievedChunk(BaseModel):
    """一次检索命中的切片。"""

    doc_id: str
    chunk_id: str
    content: str
    score: float
    filename: str
    page: int | None = None
    section: str | None = None


class Citation(BaseModel):
    """答案引用。"""

    doc_id: str
    chunk_id: str
    filename: str
    page: int | None = None
    section: str | None = None
    quote: str = Field(description="原文片段，直接摘录，不得改写")


class IterationRecord(BaseModel):
    """单轮迭代记录。"""

    iteration: int
    queries: list[str]
    retrieved_chunk_count: int
    new_chunk_count: int
    findings: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    decision: Literal["continue", "answer"]
    reason: str = ""


class AgentState(TypedDict):
    """LangGraph 图状态。"""

    # ===== 输入侧（初始化后只读）=====
    user_id: str
    session_id: str
    agent_run_id: str
    question: str
    document_ids: list[str]
    max_iterations: int
    token_budget: int
    timeout_seconds: int

    # ===== 循环侧 =====
    iteration: int
    queries: list[str]
    searched_queries: Annotated[list[str], operator.add]
    retrieved_chunks: list[RetrievedChunk]
    max_score: float
    findings: Annotated[list[str], operator.add]
    used_chunk_ids: Annotated[list[str], operator.add]
    conflicts: Annotated[list[str], operator.add]
    missing_information: str
    next_queries: list[str]
    is_sufficient: bool
    no_new_evidence_rounds: int

    # ===== 预算与观测 =====
    token_used: int
    started_at: float

    # ===== 输出侧 =====
    iterations: Annotated[list[IterationRecord], operator.add]
    final_answer: str
    confidence: Literal["high", "medium", "low"]
    citations: list[Citation]
    stop_reason: StopReason | None
    status: AgentStatus
