"""LLM 服务（占位）。

对应 prd/02-architecture.md §5.1.1：LLM 与 Embedding 必须各自构造独立客户端，
分别使用 resolved_llm_* 与 resolved_embedding_*，禁止共享同一 client（AG-7.1）。

ChatOpenAI 关键参数（已核对 langchain-openai 文档）：
    model / temperature / timeout / max_retries / api_key / base_url
    - 指向非 OpenAI 端点时显式设置 use_responses_api=False，避免模型名推断走 Responses API
    - 结构化输出：model.with_structured_output(Schema)

实现阶段：M2。
"""

from __future__ import annotations

from typing import TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


def build_llm(settings: Settings, *, structured: type[T] | None = None):
    """构造 LLM 客户端。

    Args:
        settings: 应用配置
        structured: 若传入 Pydantic 模型，则返回 with_structured_output 的链
    """
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        api_key=settings.resolved_llm_api_key,
        base_url=settings.resolved_llm_base_url,
        # 兼容 vLLM / DeepSeek / Qwen 等 OpenAI 兼容端点
        use_responses_api=False,
    )
    if structured is not None:
        return llm.with_structured_output(structured)
    return llm


def build_fallback_llm(settings: Settings):
    """构造降级模型客户端（AG-4 第 3 级降级）。未配置时返回主模型。"""
    model = settings.llm_fallback_model or settings.llm_model
    return build_llm(settings).model_copy(update={"model_name": model})


def get_llm():
    return build_llm(get_settings())
