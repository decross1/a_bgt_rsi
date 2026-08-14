"""Worker: extract the canonical claim record from an iteration row (LOOP_V1
P1, A2). The record is the idea-ledger's atom:

    {"problem": str, "mechanism": str, "predicted_effect": str,
     "evidence_ref": {"iteration_id": str,
                      "journal_entry_path": str | None,
                      "results_path": str | None}}

DETERMINISTIC-FIRST: problem / mechanism / predicted_effect are derived from
`hypothesis.text` sentence structure plus `seed.topic` — no model call needed.
An optional single low-temperature `call_sync` refinement runs ONLY when
MOCK_LLM is unset; under MOCK_LLM the deterministic path IS the behavior. A
failed refinement is an explicit, logged fallback to the deterministic record
(rule 7) — never a silent degrade, never an exception swallowed into an empty
claim.

LEAKED-JSON-BLOB REPAIR: two real surfaced rows (sf-iter-2026-06-13-001,
sf-iter-2026-08-04-001 in memory/surfaced_findings.jsonl) carry a claim /
hypothesis text that is a raw JSON candidates blob:

    {"candidates": ["...", "..."], "chosen": "..."}

— often NOT even valid JSON, because raw LaTeX (`$\\lambda$`) leaks invalid
escape sequences. `_repair_blob` detects the shape and recovers the chosen
hypothesis text (strict parse -> backslash-repaired parse -> regex extraction
of "chosen" -> last candidate). An unrecoverable blob RAISES (rule 4: a claim
we cannot read is a failure, not a pass-through).
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

# ── Leaked-JSON-blob detection + repair ──────────────────────────────────────

# A backslash NOT starting a valid JSON escape (\" \\ \/ \b \f \n \r \t \uXXXX)
# — the LaTeX-leak signature (e.g. `$\lambda$` inside a JSON string literal).
_BAD_ESCAPE = re.compile(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})')


def _looks_like_blob(text: str) -> bool:
    """True when the claim text is itself a JSON candidates blob."""
    t = text.strip()
    return t.startswith("{") and '"candidates"' in t


def _repair_blob(text: str) -> str:
    """Recover the intended hypothesis text from a leaked candidates blob.

    Ladder: strict json.loads -> loads after doubling invalid escapes ->
    regex-extract the "chosen" string literal. Preference inside a parsed
    blob: "chosen", else the LAST candidate (the generation loop's pick).
    Raises ValueError when nothing recoverable remains.
    """
    obj = None
    for candidate_text in (text, _BAD_ESCAPE.sub(r"\\\\", text)):
        try:
            obj = json.loads(candidate_text)
            break
        except (json.JSONDecodeError, ValueError):
            continue
    if isinstance(obj, dict):
        chosen = obj.get("chosen")
        if isinstance(chosen, str) and chosen.strip():
            return chosen.strip()
        cands = obj.get("candidates")
        if isinstance(cands, list):
            strs = [c for c in cands if isinstance(c, str) and c.strip()]
            if strs:
                return strs[-1].strip()
    # Regex fallback on the raw text: the "chosen" string literal.
    m = re.search(r'"chosen"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if m and m.group(1).strip():
        raw = m.group(1)
        # Undo the escapes we can; leave LaTeX backslashes as-is.
        for esc, rep in (('\\"', '"'), ("\\n", "\n"), ("\\t", "\t")):
            raw = raw.replace(esc, rep)
        return raw.strip()
    raise ValueError(
        "claim_extract: leaked-JSON-blob claim is unrecoverable (no parseable "
        "'chosen' or 'candidates') — refusing to emit an empty claim (rule 4)."
    )


# ── Deterministic sentence-structure derivation ──────────────────────────────

# Mechanism-clause markers, matched at the EARLIEST occurrence. Word-bounded;
# "where"/"such that" rank after the causal markers so "because" wins ties.
_MECH_MARKERS = (
    "because", "due to", "driven by", "caused by", "reflecting",
    "as a function of", "via", "such that", "where", "when",
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _first_sentence(text: str) -> str:
    parts = _SENT_SPLIT.split(text.strip(), maxsplit=1)
    return parts[0].strip()


def _mechanism_clause(text: str) -> str:
    """Clause after the earliest mechanism marker, to the sentence end.
    "" when no marker is present — an honest absence, never invented."""
    low = text.lower()
    best: tuple[int, str] | None = None
    for marker in _MECH_MARKERS:
        m = re.search(r"\b" + re.escape(marker) + r"\b", low)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), marker)
    if best is None:
        return ""
    clause = text[best[0]:]
    return _first_sentence(clause).rstrip(".").strip()


def _derive_fields(hypothesis_text: str, seed_topic: str) -> dict[str, str]:
    """The deterministic core: {problem, mechanism, predicted_effect} from
    sentence structure + seed topic."""
    first = _first_sentence(hypothesis_text)
    problem = seed_topic.strip() if seed_topic.strip() else first
    mechanism = _mechanism_clause(hypothesis_text)
    return {"problem": problem, "mechanism": mechanism, "predicted_effect": first}


# ── Optional single low-temp refinement (real runs only) ─────────────────────

_REFINE_SYSTEM = (
    "You canonicalize research claims. Given a hypothesis and a draft "
    "decomposition, return ONLY a JSON object with exactly these string keys: "
    '"problem" (the research question addressed), "mechanism" (the causal '
    'mechanism asserted; empty string if none is stated), "predicted_effect" '
    "(the testable predicted effect). Stay faithful to the hypothesis; do not "
    "invent content absent from it."
)


def _refine_fields(fields: dict[str, str], hypothesis_text: str) -> dict[str, str]:
    """One low-temp call_sync pass over the deterministic draft. Returns the
    refined fields, or raises — the caller owns the logged fallback."""
    from agent_wrapper.wrapper import call_sync

    record = call_sync(
        [
            {"role": "system", "content": _REFINE_SYSTEM},
            {"role": "user", "content": (
                f"Hypothesis:\n{hypothesis_text}\n\nDraft decomposition:\n"
                f"{json.dumps(fields, ensure_ascii=False)}\n\nReturn the JSON object."
            )},
        ],
        temperature=0.1,
        seed=0,
        max_tokens=400,
        caller_tag="claim_extract_refine",
    )
    completion = record["completion"]
    m = re.search(r"\{.*\}", completion, re.DOTALL)
    if not m:
        raise ValueError("refinement returned no JSON object")
    obj = json.loads(m.group(0))
    out = {}
    for key in ("problem", "mechanism", "predicted_effect"):
        val = obj.get(key)
        if not isinstance(val, str):
            raise ValueError(f"refinement missing/non-string field {key!r}")
        out[key] = val.strip()
    if not out["problem"] or not out["predicted_effect"]:
        raise ValueError("refinement emptied a required field")
    return out


# ── Public API ───────────────────────────────────────────────────────────────

def extract_claim(iteration_row: dict) -> dict[str, Any]:
    """Canonical claim record for one iteration row.

    Source text = hypothesis.text (blob-repaired when it is a leaked JSON
    candidates blob), falling back to seed.topic for a hypothesis-less legacy
    row. A row with neither RAISES ValueError — no silent empty claim.
    """
    hyp = iteration_row.get("hypothesis")
    text = hyp.get("text") if isinstance(hyp, dict) else None
    seed = iteration_row.get("seed") if isinstance(iteration_row.get("seed"), dict) else {}
    topic = seed.get("topic") if isinstance(seed.get("topic"), str) else ""

    if isinstance(text, str) and _looks_like_blob(text):
        text = _repair_blob(text)
    if not (isinstance(text, str) and text.strip()):
        text = topic
    if not (isinstance(text, str) and text.strip()):
        raise ValueError(
            "claim_extract: iteration row "
            f"{iteration_row.get('iteration_id')!r} has no hypothesis text and "
            "no seed topic — cannot fabricate a claim (rule 4)."
        )
    text = text.strip()

    fields = _derive_fields(text, topic)

    if not os.environ.get("MOCK_LLM"):
        # Real run: one low-temp refinement pass. Failure -> explicit, logged
        # fallback to the deterministic draft (rule 7).
        t0 = time.perf_counter()
        try:
            fields = _refine_fields(fields, text)
        except Exception as exc:  # noqa: BLE001 — logged, never silent
            from orchestrator import runtime
            runtime.append_run_log({
                "task_id": "claim_extract_refine",
                "status": "fallback",
                "observable_actual": (
                    f"refinement failed ({type(exc).__name__}: {exc}); "
                    "using deterministic derivation"
                ),
                "observable_expected": "refined {problem, mechanism, predicted_effect}",
                "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            })

    outcome = iteration_row.get("experiment_outcome")
    results_path = outcome.get("results_path") if isinstance(outcome, dict) else None
    journal = iteration_row.get("journal_entry_path")
    return {
        "problem": fields["problem"],
        "mechanism": fields["mechanism"],
        "predicted_effect": fields["predicted_effect"],
        "evidence_ref": {
            "iteration_id": str(iteration_row.get("iteration_id") or ""),
            "journal_entry_path": journal if isinstance(journal, str) and journal else None,
            "results_path": results_path if isinstance(results_path, str) and results_path else None,
        },
    }
