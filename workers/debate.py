"""Bounded multi-turn adversarial debate (D-065).

The single-shot skeptic exchange (orchestrator.novelty_skeptic.attack)
asks one independent model for one verdict and stops. That is not a
research argument — the challenger never hears a rebuttal, the defender
never answers an objection, and `subagent_turns_used: 1` is the honest
record of it. This module runs the exchange the owner asked for: a real
back-and-forth, bounded, with every turn tagged by the model that
produced it.

Protocol, per round:
  CHALLENGER (independent weights — vllm-qwen by default) attacks the
  claim, grounded in retrieved evidence, or concedes that the claim
  stands.
  DEFENDER (the apparatus's own vllm-gemma) must either REBUT with a
  specific counter-argument/counter-citation, or CONCEDE explicitly.

Stop criteria, checked in this precedence order:
  1. challenger concedes ("no further objection")      -> "survives_debate".
     An explicit challenger concession is the ONLY route to that verdict
     (owner ratification 2026-08-15, run_state/overrides.jsonl
     D065_debate_params_ratified).
  2. challenger repeats its previous objection          -> "converged",
     verdict "inconclusive". A repeat is not a new attack, and a merely
     rebutted objection is not a survival — converged stays NEUTRAL.
  3. defender concedes                                 -> "refuted"
  4. MAX_DEBATE_ROUNDS reached                         -> "inconclusive"
     (NEVER coerced to survives — a debate that ran out of rounds
     decided nothing; inviolate rule 4)
Any subagent error / timeout / unparseable turn ends the debate at that
turn and returns "inconclusive", with the error recorded in the
transcript (fail-closed, mirroring the existing skeptics).

Independence (D-041) is preserved: `evidence=None` makes the debate do
its OWN retrieval rather than reason over the critic's neighbor set —
sharing that set is exactly the blind spot the skeptic seam exists to
break.

MOCK_LLM: every real turn and the debate's own retrieval refuse to run
and fail the debate closed. Tests inject `defender_fn`/`challenger_fn`.

Return shape:
  {"verdict": "refuted" | "survives_debate" | "inconclusive",
   "rounds": int,
   "transcript": [{"round", "role", "backend", "model", "text",
                   "wall_seconds", "error"?}, ...],
   "stop_reason": str}
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from agent_wrapper.backends import get_backend
from orchestrator.chroma_query import query_top_k
from orchestrator.subagent import SubAgentBudget, run_subagent
from workers.novelty_skeptic import _format_neighbors
from workers.retrieval_relevance import _tokenize


# Hard cap. `max_rounds` above this raises — the bound is not negotiable
# from the call site (that is what makes it a bound).
MAX_DEBATE_ROUNDS = 4

# The debate's own retrieval depth when the caller passes evidence=None.
# Same figure as the D-044 attack().
DEBATE_EVIDENCE_K = 10

# A challenger turn whose objection is this lexically similar to its own
# previous turn is a repeat, not a new attack.
REPEAT_SIMILARITY_THRESHOLD = 0.8

CHALLENGER_BACKEND_DEFAULT = "vllm-qwen"
DEFENDER_BACKEND = "vllm-gemma"

# Qwen's hidden reasoning channel starves at the subagent default 1024
# (observed 2026-06-09); 3072 is the working figure the D-044 skeptics
# already run with.
DEBATE_MAX_TOKENS_PER_TURN = 3072
DEBATE_TURN_WALL_SECONDS = 90.0

ALLOWED_DEBATE_VERDICTS = ("refuted", "survives_debate", "inconclusive")

_MARKER_RE = re.compile(r"^\s*(OBJECT|REBUT|CONCEDE)\s*:\s*", re.IGNORECASE)
_CONCEDE_RE = re.compile(r"^\s*CONCEDE\b", re.IGNORECASE)


CHALLENGER_SYSTEM_PROMPT = (
    "You are the CHALLENGER in a bounded adversarial debate inside the\n"
    "a_bgt_rsi research apparatus — a DIFFERENT model from the one that\n"
    "generated the claim and now defends it. Each round you attack the\n"
    "claim with the strongest objection the retrieved evidence supports:\n"
    "a chunk that CONTRADICTS it, or a chunk it merely RESTATES.\n"
    "\n"
    "Rules of the exchange:\n"
    "  - Ground every objection in a specific retrieved chunk and cite\n"
    "    its doc_id. Never invent evidence.\n"
    "  - READ THE TRANSCRIPT. Do not re-file an objection the defender\n"
    "    has already rebutted — either escalate with a NEW objection\n"
    "    (a different chunk, or a flaw in the rebuttal itself) or\n"
    "    concede. A repeated objection ends the debate as unresolved.\n"
    "  - If the rebuttals have answered you and the evidence supports no\n"
    "    further objection, CONCEDE. That is a legitimate outcome, not a\n"
    "    failure — a challenger who never concedes carries no signal.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences:\n"
    "{\n"
    '  "stance": "object" | "concede",\n'
    '  "argument": "<1-3 sentences: the objection, or why you concede>",\n'
    '  "cited_doc_id": "<doc_id from the evidence>" | null\n'
    "}"
)

DEFENDER_SYSTEM_PROMPT = (
    "You are the DEFENDER in a bounded adversarial debate inside the\n"
    "a_bgt_rsi research apparatus. The claim below is the apparatus's own\n"
    "hypothesis and a skeptic on different weights is attacking it.\n"
    "\n"
    "Each round you MUST do exactly one of:\n"
    "  (a) REBUT — answer the challenger's LATEST objection with a\n"
    "      specific counter-argument or counter-citation from the\n"
    "      evidence. A rebuttal that does not engage the actual\n"
    "      objection is worthless; restating the claim is not a\n"
    "      rebuttal.\n"
    "  (b) CONCEDE — say plainly that the objection stands and the claim\n"
    "      does not survive it. Conceding a correct objection is the\n"
    "      honest move; defending an indefensible claim is the exact\n"
    "      failure mode this debate exists to catch.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences:\n"
    "{\n"
    '  "stance": "rebut" | "concede",\n'
    '  "argument": "<1-3 sentences: the rebuttal, or what you concede>",\n'
    '  "cited_doc_id": "<doc_id from the evidence>" | null\n'
    "}"
)

_CHALLENGER_SCHEMA = {
    "type": "object",
    "required": ["stance", "argument"],
    "properties": {
        "stance":       {"type": "string", "enum": ["object", "concede"]},
        "argument":     {"type": "string"},
        "cited_doc_id": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}

_DEFENDER_SCHEMA = {
    "type": "object",
    "required": ["stance", "argument"],
    "properties": {
        "stance":       {"type": "string", "enum": ["rebut", "concede"]},
        "argument":     {"type": "string"},
        "cited_doc_id": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}


def _concedes(text: Any) -> bool:
    """True iff the turn opens with the explicit CONCEDE marker. Anything
    else is a continued objection/rebuttal — a turn never concedes by
    accident (fail-closed direction)."""
    return bool(_CONCEDE_RE.match(text or "")) if isinstance(text, str) else False


def _jaccard(a: set[str], b: set[str]) -> float:
    """Lexical Jaccard over content tokens. Reuses retrieval_relevance's
    tokenizer rather than adding a similarity dependency."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _objection_tokens(text: str) -> set[str]:
    """Content tokens of a turn, with the protocol marker stripped so the
    shared 'OBJECT:' prefix doesn't inflate the similarity."""
    return _tokenize(_MARKER_RE.sub("", text or ""))


def _turn(round_no: int, role: str, payload: dict) -> dict[str, Any]:
    """One transcript row. Every model turn carries the backend + model
    that produced it — that tagging is the point of the exercise."""
    row = {
        "round":        round_no,
        "role":         role,
        "backend":      payload.get("backend"),
        "model":        payload.get("model"),
        "text":         payload.get("text") or "",
        "wall_seconds": payload.get("wall_seconds") or 0.0,
    }
    if payload.get("error"):
        row["error"] = payload["error"]
    return row


def _transcript_block(transcript: list[dict]) -> str:
    if not transcript:
        return "(this is the first round; no exchange yet)"
    return "\n".join(
        f"[round {t['round']}] {str(t['role']).upper()} "
        f"({t.get('backend')}): {t['text']}"
        for t in transcript
    )


def _subagent_turn(
    *,
    role: str,
    backend: str,
    system_prompt: str,
    user_prompt: str,
    schema: dict,
    allowed_stances: tuple[str, ...],
    iteration_id: str | None,
) -> dict[str, Any]:
    """Run one debate turn on a real backend via run_subagent.

    Returns the turn payload the engine records. An `error` key on the
    payload ends the debate (fail-closed) — this function never raises
    and never manufactures an argument.
    """
    if os.environ.get("MOCK_LLM"):
        return {
            "text": "", "backend": backend, "model": "mock", "wall_seconds": 0.0,
            "error": "MOCK_LLM set; refusing to spawn a real debate subagent",
        }
    try:
        resolved_be = get_backend(backend)
    except KeyError as exc:
        return {
            "text": "", "backend": backend, "model": None, "wall_seconds": 0.0,
            "error": f"unknown debate backend: {exc}",
        }
    try:
        sa = run_subagent(
            name=f"debate_{role}",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expected_output_schema=schema,
            budget=SubAgentBudget(
                max_turns=2,  # one answer + at most one JSON repair-retry
                max_wall_seconds=DEBATE_TURN_WALL_SECONDS,
                max_tokens_per_turn=DEBATE_MAX_TOKENS_PER_TURN,
            ),
            parent_request_id=iteration_id,
            backend=backend,
        )
    except Exception as exc:
        return {
            "text": "", "backend": resolved_be.name,
            "model": resolved_be.default_model, "wall_seconds": 0.0,
            "error": f"run_subagent raised: {type(exc).__name__}: {exc}",
        }

    payload: dict[str, Any] = {
        "backend":      resolved_be.name,
        "model":        resolved_be.default_model,
        "wall_seconds": round(sa.wall_seconds, 3),
        "text":         "",
    }
    if sa.status != "passed" or not isinstance(sa.result, dict):
        payload["error"] = (
            f"{role} turn {sa.status}: " + "; ".join(sa.errors)[:300]
        )
        return payload
    stance = str(sa.result.get("stance") or "").strip().lower()
    argument = str(sa.result.get("argument") or "").strip()
    if stance not in allowed_stances or not argument:
        payload["error"] = (
            f"{role} turn off-protocol (stance={stance!r}, "
            f"argument_len={len(argument)})"
        )
        return payload
    cited = sa.result.get("cited_doc_id")
    cite_suffix = (
        f" [cites {cited.strip()}]"
        if isinstance(cited, str) and cited.strip() else ""
    )
    # The marker is machine-written from the validated stance, so the
    # stop criteria never depend on the model's prose formatting.
    payload["text"] = f"{stance.upper()}: {argument}{cite_suffix}"
    return payload


def _default_challenger(claim, evidence_text, transcript, iteration_id):
    return _subagent_turn(
        role="challenger",
        backend=os.environ.get(
            "NARA_SKEPTIC_BACKEND", CHALLENGER_BACKEND_DEFAULT),
        system_prompt=CHALLENGER_SYSTEM_PROMPT,
        user_prompt=(
            f"Claim under debate:\n{claim}\n\n"
            f"Retrieved evidence:\n{evidence_text}\n\n"
            f"Transcript so far:\n{_transcript_block(transcript)}\n\n"
            "Your turn."
        ),
        schema=_CHALLENGER_SCHEMA,
        allowed_stances=("object", "concede"),
        iteration_id=iteration_id,
    )


def _default_defender(claim, evidence_text, transcript, iteration_id):
    return _subagent_turn(
        role="defender",
        backend=DEFENDER_BACKEND,
        system_prompt=DEFENDER_SYSTEM_PROMPT,
        user_prompt=(
            f"Claim you are defending:\n{claim}\n\n"
            f"Retrieved evidence:\n{evidence_text}\n\n"
            f"Transcript so far:\n{_transcript_block(transcript)}\n\n"
            "Rebut the challenger's latest objection, or concede it."
        ),
        schema=_DEFENDER_SCHEMA,
        allowed_stances=("rebut", "concede"),
        iteration_id=iteration_id,
    )


def _evidence_text(
    claim: str, evidence: Any, iteration_id: str | None
) -> tuple[str, str | None]:
    """Render the evidence block. Returns (text, error).

    `evidence=None` means the debate retrieves its OWN evidence (D-041
    independence). A list of neighbors or a pre-rendered string is used
    as given.
    """
    if isinstance(evidence, str):
        return (evidence.strip() or "(none)", None)
    if isinstance(evidence, list):
        return (_format_neighbors(evidence), None)
    if evidence is not None:
        return ("", f"unusable evidence of type {type(evidence).__name__}")
    if os.environ.get("MOCK_LLM"):
        return ("", "MOCK_LLM set; refusing the debate's own live retrieval")
    try:
        ret = query_top_k(
            claim, k=DEBATE_EVIDENCE_K, parent_request_id=iteration_id)
    except Exception as exc:
        return ("", f"debate's own retrieval raised: {type(exc).__name__}: {exc}")
    neighbors = (ret.get("result") or {}).get("neighbors") or []
    if ret.get("status") != "passed" or not neighbors:
        return ("", (
            f"debate's own retrieval returned no usable neighbors "
            f"(status={ret.get('status')!r}); cannot ground a debate"
        ))
    return (_format_neighbors(neighbors), None)


def _out(verdict: str, rounds: int, transcript: list[dict], stop_reason: str) -> dict:
    return {
        "verdict":     verdict,
        "rounds":      rounds,
        "transcript":  transcript,
        "stop_reason": stop_reason,
    }


def debate(
    claim: str,
    evidence: Any,
    *,
    defender_fn: Callable | None = None,
    challenger_fn: Callable | None = None,
    max_rounds: int = MAX_DEBATE_ROUNDS,
    iteration_id: str | None = None,
) -> dict[str, Any]:
    """Run a bounded adversarial debate over `claim`. See module docstring.

    `defender_fn`/`challenger_fn` are called as fn(claim, evidence_text,
    transcript) and must return
    {"text", "backend", "model", "wall_seconds", "error"?}. They exist so
    tests can drive the protocol without a model; production leaves them
    None and gets the vllm-qwen challenger / vllm-gemma defender.

    Raises ValueError when `max_rounds` is out of band — the cap is a
    bound, not a suggestion.
    """
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) \
            or not 1 <= max_rounds <= MAX_DEBATE_ROUNDS:
        raise ValueError(
            f"max_rounds must be an int in 1..{MAX_DEBATE_ROUNDS}, "
            f"got {max_rounds!r}"
        )

    transcript: list[dict] = []
    if not isinstance(claim, str) or not claim.strip():
        transcript.append(_turn(0, "system", {
            "text": "empty claim; nothing to debate",
            "error": "empty claim",
        }))
        return _out("inconclusive", 0, transcript, "error")

    evidence_text, ev_error = _evidence_text(claim.strip(), evidence, iteration_id)
    if ev_error:
        transcript.append(_turn(0, "system", {
            "text": ev_error, "error": ev_error,
        }))
        return _out("inconclusive", 0, transcript, "error")

    challenger = challenger_fn or (
        lambda c, e, t: _default_challenger(c, e, t, iteration_id))
    defender = defender_fn or (
        lambda c, e, t: _default_defender(c, e, t, iteration_id))

    prev_challenger_tokens: set[str] | None = None

    for round_no in range(1, max_rounds + 1):
        try:
            ch = challenger(claim.strip(), evidence_text, transcript) or {}
        except Exception as exc:
            ch = {"error": f"challenger raised: {type(exc).__name__}: {exc}"}
        transcript.append(_turn(round_no, "challenger", ch))
        if ch.get("error") or not ch.get("text"):
            return _out(
                "inconclusive", round_no, transcript, "challenger_error")

        if _concedes(ch["text"]):
            return _out(
                "survives_debate", round_no, transcript, "challenger_conceded")

        tokens = _objection_tokens(ch["text"])
        if prev_challenger_tokens is not None and _jaccard(
                tokens, prev_challenger_tokens) >= REPEAT_SIMILARITY_THRESHOLD:
            # A repeat is not a new attack — and a rebutted objection is
            # not a survival. Converged is NEUTRAL (owner ratification
            # 2026-08-15): the exchange stalled, it did not settle.
            return _out("inconclusive", round_no, transcript, "converged")
        prev_challenger_tokens = tokens

        try:
            df = defender(claim.strip(), evidence_text, transcript) or {}
        except Exception as exc:
            df = {"error": f"defender raised: {type(exc).__name__}: {exc}"}
        transcript.append(_turn(round_no, "defender", df))
        if df.get("error") or not df.get("text"):
            return _out("inconclusive", round_no, transcript, "defender_error")

        if _concedes(df["text"]):
            return _out("refuted", round_no, transcript, "defender_conceded")

    # Rounds exhausted with both sides still arguing. Rule 4: that is
    # undecided, NOT survival.
    return _out("inconclusive", max_rounds, transcript, "round_cap")


if __name__ == "__main__":
    # Smoke: `env -u MOCK_LLM ./.venv-chroma/bin/python -m workers.debate \
    #         "<claim text>"`
    import json
    import sys
    import time as _time

    from agent_wrapper.wrapper import set_run_id
    from orchestrator import active_run

    hyp = sys.argv[1] if len(sys.argv) > 1 else (
        "In repeated public-goods games, contribution decay is driven by "
        "conditional cooperators imitating free riders."
    )
    _run_id = f"debate_smoke_{int(_time.time())}"
    set_run_id(_run_id)
    active_run.write_active_run(_run_id, "ad_hoc", "workers.debate smoke")
    try:
        print(json.dumps(debate(hyp, None, iteration_id="smoke"), indent=2))
    finally:
        active_run.clear_active_run()
        set_run_id(None)
