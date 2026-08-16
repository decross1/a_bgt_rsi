"""Independent-skeptic attack ladder (D-041).

The 068 review's central finding: novelty_classify and the critic reason
over the SAME retrieved neighbor set, so their agreement is a shared
blind spot, not corroboration. This module's `attack()` breaks that by
doing its OWN literature retrieval (orchestrator.chroma_query.query_top_k
with the default collections) and prompting an independent backend to
REFUTE the hypothesis against that fresh evidence.

Priority ladder (D-041, selected by `backend=`):
  step 1 — "ollama-coder" (default): Qwen via the D-035 ollama route.
            Genuinely different weights from Gemma -> a real second judge.
  step 2 — "vllm-gemma": same weights as the apparatus, but under a
            visibly ADVERSARIAL persona distinct from the critic's
            methodological-critic persona, so it is not the same judge
            run twice with the same framing.
  step 3 — Claude via the Agent SDK: DESIGN ONLY this session
            (docs/skeptic_ladder.md); not wired here.

Return shape (FROZEN — other limbs build against it):
  {"attack_verdict": "refuted" | "survives_attack" | "inconclusive",
   "rationale": str,
   "contradicting_doc_id": str | None,
   "backend": str,
   "model": str}

Fail-closed discipline: anything that prevents a grounded verdict —
empty input, unknown backend, failed retrieval, wrapper error,
unparseable or off-enum model output, an unverifiable "refuted"
citation — returns "inconclusive", NEVER "survives_attack". Consumers
gate on == "refuted" / == "survives_attack" explicitly.

MOCK_LLM: returns a deterministic stub without touching retrieval,
network, or any model.

Shares the balanced-brace JSON extractor and neighbor formatter with
workers/novelty_skeptic.py rather than duplicating them (bounded
codegen).
"""
from __future__ import annotations

import os
from typing import Any

from agent_wrapper.backends import get_backend
from agent_wrapper.cleanup import strip_channel_markup
from agent_wrapper.wrapper import DEFAULT_BACKEND, call_sync
from orchestrator.chroma_query import query_top_k
from workers.novelty_skeptic import _extract_json_object, _format_neighbors


CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

ALLOWED_ATTACK_VERDICTS = ("refuted", "survives_attack", "inconclusive")

# The skeptic's own retrieval depth. Independent of whatever k the
# apparatus used for novelty/critic — that independence is the point.
ATTACK_RETRIEVAL_K = 10

# Token config mirrors workers/novelty_skeptic.py: the non-reasoning
# gemma persona stops at a short verdict, so 512 suffices on the default
# backend; reasoning/MTP backends (Qwen) burn tokens on a hidden channel
# first and starve at 512/2048 (observed 2026-06-09). 3072 was the 2026-06
# working figure; the ledger has since outgrown it — 651 real Qwen calls to 2026-08-16 put the p90 output AT the 3072 cap for the independent-skeptic sites; 43 calls hit it and 31 returned EMPTY content,
# i.e. the cap was silently eating ~5% of independent verdicts (the
# 2026-08-16T04:00Z qwen_degraded_empty_content alert). 6144 clears the
# measured tail with the served 16k window still half free (prompts run
# ~2k). vLLM REJECTS rather than clamps, so this stays sized, not guessed.
ATTACK_MAX_TOKENS_DEFAULT_BACKEND = 512
ATTACK_MAX_TOKENS_INDEPENDENT = 6144


# Shared task body: the attack instructions + strict JSON schema. The
# persona prefix differs per ladder step (see below).
_ATTACK_TASK_BODY = (
    "\n\n"
    "You are given a hypothesis and the top-K most semantically similar\n"
    "chunks retrieved FRESH from the apparatus's knowledge base (curated\n"
    "foundational texts and live papers). This retrieval is YOURS — the\n"
    "model that scored the hypothesis never saw this exact set, so do not\n"
    "assume anything has already been checked.\n"
    "\n"
    "Your single job is to try to REFUTE the hypothesis:\n"
    "  - find a retrieved chunk that CONTRADICTS the claim, or\n"
    "  - find a retrieved chunk the claim merely RESTATES (prior art).\n"
    "\n"
    "Verdicts:\n"
    '  - "refuted"         — you found a contradiction or a restatement.\n'
    "                        You MUST cite the doc_id of the chunk that\n"
    "                        kills the claim.\n"
    '  - "survives_attack" — you genuinely tried and the retrieved set\n'
    "                        contains neither a contradiction nor a\n"
    "                        restatement. Do NOT award this as a default.\n"
    '  - "inconclusive"    — the evidence does not decide it, or the\n'
    "                        claim is too vague to attack.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences:\n"
    "{\n"
    '  "attack_verdict": "refuted" | "survives_attack" | "inconclusive",\n'
    '  "rationale": "<1-3 sentences grounded in specific retrieved chunks>",\n'
    '  "contradicting_doc_id": "<doc_id from the list>" | null\n'
    "}\n"
    "\n"
    '`contradicting_doc_id` is REQUIRED (non-null) for "refuted" and MUST\n'
    "be one of the doc_id strings from the retrieved list (string\n"
    "equality). For the other verdicts it is null."
)

# Step 1 — independent weights (Qwen / ollama-coder). Plain skeptic
# framing; independence comes from the different model.
QWEN_ATTACK_PERSONA = (
    "You are the INDEPENDENT SKEPTIC in the a_bgt_rsi research apparatus —\n"
    "a different model from the one that generated and scored the\n"
    "hypothesis below. The apparatus's own model judged this hypothesis\n"
    "novel-and-surviving; your job is to attack that judgment with fresh\n"
    "evidence it never saw."
) + _ATTACK_TASK_BODY

# Step 2 — same weights as the apparatus (vllm-gemma), so the persona
# must be VISIBLY adversarial and distinct from both the critic's
# methodological-critic framing and novelty_skeptic's second-opinion
# framing — otherwise it is the same judge twice.
GEMMA_ADVERSARY_PERSONA = (
    "You are HOSTILE REVIEWER #2 — a prior-art prosecutor. You are NOT a\n"
    "balanced critic and you are NOT here to give a second opinion: your\n"
    "professional reputation rides on finding the citation that kills\n"
    "this claim. Assume the hypothesis is wrong or unoriginal until the\n"
    "evidence forces you to concede otherwise. Conceding\n"
    '"survives_attack" is an admission of defeat you make only after a\n'
    "genuine, chunk-by-chunk hunt for the contradiction or the prior\n"
    "art. Never invent evidence: a kill requires a real doc_id from the\n"
    "retrieved list."
) + _ATTACK_TASK_BODY


def _result(
    verdict: str,
    rationale: str,
    contradicting_doc_id: str | None,
    backend: str,
    model: str,
) -> dict[str, Any]:
    return {
        "attack_verdict": verdict,
        "rationale": rationale,
        "contradicting_doc_id": contradicting_doc_id,
        "backend": backend,
        "model": model,
    }


def attack(
    hypothesis_text: str,
    iteration_id: str | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    """Independent refutation attack on a hypothesis (D-041 ladder).

    Does its OWN retrieval via `query_top_k` (default collections) and
    asks the selected backend to refute the hypothesis against that set.
    `iteration_id` is provenance only — it is threaded into the calls
    log as `parent_request_id` so the attack joins the iteration trace;
    it is NOT used to read the iteration cache (no shared neighbors —
    that shared-blind-spot is exactly what this closes).

    Fail-closed: every failure path returns "inconclusive", never
    "survives_attack".

    backend=None resolves from NARA_SKEPTIC_BACKEND (default "vllm-qwen"
    — the backend the 2026-06-09 ladder step-1 live test validated 3/3;
    the ollama-coder path needs OLLAMA_MODEL set and pages a second qwen
    copy into the unified pool, so it is no longer the default).
    """
    if backend is None:
        backend = os.environ.get("NARA_SKEPTIC_BACKEND", "vllm-qwen")
    if os.environ.get("MOCK_LLM"):
        return _result("inconclusive", "MOCK_LLM stub", None, backend, "mock")

    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        return _result(
            "inconclusive",
            "empty hypothesis_text; nothing to attack",
            None, backend, "",
        )

    # Resolve the backend up front so provenance is stamped on every
    # outcome. Unknown name -> inconclusive (fail-closed), not coerced
    # to the default (rule 4 / explicit-fallback discipline).
    try:
        resolved_be = get_backend(backend)
    except KeyError as exc:
        return _result(
            "inconclusive", f"unknown skeptic backend: {exc}; attack not run",
            None, backend, "",
        )
    model_version = resolved_be.model_version

    # The skeptic's OWN retrieval. Default collections — Limb D is
    # making the default curated; we deliberately do not pin a list.
    try:
        ret = query_top_k(
            hypothesis_text.strip(), k=ATTACK_RETRIEVAL_K,
            parent_request_id=iteration_id,
        )
    except Exception as exc:
        return _result(
            "inconclusive",
            f"skeptic's own retrieval raised: {type(exc).__name__}: {exc}",
            None, resolved_be.name, model_version,
        )
    neighbors = (ret.get("result") or {}).get("neighbors") or []
    if ret.get("status") != "passed" or not neighbors:
        return _result(
            "inconclusive",
            f"skeptic's own retrieval returned no usable neighbors "
            f"(status={ret.get('status')!r}, errors={ret.get('errors')!r}); "
            "cannot ground an attack",
            None, resolved_be.name, model_version,
        )
    valid_doc_ids = {
        n.get("doc_id") for n in neighbors if isinstance(n.get("doc_id"), str)
    }

    system_prompt = (
        GEMMA_ADVERSARY_PERSONA if backend == "vllm-gemma" else QWEN_ATTACK_PERSONA
    )
    user_content = (
        f"Hypothesis:\n{hypothesis_text.strip()}\n\n"
        f"Your retrieved neighbors ({len(neighbors)}):\n"
        f"{_format_neighbors(neighbors)}\n"
    )
    max_tokens = (
        ATTACK_MAX_TOKENS_DEFAULT_BACKEND
        if backend == DEFAULT_BACKEND
        else ATTACK_MAX_TOKENS_INDEPENDENT
    )

    try:
        record = call_sync(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            top_p=0.95,
            max_tokens=max_tokens,
            caller_tag="skeptic_attack",
            parent_request_id=iteration_id,
            log_path=CALLS_LOG_PATH,
            backend=backend,
        )
    except Exception as exc:
        return _result(
            "inconclusive",
            f"wrapper.call_sync failed: {type(exc).__name__}: {exc}",
            None, resolved_be.name, model_version,
        )

    completion = record.get("completion") or ""
    payload = _extract_json_object(completion)
    if payload is None:
        payload = _extract_json_object(strip_channel_markup(completion))
    if not isinstance(payload, dict) or payload.get("attack_verdict") not in ALLOWED_ATTACK_VERDICTS:
        return _result(
            "inconclusive",
            (
                "(unparseable or off-enum skeptic output; defaulting to "
                "inconclusive) " + strip_channel_markup(completion[:800] or "")
            ).strip(),
            None, resolved_be.name, model_version,
        )

    verdict = payload["attack_verdict"]
    rationale = payload.get("rationale")
    if not isinstance(rationale, str):
        rationale = ""
    rationale = rationale.strip()[:2000]

    doc_id_raw = payload.get("contradicting_doc_id")
    doc_id = doc_id_raw.strip() or None if isinstance(doc_id_raw, str) else None
    if doc_id is not None and doc_id not in valid_doc_ids:
        doc_id = None  # unverifiable citation

    if verdict == "refuted" and doc_id is None:
        # A refutation we cannot tie to a retrieved chunk is not a
        # refutation — downgrade, never coerce (rule 4).
        return _result(
            "inconclusive",
            (
                "(skeptic claimed 'refuted' but cited no doc_id from its "
                "retrieved set; downgraded) " + rationale
            ).strip(),
            None, resolved_be.name, model_version,
        )
    if verdict != "refuted":
        doc_id = None

    return _result(verdict, rationale, doc_id, resolved_be.name, model_version)


if __name__ == "__main__":
    # Smoke: `env -u MOCK_LLM ./.venv-chroma/bin/python -m orchestrator.novelty_skeptic \
    #         "<hypothesis text>" [backend]`
    import json
    import sys
    import time as _time

    from agent_wrapper.wrapper import set_run_id
    from orchestrator import active_run

    hyp = sys.argv[1] if len(sys.argv) > 1 else (
        "In repeated public-goods games, contribution decay is driven by "
        "conditional cooperators imitating free riders."
    )
    be = sys.argv[2] if len(sys.argv) > 2 else "ollama-coder"
    # Run-provenance registration (2026-06-10): even the smoke registers,
    # so skeptic calls never show up as unattributed backend load.
    _run_id = f"skeptic_smoke_{int(_time.time())}"
    set_run_id(_run_id)
    active_run.write_active_run(
        _run_id, "ad_hoc", f"novelty_skeptic smoke ({be})",
    )
    try:
        print(json.dumps(attack(hyp, iteration_id="smoke", backend=be), indent=2))
    finally:
        active_run.clear_active_run()
        set_run_id(None)
