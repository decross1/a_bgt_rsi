"""LOOP_V0 step 2 worker — hypothesize.

Given a research topic, ask the configured generator to produce 1–3 candidate hypotheses
in the domain of game theory / behavioral game theory / learning in
games, then pick the most specific.

Output matches the `iteration_record.hypothesis` subschema:
- `text` — the chosen hypothesis (the most specific candidate)
- `candidates_considered` — how many candidates the generator returned (1–3)
- `all_candidates` — every candidate, including the chosen one

The LLM call goes through `agent_wrapper.wrapper.call_sync`, which
auto-logs to `logs/calls.jsonl` with full provenance (request_id,
parent_request_id, model, usage, latency).
"""
from __future__ import annotations

import json
import os
from typing import Any

from agent_wrapper.wrapper import call_sync

CALLS_LOG_PATH = os.environ.get(
    "LOOP_V0_CALLS_LOG", "logs/calls.jsonl"
)

_MAX_TOKENS = 1024
_REPAIR_MAX_TOKENS = 1024
_REASONING_CHANNEL_MARKERS = (
    "<|channel",
    "<channel|>",
    "<think>",
    "</think>",
    "<analysis>",
    "</analysis>",
    "[analysis]",
    "[/analysis]",
)
_EXPECTED_KEYS = {"candidates", "chosen"}


class _DuplicateKey(ValueError):
    pass


class _NonFinite(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise _NonFinite(value)


HYPOTHESIZE_SYSTEM_PROMPT = (
    "You are the HYPOTHESIZE worker in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Generate 1–3 research hypotheses in game theory, behavioral game\n"
    "theory, or learning in games. Delegation, liquid democracy, social\n"
    "choice and sortition are also within the research program.\n"
    "The input may be an unvetted machine-selected paper title, not a\n"
    "human-authored claim. Check what the question actually studies.\n"
    "Every candidate must concern strategic interaction or collective\n"
    "choice: identify the decision-makers, their actions or votes, the\n"
    "incentives or preference-aggregation rule, and a measurable outcome\n"
    "or formally checkable property.\n"
    "Collaborative ML accuracy, training throughput, distributed-system\n"
    "performance and software quality alone are outside this scope.\n"
    "Calling components 'players' or adding 'cooperation', 'payoff' or\n"
    "'equilibrium' does not turn an engineering claim into game theory.\n"
    "If the input is outside scope, formulate a NEW concrete question\n"
    "about a game or collective-choice mechanism instead of preserving\n"
    "that claim. Do not imply that an input paper studied or supports\n"
    "this new question. A proposed experiment is not an observed result.\n"
    "Each candidate must be:\n"
    "  - **specific** — narrows the topic to a falsifiable claim\n"
    "  - **mechanistic** — names a concrete variable, condition, or comparison\n"
    "  - **testable** — could be checked against literature or a sandbox experiment\n"
    "  - **concise** — no more than 80 words and 1200 characters\n"
    "\n"
    "When the topic is IN SCOPE and already a sharp, falsifiable claim with a\n"
    "stated mechanism and fits those bounds, include it VERBATIM as one of the candidates — do\n"
    "not paraphrase or 'fix' an in-scope claim that's already specific.\n"
    "Preserve its stated mechanism, including deliberately testable errors.\n"
    "\n"
    "After generating, pick the SINGLE candidate that engages most\n"
    "directly with a CONCRETE MECHANISM — a named causal pathway, a\n"
    "named modulator, or a comparison between specific conditions.\n"
    "Prefer mechanistic specificity over linguistic specificity. Example:\n"
    "  • Candidate A: 'X happens faster under noisy conditions.'\n"
    "  • Candidate B: 'X happens faster under noisy conditions because\n"
    "    asymmetric Bayesian updating inflates the posterior probability\n"
    "    of bad-type opponents.'\n"
    "Both are testable; B is sharper because it names the mechanism.\n"
    "Choose B.\n"
    "\n"
    "If the topic is IN SCOPE, verbatim among the candidates and already\n"
    "engages a concrete mechanism, prefer it. Specificity alone never\n"
    "overrides the research scope.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "candidates": ["<hypothesis 1>", "<hypothesis 2>", ...],\n'
    '  "chosen": "<the most mechanism-engaged candidate, copied verbatim from candidates>"\n'
    "}\n"
    "\n"
    "`candidates` has 1 to 3 items. `chosen` MUST be exactly one of the\n"
    "candidates (string equality)."
)


def _validate_record(record: Any) -> tuple[list[str] | None, str | None, str | None]:
    """Validate one complete wrapper record without repairing model output.

    Returns ``(candidates, chosen, diagnostic)``.  The diagnostic starts with
    a stable failure code so callers can distinguish transport truncation,
    protocol leakage, and field-contract errors.  Invalid visible text is
    never promoted into a scientific hypothesis.
    """
    if not isinstance(record, dict):
        return None, None, "wrapper_record: wrapper returned a non-object record"

    finish_reason = record.get("finish_reason")
    if finish_reason == "length":
        return None, None, "truncated_completion: generation reached its output limit"
    if finish_reason != "stop":
        return (
            None,
            None,
            ("incomplete_completion: wrapper did not report finish_reason='stop' "
             f"(got {finish_reason!r})"),
        )

    completion = record.get("completion")
    if not isinstance(completion, str):
        return None, None, "completion_not_text: visible completion is not text"
    if not completion.strip():
        return None, None, "empty_completion: visible completion is empty"

    # A complete Markdown JSON fence is a harmless transport envelope.  Strip
    # exactly one whole envelope, but never scan prose for an embedded object.
    # This still rejects partial fences, surrounding prose, and multiple values.
    candidate_text = completion.strip()
    if candidate_text.startswith("```json\n") and candidate_text.endswith("\n```"):
        candidate_text = candidate_text[len("```json\n"):-len("\n```")]

    try:
        payload = json.loads(
            candidate_text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except _DuplicateKey as exc:
        return None, None, f"duplicate_json_key: duplicate object key {exc.args[0]!r}"
    except _NonFinite:
        return None, None, "non_finite_json: JSON contains NaN or infinity"
    except json.JSONDecodeError as exc:
        lowered = candidate_text.casefold()
        if any(marker in lowered for marker in _REASONING_CHANNEL_MARKERS):
            return (
                None,
                None,
                ("reasoning_channel_leakage: visible completion contains "
                 "reasoning/channel protocol markup outside valid JSON"),
            )
        return (
            None,
            None,
            ("malformed_json: visible completion is not exactly one JSON "
             f"object (line {exc.lineno} column {exc.colno})"),
        )

    if not isinstance(payload, dict) or set(payload) != _EXPECTED_KEYS:
        return None, None, "field_schema: response must have exactly candidates and chosen"

    candidate_value = payload["candidates"]
    chosen = payload["chosen"]
    if not isinstance(candidate_value, list) or not 1 <= len(candidate_value) <= 3:
        return None, None, "field_schema: candidates must contain 1 to 3 items"
    if any(not isinstance(item, str) or not item.strip() for item in candidate_value):
        return None, None, "field_schema: every candidate must be a non-empty string"
    candidates = [item.strip() for item in candidate_value]
    if any(item.casefold().startswith(_REASONING_CHANNEL_MARKERS) for item in candidates):
        return None, None, "reasoning_channel_leakage: candidate starts with channel markup"
    if any(item.startswith(("{", "[", "```")) for item in candidates):
        return None, None, "field_schema: candidate is a structured envelope rather than a claim"
    if any(len(item.split()) > 80 or len(item) > 1200 for item in candidates):
        return None, None, "field_schema: candidates must fit 80 words and 1200 characters"
    if len(set(candidates)) != len(candidates):
        return None, None, "field_schema: candidates must be distinct"
    if not isinstance(chosen, str) or not chosen.strip():
        return None, None, "field_schema: chosen must be a non-empty string"
    chosen = chosen.strip()
    if chosen not in candidates:
        return (
            None,
            None,
            "field_schema: chosen must exactly equal one candidate",
        )
    return candidates, chosen, None


def _messages(topic: str, *, repair_code: str | None = None) -> list[dict[str, str]]:
    messages = [
        {"role": "system", "content": HYPOTHESIZE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Research topic: {topic}"},
    ]
    if repair_code is not None:
        messages.append(
            {
                "role": "user",
                "content": (
                    "The previous attempt failed the machine-readable response "
                    f"contract ({repair_code}). Retry once from the research topic. "
                    "Return exactly one JSON object with only `candidates` and "
                    "`chosen`; do not repeat or discuss the previous response."
                ),
            }
        )
    return messages


def _failure_code(diagnostic: str) -> str:
    return diagnostic.split(":", 1)[0]


def hypothesize(
    topic: str,
    *,
    parent_request_id: str | None = None,
    log_path: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Generate 1–3 hypothesis candidates from a topic; pick the most specific.

    Returns worker-shaped:
    ```
    {
        "status": "passed" | "error",
        "result": {
            "text": str,                          # the chosen hypothesis
            "candidates_considered": int,         # len(all_candidates), 1..3
            "all_candidates": list[str],
        } | None,
        "errors": [str, ...],
        "wrapper_request_id": str | None,         # for chain reconstruction
        "parent_request_id": str | None,
    }
    ```
    """
    if not isinstance(topic, str) or not topic.strip():
        return {
            "status": "error",
            "result": None,
            "errors": ["topic is required and must be non-empty"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    topic = topic.strip()
    log_path = log_path or CALLS_LOG_PATH

    # Evaluate-as-stated bypass: when HYPOTHESIZE_AS_STATED is truthy,
    # skip the LLM call entirely and return the topic verbatim as the
    # chosen hypothesis. Use this when testing a specific claim end-to-end
    # without hypothesize's rewrite step (e.g., a deliberately-wrong
    # claim where the rewrite would sanitize the wrongness — see D-036
    # Topic 3 diagnosis). Operational toggle, no code change required.
    if (os.environ.get("HYPOTHESIZE_AS_STATED") or "").strip().lower() in (
        "1", "true", "yes", "on"
    ):
        return {
            "status": "passed",
            "result": {
                "text": topic,
                "candidates_considered": 1,
                "all_candidates": [topic],
            },
            "errors": ["(HYPOTHESIZE_AS_STATED set; LLM rewrite bypassed; topic returned verbatim)"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }

    try:
        record = call_sync(
            _messages(topic),
            temperature=0.7,
            top_p=0.95,
            max_tokens=_MAX_TOKENS,
            caller_tag="hypothesize",
            parent_request_id=parent_request_id,
            log_path=log_path,
            model=model,
        )
    except Exception as exc:
        return {
            "status": "error",
            "result": None,
            "errors": [f"wrapper.call_sync failed: {type(exc).__name__}: {exc}"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }

    wrapper_rid = record.get("request_id") if isinstance(record, dict) else None
    candidates, chosen, diagnostic = _validate_record(record)
    initial_diagnostic = diagnostic

    if diagnostic is not None:
        # One fresh repair attempt is intentionally bounded.  Do not feed the
        # malformed response back to the model: the topic and stable failure
        # code are sufficient, and treating model output as a new instruction
        # would blur the protocol boundary.
        try:
            repair = call_sync(
                _messages(topic, repair_code=_failure_code(diagnostic)),
                temperature=0.2,
                top_p=0.9,
                max_tokens=_REPAIR_MAX_TOKENS,
                caller_tag="hypothesize_repair",
                parent_request_id=(wrapper_rid or parent_request_id),
                log_path=log_path,
                model=model,
            )
        except Exception as exc:  # noqa: BLE001 — worker boundary reports failed repair without admitting output
            return {
                "status": "error",
                "result": None,
                "errors": [
                    f"initial structured output rejected: {diagnostic}",
                    ("bounded repair call failed: "
                     f"{type(exc).__name__}: {exc}"),
                ],
                "wrapper_request_id": wrapper_rid,
                "parent_request_id": parent_request_id,
            }

        repair_rid = repair.get("request_id") if isinstance(repair, dict) else None
        wrapper_rid = repair_rid or wrapper_rid
        candidates, chosen, diagnostic = _validate_record(repair)
        if diagnostic is not None:
            return {
                "status": "error",
                "result": None,
                "errors": [
                    f"initial structured output rejected: {initial_diagnostic}",
                    f"bounded repair output rejected: {diagnostic}",
                ],
                "wrapper_request_id": wrapper_rid,
                "parent_request_id": parent_request_id,
            }

    if candidates is None or chosen is None:
        # Defensive invariant: every successful validation supplies both.
        return {
            "status": "error",
            "result": None,
            "errors": ["internal validation error: accepted output has no candidate"],
            "wrapper_request_id": wrapper_rid,
            "parent_request_id": parent_request_id,
        }

    return {
        "status": "passed",
        "result": {
            "text": chosen,
            "candidates_considered": len(candidates),
            "all_candidates": candidates,
        },
        "errors": (
            [f"initial structured output rejected and repaired: {initial_diagnostic}"]
            if initial_diagnostic is not None
            else []
        ),
        "wrapper_request_id": wrapper_rid,
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke: `env -u MOCK_LLM ./.venv-chroma/bin/python -m workers.hypothesize`
    out = hypothesize(
        "Cooperation rates in repeated Prisoner's Dilemma between LLM agents",
        parent_request_id="smoke",
    )
    print(json.dumps(out, indent=2))
