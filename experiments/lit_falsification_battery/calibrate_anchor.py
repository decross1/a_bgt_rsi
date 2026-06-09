#!/usr/bin/env python3
"""Anchor-cosine distribution report — embedder-only, no LLM workers.

Computes the domain-anchor cosine (orchestrator.domain_anchor.anchor_cosine,
Limb A's module) for:
  (a) every labelled hypothesis in cases.jsonl (on/off domain labels), and
  (b) every historical run_state/iteration_cache/iter-*/hypothesis.json
      result text (~45 iterations, unlabelled except the known FASE bug).

Writes a JSON + markdown distribution report to runs/ and prints the
CANDIDATE threshold rule (a proposal for the human/integrator — NOT applied
anywhere by this script):

    ANCHOR_LOW        = midpoint(max off-domain A, min on-domain A)
                        ONLY if the gap (min_on - max_off) >= 0.05;
                        otherwise: no clean threshold — reported honestly.
    ANCHOR_BORDERLINE = min on-domain A

The cases.jsonl labels were authored BEFORE any anchor threshold existed
(P-009 anti-overfit), so calibrating against them is not circular.

Real run (integrator, serial):
    env -u MOCK_LLM ./.venv-chroma/bin/python -m experiments.lit_falsification_battery.calibrate_anchor
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
CACHE_ROOT = REPO_ROOT / "run_state" / "iteration_cache"

# The one historical iteration with a defensible off-domain label: the
# 2026-06-09 FASE false positive that motivated the relevance gate.
KNOWN_OFF_ITERATIONS = frozenset({"iter-2026-06-09-001"})

MIN_GAP = 0.05  # required separation for a clean ANCHOR_LOW proposal


def _fmt(v) -> str:
    return f"{v:.4f}" if isinstance(v, float) else "-"


def main() -> int:
    try:
        from orchestrator.domain_anchor import anchor_cosine
    except ImportError as exc:
        print(
            "calibrate_anchor: orchestrator.domain_anchor is not available "
            f"({exc}).\nThis script depends on Limb A's domain-anchor module; "
            "run it after that module is merged.",
            file=sys.stderr,
        )
        return 2

    # (a) labelled battery cases
    labelled: list[dict] = []
    with open(CASES_PATH) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            labelled.append({
                "id": c["case_id"],
                "domain": c.get("domain", "on"),
                "anchor_cosine": float(anchor_cosine(c["hypothesis"])),
            })

    # (b) historical iteration-cache hypotheses (battery-* dirs excluded —
    # they duplicate the labelled cases above).
    historical: list[dict] = []
    for d in sorted(CACHE_ROOT.glob("iter-*")):
        hyp_path = d / "hypothesis.json"
        if not hyp_path.exists():
            continue
        try:
            text = (json.loads(hyp_path.read_text()).get("result") or {}).get("text")
        except (json.JSONDecodeError, OSError) as exc:
            historical.append({"id": d.name, "error": repr(exc)})
            continue
        if not text:
            continue
        historical.append({
            "id": d.name,
            "known_off_domain": d.name in KNOWN_OFF_ITERATIONS,
            "anchor_cosine": float(anchor_cosine(text)),
        })

    on_vals = sorted(r["anchor_cosine"] for r in labelled if r["domain"] == "on")
    off_vals = sorted(r["anchor_cosine"] for r in labelled if r["domain"] == "off")

    rule: dict = {"min_gap_required": MIN_GAP}
    if on_vals and off_vals:
        max_off, min_on = max(off_vals), min(on_vals)
        gap = min_on - max_off
        rule.update({
            "max_off_domain": max_off,
            "min_on_domain": min_on,
            "gap": round(gap, 4),
            "anchor_borderline": min_on,
        })
        if gap >= MIN_GAP:
            rule["anchor_low"] = round((max_off + min_on) / 2.0, 4)
        else:
            rule["anchor_low"] = None
            rule["note"] = (
                f"NO clean threshold: gap {gap:.4f} < {MIN_GAP} — the anchor "
                "cosine does not separate the labelled sets; do not ship "
                "ANCHOR_LOW from this data."
            )
    else:
        rule["note"] = "labelled set lacks on- or off-domain values"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    import os
    payload = {
        "generated_at": stamp,
        "ran_under_mock_llm": bool(os.environ.get("MOCK_LLM")),
        "labelled_cases": labelled,
        "historical_iterations": historical,
        "candidate_threshold_rule": rule,
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RUNS_DIR / f"anchor_calibration_{stamp}.json"

    lines = ["# Anchor-cosine calibration report", ""]
    if payload["ran_under_mock_llm"]:
        lines += ["> WARNING: ran under MOCK_LLM — embedder stubbed; values "
                  "are meaningless. Re-run with `env -u MOCK_LLM`.", ""]
    lines.append(f"- labelled cases: {len(labelled)} "
                 f"(on={len(on_vals)}, off={len(off_vals)})")
    lines.append(f"- historical iterations: {len(historical)}")
    lines.append("")
    lines.append("## Labelled distribution")
    lines.append("")
    lines.append("| case | domain | anchor_cosine |")
    lines.append("| --- | --- | --- |")
    for r in sorted(labelled, key=lambda r: r["anchor_cosine"]):
        lines.append(f"| {r['id']} | {r['domain']} | {_fmt(r['anchor_cosine'])} |")
    lines.append("")
    lines.append("## Historical iterations (unlabelled; FASE bug marked)")
    lines.append("")
    lines.append("| iteration | known_off | anchor_cosine |")
    lines.append("| --- | --- | --- |")
    for r in historical:
        if "error" in r:
            lines.append(f"| {r['id']} | - | unreadable: {r['error']} |")
        else:
            lines.append(f"| {r['id']} | {r['known_off_domain']} "
                         f"| {_fmt(r['anchor_cosine'])} |")
    lines.append("")
    lines.append("## Candidate threshold rule (PROPOSAL, not applied)")
    lines.append("")
    lines.append(f"```json\n{json.dumps(rule, indent=2)}\n```")
    lines.append("")
    md = "\n".join(lines)

    md_path = RUNS_DIR / f"anchor_calibration_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(md)
    print(md)
    print(f"\nwrote {json_path}\nwrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
