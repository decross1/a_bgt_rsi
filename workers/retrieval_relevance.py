"""LOOP_V0 critic-honesty helper — retrieval_relevance.

The 2026-06-09 autonomous iteration (`iter-2026-06-09-001`) exposed a
research-integrity failure: an OFF-DOMAIN topic (FASE / code quality)
retrieved 9 game-theory foundational books + 1 arXiv (all topically
IRRELEVANT) and the loop scored it `novel/survives` —

  - novelty said "novel" *because* the game-theory corpus omits semantic
    entropy;
  - the critic said "survives" *because* that irrelevant corpus "contains
    no contradiction."

Both verdicts are ARTIFACTS of irrelevant retrieval. Inviolate rule 4
(validations are never silently coerced): "no contradiction in an
IRRELEVANT corpus" is NOT "survives". The fix is a RELEVANCE SIGNAL the
verdict workers can read to emit a *low-confidence* flag instead of
asserting novel/survives on thin/off-domain retrieval.

This is a small PURE function — no new embedding, no LLM call. It reads
the two signals already present on every neighbor:

  1. the BGE-M3 cosine `score` (`1.0 - distance`), and
  2. the lexical overlap between the hypothesis and the neighbor's
     `chunk_text` + `title`.

Calibration (the decisive finding — `memory/loop_memory.jsonl`, 41
score-bearing iterations as of 2026-06-09): the raw cosine `score`
does NOT cleanly separate off-domain from on-domain — BGE-M3 cosines
cluster 0.53–0.74 and the bug iteration's max=0.603 sits *inside* the
on-domain band (e.g. `iter-2026-06-06-001` max=0.574, a real on-domain
novel). What DOES separate cleanly is the hypothesis↔neighbor LEXICAL
overlap: the bug iteration's max overlap is **0.043**, the single lowest
in the whole dataset by a wide margin (next-lowest on-domain is 0.069,
an `unclear`; on-domain novel/rediscovery verdicts sit 0.12–0.42). A
code-quality hypothesis retrieved against game-theory textbooks shares
almost no vocabulary — that is the off-domain fingerprint.

So the gate is overlap-driven, with the cosine `score` retained as a
secondary corroborating signal (and a guard for the empty / no-text
cases the score still catches). The thresholds below are calibrated
against those actual distributions and are deliberately CONSERVATIVE —
they fire on the genuine off-domain outlier, not on borderline
on-domain retrieval. A near-miss is reported honestly (rule 4); it is
never coerced into "relevant".

Output (consumed by `novelty_classify` / `critic_loop_v0`, cached on
`retrieval.relevance`):
  - `relevance`      — float in [0, 1]; the blended relevance score
                       (higher = more topically grounded).
  - `low_confidence` — bool; True when retrieval is thin/irrelevant and
                       the verdict workers MUST temper (never assert
                       novel/survives).
  - `reason`         — short human-readable explanation of the verdict.
"""
from __future__ import annotations

import re
from typing import Any


# ---- Calibrated thresholds (see module docstring for the data) -------------
#
# OVERLAP is the primary discriminator. The bug iteration sat at 0.043;
# the lowest on-domain at 0.069. 0.05 cleanly splits them with margin on
# both sides. We gate the MEAN of the top-3 neighbor overlaps (more robust
# than a single max — one accidentally-overlapping neighbor can't rescue an
# otherwise off-domain set; bug top-3 mean = 0.029, lowest on-domain = 0.046).
LOW_OVERLAP_THRESHOLD = 0.05

# COSINE is the secondary signal. retrieve_literature already treats
# max_score < 0.62 as a *weak* signal worth an ml-intern escalation; we use a
# lower floor here (we only want to flag genuinely thin retrieval, and several
# real on-domain iterations have max cosine in the 0.53–0.60 band). A set is
# corroborated-thin only when BOTH the overlap is borderline AND the cosine is
# weak — neither alone downgrades an otherwise on-domain set.
WEAK_COSINE_THRESHOLD = 0.55

# How many top neighbors feed the overlap mean.
TOP_N_FOR_OVERLAP = 3

# Token cleaning. Domain-agnostic English stopwords plus a few game-theory
# words that recur in nearly every foundational neighbor regardless of the
# query topic ("nash", "equilibrium", "game(s)") — counting them as overlap
# would falsely rescue an off-domain set retrieved against the GT corpus.
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_STOPWORDS = frozenset(
    (
        "the and for with that this from are was its has have not can may which "
        "when where what how into onto over under between among per via using "
        "used use uses both each other than then them they their there these "
        "those some any all one two three four five six but our her his she him "
        "you your will would should could about within without across through "
        "such more most less least also given whether against toward towards "
        "nash equilibrium game games"
    ).split()
)


def _tokenize(text: Any) -> set[str]:
    """Lowercase content tokens (len>=3), stopwords removed. Non-str -> {}."""
    if not isinstance(text, str):
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def _neighbor_overlap(hyp_tokens: set[str], neighbor: dict) -> float:
    """Fraction of hypothesis tokens that appear in this neighbor's
    chunk_text + title. 0.0 when either side is empty."""
    if not hyp_tokens or not isinstance(neighbor, dict):
        return 0.0
    n_tokens = _tokenize(neighbor.get("chunk_text")) | _tokenize(neighbor.get("title"))
    if not n_tokens:
        return 0.0
    return len(hyp_tokens & n_tokens) / len(hyp_tokens)


def relevance(
    neighbors: list[dict] | None,
    hypothesis_text: str | None = None,
) -> dict[str, Any]:
    """Score how topically relevant a retrieval set is to the hypothesis.

    Pure + cheap: reads the cosine `score` already on each neighbor and the
    lexical overlap between the hypothesis and each neighbor's text. No new
    embedding, no LLM call.

    Args:
        neighbors: the `retrieval.neighbors` list (each a dict with at least
            `score`, and ideally `chunk_text` / `title`). None or [] -> the
            empty-retrieval case (low_confidence True).
        hypothesis_text: the hypothesis under test. When absent/empty the
            lexical signal can't be computed and the function falls back to
            the cosine-only signal (and says so in `reason`).

    Returns:
        {"relevance": float in [0,1], "low_confidence": bool, "reason": str}
    """
    # --- empty / malformed retrieval: cannot be a basis for novel/survives ---
    if not isinstance(neighbors, list) or len(neighbors) == 0:
        return {
            "relevance": 0.0,
            "low_confidence": True,
            "reason": "empty retrieval (0 neighbors); no basis to assert novelty or survival",
        }

    scores = [
        n.get("score") for n in neighbors
        if isinstance(n, dict) and isinstance(n.get("score"), (int, float))
    ]
    max_cosine = max(scores) if scores else 0.0

    hyp_tokens = _tokenize(hypothesis_text)
    have_text_signal = bool(hyp_tokens) and any(
        _tokenize(n.get("chunk_text")) or _tokenize(n.get("title"))
        for n in neighbors if isinstance(n, dict)
    )

    if have_text_signal:
        overlaps = sorted(
            (_neighbor_overlap(hyp_tokens, n) for n in neighbors), reverse=True
        )
        top = overlaps[:TOP_N_FOR_OVERLAP]
        mean_top_overlap = sum(top) / len(top)
        # Blend overlap (primary) with cosine (secondary), clamped to [0,1].
        rel = round(min(1.0, 0.7 * (mean_top_overlap / LOW_OVERLAP_THRESHOLD * 0.5)
                        + 0.3 * max(0.0, max_cosine)), 4)
        low_overlap = mean_top_overlap < LOW_OVERLAP_THRESHOLD
        weak_cosine = max_cosine < WEAK_COSINE_THRESHOLD
        if low_overlap:
            return {
                "relevance": rel,
                "low_confidence": True,
                "reason": (
                    f"off-domain retrieval: hypothesis shares almost no vocabulary "
                    f"with its neighbors (mean top-{len(top)} lexical overlap "
                    f"{mean_top_overlap:.3f} < {LOW_OVERLAP_THRESHOLD}; "
                    f"max cosine {max_cosine:.3f}). 'No contradiction in an "
                    f"irrelevant corpus' is not 'survives'."
                ),
            }
        if weak_cosine and mean_top_overlap < 2 * LOW_OVERLAP_THRESHOLD:
            # Borderline on both signals — thin but not a clean outlier.
            return {
                "relevance": rel,
                "low_confidence": True,
                "reason": (
                    f"thin retrieval: borderline lexical overlap "
                    f"(mean top-{len(top)} {mean_top_overlap:.3f}) and weak cosine "
                    f"(max {max_cosine:.3f} < {WEAK_COSINE_THRESHOLD})."
                ),
            }
        return {
            "relevance": rel,
            "low_confidence": False,
            "reason": (
                f"on-domain retrieval: mean top-{len(top)} lexical overlap "
                f"{mean_top_overlap:.3f} >= {LOW_OVERLAP_THRESHOLD}, "
                f"max cosine {max_cosine:.3f}."
            ),
        }

    # --- no lexical signal: fall back to cosine-only (rule 7: explicit) ------
    rel = round(max(0.0, min(1.0, max_cosine)), 4)
    weak = max_cosine < WEAK_COSINE_THRESHOLD
    why = (
        "(no hypothesis/neighbor text available; cosine-only relevance) "
        if hypothesis_text else
        "(no hypothesis text supplied; cosine-only relevance) "
    )
    if weak:
        return {
            "relevance": rel,
            "low_confidence": True,
            "reason": why + f"weak max cosine {max_cosine:.3f} < {WEAK_COSINE_THRESHOLD}.",
        }
    return {
        "relevance": rel,
        "low_confidence": False,
        "reason": why + f"max cosine {max_cosine:.3f} >= {WEAK_COSINE_THRESHOLD}.",
    }
