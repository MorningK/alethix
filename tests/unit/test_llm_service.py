"""LLM 结构化输出解析与降级链测试。"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app.agents.schemas import PlanQueriesOutput, SufficiencyDecision
from app.core.config import Settings
from app.schemas.answer import GeneratedAnswer
from app.services import llm_service


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[arg-type]


class FakeChat:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def with_structured_output(self, schema, *, method=None):
        return (schema, method)


class FakeResponse:
    def __init__(self, content, *, usage=None) -> None:
        self.content = content
        self.usage_metadata = usage or {"input_tokens": 3, "output_tokens": 2}


def test_build_llm_keeps_structured_json_mode(monkeypatch):
    monkeypatch.setattr(llm_service, "ChatOpenAI", FakeChat)
    result = llm_service.build_llm(_settings(), structured=GeneratedAnswer)
    assert result[1] == "json_mode"


def test_build_llm_json_mode_sets_response_format(monkeypatch):
    captured: dict = {}

    class Chat(FakeChat):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            captured.update(kwargs)

    monkeypatch.setattr(llm_service, "ChatOpenAI", Chat)
    llm_service.build_llm(_settings(), json_mode=True)
    assert captured["model_kwargs"] == {"response_format": {"type": "json_object"}}


def test_parse_json_from_content_block_with_fence_and_trailing_text():
    content = [
        {
            "type": "text",
            "text": '说明文字\n```json\n{"queries": ["风险", "合规"]}\n```\n以上为结果。',
        }
    ]
    response = SimpleNamespace(content=content)
    payload, candidates, has_fence = llm_service._parse_json_payload(
        response.content, PlanQueriesOutput
    )
    assert payload is not None
    assert payload.queries == ["风险", "合规"]
    assert has_fence is True
    assert candidates >= 1


def test_parse_json_skips_invalid_candidates():
    text = '先输出 {"foo": 1}，然后才是 {"is_sufficient": false, "missing_information": "缺数据", "new_queries": ["补查"], "reason": "不足"}。'
    payload, candidates, _ = llm_service._parse_json_payload(text, SufficiencyDecision)
    assert candidates == 2
    assert payload is not None
    assert payload.is_sufficient is False
    assert payload.new_queries == ["补查"]


def test_usage_uses_text_from_content_blocks():
    response = SimpleNamespace(
        content=[{"type": "text", "text": "很长的输出内容" * 20}],
        usage_metadata=None,
    )
    prompt, completion = llm_service._usage(response)
    assert prompt == 0
    assert completion > 0


async def test_invoke_structured_retry_then_success(monkeypatch):
    responses = [
        FakeResponse("不是 JSON"),
        FakeResponse('{"queries": ["风险"]}'),
    ]

    class LLM:
        async def ainvoke(self, messages):
            return responses.pop(0)

    monkeypatch.setattr(llm_service, "build_llm", lambda *a, **k: LLM())
    monkeypatch.setattr(llm_service, "build_fallback_llm", lambda *a, **k: LLM())

    result = await llm_service.invoke_structured(
        PlanQueriesOutput,
        messages=[("user", "生成查询")],
        settings=_settings(),
        node="plan_queries",
    )

    assert isinstance(result.payload, PlanQueriesOutput)
    assert result.payload.queries == ["风险"]
    assert result.fallback_count == 1
    assert result.token_used == 10


async def test_invoke_structured_all_levels_fail(monkeypatch):
    class LLM:
        async def ainvoke(self, messages):
            return FakeResponse("仍然不是 JSON")

    monkeypatch.setattr(llm_service, "build_llm", lambda *a, **k: LLM())
    monkeypatch.setattr(llm_service, "build_fallback_llm", lambda *a, **k: LLM())

    result = await llm_service.invoke_structured(
        PlanQueriesOutput,
        messages=[("user", "生成查询")],
        settings=_settings(),
        node="plan_queries",
    )

    assert result.payload is None
    assert result.fallback_count == 3
    assert result.token_used == 15


async def test_invoke_structured_retries_without_json_mode_on_400(monkeypatch):
    modes: list[bool | None] = []

    class BadRequestError(Exception):
        status_code = 400

    class LLM:
        def __init__(self, json_mode: bool | None) -> None:
            self.json_mode = json_mode

        async def ainvoke(self, messages):
            if self.json_mode:
                raise BadRequestError("unsupported parameter response_format")
            return FakeResponse('{"queries": ["风险"]}')

    def _builder(*args, **kwargs):
        json_mode = kwargs.get("json_mode")
        modes.append(json_mode)
        return LLM(json_mode)

    monkeypatch.setattr(llm_service, "build_llm", _builder)
    monkeypatch.setattr(llm_service, "build_fallback_llm", _builder)

    result = await llm_service.invoke_structured(
        PlanQueriesOutput,
        messages=[("user", "生成查询")],
        settings=_settings(),
        node="plan_queries",
    )

    assert isinstance(result.payload, PlanQueriesOutput)
    assert modes[:2] == [True, False]
    assert result.fallback_count == 0


def test_parse_json_logs_validation_error(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.llm_service")
    text = (
        '{"is_sufficient": true, "missing_information": null, '
        '"new_queries": [], "reason": "证据充分"}'
    )

    payload, candidates, _ = llm_service._parse_json_payload(
        text, SufficiencyDecision, node="decide_next_step", attempt=2
    )

    assert payload is None
    assert candidates == 1
    record = next(item for item in caplog.records if item.getMessage() == "JSON Schema 校验失败")
    assert record.node == "decide_next_step"
    assert record.attempt == 2
    assert record.schema == "SufficiencyDecision"
    assert "missing_information" in record.errors
