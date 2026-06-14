#!/usr/bin/env python3
"""D-052 isolated topicality-instrument boundary probe.

Answers the D-052 question: *is the independent ADVERSARIAL REFUTE-framed
topicality skeptic (R0b) the right instrument?* — by comparing topicality-
judge VARIANTS in ISOLATION. The judges are called DIRECTLY on the labelled
battery cases (`experiments/lit_falsification_battery/cases.jsonl`), with NO
retrieval / novelty / critic chain attached.

The isolation is what makes the result a valid hard gate on promotion
(D-052 method): the topicality judgment is an isolated function, so a variant
that condemns ZERO on-domain case *in isolation* CANNOT over-gate in the full
battery (the gate cannot fire when the judge says on/unsure); and whether a
variant catches the primary's off-domain misses is directly observable here.

FOUR variants, each -> "on" | "off" | "unsure" | None for a hypothesis string:
  1. primary-gemma   — `topicality._primary_check` (the apparatus's own neutral
     Gemma judge; the BASELINE the others must add marginal value over).
  2. adversarial-qwen — `topicality_skeptic.attack_topicality` VERBATIM (the
     CURRENT R0b, default backend vllm-qwen).
  3. positive-id-qwen — candidate B: a harness-owned prompt that condemns ONLY
     on positive ID of an off-domain subject, backend vllm-qwen.
  4. neutral-qwen     — control: the primary NEUTRAL prompt on vllm-qwen —
     isolates framing (adversarial vs neutral) from backend (Gemma vs Qwen).

Scoring is a PURE function of (per_case observations, cases) — `score_probe`
takes NO model and is exercised by the unit tests with canned data. The
model-touching half (`run_probe`) is the integrator's real `env -u MOCK_LLM`
run; under MOCK_LLM every variant returns None (mirrors the modules), so the
boundary cannot be measured and the harness says so and exits.

NEVER coerced (inviolate rule 4): an unstable boundary label is a FAIL, not a
"close enough"; an over-gated on-domain case disqualifies a variant. We do not
recode mismatches.

Real entrypoint (NOT a unit-test concern):
    env -u MOCK_LLM ./.venv-chroma/bin/python -m experiments.topicality_instrument.boundary_probe --repeats 3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.lit_falsification_battery.battery import CASES_PATH, load_cases  # noqa: E402
from orchestrator.topicality import _SYSTEM as PRIMARY_SYSTEM  # noqa: E402
from orchestrator.topicality import _primary_check  # noqa: E402
from orchestrator.topicality_skeptic import attack_topicality  # noqa: E402
from agent_wrapper.wrapper import call_sync  # noqa: E402

RUNS_DIR = Path(__file__).resolve().parent / "runs"
CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

# Match the skeptic's token budget verbatim: Qwen burns tokens on a hidden
# reasoning channel and starves at 512/2048 (D-044); 3072 is the working figure.
PROBE_MAX_TOKENS = 3072

VARIANTS = ("primary-gemma", "adversarial-qwen", "positive-id-qwen", "neutral-qwen")
NON_PRIMARY_VARIANTS = ("adversarial-qwen", "positive-id-qwen", "neutral-qwen")

# Candidate B (positive-identification reframe): condemn ONLY on positive ID of
# an off-domain subject, never on failure-to-defend-in-domain. Harness-owned —
# this prompt enters orchestrator/topicality_skeptic._SYSTEM only on a Phase-2
# battery PASS (D-052). Used VERBATIM.
POSITIVE_ID_SYSTEM = (
    "You identify the PRIMARY tested subject of a research claim for a "
    "game-theory research apparatus. Name the single primary quantity the "
    "claim is about and the evidence that would test it. Output STRICT JSON, "
    "nothing else: {\"domain\": \"on\"|\"off\"|\"unsure\", \"primary_subject\": "
    "\"<one phrase>\", \"reason\": \"<one sentence>\"}. Output \"off\" ONLY IF "
    "the primary subject is positively one of these off-domain fields: "
    "single-model output properties in isolation (uncertainty / semantic "
    "entropy / calibration / hallucination detection), databases / indexing, "
    "distributed systems / consensus, ML training or serving infrastructure, "
    "code quality / software engineering, web frameworks, or retrieval / "
    "chunk-overlap quality. In every other case output \"on\" — including "
    "claims about strategic interaction among decision-makers (humans, "
    "animals, or machines): equilibrium and solution concepts, repeated-game "
    "cooperation and the folk theorem, bargaining, evolutionary stability, "
    "learning in games. Do NOT output \"off\" merely because a claim is "
    "unusual, novel, hard to place, or lacks AI framing — novelty is not "
    "off-domain. If you genuinely cannot identify the primary subject, output "
    "\"unsure\"."
)


# ──────────────────────────────────────────────────────────────────────
# Model-touching half — one judge call per (variant, case, repeat).
# Mirrors attack_topicality's call+parse EXACTLY. Under MOCK_LLM every
# variant returns None (signal unavailable), like the real modules.
# ──────────────────────────────────────────────────────────────────────
def _judge(system: str, text: str) -> Optional[str]:
    """One judge call on vllm-qwen -> "on" | "off" | "unsure" | None.

    Replicates orchestrator/topicality_skeptic.attack_topicality's call +
    parse verbatim (same backend, token budget, fail-open contract): None
    under MOCK_LLM / empty input / wrapper failure / empty completion; an
    unparseable-but-responsive completion -> "unsure"; an off-enum domain
    -> "unsure". Only the literal "off" condemns.
    """
    if os.environ.get("MOCK_LLM"):
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        record = call_sync(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": text.strip()},
            ],
            temperature=0.0,
            max_tokens=PROBE_MAX_TOKENS,
            caller_tag="topicality_probe",
            backend="vllm-qwen",
            log_path=CALLS_LOG_PATH,
        )
    except Exception:
        return None

    content = record.get("completion") if isinstance(record, dict) else None
    if not isinstance(content, str) or not content.strip():
        return None
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return "unsure"
    try:
        payload: Any = json.loads(m.group(0))
    except json.JSONDecodeError:
        return "unsure"
    domain = payload.get("domain") if isinstance(payload, dict) else None
    if domain not in ("on", "off", "unsure"):
        return "unsure"
    return domain


def _variant_call(variant: str, text: str) -> Optional[str]:
    """Dispatch one variant on one hypothesis. Each reuses an existing judge."""
    if variant == "primary-gemma":
        return _primary_check(text)          # apparatus's own neutral Gemma judge
    if variant == "adversarial-qwen":
        return attack_topicality(text)       # the CURRENT R0b, verbatim
    if variant == "positive-id-qwen":
        return _judge(POSITIVE_ID_SYSTEM, text)
    if variant == "neutral-qwen":
        return _judge(PRIMARY_SYSTEM, text)  # primary prompt, on qwen (control)
    raise ValueError(f"unknown variant {variant!r}")


def _modal(labels: list[Optional[str]]) -> Optional[str]:
    """Most common label; ties broken by first-seen order. PURE."""
    counts = Counter(labels)
    if not counts:
        return None
    best = max(counts.values())
    for lab in labels:               # first-seen tie-break
        if counts[lab] == best:
            return lab
    return None


def run_probe(cases: list[dict[str, Any]], repeats: int) -> dict[str, dict]:
    """Call every variant `repeats` times on every case. MODEL-TOUCHING.

    Returns per_case: {case_id: {"domain": <label>,
        <variant>: {"labels": [...], "modal": <modal>, "stable": <all-equal>}}}.
    `stable` is True iff all `repeats` labels are identical (a None among them
    breaks stability too — an unmeasurable boundary is not stable)."""
    per_case: dict[str, dict] = {}
    for c in cases:
        cid = c["case_id"]
        hyp = c["hypothesis"]
        row: dict[str, Any] = {"domain": c.get("domain", "on")}
        for v in VARIANTS:
            labels = [_variant_call(v, hyp) for _ in range(repeats)]
            row[v] = {
                "labels": labels,
                "modal": _modal(labels),
                "stable": len(set(labels)) == 1,
            }
        per_case[cid] = row
    return per_case


# ──────────────────────────────────────────────────────────────────────
# Pure scoring — the pre-registered D-052 Phase-1 rule. NO model, NO I/O.
# ──────────────────────────────────────────────────────────────────────
def score_probe(per_case: dict[str, dict], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the D-052 pre-registered rule to probe observations. PURE.

    Boundary set (from the labels):
      * must_catch        = every domain:off case.
      * must_not_condemn  = every domain:on case that is NOT a `nonsense_*`
        probe (nonsense is informational — neither a catch nor a condemn).
    primary_misses = off cases whose `primary-gemma` modal is NOT "off" — the
    only cases a skeptic could add marginal value on.

    A non-primary variant QUALIFIES iff ALL three pre-registered clauses hold:
      (1) marginal catch — its modal is "off" on EVERY primary_miss
          (vacuously True if primary_misses is empty);
      (2) zero over-gating — its modal is "off" on ZERO must_not_condemn case;
      (3) stable — every boundary label (must_catch + must_not_condemn) is
          identical across all repeats.
    No clause is coerced: a single over-gated case or a single unstable
    boundary disqualifies (rule 4).

    recommended_outcome:
      * primary catches all off (primary_misses empty) -> "A (retire ...)" —
        the marginal-catch clause is vacuous, so no skeptic adds value.
      * else if ANY variant qualifies -> "PAUSE for Phase-2 ...".
      * else -> "A+C (retire the gate + advisory non-gating flag)".
    """
    domain_of = {c["case_id"]: c.get("domain", "on") for c in cases}
    must_catch = [cid for cid in per_case if domain_of.get(cid) == "off"]
    must_not_condemn = [
        cid for cid in per_case
        if domain_of.get(cid) == "on" and not cid.startswith("nonsense")
    ]
    boundary = must_catch + must_not_condemn

    def _modal_of(cid: str, variant: str) -> Optional[str]:
        return per_case[cid][variant]["modal"]

    def _stable_of(cid: str, variant: str) -> bool:
        return bool(per_case[cid][variant]["stable"])

    primary_misses = [cid for cid in must_catch if _modal_of(cid, "primary-gemma") != "off"]

    per_variant: dict[str, dict] = {}
    for v in NON_PRIMARY_VARIANTS:
        covers_primary_misses = all(_modal_of(cid, v) == "off" for cid in primary_misses)
        over_gated = [cid for cid in must_not_condemn if _modal_of(cid, v) == "off"]
        unstable_boundary = [cid for cid in boundary if not _stable_of(cid, v)]
        qualifies = (covers_primary_misses
                     and len(over_gated) == 0
                     and len(unstable_boundary) == 0)
        per_variant[v] = {
            "covers_primary_misses": covers_primary_misses,
            "over_gated": over_gated,
            "unstable_boundary": unstable_boundary,
            "qualifies": qualifies,
        }

    if not primary_misses:
        recommended_outcome = (
            "A (retire; primary catches all off-domain — no marginal value "
            "for any skeptic)"
        )
    elif any(per_variant[v]["qualifies"] for v in NON_PRIMARY_VARIANTS):
        winners = [v for v in NON_PRIMARY_VARIANTS if per_variant[v]["qualifies"]]
        recommended_outcome = (
            f"PAUSE for Phase-2 (variant {', '.join(winners)} qualify in isolation)"
        )
    else:
        recommended_outcome = "A+C (retire the gate + advisory non-gating flag)"

    return {
        "must_catch": must_catch,
        "must_not_condemn": must_not_condemn,
        "primary_misses": primary_misses,
        "per_variant": per_variant,
        "recommended_outcome": recommended_outcome,
    }


# ──────────────────────────────────────────────────────────────────────
# Report rendering
# ──────────────────────────────────────────────────────────────────────
def _cell(entry: dict) -> str:
    """A variant cell: the modal label, with a trailing * when unstable."""
    modal = entry.get("modal")
    txt = "-" if modal is None else str(modal)
    return txt + ("" if entry.get("stable") else "*")


def render_markdown(per_case: dict[str, dict], summary: dict[str, Any], *, mock: bool) -> str:
    lines: list[str] = ["# D-052 topicality-instrument boundary probe", ""]
    if mock:
        lines += [
            "> WARNING: ran under MOCK_LLM — every variant returns None, so the "
            "boundary cannot be measured. Re-run with `env -u MOCK_LLM`.",
            "",
        ]
    lines += [
        "| case | domain | primary | adversarial | positive-id | neutral |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for cid, row in per_case.items():
        lines.append(
            f"| {cid} | {row['domain']} | {_cell(row['primary-gemma'])} "
            f"| {_cell(row['adversarial-qwen'])} | {_cell(row['positive-id-qwen'])} "
            f"| {_cell(row['neutral-qwen'])} |"
        )
    lines += ["", "(* = label NOT stable across all repeats)", ""]
    lines += ["## Pre-registered rule (D-052 Phase-1)", ""]
    lines.append(f"- must-catch (domain:off): **{len(summary['must_catch'])}**")
    lines.append(
        f"- must-not-condemn (genuine domain:on): "
        f"**{len(summary['must_not_condemn'])}**"
    )
    pm = summary["primary_misses"]
    lines.append(
        f"- primary-gemma MISSES (off cases primary did NOT catch): "
        f"**{len(pm)}**" + (f" ({', '.join(pm)})" if pm else " — primary catches all")
    )
    lines.append("")
    lines.append("| variant | covers primary misses | over-gated | unstable boundary | QUALIFIES |")
    lines.append("| --- | --- | --- | --- | --- |")
    for v in NON_PRIMARY_VARIANTS:
        pv = summary["per_variant"][v]
        og = pv["over_gated"]
        ub = pv["unstable_boundary"]
        lines.append(
            f"| {v} | {pv['covers_primary_misses']} "
            f"| {len(og)}{(' (' + ', '.join(og) + ')') if og else ''} "
            f"| {len(ub)}{(' (' + ', '.join(ub) + ')') if ub else ''} "
            f"| {'YES' if pv['qualifies'] else 'no'} |"
        )
    lines += ["", f"## RECOMMENDED OUTCOME: {summary['recommended_outcome']}", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cases", default=str(CASES_PATH), help="path to cases.jsonl")
    p.add_argument("--repeats", type=int, default=3, help="judge calls per variant per case")
    p.add_argument("--out-dir", default=str(RUNS_DIR), help="report output dir")
    p.add_argument("--only", default=None,
                   help="optional comma-separated case_ids to restrict the probe to")
    args = p.parse_args(argv)

    mock = bool(os.environ.get("MOCK_LLM"))
    if mock:
        print("WARNING: MOCK_LLM is set — every topicality variant returns None, "
              "so the boundary cannot be measured. Re-run with `env -u MOCK_LLM`.",
              file=sys.stderr)
        return 0

    cases = load_cases(Path(args.cases))
    if args.only:
        wanted = {cid.strip() for cid in args.only.split(",") if cid.strip()}
        cases = [c for c in cases if c["case_id"] in wanted]

    per_case = run_probe(cases, args.repeats)
    summary = score_probe(per_case, cases)
    md = render_markdown(per_case, summary, mock=mock)
    print(md)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"probe_{stamp}.json"
    md_path = out_dir / f"probe_{stamp}.md"
    json_path.write_text(json.dumps(
        {"per_case": per_case, "summary": summary, "repeats": args.repeats,
         "ran_under_mock_llm": mock, "generated_at": stamp},
        indent=2))
    md_path.write_text(md)
    print(f"\nwrote {json_path}\nwrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
