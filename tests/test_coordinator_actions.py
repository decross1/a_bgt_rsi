"""Offline tests for the constrained action space + plan validation.

These exercise the guardrail core: a valid plan passes; off-menu actions,
schema-bad args, over-budget plans, and empty/over-MAX plans are all rejected
with concrete errors and never raise. Pure module, zero deps — no LLM, no
network, no fixtures.
"""
from __future__ import annotations

from orchestrator.coordinator_actions import (
    ACTIONS,
    MAX_ACTIONS,
    known_actions,
    validate_plan,
)


def test_known_actions_returns_four_action_menu():
    menu = known_actions()
    names = {a["name"] for a in menu}
    assert names == {"run_loop_iteration", "promote_findings", "bubble_up", "noop"}
    for entry in menu:
        assert set(entry) == {"name", "description", "arg_schema", "cost"}
        # handler_ref must NOT leak into the planner-facing menu
        assert "handler_ref" not in entry
        assert isinstance(entry["description"], str) and entry["description"]
        assert isinstance(entry["arg_schema"], dict)
        assert isinstance(entry["cost"], int)


def test_valid_plan_passes_and_normalizes():
    plan = [
        {"action": "run_loop_iteration", "args": {"topic": "Vickrey auctions"}},
        {"action": "promote_findings", "args": {"max_candidates": 3}},
        {"action": "noop", "args": {"reason": "wait for human gate"}},
    ]
    res = validate_plan(plan, budget=10)
    assert res["ok"] is True
    assert res["errors"] == []
    assert [a["name"] for a in res["normalized"]] == [
        "run_loop_iteration",
        "promote_findings",
        "noop",
    ]
    # cost + handler_ref attached for the coordinator to dispatch
    assert res["normalized"][0]["cost"] == 3
    assert res["normalized"][0]["handler_ref"] == "orchestrator.nara:run_iteration"
    assert res["normalized"][0]["args"] == {"topic": "Vickrey auctions"}


def test_optional_arg_omitted_is_valid():
    # promote_findings.max_candidates is optional; bubble_up.note is optional.
    plan = [
        {"action": "promote_findings", "args": {}},
        {"action": "bubble_up", "args": {"finding_ids": ["f1", "f2"]}},
    ]
    res = validate_plan(plan, budget=10)
    assert res["ok"] is True, res["errors"]


def test_off_menu_action_rejected():
    plan = [{"action": "launch_live_trade", "args": {"size": 100}}]
    res = validate_plan(plan, budget=10)
    assert res["ok"] is False
    assert any("launch_live_trade" in e and "not in the action menu" in e for e in res["errors"])
    assert res["normalized"] == []


def test_bad_args_schema_rejected():
    # topic must be a string; an integer fails the jsonschema.
    plan = [{"action": "run_loop_iteration", "args": {"topic": 42}}]
    res = validate_plan(plan, budget=10)
    assert res["ok"] is False
    assert any("run_loop_iteration" in e and "topic" in e for e in res["errors"])


def test_missing_required_arg_rejected():
    plan = [{"action": "run_loop_iteration", "args": {}}]
    res = validate_plan(plan, budget=10)
    assert res["ok"] is False
    assert any("run_loop_iteration" in e for e in res["errors"])


def test_unknown_extra_arg_rejected():
    # additionalProperties is False — a stray arg is a malformed plan.
    plan = [{"action": "noop", "args": {"reason": "ok", "extra": 1}}]
    res = validate_plan(plan, budget=10)
    assert res["ok"] is False


def test_over_budget_rejected():
    # run_loop_iteration costs 3 each; three of them = 9 > budget 5.
    plan = [
        {"action": "run_loop_iteration", "args": {"topic": "a"}},
        {"action": "run_loop_iteration", "args": {"topic": "b"}},
        {"action": "run_loop_iteration", "args": {"topic": "c"}},
    ]
    res = validate_plan(plan, budget=5)
    assert res["ok"] is False
    assert any("exceeds budget" in e for e in res["errors"])


def test_empty_plan_rejected():
    res = validate_plan([], budget=10)
    assert res["ok"] is False
    assert any("empty" in e for e in res["errors"])


def test_over_max_actions_rejected():
    plan = [{"action": "noop", "args": {"reason": f"r{i}"}} for i in range(MAX_ACTIONS + 1)]
    res = validate_plan(plan, budget=100)
    assert res["ok"] is False
    assert any("MAX_ACTIONS" in e for e in res["errors"])


def test_non_list_plan_rejected_without_raising():
    res = validate_plan({"action": "noop"}, budget=10)
    assert res["ok"] is False
    assert any("must be a list" in e for e in res["errors"])


def test_malformed_item_rejected():
    plan = ["not a dict", {"action": "noop", "args": {"reason": "x"}}]
    res = validate_plan(plan, budget=10)
    assert res["ok"] is False
    assert any("must be an object" in e for e in res["errors"])


def test_args_not_object_rejected():
    plan = [{"action": "noop", "args": "oops"}]
    res = validate_plan(plan, budget=10)
    assert res["ok"] is False
    assert any("'args' must be an object" in e for e in res["errors"])


def test_noop_is_free_and_counts_toward_max_only():
    plan = [{"action": "noop", "args": {"reason": "idle"}}]
    res = validate_plan(plan, budget=0)
    # cost 0 noop fits budget 0
    assert res["ok"] is True, res["errors"]
    assert res["normalized"][0]["cost"] == 0


def test_actions_registry_is_the_v1_menu():
    assert set(ACTIONS) == {"run_loop_iteration", "promote_findings", "bubble_up", "noop"}
    assert ACTIONS["run_loop_iteration"]["cost"] == 3
    assert ACTIONS["promote_findings"]["cost"] == 2
    assert ACTIONS["bubble_up"]["cost"] == 1
    assert ACTIONS["noop"]["cost"] == 0
