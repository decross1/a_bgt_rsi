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

Those three keys are FROZEN (UI join contract, commit 0fdb671). The T1a
refinement (2026-06-09 evening) adds ADDITIVE diagnostic keys:
  - `anchor_cosine`   — float|None; hypothesis↔GT-domain-anchor cosine as
                        passed in by the caller (None = unavailable).
  - `curated_overlap` — float|None; mean top-3 lexical overlap over
                        foundational-layer neighbors only.
  - `neighbor_spread` — float|None; max-min of the top-10 neighbor scores.
  - `topicality`      — "on"|"off"|"off_independent"|"unsure"|None; the
                        caller-computed LLM domain judgment
                        (orchestrator/topicality.py). R0; "off_independent"
                        (the env-gated independent attack) fires R0b.
  - `category`        — "off_domain"|"thin"|"no_sharp_match"|"empty"|"ok".
  - `rule_fired`      — str|None; first rule in the R0..R5 ladder that fired.

D-053 (2026-06-15) adds a further-additive, env-gated, NON-GATING field:
  - `r0_advisory`     — "off"; present ONLY when NARA_R0_ADVISORY=1 AND the
                        primary R0 judge said "off". It DEMOTES the primary
                        R0 gate to a human-facing advisory: low_confidence is
                        then driven by the lexical/cosine ladder, never by R0,
                        so an on-domain-novel claim R0 mislabels "off" is no
                        longer downgraded. With the flag unset the key is
                        absent and R0 gates exactly as before (byte-identical).
                        Mirrors the D-052 relevance.topicality_advisory shape.

D-075 R2 (2026-08-18, owner-ratified) adds a further-additive field:
  - `domain_anchor_term` — str; present ONLY when the LLM topicality judge
                        said "off"/"off_independent" AND the hypothesis
                        matches a curated DOMAIN_ANCHOR_PHRASES entry (the
                        program's owner-ratified extension into delegation /
                        liquid democracy / social choice / sortition /
                        mechanism design). The LLM kill is then DEMOTED —
                        the active research program is in-domain to its own
                        gates BY CONSTRUCTION — and the lexical/cosine
                        ladder owns the gate (same recursion shape as
                        r0_advisory). The anchor only demotes the LLM kill;
                        it NEVER rescues from the ladder itself (empty/thin/
                        R1..R5 still gate). Diagnosis: 20/21 August
                        off-domain kills were the lab's OWN active topic
                        (wf_c806049b).
"""
from __future__ import annotations

import os
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

# ---- T1a anchor + spread rules (R3/R4/R5) — SHIPPED DISABLED ----------------
#
# The 2026-06-09 falsification battery showed the lexical gate is
# vocabulary-gameable (off-domain probes at overlap 0.127 / 0.193 sail
# through; the real bug was 0.043), and the iteration-068 review showed a
# top-10 neighbor score spread of 0.027 at moderate absolute similarity
# (0.604-0.631) is the signature of "no sharp match — query landed near a
# cluster centroid", which must flag rather than read as confident
# retrieval. Two new signals close those holes:
#
#   - anchor_cosine: hypothesis ↔ GT-domain-anchor cosine, computed by the
#     CALLER via orchestrator/domain_anchor.py and passed in (this function
#     stays pure — no embedding here). Rules R3 (hard off-domain) and R4
#     (borderline anchor + weak lexical corroboration).
#   - neighbor_spread: max-min of the top-10 neighbor scores. Rule R5
#     (no-sharp-match) fires on a tight spread at sub-SPREAD_COSINE_CEIL
#     absolute similarity.
#
# ANCHOR_LOW / ANCHOR_BORDERLINE / SPREAD_MAX ship as None: R3/R4/R5 are
# INERT until the INTEGRATOR sets them, and ONLY after calibration against
# a varied probe set — never a single instance (P-009). With them None and
# anchor_cosine=None the function reduces exactly to the legacy lexical
# gate. INVARIANT: the anchor only CONDEMNS, never rescues — R1/R2 are
# evaluated first and a high anchor cosine cannot suppress them.
ANCHOR_LOW = None          # R3: anchor_cosine < ANCHOR_LOW -> off_domain
ANCHOR_BORDERLINE = None   # R4: borderline anchor + weak lexical corroboration -> thin
SPREAD_MAX = None          # R5: top-10 score spread below this -> no_sharp_match
SPREAD_COSINE_CEIL = 0.66  # R5 also requires max cosine below this ceiling

# How many top neighbors feed the spread diagnostic.
TOP_N_FOR_SPREAD = 10

# ---- D-075 R2: curated in-domain anchor phrases (2026-08-18) ---------------
#
# The August diagnosis (wf_c806049b): 20/21 off-domain kills were the lab's
# OWN active topic — the R0/R0b LLM topicality judges kill delegation /
# liquid-democracy / social-choice hypotheses because their domain framing
# predates the program's owner-ratified extension into computational social
# choice. These phrases are the curated extension of the research program's
# domain: a hypothesis matching one is in-domain BY CONSTRUCTION (D-075 R2:
# "the active research program must be in-domain to its own gates by
# construction"), so an LLM "off"/"off_independent" verdict is DEMOTED — the
# lexical/cosine ladder owns the gate — instead of condemning outright.
#
# ADDITIVE ONLY. The condemn-side rules (R1..R5, empty) are untouched: the
# anchor demotes the LLM kill, it never rescues a hypothesis from the ladder.
# Matching is word-boundary, case-insensitive, with an optional plural "s" on
# the final word — multi-word phrases and unambiguous domain terms only, to
# keep the set hard to vocabulary-game (the D-045 lesson).
DOMAIN_ANCHOR_PHRASES = (
    "liquid democracy",
    "delegative democracy",
    "delegative voting",
    "delegated voting",
    "proxy voting",
    "vote delegation",
    "voting delegation",
    "transitive delegation",
    "delegation game",
    "delegation graph",
    "delegation network",
    "sortition",
    "social choice",
    "voting power",
    "power index",
    "voting rule",
    "mechanism design",
    "peer selection",
    "committee selection",
    "multiwinner voting",
    "participatory budgeting",
    "preference aggregation",
    "condorcet",
    "borda count",
)

_DOMAIN_ANCHOR_RES = tuple(
    re.compile(r"\b" + re.escape(p) + r"s?\b") for p in DOMAIN_ANCHOR_PHRASES
)


def _domain_anchor_hit(text: Any) -> str | None:
    """First DOMAIN_ANCHOR_PHRASES entry present in `text` (word-boundary,
    case-insensitive, optional trailing plural), else None. Non-str -> None."""
    if not isinstance(text, str) or not text:
        return None
    low = text.lower()
    for phrase, rx in zip(DOMAIN_ANCHOR_PHRASES, _DOMAIN_ANCHOR_RES):
        if rx.search(low):
            return phrase
    return None


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


def _out(
    rel: float,
    low: bool,
    reason: str,
    category: str,
    rule: str | None,
    diag: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the output dict: the three FROZEN keys (UI join contract,
    commit 0fdb671) plus the additive diagnostic keys."""
    return {
        "relevance": rel,
        "low_confidence": low,
        "reason": reason,
        "anchor_cosine": diag["anchor_cosine"],
        "curated_overlap": diag["curated_overlap"],
        "neighbor_spread": diag["neighbor_spread"],
        "topicality": diag.get("topicality"),
        "category": category,
        "rule_fired": rule,
    }


def _condemn(
    anchor: float | None,
    mean_overlap: float | None,
    curated: float | None,
    spread: float | None,
    max_cosine: float,
    n_neighbors: int,
) -> tuple[str, str, str] | None:
    """Evaluate the condemn-only rules R3/R4/R5 (in ladder order). Returns
    (rule, category, reason) for the first that fires, else None. All three
    are inert while their gating constants are None (shipped state)."""
    # R3: hard off-domain by anchor — the hypothesis itself does not live in
    # the curated domain, regardless of how its neighbors read lexically.
    if anchor is not None and ANCHOR_LOW is not None and anchor < ANCHOR_LOW:
        return ("R3", "off_domain", (
            f"off-domain by domain anchor: hypothesis-to-GT-anchor cosine "
            f"{anchor:.3f} < {ANCHOR_LOW} — lexical overlap cannot rescue a "
            f"hypothesis that does not live in the curated domain."
        ))
    # R4: borderline anchor, corroborated by weak lexical signal — overall
    # mean top-3 overlap under 0.10 OR curated(foundational-only) overlap
    # under 0.05.
    if (
        anchor is not None and ANCHOR_BORDERLINE is not None
        and anchor < ANCHOR_BORDERLINE
        and (
            (mean_overlap is not None and mean_overlap < 2 * LOW_OVERLAP_THRESHOLD)
            or (curated is not None and curated < LOW_OVERLAP_THRESHOLD)
        )
    ):
        mo = "n/a" if mean_overlap is None else f"{mean_overlap:.3f}"
        co = "n/a" if curated is None else f"{curated:.3f}"
        return ("R4", "thin", (
            f"thin by domain anchor: borderline anchor cosine {anchor:.3f} < "
            f"{ANCHOR_BORDERLINE} with weak lexical corroboration (mean top-"
            f"{TOP_N_FOR_OVERLAP} overlap {mo}, curated-foundational overlap {co})."
        ))
    # R5: no sharp match — a tight top-10 score spread at moderate absolute
    # similarity means the query landed near a cluster centroid, not on a
    # genuinely matching chunk (iteration-068 fingerprint: spread 0.027 over
    # scores 0.604-0.631).
    if (
        SPREAD_MAX is not None and SPREAD_COSINE_CEIL is not None
        and n_neighbors >= 8 and spread is not None
        and spread < SPREAD_MAX and max_cosine < SPREAD_COSINE_CEIL
    ):
        return ("R5", "no_sharp_match", (
            f"no sharp match: top-{min(n_neighbors, TOP_N_FOR_SPREAD)} neighbor "
            f"score spread {spread:.3f} < {SPREAD_MAX} at moderate similarity "
            f"(max cosine {max_cosine:.3f} < {SPREAD_COSINE_CEIL}) — the query "
            f"landed near a cluster centroid, not on a matching chunk."
        ))
    return None


def relevance(
    neighbors: list[dict] | None,
    hypothesis_text: str | None = None,
    *,
    anchor_cosine: float | None = None,
    topicality: str | None = None,
) -> dict[str, Any]:
    """Score how topically relevant a retrieval set is to the hypothesis.

    Pure + cheap: reads the cosine `score` already on each neighbor and the
    lexical overlap between the hypothesis and each neighbor's text. No new
    embedding, no LLM call — `anchor_cosine` is computed by the CALLER
    (orchestrator/domain_anchor.py) and passed in.

    Args:
        neighbors: the `retrieval.neighbors` list (each a dict with at least
            `score`, and ideally `chunk_text` / `title` / `source_layer`).
            None or [] -> the empty-retrieval case (low_confidence True).
        hypothesis_text: the hypothesis under test. When absent/empty the
            lexical signal can't be computed and the function falls back to
            the cosine-only signal (and says so in `reason`).
        anchor_cosine: hypothesis-to-GT-domain-anchor cosine, or None when
            unavailable (MOCK_LLM / anchor not built / embed failure). None
            reduces EXACTLY to legacy behavior — anchor rules never fire.

    Returns (frozen keys first, additive keys after):
        {"relevance": float in [0,1], "low_confidence": bool, "reason": str,
         "anchor_cosine": float|None, "curated_overlap": float|None,
         "neighbor_spread": float|None, "topicality": str|None,
         "category": "off_domain"|"thin"|"no_sharp_match"|"empty"|"ok",
         "rule_fired": str|None}

    Rule ladder (low_confidence = any fired; rule_fired = first fired):
        R0  topicality == "off"                    -> off_domain (LLM check)
        R0b topicality == "off_independent"        -> off_domain (independent
                                                      topicality attack)
        R1 overlap < 0.05                          -> off_domain (legacy)
        R2 maxcos < 0.55 and overlap < 0.10        -> thin       (legacy)
        R3 anchor < ANCHOR_LOW                     -> off_domain
        R4 anchor < ANCHOR_BORDERLINE + weak lex   -> thin
        R5 tight top-10 spread at maxcos < ceiling -> no_sharp_match
    The legacy cosine-only fallback (no text signal, weak max cosine) keeps
    category "thin" with rule_fired None — it predates the ladder.

    D-075 R2: R0/R0b are DEMOTED (never fire) when the hypothesis matches a
    curated DOMAIN_ANCHOR_PHRASES entry — the program's ratified extension
    into delegation / liquid democracy / social choice / sortition /
    mechanism design. The matched phrase rides as `domain_anchor_term`; the
    ladder (empty/R1..R5) still gates normally.

    topicality is an explicit LLM domain judgment computed by the caller
    (orchestrator/topicality.py): "on" | "off" | "unsure" | None. Added
    2026-06-09 after BOTH corpus-derived anchor variants were falsified as
    separators (calibration gap -0.079 / -0.075: a genuinely novel
    on-domain hypothesis is far from the corpus BY DEFINITION, same as a
    camouflaged off-domain one — distance-to-known-content conflates the
    two). Only the literal "off" (R0, primary judge) and "off_independent"
    (R0b, 2026-06-10 D-045 residual 1: the primary judge passed it but the
    env-gated independent attack — orchestrator/topicality_skeptic.py —
    condemned) fire; "on"/"unsure"/None never gate (over-gating guard —
    the canary cases are part of the battery bar).
    """
    # --- R0 ADVISORY DEMOTION (env-gated, DARK by default) -------------------
    # The primary R0 judge ("off") and a camouflaged off-domain claim are
    # INSEPARABLE from hypothesis text alone (confirmed 4× — D-045/D-050/
    # D-052 + docs/overgating_promotion_analysis.md): R0 over-gates the
    # on-domain novel case `novel_on_02` exactly as it catches the off-domain
    # `fase_off_01`. NARA_R0_ADVISORY=1 demotes the PRIMARY judge from a gate
    # to a NON-GATING advisory, mirroring the D-052 topicality_advisory shape:
    # the verdict ("off") rides as the ADDITIVE `r0_advisory` field and NEVER
    # sets low_confidence — we re-score with R0 demoted (topicality=None) so
    # the lexical/cosine ladder owns the gate, then tack the advisory on.
    # With the flag UNSET this branch is skipped entirely and the R0 path
    # below is byte-identical to before (no r0_advisory key, "off" gates).
    # SCOPE: only the primary "off" is demoted. "off_independent" (R0b, the
    # independent skeptic, env-gated under NARA_TOPICALITY_SKEPTIC) is a
    # distinct judge and keeps its existing gating behavior here.
    if topicality == "off" and os.environ.get("NARA_R0_ADVISORY", "0") == "1":
        out = relevance(
            neighbors, hypothesis_text,
            anchor_cosine=anchor_cosine, topicality=None,
        )
        out["r0_advisory"] = "off"
        return out

    # --- D-075 R2: curated domain-anchor demotion (ALWAYS ON, additive) -----
    # An LLM "off"/"off_independent" verdict on a hypothesis that matches the
    # curated program-domain anchors (DOMAIN_ANCHOR_PHRASES) is demoted, not
    # obeyed: the active research program is in-domain to its own gates by
    # construction. Same recursion shape as the r0_advisory demotion — the
    # lexical/cosine ladder owns the gate (empty/R1..R5 still condemn), and
    # the matched phrase rides as the additive `domain_anchor_term` key so
    # the demotion is visible downstream. Non-anchor hypotheses fall through
    # to the R0/R0b block byte-identically.
    if topicality in ("off", "off_independent"):
        _anchor_term = _domain_anchor_hit(hypothesis_text)
        if _anchor_term is not None:
            out = relevance(
                neighbors, hypothesis_text,
                anchor_cosine=anchor_cosine, topicality=None,
            )
            out["domain_anchor_term"] = _anchor_term
            return out

    # --- R0/R0b: explicit LLM topicality judgment (condemn-only, like the
    # anchor). "off" = the primary judge; "off_independent" = the primary
    # judge passed it and the independent skeptic condemned (check() only
    # emits it under NARA_TOPICALITY_SKEPTIC=1).
    if topicality in ("off", "off_independent"):
        if topicality == "off":
            rule, reason = "R0", (
                "off-domain hypothesis (LLM topicality check): the claim is "
                "not primarily a game-theory / behavioral-GT / "
                "learning-in-games question, so this corpus cannot ground "
                "novelty or survival."
            )
        else:
            rule, reason = "R0b", (
                "off-domain by independent topicality attack (the "
                "NARA_SKEPTIC_BACKEND judge): the primary judge passed it, "
                "but the independent skeptic judged the claim's primary "
                "subject outside game theory, so this corpus cannot ground "
                "novelty or survival."
            )
        return _out(
            0.0, True, reason, "off_domain", rule,
            {"anchor_cosine": anchor_cosine, "curated_overlap": None,
             "neighbor_spread": None, "topicality": topicality},
        )
    # --- empty / malformed retrieval: cannot be a basis for novel/survives ---
    if not isinstance(neighbors, list) or len(neighbors) == 0:
        return _out(
            0.0, True,
            "empty retrieval (0 neighbors); no basis to assert novelty or survival",
            "empty", None,
            {"anchor_cosine": anchor_cosine, "curated_overlap": None,
             "neighbor_spread": None, "topicality": topicality},
        )

    scores = [
        n.get("score") for n in neighbors
        if isinstance(n, dict) and isinstance(n.get("score"), (int, float))
    ]
    max_cosine = max(scores) if scores else 0.0
    top_scores = sorted(scores, reverse=True)[:TOP_N_FOR_SPREAD]
    neighbor_spread = (
        round(top_scores[0] - top_scores[-1], 4) if top_scores else None
    )

    hyp_tokens = _tokenize(hypothesis_text)
    have_text_signal = bool(hyp_tokens) and any(
        _tokenize(n.get("chunk_text")) or _tokenize(n.get("title"))
        for n in neighbors if isinstance(n, dict)
    )

    mean_top_overlap: float | None = None
    curated_overlap: float | None = None
    if have_text_signal:
        overlaps = sorted(
            (_neighbor_overlap(hyp_tokens, n) for n in neighbors), reverse=True
        )
        top = overlaps[:TOP_N_FOR_OVERLAP]
        mean_top_overlap = sum(top) / len(top)
        # Curated overlap: foundational-source neighbors only. The live
        # layers can lexically echo a gamed hypothesis; the human-curated
        # corpus is the harder-to-game reference.
        curated = sorted(
            (_neighbor_overlap(hyp_tokens, n) for n in neighbors
             if isinstance(n, dict) and n.get("source_layer") == "foundational"),
            reverse=True,
        )
        if curated:
            top_c = curated[:TOP_N_FOR_OVERLAP]
            curated_overlap = round(sum(top_c) / len(top_c), 4)

    diag = {
        "anchor_cosine": anchor_cosine,
        "curated_overlap": curated_overlap,
        "neighbor_spread": neighbor_spread,
        "topicality": topicality,
    }

    if have_text_signal:
        # Blend overlap (primary) with cosine (secondary), clamped to [0,1].
        rel = round(min(1.0, 0.7 * (mean_top_overlap / LOW_OVERLAP_THRESHOLD * 0.5)
                        + 0.3 * max(0.0, max_cosine)), 4)
        # R1/R2 FIRST — the anchor only condemns, never rescues: a high
        # anchor_cosine must not suppress the legacy lexical rules.
        if mean_top_overlap < LOW_OVERLAP_THRESHOLD:
            return _out(rel, True, (
                f"off-domain retrieval: hypothesis shares almost no vocabulary "
                f"with its neighbors (mean top-{len(top)} lexical overlap "
                f"{mean_top_overlap:.3f} < {LOW_OVERLAP_THRESHOLD}; "
                f"max cosine {max_cosine:.3f}). 'No contradiction in an "
                f"irrelevant corpus' is not 'survives'."
            ), "off_domain", "R1", diag)
        if max_cosine < WEAK_COSINE_THRESHOLD and mean_top_overlap < 2 * LOW_OVERLAP_THRESHOLD:
            # Borderline on both signals — thin but not a clean outlier.
            return _out(rel, True, (
                f"thin retrieval: borderline lexical overlap "
                f"(mean top-{len(top)} {mean_top_overlap:.3f}) and weak cosine "
                f"(max {max_cosine:.3f} < {WEAK_COSINE_THRESHOLD})."
            ), "thin", "R2", diag)
        hit = _condemn(anchor_cosine, mean_top_overlap, curated_overlap,
                       neighbor_spread, max_cosine, len(neighbors))
        if hit is not None:
            rule, category, reason = hit
            return _out(rel, True, reason, category, rule, diag)
        return _out(rel, False, (
            f"on-domain retrieval: mean top-{len(top)} lexical overlap "
            f"{mean_top_overlap:.3f} >= {LOW_OVERLAP_THRESHOLD}, "
            f"max cosine {max_cosine:.3f}."
        ), "ok", None, diag)

    # --- no lexical signal: fall back to cosine-only (rule 7: explicit) ------
    rel = round(max(0.0, min(1.0, max_cosine)), 4)
    why = (
        "(no hypothesis/neighbor text available; cosine-only relevance) "
        if hypothesis_text else
        "(no hypothesis text supplied; cosine-only relevance) "
    )
    # R3/R5 can still condemn without text (R4 needs a lexical signal).
    hit = _condemn(anchor_cosine, None, None,
                   neighbor_spread, max_cosine, len(neighbors))
    if hit is not None:
        rule, category, reason = hit
        return _out(rel, True, why + reason, category, rule, diag)
    if max_cosine < WEAK_COSINE_THRESHOLD:
        return _out(
            rel, True,
            why + f"weak max cosine {max_cosine:.3f} < {WEAK_COSINE_THRESHOLD}.",
            "thin", None, diag,
        )
    return _out(
        rel, False,
        why + f"max cosine {max_cosine:.3f} >= {WEAK_COSINE_THRESHOLD}.",
        "ok", None, diag,
    )
