"""答案生成服务的结构化输出 DTO。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.ask import Confidence


class GeneratedAnswer(BaseModel):
    """LLM 单次生成结果；chunk_id 仅作候选，最终由服务层白名单校验。"""

    answer: str = Field(min_length=1)
    confidence: Confidence
    findings: list[str] = Field(default_factory=list)
    used_chunk_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    conflicts: list[str] = Field(default_factory=list)
