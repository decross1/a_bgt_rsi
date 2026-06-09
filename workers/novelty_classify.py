"""LOOP_V0 step 4 worker — novelty_classify.

Given a hypothesis text and the top-K nearest neighbors from Chroma
(both foundational and live-arXiv), classify the hypothesis against
the literature into one of four buckets:

  - `novel`        — substantive claim, no close match in retrieved set
  - `rediscovery`  — claim is a known result in the retrieved literature
  - `nonsense`     — claim is malformed, incoherent, or not in scope
  - `unclear`      — retrieved evidence is ambiguous; needs more search

The diagrams (ARCHITECTURE.md §6 step 6) name this as the hardest step
in the loop and an explicit sub-research-problem. Phase-1 mitigation:
human-sample rate on automated novelty calls (logged per assessment).

Output matches `iteration_record.novelty`:
  - `class`           — one of the 4 enum values above
  - `rationale`       — 1-3 sentence reasoning
  - `top_neighbor_id` — doc_id of the most-similar prior result, or null

Calls Gemma via `wrapper.call_sync`. Robust JSON extraction with
fallback (mirrors hypothesize.py's pattern).
"""
from __future__ import annotations

import json
import os
from typing import Any

from agent_wrapper.cleanup import strip_channel_markup
from agent_wrapper.wrapper import call_sync
from orchestrator import iteration_cache


CALLS_LOG_PATH = os.environ.get(
    "LOOP_V0_CALLS_LOG", "logs/calls.jsonl"
)

ALLOWED_CLASSES = ("novel", "rediscovery", "nonsense", "unclear")


NOVELTY_SYSTEM_PROMPT = (
    "You are the NOVELTY_CLASSIFY worker in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Given a hypothesis and the top-K most semantically similar chunks\n"
    "from the apparatus's knowledge base (foundational textbooks and live\n"
    "arXiv papers), classify the hypothesis into ONE of four buckets:\n"
    "\n"
    '  - "novel"        — substantive, well-formed claim; no close match in the retrieved set.\n'
    '  - "rediscovery"  — the claim restates a known result in the retrieved literature.\n'
    '  - "nonsense"     — the claim is malformed, incoherent, or out-of-domain.\n'
    '  - "unclear"      — retrieved evidence is ambiguous; you cannot tell.\n'
    "\n"
    "Be honest about uncertainty. `unclear` is a legitimate answer when\n"
    "the neighbors don't give you enough signal to decide between novel\n"
    "and rediscovery. `nonsense` is for hypotheses that aren't real\n"
    "research questions in game theory / learning in games / behavioral\n"
    "game theory.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "class": "novel" | "rediscovery" | "nonsense" | "unclear",\n'
    '  "rationale": "<1-3 sentence reasoning grounded in the neighbors>",\n'
    '  "top_neighbor_id": "<doc_id of the most-similar neighbor>" | null\n'
    "}\n"
    "\n"
    '`top_neighbor_id` is null for "nonsense" or when no neighbor is\n'
    "relevant. Otherwise it MUST be one of the doc_id strings from the\n"
    "neighbors list (string equality)."
)


def _format_neighbors(neighbors: list[dict]) -> str:
    """Compact human-readable neighbor list for the user-prompt body."""
    if not neighbors:
        return "(none)"
    lines = []
    for i, n in enumerate(neighbors, 1):
        doc_id = n.get("doc_id", "?")
        score = n.get("score")
        title = n.get("title") or "(untitled)"
        source = n.get("source_layer", "?")
        chunk = (n.get("chunk_text") or "").replace("\n", " ").replace("\r", " ").strip()
        if len(chunk) > 600:
            chunk = chunk[:600] + "…"
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "?"
        lines.append(
            f"[{i}] doc_id={doc_id!r}  score={score_str}  source={source}  "
            f"title={title!r}\n    {chunk}"
        )
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Same balanced-brace extractor as hypothesize.py — keep one
    copy here so each worker is self-contained for now. Will hoist to
    a shared util when the pattern repeats once more."""
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


def _validate_payload(
    payload: Any, valid_doc_ids: set[str]
) -> tuple[str | None, str, str | None, list[str]]:
    """Pull class, rationale, top_neighbor_id out of parsed JSON.
    Returns (class, rationale, top_neighbor_id, warnings). class is
    None when the payload is unusable."""
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return None, "", None, ["payload is not a JSON object"]
    cls = payload.get("class")
    if cls not in ALLOWED_CLASSES:
        return None, "", None, [
            f"class={cls!r} not in {ALLOWED_CLASSES}"
        ]
    rationale = payload.get("rationale")
    if not isinstance(rationale, str):
        rationale = ""
        warnings.append("rationale missing or non-string; defaulted to empty")
    rationale = rationale.strip()[:2000]
    top_id_raw = payload.get("top_neighbor_id")
    top_id: str | None
    if top_id_raw is None:
        top_id = None
    elif isinstance(top_id_raw, str):
        top_id = top_id_raw.strip() or None
        if top_id and valid_doc_ids and top_id not in valid_doc_ids:
            warnings.append(
                f"top_neighbor_id={top_id!r} not in retrieved neighbors; nulling"
            )
            top_id = None
    else:
        top_id = None
        warnings.append("top_neighbor_id not a string or null; nulling")
    return cls, rationale, top_id, warnings


def novelty_classify(
    hypothesis_text: str,
    iteration_id: str,
    *,
    parent_request_id: str | None = None,
    log_path: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Classify the hypothesis against the retrieved literature.

    Reads `neighbors` from the per-iteration cache by `iteration_id`
    rather than receiving them in args (reference-passing refactor —
    keeps Nara's tool_call emission small enough to fit the 1024-token
    per-turn cap regardless of Gemma's stochastic inline format).

    Returns:
    ```
    {
        "status": "passed" | "error",
        "result": {
            "class": "novel" | "rediscovery" | "nonsense" | "unclear",
            "rationale": str,
            "top_neighbor_id": str | None,
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
    try:
        retrieval = iteration_cache.read_entry(iteration_id, "retrieval")
    except KeyError as exc:
        return {
            "status": "error",
            "result": None,
            "errors": [f"iteration cache miss for retrieval: {exc}"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    # `retrieval` is the tool_result dict written by Nara, which wraps the
    # worker's payload as {"status": "passed", "result": {...}, ...}.
    # Neighbors live under result.neighbors.
    neighbors = (retrieval.get("result") or {}).get("neighbors") or []
    if not isinstance(neighbors, list):
        return {
            "status": "error",
            "result": None,
            "errors": [
                f"cached retrieval.result.neighbors is not a list "
                f"(got {type(neighbors).__name__})"
            ],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    log_path = log_path or CALLS_LOG_PATH

    valid_doc_ids = {n.get("doc_id") for n in neighbors if isinstance(n.get("doc_id"), str)}

    # Topical-relevance gate (rule 4). If the orchestrator flagged the retrieval
    # as thin/off-topic, warn the model so it does NOT conclude 'novel' merely
    # because an off-topic corpus omits the hypothesis's terms, and stamp
    # low_confidence on the result so no consumer reads a bare 'novel'.
    rel = (retrieval.get("result") or {}).get("relevance") or {}
    rel_low = bool(rel.get("low_confidence"))
    relevance_warning = (
        f"\nRETRIEVAL RELEVANCE WARNING: {rel.get('reason') or 'thin/off-topic retrieval'}. "
        "The retrieved neighbors may be topically irrelevant to this hypothesis. "
        "An omission in an off-topic corpus is NOT evidence of novelty — prefer 'unclear'.\n"
        if rel_low else ""
    )

    user_content = (
        f"Hypothesis:\n{hypothesis_text.strip()}\n\n"
        f"Retrieved neighbors ({len(neighbors)}):\n"
        f"{_format_neighbors(neighbors)}\n"
        f"{relevance_warning}"
    )

    messages = [
        {"role": "system", "content": NOVELTY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        record = call_sync(
            messages,
            temperature=0.2,
            top_p=0.95,
            max_tokens=512,
            caller_tag="novelty_classify",
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
    cls, rationale, top_id, warnings = _validate_payload(payload, valid_doc_ids)

    if cls is None:
        # Fallback: default to "unclear" with a flagged rationale.
        return {
            "status": "passed",
            "result": {
                "class": "unclear",
                "rationale": (
                    "(model emitted unparseable / invalid output; defaulting to unclear) "
                    + strip_channel_markup(completion[:500] or "")
                ).strip(),
                "top_neighbor_id": None,
                "low_confidence": rel_low,
            },
            "errors": ["unparseable model output; classification defaulted to 'unclear'"] + warnings,
            "wrapper_request_id": wrapper_rid,
            "parent_request_id": parent_request_id,
        }

    return {
        "status": "passed",
        "result": {
            "class": cls,
            "rationale": rationale,
            "top_neighbor_id": top_id,
            "low_confidence": rel_low,
        },
        "errors": warnings,
        "wrapper_request_id": wrapper_rid,
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke: pull real neighbors, stage them in the cache, then classify
    # by iteration_id (mirrors how Nara wires things in production).
    from workers.retrieve_literature import retrieve_literature
    hyp = (
        "Tit-for-Tat is the dominant strategy in infinitely repeated "
        "Prisoner's Dilemma against unknown opponents."
    )
    iter_id = "smoke-novelty-classify"
    r = retrieve_literature(hyp, k=5)
    iteration_cache.write_entry(iter_id, "retrieval", r)
    out = novelty_classify(hyp, iter_id, parent_request_id="smoke")
    print(json.dumps(out, indent=2))
