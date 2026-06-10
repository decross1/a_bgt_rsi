"""Restatement skeptic — canonicalize-then-retrieve prior-art confirmation.

The 2026-06-09 battery's residual 2: four novelty=rediscovery cases
(redisc_on_01_tft_reciprocity, redisc_on_03_quantal_response,
canary_on_01_ultimatum_plain, canary_on_02_hawkdove_ess) got past the
critic as survives/undecidable even though novelty had already — and
correctly — called them rediscoveries. The generic refute attack does
not fix them: it hair-splits on substrate ("no chunk about LLM agents in
infinitely-repeated PD") and plain-language phrasings miss their prior
art at retrieval time. This module is the purpose-built fix, triggered
by the critic hook on novelty=rediscovery + verdict survives/undecidable.

Flow (every failure path is FAIL-OPEN "inconclusive" — the critic hook
acts only on a doc-grounded "restated"; anything else leaves the critic
verdict untouched):
  1. canonicalize — one call_sync (temp 0.0) names the canonical
     game-theory concept(s) and restates the claim in the vocabulary a
     textbook index would use. Failure -> fall back to the original
     hypothesis text, explicitly recorded in the rationale (this step
     closes the plain-language retrieval miss, e.g. "split a sum...
     reject... both get nothing" -> "ultimatum game rejection of low
     offers").
  2. fresh retrieval — query_top_k on the canonical statement (k=10),
     then union the ONE cached novelty top-neighbor chunk (read from the
     iteration cache; cache-read failure non-fatal). Sharing this one
     neighbor is safe because the job is confirming prior art, not
     corroborating survives. Retrieval failure/empty -> inconclusive.
  3. judge — one call_sync (temp 0.2) under the pre-registered two-axis
     transfer rule; "restated" REQUIRES a restating_doc_id verifiable
     against the retrieved list (missing/out-of-set -> DOWNGRADED to
     inconclusive, rule 4 — never coerced).

Return shape (FROZEN — the critic hook builds against it):
  {"restate_verdict": "restated" | "not_restated" | "inconclusive",
   "rationale": str,
   "restating_doc_id": str | None,
   "canonical_statement": str | None,
   "backend": str,
   "model": str}

MOCK_LLM: returns a deterministic stub without touching retrieval,
network, or any model.

Shares the balanced-brace JSON extractor and neighbor formatter with
workers/novelty_skeptic.py rather than duplicating them (bounded
codegen), mirroring orchestrator/novelty_skeptic.py.
"""
from __future__ import annotations

import os
from typing import Any

from agent_wrapper.backends import get_backend
from agent_wrapper.cleanup import strip_channel_markup
from agent_wrapper.wrapper import call_sync
from orchestrator import iteration_cache
from orchestrator.chroma_query import query_top_k
from workers.novelty_skeptic import _extract_json_object, _format_neighbors


CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

ALLOWED_RESTATE_VERDICTS = ("restated", "not_restated", "inconclusive")

# The skeptic's own retrieval depth — same figure as the D-044 attack().
RESTATE_RETRIEVAL_K = 10

# Both calls run on the independent backend (vllm-qwen by default), whose
# hidden reasoning channel starves at 512/2048 (observed 2026-06-09) —
# 3072 flat is the D-044 working figure, pinned for both calls.
RESTATE_MAX_TOKENS = 3072


CANONICALIZE_SYSTEM_PROMPT = (
    "You are the CANONICALIZER in the a_bgt_rsi research apparatus. A\n"
    "claim is about to be checked for prior art against a game-theory\n"
    "knowledge base, but it may be phrased in plain language, ML\n"
    "vocabulary, or biological vocabulary that embedding retrieval\n"
    "misses.\n"
    "\n"
    "Your single job: name the canonical game-theory concept(s) the claim\n"
    "is about, and restate the claim in the vocabulary a game-theory\n"
    'textbook index would use. Example: "two players split a sum; the\n'
    "receiver can reject, and then both get nothing; lowball splits get\n"
    'rejected" is canonically the ultimatum game, restated as "In the\n'
    'ultimatum game, responders reject low offers even at a cost to\n'
    'themselves."\n'
    "\n"
    "Do NOT judge novelty or truth. Do NOT add content — only rename into\n"
    "standard terminology, preserving the claim's predicted direction.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences:\n"
    "{\n"
    '  "canonical_statement": "<the claim in textbook-index vocabulary>",\n'
    '  "concept_names": ["<canonical concept name>", ...]\n'
    "}"
)

JUDGE_SYSTEM_PROMPT = (
    "You are the RESTATEMENT SKEPTIC in the a_bgt_rsi research apparatus.\n"
    "The apparatus's novelty classifier judged the claim below a\n"
    "REDISCOVERY of the retrieved literature, yet its critic let the\n"
    "claim stand. Your single job is to settle that disagreement: does a\n"
    "retrieved chunk ALREADY STATE this claim?\n"
    "\n"
    "TRANSFER RULE (pre-registered two-axis rubric, known+matches ->\n"
    "rediscovery): a claim whose phenomenon a retrieved chunk already\n"
    "states, with the same predicted direction, is RESTATED even if the\n"
    "claim names a different population or substrate (LLM agents,\n"
    "animals, plain language) — substrate transfer alone is not new\n"
    'content. Do not hair-split on substrate: "no chunk mentions LLM\n'
    'agents" is NOT a reason to answer "not_restated" when the phenomenon\n'
    "and direction match.\n"
    "\n"
    "Verdicts:\n"
    '  - "restated"     — a retrieved chunk already states the claim\'s\n'
    "                     phenomenon with the same predicted direction.\n"
    "                     You MUST cite the doc_id of that chunk.\n"
    '  - "not_restated" — you checked every chunk and none states the\n'
    "                     phenomenon-and-direction; the claim carries\n"
    "                     content beyond substrate renaming.\n"
    '  - "inconclusive" — the retrieved evidence does not decide it.\n'
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences:\n"
    "{\n"
    '  "restate_verdict": "restated" | "not_restated" | "inconclusive",\n'
    '  "rationale": "<1-3 sentences grounded in specific retrieved chunks>",\n'
    '  "restating_doc_id": "<doc_id from the list>" | null\n'
    "}\n"
    "\n"
    '`restating_doc_id` is REQUIRED (non-null) for "restated" and MUST be\n'
    "one of the doc_id strings from the retrieved list (string equality).\n"
    "For the other verdicts it is null."
)


def _result(
    verdict: str,
    rationale: str,
    restating_doc_id: str | None,
    canonical_statement: str | None,
    backend: str,
    model: str,
) -> dict[str, Any]:
    return {
        "restate_verdict": verdict,
        "rationale": rationale,
        "restating_doc_id": restating_doc_id,
        "canonical_statement": canonical_statement,
        "backend": backend,
        "model": model,
    }


def _canonicalize(
    hypothesis_text: str, iteration_id: str | None, backend: str
) -> tuple[str | None, str]:
    """Step 1: textbook-vocabulary restatement of the claim.

    Returns (canonical_statement | None, note). None means the caller
    falls back to the original hypothesis text; `note` records why, so
    the fallback is explicit in whatever rationale the attack returns."""
    try:
        record = call_sync(
            [
                {"role": "system", "content": CANONICALIZE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Claim:\n{hypothesis_text}"},
            ],
            temperature=0.0,
            max_tokens=RESTATE_MAX_TOKENS,
            caller_tag="restate_canonicalize",
            parent_request_id=iteration_id,
            log_path=CALLS_LOG_PATH,
            backend=backend,
        )
    except Exception as exc:
        return None, (
            f"(canonicalize call failed: {type(exc).__name__}: {exc}; "
            "attacked the original claim text) "
        )
    # Wrapper records carry `completion` as a plain STRING (the dict-shaped
    # misread class the 2026-06-09 review caught; same guard as the
    # topicality sibling).
    completion = (record.get("completion") or "") if isinstance(record, dict) else ""
    payload = _extract_json_object(completion)
    if payload is None:
        payload = _extract_json_object(strip_channel_markup(completion))
    stmt = payload.get("canonical_statement") if isinstance(payload, dict) else None
    if not isinstance(stmt, str) or not stmt.strip():
        return None, (
            "(canonicalize output unparseable or empty; attacked the "
            "original claim text) "
        )
    return stmt.strip()[:2000], ""


def restate_attack(
    hypothesis_text: str,
    iteration_id: str | None = None,
    backend: str | None = None,
    novelty_top_neighbor_id: str | None = None,
) -> dict[str, Any]:
    """Restatement attack on a novelty-judged rediscovery (residual 2).

    Canonicalizes the claim into textbook vocabulary, retrieves FRESH on
    that statement (closing the plain-language retrieval miss), unions
    the one cached novelty top-neighbor as a prior-art candidate, and
    judges restatement under the two-axis transfer rule.

    `iteration_id` rides as parent_request_id on both calls and the
    retrieval (provenance), and locates the cached retrieval entry the
    novelty top-neighbor is copied from. `novelty_top_neighbor_id` is
    the doc_id novelty_classify cited — its chunk is appended to the
    fresh set if absent (cache-read failure non-fatal).

    Fail-OPEN: every failure path returns "inconclusive", which the
    critic hook treats as no-evidence (verdict unchanged). "restated" is
    returned only with a restating_doc_id verified against the retrieved
    list, so the hook can only move a verdict on grounded prior art.

    backend=None resolves from NARA_SKEPTIC_BACKEND (default "vllm-qwen",
    matching the D-044 attack()).
    """
    if backend is None:
        backend = os.environ.get("NARA_SKEPTIC_BACKEND", "vllm-qwen")
    if os.environ.get("MOCK_LLM"):
        return _result("inconclusive", "MOCK_LLM stub", None, None, backend, "mock")

    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        return _result(
            "inconclusive",
            "empty hypothesis_text; nothing to attack",
            None, None, backend, "",
        )

    # Resolve the backend up front so provenance is stamped on every
    # outcome. Unknown name -> inconclusive (fail-open), not coerced to
    # the default (rule 4 / explicit-fallback discipline).
    try:
        resolved_be = get_backend(backend)
    except KeyError as exc:
        return _result(
            "inconclusive",
            f"unknown skeptic backend: {exc}; restate attack not run",
            None, None, backend, "",
        )
    model_version = resolved_be.model_version

    hyp = hypothesis_text.strip()

    # Step 1 — canonicalize. Failure falls back to the original text;
    # `canon_note` makes the fallback explicit in the final rationale.
    canonical_statement, canon_note = _canonicalize(hyp, iteration_id, backend)

    # Step 2 — the skeptic's own retrieval, on the canonical phrasing.
    try:
        ret = query_top_k(
            canonical_statement or hyp, k=RESTATE_RETRIEVAL_K,
            parent_request_id=iteration_id,
        )
    except Exception as exc:
        return _result(
            "inconclusive",
            canon_note + (
                f"restate skeptic's own retrieval raised: "
                f"{type(exc).__name__}: {exc}"
            ),
            None, canonical_statement, resolved_be.name, model_version,
        )
    neighbors = list((ret.get("result") or {}).get("neighbors") or [])
    if ret.get("status") != "passed" or not neighbors:
        return _result(
            "inconclusive",
            canon_note + (
                f"restate skeptic's own retrieval returned no usable "
                f"neighbors (status={ret.get('status')!r}, "
                f"errors={ret.get('errors')!r}); cannot ground a judgment"
            ),
            None, canonical_statement, resolved_be.name, model_version,
        )

    # Union the ONE cached novelty top-neighbor (the prior-art candidate
    # novelty_classify cited) into the candidate set when the fresh query
    # missed it. Cache-read failure is non-fatal — the fresh set still
    # grounds the judge.
    if novelty_top_neighbor_id and iteration_id:
        if novelty_top_neighbor_id not in {n.get("doc_id") for n in neighbors}:
            try:
                cached = iteration_cache.read_entry(iteration_id, "retrieval")
                for n in (cached.get("result") or {}).get("neighbors") or []:
                    if n.get("doc_id") == novelty_top_neighbor_id:
                        neighbors.append(n)
                        break
            except Exception as exc:  # fail-open, but named (rule-7 style)
                canon_note += (
                    f"(cached-neighbor union skipped: "
                    f"{type(exc).__name__}) "
                )

    valid_doc_ids = {
        n.get("doc_id") for n in neighbors if isinstance(n.get("doc_id"), str)
    }

    user_content = (
        f"Claim (original phrasing):\n{hyp}\n\n"
        f"Canonical restatement (used for retrieval):\n"
        f"{canonical_statement or '(canonicalization failed; original text used)'}\n\n"
        f"Retrieved neighbors ({len(neighbors)}):\n"
        f"{_format_neighbors(neighbors)}\n"
    )

    # Step 3 — the transfer-rule judge.
    try:
        record = call_sync(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            top_p=0.95,
            max_tokens=RESTATE_MAX_TOKENS,
            caller_tag="restate_judge",
            parent_request_id=iteration_id,
            log_path=CALLS_LOG_PATH,
            backend=backend,
        )
    except Exception as exc:
        return _result(
            "inconclusive",
            canon_note + f"wrapper.call_sync failed: {type(exc).__name__}: {exc}",
            None, canonical_statement, resolved_be.name, model_version,
        )

    completion = (record.get("completion") or "") if isinstance(record, dict) else ""
    payload = _extract_json_object(completion)
    if payload is None:
        payload = _extract_json_object(strip_channel_markup(completion))
    if not isinstance(payload, dict) or payload.get("restate_verdict") not in ALLOWED_RESTATE_VERDICTS:
        return _result(
            "inconclusive",
            (
                canon_note + "(unparseable or off-enum restate-judge output; "
                "defaulting to inconclusive) "
                + strip_channel_markup(completion[:800] or "")
            ).strip(),
            None, canonical_statement, resolved_be.name, model_version,
        )

    verdict = payload["restate_verdict"]
    rationale = payload.get("rationale")
    if not isinstance(rationale, str):
        rationale = ""
    rationale = (canon_note + rationale.strip()).strip()[:2000]

    doc_id_raw = payload.get("restating_doc_id")
    doc_id = doc_id_raw.strip() or None if isinstance(doc_id_raw, str) else None
    if doc_id is not None and doc_id not in valid_doc_ids:
        doc_id = None  # unverifiable citation

    if verdict == "restated" and doc_id is None:
        # A restatement we cannot tie to a retrieved chunk is not a
        # restatement — downgrade, never coerce (rule 4).
        return _result(
            "inconclusive",
            (
                "(restate judge claimed 'restated' but cited no doc_id from "
                "its retrieved set; downgraded) " + rationale
            ).strip(),
            None, canonical_statement, resolved_be.name, model_version,
        )
    if verdict != "restated":
        doc_id = None

    return _result(
        verdict, rationale, doc_id, canonical_statement,
        resolved_be.name, model_version,
    )


if __name__ == "__main__":
    # Smoke: `env -u MOCK_LLM ./.venv-chroma/bin/python -m orchestrator.restate_skeptic \
    #         "<hypothesis text>" [backend]`
    import json
    import sys
    import time as _time

    from agent_wrapper.wrapper import set_run_id
    from orchestrator import active_run

    hyp = sys.argv[1] if len(sys.argv) > 1 else (
        "Two players split a fixed sum; one proposes the split and the "
        "other can reject, leaving both with nothing. Receivers turn down "
        "lowball splits even though rejecting costs them money."
    )
    be = sys.argv[2] if len(sys.argv) > 2 else None
    # Run-provenance registration: even the smoke registers, so restate
    # calls never show up as unattributed backend load.
    _run_id = f"restate_smoke_{int(_time.time())}"
    set_run_id(_run_id)
    active_run.write_active_run(
        _run_id, "ad_hoc", f"restate_skeptic smoke ({be or 'env-default'})",
    )
    try:
        print(json.dumps(restate_attack(hyp, iteration_id="smoke", backend=be), indent=2))
    finally:
        active_run.clear_active_run()
        set_run_id(None)
