"""终止策略与优先级测试（PRD §4.2）。"""

from __future__ import annotations

from time import monotonic
from types import SimpleNamespace

from app.agents.routing import resolve_stop_reason, route_after_decide


def _state(**overrides):
    base = dict(
        iteration=1,
        max_iterations=3,
        is_sufficient=False,
        no_new_evidence_rounds=0,
        token_used=0,
        token_budget=60000,
        timeout_seconds=120,
        started_at=monotonic(),
        stop_reason=None,
    )
    base.update(overrides)
    return base  # type: ignore[return-value]


def test_pre_stop_wins_over_sufficiency():
    state = _state(stop_reason="low_relevance", is_sufficient=True)
    assert resolve_stop_reason(state) == "low_relevance"
    assert route_after_decide(state) == "final_answer"


def test_sufficient_ends_run():
    assert resolve_stop_reason(_state(is_sufficient=True)) == "sufficient"


def test_max_iterations_before_no_new_evidence():
    state = _state(iteration=3, no_new_evidence_rounds=5)
    assert resolve_stop_reason(state, no_new_evidence_rounds=1) == "max_iterations_reached"


def test_no_new_evidence_uses_configured_threshold():
    state = _state(no_new_evidence_rounds=1)
    assert resolve_stop_reason(state, no_new_evidence_rounds=1) == "no_new_evidence"


def test_token_budget_ends_run():
    state = _state(token_used=60000, token_budget=60000)
    assert resolve_stop_reason(state) == "budget_exceeded"


def test_timeout_ends_run():
    state = _state(started_at=monotonic() - 1000, timeout_seconds=1)
    assert resolve_stop_reason(state) == "budget_exceeded"


def test_continue_to_next_round():
    assert route_after_decide(_state()) == "plan_queries"


def test_route_uses_recorded_stop_reason_only():
    state = _state(stop_reason="sufficient", is_sufficient=False)
    assert route_after_decide(state) == "final_answer"


def test_route_does_not_recompute_budget():
    state = _state(token_used=999999, token_budget=1)
    assert route_after_decide(state) == "plan_queries"


def test_settings_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.agents.routing.get_settings",
        lambda: SimpleNamespace(
            agent_max_iterations=3,
            agent_no_new_evidence_rounds=1,
            agent_token_budget=60000,
            agent_timeout_seconds=120,
        ),
    )
    state = _state(no_new_evidence_rounds=1)
    assert resolve_stop_reason(state) == "no_new_evidence"
