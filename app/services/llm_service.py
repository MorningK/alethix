"""LLM 服务。

对应 prd/02-architecture.md §5.1.1：LLM 与 Embedding 必须各自构造独立客户端，
分别使用 resolved_llm_* 与 resolved_embedding_*，禁止共享同一 client（AG-7.1）。

智能体结构化输出（invoke_structured）使用原始 JSON 模式调用 + 自写稳健解析，
兼容 DeepSeek 等 OpenAI 兼容端点返回 Markdown 围栏、前后解释文字与内容块的情况。
保留四级降级链：主模型 → 同模型重试 → 降级模型 → 节点保守默认值。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, safe_extra

T = TypeVar("T", bound=BaseModel)

logger = get_logger(__name__)

_RETRY_HINT = (
    "\n<format_reminder>\n"
    "再次强调：只输出一个符合给定 JSON Schema 的合法 JSON 对象，"
    "不要输出 Markdown 代码块或任何解释文字。\n"
    "</format_reminder>"
)

_FENCE_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)

_JSON_MODE_KWARGS = {"response_format": {"type": "json_object"}}


@dataclass(frozen=True)
class StructuredResult:
    """结构化调用结果与成本统计。"""

    payload: BaseModel | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fallback_count: int = 0

    @property
    def token_used(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def build_llm(
    settings: Settings,
    *,
    structured: type[T] | None = None,
    temperature: float | None = None,
    model: str | None = None,
    json_mode: bool = False,
):
    """构造 LLM 客户端。

    Args:
        settings: 应用配置
        structured: 若传入 Pydantic 模型，则返回 with_structured_output 的链
        temperature: 覆盖配置中的默认温度（决策节点固定为 0）
        model: 覆盖模型名（用于降级模型）
        json_mode: 原始调用时请求 JSON 输出；structured 模式忽略该参数
    """
    kwargs: dict[str, Any] = {
        "model": model or settings.llm_model,
        "temperature": settings.llm_temperature if temperature is None else temperature,
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
        "max_tokens": settings.llm_max_tokens,
        "api_key": settings.resolved_llm_api_key,
        "base_url": settings.resolved_llm_base_url,
        # 兼容 vLLM / DeepSeek / Qwen 等 OpenAI 兼容端点
        "use_responses_api": False,
    }
    if json_mode and structured is None:
        kwargs["model_kwargs"] = dict(_JSON_MODE_KWARGS)

    llm = ChatOpenAI(**kwargs)
    if structured is not None:
        return llm.with_structured_output(structured, method="json_mode")
    return llm


def build_fallback_llm(
    settings: Settings,
    *,
    temperature: float | None = None,
    json_mode: bool = False,
):
    """构造降级模型客户端（AG-4 第 3 级）。未配置时返回主模型。"""
    return build_llm(
        settings,
        model=settings.llm_fallback_model or settings.llm_model,
        temperature=temperature,
        json_mode=json_mode,
    )


def get_llm():
    return build_llm(get_settings())


@lru_cache(maxsize=1)
def _tokenizer():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        return len(_tokenizer().encode(text))
    except Exception:  # noqa: BLE001
        return max(1, len(text) // 4)


def _extract_text(value: Any) -> str:
    """从字符串、内容块列表或内容块对象中提取纯文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(part for item in value if (part := _extract_text(item)))
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            item = value.get(key)
            if isinstance(item, str) and item:
                return item
        return ""
    for attr in ("text", "content"):
        item = getattr(value, attr, None)
        if isinstance(item, str) and item:
            return item
    return ""


def _messages_text(messages: Sequence[tuple[str, str]]) -> str:
    return "\n".join(f"{role}:\n{content}" for role, content in messages)


def _append_hint(messages: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    result = [tuple(message) for message in messages]  # type: ignore[misc]
    if result and result[0][0] == "system":
        result[0] = ("system", result[0][1] + _RETRY_HINT)
    else:
        result.insert(0, ("system", _RETRY_HINT.strip()))
    return result


def _usage(response: Any) -> tuple[int, int]:
    metadata = getattr(response, "usage_metadata", None) or {}
    prompt = int(metadata.get("input_tokens") or metadata.get("prompt_tokens") or 0)
    completion = int(metadata.get("output_tokens") or metadata.get("completion_tokens") or 0)
    if prompt or completion:
        return prompt, completion
    return 0, _estimate_tokens(_extract_text(getattr(response, "content", "")))


def _strip_json_fences(text: str) -> tuple[str, bool]:
    blocks = list(_FENCE_BLOCK.finditer(text or ""))
    if not blocks:
        return text or "", False
    best = max(blocks, key=lambda match: len(match.group(1).strip()))
    return best.group(1).strip(), True


def _iter_json_candidates(text: str):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            yield candidate


def _validation_error_details(exc: Exception) -> str:
    """把 Pydantic 校验错误压成简短、可诊断的一行文本。"""
    if isinstance(exc, ValidationError):
        details: list[str] = []
        for error in exc.errors()[:2]:
            location = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
            message = str(error.get("msg", ""))[:120]
            details.append(f"{location}: {message}")
        return "; ".join(details) or str(exc)[:200]
    return str(exc)[:200]


def _parse_json_payload(
    text: str,
    schema: type[T],
    *,
    node: str = "unknown",
    attempt: int = 0,
) -> tuple[T | None, int, bool]:
    """清理围栏并逐个校验 JSON 候选，返回 (结果, 候选数量, 是否含围栏)。"""
    raw = _extract_text(text)
    cleaned, has_fence = _strip_json_fences(raw)
    candidates: list[dict] = []

    try:
        direct = json.loads(cleaned)
        if isinstance(direct, dict):
            candidates.append(direct)
    except json.JSONDecodeError:
        pass

    for candidate in _iter_json_candidates(cleaned):
        if candidate not in candidates:
            candidates.append(candidate)

    for index, candidate in enumerate(candidates, start=1):
        try:
            return schema.model_validate(candidate), len(candidates), has_fence
        except (ValidationError, TypeError, ValueError) as exc:
            if index <= 2:
                logger.warning(
                    "JSON Schema 校验失败",
                    extra=safe_extra(
                        node=node,
                        attempt=attempt,
                        schema=schema.__name__,
                        candidate=index,
                        candidates=len(candidates),
                        errors=_validation_error_details(exc),
                    ),
                )
            continue
    return None, len(candidates), has_fence


def _snippet(text: str, limit: int = 240) -> str:
    compact = " ".join(_extract_text(text).split())
    return compact[:limit]


def _log_parse_failure(
    *,
    node: str,
    attempt: int,
    raw_text: str,
    candidate_count: int,
    has_fence: bool,
) -> None:
    logger.warning(
        "结构化输出解析失败",
        extra=safe_extra(
            node=node,
            attempt=attempt,
            candidates=candidate_count,
            has_fence=has_fence,
            snippet=_snippet(raw_text),
        ),
    )


def _is_json_mode_unsupported(exc: Exception) -> bool:
    """判断错误是否因为端点不接受 response_format 参数。"""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    if status != 400:
        return False
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("response_format", "json_object", "unsupported parameter", "not support")
    )


async def _invoke_raw(
    builder: Callable[..., Any],
    messages: Sequence[tuple[str, str]],
    *,
    node: str,
    attempt: int,
) -> Any:
    """原始 JSON 模式调用；端点拒绝该参数时同级别去掉参数重试一次。"""
    try:
        return await builder(json_mode=True).ainvoke(list(messages))
    except Exception as exc:  # noqa: BLE001
        if not _is_json_mode_unsupported(exc):
            raise
        logger.warning(
            "端点不支持 JSON 模式参数，去掉 response_format 重试",
            extra=safe_extra(node=node, attempt=attempt, reason=type(exc).__name__),
        )
        return await builder(json_mode=False).ainvoke(list(messages))


async def invoke_structured(
    schema: type[T],
    *,
    messages: Sequence[tuple[str, str]],
    settings: Settings | None = None,
    node: str = "unknown",
    temperature: float | None = None,
) -> StructuredResult:
    """四级降级的结构化调用；任何失败都返回 payload=None，不抛给节点。"""
    s = settings or get_settings()
    prompt_tokens = 0
    completion_tokens = 0

    def _primary_builder(*, json_mode: bool):
        return build_llm(s, temperature=temperature, json_mode=json_mode)

    def _fallback_builder(*, json_mode: bool):
        return build_fallback_llm(s, temperature=temperature, json_mode=json_mode)

    attempts: list[tuple[Callable[..., Any], Sequence[tuple[str, str]], int]] = [
        (_primary_builder, messages, 0),
        (_primary_builder, _append_hint(messages), 1),
        (_fallback_builder, messages, 2),
    ]

    for builder, current_messages, attempt in attempts:
        try:
            response = await _invoke_raw(builder, current_messages, node=node, attempt=attempt)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "结构化输出调用失败",
                extra=safe_extra(node=node, attempt=attempt, reason=type(exc).__name__),
            )
            continue

        p_tokens, c_tokens = _usage(response)
        prompt_tokens += p_tokens
        completion_tokens += c_tokens

        if isinstance(response, schema):
            return StructuredResult(
                payload=response,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                fallback_count=attempt,
            )

        raw_text = getattr(response, "content", response)
        payload, candidate_count, has_fence = _parse_json_payload(
            raw_text, schema, node=node, attempt=attempt
        )
        if payload is not None:
            return StructuredResult(
                payload=payload,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                fallback_count=attempt,
            )

        _log_parse_failure(
            node=node,
            attempt=attempt,
            raw_text=raw_text,
            candidate_count=candidate_count,
            has_fence=has_fence,
        )

    logger.warning("结构化输出四级降级均未成功", extra=safe_extra(node=node))
    return StructuredResult(
        payload=None,
        prompt_tokens=prompt_tokens or _estimate_tokens(_messages_text(messages)),
        completion_tokens=completion_tokens,
        fallback_count=3,
    )


__all__ = [
    "StructuredResult",
    "build_fallback_llm",
    "build_llm",
    "get_llm",
    "invoke_structured",
]
