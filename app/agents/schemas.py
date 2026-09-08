"""四个 LLM 节点的结构化输出模型。

与 prd/03-agent-design.md §3 各节点契约一致，用于 with_structured_output。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlanQueriesOutput(BaseModel):
    """NODE-1 plan_queries 输出。"""

    queries: list[str] = Field(
        min_length=1,
        max_length=3,
        description="1~3 条用于向量检索的查询，简洁、互不重复",
    )


class AnalyzeEvidenceOutput(BaseModel):
    """NODE-3 analyze_evidence 输出。"""

    findings: list[str] = Field(description="与问题相关的事实陈述，每条独立、简洁、可验证")
    used_chunk_ids: list[str] = Field(description="支撑上述发现的 chunk_id，必须来自给定片段")
    conflicts: list[str] = Field(default_factory=list, description="片段之间的矛盾")
    reasoning: str = Field(description="分析过程说明")


class SufficiencyDecision(BaseModel):
    """NODE-4 decide_next_step 输出。"""

    is_sufficient: bool = Field(description="当前证据是否足以回答用户问题")
    missing_information: str = Field(default="", description="若不足，说明缺少什么信息")
    new_queries: list[str] = Field(
        default_factory=list, max_length=3, description="建议的下一轮查询"
    )
    reason: str = Field(description="判断理由")


class FinalAnswerOutput(BaseModel):
    """NODE-5 final_answer 输出。"""

    answer: str = Field(description="最终回答，结构化、基于证据、含引用标记")
    confidence: Literal["high", "medium", "low"]
    citations: list[dict] = Field(default_factory=list, description="引用的 chunk_id 与原文摘录")
