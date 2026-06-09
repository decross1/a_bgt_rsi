"""Independent novelty skeptic — a second-opinion novelty class.

D-033 makes the apparatus single-model (Gemma) for novelty, mitigated
ONLY by per-iteration human sampling. Beta removes the human from the
loop, so without an independent second opinion the same weights would
score their own novelty unchecked while "the apparatus is the
contribution" rides on novelty validity. This worker gives a
second-opinion novelty class on (hypothesis, retrieved neighbors,
Gemma's own novelty verdict) plus an `agreement` flag.

Mirrors the `novelty_classify` contract: reads heavy payloads
(retrieval neighbors, Gemma's novelty result) by `iteration_id` from
the per-iteration cache, makes ONE chat completion via
`wrapper.call_sync(..., backend=...)`, robust-JSON-extracts, validates
the class against the closed enum (NEVER coerces), and returns the
standard {status, result, errors, wrapper_request_id,
parent_request_id} envelope.

Backend selection (D-035 substrate) is a `backend=` kwarg, defaulting
to `NOVELTY_SKEPTIC_BACKEND` env, falling back to "vllm-gemma" — the
same `gemma_persona` route `critic_loop_v0` uses CRITIC_BACKEND for.

  CAVEAT (load-bearing): the default "vllm-gemma" route is the SAME
  weights as novelty_classify, so its agreement is a SELF-CHECK, NOT
  independent corroboration. It is plumbing/CI/baseline only. The
  `skeptic_backend` field is stamped into every result so no consumer
  mistakes a gemma_persona agreement for an independent witness. The
  actual D-033 mitigation requires an independent backend (vllm-qwen
  on-box, behind the B1 memory guard with a logged fallback; or the
  off-box anthropic route once credits/auth are cleared).

Schema additions (under iteration_record.novelty, NOT wired this
session — standalone-runnable):
  - skeptic_class           — second-opinion class, same closed enum
  - skeptic_backend         — registry name of the backend used
  - skeptic_model_version   — provenance string from the resolved backend
  - agreement               — True iff skeptic_class == novelty.class
  - skeptic_rationale       — 1-3 sentence reasoning reacting to Gemma's call
  - skeptic_top_neighbor_id — skeptic's own top neighbor, validated in-set
"""
from __future__ import annotations

import json
import os
from typing import Any

from agent_wrapper.backends import get_backend
from agent_wrapper.cleanup import strip_channel_markup
from agent_wrapper.wrapper import DEFAULT_BACKEND, call_sync
from orchestrator import iteration_cache


CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

# Same closed enum as novelty.class, so agreement is a direct equality.
ALLOWED_CLASSES = ("novel", "rediscovery", "nonsense", "unclear")


SKEPTIC_SYSTEM_PROMPT = (
    "You are the NOVELTY_SKEPTIC in the a_bgt_rsi research apparatus — an\n"
    "INDEPENDENT second opinion on a novelty judgment another model already\n"
    "made. The apparatus generates hypotheses and scores their novelty with\n"
    "ITS OWN weights; your job is to confirm or dissent against that\n"
    "self-assessment so a single model does not grade its own novelty\n"
    "unchecked.\n"
    "\n"
    "You are given: a hypothesis, the top-K most semantically similar chunks\n"
    "from the apparatus's knowledge base (foundational textbooks and live\n"
    "arXiv papers), and the FIRST model's novelty verdict (its class and\n"
    "rationale). Independently classify the hypothesis into ONE of four\n"
    "buckets — the SAME set the first model used:\n"
    "\n"
    '  - "novel"        — substantive, well-formed claim; no close match in the retrieved set.\n'
    '  - "rediscovery"  — the claim restates a known result in the retrieved literature.\n'
    '  - "nonsense"     — the claim is malformed, incoherent, or out-of-domain.\n'
    '  - "unclear"      — retrieved evidence is ambiguous; you cannot tell.\n'
    "\n"
    "Judge the EVIDENCE yourself. Do not defer to the first model's verdict —\n"
    "agree only if the neighbors genuinely support its class, and dissent\n"
    "(with a reason grounded in specific neighbors) when they do not. A model\n"
    "over-claiming `novel` on its own output when a neighbor already covers\n"
    "the claim is exactly what you are here to catch. Be honest about\n"
    "uncertainty: `unclear` is legitimate when the neighbors don't decide it.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "skeptic_class": "novel" | "rediscovery" | "nonsense" | "unclear",\n'
    '  "skeptic_rationale": "<1-3 sentences grounded in the neighbors, explicitly reacting to the first model\'s class>",\n'
    '  "skeptic_top_neighbor_id": "<doc_id of YOUR most-similar neighbor>" | null\n'
    "}\n"
    "\n"
    '`skeptic_top_neighbor_id` is null for "nonsense" or when no neighbor is\n'
    "relevant. Otherwise it MUST be one of the doc_id strings from the\n"
    "neighbors list (string equality)."
)


def _format_neighbors(neighbors: list[dict]) -> str:
    """Compact human-readable neighbor list for the user-prompt body
    (kept identical to novelty_classify so the two models see the same
    evidence formatting — a fair second opinion)."""
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
    """Balanced-brace extractor — same one novelty_classify/hypothesize
    use. Kept self-contained per the bounded-codegen rule."""
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
    """Pull skeptic_class, skeptic_rationale, skeptic_top_neighbor_id out
    of parsed JSON. Returns (class, rationale, top_neighbor_id, warnings).
    class is None when the payload is unusable — NEVER coerced to a
    nearby enum value (rule 4)."""
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return None, "", None, ["payload is not a JSON object"]
    cls = payload.get("skeptic_class")
    if cls not in ALLOWED_CLASSES:
        return None, "", None, [
            f"skeptic_class={cls!r} not in {ALLOWED_CLASSES}"
        ]
    rationale = payload.get("skeptic_rationale")
    if not isinstance(rationale, str):
        rationale = ""
        warnings.append("skeptic_rationale missing or non-string; defaulted to empty")
    rationale = rationale.strip()[:2000]
    top_id_raw = payload.get("skeptic_top_neighbor_id")
    top_id: str | None
    if top_id_raw is None:
        top_id = None
    elif isinstance(top_id_raw, str):
        top_id = top_id_raw.strip() or None
        if top_id and valid_doc_ids and top_id not in valid_doc_ids:
            warnings.append(
                f"skeptic_top_neighbor_id={top_id!r} not in retrieved neighbors; nulling"
            )
            top_id = None
    else:
        top_id = None
        warnings.append("skeptic_top_neighbor_id not a string or null; nulling")
    return cls, rationale, top_id, warnings


def novelty_skeptic(
    hypothesis_text: str,
    iteration_id: str,
    *,
    backend: str | None = None,
    parent_request_id: str | None = None,
    log_path: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Independent second-opinion novelty class on a hypothesis.

    Reads `neighbors` (from the cached `retrieval` entry) and Gemma's
    novelty verdict (from the cached `novelty` entry) by `iteration_id`
    — reference-passing, mirroring novelty_classify/critic_loop_v0.

    `backend` selects the D-035 backend; None -> NOVELTY_SKEPTIC_BACKEND
    env -> DEFAULT_BACKEND ("vllm-gemma"). NOTE: the default is the SAME
    weights as novelty_classify and is therefore a self-check, not an
    independent witness — `skeptic_backend` in the result tells consumers
    which it was.

    Returns:
    ```
    {
        "status": "passed" | "error",
        "result": {
            "skeptic_class": "novel" | "rediscovery" | "nonsense" | "unclear",
            "skeptic_backend": str,
            "skeptic_model_version": str,
            "agreement": bool,
            "skeptic_rationale": str,
            "skeptic_top_neighbor_id": str | None,
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
    try:
        novelty = iteration_cache.read_entry(iteration_id, "novelty")
    except KeyError as exc:
        return {
            "status": "error",
            "result": None,
            "errors": [f"iteration cache miss for novelty: {exc}"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }

    # Cache entries are the tool_result envelope Nara writes:
    # {"status": ..., "result": {...}, ...}.
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
    gemma_nov = novelty.get("result") or {}
    gemma_class = gemma_nov.get("class")
    if gemma_class not in ALLOWED_CLASSES:
        return {
            "status": "error",
            "result": None,
            "errors": [
                f"cached novelty.result.class={gemma_class!r} not in "
                f"{ALLOWED_CLASSES}; cannot form a second opinion"
            ],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    gemma_rationale = gemma_nov.get("rationale")
    if not isinstance(gemma_rationale, str):
        gemma_rationale = ""

    log_path = log_path or CALLS_LOG_PATH
    backend_name = backend or os.environ.get("NOVELTY_SKEPTIC_BACKEND") or DEFAULT_BACKEND
    valid_doc_ids = {n.get("doc_id") for n in neighbors if isinstance(n.get("doc_id"), str)}

    user_content = (
        f"Hypothesis:\n{hypothesis_text.strip()}\n\n"
        f"Retrieved neighbors ({len(neighbors)}):\n"
        f"{_format_neighbors(neighbors)}\n\n"
        f"The first model's novelty verdict (independently re-judge it):\n"
        f"  class: {gemma_class}\n"
        f"  rationale: {gemma_rationale.strip()[:1500] or '(none given)'}\n"
    )

    messages = [
        {"role": "system", "content": SKEPTIC_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # Resolve the backend up front so its provenance is stamped even when
    # the model output is unparseable (the second opinion still has a
    # known source). An unknown backend name is a hard error — not coerced
    # to the default, per rule 4 / explicit-fallback discipline.
    try:
        resolved_be = get_backend(backend_name)
    except KeyError as exc:
        return {
            "status": "error",
            "result": None,
            "errors": [f"unknown skeptic backend: {exc}"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    skeptic_model_version = resolved_be.model_version

    # Reasoning/MTP backends (e.g. vllm-qwen qwen3.6-MTP) spend tokens on a hidden
    # reasoning channel before emitting content; 512 (fine for the non-reasoning
    # gemma persona) starves them and yields empty completions (observed on
    # vllm-qwen 2026-06-09: finish_reason=length, content=None). Give the
    # independent routes generous headroom — the bound is an upper limit, so the
    # gemma persona still stops at its short verdict.
    skeptic_max_tokens = 512 if backend_name == DEFAULT_BACKEND else 2048

    try:
        record = call_sync(
            messages,
            temperature=0.2,
            top_p=0.95,
            max_tokens=skeptic_max_tokens,
            caller_tag="novelty_skeptic",
            parent_request_id=parent_request_id,
            log_path=log_path,
            model=model,
            backend=backend_name,
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
    cls, rationale, top_id, warnings = _validate_payload(
        _extract_json_object(completion), valid_doc_ids
    )

    if cls is None:
        # Fallback: default to "unclear" with a flagged rationale — same
        # discipline as novelty_classify. NEVER coerce a near-miss to a
        # valid enum value. agreement is computed against the fallback
        # class so the flag stays honest (unclear != gemma's class unless
        # gemma also said unclear).
        skeptic_class = "unclear"
        return {
            "status": "passed",
            "result": {
                "skeptic_class": skeptic_class,
                "skeptic_backend": resolved_be.name,
                "skeptic_model_version": skeptic_model_version,
                "agreement": skeptic_class == gemma_class,
                "skeptic_rationale": (
                    "(skeptic emitted unparseable / invalid output; defaulting to unclear) "
                    + strip_channel_markup(completion[:500] or "")
                ).strip(),
                "skeptic_top_neighbor_id": None,
            },
            "errors": ["unparseable skeptic output; class defaulted to 'unclear'"] + warnings,
            "wrapper_request_id": wrapper_rid,
            "parent_request_id": parent_request_id,
        }

    return {
        "status": "passed",
        "result": {
            "skeptic_class": cls,
            "skeptic_backend": resolved_be.name,
            "skeptic_model_version": skeptic_model_version,
            "agreement": cls == gemma_class,
            "skeptic_rationale": rationale,
            "skeptic_top_neighbor_id": top_id,
        },
        "errors": warnings,
        "wrapper_request_id": wrapper_rid,
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke: read a real iteration_cache triple (hypothesis + retrieval +
    # Gemma's novelty) and form a second opinion by iteration_id. Defaults
    # to the gemma_persona route (plumbing); pass NOVELTY_SKEPTIC_BACKEND=
    # vllm-qwen / anthropic for an independent witness. Needs env -u MOCK_LLM
    # for a real run.
    import sys
    iter_id = sys.argv[1] if len(sys.argv) > 1 else "iter-2026-05-27-001"
    hyp_entry = iteration_cache.read_entry(iter_id, "hypothesis")
    hyp_text = (hyp_entry.get("result") or {}).get("text") or ""
    out = novelty_skeptic(hyp_text, iter_id, parent_request_id="smoke")
    print(json.dumps(out, indent=2))
