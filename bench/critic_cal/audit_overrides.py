"""DELIVERABLE 2 — override-chain audit. Deterministic, ZERO model calls.

Prereg: experiments/PREREG_critic_cal_2026-08-19.md (v2), sections 14-19.

Answers, over the existing record alone: what did the PRIMARY literature
critic say, what overrode it, to what, and what did the override cost
downstream? No LLM, no network, no writes outside the artifact named by
``--out``.

Three things this module does differently from the v1 draft, each a v2
correction (see the prereg changelog):

  1. ``blocked_by_override`` is computed on the REAL L1 rung
     (workers.evidence_ladder.derive_level, which finding_promotion.py
     delegates to) — NOT on thesis_to_experiment.is_eligible alone. The
     is_eligible-only figure is still reported, named
     ``t2e_blocked_loose``, as the loose upper bound it is. The two
     differ by 2.6x on the current record and the loose one flatters the
     override chain's importance.
  2. The 59 undecidables are censused by the PACK-RELEVANCE STATE
     RECORDED AT THE TIME, so a NATIVE undecidable emitted on a pack the
     apparatus itself flagged off_domain (where the critic's own prompt
     instructs it to say exactly that) is never pooled with a NATIVE
     undecidable on a clean pack.
  3. Cluster state is reconstructed with workers.idea_ledger.load_state
     — the canonical FILE-ORDER fold that the UI and coordinator already
     use — not a re-implemented "timestamp order" fold. memory/
     idea_ledger.jsonl has 37 duplicate-timestamp groups (one shared by
     190 events), so a timestamp sort has no defined answer; file order
     is the append order and is the only reproducible one.

Determinism: same inputs -> byte-identical artifact. Every emitted
collection is sorted by an explicit key; no dict/set iteration order
reaches the output; unit-tested under shuffled loop_memory input and
three PYTHONHASHSEEDs (this repo shipped a hash-seed ordering bug on
2026-08-18).

Coverage invariants are HARD (inviolate rule 4 — never coerced): rows
read == rows emitted, class counts sum to their totals, and the
single-level-override invariant is asserted per row rather than assumed.
A violation raises AuditInvariantError and writes nothing.

Usage:
    .venv-chroma/bin/python -m bench.critic_cal.audit_overrides \\
        --out bench/critic_cal/runs/override_audit.json
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOOP_MEMORY_PATH = REPO_ROOT / "memory" / "loop_memory.jsonl"
IDEA_LEDGER_PATH = REPO_ROOT / "memory" / "idea_ledger.jsonl"
LOOP_FEEDBACK_PATH = REPO_ROOT / "memory" / "loop_feedback.jsonl"

PREREG = "experiments/PREREG_critic_cal_2026-08-19.md"

# override_class keys on the reason PREFIX, never a substring: a substring
# test for "debate" mis-sorts skeptic rows whose own prose contains the
# word (two 07-06 rows do). Order matters — first match wins.
OVERRIDE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("relevance category ", "RELEVANCE_CATEGORY"),
    ("relevance low_confidence is true:", "RELEVANCE_LOWCONF"),
    ("debate verdict=", "DEBATE"),
    ("skeptic attack_verdict=", "SKEPTIC"),
    ("restatement skeptic (", "RESTATE_SKEPTIC"),
)
# The two RELEVANCE sub-branches roll up for the headline census.
RELEVANCE_CLASSES = ("RELEVANCE_CATEGORY", "RELEVANCE_LOWCONF")

# Regime marks — every time series is annotated with these, and counts
# either side of one are never pooled without the split being shown.
REGIME_MARKS: tuple[dict[str, str], ...] = (
    {"date": "2026-08-18", "mark": "D-071 bounded debate ARMED"},
    {"date": "2026-08-18", "mark": "D-075 R3a debate turn cap 4 -> 6"},
    {"date": "2026-08-18", "mark": "D-075 R2 curated phrase-anchor R0 demotion"},
    {"date": "2026-08-18", "mark": "D-075 R3b skeptic_infra_error flag introduced"},
)

INFRA_FLAVOR_SUBSTRING = "unparseable or off-enum"


class AuditInvariantError(RuntimeError):
    """A coverage / consistency invariant failed. Never coerced."""


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-row classification (pure)
# ---------------------------------------------------------------------------

def classify_override(critique: dict) -> tuple[str, str | None]:
    """(override_class, override_reason) for one critique block.

    NATIVE when there is no verdict_overridden_from. Otherwise the first
    matching reason PREFIX. Anything unmatched is OTHER and is printed
    row-by-row rather than silently pooled.
    """
    if "verdict_overridden_from" not in critique:
        return "NATIVE", None
    reason = critique.get("override_reason") or ""
    for prefix, cls in OVERRIDE_PREFIXES:
        if reason.startswith(prefix):
            return cls, reason
    return "OTHER", reason


def pack_state(row: dict) -> str:
    """The pack-relevance state RECORDED AT THE TIME of the critic call.

    adequate  — category in (absent, 'ok') and not low_confidence. The
                critic's user prompt carried NO relevance warning.
    flagged   — low_confidence true, or category present and != 'ok'. The
                RETRIEVAL RELEVANCE WARNING (critic_loop_v0.py:653-660)
                WAS in the prompt, instructing the critic that absence of
                contradiction here is not 'survives'.
    absent    — no retrieval block at all.
    """
    retrieval = row.get("retrieval")
    if not isinstance(retrieval, dict):
        return "absent"
    rel = retrieval.get("relevance")
    if not isinstance(rel, dict):
        return "adequate"  # legacy rows: worker treats missing category as ok
    if rel.get("low_confidence"):
        return "flagged"
    cat = rel.get("category")
    if cat is not None and cat != "ok":
        return "flagged"
    return "adequate"


def asserted_refutation(critique: dict, override_class: str) -> bool:
    """True iff the OVERRIDER's own verdict was a refutation.

    Coverage overrides and every 'inconclusive' are False — running out
    of rounds is not a refutation, and neither is a statement about the
    corpus.
    """
    if override_class == "DEBATE":
        debate = critique.get("debate")
        return isinstance(debate, dict) and debate.get("verdict") == "refuted"
    if override_class == "SKEPTIC":
        return (critique.get("override_reason") or "").startswith(
            "skeptic attack_verdict='refuted'"
        )
    return False


def infra_flavored(critique: dict) -> bool:
    """True iff this override was an INFRASTRUCTURE failure wearing a
    verdict's clothes.

    skeptic_infra_error (D-075 R3b) is 0 across the whole ledger because
    the flag POSTDATES every row that would carry it, so the flag alone
    is not an infra census. challenger_error and the unparseable-skeptic
    reason are the same event under older code.
    """
    if critique.get("skeptic_infra_error"):
        return True
    debate = critique.get("debate")
    if isinstance(debate, dict) and debate.get("stop_reason") == "challenger_error":
        return True
    return INFRA_FLAVOR_SUBSTRING in (critique.get("override_reason") or "")


def undecidable_kind(critique: dict) -> str | None:
    """substantive | schema_mismatch | timeout | unknown — or None when the
    verdict is not undecidable. `timeout` has NEVER fired on the record;
    it is kept as a defensive category so a first occurrence is itself a
    signal."""
    if critique.get("verdict") != "undecidable":
        return None
    status = critique.get("subagent_status")
    if status == "schema_mismatch":
        return "schema_mismatch"
    if status == "timeout":
        return "timeout"
    if status == "passed":
        return "substantive"
    return "unknown"


# ---------------------------------------------------------------------------
# Downstream cost — BOTH predicates, named honestly
# ---------------------------------------------------------------------------

def _row_with_verdict(row: dict, verdict: str) -> dict:
    """Shallow copy of `row` whose critique.verdict is replaced. Only the
    two nested dicts that change are copied — derive_level never mutates."""
    out = dict(row)
    critique = dict(row.get("critique") or {})
    critique["verdict"] = verdict
    out["critique"] = critique
    return out


def downstream(row: dict) -> dict:
    """L1-ladder and thesis_to_experiment eligibility, raw vs final.

    raw   = counterfactual in which the PRIMARY critic's own verdict stood.
    final = what the pipeline actually recorded.
    """
    from orchestrator.thesis_to_experiment import is_eligible
    from workers.evidence_ladder import LEVELS, derive_level

    critique = row.get("critique") or {}
    verdict_final = critique.get("verdict")
    verdict_raw = critique.get("verdict_overridden_from") or verdict_final
    novelty_class = (row.get("novelty") or {}).get("class")
    low_conf = bool(critique.get("low_confidence"))

    lvl_final = derive_level(row, None, None, [])
    lvl_raw = (
        lvl_final if verdict_raw == verdict_final
        else derive_level(_row_with_verdict(row, verdict_raw), None, None, [])
    )
    l1_final = LEVELS.index(lvl_final["level"]) >= LEVELS.index("L1")
    l1_raw = LEVELS.index(lvl_raw["level"]) >= LEVELS.index("L1")

    t2e_final = is_eligible(novelty_class, verdict_final, low_conf)
    t2e_raw = is_eligible(novelty_class, verdict_raw, low_conf)

    return {
        "verdict_raw": verdict_raw,
        "verdict_final": verdict_final,
        "l1_level_raw": lvl_raw["level"],
        "l1_level_final": lvl_final["level"],
        "l1_missing_final": list(lvl_final["missing_for_next"]),
        "l1_raw": l1_raw,
        "l1_final": l1_final,
        "t2e_eligible_raw": t2e_raw,
        "t2e_eligible_final": t2e_final,
        # THE central quantity — defined on the real L1 rung.
        "blocked_by_override": bool(l1_raw and not l1_final),
        # The loose upper bound the v1 draft used as if it were the same
        # thing. Reported, never headlined.
        "t2e_blocked_loose": bool(t2e_raw and not t2e_final),
    }


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------

def build_rows(loop_memory: list[dict]) -> list[dict]:
    """One audit record per loop_memory row. Order follows the input file."""
    out = []
    for row in loop_memory:
        critique = row.get("critique")
        has_critique = isinstance(critique, dict) and bool(critique)
        critique = critique if has_critique else {}
        override_class, override_reason = (
            classify_override(critique) if has_critique else ("NO_CRITIQUE", None)
        )
        debate = critique.get("debate") if isinstance(critique.get("debate"), dict) else None
        rec = {
            "iteration_id": row.get("iteration_id"),
            "started_at": row.get("started_at"),
            "day": (row.get("started_at") or "")[:10],
            "has_critique": has_critique,
            "override_class": override_class,
            "override_reason": override_reason,
            "override_class_rollup": (
                "RELEVANCE" if override_class in RELEVANCE_CLASSES else override_class
            ),
            "asserted_refutation": (
                asserted_refutation(critique, override_class) if has_critique else False
            ),
            "infra_flavored": infra_flavored(critique) if has_critique else False,
            "skeptic_infra_error_flag": bool(critique.get("skeptic_infra_error")),
            "undecidable_kind": undecidable_kind(critique) if has_critique else None,
            "pack_state": pack_state(row),
            "relevance_category": (
                ((row.get("retrieval") or {}).get("relevance") or {}).get("category")
                if isinstance(row.get("retrieval"), dict) else None
            ),
            "relevance_low_confidence": (
                ((row.get("retrieval") or {}).get("relevance") or {}).get("low_confidence")
                if isinstance(row.get("retrieval"), dict) else None
            ),
            "subagent_status": critique.get("subagent_status"),
            "subagent_turns_used": critique.get("subagent_turns_used"),
            "subagent_wall_seconds": critique.get("subagent_wall_seconds"),
            "debate_verdict": (debate or {}).get("verdict"),
            "debate_rounds": (debate or {}).get("rounds"),
            "debate_stop_reason": (debate or {}).get("stop_reason"),
            "skeptic_verdict": critique.get("skeptic_verdict"),
            "skeptic_backend": critique.get("skeptic_backend"),
            "skeptic_model": critique.get("skeptic_model"),
            "novelty_class": (row.get("novelty") or {}).get("class"),
            "redteam_verdict": (row.get("redteam") or {}).get("verdict"),
            "gate_status": row.get("gate_status"),
        }
        if has_critique:
            rec.update(downstream(row))
        else:
            rec.update({
                "verdict_raw": None, "verdict_final": None,
                "l1_level_raw": None, "l1_level_final": None,
                "l1_missing_final": [], "l1_raw": False, "l1_final": False,
                "t2e_eligible_raw": False, "t2e_eligible_final": False,
                "blocked_by_override": False, "t2e_blocked_loose": False,
            })
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Aggregations — every emitted collection explicitly sorted
# ---------------------------------------------------------------------------

def _counter_to_sorted(counter: collections.Counter) -> list[dict]:
    return [
        {"key": list(k) if isinstance(k, tuple) else k, "n": v}
        for k, v in sorted(counter.items(), key=lambda kv: (str(kv[0]),))
    ]


def undecidable_census(rows: list[dict]) -> dict:
    """THE census the v2 prereg makes first-class: all undecidable rows
    split by provenance AND by the pack state recorded at the time.

    A NATIVE undecidable on a FLAGGED pack is the critic obeying an
    explicit instruction printed in its own prompt. Pooling it with a
    NATIVE undecidable on a clean pack is the attribution blur that lets
    a calibration result be read as a statement about all 59.
    """
    und = [r for r in rows if r["verdict_final"] == "undecidable"]
    by_class = collections.Counter(r["override_class_rollup"] for r in und)
    by_class_pack = collections.Counter(
        (r["override_class_rollup"], r["pack_state"]) for r in und
    )
    by_day_class = collections.Counter(
        (r["day"], r["override_class_rollup"]) for r in und
    )
    native = [r for r in und if r["override_class"] == "NATIVE"]
    return {
        "n_undecidable": len(und),
        "by_class": _counter_to_sorted(by_class),
        "by_class_and_pack_state": _counter_to_sorted(by_class_pack),
        "by_day_and_class": _counter_to_sorted(by_day_class),
        "native_by_pack_state": _counter_to_sorted(
            collections.Counter(r["pack_state"] for r in native)
        ),
        "native_on_adequate_pack_ids": sorted(
            r["iteration_id"] for r in native if r["pack_state"] == "adequate"
        ),
        "native_on_flagged_pack_ids": sorted(
            r["iteration_id"] for r in native if r["pack_state"] == "flagged"
        ),
        "attribution_sentence": _attribution_sentence(und, native),
    }


def _attribution_sentence(und: list[dict], native: list[dict]) -> str:
    n_adq = sum(1 for r in native if r["pack_state"] == "adequate")
    n_flag = sum(1 for r in native if r["pack_state"] == "flagged")
    n_other = len(native) - n_adq - n_flag
    n_override = len(und) - len(native)
    return (
        f"Of {len(und)} undecidable rows: {n_adq} are NATIVE on an "
        f"ADEQUATE pack (the only population a critic-calibration result "
        f"speaks to), {n_flag} are NATIVE on a pack the apparatus itself "
        f"FLAGGED (the critic's own prompt instructs it to say undecidable "
        f"there), {n_other} are NATIVE with no retrieval block, and "
        f"{n_override} were OVERRIDDEN after the critic had already spoken."
    )


def production_reference_rates(rows: list[dict]) -> dict:
    """The critic's NATIVE undecidable rate on ADEQUATE packs — the rate
    any bar on over-emission must be calibrated against, and the reason
    D1 does not pretend to estimate it: it is a census, already exact."""
    adequate = [
        r for r in rows if r["has_critique"] and r["pack_state"] == "adequate"
    ]

    def _k(subset: list[dict]) -> int:
        # NATIVE undecidable only: an OVERRIDDEN row's own native verdict
        # was 'survives', so it belongs in the denominator as a
        # not-undecidable outcome, never in the numerator.
        return sum(
            1 for r in subset
            if r["override_class"] == "NATIVE" and r["verdict_final"] == "undecidable"
        )

    by_month: dict[str, list[dict]] = {}
    for r in adequate:
        by_month.setdefault(r["day"][:7], []).append(r)
    native_only = [r for r in adequate if r["override_class"] == "NATIVE"]
    return {
        "definition": (
            "numerator = critic calls on an adequate pack whose NATIVE "
            "(non-overridden) verdict is 'undecidable'; denominator = ALL "
            "critic calls on an adequate pack. Overridden rows stay in the "
            "denominator because their native verdict was 'survives' — "
            "dropping them would inflate the rate."
        ),
        "all_time": {"k": _k(adequate), "n": len(adequate)},
        "by_month": [
            {"month": m, "k": _k(v), "n": len(v)}
            for m, v in sorted(by_month.items())
        ],
        "secondary_native_only_denominator": {
            "k": _k(native_only), "n": len(native_only),
            "note": "reported for transparency; NOT the headline rate",
        },
    }


def survives_override_decomposition(rows: list[dict]) -> dict:
    """Of the rows whose PRIMARY verdict was survives and which an
    override turned into undecidable: what did the overrider claim?"""
    sov = [
        r for r in rows
        if r["verdict_raw"] == "survives" and r["verdict_final"] == "undecidable"
    ]

    def bucket(r: dict) -> str:
        if r["asserted_refutation"]:
            return "refutation_asserted"
        if r["infra_flavored"]:
            return "infra_failure"
        if r["override_class_rollup"] == "RELEVANCE":
            return "corpus_coverage_statement"
        if r["debate_stop_reason"] == "round_cap":
            return "ran_out_of_rounds"
        return "other_no_refutation"

    buckets = collections.Counter(bucket(r) for r in sov)
    return {
        "n_survives_overrides": len(sov),
        "by_assertion": _counter_to_sorted(buckets),
        "n_no_refutation_asserted": sum(
            1 for r in sov if not r["asserted_refutation"]
        ),
        "by_class": _counter_to_sorted(
            collections.Counter(r["override_class_rollup"] for r in sov)
        ),
        "ids_by_bucket": {
            b: sorted(r["iteration_id"] for r in sov if bucket(r) == b)
            for b in sorted(set(bucket(r) for r in sov))
        },
    }


def debate_anatomy(rows: list[dict]) -> dict:
    """(verdict, stop_reason, rounds) joint distribution. `rounds` counts
    TRANSCRIPT TURNS, not exchanges — cap 4 = 2 exchanges, cap 6 = 3."""
    deb = [r for r in rows if r["debate_verdict"] is not None]
    return {
        "n_debate_rows": len(deb),
        "joint": _counter_to_sorted(collections.Counter(
            (r["debate_verdict"], r["debate_stop_reason"], r["debate_rounds"])
            for r in deb
        )),
        "round_cap_by_cap_value": _counter_to_sorted(collections.Counter(
            r["debate_rounds"] for r in deb if r["debate_stop_reason"] == "round_cap"
        )),
        "rounds_note": (
            "`rounds` is the transcript TURN count (challenger+defender), "
            "not the exchange count: cap 4 = 2 exchanges, cap 6 = 3."
        ),
    }


def blocking_summary(rows: list[dict]) -> dict:
    blocked = [r for r in rows if r["blocked_by_override"]]
    loose = [r for r in rows if r["t2e_blocked_loose"]]
    return {
        "blocked_by_override_L1_ladder": {
            "n": len(blocked),
            "predicate": (
                "workers.evidence_ladder.derive_level >= L1 on the primary "
                "critic's own verdict AND < L1 on the recorded verdict — the "
                "rung orchestrator/finding_promotion.py:191-206 actually gates on"
            ),
            "ids": sorted(r["iteration_id"] for r in blocked),
            "by_class": _counter_to_sorted(
                collections.Counter(r["override_class_rollup"] for r in blocked)
            ),
            "by_day": _counter_to_sorted(
                collections.Counter(r["day"] for r in blocked)
            ),
            "redteam_verdicts": _counter_to_sorted(
                collections.Counter(str(r["redteam_verdict"]) for r in blocked)
            ),
        },
        "t2e_blocked_loose": {
            "n": len(loose),
            "predicate": (
                "orchestrator/thesis_to_experiment.py is_eligible only "
                "(novelty in ELIGIBLE_NOVELTY and verdict=='survives' and not "
                "low_confidence) — a LOOSE UPPER BOUND: it ignores the L1 "
                "rung's relevance and redteam terms"
            ),
            "ids": sorted(r["iteration_id"] for r in loose),
            "already_L0_for_other_reasons": sorted(
                r["iteration_id"] for r in loose if not r["blocked_by_override"]
            ),
            "already_L0_reason_counts": _counter_to_sorted(collections.Counter(
                "; ".join(r["l1_missing_final"])
                for r in loose if not r["blocked_by_override"]
            )),
        },
    }


def cluster_impact(rows: list[dict], ledger_path: Path) -> dict:
    """Per OPEN cluster: what actually blocks it, and would a critic fix
    move it? Settles the v1 draft's open question C-4 from the record.

    Reconstruction: workers.idea_ledger.load_state (canonical file-order
    fold). The cluster's current iteration is its LAST member present in
    loop_memory; agreement across three candidate orderings (append
    order, id sort, loop_memory file order) is asserted and reported, so
    a reconstruction ambiguity can never hide inside this number.
    """
    from workers.evidence_ladder import LEVELS, derive_level
    from workers.idea_ledger import load_state

    state = load_state(ledger_path)
    by_id = {r["iteration_id"]: r for r in rows}
    loop_order = {r["iteration_id"]: i for i, r in enumerate(rows)}
    raw_rows = {r["iteration_id"]: r for r in _read_jsonl(LOOP_MEMORY_PATH)}

    out = []
    disagreements = []
    n_critic_only = 0
    for cid in sorted(k for k, v in state.items() if v.get("status") == "open"):
        members = [m for m in state[cid]["members"] if m in by_id]
        if not members:
            out.append({
                "cluster_id": cid, "latest_iteration": None,
                "note": "no member present in loop_memory",
            })
            continue
        cand = {
            "append": members[-1],
            "id_sort": sorted(members)[-1],
            "loop_order": max(members, key=lambda m: loop_order[m]),
        }
        if len(set(cand.values())) > 1:
            disagreements.append({"cluster_id": cid, "candidates": cand})
        latest = cand["append"]
        rec = by_id[latest]
        raw = raw_rows[latest]
        lvl = derive_level(raw, None, None, [])
        cf = derive_level(_row_with_verdict(raw, "survives"), None, None, [])
        critic_only = (
            LEVELS.index(lvl["level"]) < LEVELS.index("L1")
            and LEVELS.index(cf["level"]) >= LEVELS.index("L1")
        )
        n_critic_only += int(critic_only)
        out.append({
            "cluster_id": cid,
            "latest_iteration": latest,
            "n_members_in_loop_memory": len(members),
            "verdict_final": rec["verdict_final"],
            "verdict_raw": rec["verdict_raw"],
            "override_class": rec["override_class"],
            "level": lvl["level"],
            "missing_for_next": list(lvl["missing_for_next"]),
            "level_if_verdict_were_survives": cf["level"],
            "critic_only_blocked": critic_only,
            "blocked_by_override": rec["blocked_by_override"],
        })
    return {
        "n_open_clusters": len(out),
        "n_critic_only_blocked": n_critic_only,
        "n_at_L1_already": sum(1 for c in out if c.get("level") == "L1"),
        "at_L1_already": sorted(
            c["cluster_id"] for c in out if c.get("level") == "L1"
        ),
        "reconstruction_disagreements": disagreements,
        "clusters": out,
        "blocking_term_census": _counter_to_sorted(collections.Counter(
            "; ".join(c.get("missing_for_next") or ["(at L1 or above)"])
            for c in out
        )),
    }


def gate_ledger_census(path: Path) -> dict:
    """The human-gate ledger, counted honestly and never inflated. Using
    recorded VERDICTS as labels is legitimate; inviolate rule 9 protects
    the human's reflective PROSE, which this audit does not reproduce,
    summarize, or interpret — only the verdict enum and the iteration_id
    are read."""
    fb = _read_jsonl(path)
    return {
        "n_rows": len(fb),
        "n_distinct_iteration_ids": len({r.get("iteration_id") for r in fb}),
        "by_verdict": _counter_to_sorted(
            collections.Counter(r.get("verdict") for r in fb)
        ),
        "iteration_ids": sorted({str(r.get("iteration_id")) for r in fb}),
        "note": (
            "Iteration-level valid/invalid/needs_revision does NOT project "
            "onto the critic enum survives/falsified/restated/undecidable. "
            "This ledger anchors ZERO bars in D1."
        ),
    }


# ---------------------------------------------------------------------------
# Invariants — hard, never coerced
# ---------------------------------------------------------------------------

def check_invariants(loop_memory: list[dict], rows: list[dict], report: dict) -> list[str]:
    """Raises AuditInvariantError on any violation. Returns the list of
    checks that passed, so the artifact records what was actually
    verified rather than asserting 'deterministic' and moving on."""
    passed = []

    if len(rows) != len(loop_memory):
        raise AuditInvariantError(
            f"rows read {len(loop_memory)} != rows emitted {len(rows)}"
        )
    passed.append(f"rows_read == rows_emitted == {len(rows)}")

    n_class = sum(c["n"] for c in report["census"]["overall_by_class"])
    if n_class != len(rows):
        raise AuditInvariantError(
            f"override_class counts sum to {n_class}, expected {len(rows)}"
        )
    passed.append("override_class counts sum to total rows")

    und = report["undecidable_census"]
    n_und_class = sum(c["n"] for c in und["by_class"])
    if n_und_class != und["n_undecidable"]:
        raise AuditInvariantError(
            f"undecidable class counts sum to {n_und_class}, expected "
            f"{und['n_undecidable']}"
        )
    passed.append(f"undecidable class counts sum to {und['n_undecidable']}")

    n_pack = sum(c["n"] for c in und["by_class_and_pack_state"])
    if n_pack != und["n_undecidable"]:
        raise AuditInvariantError(
            f"undecidable (class, pack_state) counts sum to {n_pack}"
        )
    passed.append("undecidable (class, pack_state) counts sum to total")

    # SINGLE-LEVEL OVERRIDE. verdict_raw = verdict_overridden_from or
    # verdict is only correct because the coverage override
    # (critic_loop_v0.py:738-762) PRECEDES and short-circuits the
    # skeptic/debate seams (:777+, guarded on verdict == 'survives'), so
    # no row can be overridden twice. Assert it; never assume it.
    for r in rows:
        if r["override_class"] in RELEVANCE_CLASSES and (
            r["debate_verdict"] is not None or r["skeptic_verdict"] is not None
        ):
            if r["verdict_raw"] != "survives":
                raise AuditInvariantError(
                    f"{r['iteration_id']}: coverage override coexists with a "
                    "skeptic/debate block and verdict_raw is not 'survives' — "
                    "the single-level-override invariant does not hold"
                )
    passed.append("single-level override invariant holds on every row")

    for r in rows:
        if r["override_class"] == "OTHER":
            raise AuditInvariantError(
                f"{r['iteration_id']}: unmatched override_reason "
                f"{r['override_reason']!r} — a new override seam shipped and "
                "the prefix table must be extended before this audit is read"
            )
    passed.append("no OTHER-class override_reason (prefix table is complete)")

    return passed


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(
    loop_memory_path: Path = LOOP_MEMORY_PATH,
    idea_ledger_path: Path = IDEA_LEDGER_PATH,
    loop_feedback_path: Path = LOOP_FEEDBACK_PATH,
    *,
    include_rows: bool = True,
    now: str | None = None,
) -> dict:
    loop_memory = _read_jsonl(loop_memory_path)
    rows = build_rows(loop_memory)

    report: dict[str, Any] = {
        "prereg": PREREG,
        "deliverable": "D2 — override-chain audit",
        "generated_at": now or datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "model_calls_made": 0,
        "inputs": {
            "loop_memory": {
                "path": str(loop_memory_path.relative_to(REPO_ROOT))
                if loop_memory_path.is_relative_to(REPO_ROOT) else str(loop_memory_path),
                "sha256": _sha256(loop_memory_path),
                "n_rows": len(loop_memory),
            },
            "idea_ledger": {
                "path": str(idea_ledger_path.relative_to(REPO_ROOT))
                if idea_ledger_path.is_relative_to(REPO_ROOT) else str(idea_ledger_path),
                "sha256": _sha256(idea_ledger_path),
            },
            "loop_feedback": {
                "path": str(loop_feedback_path.relative_to(REPO_ROOT))
                if loop_feedback_path.is_relative_to(REPO_ROOT) else str(loop_feedback_path),
                "sha256": _sha256(loop_feedback_path),
            },
        },
        "regime_marks": list(REGIME_MARKS),
        "census": {
            "overall_by_class": _counter_to_sorted(
                collections.Counter(r["override_class_rollup"] for r in rows)
            ),
            "overall_by_class_detailed": _counter_to_sorted(
                collections.Counter(r["override_class"] for r in rows)
            ),
            "verdict_final": _counter_to_sorted(
                collections.Counter(str(r["verdict_final"]) for r in rows)
            ),
            "verdict_raw": _counter_to_sorted(
                collections.Counter(str(r["verdict_raw"]) for r in rows)
            ),
            "subagent_status": _counter_to_sorted(
                collections.Counter(str(r["subagent_status"]) for r in rows if r["has_critique"])
            ),
            "n_rows_without_critique": sum(1 for r in rows if not r["has_critique"]),
            "n_critique_rows_with_null_status": sum(
                1 for r in rows if r["has_critique"] and r["subagent_status"] is None
            ),
            "undecidable_kind": _counter_to_sorted(
                collections.Counter(
                    str(r["undecidable_kind"]) for r in rows
                    if r["undecidable_kind"] is not None
                )
            ),
        },
        "undecidable_census": undecidable_census(rows),
        "production_reference_rates": production_reference_rates(rows),
        "survives_override_decomposition": survives_override_decomposition(rows),
        "debate_anatomy": debate_anatomy(rows),
        "infra": {
            "skeptic_infra_error_flag_count": sum(
                1 for r in rows if r["skeptic_infra_error_flag"]
            ),
            "infra_flavored_count": sum(1 for r in rows if r["infra_flavored"]),
            "infra_flavored_ids": sorted(
                r["iteration_id"] for r in rows if r["infra_flavored"]
            ),
            "note": (
                "The flag is 0 across the ledger because D-075 R3b POSTDATES "
                "every row that would carry it. infra_flavored is the honest "
                "census; the flag count is reported beside it, not instead."
            ),
        },
        "downstream": blocking_summary(rows),
        "clusters": cluster_impact(rows, idea_ledger_path),
        "gate_ledger": gate_ledger_census(loop_feedback_path),
    }
    report["invariants_passed"] = check_invariants(loop_memory, rows, report)
    if include_rows:
        report["rows"] = rows
    return report


def _print_summary(rep: dict) -> None:
    p = print
    p("=" * 74)
    p("D2 — OVERRIDE-CHAIN AUDIT   (deterministic, 0 model calls)")
    p("=" * 74)
    uc = rep["undecidable_census"]
    p("\nATTRIBUTION (the mandatory opening sentence):")
    p("  " + uc["attribution_sentence"])
    p(f"\nUndecidable rows: {uc['n_undecidable']}")
    for c in uc["by_class"]:
        p(f"    {c['key']:<22s} {c['n']}")
    p("\nNATIVE undecidables by pack state recorded at the time:")
    for c in uc["native_by_pack_state"]:
        p(f"    {c['key']:<22s} {c['n']}")
    ref = rep["production_reference_rates"]
    at = ref["all_time"]
    p(f"\nPRODUCTION REFERENCE — native undecidable rate on ADEQUATE packs:")
    p(f"    all time : {at['k']}/{at['n']} = {at['k']/at['n']:.4f}")
    for m in ref["by_month"]:
        p(f"    {m['month']}  : {m['k']}/{m['n']} = {m['k']/m['n']:.4f}")
    sec = ref["secondary_native_only_denominator"]
    p(f"    (native-only denominator, secondary: {sec['k']}/{sec['n']})")
    d = rep["survives_override_decomposition"]
    p(f"\nSURVIVES-OVERRIDES: {d['n_survives_overrides']}  "
      f"({d['n_no_refutation_asserted']} asserted NO refutation)")
    for c in d["by_assertion"]:
        p(f"    {c['key']:<28s} {c['n']}")
    da = rep["debate_anatomy"]
    p(f"\nDEBATE ANATOMY ({da['n_debate_rows']} rows) (verdict, stop_reason, turns):")
    for c in da["joint"]:
        p(f"    {str(c['key']):<50s} {c['n']}")
    dn = rep["downstream"]
    b = dn["blocked_by_override_L1_ladder"]
    l = dn["t2e_blocked_loose"]
    p(f"\nDOWNSTREAM COST")
    p(f"    blocked_by_override (REAL L1 ladder) : {b['n']}")
    for i in b["ids"]:
        p(f"        {i}")
    p(f"    t2e_blocked_loose (is_eligible only) : {l['n']}"
      f"   [{len(l['already_L0_for_other_reasons'])} of them were ALREADY "
      f"below L1 for other reasons]")
    cl = rep["clusters"]
    p(f"\nOPEN CLUSTERS: {cl['n_open_clusters']}")
    p(f"    already at L1 (need an EXPERIMENT, not a critic): "
      f"{cl['n_at_L1_already']}  {cl['at_L1_already']}")
    p(f"    critic-only-blocked (flip verdict to survives -> L1): "
      f"{cl['n_critic_only_blocked']}")
    p(f"    reconstruction disagreements: {len(cl['reconstruction_disagreements'])}")
    p("\n    per-cluster blocking terms:")
    for c in cl["blocking_term_census"]:
        p(f"      {c['n']:>2d}  {c['key']}")
    inf = rep["infra"]
    p(f"\nINFRA: flag={inf['skeptic_infra_error_flag_count']}  "
      f"infra_flavored={inf['infra_flavored_count']}")
    g = rep["gate_ledger"]
    p(f"\nHUMAN GATE LEDGER: {g['n_rows']} rows, "
      f"{g['n_distinct_iteration_ids']} distinct iteration_ids")
    p(f"\nINVARIANTS PASSED ({len(rep['invariants_passed'])}):")
    for i in rep["invariants_passed"]:
        p(f"    OK  {i}")
    p("")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--out", required=True,
        help="artifact path; a relative path is anchored to REPO_ROOT "
             "(a relative --out crashed a battery AFTER its calls were spent)",
    )
    ap.add_argument("--no-rows", action="store_true",
                    help="omit the per-row block from the artifact")
    args = ap.parse_args(argv)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path

    try:
        report = build_report(include_rows=not args.no_rows)
    except AuditInvariantError as exc:
        print(f"AUDIT INVARIANT FAILED — refusing to write: {exc}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    _print_summary(report)
    print(f"artifact -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
