"""LOOP_V1 P1 — evidence ladder: pure rung derivation for a loop iteration.

Derives the evidence level (L0..L5) a `memory/loop_memory.jsonl` row has
actually EARNED, from the signals already on the row plus the human
feedback row, the adversarial-vote block, and the run's health signals.
Pure Python — no I/O, no LLM, never coerced (inviolate rule 4):

  L0  asserted        — the default; a hypothesis with no earned evidence.
  L1  literature-consistent
                      — retrieval.relevance present AND not low_confidence
                        AND novelty.class == "novel"
                        AND critique.verdict == "survives"
                        AND redteam.verdict != "fatal_flaw"
                        (redteam ABSENT is acceptable at L1 only).
  L2  synthetic       — experiment_outcome present, trials >= 30, and
                        summary not INVALID.
  L3  replicated      — cross_tier_comparison / replication evidence present.
  L4  adversarial     — adversarial_block survived == True
                        AND redteam.verdict == "proceed" (BOTH; the two
                        previously-ignored signals become the L3→L4 gate).
  L5  human-validated — feedback_row verdict == "valid".

Ladder semantics (the non-coercion core):

  - Rungs are climbed IN ORDER; the level is the highest rung whose every
    lower rung also passed. A missing signal NEVER passes a rung — absence
    halts the climb at the rung below.
  - redteam `fatal_flaw` is a HARD CAP below L1: a row with redteam
    fatal_flaw + critique survives never reaches L1, no matter what other
    evidence is present (today's blind spot, pinned by regression test).
  - adversarial survived == False caps below L4 even when everything
    lower passed.
  - `provisional: ["external_search_blind"]` marks a level earned while
    the iteration's ml-intern external search stored 0 papers
    (health signal `ml_intern_zero_papers`) — the literature rung was
    judged against local corpus only.

`next_test_owed(level)` names the test that advances each level, so the
coordinator can plan the next rung instead of re-asserting the current one.
"""
from __future__ import annotations

import re
from typing import Any

LEVELS = ["L0", "L1", "L2", "L3", "L4", "L5"]

# The test that advances FROM this level to the next rung.
_NEXT_TEST = {
    "L0": "literature-consistency pass (relevant retrieval + novel + critique survives + no redteam fatal_flaw)",
    "L1": "synthetic experiment",
    "L2": "robustness battery",
    "L3": "adversarial panel",
    "L4": "human review",
    "L5": "none — top rung",
}

_MIN_TRIALS = 30


_SURPRISE_RE = re.compile(r"Verdict=NO|signed_residual", re.IGNORECASE)


def _surprising_vs_theory(row: dict[str, Any]) -> bool:
    """The exp005-shaped alternative novelty route at L1: novelty 'unclear'
    (or 'novel') backed by a SOUND experiment whose summary ran against
    expectation (/Verdict=NO|signed_residual/i). A bad experiment (low
    trials, INVALID) never qualifies — the L2 soundness bar is reused, not
    relaxed."""
    novelty = row.get("novelty")
    if not isinstance(novelty, dict) or novelty.get("class") not in {"novel", "unclear"}:
        return False
    l2_passed, _ = _rung_l2(row)
    if not l2_passed:
        return False
    outcome = row.get("experiment_outcome") or {}
    return bool(_SURPRISE_RE.search(str(outcome.get("summary") or "")))


def _rung_l1(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """L1 literature-consistent. Returns (passed, missing/failure notes)."""
    missing: list[str] = []

    retrieval = row.get("retrieval")
    relevance = retrieval.get("relevance") if isinstance(retrieval, dict) else None
    if not isinstance(relevance, dict):
        missing.append("retrieval.relevance absent")
    elif relevance.get("low_confidence") is not False:
        missing.append("retrieval.relevance is low_confidence")

    novelty = row.get("novelty")
    if not isinstance(novelty, dict) or "class" not in novelty:
        missing.append("novelty.class absent")
    elif novelty.get("class") != "novel" and not _surprising_vs_theory(row):
        missing.append(
            f"novelty.class={novelty.get('class')!r} (need 'novel', and the "
            "result is not surprising-vs-theory)"
        )

    critique = row.get("critique")
    if not isinstance(critique, dict) or "verdict" not in critique:
        missing.append("critique.verdict absent")
    elif critique.get("verdict") != "survives":
        missing.append(f"critique.verdict={critique.get('verdict')!r} (need 'survives')")

    # redteam ABSENT is acceptable at L1; fatal_flaw is a hard cap below L1.
    redteam = row.get("redteam")
    if isinstance(redteam, dict) and redteam.get("verdict") == "fatal_flaw":
        missing.append("redteam.verdict=fatal_flaw (hard cap below L1)")

    return (not missing, missing)


def _rung_l2(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """L2 synthetic experiment: outcome present, trials >= 30, not INVALID."""
    missing: list[str] = []
    outcome = row.get("experiment_outcome")
    if not isinstance(outcome, dict) or not outcome:
        return (False, ["experiment_outcome absent"])

    trials = outcome.get("trials")
    if not isinstance(trials, int) or isinstance(trials, bool):
        missing.append("experiment_outcome.trials absent")
    elif trials < _MIN_TRIALS:
        missing.append(f"experiment_outcome.trials={trials} (need >= {_MIN_TRIALS})")

    summary = outcome.get("summary")
    if not isinstance(summary, str):
        missing.append("experiment_outcome.summary absent")
    elif "INVALID" in summary:
        missing.append("experiment_outcome.summary is INVALID")

    return (not missing, missing)


def _rung_l3(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """L3 replication: cross_tier_comparison evidence present."""
    ctc = row.get("cross_tier_comparison")
    if not isinstance(ctc, dict) or not ctc:
        return (False, ["cross_tier_comparison / replication evidence absent"])
    return (True, [])


def _rung_l4(
    row: dict[str, Any], adversarial_block: dict[str, Any] | None
) -> tuple[bool, list[str]]:
    """L4: adversarial survived == True AND redteam.verdict == 'proceed'."""
    missing: list[str] = []
    if not isinstance(adversarial_block, dict):
        missing.append("adversarial_block absent")
    elif adversarial_block.get("survived") is not True:
        missing.append("adversarial_block.survived is not True (caps below L4)")

    redteam = row.get("redteam")
    if not isinstance(redteam, dict) or "verdict" not in redteam:
        missing.append("redteam.verdict absent (missing signal never passes)")
    elif redteam.get("verdict") != "proceed":
        missing.append(f"redteam.verdict={redteam.get('verdict')!r} (need 'proceed')")

    return (not missing, missing)


def _rung_l5(feedback_row: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """L5: human feedback verdict == 'valid'."""
    if not isinstance(feedback_row, dict):
        return (False, ["human feedback_row absent"])
    verdict = feedback_row.get("verdict")
    if verdict != "valid":
        return (False, [f"feedback_row.verdict={verdict!r} (need 'valid')"])
    return (True, [])


def derive_level(
    row: dict[str, Any],
    feedback_row: dict[str, Any] | None,
    adversarial_block: dict[str, Any] | None,
    health_rows: list,
) -> dict[str, Any]:
    """Derive the earned evidence level for one loop-memory row.

    Returns {"level": "L0".."L5", "provisional": list[str],
             "missing_for_next": list[str], "reasons": list[str]}.

    Rungs are evaluated in order; the climb halts at the first rung that
    fails, and that rung's failure notes become `missing_for_next`.
    A redteam fatal_flaw halts at L0 unconditionally (hard cap).
    """
    reasons: list[str] = []

    rungs: list[tuple[str, tuple[bool, list[str]]]] = [
        ("L1", _rung_l1(row)),
        ("L2", _rung_l2(row)),
        ("L3", _rung_l3(row)),
        ("L4", _rung_l4(row, adversarial_block)),
        ("L5", _rung_l5(feedback_row)),
    ]

    level = "L0"
    missing_for_next: list[str] = []
    for name, (passed, notes) in rungs:
        if passed:
            level = name
            reasons.append(f"{name}: passed")
        else:
            missing_for_next = list(notes)
            reasons.append(f"{name}: NOT passed — " + "; ".join(notes))
            break
    else:
        reasons.append("L5: top rung — nothing further owed")

    provisional: list[str] = []
    iteration_id = row.get("iteration_id")
    for h in health_rows:
        if (
            isinstance(h, dict)
            and h.get("signal") == "ml_intern_zero_papers"
            and h.get("iteration_id") == iteration_id
        ):
            provisional.append("external_search_blind")
            break

    return {
        "level": level,
        "provisional": provisional,
        "missing_for_next": missing_for_next,
        "reasons": reasons,
    }


def next_test_owed(level: str) -> str:
    """The test that advances `level` to the next rung. Raises on unknown."""
    if level not in _NEXT_TEST:
        raise ValueError(f"unknown evidence level: {level!r}")
    return _NEXT_TEST[level]
