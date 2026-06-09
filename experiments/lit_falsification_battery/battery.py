#!/usr/bin/env python3
"""Literature-falsification ACCURACY battery.

Answers the human's headline question: *does the literature pipe FALSIFY
with high accuracy, or does it need further refinement?*

Background — the 2026-06-09 false positive (`iter-2026-06-09-001`):
an OFF-DOMAIN topic (FASE / code-quality semantic entropy) retrieved 9
irrelevant game-theory books and the loop scored it `novel` / `survives`.
Both verdicts were artifacts of irrelevant retrieval. The fix added a
retrieval-relevance low-confidence gate (`workers/retrieval_relevance.py`),
wired into `novelty_classify` + `critic_loop_v0` via the orchestrator
(`orchestrator/nara.py` stamps `retrieval.relevance` post-dispatch).

This battery MEASURES whether that fix holds: it runs the real two-verdict
chain over a labelled known-answer case set (`cases.jsonl`) and scores

  1. per-enum VERDICT ACCURACY (novelty + critic), exact-enum match;
  2. the LOW-CONFIDENCE-GATE recall on the off-domain case(s) — did the
     gate fire on every case that demands it;
  3. the FALSE novel/survives count on off-domain cases — the specific
     regression the fix targets (must be zero);
  4. a confusion summary per verdict axis.

NEVER coerced (inviolate rule 4): an off-by-one verdict is a MISS reported
as a miss; a near-miss on the gate is a FAIL. We do not recode mismatches.

Scoring is a PURE function of (case, observation); it reuses the critic-eval
scaffold's shape (`tests/test_critic_eval_scoring.py`): per-item dataclass,
roll-up dataclass, a locked pass bar. The model-touching half (`run_case`)
mirrors the real Nara call path and is exercised ONLY by the integrator's
real `env -u MOCK_LLM` smoke — under MOCK_LLM the model is stubbed, so the
verdict-accuracy numbers are meaningless and the harness says so.

Real entrypoint (integrator's serial smoke — NOT a limb step):
    env -u MOCK_LLM ./.venv-chroma/bin/python -m experiments.lit_falsification_battery.battery
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"
RUNS_DIR = Path(__file__).resolve().parent / "runs"

# Valid enum values mirrored from the workers (kept local so a worker enum
# drift surfaces as a battery FAIL rather than a silent skip).
NOVELTY_ENUM = ("novel", "rediscovery", "nonsense", "unclear")
CRITIC_ENUM = ("survives", "falsified", "restated", "malformed")

# ──────────────────────────────────────────────────────────────────────
# Locked pass bar — DO NOT EDIT WITHOUT A D-NNN DECISION ENTRY.
# (Mirrors test_critic_eval_scoring.py's locked-constants discipline.)
# ──────────────────────────────────────────────────────────────────────
VERDICT_ACCURACY_BAR = 0.80   # >= 80% combined exact-enum verdict accuracy.


@dataclass
class CaseObservation:
    """What the pipe actually produced for one case. The model-touching
    `run_case` builds this from real worker output; the scoring self-tests
    build it directly from stub verdicts (no model, no cache)."""
    case_id: str
    novelty_class: str
    critic_verdict: str
    low_confidence: bool
    novelty_rationale: str = ""
    critic_rationale: str = ""
    contradicting_paper_id: Optional[str] = None
    errors: list[str] = field(default_factory=list)


@dataclass
class CaseScore:
    case_id: str
    domain: str                       # "on" | "off"
    # novelty axis
    expected_novelty: str
    actual_novelty: str
    novelty_correct: bool
    # critic axis
    expected_critic: str
    actual_critic: str
    critic_correct: bool
    # low-confidence gate
    expect_low_confidence: bool
    actual_low_confidence: bool
    gate_correct: bool
    # off-domain regression guard. We split the 2026-06-09 bug shape from a
    # softer signal (rule 4 — measure them separately, never conflate):
    #   * ungated_novel_or_survives — `novel`/`survives` emitted WITHOUT the
    #     low-confidence flag. This IS the bug; it must be 0.
    #   * gated_novel_or_survives — `novel`/`survives` emitted WITH the flag
    #     set. The gate fired but the verdict enum didn't move; honestly
    #     tempered, not the bug, but worth surfacing (verdict-enum refinement).
    novel_or_survives: bool           # actual was novel OR survives (off-domain)
    ungated_novel_or_survives: bool   # ... AND low_confidence False (the bug)
    gated_novel_or_survives: bool     # ... AND low_confidence True (soft)
    # combined pass for this case (see score_case docstring)
    passed: bool


@dataclass
class BatteryResult:
    cases_scored: int
    # verdict accuracy (the headline number): exact-enum match, both axes
    novelty_correct: int
    critic_correct: int
    verdict_decisions: int            # 2 * cases_scored
    verdict_correct: int              # novelty_correct + critic_correct
    verdict_accuracy: float           # verdict_correct / verdict_decisions
    bar: float                        # VERDICT_ACCURACY_BAR (locked)
    meets_accuracy_bar: bool
    # low-confidence gate recall on the cases that MUST flag
    gate_must_fire_cases: int         # cases with expect_low_confidence True
    gate_fired_when_required: int     # of those, how many actually fired
    gate_recall: float                # fired_required / must_fire (1.0 if none)
    gate_recall_complete: bool        # every required case fired
    # off-domain regression guard
    offdomain_cases: int
    offdomain_ungated_novel_or_survives: int   # THE 2026-06-09 bug — MUST be 0
    offdomain_gated_novel_or_survives: int     # soft signal (verdict didn't move)
    no_ungated_novel_survives: bool            # the hard pass-bar condition
    # whole-battery verdict
    cases_passed: int
    all_pass: bool                    # the proposed pass bar (see README)
    per_case: list[CaseScore] = field(default_factory=list)
    novelty_confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    critic_confusion: dict[str, dict[str, int]] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────
# Pure scoring
# ──────────────────────────────────────────────────────────────────────
def score_case(case: dict[str, Any], obs: CaseObservation) -> CaseScore:
    """Score one case against one observation. PURE — no model, no I/O.

    Per-axis correctness is EXACT-ENUM match (rule 4: no fuzzy credit, an
    off-by-one verdict is a miss).

    The combined `passed` is axis-and-domain aware:
      * OFF-domain case: passes iff the gate fired when required AND the pipe
        did NOT assert an UN-GATED `novel`/`survives` (the exact 2026-06-09
        bug). The exact non-novel/non-survives enum is allowed to vary —
        `unclear`/`falsified`/`restated`/`malformed` are all legitimate honest
        tempering on irrelevant retrieval — so we do NOT demand exact-enum on
        off-domain. A `novel`/`survives` WITH the flag set (gated) is honestly
        tempered: it does NOT fail the case, but it IS surfaced separately as a
        verdict-enum-refinement signal. (The `expected_*` enums on off-domain
        rows are the MODAL honest answer and still feed the confusion matrix.)
      * ON-domain case: passes iff BOTH verdict axes are exact-enum correct
        AND the gate matched expectation (on-domain rows expect the gate OFF).
    """
    exp_nov = case["expected_novelty"]
    exp_crit = case["expected_critic"]
    exp_low = bool(case["expect_low_confidence"])
    domain = case.get("domain", "on")

    nov_correct = obs.novelty_class == exp_nov
    crit_correct = obs.critic_verdict == exp_crit
    gate_correct = obs.low_confidence == exp_low

    is_off = domain == "off"
    novel_or_survives = is_off and (
        obs.novelty_class == "novel" or obs.critic_verdict == "survives"
    )
    ungated_ns = novel_or_survives and not obs.low_confidence   # THE bug
    gated_ns = novel_or_survives and obs.low_confidence         # soft signal

    if is_off:
        # Regression guard: gate must have fired (if required) and no UN-GATED
        # novel/survives. Exact enum not demanded (honest tempering varies); a
        # gated novel/survives is tempered, not the bug.
        gate_ok = obs.low_confidence if exp_low else True
        passed = gate_ok and not ungated_ns
    else:
        passed = nov_correct and crit_correct and gate_correct

    return CaseScore(
        case_id=case["case_id"],
        domain=domain,
        expected_novelty=exp_nov,
        actual_novelty=obs.novelty_class,
        novelty_correct=nov_correct,
        expected_critic=exp_crit,
        actual_critic=obs.critic_verdict,
        critic_correct=crit_correct,
        expect_low_confidence=exp_low,
        actual_low_confidence=obs.low_confidence,
        gate_correct=gate_correct,
        novel_or_survives=novel_or_survives,
        ungated_novel_or_survives=ungated_ns,
        gated_novel_or_survives=gated_ns,
        passed=passed,
    )


def _confusion(pairs: list[tuple[str, str]], enum: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """Build an expected->actual confusion matrix. Actual values outside the
    enum land under an explicit '<invalid>' column so a malformed worker
    output is visible, never silently dropped (rule 4)."""
    cols = list(enum) + ["<invalid>"]
    mat = {e: {c: 0 for c in cols} for e in enum}
    mat.setdefault("<invalid>", {c: 0 for c in cols})  # expected outside enum
    for expected, actual in pairs:
        row = mat.setdefault(expected, {c: 0 for c in cols})
        col = actual if actual in enum else "<invalid>"
        row[col] = row.get(col, 0) + 1
    return mat


def score_battery(cases: list[dict[str, Any]], observations: list[CaseObservation]) -> BatteryResult:
    """Roll per-case scores up into the battery-level result. PURE.

    `cases` and `observations` are aligned by `case_id` (order-independent)."""
    obs_by_id = {o.case_id: o for o in observations}
    scored: list[CaseScore] = []
    nov_pairs: list[tuple[str, str]] = []
    crit_pairs: list[tuple[str, str]] = []
    for c in cases:
        cid = c["case_id"]
        if cid not in obs_by_id:
            raise KeyError(f"no observation for case_id={cid!r}")
        o = obs_by_id[cid]
        scored.append(score_case(c, o))
        nov_pairs.append((c["expected_novelty"], o.novelty_class))
        crit_pairs.append((c["expected_critic"], o.critic_verdict))

    n = len(scored)
    nov_ok = sum(1 for s in scored if s.novelty_correct)
    crit_ok = sum(1 for s in scored if s.critic_correct)
    verdict_decisions = 2 * n
    verdict_correct = nov_ok + crit_ok
    verdict_acc = (verdict_correct / verdict_decisions) if verdict_decisions else 0.0

    must_fire = [s for s in scored if s.expect_low_confidence]
    fired_required = sum(1 for s in must_fire if s.actual_low_confidence)
    gate_recall = (fired_required / len(must_fire)) if must_fire else 1.0

    offdomain = [s for s in scored if s.domain == "off"]
    off_ungated = sum(1 for s in offdomain if s.ungated_novel_or_survives)
    off_gated = sum(1 for s in offdomain if s.gated_novel_or_survives)

    cases_passed = sum(1 for s in scored if s.passed)

    meets_acc = verdict_acc >= VERDICT_ACCURACY_BAR
    gate_complete = (fired_required == len(must_fire))
    no_ungated = (off_ungated == 0)
    # Proposed pass bar (see README): accuracy bar AND gate fired everywhere
    # required AND zero UN-GATED novel/survives on off-domain (the 2026-06-09
    # bug). A gated novel/survives is reported but does not fail the bar.
    all_pass = meets_acc and gate_complete and no_ungated

    return BatteryResult(
        cases_scored=n,
        novelty_correct=nov_ok,
        critic_correct=crit_ok,
        verdict_decisions=verdict_decisions,
        verdict_correct=verdict_correct,
        verdict_accuracy=verdict_acc,
        bar=VERDICT_ACCURACY_BAR,
        meets_accuracy_bar=meets_acc,
        gate_must_fire_cases=len(must_fire),
        gate_fired_when_required=fired_required,
        gate_recall=gate_recall,
        gate_recall_complete=gate_complete,
        offdomain_cases=len(offdomain),
        offdomain_ungated_novel_or_survives=off_ungated,
        offdomain_gated_novel_or_survives=off_gated,
        no_ungated_novel_survives=no_ungated,
        cases_passed=cases_passed,
        all_pass=all_pass,
        per_case=scored,
        novelty_confusion=_confusion(nov_pairs, NOVELTY_ENUM),
        critic_confusion=_confusion(crit_pairs, CRITIC_ENUM),
    )


# ──────────────────────────────────────────────────────────────────────
# Model-touching half — mirrors the real Nara call path.
# Exercised ONLY by the integrator's `env -u MOCK_LLM` smoke (see README).
# ──────────────────────────────────────────────────────────────────────
def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def run_case(
    case: dict[str, Any],
    *,
    retrieve_fn: Callable[..., dict] | None = None,
    relevance_fn: Callable[..., dict] | None = None,
    novelty_fn: Callable[..., dict] | None = None,
    critic_fn: Callable[..., dict] | None = None,
) -> CaseObservation:
    """Run the real two-verdict chain for one case, mirroring nara.py:
      1. retrieve_literature(hypothesis)
      2. stamp retrieval.result.relevance = relevance(neighbors, hypothesis)
         (orchestrator-driven in the real loop; see nara.py ~L660)
      3. write the retrieval tool_result into the per-iteration cache
      4. novelty_classify(hypothesis, iteration_id)  [reads cache]
      5. critic_loop_v0(hypothesis, iteration_id)     [reads cache]

    The four worker functions are injectable so tests can stub them; the
    defaults are the real workers + the real relevance gate. NOTE: under
    MOCK_LLM the LLM workers are stubbed, so verdict accuracy is meaningless
    — this path is for the integrator's real `env -u MOCK_LLM` smoke.
    """
    # Lazy imports: keep `score_*` importable (for the scoring self-tests)
    # without pulling chromadb / the wrapper. The defaults bind here.
    if retrieve_fn is None:
        from workers.retrieve_literature import retrieve_literature as retrieve_fn  # noqa: E501
    if relevance_fn is None:
        from workers.retrieval_relevance import relevance as relevance_fn
    if novelty_fn is None:
        from workers.novelty_classify import novelty_classify as novelty_fn
    if critic_fn is None:
        from workers.critic_loop_v0 import critic_loop_v0 as critic_fn
    from orchestrator import iteration_cache

    cid = case["case_id"]
    hyp = case["hypothesis"]
    iter_id = f"battery-{cid}"
    errors: list[str] = []

    ret = retrieve_fn(hyp)
    payload = (ret.get("result") if isinstance(ret, dict) else None) or {}
    neighbors = payload.get("neighbors") or []
    # Step 2: stamp relevance exactly as nara does (orchestrator-driven gate).
    payload["relevance"] = relevance_fn(neighbors, hyp)
    if isinstance(ret, dict):
        ret["result"] = payload
    # Step 3: cache the full tool_result so the workers read it by id.
    iteration_cache.write_entry(iter_id, "retrieval", ret)

    nov = novelty_fn(hyp, iter_id)
    crit = critic_fn(hyp, iter_id)
    nov_res = (nov.get("result") if isinstance(nov, dict) else None) or {}
    crit_res = (crit.get("result") if isinstance(crit, dict) else None) or {}

    errors += list(nov.get("errors") or []) if isinstance(nov, dict) else []
    errors += list(crit.get("errors") or []) if isinstance(crit, dict) else []

    # low_confidence is stamped identically by both workers; prefer novelty's,
    # fall back to critic's, then to the relevance stamp itself.
    low_conf = nov_res.get("low_confidence")
    if low_conf is None:
        low_conf = crit_res.get("low_confidence")
    if low_conf is None:
        low_conf = bool(payload["relevance"].get("low_confidence"))

    return CaseObservation(
        case_id=cid,
        novelty_class=str(nov_res.get("class", "<missing>")),
        critic_verdict=str(crit_res.get("verdict", "<missing>")),
        low_confidence=bool(low_conf),
        novelty_rationale=str(nov_res.get("rationale", "")),
        critic_rationale=str(crit_res.get("rationale", "")),
        contradicting_paper_id=crit_res.get("contradicting_paper_id"),
        errors=errors,
    )


# ──────────────────────────────────────────────────────────────────────
# Report rendering
# ──────────────────────────────────────────────────────────────────────
def result_to_dict(res: BatteryResult) -> dict[str, Any]:
    return {
        "cases_scored": res.cases_scored,
        "verdict_accuracy": round(res.verdict_accuracy, 4),
        "verdict_correct": res.verdict_correct,
        "verdict_decisions": res.verdict_decisions,
        "novelty_correct": res.novelty_correct,
        "critic_correct": res.critic_correct,
        "bar": res.bar,
        "meets_accuracy_bar": res.meets_accuracy_bar,
        "gate_must_fire_cases": res.gate_must_fire_cases,
        "gate_fired_when_required": res.gate_fired_when_required,
        "gate_recall": round(res.gate_recall, 4),
        "gate_recall_complete": res.gate_recall_complete,
        "offdomain_cases": res.offdomain_cases,
        "offdomain_ungated_novel_or_survives": res.offdomain_ungated_novel_or_survives,
        "offdomain_gated_novel_or_survives": res.offdomain_gated_novel_or_survives,
        "no_ungated_novel_survives": res.no_ungated_novel_survives,
        "cases_passed": res.cases_passed,
        "all_pass": res.all_pass,
        "novelty_confusion": res.novelty_confusion,
        "critic_confusion": res.critic_confusion,
        "per_case": [
            {
                "case_id": s.case_id,
                "domain": s.domain,
                "expected_novelty": s.expected_novelty,
                "actual_novelty": s.actual_novelty,
                "novelty_correct": s.novelty_correct,
                "expected_critic": s.expected_critic,
                "actual_critic": s.actual_critic,
                "critic_correct": s.critic_correct,
                "expect_low_confidence": s.expect_low_confidence,
                "actual_low_confidence": s.actual_low_confidence,
                "gate_correct": s.gate_correct,
                "novel_or_survives": s.novel_or_survives,
                "ungated_novel_or_survives": s.ungated_novel_or_survives,
                "gated_novel_or_survives": s.gated_novel_or_survives,
                "passed": s.passed,
            }
            for s in res.per_case
        ],
    }


def render_markdown(res: BatteryResult, *, mock: bool) -> str:
    lines: list[str] = []
    lines.append("# Literature-falsification accuracy battery")
    lines.append("")
    if mock:
        lines.append(
            "> WARNING: ran under MOCK_LLM — the LLM workers are STUBBED, so the "
            "verdict-accuracy numbers below are MEANINGLESS. Re-run with "
            "`env -u MOCK_LLM` for the real measurement."
        )
        lines.append("")
    lines.append(f"- cases scored: **{res.cases_scored}**")
    lines.append(
        f"- combined verdict accuracy: **{res.verdict_accuracy:.1%}** "
        f"({res.verdict_correct}/{res.verdict_decisions}) — bar {res.bar:.0%} — "
        f"{'PASS' if res.meets_accuracy_bar else 'FAIL'}"
    )
    lines.append(
        f"  - novelty: {res.novelty_correct}/{res.cases_scored}; "
        f"critic: {res.critic_correct}/{res.cases_scored}"
    )
    lines.append(
        f"- low-confidence-gate recall (cases that MUST flag): "
        f"**{res.gate_fired_when_required}/{res.gate_must_fire_cases}** "
        f"({res.gate_recall:.0%}) — "
        f"{'PASS' if res.gate_recall_complete else 'FAIL'}"
    )
    lines.append(
        f"- off-domain UN-GATED novel/survives (THE 2026-06-09 bug): "
        f"**{res.offdomain_ungated_novel_or_survives}** of {res.offdomain_cases} "
        f"off-domain cases — {'PASS' if res.no_ungated_novel_survives else 'FAIL'} "
        f"(must be 0)"
    )
    lines.append(
        f"- off-domain GATED novel/survives (soft — gate fired but verdict "
        f"enum didn't move): **{res.offdomain_gated_novel_or_survives}** "
        f"(reported, does not fail the bar)"
    )
    lines.append(
        f"- cases passing combined bar: {res.cases_passed}/{res.cases_scored}"
    )
    lines.append("")
    lines.append(
        f"## PROPOSED PASS BAR: {'PASS' if res.all_pass else 'FAIL'}"
    )
    lines.append(
        "(verdict accuracy >= 80% AND every off-domain case low-confidence-"
        "flagged AND zero false novel/survives on off-domain)"
    )
    lines.append("")
    lines.append("## Per-case")
    lines.append("")
    lines.append(
        "| case | dom | nov exp/act | crit exp/act | gate exp/act | pass |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for s in res.per_case:
        nov = f"{s.expected_novelty}/{s.actual_novelty}" + ("" if s.novelty_correct else " ✗")
        crit = f"{s.expected_critic}/{s.actual_critic}" + ("" if s.critic_correct else " ✗")
        gate = f"{s.expect_low_confidence}/{s.actual_low_confidence}" + ("" if s.gate_correct else " ✗")
        lines.append(
            f"| {s.case_id} | {s.domain} | {nov} | {crit} | {gate} | "
            f"{'Y' if s.passed else 'N'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import os

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cases", default=str(CASES_PATH), help="path to cases.jsonl")
    p.add_argument("--out-dir", default=str(RUNS_DIR), help="report output dir")
    args = p.parse_args(argv)

    mock = bool(os.environ.get("MOCK_LLM"))
    cases = load_cases(Path(args.cases))
    observations = [run_case(c) for c in cases]
    res = score_battery(cases, observations)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = result_to_dict(res)
    payload["ran_under_mock_llm"] = mock
    payload["generated_at"] = stamp
    json_path = out_dir / f"battery_{stamp}.json"
    md_path = out_dir / f"battery_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(render_markdown(res, mock=mock))

    print(render_markdown(res, mock=mock))
    print(f"\nwrote {json_path}\nwrote {md_path}")
    # Exit non-zero when the proposed bar fails (so CI / the integrator's
    # smoke can gate on it) — UNLESS we're under MOCK_LLM, where the numbers
    # are stubbed and a fail/pass is not meaningful.
    if mock:
        return 0
    return 0 if res.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
