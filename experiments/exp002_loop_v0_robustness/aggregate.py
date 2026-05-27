#!/usr/bin/env python3
"""exp002 — aggregate results.jsonl into a per-topic verdict-distribution table.

Reads `results.jsonl`, groups by topic_label, computes:
  - verdict distribution (novelty class × critic verdict)
  - top-neighbor distribution (which doc_id dominated)
  - wall-clock distribution
  - hypothesis-text diversity

Writes `results.md` with one table per topic + a summary verdict.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean, stdev

EXP_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXP_DIR / "results.jsonl"
OUT_PATH = EXP_DIR / "results.md"


def _load_rows() -> list[dict]:
    if not RESULTS_PATH.exists():
        raise SystemExit(f"FATAL: {RESULTS_PATH} does not exist — run runner.py first")
    rows: list[dict] = []
    with open(RESULTS_PATH) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _per_topic_block(label: str, rows: list[dict]) -> str:
    n = len(rows)
    if n == 0:
        return f"## {label}\n\n(no rows)\n"

    spec = rows[0]
    diag = spec.get("diagnostic_role", "?")
    prior_n = spec.get("prior_novelty", "?")
    prior_v = spec.get("prior_verdict", "?")

    errors = [r for r in rows if "error" in r]
    ok = [r for r in rows if "error" not in r]

    novelty_dist = Counter(r.get("novelty_class") for r in ok)
    verdict_dist = Counter(r.get("critic_verdict") for r in ok)
    top_neighbor_dist = Counter(r.get("novelty_top_neighbor_id") for r in ok)
    contradicting_dist = Counter(r.get("critic_contradicting_paper_id") for r in ok)

    subagent_status_dist = Counter(r.get("critic_subagent_status") for r in ok)

    walls = [r.get("wall_s_total") for r in ok if isinstance(r.get("wall_s_total"), (int, float))]
    wall_mean = round(mean(walls), 1) if walls else None
    wall_sd = round(stdev(walls), 1) if len(walls) >= 2 else None

    # Hypothesis-text diversity: how many distinct chosen hypotheses?
    hyps = [r.get("hypothesis_text") or "" for r in ok]
    distinct_hyps = len(set(hyps))

    body = [f"## {label}", ""]
    body.append(f"- **Diagnostic role**: `{diag}`")
    body.append(f"- **Human priors**: novelty=`{prior_n}` / verdict=`{prior_v}`")
    body.append(f"- **n runs**: {n} (errors: {len(errors)}, ok: {len(ok)})")
    body.append(f"- **Wall-clock**: mean {wall_mean} s, sd {wall_sd} s" if walls else "- **Wall-clock**: n/a")
    body.append(f"- **Distinct chosen hypotheses**: {distinct_hyps}/{len(ok)}")
    body.append("")
    body.append("**Novelty class distribution**")
    body.append("")
    body.append("| class | count |")
    body.append("|---|---|")
    for cls, ct in novelty_dist.most_common():
        body.append(f"| `{cls}` | {ct} |")
    body.append("")
    body.append("**Critic verdict distribution**")
    body.append("")
    body.append("| verdict | count |")
    body.append("|---|---|")
    for v, ct in verdict_dist.most_common():
        body.append(f"| `{v}` | {ct} |")
    body.append("")
    body.append("**Critic sub-agent status distribution**")
    body.append("")
    body.append("| status | count |")
    body.append("|---|---|")
    for s, ct in subagent_status_dist.most_common():
        body.append(f"| `{s}` | {ct} |")
    body.append("")
    body.append("**Top-neighbor (novelty) distribution**")
    body.append("")
    body.append("| doc_id | count |")
    body.append("|---|---|")
    for d, ct in top_neighbor_dist.most_common():
        d_disp = d if d else "(null)"
        body.append(f"| `{d_disp}` | {ct} |")
    body.append("")
    if any(v for v in contradicting_dist if v):
        body.append("**Contradicting-paper (critic) distribution**")
        body.append("")
        body.append("| doc_id | count |")
        body.append("|---|---|")
        for d, ct in contradicting_dist.most_common():
            d_disp = d if d else "(null)"
            body.append(f"| `{d_disp}` | {ct} |")
        body.append("")
    body.append("**Chosen hypotheses (verbatim)**")
    body.append("")
    seen: set[str] = set()
    for i, h in enumerate(hyps, 1):
        truncated = h[:280] + ("…" if len(h) > 280 else "")
        marker = "  " if h not in seen else "↺ "
        seen.add(h)
        body.append(f"  {i}. {marker}{truncated}")
    body.append("")
    body.append("---")
    body.append("")
    return "\n".join(body)


def main() -> int:
    rows = _load_rows()
    # Group by topic_label.
    by_label: dict[str, list[dict]] = {}
    for r in rows:
        by_label.setdefault(r.get("topic_label", "?"), []).append(r)

    out = [
        "# exp002 — LOOP_V0 robustness battery on the three Phase-2 topics",
        "",
        "_Each topic re-run 5× with the chain's default sampling (no seed plumbing)._",
        f"_Total rows in `results.jsonl`: {len(rows)}._",
        "",
        f"Per-topic tables follow. The headline interpretation is in `notes.md` "
        f"(human-written, per CLAUDE.md inviolate rule #9).",
        "",
        "---",
        "",
    ]
    for label in sorted(by_label):
        out.append(_per_topic_block(label, by_label[label]))

    OUT_PATH.write_text("\n".join(out))
    print(f"Wrote {OUT_PATH} ({sum(len(v) for v in by_label.values())} rows across {len(by_label)} topics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
