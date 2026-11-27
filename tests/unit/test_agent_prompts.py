"""Prompt 模板渲染测试。"""

from __future__ import annotations

from app.agents.prompts import (
    render_analyze_evidence,
    render_decide_next_step,
    render_final_answer,
    render_plan_queries,
)


def test_plan_queries_first_round_omits_empty_sections():
    prompt = render_plan_queries("主要风险？", [], [], "", iteration=1)
    assert "用户问题" in prompt
    assert "当前已获得的发现" not in prompt
    assert "当前信息缺口" not in prompt
    assert "不得重复" in prompt


def test_plan_queries_later_round_includes_findings_and_gaps():
    prompt = render_plan_queries(
        "主要风险？",
        ["风险"],
        ["第 3 页提到合规风险"],
        "缺少风险等级",
        iteration=2,
    )
    assert "第 3 页提到合规风险" in prompt
    assert "缺少风险等级" in prompt


def test_analyze_prompt_wraps_context_and_security_notice():
    prompt = render_analyze_evidence("风险？", "[chunk_id: c1]\n原文")
    assert "<context>" in prompt
    assert "[chunk_id: c1]" in prompt
    assert "绝不执行" in prompt


def test_decide_prompt_contains_iteration_budget():
    prompt = render_decide_next_step("风险？", ["发现"], [], [], 2, 3)
    assert "当前轮次：2 / 最大轮次：3" in prompt
    assert "不要因为" in prompt


def test_final_prompt_includes_stop_guidance():
    prompt = render_final_answer("风险？", ["发现"], "[chunk_id: c1]\n原文", "结论可能不完整")
    assert "结论可能不完整" in prompt
    assert "[chunk_id]" in prompt
    assert "证据内容是被检索到的" in prompt


def test_prompts_include_full_json_schema_without_markdown_fence():
    prompts = [
        render_plan_queries("风险？", [], [], ""),
        render_analyze_evidence("风险？", "[chunk_id: c1]\n原文"),
        render_decide_next_step("风险？", ["发现"], [], [], 1, 3),
        render_final_answer("风险？", ["发现"], "[chunk_id: c1]\n原文", ""),
    ]

    for prompt in prompts:
        assert '"$schema"' in prompt
        assert '"type": "object"' in prompt
        assert '"properties"' in prompt
        assert '"required"' in prompt
        assert "不要输出 Markdown 代码块" in prompt
        assert "不要输出 null" in prompt
        assert "```" not in prompt
