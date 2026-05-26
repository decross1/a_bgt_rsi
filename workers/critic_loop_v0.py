"""LOOP_V0 step 5 worker — critic_loop_v0 (literature-grounded falsification).

Given a hypothesis and the top-K retrieved neighbors, attempt to falsify
the hypothesis using ONLY the retrieved literature. This is the
literature-only critic — no experiment is run; the verdict draws only
on the prior work that's already in the knowledge base.

Verdicts (matches `iteration_record.critique`):
  - `survives`   — no retrieved paper contradicts; claim is well-formed
  - `falsified`  — at least one retrieved paper directly contradicts
  - `restated`   — claim is a restatement of a known result (often
                   correlates with novelty=rediscovery but the framing
                   here is "this hypothesis adds nothing new")
  - `malformed`  — claim is incoherent, ill-defined, or out-of-scope

Named `critic_loop_v0` to avoid colliding with the salvaged Day-9
`workers/critic.py` (Phase-2 contract with a different 2-class verdict;
keep both files independently importable).

Calls Gemma via `wrapper.call_sync`. Same robust JSON-extraction
pattern as the other LLM-using workers.
"""
from __future__ import annotations

import json
import os
from typing import Any

from agent_wrapper.wrapper import call_sync


CALLS_LOG_PATH = os.environ.get(
    "LOOP_V0_CALLS_LOG", "logs/calls.jsonl"
)

ALLOWED_VERDICTS = ("survives", "falsified", "restated", "malformed")


CRITIC_SYSTEM_PROMPT = (
    "You are the CRITIC worker in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Given a hypothesis and the top-K most semantically similar chunks\n"
    "from the apparatus's knowledge base, attempt to FALSIFY the\n"
    "hypothesis using ONLY the retrieved literature. Do not invoke\n"
    "knowledge from outside the retrieved set. Do not run experiments.\n"
    "Your job is to find the strongest counter-argument that's already\n"
    "present in the prior work.\n"
    "\n"
    "Return ONE of four verdicts:\n"
    '  - "survives"   — no retrieved chunk directly contradicts the claim.\n'
    '                    The hypothesis is well-formed and not yet defeated.\n'
    '  - "falsified"  — at least one retrieved chunk directly contradicts\n'
    '                    the claim. Cite which one in `contradicting_paper_id`.\n'
    '  - "restated"   — the claim restates a known result in the retrieved\n'
    '                    set; it adds no new content. (Often pairs with a\n'
    '                    "rediscovery" novelty class, but the framing here\n'
    '                    is about novelty-of-contribution, not novelty-of-claim.)\n'
    '  - "malformed"  — the claim is incoherent, ill-defined, or not a\n'
    '                    real game-theory / learning-in-games question.\n'
    "\n"
    "Be intellectually honest: `survives` is a legitimate answer when the\n"
    "literature simply doesn't address the claim. `restated` is reserved\n"
    "for claims that the retrieved set proves redundant. Cite specific\n"
    "doc_ids when relevant.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "verdict": "survives" | "falsified" | "restated" | "malformed",\n'
    '  "rationale": "<2-4 sentences citing specific neighbors where relevant>",\n'
    '  "contradicting_paper_id": "<doc_id of the contradicting neighbor>" | null\n'
    "}\n"
    "\n"
    '`contradicting_paper_id` is non-null ONLY for "falsified" or "restated".\n'
    "It MUST be one of the doc_id strings from the neighbors list when present."
)


def _format_neighbors(neighbors: list[dict]) -> str:
    """Compact neighbor list for the user prompt body."""
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
    """Balanced-brace JSON extractor (same pattern as
    workers/hypothesize.py and workers/novelty_classify.py)."""
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
    """Pull verdict, rationale, contradicting_paper_id from parsed JSON."""
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return None, "", None, ["payload is not a JSON object"]
    verdict = payload.get("verdict")
    if verdict not in ALLOWED_VERDICTS:
        return None, "", None, [
            f"verdict={verdict!r} not in {ALLOWED_VERDICTS}"
        ]
    rationale = payload.get("rationale")
    if not isinstance(rationale, str):
        rationale = ""
        warnings.append("rationale missing or non-string; defaulted to empty")
    rationale = rationale.strip()[:2000]
    contra_raw = payload.get("contradicting_paper_id")
    contra: str | None
    if contra_raw is None:
        contra = None
    elif isinstance(contra_raw, str):
        contra = contra_raw.strip() or None
        if contra and valid_doc_ids and contra not in valid_doc_ids:
            warnings.append(
                f"contradicting_paper_id={contra!r} not in retrieved neighbors; nulling"
            )
            contra = None
    else:
        contra = None
        warnings.append("contradicting_paper_id not a string or null; nulling")
    # Consistency: contradicting_paper_id must be null when verdict is
    # survives / malformed; allowed for falsified / restated.
    if verdict in ("survives", "malformed") and contra is not None:
        warnings.append(
            f"contradicting_paper_id set on verdict={verdict!r}; nulling per schema"
        )
        contra = None
    return verdict, rationale, contra, warnings


def critic_loop_v0(
    hypothesis_text: str,
    neighbors: list[dict],
    *,
    parent_request_id: str | None = None,
    log_path: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Falsify the hypothesis against retrieved literature.

    Returns:
    ```
    {
        "status": "passed" | "error",
        "result": {
            "verdict": "survives" | "falsified" | "restated" | "malformed",
            "rationale": str,
            "contradicting_paper_id": str | None,
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
    if not isinstance(neighbors, list):
        return {
            "status": "error",
            "result": None,
            "errors": ["neighbors must be a list"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    log_path = log_path or CALLS_LOG_PATH

    valid_doc_ids = {n.get("doc_id") for n in neighbors if isinstance(n.get("doc_id"), str)}

    user_content = (
        f"Hypothesis:\n{hypothesis_text.strip()}\n\n"
        f"Retrieved neighbors ({len(neighbors)}):\n"
        f"{_format_neighbors(neighbors)}\n"
    )

    messages = [
        {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        record = call_sync(
            messages,
            temperature=0.2,
            top_p=0.95,
            max_tokens=512,
            caller_tag="critic_loop_v0",
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
    verdict, rationale, contra, warnings = _validate_payload(payload, valid_doc_ids)

    if verdict is None:
        # Fallback: default to "survives" with a flagged rationale. We
        # default to survives (not falsified) because absence-of-evidence
        # should not be evidence-of-absence — if the model fails, the
        # hypothesis hasn't actually been disproven.
        return {
            "status": "passed",
            "result": {
                "verdict": "survives",
                "rationale": (
                    "(model emitted unparseable / invalid output; defaulting to survives) "
                    + (completion[:500] or "")
                ).strip(),
                "contradicting_paper_id": None,
            },
            "errors": ["unparseable model output; verdict defaulted to 'survives'"] + warnings,
            "wrapper_request_id": wrapper_rid,
            "parent_request_id": parent_request_id,
        }

    return {
        "status": "passed",
        "result": {
            "verdict": verdict,
            "rationale": rationale,
            "contradicting_paper_id": contra,
        },
        "errors": warnings,
        "wrapper_request_id": wrapper_rid,
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke: pull real neighbors, criticize.
    from workers.retrieve_literature import retrieve_literature
    hyp = (
        "In finitely repeated Prisoner's Dilemma with known horizon, "
        "rational players defect on every round by backward induction."
    )
    r = retrieve_literature(hyp, k=5)
    out = critic_loop_v0(hyp, r["result"]["neighbors"], parent_request_id="smoke")
    print(json.dumps(out, indent=2))
