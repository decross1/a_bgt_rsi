"""LOOP_V0 step 2 worker — hypothesize.

Given a research topic, ask Gemma to generate 1–3 candidate hypotheses
in the domain of game theory / behavioral game theory / learning in
games, then pick the most specific.

Output matches the `iteration_record.hypothesis` subschema:
- `text` — the chosen hypothesis (the most specific candidate)
- `candidates_considered` — how many candidates Gemma generated (1–3)
- `all_candidates` — every candidate, including the chosen one

The LLM call goes through `agent_wrapper.wrapper.call_sync`, which
auto-logs to `logs/calls.jsonl` with full provenance (request_id,
parent_request_id, model, usage, latency).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from agent_wrapper.wrapper import call_sync


CALLS_LOG_PATH = os.environ.get(
    "LOOP_V0_CALLS_LOG", "logs/calls.jsonl"
)


HYPOTHESIZE_SYSTEM_PROMPT = (
    "You are the HYPOTHESIZE worker in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Given a research topic in game theory, behavioral game theory, or\n"
    "learning in games, generate 1–3 candidate research hypotheses.\n"
    "Each candidate must be:\n"
    "  - **specific** — narrows the topic to a falsifiable claim\n"
    "  - **mechanistic** — names a concrete variable, condition, or comparison\n"
    "  - **testable** — could be checked against literature or a sandbox experiment\n"
    "\n"
    "After generating, pick the SINGLE candidate that's most specific\n"
    "and most directly testable. That's the 'chosen' one.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "candidates": ["<hypothesis 1>", "<hypothesis 2>", ...],\n'
    '  "chosen": "<the most specific candidate, copied verbatim from candidates>"\n'
    "}\n"
    "\n"
    "`candidates` has 1 to 3 items. `chosen` MUST be exactly one of the\n"
    "candidates (string equality)."
)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Find the first balanced JSON object in `text` and parse it.

    Gemma occasionally wraps JSON in prose or in `<channel|>` markup.
    We scan for the first `{` and find its matching `}` by counting
    braces, then try to parse that slice."""
    if not isinstance(text, str):
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _validate_payload(payload: Any) -> tuple[list[str], str | None]:
    """Pull candidates + chosen out of a parsed JSON object. Returns
    `(candidates, chosen)`. Either may be empty / None if invalid."""
    if not isinstance(payload, dict):
        return [], None
    cand_raw = payload.get("candidates")
    chosen = payload.get("chosen")
    candidates: list[str] = []
    if isinstance(cand_raw, list):
        for c in cand_raw:
            if isinstance(c, str) and c.strip():
                candidates.append(c.strip())
    candidates = candidates[:3]  # schema cap
    if not isinstance(chosen, str) or not chosen.strip():
        chosen = None
    else:
        chosen = chosen.strip()
        # Ensure chosen is among candidates (per the prompt's contract).
        # If not, fall back to using chosen as the only candidate.
        if chosen not in candidates:
            if not candidates:
                candidates = [chosen]
            else:
                # Prefer the model's chosen even when not in list — it's
                # the model's pick, after all. But also keep the list.
                candidates = [chosen] + [c for c in candidates if c != chosen][:2]
    return candidates, chosen


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

    messages = [
        {"role": "system", "content": HYPOTHESIZE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Research topic: {topic}"},
    ]

    try:
        record = call_sync(
            messages,
            temperature=0.7,
            top_p=0.95,
            max_tokens=512,
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

    completion = record.get("completion") or ""
    wrapper_rid = record.get("request_id")

    payload = _extract_json_object(completion)
    candidates, chosen = _validate_payload(payload)

    if not candidates or chosen is None:
        # Robust fallback: use the raw completion as a single candidate.
        # Marks status=passed but with an error annotation so callers can
        # decide whether to retry / surface to the human.
        text = (completion or "").strip() or "(empty completion)"
        # Strip Gemma's <channel|> markup at the start if present.
        text = re.sub(r"^\s*<\|?channel\|?>.*?(?=\S)", "", text, flags=re.DOTALL).strip()
        text = text[:2000]
        return {
            "status": "passed",
            "result": {
                "text": text,
                "candidates_considered": 1,
                "all_candidates": [text],
            },
            "errors": [
                "JSON parse fell back to raw-completion-as-hypothesis; "
                "model emitted unstructured output"
            ],
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
        "errors": [],
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
