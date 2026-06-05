"""Step 2.5 worker — redteam_critic (pre-experiment hypothesis falsification).

Distinct from `workers/critic_loop_v0`: that worker falsifies a hypothesis
against the RETRIEVED LITERATURE. This one red-teams the HYPOTHESIS ITSELF —
before any experiment budget is spent — by asking the strongest adversarial
questions: what is the best counter-argument, what known result does the
claim contradict, is it even testable as stated.

It takes `hypothesis_text` directly (it does NOT read the iteration_cache),
so the unit is self-contained and the integrator wires it as a cheap
pre-flight gate ahead of the experiment step.

Like `critic_loop_v0` it dispatches a bounded sub-agent via
`orchestrator.subagent.run_subagent` and mirrors that worker's status
fallback ladder: a critic failure (timeout / schema_mismatch) does NOT block
the chain — it defaults to verdict "proceed". Absence of a found flaw is a
"proceed", not a "fatal_flaw".

Output shape (worker contract) carries the standard sub-agent observability
fields under `result`:
  - `subagent_turns_used`, `subagent_wall_seconds`, `subagent_status`,
    `subagent_backend`, `subagent_model`.
"""
from __future__ import annotations

import os
from typing import Any

from agent_wrapper.backends import get_backend
from agent_wrapper.cleanup import strip_channel_markup
from agent_wrapper.wrapper import DEFAULT_BACKEND
from orchestrator.subagent import (
    SubAgentBudget,
    SubAgentResult,
    run_subagent,
)


ALLOWED_VERDICTS = ("fatal_flaw", "proceed")


REDTEAM_AGENT_SYSTEM_PROMPT = (
    "You are the RED-TEAM critic in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Your job: attack a research hypothesis BEFORE any experiment budget is\n"
    "spent on it. Find the reason it should NOT be tested. Ask:\n"
    "  - What is the STRONGEST counter-argument to this claim?\n"
    "  - What KNOWN result (theorem, established finding) does it contradict?\n"
    "  - Is it even TESTABLE as stated — or is it vague, circular, or\n"
    "    unfalsifiable?\n"
    "\n"
    "Do NOT run experiments. Do NOT be charitable for its own sake. But be\n"
    "intellectually honest: a hypothesis with no fatal flaw should PROCEED.\n"
    "A fatal flaw means the claim is logically incoherent, contradicts a\n"
    "well-established result, or cannot be tested as phrased — not merely\n"
    "that it is uncertain or unproven (uncertainty is why we experiment).\n"
    "\n"
    "Return ONE of two verdicts:\n"
    '  - "fatal_flaw" — the hypothesis should NOT be tested as stated;\n'
    "                    give the killer critique and a suggested revision.\n"
    '  - "proceed"    — no fatal flaw found; the experiment budget is\n'
    "                    justified.\n"
    "\n"
    "When you've judged, emit a FINAL assistant message that is STRICT JSON,\n"
    "nothing else — no prose, no markdown fences, no channel markers. Schema:\n"
    "{\n"
    '  "verdict": "fatal_flaw" | "proceed",\n'
    '  "critique": "<2-4 sentences: the strongest attack you could mount>",\n'
    '  "suggested_revision": "<a reworded testable hypothesis>" | null,\n'
    '  "confidence": <float 0.0-1.0, your confidence in the verdict>\n'
    "}\n"
    "\n"
    '`suggested_revision` is non-null ONLY for "fatal_flaw".'
)


_REDTEAM_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "critique", "confidence"],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": list(ALLOWED_VERDICTS),
        },
        "critique": {"type": "string"},
        "suggested_revision": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "additionalProperties": True,
}


def _post_validate(payload: dict) -> tuple[dict, list[str]]:
    """Enforce cross-field invariants the schema can't:
    - suggested_revision must be None for the "proceed" verdict
    - confidence clamped to [0, 1]
    The sub-agent's schema validation already guarantees
    verdict ∈ ALLOWED_VERDICTS."""
    warnings: list[str] = []
    verdict = payload.get("verdict")
    critique = strip_channel_markup(payload.get("critique") or "")[:2000]
    revision = payload.get("suggested_revision")
    if isinstance(revision, str):
        revision = strip_channel_markup(revision).strip()[:2000] or None
    elif revision is not None:
        warnings.append("suggested_revision not a string or null; nulling")
        revision = None
    if verdict == "proceed" and revision is not None:
        warnings.append("suggested_revision set on verdict='proceed'; nulling per schema")
        revision = None
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)):
        warnings.append("confidence not a number; defaulting to 0.5")
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))
    return (
        {
            "verdict": verdict,
            "critique": critique,
            "suggested_revision": revision,
            "confidence": confidence,
        },
        warnings,
    )


def _proceed_fallback(reason: str, observability: dict) -> dict:
    """Default verdict when the sub-agent fails — a critic failure does
    NOT block the chain. Absence of a found flaw = proceed."""
    return {
        "verdict": "proceed",
        "critique": reason,
        "suggested_revision": None,
        "confidence": 0.0,
        **observability,
    }


def redteam_critic(
    hypothesis_text: str,
    iteration_id: str,
    *,
    parent_request_id: str | None = None,
    budget: SubAgentBudget | None = None,
) -> dict[str, Any]:
    """Red-team the hypothesis itself via a bounded sub-agent.

    Takes `hypothesis_text` directly (does NOT read the iteration_cache).
    `iteration_id` is accepted for chain/log correlation only.

    Returns:
    ```
    {
        "status": "passed" | "error",
        "result": {
            "verdict": "fatal_flaw" | "proceed",
            "critique": str,
            "suggested_revision": str | None,
            "confidence": float,
            "subagent_turns_used": int,
            "subagent_wall_seconds": float,
            "subagent_status": "passed" | "timeout" | "schema_mismatch" | "error",
            "subagent_backend": str,
            "subagent_model": str,
        } | None,
        "errors": [str, ...],
        "wrapper_request_id": str | None,
        "parent_request_id": str | None,
    }
    ```
    """
    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        return {
            "status": "error",
            "result": None,
            "errors": ["hypothesis_text is required and must be non-empty"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    if not isinstance(iteration_id, str) or not iteration_id.strip():
        return {
            "status": "error",
            "result": None,
            "errors": ["iteration_id is required and must be a non-empty string"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }

    user_prompt = (
        f"Hypothesis to red-team:\n{hypothesis_text.strip()}\n\n"
        "Mount your strongest attack, then emit the final JSON verdict."
    )

    # Inherit the CRITIC_BACKEND env override if present (same operational
    # lever critic_loop_v0 uses), else the orchestrator default backend.
    critic_backend = os.environ.get("CRITIC_BACKEND") or None
    resolved_be = get_backend(critic_backend or DEFAULT_BACKEND)

    sa_result: SubAgentResult = run_subagent(
        name="redteam_critic",
        system_prompt=REDTEAM_AGENT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        expected_output_schema=_REDTEAM_OUTPUT_SCHEMA,
        budget=budget or SubAgentBudget(max_turns=3, max_wall_seconds=45.0),
        parent_request_id=parent_request_id,
        backend=critic_backend,
    )

    observability = {
        "subagent_turns_used":   sa_result.turns_used,
        "subagent_wall_seconds": round(sa_result.wall_seconds, 3),
        "subagent_status":       sa_result.status,
        "subagent_backend":      resolved_be.name,
        "subagent_model":        resolved_be.default_model,
    }
    last_rid = sa_result.wrapper_call_ids[-1] if sa_result.wrapper_call_ids else None

    if sa_result.status == "passed":
        validated, warnings = _post_validate(sa_result.result or {})
        validated.update(observability)
        return {
            "status": "passed",
            "result": validated,
            "errors": warnings,
            "wrapper_request_id": last_rid,
            "parent_request_id": parent_request_id,
        }

    if sa_result.status == "schema_mismatch":
        raw = sa_result.result if isinstance(sa_result.result, dict) else None
        fallback = _proceed_fallback(
            "(sub-agent emitted schema-mismatched output; defaulting to proceed) "
            + str(raw)[:500],
            observability,
        )
        return {
            "status": "passed",
            "result": fallback,
            "errors": ["sub-agent schema mismatch; verdict defaulted to 'proceed'"]
                       + sa_result.errors,
            "wrapper_request_id": last_rid,
            "parent_request_id": parent_request_id,
        }

    if sa_result.status == "timeout":
        fallback = _proceed_fallback(
            f"(sub-agent budget exceeded after {sa_result.turns_used} turns; "
            "defaulting to proceed)",
            observability,
        )
        return {
            "status": "passed",
            "result": fallback,
            "errors": ["sub-agent timeout; verdict defaulted to 'proceed'"]
                       + sa_result.errors,
            "wrapper_request_id": last_rid,
            "parent_request_id": parent_request_id,
        }

    # sa_result.status == "error"
    return {
        "status": "error",
        "result": None,
        "errors": sa_result.errors,
        "wrapper_request_id": last_rid,
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    import json
    hyp = (
        "In finitely repeated Prisoner's Dilemma with known horizon, "
        "rational players cooperate on every round."
    )
    out = redteam_critic(hyp, "smoke-redteam-critic", parent_request_id="smoke")
    print(json.dumps(out, indent=2))
