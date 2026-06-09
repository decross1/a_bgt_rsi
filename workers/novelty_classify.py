"""LOOP_V0 step 4 worker — novelty_classify (two-axis rubric, T1b).

Given a hypothesis text and the top-K nearest neighbors from Chroma
(both foundational and live-arXiv), assess the hypothesis on TWO AXES
(plus a substrate tag) and derive the legacy 4-class label
DETERMINISTICALLY in code — the model emits the axes, not the class.
Rubric pre-registered in `docs/novelty_two_axis_rubric.md`.

Axes (`novelty_axes` on the result):
  - `phenomenon`          — "known" | "novel"
  - `substrate`           — "studied_llm" | "unstudied_llm" | "na"
  - `predicted_direction` — "matches" | "deviates" | "silent"

Derived legacy class (kept for every existing consumer):
  - phenomenon novel                  -> `novel`
  - known + deviates                  -> `novel`
  - known + (matches|silent)          -> `rediscovery`  (transfer/replication bucket)
  - incoherent (model sentinel)       -> `nonsense`
  - ambiguous  (model sentinel)       -> `unclear`

Motivation (iteration-068 review): the flat 4-class scheme could not
express "known phenomenon x unstudied substrate x predicts-match" — a
p-beauty/level-k hypothesis on Gemma was labeled `novel` though the
phenomenon is published. The honest label is a low-priority
transfer/replication bucket, which the deterministic mapping now
produces ("no one has run model X on game Y" is a near-null novelty
signal).

The diagrams (ARCHITECTURE.md §6 step 6) name this as the hardest step
in the loop and an explicit sub-research-problem. Phase-1 mitigation:
human-sample rate on automated novelty calls (logged per assessment).

Output matches `iteration_record.novelty`:
  - `class`           — one of the 4 legacy enum values
  - `rationale`       — 1-3 sentence reasoning
  - `top_neighbor_id` — doc_id of the most-similar prior result, or null
  - `low_confidence`  — bool, from the cached retrieval-relevance gate
  - `novelty_axes`    — the axes dict above, or null (sentinels / legacy)
  - `verdict_overridden_from` / `override_reason` — present only when the
    deterministic low-confidence override fired (novel -> unclear).

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

# Model-facing axis vocabularies. `phenomenon` carries two SENTINELS
# ("incoherent", "ambiguous") that map to nonsense/unclear and emit
# novelty_axes = null — the frozen output enum for novelty_axes.phenomenon
# is only ("known", "novel").
PHENOMENON_VALUES = ("known", "novel", "incoherent", "ambiguous")
AXIS_SUBSTRATE = ("studied_llm", "unstudied_llm", "na")
AXIS_DIRECTION = ("matches", "deviates", "silent")


NOVELTY_SYSTEM_PROMPT = (
    "You are the NOVELTY_CLASSIFY worker in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Given a hypothesis and the top-K most semantically similar chunks\n"
    "from the apparatus's knowledge base (foundational textbooks and live\n"
    "arXiv papers), assess the hypothesis on TWO AXES plus a substrate tag.\n"
    "You emit the AXES; the final novelty class is computed by\n"
    "deterministic code, NOT by you.\n"
    "\n"
    'phenomenon — is the underlying effect/regularity a "known" result\n'
    '  stated in the retrieved literature, or "novel" (no retrieved chunk\n'
    '  states it)? Use "incoherent" when the text is malformed, has no\n'
    "  falsifiable content, or is not a real game-theory / learning-in-games /\n"
    '  behavioral-game-theory question. Use "ambiguous" when the neighbors\n'
    "  do not give enough signal to decide known vs novel.\n"
    'substrate — what population the claim is about: "studied_llm" (an\n'
    "  LLM/agent substrate the retrieved literature already studies),\n"
    '  "unstudied_llm" (an LLM substrate the retrieved set does NOT cover,\n'
    '  e.g. one specific new model), or "na" (not substrate-specific).\n'
    'predicted_direction — relative to the known phenomenon: "matches"\n'
    '  (predicts the published direction/effect), "deviates" (predicts a\n'
    '  different direction, boundary, or breakdown), or "silent" (the claim\n'
    '  does not commit to a direction). For a novel phenomenon use "silent"\n'
    "  unless the claim explicitly contradicts a known result.\n"
    "\n"
    "Calibration rules:\n"
    "  - A KNOWN phenomenon predicted to MATCH on a new substrate is\n"
    "    TRANSFER/REPLICATION, not discovery. 'No one has run model X on\n"
    "    game Y' is a near-null novelty signal by itself.\n"
    "  - A well-formed claim that is FALSE is NOT nonsense — falsity is the\n"
    "    critic's job. Classify substance, not truth.\n"
    "  - A definitional truism that states a textbook fact with no\n"
    '    falsifiable claim IS nonsense — mark phenomenon "incoherent".\n'
    '  - Be honest about uncertainty: "ambiguous" is a legitimate answer\n'
    "    when the neighbors don't give you enough signal.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "phenomenon": "known" | "novel" | "incoherent" | "ambiguous",\n'
    '  "substrate": "studied_llm" | "unstudied_llm" | "na",\n'
    '  "predicted_direction": "matches" | "deviates" | "silent",\n'
    '  "rationale": "<1-3 sentence reasoning grounded in the neighbors>",\n'
    '  "top_neighbor_id": "<doc_id of the most-similar neighbor>" | null\n'
    "}\n"
    "\n"
    '`top_neighbor_id` is null for "incoherent" or when no neighbor is\n'
    "relevant. Otherwise it MUST be one of the doc_id strings from the\n"
    "neighbors list (string equality)."
)


def _derive_class(phenomenon: str, predicted_direction: str) -> str:
    """Deterministic axes -> legacy class mapping (pre-registered in
    docs/novelty_two_axis_rubric.md; the model never picks the class)."""
    if phenomenon == "novel":
        return "novel"
    # phenomenon == "known"
    if predicted_direction == "deviates":
        return "novel"
    return "rediscovery"  # matches | silent -> transfer/replication bucket


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
) -> tuple[str | None, dict | None, str, str | None, list[str]]:
    """Pull axes, rationale, top_neighbor_id out of parsed JSON and derive
    the legacy class deterministically.
    Returns (class, novelty_axes, rationale, top_neighbor_id, warnings).
    class is None when the payload is unusable; novelty_axes is None for
    the incoherent/ambiguous sentinels and for legacy class-only payloads."""
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return None, None, "", None, ["payload is not a JSON object"]
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

    phenomenon = payload.get("phenomenon")
    if phenomenon in PHENOMENON_VALUES:
        if phenomenon == "incoherent":
            return "nonsense", None, rationale, top_id, warnings
        if phenomenon == "ambiguous":
            return "unclear", None, rationale, top_id, warnings
        substrate = payload.get("substrate")
        if substrate not in AXIS_SUBSTRATE:
            warnings.append(f"substrate={substrate!r} invalid; defaulted to 'na'")
            substrate = "na"
        direction = payload.get("predicted_direction")
        if direction not in AXIS_DIRECTION:
            if phenomenon == "known":
                # The class-determining axis is unusable — fail closed.
                warnings.append(
                    f"predicted_direction={direction!r} invalid on known "
                    "phenomenon; class-determining axis unusable -> 'unclear'"
                )
                return "unclear", None, rationale, top_id, warnings
            warnings.append(
                f"predicted_direction={direction!r} invalid; defaulted to 'silent'"
            )
            direction = "silent"
        axes = {
            "phenomenon": phenomenon,
            "substrate": substrate,
            "predicted_direction": direction,
        }
        return _derive_class(phenomenon, direction), axes, rationale, top_id, warnings

    # Legacy class-only payload (model ignored the axes schema — Gemma is
    # stochastic about format). Accept with a warning so old-format
    # completions degrade gracefully instead of collapsing to unparseable.
    cls = payload.get("class")
    if cls in ALLOWED_CLASSES:
        warnings.append(
            "model emitted legacy 'class' without novelty_axes; axes set to null"
        )
        return cls, None, rationale, top_id, warnings
    return None, None, "", None, warnings + [
        f"phenomenon={phenomenon!r} not in {PHENOMENON_VALUES} and "
        f"class={cls!r} not in {ALLOWED_CLASSES}"
    ]


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
            "low_confidence": bool,
            "novelty_axes": {
                "phenomenon": "known" | "novel",
                "substrate": "studied_llm" | "unstudied_llm" | "na",
                "predicted_direction": "matches" | "deviates" | "silent",
            } | None,
            # only when the low-confidence override fired (novel -> unclear):
            "verdict_overridden_from": str,
            "override_reason": str,
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
        "An omission in an off-topic corpus is NOT evidence of novelty — prefer "
        "phenomenon 'ambiguous'.\n"
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
    cls, axes, rationale, top_id, warnings = _validate_payload(payload, valid_doc_ids)

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
                "novelty_axes": None,
            },
            "errors": ["unparseable model output; classification defaulted to 'unclear'"] + warnings,
            "wrapper_request_id": wrapper_rid,
            "parent_request_id": parent_request_id,
        }

    result: dict[str, Any] = {
        "class": cls,
        "rationale": rationale,
        "top_neighbor_id": top_id,
        "low_confidence": rel_low,
        "novelty_axes": axes,
    }

    # Deterministic override (rule 4: never trust 'novel' on inadequate
    # retrieval): low-confidence retrieval + derived class 'novel' ->
    # 'unclear'. The axes (the model's judgment) are preserved; only the
    # derived class is downgraded, with the override recorded.
    if rel_low and cls == "novel":
        result["verdict_overridden_from"] = "novel"
        result["override_reason"] = (
            "low-confidence retrieval ("
            + (rel.get("reason") or "thin/off-topic retrieval")
            + "); 'novel' downgraded to 'unclear' — an omission in an "
            "off-topic corpus is not novelty"
        )
        result["class"] = "unclear"
        warnings = warnings + [
            "low-confidence retrieval: derived class 'novel' overridden to 'unclear'"
        ]

    return {
        "status": "passed",
        "result": result,
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
