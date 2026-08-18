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
`orchestrator.subagent.run_subagent`. Failure polarity (D-075 R1b): a
critic failure (schema_mismatch / timeout / sub-agent error) yields verdict
"unscored" — it does NOT block the chain, but it is never fail-opened into
a "proceed" either. Downstream, "unscored" behaves exactly like an ABSENT
redteam signal: acceptable at L1 in the evidence ladder, blocks L4 (which
requires verdict == "proceed"), and never kills (which requires
"fatal_flaw"). Only the sub-agent itself can award "proceed" or
"fatal_flaw".

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


# What the SUB-AGENT may emit. The worker synthesizes a third verdict,
# UNSCORED_VERDICT, on every sub-agent failure path (D-075 R1b). It is
# deliberately NOT part of the sub-agent's output schema — a parse
# accident can never mint it, and a parse accident can never mint
# "proceed" any more either.
ALLOWED_VERDICTS = ("fatal_flaw", "proceed")
UNSCORED_VERDICT = "unscored"


# R1a adoption 2026-08-18: the calibration battery (bench/redteam_cal/,
# prereg experiments/PREREG_redteam_cal_2026-08-18.md, LOCKED) elected the
# gemma-revised arm — bars 9/12 caught, 0/12 false-condemned, 0 unscored;
# production (old prompt) condemned 18/19 parsed and failed bars 1+3. The
# swap is ratified by the LOCK COMMIT per the prereg adoption rule. Text
# below is byte-identical to the winning arm's prompt (sha256 asserted at
# swap time against the run artifact).
REDTEAM_AGENT_SYSTEM_PROMPT = (
    "You are the RED-TEAM critic in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Your job: attack a research hypothesis BEFORE any experiment budget is\n"
    "spent on it. Mount the strongest attack you can:\n"
    "  - What is the STRONGEST counter-argument to this claim?\n"
    "  - What KNOWN result (theorem, established finding) does it contradict?\n"
    "  - Is it even TESTABLE as stated — or is it vague, circular, or\n"
    "    unfalsifiable?\n"
    "\n"
    "Then apply the ONE decision rule that separates the verdicts:\n"
    "\n"
    '"fatal_flaw" means the claim CANNOT be rescued by ANY reasonable\n'
    "experimental design. The defect lives in the claim itself, not in the\n"
    "experiment someone might run on it. That standard is met when, and only\n"
    "when, at least one of these holds:\n"
    "  - it is logically incoherent, self-contradictory, or circular (it\n"
    "    asserts nothing, or its cause is defined as its effect);\n"
    "  - it contradicts a well-established theorem or finding, so the\n"
    "    predicted outcome cannot occur as stated;\n"
    "  - it is unfalsifiable as stated — every possible observation is\n"
    "    consistent with it, or it turns on a construct that is unmeasurable\n"
    "    in principle;\n"
    "  - its central attribution cannot be identified by ANY design, because\n"
    "    every available manipulation moves the claimed mechanism and its\n"
    "    stated alternative together.\n"
    "\n"
    "A FIXABLE weakness is NOT a fatal flaw. If a reasonable design choice —\n"
    "a control condition, an ablation, a sharper operationalization, a\n"
    'stated measurement — would rescue the claim, the verdict is "proceed",\n'
    "and you MUST name that weakness and the design step that addresses it\n"
    "in `critique`. Missing controls, definable-but-undefined details,\n"
    "uncertain truth, likely-false predictions, interpretive ambiguity, and\n"
    "lack of novelty are ALL proceed-class. A claim that looks wrong but is\n"
    "cleanly testable PROCEEDS — the experiment is how it dies. Uncertainty\n"
    "is why we experiment.\n"
    "\n"
    "Do NOT run experiments. Do NOT be charitable for its own sake. But be\n"
    "intellectually honest in both directions: condemning a rescuable claim\n"
    "wastes a hypothesis just as surely as testing an unrescuable one wastes\n"
    "the budget.\n"
    "\n"
    "Return ONE of two verdicts:\n"
    '  - "fatal_flaw" — unrescuable by any reasonable design; give the\n'
    "                    killer critique and a suggested revision.\n"
    '  - "proceed"    — testable as stated, or rescuable by a reasonable\n'
    "                    design; name the strongest remaining weakness in\n"
    "                    `critique`.\n"
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


def _unscored_fallback(reason: str, observability: dict) -> dict:
    """Verdict when the sub-agent fails (D-075 R1b). A critic failure does
    NOT block the chain, but it never counts as a real "proceed" either:
    "unscored" behaves as an ABSENT redteam signal downstream — L1-eligible
    in the evidence ladder, never L4 (requires "proceed"), never a kill
    (requires "fatal_flaw")."""
    return {
        "verdict": UNSCORED_VERDICT,
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
        "status": "passed" | "error",   # "error" = invalid inputs only;
                                        # every sub-agent failure path
                                        # returns "passed" + "unscored"
        "result": {
            "verdict": "fatal_flaw" | "proceed" | "unscored",
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
        fallback = _unscored_fallback(
            "(sub-agent emitted schema-mismatched output; verdict unscored) "
            + str(raw)[:500],
            observability,
        )
        return {
            "status": "passed",
            "result": fallback,
            "errors": ["sub-agent schema mismatch; verdict 'unscored' "
                       "(D-075 R1b: never fail-open to 'proceed')"]
                       + sa_result.errors,
            "wrapper_request_id": last_rid,
            "parent_request_id": parent_request_id,
        }

    if sa_result.status == "timeout":
        fallback = _unscored_fallback(
            f"(sub-agent budget exceeded after {sa_result.turns_used} turns; "
            "verdict unscored)",
            observability,
        )
        return {
            "status": "passed",
            "result": fallback,
            "errors": ["sub-agent timeout; verdict 'unscored' "
                       "(D-075 R1b: never fail-open to 'proceed')"]
                       + sa_result.errors,
            "wrapper_request_id": last_rid,
            "parent_request_id": parent_request_id,
        }

    # sa_result.status == "error" — the dispatch itself failed (backend
    # down, transport error). Same polarity as the other failure paths
    # (D-075 R1b): the chain proceeds on "unscored"; the honest detail
    # rides in subagent_status == "error" plus the errors list.
    fallback = _unscored_fallback(
        "(sub-agent dispatch error; verdict unscored) "
        + "; ".join(sa_result.errors)[:500],
        observability,
    )
    return {
        "status": "passed",
        "result": fallback,
        "errors": ["sub-agent error; verdict 'unscored' "
                   "(D-075 R1b: never fail-open to 'proceed')"]
                   + sa_result.errors,
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
