"""Slice-Alpha coordinator: the CONSTRAINED ACTION SPACE + plan validation.

This is the guardrail core of the coordinator-brain proof. The planner (an
LLM) is *never* trusted to free-form sequence the apparatus. Instead it may
only choose from a fixed, validated menu of cheap/safe actions. A plan that
names an off-menu action, supplies malformed args, exceeds the budget, or is
empty/over-length is REJECTED — it is never handed to a handler.

That rejection-and-replan loop is what prevents Gemma from mis-sequencing the
steps the hardcoded `orchestrator.nara.run_iteration` currently keeps in a
fixed order.

This module is intentionally pure: just the menu and the validator. It has no
dependency on the heavy pieces it gates. `handler_ref` is a *string* pointer
(e.g. ``"orchestrator.nara:run_iteration"``) that the coordinator resolves
when it wires handlers; keeping it a string here means the validator imports
nothing and tests run offline with zero deps. The handler dispatch table lives
in the coordinator, not here.
"""
from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator

# Cap on plan length, independent of budget. A plan longer than this is
# rejected outright — a runaway planner emitting hundreds of noops should not
# even reach the budget check.
MAX_ACTIONS = 6


def _obj_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """A closed object schema: only the declared properties, no extras."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


# The fixed v1 menu. Cheap/safe only — NO live experiment runs, NO trades.
# Each entry: arg_schema (jsonschema), description, cost (budget units),
# handler_ref (string pointer the coordinator resolves to a callable).
ACTIONS: dict[str, dict[str, Any]] = {
    "run_loop_iteration": {
        "description": (
            "Run one LOOP_V0 iteration (hypothesize -> critique -> ... ) on a "
            "topic via orchestrator.nara.run_iteration."
        ),
        "cost": 3,
        "arg_schema": _obj_schema(
            {"topic": {"type": "string", "minLength": 1}},
            ["topic"],
        ),
        "handler_ref": "orchestrator.nara:run_iteration",
    },
    "promote_findings": {
        "description": (
            "Promote vetted candidate findings via "
            "orchestrator.finding_promotion.promote_findings."
        ),
        "cost": 2,
        "arg_schema": _obj_schema(
            {"max_candidates": {"type": "integer", "minimum": 1}},
            [],
        ),
        "handler_ref": "orchestrator.finding_promotion:promote_findings",
    },
    "bubble_up": {
        "description": (
            "Surface specific finding ids to the human for review, with an "
            "optional note."
        ),
        "cost": 1,
        "arg_schema": _obj_schema(
            {
                "finding_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                },
                "note": {"type": "string"},
            },
            ["finding_ids"],
        ),
        "handler_ref": "orchestrator.coordinator:handle_bubble_up",
    },
    "noop": {
        "description": "Do nothing this cycle; record a reason why.",
        "cost": 0,
        "arg_schema": _obj_schema(
            {"reason": {"type": "string", "minLength": 1}},
            ["reason"],
        ),
        "handler_ref": "orchestrator.coordinator:handle_noop",
    },
}


def known_actions() -> list[dict[str, Any]]:
    """The menu, for injecting into the planner prompt.

    Returns one dict per action with name/description/arg_schema/cost. The
    handler_ref is intentionally omitted — the planner does not need (and
    should not see) the wiring."""
    return [
        {
            "name": name,
            "description": spec["description"],
            "arg_schema": spec["arg_schema"],
            "cost": spec["cost"],
        }
        for name, spec in ACTIONS.items()
    ]


def validate_plan(plan: Any, *, budget: int) -> dict[str, Any]:
    """Validate an LLM-proposed plan against the constrained action space.

    A plan is a list of ``{"action": str, "args": dict}`` items. The plan is
    REJECTED (ok=False) if any of:
      - it is not a list, is empty, or has more than MAX_ACTIONS items;
      - an item is malformed (not a dict / missing keys / wrong types);
      - an action name is not in ACTIONS;
      - the action's args fail its jsonschema;
      - the total cost exceeds `budget`.

    This never raises. It returns concrete, per-action error strings so the
    coordinator can feed them back into a bounded replan.

    Returns ``{"ok": bool, "errors": [str], "normalized": [action]}`` where
    each normalized action is ``{"name", "args", "cost", "handler_ref"}``.
    Normalized is only populated when ok is True.
    """
    errors: list[str] = []

    if not isinstance(plan, list):
        return {"ok": False, "errors": [f"plan must be a list, got {type(plan).__name__}"], "normalized": []}
    if len(plan) == 0:
        return {"ok": False, "errors": ["plan is empty"], "normalized": []}
    if len(plan) > MAX_ACTIONS:
        errors.append(f"plan has {len(plan)} actions, exceeds MAX_ACTIONS={MAX_ACTIONS}")

    normalized: list[dict[str, Any]] = []
    total_cost = 0

    for idx, item in enumerate(plan):
        if not isinstance(item, dict):
            errors.append(f"action[{idx}]: must be an object, got {type(item).__name__}")
            continue
        name = item.get("action")
        if not isinstance(name, str) or not name:
            errors.append(f"action[{idx}]: missing or non-string 'action' name")
            continue
        if name not in ACTIONS:
            errors.append(f"action[{idx}]: '{name}' is not in the action menu {sorted(ACTIONS)}")
            continue

        spec = ACTIONS[name]
        args = item.get("args", {})
        if not isinstance(args, dict):
            errors.append(f"action[{idx}] ('{name}'): 'args' must be an object, got {type(args).__name__}")
            continue

        validator = Draft7Validator(spec["arg_schema"])
        schema_errs = sorted(validator.iter_errors(args), key=lambda e: list(e.path))
        if schema_errs:
            for e in schema_errs:
                loc = "/".join(str(p) for p in e.path) or "(root)"
                errors.append(f"action[{idx}] ('{name}'): args {loc}: {e.message}")
            continue

        total_cost += spec["cost"]
        normalized.append({
            "name": name,
            "args": args,
            "cost": spec["cost"],
            "handler_ref": spec["handler_ref"],
        })

    if total_cost > budget:
        errors.append(f"plan cost {total_cost} exceeds budget {budget}")

    if errors:
        return {"ok": False, "errors": errors, "normalized": []}
    return {"ok": True, "errors": [], "normalized": normalized}
